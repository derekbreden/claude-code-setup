"""A cloud session's way back to this machine.

A session on Anthropic's machines cannot post into another session's inbox:
the server accepts its credential for its own work only. What it can do is
speak, and its transcript is readable from here with the grant the desktop
app holds. So the channel back is a mark in its own reply --

    <relay to="Time">
    What is the state of the funnel-mold trial?
    </relay>

-- and this watcher, which tails every live cloud session, finds the mark, and
delivers the body into the named session over the same peer socket a local
`send` uses. The named session answers with `send`, which posts to the cloud
record. A second mark reads instead of speaks --

    <relay read="Time" tail="40"/>

-- and the watcher renders that session's clean transcript here, where the
files are, and posts it into the cloud session in parts: the `/relay` pull,
done for a session that has no disk to pull from. Nothing runs in the sandbox,
no secret leaves this Mac, and the only medium is the one both sides already
reach.

A name that does not resolve is answered in place: a notice is posted into the
cloud session naming the sessions that are live, so the agent there can
address one of them instead of waiting for an answer that will never come.
"""

import glob
import json
import os
import re
import shlex
import sys
import time
from datetime import datetime, timezone

import jsonl2md as relay
from live_relay import DeliveryError, send_claude, send_cloud, send_codex

TAG_RE = re.compile(
    r"""<relay\s+to=(["'])([^"'<>\n]{1,120})\1\s*>[ \t]*\r?\n?(.*?)\r?\n?[ \t]*</relay\s*>""",
    re.S | re.I)
READ_RE = re.compile(
    r"""<relay\s+read=(["'])([^"'<>\n]{1,120})\1((?:\s+(?:tail|compact)=(?:["'])\d{1,4}(?:["']))*)\s*(?:/>|>\s*</relay\s*>)""",
    re.I)
READ_OPT_RE = re.compile(r"""(tail|compact)=["'](\d{1,4})["']""")
STATE_PATH = os.path.join(relay.CLOUD_CACHE_ROOT, "inbox.json")
READ_TAIL = 40
READ_COMPACT = 1
CHUNK_BYTES = 60_000
SEEN_KEEP = 200
GRANT_REFRESH = 600
LIVE_WORKERS = ("running", "idle", "requires_action")


def find_pokes(record):
    """`[(to, body)]` for every mark in an assistant record's visible text.
    Thinking and tool blocks are not the agent speaking to anyone here."""
    if record.get("type") != "assistant":
        return []
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        texts = [content]
    else:
        texts = [b.get("text") or "" for b in content or []
                 if isinstance(b, dict) and b.get("type") == "text"]
    out = []
    for text in texts:
        for m in TAG_RE.finditer(text):
            body = m.group(3).strip()
            if body:
                out.append((m.group(2).strip(), body))
    return out


def _visible_texts(record):
    if record.get("type") != "assistant":
        return []
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return [content]
    return [b.get("text") or "" for b in content or []
            if isinstance(b, dict) and b.get("type") == "text"]


def find_reads(record):
    """`[(title, tail, compact)]` for every read mark in an assistant record."""
    out = []
    for text in _visible_texts(record):
        for m in READ_RE.finditer(text):
            opts = {k: int(v) for k, v in READ_OPT_RE.findall(m.group(3) or "")}
            out.append((m.group(2).strip(), opts.get("tail", READ_TAIL), opts.get("compact", READ_COMPACT)))
    return out


def split_parts(text, limit=CHUNK_BYTES):
    """Cut on line boundaries so no part exceeds `limit` bytes; a single line
    longer than that is cut where it must be."""
    parts, buf, size = [], [], 0
    for line in text.splitlines(keepends=True):
        b = len(line.encode("utf-8"))
        while b > limit:
            if buf:
                parts.append("".join(buf)); buf, size = [], 0
            cut = line.encode("utf-8")[:limit].decode("utf-8", "ignore")
            parts.append(cut); line = line[len(cut):]; b = len(line.encode("utf-8"))
        if size + b > limit and buf:
            parts.append("".join(buf)); buf, size = [], 0
        buf.append(line); size += b
    if buf:
        parts.append("".join(buf))
    return parts or [""]


