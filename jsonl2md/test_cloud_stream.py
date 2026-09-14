"""The live stream: SSE parsed as the CLI parses it, one connection per session,
redialled from the last id, closed for good on a refusal. The server is local."""

import http.server
import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import cloud_inbox
import jsonl2md as relay
from cloud_inbox import Inbox, InboxState, SessionStream, parse_sse


class ParseTests(unittest.TestCase):
    def test_blocks_comments_and_multiline_data(self):
        raw = (": keepalive\n\n"
               "event: client_event\r\nid: 12\r\ndata: {\"a\":\r\ndata:  1}\r\n\r\n"
               "id: 13\n\n"
               "junk line\ndata: {\"b\":2}\n\n"
               "data: tail without blank line")
        blocks = list(parse_sse(raw.splitlines(keepends=True)))
        self.assertEqual(blocks[0], {"event": None, "id": None, "data": None, "comment": True})
        self.assertEqual(blocks[1], {"event": "client_event", "id": "12", "data": '{"a":\n 1}', "comment": False})
        self.assertEqual(blocks[2], {"event": None, "id": None, "data": '{"b":2}', "comment": False})
        self.assertEqual(len(blocks), 3)          # id-only block dropped; unterminated tail never delivered


class FakeStreamServer:
    """Scripted SSE responses: each connection takes the next script entry."""

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.requests = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                outer.requests.append({"path": self.path, "headers": dict(self.headers)})
                script = outer.scripts.pop(0) if outer.scripts else {"status": 404}
                status = script.get("status", 200)
                if status != 200:
                    body = json.dumps(script.get("body", {})).encode()
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                for frame in script.get("frames", []):
                    if isinstance(frame, (int, float)):
                        time.sleep(frame)
                        continue
                    data = frame.encode()
                    self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
                    self.wfile.flush()
                if script.get("hang"):
                    time.sleep(script["hang"])
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()

            def log_message(self, *args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def client_event(seq, text, uuid):
    payload = {"type": "assistant", "uuid": uuid, "message": {"role": "assistant", "content": [
        {"type": "text", "text": text}]}}
    return (f"event: client_event\nid: {seq}\ndata: " +
            json.dumps({"sequence_num": str(seq), "event_type": "assistant", "created_at": "1970-01-01T00:00:05Z",
                        "payload": payload}) + "\n\n")


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.state = InboxState(os.path.join(self.tmp.name, "inbox.json"))
        self.log, self.handled = [], []
        patches = [patch.object(relay, "_cloud_token", return_value="tok"),
                   patch.object(relay, "_org_uuid", return_value="org")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.inbox = Inbox(state=self.state, log=self.log.append, clock=lambda: 10)
        self.inbox.handle = lambda cse, title, events: self.handled.append((cse, [e["sequence_num"] for e in events])) or 0

    def stream(self, server, cursor="5", **kw):
        self.state.set_cursor("cse_S", cursor)
        st = SessionStream(self.inbox, "cse_S", "Sky", base_url=server.base, liveness=1,
                           connect_timeout=2, backoff_max=1, **kw)
        return st

    def test_events_are_handled_and_the_id_is_the_cursor(self):
        server = FakeStreamServer([{"frames": [": hello\n\n", client_event(6, "a", "u6"),
                                               client_event(7, "b", "u7"), "event: catch_up_truncated\ndata: {}\n\n"]},
                                   {"status": 404}])
        self.addCleanup(server.close)
        st = self.stream(server)
        st.start(); st.join(timeout=5)
        self.assertEqual(self.handled, [("cse_S", ["6"]), ("cse_S", ["7"])])
        self.assertEqual(self.state.cursor("cse_S"), "7")
        self.assertEqual(json.load(open(self.state.path))["cse_S"]["cursor"], "7")
        self.assertTrue(any("skipped a gap" in l for l in self.log))
        self.assertEqual(st.closed_reason, "HTTP 404")
        first, second = server.requests
        self.assertEqual(first["path"], "/v1/code/sessions/cse_S/events/stream?from_sequence_num=5")
        self.assertEqual(first["headers"]["Last-Event-ID"], "5")
        self.assertEqual(first["headers"]["Accept"], "text/event-stream")
        self.assertEqual(first["headers"]["Authorization"], "Bearer tok")
        self.assertEqual(first["headers"]["x-organization-uuid"], "org")
        self.assertEqual(second["path"], "/v1/code/sessions/cse_S/events/stream?from_sequence_num=7")

    def test_already_seen_sequence_is_skipped(self):
        server = FakeStreamServer([{"frames": [client_event(5, "old", "u5"), client_event(6, "new", "u6")]},
                                   {"status": 403}])
        self.addCleanup(server.close)
        st = self.stream(server)
        st.start(); st.join(timeout=5)
        self.assertEqual(self.handled, [("cse_S", ["6"])])
        self.assertEqual(st.closed_reason, "HTTP 403")

    def test_silence_beyond_liveness_redials(self):
        server = FakeStreamServer([{"frames": [client_event(6, "a", "u6")], "hang": 3},
                                   {"status": 404}])
        self.addCleanup(server.close)
        st = self.stream(server)
        t0 = time.time()
        st.start(); st.join(timeout=10)
        self.assertLess(time.time() - t0, 8)
        self.assertEqual(len(server.requests), 2)
        self.assertTrue(any("stream dropped" in l for l in self.log))

    def test_401_refreshes_the_grant_once(self):
        server = FakeStreamServer([{"status": 401}, {"frames": [client_event(6, "a", "u6")]}, {"status": 404}])
        self.addCleanup(server.close)
        relay._DESKTOP_GRANT["value"] = ("stale", "")
        st = self.stream(server)
        st.start(); st.join(timeout=5)
        self.assertNotIn("value", relay._DESKTOP_GRANT)      # memo cleared for the retry
        self.assertEqual(self.handled, [("cse_S", ["6"])])
        self.assertEqual(len(server.requests), 3)

    def test_first_event_cursor_sends_no_resume(self):
        server = FakeStreamServer([{"frames": [client_event(1, "first", "u1")]}, {"status": 404}])
        self.addCleanup(server.close)
        st = self.stream(server, cursor="0")
        st.start(); st.join(timeout=5)
        self.assertEqual(server.requests[0]["path"], "/v1/code/sessions/cse_S/events/stream")
        self.assertNotIn("Last-Event-ID", server.requests[0]["headers"])
        self.assertEqual(self.handled, [("cse_S", ["1"])])


class FakeStream:
    instances = []

    def __init__(self, inbox, cse_id, title):
        self.cse_id, self.title = cse_id, title
        self.alive, self.stopped, self.closed_reason = True, False, None
        FakeStream.instances.append(self)

    def start(self):
        pass

    def is_alive(self):
        return self.alive

    def stop(self):
        self.stopped = True


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.state = InboxState(os.path.join(self.tmp.name, "inbox.json"))
        self.log = []
        FakeStream.instances.clear()
        self.sessions = [{"id": "cse_A", "title": "A", "environment_kind": "anthropic_cloud", "status": "active",
                          "worker_status": "idle", "created_at": "1970-01-01T00:00:00Z"}]
        self.heads = {"cse_A": "4"}
        for p in [patch.object(relay, "cloud_sessions", side_effect=lambda force=False, **kw: self.sessions),
                  patch.object(relay, "cloud_head_sequence", side_effect=lambda cse: self.heads.get(cse))]:
            p.start()
            self.addCleanup(p.stop)
        self.inbox = Inbox(state=self.state, log=self.log.append, clock=lambda: 100000)

    def test_streams_follow_the_roster(self):
        self.assertEqual(self.inbox.reconcile_streams(FakeStream), 1)
        self.assertEqual(self.state.cursor("cse_A"), "4")
        self.assertEqual([s.cse_id for s in FakeStream.instances], ["cse_A"])
        self.sessions.append({"id": "cse_B", "title": "B", "environment_kind": "anthropic_cloud", "status": "active",
                              "worker_status": "running", "created_at": "1970-01-02T03:46:00Z"})   # 40 s old
        self.assertEqual(self.inbox.reconcile_streams(FakeStream), 2)
        self.assertEqual(self.state.cursor("cse_B"), "0")
        del self.sessions[0]
        self.assertEqual(self.inbox.reconcile_streams(FakeStream), 1)
        self.assertTrue(FakeStream.instances[0].stopped)
        self.assertNotIn("cse_A", self.state.data)

    def test_a_dead_stream_is_reopened_a_refused_one_is_not(self):
        self.inbox.reconcile_streams(FakeStream)
        FakeStream.instances[0].alive = False
        self.inbox.reconcile_streams(FakeStream)
        self.assertEqual(len(FakeStream.instances), 2)
        FakeStream.instances[1].alive, FakeStream.instances[1].closed_reason = False, "HTTP 404"
        self.assertEqual(self.inbox.reconcile_streams(FakeStream), 0)
        self.assertEqual(len(FakeStream.instances), 2)

    def test_roster_failure_keeps_streams(self):
        self.inbox.reconcile_streams(FakeStream)
        with patch.object(relay, "cloud_sessions", side_effect=OSError("offline")):
            self.assertEqual(self.inbox.reconcile_streams(FakeStream), 1)
        self.assertFalse(FakeStream.instances[0].stopped)


if __name__ == "__main__":
    unittest.main()
