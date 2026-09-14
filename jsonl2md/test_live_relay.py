"""Transport and deferred-delivery regressions; all receivers are isolated sockets."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import socket
import struct
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import jsonl2md as relay
from live_relay import (DeliveryError, cloud_envelope, cloud_ids, send_claude, send_cloud,
                        send_codex)
import http.server


def receive(sock):
    def exact(count):
        data = b""
        while len(data) < count:
            part = sock.recv(count - len(data))
            if not part:
                raise EOFError()
            data += part
        return data
    size, = struct.unpack("<I", exact(4))
    return json.loads(exact(size))


def respond(sock, packet):
    body = json.dumps(packet).encode()
    frame = struct.pack("<I", len(body)) + body
    # IPC reads must tolerate both split headers and split bodies.
    for part in (frame[:2], frame[2:7], frame[7:]):
        sock.sendall(part)


@contextlib.contextmanager
def receiver(path, handler):
    errors = []
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        os.chmod(path, 0o600)
        listener.listen()
        listener.settimeout(2)

        def run():
            try:
                with listener.accept()[0] as conn:
                    conn.settimeout(2)
                    handler(conn)
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        try:
            yield
        finally:
            worker.join(3)
            if worker.is_alive():
                raise AssertionError("test receiver did not finish")
            if errors:
                raise errors[0]


class LiveRelayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="relay-test-", dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.thread_id = "target-thread"
        self.requests = []

    @contextlib.contextmanager
    def codex(self, replies, *, owner=True, eof=False, stall=False):
        (self.root / "ipc").mkdir()

        def handle(conn):
            while True:
                try:
                    req = receive(conn)
                except EOFError:
                    return
                method = req["method"]
                self.requests.append(req)
                self.assertEqual(req["type"], "request")
                self.assertNotIn("hostId", req)  # local follower protocol versions
                result = None
                error = None
                if method == "initialize":
                    self.assertEqual(req["version"], 0)
                    self.assertEqual(req["params"], {"clientType": "relay"})
                    result = {"clientId": "assigned-client"}
                else:
                    self.assertEqual(req["sourceClientId"], "assigned-client")
                    self.assertEqual(req["params"]["conversationId"], self.thread_id)
                    if method == "thread-owner-discovery":
                        self.assertEqual(req["params"]["hostId"], "local")
                        self.assertEqual(req["version"], 1)
                        if owner:
                            result = {"supportsUntrustedAppInput": True}
                        else:
                            error = "no-client-found"
                    else:
                        self.assertEqual(req["targetClientId"], "owner-client")
                        expected = 1 if method == "thread-follower-steer-turn" else 2
                        self.assertEqual(req["version"], expected)
                        if stall:
                            time.sleep(0.12)
                            return
                        if eof:
                            conn.sendall(struct.pack("<I", 500) + b'{"partial":')
                            return
                        reply = replies.pop(0)
                        if isinstance(reply, str):
                            error = reply
                        else:
                            result = {"result": reply}
                # A send-only client must not claim ownership of other tasks.
                respond(conn, {"type": "client-discovery-request", "requestId": "probe"})
                self.assertEqual(receive(conn), {"type": "client-discovery-response",
                                                 "requestId": "probe", "response": {"canHandle": False}})
                respond(conn, {"type": "broadcast", "method": "ignored"})
                response = {"type": "response", "requestId": req["requestId"],
                            "method": method, "handledByClientId": "owner-client"}
                if error:
                    response.update(resultType="error", error=error)
                else:
                    response.update(resultType="success", result=result)
                respond(conn, response)

        with receiver(self.root / "ipc/ipc.sock", handle):
            yield

    def send_codex(self):
        return send_codex(self.thread_id, "Agent message from test\n\nHello", str(self.root), timeout=2)

    def test_active_task_is_steered_once(self):
        with self.codex([{"turnId": "active-turn"}]):
            receipt = self.send_codex()
        self.assertEqual(receipt["status"], "steered")
        self.assertEqual(receipt["turnId"], "active-turn")
        self.assertEqual([r["method"] for r in self.requests],
                         ["initialize", "thread-owner-discovery", "thread-follower-steer-turn"])
        request = self.requests[-1]["params"]
        self.assertEqual(request["input"][0]["text"], request["restoreMessage"]["text"])
        self.assertNotIn("serviceTier", request)
        self.assertNotIn("cwd", request["restoreMessage"])

    def test_idle_task_starts_with_saved_settings(self):
        idle = f"Cannot steer conversation {self.thread_id} because its active turn already ended"
        with self.codex([idle, {"turn": {"id": "new-turn"}}]):
            receipt = self.send_codex()
        self.assertEqual(receipt["status"], "started")
        steer = self.requests[-2]["params"]
        start = self.requests[-1]["params"]["turnStart"]
        self.assertEqual(start["context"], {"inheritThreadSettings": True})
        self.assertEqual(set(start["request"]), {"threadId", "input", "clientUserMessageId"})
        self.assertEqual(start["request"]["clientUserMessageId"], steer["clientUserMessageId"])

    def test_missing_owner_sends_no_message(self):
        with self.codex([], owner=False), self.assertRaises(DeliveryError) as caught:
            self.send_codex()
        self.assertFalse(caught.exception.uncertain)
        self.assertEqual(len(self.requests), 2)

    def test_rejected_steering_never_falls_back(self):
        with self.codex(["permission denied"]), self.assertRaises(DeliveryError) as caught:
            self.send_codex()
        self.assertFalse(caught.exception.uncertain)
        self.assertEqual(len(self.requests), 3)

    def test_router_timeout_never_resends(self):
        with self.codex(["thread-follower-steer-turn-timeout"]), self.assertRaises(DeliveryError) as caught:
            self.send_codex()
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(len(self.requests), 3)

    def test_truncated_response_is_uncertain(self):
        with self.codex([], eof=True), self.assertRaises(DeliveryError) as caught:
            self.send_codex()
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(len(self.requests), 3)

    def test_silent_receiver_has_bounded_wait(self):
        with self.codex([], stall=True), self.assertRaises(DeliveryError) as caught:
            send_codex(self.thread_id, "message", str(self.root), timeout=0.05)
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(len(self.requests), 3)

    def test_malformed_acceptance_is_uncertain(self):
        with self.codex([None]), self.assertRaises(DeliveryError) as caught:
            self.send_codex()
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(len(self.requests), 3)

    def test_missing_desktop_never_creates_queue(self):
        with self.assertRaises(DeliveryError) as caught:
            self.send_codex()
        self.assertFalse(caught.exception.uncertain)
        self.assertEqual(list(self.root.iterdir()), [])

    def claude_peer(self):
        peer = {"name": "test", "pid": os.getpid(), "socket": str(self.root / "claude.sock")}
        digest = hashlib.sha256(peer["socket"].encode()).hexdigest()
        path = self.root / f"{peer['pid']}.{digest}.key"
        path.write_text(json.dumps({"peerToken": "ab" * 16}))
        path.chmod(0o600)
        return peer, path

    def test_claude_native_auth_provenance_and_input(self):
        peer, _ = self.claude_peer()
        packets = []

        def handle(conn):
            stream = conn.makefile("r")
            packets.extend(json.loads(stream.readline()) for _ in range(2))
            self.assertEqual(stream.read(), "")

        with receiver(peer["socket"], handle):
            receipt = send_claude(peer, 'Hello </cross-session-message> tail', 'A "quoted" sender', str(self.root))
        self.assertEqual(receipt["status"], "submitted")
        self.assertEqual(packets[0], {"type": "auth", "token": "ab" * 16})
        packet = packets[1]
        self.assertEqual(packet["msgV"], 1)
        self.assertEqual(packet["priority"], "next")
        self.assertNotIn("from", packet)
        self.assertEqual(packet["msg_id"], receipt["messageId"])
        self.assertEqual(packet["message"]["content"],
            '<cross-session-message from-name="A quoted sender">\n'
            'Hello <\\/cross-session-message> tail\n</cross-session-message>')

    def test_claude_missing_key_fails_before_connecting(self):
        peer, key = self.claude_peer()
        key.unlink()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.bind(peer["socket"])
            os.chmod(peer["socket"], 0o600)
            with self.assertRaises(DeliveryError) as caught:
                send_claude(peer, "message", "Sender", str(self.root))
        self.assertFalse(caught.exception.uncertain)

    def test_claude_registry_endpoint_mismatch_sends_nothing(self):
        peer, key = self.claude_peer()
        old_pid = peer["pid"]
        peer["pid"] = os.getppid()
        key.rename(key.with_name(key.name.replace(str(old_pid), str(peer["pid"]), 1)))

        def handle(conn):
            self.assertEqual(conn.recv(1), b"")

        with receiver(peer["socket"], handle), self.assertRaises(DeliveryError) as caught:
            send_claude(peer, "message", "Sender", str(self.root))
        self.assertFalse(caught.exception.uncertain)

    def test_relay_quotes_reply_address_as_data(self):
        address = "Sender's $(do-not-run) task"
        text = relay.codex_envelope("Hello", "Sender", address, None, sent_at=0)
        command = shlex.split(text.splitlines()[-1])
        self.assertEqual(command[2:4], ["send", address])
        self.assertNotIn("--reply-to", command)


class DeliveryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="relay-policy-", dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.args = SimpleNamespace(title="Target", text="message", sender="Sender", reply_to=None,
            kind=None, force_relay=True, defer=False, expires_in=300, mode="interrupt", cwd="/tmp")

    def send(self, kind="claude", **patches):
        target = {"kind": kind, "id": "target", "label": "Target"}
        defaults = {"RELAY_INBOX_ROOT": str(self.root), "resolve_any_target": lambda *a: target,
                    "peer_addresses": lambda: {"target": {"name": "Target"}}, **patches}
        output = io.StringIO()
        with patch.multiple(relay, **defaults), contextlib.redirect_stderr(output), contextlib.redirect_stdout(output):
            rc = relay.cmd_send(self.args)
        return rc, output.getvalue()

    def test_unavailable_claude_does_not_defer(self):
        rc, output = self.send(peer_addresses=lambda: {})
        self.assertEqual(rc, 1)
        self.assertIn("Nothing was queued", output)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_uncertain_failure_does_not_defer(self):
        def fail(*args):
            raise DeliveryError("disconnected", uncertain=True)
        rc, output = self.send(send_claude=fail)
        self.assertEqual(rc, 2)
        self.assertIn("unknown", output)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_explicit_defer_has_expiry(self):
        self.args.defer = True
        rc, _ = self.send()
        self.assertEqual(rc, 0)
        message = json.loads(next(self.root.glob("target/*.json")).read_text())
        self.assertEqual(message["expires_at"] - message["ts"], 300)

    def test_no_unbounded_defer(self):
        self.args.defer = True
        for ttl in (0, -1, 86401, float("nan"), float("inf")):
            self.args.expires_in = ttl
            self.assertEqual(self.send()[0], 1)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_codex_never_uses_deferred_transport(self):
        self.args.defer = True
        self.assertEqual(self.send(kind="codex")[0], 1)
        self.assertEqual(list(self.root.iterdir()), [])

    def hook(self):
        script = Path(__file__).resolve().parent.parent / "hooks/deliver-relay-message.sh"
        return subprocess.run(["bash", str(script)], input=json.dumps({"session_id": "target"}),
            text=True, capture_output=True, check=True,
            env={**os.environ, "HSM_RELAY_INBOX_ROOT": str(self.root)}).stdout

    def queue(self, name, **values):
        box = self.root / "target"
        box.mkdir(exist_ok=True)
        path = box / (name + ".json")
        path.write_text(json.dumps({"text": "fresh message", "from": "Sender", "ts": time.time(), **values}))
        return path

    def test_deferred_interrupt_is_short_and_delivered_once(self):
        path = self.queue("001", reply_to="Sender's task")
        output = json.loads(self.hook())["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        text = output["permissionDecisionReason"]
        self.assertTrue(text.startswith("Agent message from Sender · sent "))
        self.assertNotIn("--reply-to", text)
        self.assertIn("Sender's task", shlex.split(text.splitlines()[-1]))
        self.assertFalse(path.exists())
        self.assertEqual(self.hook(), "")

    def test_nudge_adds_context_without_denial(self):
        self.queue("001", mode="nudge")
        output = json.loads(self.hook())["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", output)
        self.assertIn("fresh message", output["additionalContext"])

    def test_expired_messages_are_archived_without_injection(self):
        explicit = self.queue("001", text="stale explicit", expires_at=time.time() - 1)
        legacy = self.queue("002", text="stale legacy", ts=time.time() - 3600)
        self.queue("003", mode="nudge")
        output = self.hook()
        self.assertNotIn("stale", output)
        self.assertIn("fresh message", output)
        for path in (explicit, legacy):
            self.assertFalse(path.exists())
            self.assertTrue((path.parent / "expired" / path.name).is_file())

    def test_expired_only_does_not_interrupt(self):
        self.queue("001", expires_at=1)
        self.assertEqual(self.hook(), "")

    def test_malformed_message_is_preserved_without_interrupt(self):
        path = self.queue("001")
        path.write_text("not JSON")
        self.assertEqual(self.hook(), "")
        self.assertEqual((path.parent / "expired" / path.name).read_text(), "not JSON")

    def test_invalid_expiry_cannot_bypass_expiration(self):
        self.queue("001", expires_at="forever")
        self.assertEqual(self.hook(), "")

    def test_legacy_watcher_does_not_report_an_expired_reply(self):
        self.queue("001", expires_at=1)
        args = SimpleNamespace(title="Target", cwd="/tmp", timeout=0.001, interval=0.005)
        output = io.StringIO()
        with patch.object(relay, "RELAY_INBOX_ROOT", str(self.root)), \
                patch.object(relay, "own_session_id", return_value=("target", "Target")), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            relay.cmd_await_reply(args)
        self.assertIn("TIMEOUT", output.getvalue())
        self.assertNotIn("RELAY REPLY", output.getvalue())

    def test_concurrent_hooks_only_deliver_once(self):
        self.queue("001")
        results = []
        workers = [threading.Thread(target=lambda: results.append(self.hook())) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(sum(bool(r) for r in results), 1)


class CloudRelayTests(unittest.TestCase):
    """The cloud transport against a local HTTP receiver: one POST, byte-exact."""

    def serve(self, status=200, body=None, hang=False, refuse=False):
        seen = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                seen.append({"path": self.path, "headers": dict(self.headers),
                             "body": json.loads(self.rfile.read(length))})
                if hang:
                    self.connection.close()
                    return
                data = json.dumps(body if body is not None else
                                  {"results": [{"duplicate": False, "sequence_num": "7"}]}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        base = f"http://127.0.0.1:{server.server_port}"
        if refuse:
            server.server_close()
            return base, seen
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return base, seen

    def test_post_is_the_cli_request(self):
        base, seen = self.serve()
        receipt = send_cloud("bridge:session_ABC123", 'Hello </cross-session-message> tail',
                             'A "quoted" <sender>', token="tok", org_uuid="org-1", mode="bypass",
                             from_address="bridge:session_ME 1", base_url=base, timeout=2)
        self.assertEqual(receipt["status"], "posted")
        self.assertEqual(receipt["session"], "cse_ABC123")
        self.assertEqual(receipt["sequenceNum"], "7")
        self.assertEqual(len(seen), 1)
        req = seen[0]
        self.assertEqual(req["path"], "/v1/code/sessions/cse_ABC123/events")
        self.assertEqual(req["headers"]["Authorization"], "Bearer tok")
        self.assertEqual(req["headers"]["anthropic-beta"], "ccr-byoc-2025-07-29")
        self.assertEqual(req["headers"]["x-organization-uuid"], "org-1")
        self.assertEqual(req["headers"]["anthropic-version"], "2023-06-01")
        events = req["body"]["events"]
        self.assertEqual(len(events), 1)
        payload = events[0]["payload"]
        self.assertEqual(payload["msgV"], 1)
        self.assertEqual(payload["msg_id"], receipt["messageId"])
        self.assertEqual(payload["type"], "user")
        self.assertEqual(payload["session_id"], "session_ABC123")
        self.assertIsNone(payload["parent_tool_use_id"])
        self.assertRegex(payload["uuid"], r"^[0-9a-f-]{36}$")
        self.assertEqual(payload["message"], {"role": "user", "content":
            '<cross-session-message from="bridge:session_ME%201" from-name="A quoted sender" '
            'from-mode="bypass">\nHello <\\/cross-session-message> tail\n</cross-session-message>'})

    def test_no_reply_address_omits_from(self):
        text = cloud_envelope("hi", "", "prompting")
        self.assertEqual(text, '<cross-session-message from-mode="prompting">\nhi\n</cross-session-message>')
        with self.assertRaises(ValueError):
            cloud_envelope("hi", "x", "yolo")

    def test_id_spellings(self):
        for spelling in ("cse_Ab9", "session_Ab9", "bridge:session_Ab9"):
            self.assertEqual(cloud_ids(spelling), ("cse_Ab9", "session_Ab9"))
        for bad in ("Ab9", "uds:/tmp/x.sock", "cse_", "cse_a b"):
            with self.assertRaises(ValueError):
                cloud_ids(bad)

    def test_server_refusal_is_certain(self):
        base, seen = self.serve(status=404, body={"error": {"message": "no such session"}})
        with self.assertRaises(DeliveryError) as caught:
            send_cloud("cse_X", "m", "s", token="tok", org_uuid="o", base_url=base, timeout=2)
        self.assertFalse(caught.exception.uncertain)
        self.assertIn("no such cloud session", str(caught.exception))
        self.assertEqual(len(seen), 1)

    def test_auth_refusal_names_the_grant(self):
        base, _ = self.serve(status=401, body={"error": {"message": "bad token"}})
        with self.assertRaises(DeliveryError) as caught:
            send_cloud("cse_X", "m", "s", token="tok", org_uuid="o", base_url=base, timeout=2)
        self.assertFalse(caught.exception.uncertain)
        self.assertIn("claude auth login", str(caught.exception))

    def test_dropped_connection_after_post_is_uncertain(self):
        base, seen = self.serve(hang=True)
        with self.assertRaises(DeliveryError) as caught:
            send_cloud("cse_X", "m", "s", token="tok", org_uuid="o", base_url=base, timeout=2)
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(len(seen), 1)

    def test_refused_connection_is_certain(self):
        base, seen = self.serve(refuse=True)
        with self.assertRaises(DeliveryError) as caught:
            send_cloud("cse_X", "m", "s", token="tok", org_uuid="o", base_url=base, timeout=2)
        self.assertFalse(caught.exception.uncertain)
        self.assertEqual(seen, [])

    def test_missing_grant_sends_nothing(self):
        base, seen = self.serve()
        with self.assertRaises(DeliveryError):
            send_cloud("cse_X", "m", "s", token="", org_uuid="o", base_url=base, timeout=2)
        self.assertEqual(seen, [])

    def test_desktop_grant_selection(self):
        key = lambda client, scopes: f"acct:A|{client}:org-9:https://api.anthropic.com:{scopes}"
        now = 1_000_000
        cache = {
            key("9d1c250a-e61b-44d9-88ed-5944d1962f5e", "user:inference user:profile"):
                {"token": "no-sessions-scope", "expiresAt": now + 10_000_000},
            key("9d1c250a-e61b-44d9-88ed-5944d1962f5e",
                "user:inference user:file_upload user:profile user:sessions:claude_code"):
                {"token": "fresh", "expiresAt": now + 3_600_000},
            key("other-client", "user:sessions:claude_code"):
                {"token": "other-client", "expiresAt": now + 9_000_000},
            key("9d1c250a-e61b-44d9-88ed-5944d1962f5e", "user:sessions:claude_code"):
                {"token": "expired", "expiresAt": now + 30_000},
        }
        grant = relay.pick_desktop_grant(cache, now)
        self.assertEqual(grant, {"token": "fresh", "expiresAt": now + 3_600_000, "org": "org-9"})
        self.assertIsNone(relay.pick_desktop_grant(cache, now + 3_600_000))
        self.assertIsNone(relay.pick_desktop_grant({}, now))
        self.assertEqual(relay.grant_key_fields("garbage"), (None, None, ()))


if __name__ == "__main__":
    unittest.main()