def resolve_transcript(name, cwd):
    """The local transcript a read mark names, rendered: `(title, markdown)`
    for a Claude session (any project's title, this project first) or a Codex
    task, else `(None, names)` with what could have been named."""
    sessions = relay.list_sessions(cwd)
    titles = {s.get("title"): s for s in sessions if s.get("title") and not relay.is_cloud(s.get("cliSessionId"))}
    try:
        tasks = {t["title"]: t for t in relay.list_codex_sessions(cwd)}
    except Exception:
        tasks = {}
    def pick(table):
        if name in table:
            return table[name]
        folded = [k for k in table if k.casefold() == name.casefold()]
        return table[folded[0]] if len(folded) == 1 else None
    session = pick(titles)
    if session is not None:
        return session["title"], lambda tail, compact: relay.render_tail(relay.records_of(session), tail, compact)
    task = pick(tasks)
    if task is not None:
        def render(tail, compact):
            turns = relay.codex_dialogue(task["id"], task.get("rollout_path"))
            return relay.render_blocks(turns[-tail:] if tail else turns, compact)
        return task["title"], render
    return None, sorted(set(titles) | set(tasks))


def poke_text(body, cloud_title, cse_id, sent_at=None):
    """What the local session reads: who, when, what, and how to answer."""
    stamp = datetime.fromtimestamp(time.time() if sent_at is None else sent_at,
                                   timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    reply = shlex.join(["python3", os.path.abspath(relay.__file__), "send", cse_id,
                        "<your answer>", "--from", "<your session name>"])
    return (f"Agent message from {cloud_title} (a cloud session) · sent {stamp}\n\n{body}\n\n"
            f"Reply to {cloud_title}:\n{reply}\n"
            "It cannot reach you through SendMessage; its own replies come back this same way, "
            "as a mark in its transcript that this watcher delivers.\n")


class InboxState:
    """Per cloud session: the last event sequence read, and the assistant
    events already acted on, so a restart neither replays a mark nor loses
    its place."""

    def __init__(self, path=STATE_PATH):
        self.path = path
        try:
            self.data = json.load(open(path))
        except (OSError, ValueError):
            self.data = {}

    def entry(self, cse_id):
        return self.data.setdefault(cse_id, {"cursor": None, "seen": []})

    def cursor(self, cse_id):
        return self.entry(cse_id).get("cursor")

    def set_cursor(self, cse_id, seq):
        self.entry(cse_id)["cursor"] = seq

    def seen(self, cse_id, uuid):
        return uuid in self.entry(cse_id)["seen"]

    def mark(self, cse_id, uuid):
        seen = self.entry(cse_id)["seen"]
        seen.append(uuid)
        del seen[:-SEEN_KEEP]

    def forget(self, live_ids):
        for cse_id in list(self.data):
            if cse_id not in live_ids:
                del self.data[cse_id]

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f)
        os.replace(tmp, self.path)


def _local_titles():
    """title -> cliSessionId for every desktop session record, any project."""
    out = {}
    for p in glob.glob(f"{relay.META_ROOT}/*/*/local_*.json"):
        try:
            m = json.load(open(p))
        except Exception:
            continue
        if m.get("title") and m.get("cliSessionId") and not m.get("isArchived"):
            out.setdefault(m["title"], m["cliSessionId"])
    return out


