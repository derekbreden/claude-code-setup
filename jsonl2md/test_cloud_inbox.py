"""The cloud inbox watcher: marks are found, delivered once, and bounced when
they name nobody. Every cloud read and every transport is a recorder."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import cloud_inbox
import jsonl2md as relay
from cloud_inbox import (Inbox, InboxState, find_pokes, find_reads, poke_text, resolve_local,
                         resolve_transcript, split_parts)
from live_relay import DeliveryError


def assistant(text, uuid="u1", extra_blocks=()):
    blocks = [{"type": "thinking", "thinking": "<relay to=\"Time\">not this</relay>"},
              {"type": "text", "text": text}, *extra_blocks]
    return {"type": "assistant", "uuid": uuid, "message": {"role": "assistant", "content": blocks}}


class MarkTests(unittest.TestCase):
    def test_marks_in_visible_text_only(self):
        rec = assistant('lead-in\n<relay to="Time">\nWhat is the trial state?\n</relay>\ntail',
                        extra_blocks=[{"type": "tool_use", "input": {"x": '<relay to="Time">no</relay>'}}])
        self.assertEqual(find_pokes(rec), [("Time", "What is the trial state?")])

    def test_quote_styles_case_and_several(self):
        rec = assistant("<RELAY to='System status'>one</RELAY> then\n"
                        '  <relay to="Time">\n  two\n  </relay >')
        self.assertEqual(find_pokes(rec), [("System status", "one"), ("Time", "two")])

    def test_empty_and_user_records_are_nothing(self):
        self.assertEqual(find_pokes(assistant('<relay to="Time">\n\n</relay>')), [])
        self.assertEqual(find_pokes({"type": "user", "message": {"content": '<relay to="T">x</relay>'}}), [])
        self.assertEqual(find_pokes({"type": "assistant", "message": {"content": '<relay to="T">str body</relay>'}}),
                         [("T", "str body")])

    def test_delivered_text_carries_the_return_route(self):
        text = poke_text("hello", "Ceiling panel", "cse_ABC", sent_at=0)
        self.assertTrue(text.startswith("Agent message from Ceiling panel (a cloud session) · sent 1970-01-01 00:00:00 UTC"))
        self.assertIn("\nhello\n", text)
        self.assertIn("send cse_ABC '<your answer>' --from '<your session name>'", text)


class StateTests(unittest.TestCase):
    def test_round_trip_and_bounded_seen(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as d:
            path = os.path.join(d, "inbox.json")
            st = InboxState(path)
            st.set_cursor("cse_A", "17")
            for i in range(cloud_inbox.SEEN_KEEP + 5):
                st.mark("cse_A", f"u{i}")
            st.save()
            again = InboxState(path)
            self.assertEqual(again.cursor("cse_A"), "17")
            self.assertFalse(again.seen("cse_A", "u0"))
            self.assertTrue(again.seen("cse_A", f"u{cloud_inbox.SEEN_KEEP + 4}"))
            again.forget({"cse_B"})
            self.assertEqual(again.data, {})


class ResolveTests(unittest.TestCase):
    def test_peer_name_title_and_codex(self):
        peers = {"sid-1": {"name": "homesodamachine-f8", "socket": "/tmp/a.sock", "pid": 1},
                 "sid-2": {"name": "Time", "socket": "/tmp/b.sock", "pid": 2}}
        with patch.object(relay, "peer_addresses", return_value=peers), \
             patch.object(cloud_inbox, "_local_titles", return_value={"Cloud instance relay setup": "sid-1", "Gone": "sid-9"}), \
             patch.object(relay, "list_codex_sessions", return_value=[{"id": "t-1", "title": "Magnets"}]):
            self.assertEqual(resolve_local("Time", "/p")[:2], ("claude", peers["sid-2"]))
            self.assertEqual(resolve_local("Cloud instance relay setup", "/p")[:2], ("claude", peers["sid-1"]))
            self.assertEqual(resolve_local("time", "/p")[:2], ("claude", peers["sid-2"]))
            self.assertEqual(resolve_local("Magnets", "/p")[:2], ("codex", {"id": "t-1", "title": "Magnets"}))
            kind, target, names = resolve_local("Gone", "/p")
            self.assertIsNone(kind)
            self.assertEqual(names, ["Cloud instance relay setup", "Time", "homesodamachine-f8"])


class PollTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.state = InboxState(os.path.join(self.tmp.name, "inbox.json"))
        self.log = []
        self.sent = []
        self.bounced = []
        self.events = {}
        self.heads = {}
        self.sessions = [{"id": "cse_A", "title": "Ceiling panel", "environment_kind": "anthropic_cloud",
                          "status": "active", "worker_status": "idle"},
                         {"id": "cse_B", "title": "Time", "environment_kind": "bridge",
                          "status": "active", "worker_status": "idle", "connection_status": "connected"}]
        patches = [
            patch.object(relay, "cloud_sessions", side_effect=lambda force=False: self.sessions),
            patch.object(relay, "cloud_head_sequence", side_effect=lambda cse: self.heads.get(cse)),
            patch.object(relay, "cloud_events", side_effect=self.fetch),
            patch.object(cloud_inbox, "send_claude", side_effect=self.record_claude),
            patch.object(cloud_inbox, "send_cloud", side_effect=self.record_bounce),
            patch.object(cloud_inbox, "resolve_local", side_effect=self.resolve),
            patch.object(relay, "_cloud_token", return_value="tok"),
            patch.object(relay, "_org_uuid", return_value="org"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.inbox = Inbox(interval=0, state=self.state, log=self.log.append, clock=lambda: 0)

    def fetch(self, cse, after=None):
        return [e for e in self.events.get(cse, []) if int(e["sequence_num"]) > int(after)]

    def record_claude(self, peer, text, sender, root):
        self.sent.append((peer["name"], sender, text))
        if peer["name"] == "Broken":
            raise DeliveryError("socket closed")
        return {"status": "submitted"}

    def record_bounce(self, cse, note, sender, **kw):
        self.bounced.append((cse, note))
        return {"status": "posted"}

    def resolve(self, name, cwd):
        live = {"Time": {"name": "Time"}, "Broken": {"name": "Broken"}}
        return ("claude", live[name], sorted(live)) if name in live else (None, None, sorted(live))

    def event(self, seq, text, uuid):
        return {"event_type": "assistant", "sequence_num": str(seq), "event_id": f"e{seq}",
                "payload": assistant(text, uuid=uuid)}

    def test_first_sight_starts_at_head_then_delivers_once(self):
        self.heads["cse_A"] = "10"
        self.events["cse_A"] = [self.event(9, '<relay to="Time">old</relay>', "old")]
        self.assertEqual(self.inbox.pass_once(), 0)
        self.assertEqual(self.state.cursor("cse_A"), "10")
        self.assertNotIn("cse_B", self.state.data)            # a bridge record is not watched
        self.events["cse_A"].append(self.event(11, 'text\n<relay to="Time">\nstate?\n</relay>', "new"))
        self.assertEqual(self.inbox.pass_once(), 1)
        self.assertEqual(self.inbox.pass_once(), 0)             # cursor moved: not again
        self.assertEqual(len(self.sent), 1)
        name, sender, text = self.sent[0]
        self.assertEqual((name, sender), ("Time", "Ceiling panel (cloud)"))
        self.assertIn("\nstate?\n", text)
        self.assertIn("send cse_A", text)
        self.assertEqual(self.bounced, [])
        # A cursor rollback does not replay a delivered mark.
        self.state.set_cursor("cse_A", "10")
        self.assertEqual(self.inbox.pass_once(), 0)

    def test_unknown_name_and_failed_delivery_bounce(self):
        self.heads["cse_A"] = "1"
        self.inbox.pass_once()
        self.events["cse_A"] = [self.event(2, '<relay to="Nobody">hi</relay>', "n1"),
                                self.event(3, '<relay to="Broken">hi</relay>', "n2")]
        self.assertEqual(self.inbox.pass_once(), 0)
        self.assertEqual(len(self.bounced), 2)
        self.assertIn("no live session or task named 'Nobody'", self.bounced[0][1])
        self.assertIn("Live sessions on that Mac right now: Broken, Time", self.bounced[0][1])
        self.assertIn("delivery to 'Broken' failed: socket closed", self.bounced[1][1])

    def test_roster_failure_keeps_cursors(self):
        self.heads["cse_A"] = "5"
        self.inbox.pass_once()
        with patch.object(relay, "cloud_sessions", side_effect=OSError("offline")):
            self.assertEqual(self.inbox.pass_once(), 0)
        self.assertEqual(self.state.cursor("cse_A"), "5")

    def test_only_watches_named_records_of_any_kind(self):
        inbox = Inbox(interval=0, only=["bridge:session_B"], state=self.state, log=self.log.append, clock=lambda: 0)
        self.heads["cse_B"] = "3"
        inbox.pass_once()
        self.assertEqual(sorted(self.state.data), ["cse_B"])
        self.events["cse_B"] = [self.event(4, '<relay to="Time">ping</relay>', "b1")]
        self.assertEqual(inbox.pass_once(), 1)
        self.assertEqual(self.sent[0][0], "Time")


class ReadMarkTests(unittest.TestCase):
    def test_read_marks_parse(self):
        rec = assistant('<relay read="Time"/> and <relay read=\'System status\' tail="12" compact="0"></relay>\n'
                        '<relay read="Nope" tail="5" />')
        self.assertEqual(find_reads(rec), [("Time", 40, 1), ("System status", 12, 0), ("Nope", 5, 1)])
        self.assertEqual(find_reads(assistant('<relay to="Time">x</relay>')), [])
        self.assertEqual(find_pokes(assistant('<relay read="Time"/>')), [])

    def test_split_parts_respects_lines_and_limit(self):
        text = "".join(f"line {i:04d} " + "x" * 90 + "\n" for i in range(50))
        parts = split_parts(text, limit=1000)
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(len(p.encode()) <= 1000 for p in parts))
        self.assertTrue(all(p.endswith("\n") for p in parts))
        self.assertEqual(split_parts("", limit=10), [""])
        self.assertEqual(split_parts("a" * 25, limit=10), ["a" * 10, "a" * 10, "a" * 5])

    def test_resolve_transcript_prefers_sessions_then_tasks(self):
        session = {"title": "Time", "cliSessionId": "abc"}
        with patch.object(relay, "list_sessions", return_value=[session, {"title": "Cloudy", "cliSessionId": "cse_X"}]), \
             patch.object(relay, "list_codex_sessions", return_value=[{"id": "t1", "title": "Magnets", "rollout_path": None}]), \
             patch.object(relay, "records_of", return_value=[{"type": "user", "message": {"role": "user", "content": "hi"}},
                                                             {"type": "assistant", "message": {"role": "assistant", "content": "yo"}}]), \
             patch.object(relay, "codex_dialogue", return_value=[("user", "q"), ("assistant", "a")]):
            title, render = resolve_transcript("time", "/p")
            self.assertEqual(title, "Time")
            self.assertIn("# User", render(40, 0))
            title, render = resolve_transcript("Magnets", "/p")
            self.assertEqual(title, "Magnets")
            self.assertIn("# Assistant", render(1, 0))
            none, names = resolve_transcript("Cloudy", "/p")     # a cloud row is not a local transcript
            self.assertIsNone(none)
            self.assertEqual(names, ["Magnets", "Time"])


class ReadPollTests(PollTests):
    def test_read_mark_posts_transcript_in_parts(self):
        big = "".join(f"---\n\n# User\n\n---\n\nturn {i} " + "y" * 200 + "\n\n" for i in range(700))
        self.heads["cse_A"] = "1"
        self.inbox.pass_once()
        self.events["cse_A"] = [self.event(2, 'reading\n<relay read="Time" tail="9"/>', "r1")]
        with patch.object(cloud_inbox, "resolve_transcript", return_value=("Time", lambda tail, compact: big)):
            self.assertEqual(self.inbox.pass_once(), 1)
        self.assertEqual(self.sent, [])
        self.assertGreaterEqual(len(self.bounced), 3)          # the recorder catches every send_cloud
        heads = [note.split("\n")[0] for _, note in self.bounced]
        self.assertTrue(all(h.startswith("Clean transcript of 'Time' on Derek's Mac") for h in heads))
        self.assertIn("last 9 exchanges, compact", heads[0])
        self.assertIn(f"part 1 of {len(self.bounced)}", heads[0])
        body = "".join(note.split("\n\n", 1)[1] for _, note in self.bounced)
        self.assertEqual(body.strip(), big.strip())
        self.assertEqual(self.inbox.pass_once(), 0)             # once

    def test_read_of_unknown_name_bounces_with_transcripts(self):
        self.heads["cse_A"] = "1"
        self.inbox.pass_once()
        self.events["cse_A"] = [self.event(2, '<relay read="Ghost"/>', "r2")]
        with patch.object(cloud_inbox, "resolve_transcript", return_value=(None, ["Time", "Magnets"])):
            self.assertEqual(self.inbox.pass_once(), 0)
        self.assertEqual(len(self.bounced), 1)
        self.assertIn('<relay read="Ghost"> was not delivered', self.bounced[0][1])
        self.assertIn("Transcripts on that Mac right now: Time, Magnets", self.bounced[0][1])


if __name__ == "__main__":
    unittest.main()