def resolve_local(name, cwd):
    """The live receiver a mark's `to` names: a Claude peer by its session
    name or desktop title, else a Codex task by title. `(kind, target, names)`
    with kind None when nothing answers to it; `names` is what does exist."""
    peers = relay.peer_addresses()
    by_name = {p["name"]: p for p in peers.values()}
    titles = _local_titles()
    candidates = dict(by_name)
    for title, cli in titles.items():
        if cli in peers:
            candidates.setdefault(title, peers[cli])
    if name in candidates:
        return "claude", candidates[name], sorted(candidates)
    folded = [n for n in candidates if n.casefold() == name.casefold()]
    if len(folded) == 1:
        return "claude", candidates[folded[0]], sorted(candidates)
    try:
        tasks = [t for t in relay.list_codex_sessions(cwd) if t["title"] == name]
    except Exception:
        tasks = []
    if len(tasks) == 1:
        return "codex", tasks[0], sorted(candidates)
    return None, None, sorted(candidates)


class Inbox:
    def __init__(self, *, interval=4.0, only=None, cwd=relay.DEFAULT_CWD, state=None,
                 log=None, clock=time.time):
        self.interval = interval
        self.only = list(only or [])
        self.cwd = cwd
        self.state = state or InboxState()
        self.log = log or (lambda line: sys.stderr.write(line + "\n"))
        self.clock = clock
        self.grant_read_at = 0

    # -- roster ---------------------------------------------------------------
    def watched(self):
        """Live cloud sessions on the account: the ones on Anthropic's machines,
        or exactly the ids asked for. A bridge record fronts a session on some
        computer, which has SendMessage of its own and needs no way back."""
        try:
            sessions = relay.cloud_sessions()
        except Exception as exc:
            self.log(f"[inbox] session list unavailable: {exc}")
            if not self.only:
                return None
            sessions = []
        by_id = {s["id"]: s for s in sessions}
        if self.only:
            return [{"id": relay.cloud_ids(i)[0],
                     "title": (by_id.get(relay.cloud_ids(i)[0]) or {}).get("title") or i}
                    for i in self.only]
        return [{"id": s["id"], "title": s.get("title") or s["id"]} for s in sessions
                if s.get("environment_kind") == "anthropic_cloud"
                and s.get("status") != "archived"
                and (s.get("worker_status") in LIVE_WORKERS or not s.get("worker_status"))]

    # -- one session ----------------------------------------------------------
    def poll(self, session):
        cse_id, title = session["id"], session["title"]
        cursor = self.state.cursor(cse_id)
        if cursor is None:
            head = relay.cloud_head_sequence(cse_id)
            if head is None:
                return 0                      # nothing said yet; look again next pass
            self.state.set_cursor(cse_id, head)
            self.log(f"[inbox] watching {title!r} ({cse_id}) from event {head}")
            return 0
        events = relay.cloud_events(cse_id, after=cursor)
        if not events:
            return 0
        self.state.set_cursor(cse_id, events[-1].get("sequence_num"))
        delivered = 0
        for e in events:
            if e.get("event_type") != "assistant":
                continue
            rec = e.get("payload") or {}
            uuid = rec.get("uuid") or e.get("event_id")
            if not uuid or self.state.seen(cse_id, uuid):
                continue
            pokes, reads = find_pokes(rec), find_reads(rec)
            if not pokes and not reads:
                continue
            self.state.mark(cse_id, uuid)
            for to, body in pokes:
                delivered += self.deliver(cse_id, title, to, body)
            for name, tail, compact in reads:
                delivered += self.read(cse_id, title, name, tail, compact)
        return delivered

    def read(self, cse_id, title, name, tail, compact):
        """Render a local transcript and post it into the cloud session, in
        parts a message can carry."""
        try:
            found, render = resolve_transcript(name, self.cwd)
        except Exception as exc:
            self.bounce(cse_id, name, f"could not read the local rosters: {exc}", [], kind="read")
            return 0
        if found is None:
            self.bounce(cse_id, name, f"no session or task named {name!r} on Derek's Mac", render, kind="read")
            return 0
        try:
            md = render(tail, compact)
        except Exception as exc:
            self.bounce(cse_id, name, f"transcript of {found!r} could not be rendered: {exc}", [], kind="read")
            return 0
        stamp = datetime.fromtimestamp(self.clock(), timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        parts = split_parts(md.strip() + "\n")
        n = len(parts)
        posted = 0
        for i, part in enumerate(parts, 1):
            head = (f"Clean transcript of {found!r} on Derek's Mac \u2014 last {tail} exchanges"
                    f"{', compact' if compact else ''}, rendered {stamp}"
                    f"{f', part {i} of {n}' if n > 1 else ''}. What was typed and what was answered; "
                    "tool calls and thinking are stripped.\n\n")
            try:
                send_cloud(cse_id, head + part, "relay", token=self.token(), org_uuid=relay._org_uuid(), mode="bypass")
                posted += 1
            except (DeliveryError, relay.TranscriptError, ValueError) as exc:
                self.log(f"[inbox] read {found!r} for {cse_id}: part {i}/{n} failed: {exc}")
                break
        self.log(f"[inbox] {title!r} read {found!r} (tail {tail}): {posted}/{n} part(s) posted")
        return 1 if posted == n else 0

    def deliver(self, cse_id, title, to, body):
        kind, target, names = resolve_local(to, self.cwd)
        text = poke_text(body, title, cse_id, self.clock())
        try:
            if kind == "claude":
                send_claude(target, text, f"{title} (cloud)", relay.SESSIONS_ROOT)
            elif kind == "codex":
                send_codex(target["id"], text, relay.CODEX_HOME)
            else:
                self.bounce(cse_id, to, f"no live session or task named {to!r} on Derek's Mac", names)
                return 0
        except DeliveryError as exc:
            self.bounce(cse_id, to, f"delivery to {to!r} failed: {exc}", names)
            return 0
        self.log(f"[inbox] {title!r} -> {to!r} ({kind}): {' '.join(body.split())[:80]}")
        return 1

    def bounce(self, cse_id, to, reason, names, kind="to"):
        """Answer an undeliverable mark where its author will see it."""
        listing = ", ".join(names) if names else "none"
        what = "Live sessions on that Mac right now" if kind == "to" else "Transcripts on that Mac right now"
        note = (f"Your <relay {kind}=\"{to}\"> was not delivered: {reason}. "
                f"{what}: {listing}. "
                "Write the mark again with one of those names.")
        try:
            send_cloud(cse_id, note, "relay", token=self.token(), org_uuid=relay._org_uuid(),
                       mode="bypass")
            self.log(f"[inbox] bounced {to!r} for {cse_id}: {reason}")
        except (DeliveryError, relay.TranscriptError, ValueError) as exc:
            self.log(f"[inbox] could not bounce {to!r} for {cse_id}: {exc}")

    # -- grant ----------------------------------------------------------------
    def token(self):
        """The desktop grant is read once and re-read on a schedule, so a token
        the app has since rotated is not held past its life."""
        if self.clock() - self.grant_read_at > GRANT_REFRESH:
            relay._DESKTOP_GRANT.clear()
            self.grant_read_at = self.clock()
        return relay._cloud_token()

    # -- loop -----------------------------------------------------------------
    def pass_once(self):
        sessions = self.watched()
        if sessions is None:                  # roster unknown: keep every cursor
            return 0
        self.state.forget({s["id"] for s in sessions})
        total = 0
        for s in sessions:
            try:
                total += self.poll(s)
            except relay.TranscriptError as exc:
                relay._DESKTOP_GRANT.clear()
                self.log(f"[inbox] {s['title']!r}: {exc}")
            except Exception as exc:  # one session's trouble must not stop the others
                self.log(f"[inbox] {s['title']!r}: {type(exc).__name__}: {exc}")
        self.state.save()
        return total

    def run(self):
        self.log(f"[inbox] watching cloud sessions every {self.interval:g}s"
                 + (f" (only {', '.join(self.only)})" if self.only else ""))
        while True:
            self.pass_once()
            time.sleep(self.interval)
