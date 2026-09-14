#!/usr/bin/env python3
"""jsonl2md - export clean Claude and Codex conversations as markdown.

Three sources, each with a list verb and an export verb, plus a standalone renderer:

  Claude Code sessions (a project on disk, or on Anthropic's machines):
    list-sessions          List titled desktop sessions, VSCode-extension
                           sessions, and cloud sessions for --cwd.
    recent-prompts         What you last asked for, newest first, across every
                           session at once -- timestamp, text, and the line it
                           lives on. --since gates on whether you are around.
    situation              One board joining title, SendMessage address, live
                           state, and how long since each was last asked.
    export-session <title> Export one session to .md (filename = title). Also
                           accepts a raw cliSessionId (or unique prefix).
    export-session --all   Export every session matching the filter.
    ... --compact [N]      Cut the middle out of each agent run, keeping N lines
                           at either end. Your turns are never cut.

  Claude.ai chats (desktop app sidebar):
    list-chats             List the top --limit chats in sidebar order.
    export-chat <name>     Export one chat to .md (filename = chat name).
    export-chat --all      Export every chat in the top --limit window.

  Codex desktop tasks (current project):
    list-codex-sessions          List user-titled, non-archived tasks.
    export-codex-session <title> Export one task's complete visible dialogue.

  Standalone:
    render <path.jsonl>    Render any Claude Code .jsonl (or stdin) to .md on stdout.

  Cross-session (the write half of relay):
    send <title> <text>    Deliver to a live agent, steering or waking it directly.

Desktop-app sessions are discovered from Claude.app's metadata at
    ~/Library/Application Support/Claude/claude-code-sessions/<workspace>/<device>/local_*.json
VSCode-extension sessions carry no such titled record; they're discovered from
the running-process descriptors at
    ~/.claude/sessions/<pid>.json          (entrypoint == "claude-vscode")
and named from the VSCode extension's own live state (the open Claude tab's
rename, else the sessions-sidebar label) at
    ~/Library/Application Support/Code/User/workspaceStorage/*/state.vscdb
Both resolve to transcripts at
    ~/.claude/projects/<cwd-with-slashes-as-dashes>/<cliSessionId>.jsonl
Chats are fetched from claude.ai using cookies decrypted from the desktop app's cookie store.
"""

import argparse
import base64
import glob
import hashlib
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from live_relay import (DeliveryError, cloud_address, cloud_ids, receiver_mode, send_claude, send_cloud,
                        send_codex)

DEFAULT_CWD = "/Users/derekbredensteiner/Developer/homesodamachine"
META_ROOT = os.path.expanduser("~/Library/Application Support/Claude/claude-code-sessions")
SESSIONS_ROOT = os.path.expanduser("~/.claude/sessions")
VSCODE_WS_STORAGE = os.path.expanduser("~/Library/Application Support/Code/User/workspaceStorage")
JSONL_ROOT = os.path.expanduser("~/.claude/projects")
RELAY_INBOX_ROOT = os.path.expanduser("~/.claude/hooks/relay-inbox")
DEFERRED_TTL = 300
CLAUDE_APP_DIR = os.path.expanduser("~/Library/Application Support/Claude")
COOKIE_DB = os.path.join(CLAUDE_APP_DIR, "Cookies")
KEYCHAIN_SERVICE = "Claude Safe Storage"
KEYCHAIN_ACCOUNT = "Claude Key"
CODEX_HOME = os.path.expanduser(os.environ.get("CODEX_HOME", "~/.codex"))

# --- cloud sessions ---------------------------------------------------------
#
# A session started in the Code section of the desktop app can run on Anthropic's
# machines instead of this one. It has a title you gave it and a transcript you
# can read, and neither is on this disk. So it is reachable exactly one way,
# through the same API the CLI uses -- for reading its transcript and for
# delivering a message into it. A session bridged from another computer through
# Remote Control has the same kind of record and takes a message the same way.
#
# The grant: the desktop app signs the Code tab in itself and hands each CLI it
# spawns a token over the SDK channel, refreshing it in its own encrypted cache
# (`config.json` -> `oauth:tokenCacheV2`, Electron safeStorage under the same
# Keychain key the cookie store uses). That cache is read here and never
# written: refreshing it from outside would rotate the refresh token underneath
# the app. The Keychain grant a terminal `claude` signs in with is the fallback.
CLOUD_API = "https://api.anthropic.com"
CLOUD_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
CLOUD_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
CLOUD_SCOPE = "user:sessions:claude_code"
CC_KEYCHAIN_SERVICE = "Claude Code-credentials"
CC_CREDENTIALS_FILE = os.path.expanduser("~/.claude/.credentials.json")
DESKTOP_CONFIG = os.path.join(CLAUDE_APP_DIR, "config.json")
DESKTOP_TOKEN_KEYS = ("oauth:tokenCacheV2", "oauth:tokenCache")
CLAUDE_JSON = os.path.expanduser("~/.claude.json")
CLOUD_UA = "claude-code/2.1.270"
CLOUD_CACHE_ROOT = os.path.expanduser("~/.jsonl2md/cloud")
CLOUD_LIST_TTL = 60
# Cloud ids carry their own prefix, so the id alone says which side a session
# lives on -- that is the discriminator every read path branches on.
CLOUD_ID_RE = re.compile(r"^cse_[A-Za-z0-9]+$")


def _latest_codex_db(stem):
    paths = glob.glob(os.path.join(CODEX_HOME, f"{stem}_*.sqlite"))
    if not paths:
        return os.path.join(CODEX_HOME, f"{stem}_1.sqlite")

    def version(path):
        match = re.search(r"_(\d+)\.sqlite$", path)
        return int(match.group(1)) if match else -1

    return max(paths, key=version)


CODEX_STATE_DB = _latest_codex_db("state")
CODEX_HISTORY_DB = _latest_codex_db("thread_history")

# The CLI supplies the normalized read projection; live_relay uses the running
# desktop app for delivery. `CODEX_CLI` overrides the read-side CLI search.
CODEX_CLI_CANDIDATES = (
    os.environ.get("CODEX_CLI") or "",
    "/Applications/ChatGPT.app/Contents/Resources/codex",
    os.path.expanduser("~/.codex/bin/codex"),
)


def codex_cli():
    """The codex binary, or None. Bundled path first, then $PATH."""
    for path in CODEX_CLI_CANDIDATES:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return shutil.which("codex")


def iter_records(text):
    decoder = json.JSONDecoder()
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        obj, end = decoder.raw_decode(text, i)
        yield obj
        i = end


# The user side of a transcript is not all speech. Tool results come back as
# role "user", and so does everything the harness posts under the user's name:
# background-task notifications, local command output, the expanded body of a
# slash command, a peer session's message. Each is either flagged
# (`toolUseResult`, `isMeta`, `isSidechain`) or wears its own envelope tag, so
# what the human typed is separable from what was typed for them.

SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
COMMAND_NAME_RE = re.compile(r"<command-name>\s*(.*?)\s*</command-name>", re.S)
COMMAND_ARGS_RE = re.compile(r"<command-args>\s*(.*?)\s*</command-args>", re.S)
ATTACH_MARK_RE = re.compile(r"^<!--\s*attach\s*-->[ \t]*\n?", re.M)
# A slash command normally arrives wearing a <command-name> envelope. One that
# never expanded arrives flagged isMeta with no envelope and no body -- the only
# trace of it is the line that was typed. This matches that line and nothing
# else: across 1795 isMeta records in the corpus, every other one is either an
# expanded command body (prose) or a tagged envelope.
BARE_COMMAND_RE = re.compile(r"^/[A-Za-z0-9][\w:-]*(?:[ \t]+\S.*)?$")
RELAY_PREFIXES = ("Agent message from ", "\U0001f4ec RELAYED MESSAGE")
INJECTED = (
    "<task-notification>",
    "<local-command-stdout>",
    "<local-command-caveat>",
    "<cross-session-message",
    "Another Claude session sent a message:",
) + RELAY_PREFIXES


def user_speech(obj, text):
    """What the human typed in this user record, or "" if they typed nothing.

    A slash command arrives as an envelope and renders as the line you actually
    typed, `/name args`; an attached quote keeps the quote and drops its marker;
    system reminders are cut wherever they were spliced in."""
    if "toolUseResult" in obj or obj.get("isSidechain"):
        return ""
    text = SYSTEM_REMINDER_RE.sub("", text).strip()
    if obj.get("isMeta"):
        # isMeta covers everything typed for the human -- expanded bodies, task
        # notifications -- and also an unexpanded slash command, which they did
        # type. A caller gating on "is the human here" reads a fleet driven by
        # slash commands as an empty one if this is dropped with the rest.
        return text if BARE_COMMAND_RE.match(text) else ""
    if not text or text.startswith(INJECTED):
        return ""
    name = COMMAND_NAME_RE.search(text)
    if name:
        args = COMMAND_ARGS_RE.search(text)
        return f"{name.group(1)} {args.group(1) if args else ''}".strip()
    return ATTACH_MARK_RE.sub("", text).strip()


def extract_message(obj):
    msg = obj.get("message") or {}
    role = msg.get("role") or obj.get("type")
    content = msg.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n\n".join(p.get("text", "") for p in content if p.get("type") == "text")
    else:
        text = ""
    text = text.strip()
    if role == "user":
        text = user_speech(obj, text)
    return role, text


# A long session is mostly agent. Between two things you said there can be
# dozens of assistant messages, one per tool step, and the shape of that run
# reads off its first lines and its last: what it set out to do, and what it
# landed. The middle is the working. Compaction coalesces each run of
# consecutive assistant turns into one block and cuts that middle out, keeping
# N lines at either end. Your own turns are never cut -- they are the spine the
# rest hangs off, and the reason to read a compacted transcript at all.


def turns_of(records):
    return [(r, t) for r, t in (extract_message(o) for o in records)
            if r in ("user", "assistant") and t]


def agent_runs(turns):
    """[(role, text)] -> [(role, text, n_messages)] with consecutive assistant
    turns merged, so one elision spans a whole run instead of each message."""
    out = []
    for role, text in turns:
        if role == "assistant" and out and out[-1][0] == "assistant":
            _, prev, n = out[-1]
            out[-1] = (role, prev + "\n\n" + text, n + 1)
        else:
            out.append((role, text, 1))
    return out


def elide_middle(text, keep, n_messages=1):
    """Keep the first and last `keep` lines; replace the rest with a count. The
    guard is 2*keep+4, not 2*keep, so a block can never come back longer than
    it went in."""
    lines = text.split("\n")
    if len(lines) <= 2 * keep + 4:
        return text
    cut = len(lines) - 2 * keep
    across = f" across {n_messages} messages" if n_messages > 1 else ""
    return "\n".join(lines[:keep] + ["", f"[... {cut} lines{across} ...]", ""] + lines[-keep:])


def render_blocks(turns, compact=0):
    runs = agent_runs(turns) if compact else [(r, t, 1) for r, t in turns]
    blocks = []
    for role, text, n in runs:
        if compact and role == "assistant":
            text = elide_middle(text, compact, n)
        label = "User" if role == "user" else "Assistant"
        blocks.append(f"---\n\n# {label}\n\n---\n\n{text}\n")
    return "\n".join(blocks)


def render_md(records, compact=0):
    return render_blocks(turns_of(records), compact)


# --- Codex desktop tasks -----------------------------------------------------
#
# `state_5.sqlite` carries the task names the desktop app shows. The history
# projection beside it carries normalized UI items: a real prompt is a
# `userMessage`, visible agent prose is an `agentMessage`, and tools/reasoning
# are different item types. Reading those two types is the Codex equivalent of
# `extract_message` above, without having to reverse-engineer system/developer
# envelopes from the rollout JSONL.


def _sqlite_readonly(path):
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only = ON")
    return db


def list_codex_sessions(target_cwd):
    """User-titled, non-archived Codex tasks in the named project."""
    cwd = os.path.realpath(os.path.expanduser(target_cwd))
    with _sqlite_readonly(CODEX_STATE_DB) as db:
        rows = db.execute(
            """
            SELECT id, name AS title, recency_at_ms, history_mode, rollout_path
              FROM threads
             WHERE cwd = ?
               AND archived = 0
               AND name IS NOT NULL
               AND name <> ''
               AND (thread_source IS NULL OR thread_source = 'user')
             ORDER BY recency_at_ms DESC, id DESC
            """,
            (cwd,),
        ).fetchall()
    return [dict(row) for row in rows]


def resolve_codex_target(positional, cwd):
    """Resolve one exact task title, or an exact/unique thread-id prefix."""
    sessions = list_codex_sessions(cwd)
    by_title = [s for s in sessions if s["title"] == positional]
    if len(by_title) == 1:
        return by_title[0]
    if len(by_title) > 1:
        sys.stderr.write(
            f"Ambiguous Codex task title {positional!r} ({len(by_title)} matches). "
            "Pass a thread id:\n"
        )
        for s in by_title:
            sys.stderr.write(f"  {s['id']}\n")
        sys.exit(1)
    by_id = [s for s in sessions if s["id"].startswith(positional)]
    if len(by_id) == 1:
        return by_id[0]
    if len(by_id) > 1:
        sys.stderr.write(f"Codex thread-id prefix {positional!r} matches {len(by_id)} tasks:\n")
        for s in by_id:
            sys.stderr.write(f"  {s['id']}  {s['title']}\n")
        sys.exit(1)
    sys.stderr.write(f"No user-titled Codex task {positional!r} in {os.path.realpath(cwd)}.\n")
    sys.stderr.write("Run 'jsonl2md.py list-codex-sessions' to see exact titles.\n")
    sys.exit(1)


# A live thread's sqlite projection lags the conversation badly -- a task an hour
# into its work can project four turns. The rollout JSONL beside it is the source
# of truth and is written as the turn happens, so it is what a reader wanting to
# know what another agent is doing RIGHT NOW has to read. The projection stays as
# the fallback for threads migrated before rollouts were kept.

# Everything the Codex harness posts under the user's name: peer-task envelopes,
# the environment block, the plugin advert, and the body of an invoked skill --
# the counterparts of the slash-command bodies and system reminders the Claude
# renderer drops. The line the user actually typed to invoke a skill is a normal
# user turn and survives.
CODEX_NOISE_PREFIXES = (
    "<codex_delegation>",
    "<environment_context>",
    "<recommended_plugins>",
    "<skill>",
    "<user_instructions>",
) + RELAY_PREFIXES
CODEX_FILE_MANIFEST = re.compile(r"\n?#+ Files mentioned by the user:\n.*\Z", re.S)


def _codex_text(payload, keys=("text",)):
    out = []
    for part in payload.get("content") or []:
        if not isinstance(part, dict):
            continue
        for k in keys:
            if part.get(k):
                out.append(part[k])
    return "\n\n".join(out).strip()


def codex_rollout_files(thread_id, newest_path=None):
    """Every rollout file for one thread, oldest first.

    A resumed task writes a NEW rollout file and `threads.rollout_path` names
    only the latest, so reading that alone loses everything before the resume --
    including, typically, the opening request. The thread id is in each filename,
    which is what joins the set back together.
    """
    paths = sorted(glob.glob(os.path.join(CODEX_HOME, "sessions", "*", "*", "*",
                                          f"rollout-*{thread_id}*.jsonl")))
    if newest_path and newest_path not in paths and os.path.exists(newest_path):
        paths.append(newest_path)
    return paths


SEAM_KEY = 48       # normalized chars compared across a resume boundary
SEAM_WINDOW = 4     # turns either side of the seam to look at


def _norm(text):
    return " ".join(text.replace("\\", "").split())


def _seam_key(role, text):
    """The identity a turn keeps across a resume, or None if it is too short to judge.

    A replayed turn is not byte-identical: the resume re-renders it, so escaping
    and even an expanded path can differ mid-string. What survives is the opening,
    so the seam matches on that -- and only on the seam, where a repeat is a
    replay rather than the user saying the same thing twice.
    """
    key = _norm(text)[:SEAM_KEY]
    return (role, key) if len(key) >= 24 else None


def codex_thread_dialogue(thread_id, newest_path=None):
    """Turns across every rollout file for a thread, spliced at the seams.

    A resume replays the message it resumed from, so the same turn ends one file
    and begins the next -- with different escaping, which is why the seam is
    matched on normalized text rather than equality.
    """
    turns = []
    for path in codex_rollout_files(thread_id, newest_path):
        chunk = codex_rollout_dialogue(path)
        if turns and chunk:
            tail = {k for k in (_seam_key(r, t) for r, t in turns[-SEAM_WINDOW:]) if k}
            while chunk and _seam_key(*chunk[0]) in tail:
                chunk.pop(0)
        turns.extend(chunk)
    return turns


def codex_rollout_dialogue(rollout_path):
    """Every visible human/agent turn from a Codex rollout JSONL, in order.

    Dropped, for the same reason the Claude renderer drops them: `developer`
    context, reasoning, tool calls and their output, the `agent_message` traffic
    between an orchestrator and its own subagents (encrypted, and not this
    conversation), peer `<codex_delegation>` envelopes, the harness's
    `<environment_context>` block, and the attachment manifest it appends under
    the user's name.
    """
    turns = []
    with open(rollout_path, "r", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("type") != "response_item":
                continue
            payload = obj.get("payload") or {}
            if payload.get("type") != "message":
                continue        # agent_message == subagent traffic, not dialogue
            role = payload.get("role")
            if role == "user":
                text = _codex_text(payload)
                if text.startswith(CODEX_NOISE_PREFIXES):
                    continue
                text = CODEX_FILE_MANIFEST.sub("", text).strip()
            elif role == "assistant":
                text = _codex_text(payload)
            else:
                continue        # developer/system context
            if text:
                turns.append((role, text))
    return turns


def codex_dialogue(thread_id, rollout_path=None):
    """Every visible human/agent text item, in rollout order.

    Reads the rollout JSONL when there is one, since the sqlite projection below
    can be many turns behind on a thread that is still working.

    `codex_delegation` is the receiving shape for peer-task traffic. It is a
    normalized `userMessage` because it enters the model as input, but it is not
    something Derek said in the task and does not appear in a clean two-speaker
    transcript.
    """
    turns = codex_thread_dialogue(thread_id, rollout_path)
    if turns:
        return turns
    with _sqlite_readonly(CODEX_HISTORY_DB) as db:
        rows = db.execute(
            """
            SELECT item_json
              FROM thread_items
             WHERE thread_id = ?
               AND item_type IN ('userMessage', 'agentMessage')
             ORDER BY rollout_ordinal
            """,
            (thread_id,),
        ).fetchall()
    turns = []
    for row in rows:
        item = json.loads(row["item_json"])
        if item.get("type") == "userMessage":
            text = "\n\n".join(
                part.get("text", "")
                for part in item.get("content", [])
                if part.get("type") == "text"
            ).strip()
            if text.startswith(CODEX_NOISE_PREFIXES):
                continue
            role = "user"
        elif item.get("type") == "agentMessage":
            text = (item.get("text") or "").strip()
            role = "assistant"
        else:
            continue
        if text:
            turns.append((role, text))
    return turns


def codex_envelope(text, sender, reply_to, reply_label, sent_at=None):
    """Identify the sender, send time, and optional reply route."""
    stamp = datetime.fromtimestamp(time.time() if sent_at is None else sent_at,
                                   timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    body = f"Agent message from {sender or 'unknown'} · sent {stamp}\n\n{text}\n"
    if reply_to:
        command = shlex.join(["python3", os.path.abspath(__file__), "send", reply_to,
                              "<your answer>", "--from", "<your task title>"])
        body += f"\nReply to {reply_label or reply_to}:\n{command}\n"
    return body


def resolve_any_target(positional, cwd, kind=None):
    """Resolve one title across BOTH runtimes.

    Returns {"kind": "claude"|"codex", "id": ..., "label": ...}. The two
    rosters are separate namespaces that happen to share a naming habit, so a
    title present in both is ambiguous and fails loud rather than picking the
    runtime this file happens to check first.
    """
    codex_hit = None
    if kind in (None, "codex"):
        try:
            matches = [s for s in list_codex_sessions(cwd) if s["title"] == positional]
            if len(matches) == 1:
                codex_hit = {"kind": "codex", "id": matches[0]["id"], "label": positional}
            elif len(matches) > 1:
                sys.stderr.write(
                    f"Ambiguous Codex task title {positional!r} ({len(matches)} matches). "
                    "Pass a thread id:\n"
                )
                for s in matches:
                    sys.stderr.write(f"  {s['id']}\n")
                sys.exit(1)
            elif UUID_RE.match(positional or ""):
                by_id = [s for s in list_codex_sessions(cwd) if s["id"] == positional]
                if by_id:
                    codex_hit = {"kind": "codex", "id": positional, "label": by_id[0]["title"]}
        except FileNotFoundError:
            codex_hit = None
    if kind == "codex":
        if codex_hit:
            return codex_hit
        sys.stderr.write(f"No user-titled Codex task {positional!r} in {os.path.realpath(cwd)}.\n")
        sys.stderr.write("Run 'jsonl2md.py list-codex-sessions' to see exact titles.\n")
        sys.exit(1)

    claude_hit = None
    if kind in (None, "claude"):
        sessions = list_sessions(cwd)
        by_title = [s for s in sessions
                    if s.get("title") == positional and s.get("cliSessionId")]
        if len(by_title) == 1:
            claude_hit = {"kind": "claude", "id": by_title[0]["cliSessionId"],
                          "label": by_title[0].get("title")}
        elif len(by_title) > 1:
            sys.stderr.write(
                f"Ambiguous title {positional!r} ({len(by_title)} matches). "
                "Pass a cliSessionId:\n"
            )
            for s in by_title:
                sys.stderr.write(
                    f"  {s['cliSessionId']}  lastActivityAt={s.get('lastActivityAt')}\n"
                )
            sys.exit(1)
        elif UUID_RE.match(positional or "") and os.path.exists(jsonl_path_for(positional, cwd)):
            claude_hit = {"kind": "claude", "id": positional, "label": positional}
        elif is_cloud(positional):
            claude_hit = {"kind": "claude", "id": positional, "label": positional}
        else:
            try:
                cse_id = cloud_ids(positional)[0]      # session_… or bridge:session_…
            except ValueError:
                cse_id = None
            if cse_id:
                claude_hit = {"kind": "claude", "id": cse_id,
                              "label": _label_for_id(cse_id, cwd) or cse_id}

    if claude_hit and codex_hit:
        sys.stderr.write(
            f"{positional!r} names BOTH a Claude session and a Codex task. They are separate\n"
            f"runtimes with separate rosters; say which:\n"
            f"  --kind claude   {claude_hit['id']}\n"
            f"  --kind codex    {codex_hit['id']}\n"
        )
        sys.exit(1)
    if claude_hit:
        return claude_hit
    if codex_hit:
        return codex_hit
    sys.stderr.write(
        f"No session or task named {positional!r} in {os.path.realpath(cwd)}.\n"
        "Run 'jsonl2md.py board' to see both rosters.\n"
    )
    sys.exit(1)


def cmd_list_codex_sessions(args):
    rows = list_codex_sessions(args.cwd)
    width = max((len(s["title"]) for s in rows), default=0)
    for s in rows:
        print(f'{s["title"]:<{width}}  {s["id"]}')


def cmd_export_codex_session(args):
    sessions = list_codex_sessions(args.cwd)
    if args.all:
        targets = sessions
    elif args.title:
        targets = [resolve_codex_target(args.title, args.cwd)]
    else:
        print("export-codex-session: provide a title or --all", file=sys.stderr)
        sys.exit(2)
    if not args.tail:
        os.makedirs(args.out, exist_ok=True)
    for task in targets:
        turns = codex_dialogue(task["id"], task.get("rollout_path"))
        if not turns:
            print(
                f"No projected user/assistant dialogue for {task['title']!r} "
                f"({task['id']}; history mode {task['history_mode']}).",
                file=sys.stderr,
            )
            continue
        if args.tail:
            turns = turns[-args.tail:]
        md = render_blocks(turns, args.compact)
        # --tail is the "just show me the end of it" path the relay uses on a long
        # task, so it goes to stdout: a file would only be read straight back.
        if args.tail:
            sys.stdout.write(md)
            continue
        md_path = os.path.join(args.out, safe_name(task["title"]) + ".md")
        with open(md_path, "w") as f:
            f.write(md)
        print(md_path)


# --- delta / watch: share only what's new since you last shared ---------------
#
# The cursor anchors on the uuid of the last RECORD seen (any record), not the
# last rendered turn, because ~70% of transcript records are tool_use/thinking/
# tool_result plumbing with no text; anchoring on a rendered turn would desync
# the moment a tool call lands between two turns. The cursor only advances on an
# explicit --commit, so it tracks what you actually relayed, not what you merely
# previewed — the human, not the bookmark, stays the switchboard.

CURSOR_ROOT = os.path.expanduser("~/.jsonl2md/cursors")
FIRST_SHARE_WARN = 40  # records; above this, a cursorless delta needs --first-share
UUID_RE = re.compile(r"^[0-9a-fA-F-]{8,}$")


def iter_records_safe(text):
    """Like iter_records, but stop cleanly at a half-written trailing record
    instead of raising — safe to read a transcript being appended to live (its
    final line is often a partially-flushed JSON object)."""
    decoder = json.JSONDecoder()
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        try:
            obj, end = decoder.raw_decode(text, i)
        except ValueError:
            break  # trailing partial record not yet committed; stop here
        yield obj
        i = end


def last_uuid(records):
    """uuid of the last record that carries one — the cursor anchor."""
    u = None
    for obj in records:
        if obj.get("uuid"):
            u = obj["uuid"]
    return u


def split_after_cursor(records, cursor_uuid):
    """Return (tail, found). tail = records strictly after the one whose
    uuid == cursor_uuid. If cursor_uuid is None or absent (compaction / fork /
    /clear minted a new sessionId), found is False and tail is the whole list."""
    records = list(records)
    if cursor_uuid is None:
        return records, False
    for idx, obj in enumerate(records):
        if obj.get("uuid") == cursor_uuid:
            return records[idx + 1:], True
    return records, False


def render_tail(records, k, compact=0):
    """Render only the last k user+assistant exchanges (2k text turns). Slices
    the list of turns, not the rendered string, so a turn whose own text
    contains the '# User' delimiter can't split wrong."""
    turns = turns_of(records)
    if k and k > 0:
        turns = turns[-2 * k:]
    return render_blocks(turns, compact)


def cursor_path(cli_id):
    return os.path.join(CURSOR_ROOT, f"{cli_id}.json")


def read_cursor(cli_id):
    try:
        with open(cursor_path(cli_id)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_cursor(cli_id, uuid, count):
    os.makedirs(CURSOR_ROOT, exist_ok=True)
    tmp = cursor_path(cli_id) + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"uuid": uuid, "count": count}, f)
    os.replace(tmp, cursor_path(cli_id))


def clear_cursor(cli_id):
    try:
        os.remove(cursor_path(cli_id))
    except OSError:
        pass


def resolve_target(positional, cwd):
    """Map a positional (exact user title OR a raw cliSessionId) to
    (cli_session_id, label). Title resolution is restricted to user-titled,
    non-archived sessions, exactly like list-sessions; a raw cliSessionId
    bypasses that filter so untitled/archived sessions stay reachable. Fails
    loud on an ambiguous title rather than silently relaying the wrong thread."""
    sessions = list_sessions(cwd)
    by_title = [s for s in sessions if s.get("title") == positional and s.get("cliSessionId")]
    if len(by_title) == 1:
        return by_title[0]["cliSessionId"], by_title[0].get("title")
    if len(by_title) > 1:
        sys.stderr.write(f"Ambiguous title {positional!r} ({len(by_title)} matches). Pass a cliSessionId:\n")
        for s in by_title:
            sys.stderr.write(f"  {s['cliSessionId']}  lastActivityAt={s.get('lastActivityAt')}\n")
        sys.exit(1)
    if UUID_RE.match(positional) and os.path.exists(jsonl_path_for(positional, cwd)):
        return positional, positional
    if is_cloud(positional):
        return positional, positional
    sys.stderr.write(f"No user-titled session {positional!r} in {cwd}, and not a known cliSessionId.\n")
    sys.stderr.write("Run 'jsonl2md.py list-sessions' to see titles, or pass a cliSessionId.\n")
    sys.exit(1)


def _read_vscode_item(db_path, key):
    """Read one ItemTable value from a VSCode state.vscdb as parsed JSON. Opened
    read-only so it's safe to read while VSCode holds the DB open (WAL readers
    don't block writers). Returns None on any error or missing key."""
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error:
        return None
    try:
        row = con.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    try:
        return json.loads(row[0]) if row else None
    except (ValueError, TypeError):
        return None


def _iter_open_panel_titles(node):
    """Walk the serialized editor layout (memento/workbench.parts.editor),
    yielding (cliSessionId, tabTitle) for every open Claude webview panel. The
    session id lives in the webview's own persisted state ({"sessionID": ...});
    the tab title is exactly what you renamed the session to, updated the moment
    you rename it — so this is the freshest name for a currently-open session."""
    if isinstance(node, dict):
        if node.get("type") == "leaf":
            for e in node.get("data", {}).get("editors", []) or []:
                try:
                    v = json.loads(e.get("value", ""))
                except (ValueError, TypeError):
                    continue
                if v.get("viewType") != "mainThreadWebview-claudeVSCodePanel":
                    continue
                try:
                    sid = json.loads(v.get("state", "")).get("sessionID")
                except (ValueError, TypeError, AttributeError):
                    sid = None
                if sid and v.get("title"):
                    yield sid, v["title"]
        for v in node.values():
            yield from _iter_open_panel_titles(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_open_panel_titles(v)


def vscode_session_names():
    """Read the VSCode extension's own state (every workspace's state.vscdb) and
    return (open_titles, cached_labels), each mapping cliSessionId -> name:

      open_titles   currently-open Claude tabs, keyed by session id from the
                    webview state; the title is your live rename. Small set.
      cached_labels the sessions-sidebar model cache's `label` for every session
                    it remembers — the durable name, used only as a fallback
                    (it can't be told apart from an auto-generated summary, so it
                    never drives which sessions get listed).

    An open tab's title always wins over its cached label."""
    open_titles, cached_labels = {}, {}
    for db in glob.glob(os.path.join(VSCODE_WS_STORAGE, "*", "state.vscdb")):
        cache = _read_vscode_item(db, "agentSessions.model.cache")
        if isinstance(cache, list):
            for e in cache:
                if not isinstance(e, dict):
                    continue
                res, lab = e.get("resource", ""), e.get("label")
                if res.startswith("claude-code:/") and lab:
                    cached_labels.setdefault(res.split("/", 1)[1], lab)
        for sid, title in _iter_open_panel_titles(
                _read_vscode_item(db, "memento/workbench.parts.editor")):
            open_titles[sid] = title
    return open_titles, cached_labels


def peer_addresses():
    """`{sessionId: {"name", "socket", "pid"}}` for every session listening on the
    NATIVE peer channel right now.

    `~/.claude/sessions/<pid>.json` is Claude Code's own registry and it carries the
    same `sessionId` this tool addresses sessions by, so it is the join between the
    two namespaces: the relay knows a session as a title and a uuid, `SendMessage`
    knows it as `name`, and this is where those meet.

    A session is reachable when it has registered a `messagingSocketPath`, that
    socket is still on disk, and its process is still alive. A registry entry
    without one needs to be opened in a current runtime for live delivery.
    An explicit --defer send can use its legacy mailbox."""
    out = {}
    for p in glob.glob(f"{SESSIONS_ROOT}/*.json"):
        try:
            m = json.load(open(p))
        except Exception:
            continue
        sid, sock, pid = m.get("sessionId"), m.get("messagingSocketPath"), m.get("pid")
        if not (sid and sock and os.path.exists(sock)):
            continue
        try:
            os.kill(pid, 0)
        except OSError:
            continue                      # registry outlived the process
        out[sid] = {"name": m.get("name") or sid[:8], "socket": sock, "pid": pid}
    return out


def list_vscode_sessions(target_cwd):
    """VSCode-extension sessions for target_cwd, titled by the name YOU gave them
    in VSCode so they're addressable interchangeably (e.g. `relay Garbage`).

    Membership is the set of sessions you currently have going — running
    claude-vscode processes (~/.claude/sessions/<pid>.json) plus any open Claude
    tab — never the full sidebar history, so the list stays as curated as the
    desktop titled list. Each is named from the VSCode extension's live state:
    the open-tab rename, else the sidebar label, else a synthesized
    'VSCode Extension - <id8>' if it was never named. Shaped like a desktop
    session so export/delta/watch/send treat it identically; lastActivityAt is
    the transcript mtime. A session id whose transcript isn't under target_cwd
    is dropped (that's the cwd filter)."""
    open_titles, cached_labels = vscode_session_names()
    ids = set(open_titles)
    for p in glob.glob(f"{SESSIONS_ROOT}/*.json"):
        try:
            m = json.load(open(p))
        except Exception:
            continue
        if m.get("entrypoint") == "claude-vscode" and m.get("cwd") == target_cwd and m.get("sessionId"):
            ids.add(m["sessionId"])
    out = []
    for sid in ids:
        try:
            last = int(os.path.getmtime(jsonl_path_for(sid, target_cwd)) * 1000)
        except OSError:
            continue  # no transcript under target_cwd -> not this project's session
        out.append({
            "cliSessionId": sid,
            "cwd": target_cwd,
            "title": open_titles.get(sid) or cached_labels.get(sid) or f"VSCode Extension - {sid[:8]}",
            "titleSource": "vscode",
            "isArchived": False,
            "lastActivityAt": last,
        })
    return out


class TranscriptError(Exception):
    """A transcript that could not be read -- a missing file, or a cloud read the
    network could not answer. Listing swallows it: an unreachable server must not
    hide the sessions that ARE on this disk. Export and delta let it out, because
    you named one session, and a silent empty transcript would read as 'nothing
    was said'."""


def _cc_credential_store():
    """Where Claude Code keeps its OAuth grant, as (kind, handle).

    The Keychain item is addressed by service AND account, and the account is
    your login name, not the service string. Writing to the wrong account makes
    a second item that `security` will never hand back -- so the account is read
    off the existing item rather than assumed."""
    out = subprocess.run(["security", "find-generic-password", "-s", CC_KEYCHAIN_SERVICE],
                         capture_output=True, text=True)
    if out.returncode == 0:
        acct = re.search(r'"acct"<blob>="([^"]*)"', out.stdout)
        if acct:
            return "keychain", acct.group(1)
    if os.path.exists(CC_CREDENTIALS_FILE):
        return "file", CC_CREDENTIALS_FILE
    raise TranscriptError(
        "no Claude Code OAuth grant found (Keychain item %r, or %s). "
        "Run `claude` once to sign in." % (CC_KEYCHAIN_SERVICE, CC_CREDENTIALS_FILE))


def _cc_credentials_read(kind, handle):
    if kind == "file":
        return json.load(open(handle))
    raw = subprocess.run(
        ["security", "find-generic-password", "-s", CC_KEYCHAIN_SERVICE, "-a", handle, "-w"],
        capture_output=True, text=True, check=True).stdout
    return json.loads(raw)


def _cc_credentials_write(kind, handle, cred):
    """Persist a refreshed grant. The refresh token rotates on every use, so the
    new one has to land where the CLI will look for it -- keeping the old one
    would leave the CLI holding a token the server has already retired."""
    if kind == "file":
        tmp = handle + ".tmp"
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            json.dump(cred, f)
        os.replace(tmp, handle)
        return
    subprocess.run(["security", "add-generic-password", "-U",
                    "-s", CC_KEYCHAIN_SERVICE, "-a", handle, "-w", json.dumps(cred)],
                   check=True, capture_output=True)


def _safe_storage_decrypt(b64):
    """Electron safeStorage on macOS: `v10` + AES-128-CBC under the app's
    Keychain password, PKCS7 padded, no digest prefix (unlike a cookie)."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    raw = base64.b64decode(b64)
    if raw[:3] not in (b"v10", b"v11"):
        raise ValueError("not a safeStorage blob")
    d = Cipher(algorithms.AES(_claude_app_aes_key()), modes.CBC(b" " * 16),
               backend=default_backend()).decryptor()
    pt = d.update(raw[3:]) + d.finalize()
    return pt[:-pt[-1]].decode("utf-8")


def grant_key_fields(key):
    """`acct:<account>|<client>:<org>:<api host>:<scopes>` -> (client, org, scopes).
    The host carries colons and the scopes carry spaces, so it is split by shape."""
    _, _, tail = key.partition("|")
    try:
        client, org, rest = tail.split(":", 2)
    except ValueError:
        return None, None, ()
    m = re.match(r"^(https?://[^/:\s]+(?::\d+)?):(.*)$", rest)
    scopes = tuple((m.group(2) if m else rest).split())
    return client, org, scopes


def pick_desktop_grant(cache, now_ms, client_id=CLOUD_CLIENT_ID, scope=CLOUD_SCOPE):
    """The desktop app's Claude Code grant: the entry minted for the CLI's
    client id carrying the sessions scope, unexpired, freshest first. None
    when the app holds nothing usable, which is the signal to fall back."""
    best = None
    for key, entry in (cache or {}).items():
        if not isinstance(entry, dict) or not entry.get("token"):
            continue
        client, org, scopes = grant_key_fields(key)
        if client != client_id or scope not in scopes:
            continue
        expires = entry.get("expiresAt") or 0
        if expires <= now_ms + 60_000:
            continue
        if best is None or expires > best["expiresAt"]:
            best = {"token": entry["token"], "expiresAt": expires, "org": org}
    return best


_DESKTOP_GRANT = {}


def _desktop_grant():
    """The desktop app's live grant, read once per process; `(grant, reason)`."""
    if "value" in _DESKTOP_GRANT:
        return _DESKTOP_GRANT["value"]
    grant, reason = None, ""
    try:
        cfg = json.load(open(DESKTOP_CONFIG))
        cache = {}
        for key in DESKTOP_TOKEN_KEYS:
            if cfg.get(key):
                cache.update(json.loads(_safe_storage_decrypt(cfg[key])))
        if not cache:
            reason = "the desktop app has no token cache (not signed in to the Code tab?)"
        else:
            grant = pick_desktop_grant(cache, time.time() * 1000)
            if grant is None:
                reason = "the desktop app's Claude Code grant is expired (open the Claude app signed in)"
    except FileNotFoundError:
        reason = "no desktop app config at %s" % DESKTOP_CONFIG
    except Exception as exc:  # keychain refusal, undecryptable blob, malformed cache
        reason = f"desktop token cache unreadable: {exc}"
    _DESKTOP_GRANT["value"] = (grant, reason)
    return grant, reason


def _org_uuid():
    """The organisation the grant acts under, as the CLI resolves it."""
    env = os.environ.get("CLAUDE_CODE_ORGANIZATION_UUID")
    if env:
        return env
    try:
        org = (json.load(open(CLAUDE_JSON)).get("oauthAccount") or {}).get("organizationUuid")
        if org:
            return org
    except Exception:
        pass
    grant, _ = _desktop_grant()
    return (grant or {}).get("org")


def _cloud_token():
    """A live access token: the desktop app's, then the Keychain grant.

    The desktop app keeps its own grant fresh for the sessions it runs, so it
    is read as-is. The Keychain grant is refreshed here when it has aged out;
    tokens last eight hours and a tree of sessions runs for days, so expiry is
    the normal case, not the error case."""
    grant, why = _desktop_grant()
    if grant:
        return grant["token"]
    try:
        kind, handle = _cc_credential_store()
    except TranscriptError as exc:
        raise TranscriptError(f"{why}; and {exc}")
    cred = _cc_credentials_read(kind, handle)
    oauth = cred.get("claudeAiOauth") or {}
    if not oauth.get("accessToken"):
        raise TranscriptError("stored Claude Code grant has no access token; run `claude` to sign in.")
    if oauth.get("expiresAt", 0) > (time.time() + 60) * 1000:
        return oauth["accessToken"]
    if not oauth.get("refreshToken"):
        raise TranscriptError("Claude Code access token expired and no refresh token is stored.")
    body = json.dumps({"grant_type": "refresh_token",
                       "refresh_token": oauth["refreshToken"],
                       "client_id": CLOUD_CLIENT_ID}).encode()
    req = Request(CLOUD_TOKEN_URL, data=body,
                  headers={"Content-Type": "application/json", "User-Agent": CLOUD_UA})
    try:
        with urlopen(req, timeout=30) as resp:
            tok = json.loads(resp.read())
    except Exception as exc:
        raise TranscriptError(f"OAuth refresh failed: {exc}")
    oauth["accessToken"] = tok["access_token"]
    if tok.get("refresh_token"):
        oauth["refreshToken"] = tok["refresh_token"]
    if tok.get("expires_in"):
        oauth["expiresAt"] = int(time.time() * 1000) + int(tok["expires_in"]) * 1000
    if tok.get("scope"):
        oauth["scopes"] = tok["scope"].split()
    cred["claudeAiOauth"] = oauth
    _cc_credentials_write(kind, handle, cred)
    return oauth["accessToken"]


def _cloud_get(path):
    req = Request(CLOUD_API + path, headers={
        "Authorization": f"Bearer {_cloud_token()}",
        "anthropic-version": "2023-06-01",
        "Accept": "application/json",
        "User-Agent": CLOUD_UA,
    })
    try:
        with urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except TranscriptError:
        raise
    except Exception as exc:
        raise TranscriptError(f"GET {path}: {exc}")


REPO_URL_RE = re.compile(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$")
ORIGIN_SECTION_RE = re.compile(r'\[remote "origin"\](.*?)(?=^\[|\Z)', re.S | re.M)
ORIGIN_URL_RE = re.compile(r"^\s*url\s*=\s*(\S+)", re.M)


def _origin_url(cwd):
    """origin's URL out of `.git/config`, without spawning git.

    This runs on every list, and a subprocess costs more than the whole rest of
    the listing put together. `.git` as a FILE is a worktree or a submodule
    pointing somewhere else -- that indirection is git's to resolve, so those
    fall through to git itself."""
    d = os.path.abspath(cwd)
    while True:
        git = os.path.join(d, ".git")
        if os.path.isdir(git):
            try:
                text = open(os.path.join(git, "config"), errors="replace").read()
            except OSError:
                return None
            section = ORIGIN_SECTION_RE.search(text)
            url = ORIGIN_URL_RE.search(section.group(1)) if section else None
            return url.group(1) if url else None
        if os.path.exists(git):
            return None
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def project_repo(cwd):
    """`owner/name` of the checkout at cwd, which is the only thing a cloud
    session and a local directory have in common: the cloud worker has no cwd,
    it has the repository it was pointed at."""
    url = _origin_url(cwd)
    if url is None:
        out = subprocess.run(["git", "-C", cwd, "remote", "get-url", "origin"],
                             capture_output=True, text=True)
        if out.returncode != 0:
            return None
        url = out.stdout.strip()
    m = REPO_URL_RE.search(url)
    return m.group(1) if m else None


def _cloud_session_repos(session):
    cfg = session.get("config") or {}
    repos = set()
    for src in cfg.get("sources") or []:
        m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", src.get("url") or "")
        if m:
            repos.add(m.group(1))
    for out in cfg.get("outcomes") or []:
        repo = (out.get("git_info") or {}).get("repo")
        if repo:
            repos.add(repo)
    return repos


def _cloud_cache(name):
    os.makedirs(CLOUD_CACHE_ROOT, exist_ok=True)
    return os.path.join(CLOUD_CACHE_ROOT, name)


def cloud_sessions(force=False, max_age=CLOUD_LIST_TTL):
    """Every live (active or paused) cloud record on the account, cached for a
    minute. Archived ones are left on the server: the account carries a
    thousand of them and nothing here addresses one.

    The cache is what lets `list-sessions` and `situation` stay as fast as they
    were when every session was a file: one request per minute, and a stale copy
    is served rather than nothing when the network or the grant is gone -- said
    so on stderr, because a silent stale roster reads as a current one."""
    cache = _cloud_cache("sessions.json")
    if not force:
        try:
            age = time.time() - os.path.getmtime(cache)
            if age < max_age:
                return json.load(open(cache))
        except (OSError, ValueError):
            pass
    try:
        data, cursor = [], None
        for _ in range(20):
            q = "/v1/code/sessions?limit=200&statuses=active&statuses=paused"
            page = _cloud_get(q + (f"&cursor={cursor}" if cursor else ""))
            data.extend(page.get("data", []))
            cursor = page.get("next_cursor")
            if not cursor:
                break
    except TranscriptError as exc:
        try:
            stale = json.load(open(cache))
            age = time.time() - os.path.getmtime(cache)
            sys.stderr.write(f"[cloud] session list failed ({exc}); serving the copy from "
                             f"{ago(age)} ago\n")
            return stale
        except (OSError, ValueError):
            raise exc
    tmp = cache + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, cache)
    return data


def _local_bridge_ids():
    """The cloud records that front sessions on THIS machine, by bare id. Every
    desktop session is mirrored to one (its `bridgeSessionIds`), and so is a
    CLI that registered a peer socket (`bridgeSessionId`)."""
    ids = set()
    for p in glob.glob(f"{META_ROOT}/*/*/local_*.json") + glob.glob(f"{SESSIONS_ROOT}/*.json"):
        try:
            m = json.load(open(p))
        except Exception:
            continue
        for b in (m.get("bridgeSessionIds") or []) + [m.get("bridgeSessionId")]:
            if b:
                ids.add(re.sub(r"^(?:session|cse)_", "", b))
    return ids


def list_cloud_sessions(target_cwd):
    """Cloud records for this project that are NOT sessions on this machine,
    shaped like a desktop session so every verb downstream treats them alike.

    Two kinds. `anthropic_cloud`: a session running on Anthropic's machines.
    `bridge`: a session bridged through Remote Control -- one of those exists
    for every session running HERE too, and that one is already listed from
    its own metadata and its own transcript, so only a bridge record no local
    session claims (a live session on another computer) is listed."""
    if os.environ.get("JSONL2MD_NO_CLOUD"):
        return []
    repo = project_repo(target_cwd)
    if not repo:
        return []
    try:
        sessions = cloud_sessions()
    except (TranscriptError, OSError, ValueError):
        return []
    local = None
    out = []
    for s in sessions:
        kind = s.get("environment_kind")
        if s.get("status") == "archived" or kind not in ("anthropic_cloud", "bridge"):
            continue
        if repo not in _cloud_session_repos(s):
            continue
        if kind == "bridge":
            if s.get("connection_status") != "connected":
                continue
            local = _local_bridge_ids() if local is None else local
            if s["id"][4:] in local:
                continue
        out.append({
            "cliSessionId": s["id"],
            "cwd": target_cwd,
            "title": s.get("title") or f"Cloud - {s['id'][4:12]}",
            "titleSource": "cloud",
            "isArchived": False,
            "lastActivityAt": int((epoch_of(s.get("last_event_at")
                                             or s.get("created_at")) or 0) * 1000),
            "cloudLastEventAt": s.get("last_event_at"),
            "cloudKind": "cloud" if kind == "anthropic_cloud" else "remote",
            "cloudWorker": s.get("worker_status"),
            "cloudInbound": (s.get("external_metadata") or {}).get("cross_session_inbound"),
        })
    return out


def cloud_reach(session):
    """How a caller reaches a cloud row: the native address for a Claude
    caller, the script verb for anyone else, and what kind of thing it is."""
    kind = session.get("cloudKind") or "cloud"
    where = "in the cloud, cannot reply" if kind == "cloud" else "on another machine"
    if session.get("cloudInbound") == "unavailable":
        where += ", refuses peer messages"
    if caller_has_peer_channel():
        return f"SendMessage to: {cloud_address(session['cliSessionId'])}  ({where})"
    return f'send "{session.get("title")}"  ({where})'


def cloud_events(cse_id, after=None):
    """Raw events, oldest first, from `after` (a sequence number) onward.

    The stream is the session's whole protocol -- control traffic, worker logs,
    tool progress -- and the two types that carry what was said are the ones
    named for who said it."""
    events, cursor = [], after
    while True:
        q = f"/v1/code/sessions/{cse_id}/events?limit=200&sort_order=asc"
        if cursor is not None:
            q += f"&cursor={cursor}"
        page = _cloud_get(q)
        batch = page.get("data") or []
        events.extend(batch)
        cursor = page.get("next_cursor")
        if not batch or cursor is None:
            return events


def cloud_to_records(events):
    """Cloud event payloads are Claude Code transcript records already -- same
    `message`, same roles, same uuids. The one thing that differs is spelling:
    the flags marking a user record as machine-written come back snake_cased,
    and `user_speech` reads them camelCased."""
    alias = {"tool_use_result": "toolUseResult", "is_sidechain": "isSidechain",
             "is_meta": "isMeta", "parent_tool_use_id": "parentToolUseId"}
    out = []
    for e in events:
        if e.get("event_type") not in ("user", "assistant"):
            continue
        rec = dict(e.get("payload") or {})
        for snake, camel in alias.items():
            if snake in rec and camel not in rec:
                rec[camel] = rec.pop(snake)
        out.append(rec)
    return out


def cloud_records(cse_id, last_event_at=None):
    """A cloud session's transcript as records, cached against re-download.

    The session's own `last_event_at` is the cache key -- a transcript that has
    not gained an event cannot have changed, so there is no interval to guess
    at and no staleness to age out."""
    cache = _cloud_cache(f"{cse_id}.json")
    if last_event_at:
        try:
            blob = json.load(open(cache))
            if blob.get("last_event_at") == last_event_at:
                return blob["records"]
        except (OSError, ValueError, KeyError):
            pass
    records = cloud_to_records(cloud_events(cse_id))
    if last_event_at:
        tmp = cache + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"last_event_at": last_event_at, "records": records}, f)
        os.replace(tmp, cache)
    return records


def is_cloud(cli_id):
    return bool(cli_id and CLOUD_ID_RE.match(cli_id))


def session_for(cli_id, cwd):
    """The listed session record for an id, or a bare stand-in for one that is
    not listed (a raw id for an untitled or archived session). Carrying the
    record rather than the id alone is what lets a cloud read reuse its cache:
    the cache key is the session's `last_event_at`, which only the record has."""
    for s in list_sessions(cwd):
        if s.get("cliSessionId") == cli_id:
            return s
    return {"cliSessionId": cli_id, "cwd": cwd, "title": cli_id}


def records_of(session):
    """Every read verb wants the same thing from a session -- its records --
    and only this function knows whether that means opening a file or asking
    the API for one."""
    cli_id = session.get("cliSessionId")
    if is_cloud(cli_id):
        return cloud_records(cli_id, session.get("cloudLastEventAt"))
    path = jsonl_path_for(cli_id, session["cwd"])
    if not os.path.exists(path):
        raise TranscriptError(f"missing transcript: {path}")
    return list(iter_records_safe(open(path, errors="replace").read()))


def list_sessions(target_cwd):
    out = []
    for p in glob.glob(f"{META_ROOT}/*/*/local_*.json"):
        try:
            m = json.load(open(p))
        except Exception:
            continue
        if m.get("cwd") != target_cwd:
            continue
        if m.get("isArchived"):
            continue
        if m.get("titleSource") != "user":
            continue
        out.append(m)
    # VSCode-extension sessions have no desktop title record; fold them in so
    # they list and export too, deduped against any desktop entry for the same id.
    seen = {m.get("cliSessionId") for m in out}
    out.extend(s for s in list_vscode_sessions(target_cwd) if s["cliSessionId"] not in seen)
    # Sessions running on Anthropic's machines are in this project too. They have
    # no metadata file and no transcript here, so the API is the only place they
    # can come from, and without this they are invisible to every verb.
    out.extend(list_cloud_sessions(target_cwd))
    out.sort(key=lambda m: m.get("lastActivityAt", 0), reverse=True)
    return out


def jsonl_path_for(cli_session_id, cwd):
    return os.path.join(JSONL_ROOT, cwd.replace("/", "-"), f"{cli_session_id}.jsonl")


def safe_name(name):
    return re.sub(r"[/\\:]+", "_", name).strip()


def _claude_app_aes_key():
    pw = subprocess.run(
        ["security", "find-generic-password", "-wa", KEYCHAIN_ACCOUNT, "-s", KEYCHAIN_SERVICE],
        capture_output=True, text=True, check=True,
    ).stdout.strip().encode()
    return hashlib.pbkdf2_hmac("sha1", pw, b"saltysalt", 1003, 16)


def _decrypt_cookie(encrypted, key):
    # Chromium v10/v11 format on macOS: 3-byte version prefix, then AES-128-CBC
    # ciphertext (IV = 16 spaces). Plaintext is 32-byte SHA-256 prefix + value.
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    body = encrypted[3:]
    d = Cipher(algorithms.AES(key), modes.CBC(b" " * 16), backend=default_backend()).decryptor()
    pt = d.update(body) + d.finalize()
    return pt[32:-pt[-1]].decode("utf-8", errors="replace")


def _claude_ai_credentials():
    key = _claude_app_aes_key()
    db = sqlite3.connect(COOKIE_DB)
    rows = db.execute(
        "SELECT name, value, encrypted_value FROM cookies WHERE host_key LIKE '%claude.ai%'"
    ).fetchall()
    cookies = {}
    for name, value, enc in rows:
        cookies[name] = value if value else _decrypt_cookie(enc, key)
    return cookies


def _claude_ai_get(path, cookies):
    org = cookies["lastActiveOrg"]
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    url = f"https://claude.ai/api/organizations/{org}{path}"
    req = Request(url, headers={
        "Cookie": cookie_header,
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://claude.ai/",
        "Origin": "https://claude.ai",
    })
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def list_chats(limit):
    return _claude_ai_get(f"/chat_conversations?limit={limit}", _claude_ai_credentials())


def fetch_chat(uuid, cookies=None):
    cookies = cookies or _claude_ai_credentials()
    return _claude_ai_get(
        f"/chat_conversations/{uuid}?tree=True&rendering_mode=messages&render_all_tools=true",
        cookies,
    )


def chat_to_records(chat):
    for m in chat.get("chat_messages", []):
        role = "user" if m.get("sender") == "human" else "assistant"
        text = "\n\n".join(c.get("text", "") for c in m.get("content", []) if c.get("type") == "text")
        yield {"message": {"role": role, "content": text}}


def cmd_list_sessions(args):
    peers = peer_addresses()
    rows = list_sessions(args.cwd)
    width = max((len(s["title"]) for s in rows), default=0)
    for s in rows:
        peer = peers.get(s["cliSessionId"])
        if peer:
            print(f'{s["title"]:<{width}}  → SendMessage to: {peer["name"]}')
        elif is_cloud(s.get("cliSessionId")):
            print(f'{s["title"]:<{width}}  → {cloud_reach(s)}')
        else:
            print(f'{s["title"]:<{width}}  → no live receiver (--defer for legacy mailbox)')


# --- recent-prompts: what you said last, and where it is ----------------------
#
# The transcripts are the only record of your side of the work that carries a
# timestamp. Reading the last things you asked for, newest first and across
# every session at once, is how you see what you are actually driving at right
# now -- which is not the same question as what any one session is doing.


def iter_located(text):
    """Like iter_records_safe, but yields (record, line) -- the 1-based line the
    record starts on, so a prompt can be pointed at where it lives on disk."""
    decoder = json.JSONDecoder()
    i, n, line = 0, len(text), 1
    while i < n:
        while i < n and text[i].isspace():
            line += text[i] == "\n"
            i += 1
        if i >= n:
            break
        try:
            obj, end = decoder.raw_decode(text, i)
        except ValueError:
            break  # trailing partial record; a live session is mid-write
        yield obj, line
        line += text.count("\n", i, end)
        i = end


def local_time(ts):
    """Transcript timestamps are UTC; you live in one timezone and remember the
    hour you typed something, so they print local."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime(
            "%Y-%m-%d %H:%M:%S %z")
    except (AttributeError, ValueError):
        return ts or "(undated)"


def session_prompts(session):
    """Every human turn in one session, oldest first, each with its timestamp
    and its location. A session whose transcript is gone contributes none.

    A cloud session's transcript has no line to point at, so its prompts carry
    the cache file they were read out of and their index within it."""
    if is_cloud(session.get("cliSessionId")):
        try:
            records = cloud_records(session["cliSessionId"], session.get("cloudLastEventAt"))
        except (TranscriptError, OSError, ValueError):
            return []
        located = [(obj, i + 1) for i, obj in enumerate(records)]
        path = _cloud_cache(f"{session['cliSessionId']}.json")
    else:
        path = jsonl_path_for(session["cliSessionId"], session["cwd"])
        try:
            text = open(path, errors="replace").read()
        except OSError:
            return []
        located = iter_located(text)
    out = []
    for obj, line in located:
        if obj.get("type") != "user":
            continue
        role, said = extract_message(obj)
        if role != "user" or not said:
            continue
        out.append({
            "when": obj.get("timestamp"),
            "session": session.get("title"),
            "path": path,
            "line": line,
            "uuid": obj.get("uuid"),
            "text": said,
        })
    return out


DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([smhdw]?)$", re.I)
DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "": 3600}


def parse_duration(text):
    """'90m', '2h', '1d', '3600' -> seconds. A bare number is hours, because the
    window this is asked for is almost always an hour."""
    m = DURATION_RE.match(str(text).strip())
    if not m:
        sys.stderr.write(f"unparseable duration {text!r}; use 30s, 90m, 2h, 1d\n")
        sys.exit(2)
    return float(m.group(1)) * DURATION_UNITS[m.group(2).lower()]


def epoch_of(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def ago(seconds):
    """Compact age: 44s, 12m, 3h07m, 2d04h."""
    if seconds is None:
        return "-"
    s = int(max(0, seconds))
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{s // 60}m"
    if s < 172800:
        return f"{s // 3600}h{(s % 3600) // 60:02d}m"
    return f"{s // 86400}d{(s % 86400) // 3600:02d}h"


def dropped_by(exclude, cli, *names):
    """True when --exclude names this session, by cliSessionId prefix or by any
    name it answers to. A titled session answers to its title; an untitled one
    answers to its peer address, which is the only name the board ever printed
    for it. Both callers share this so that a session cannot be excluded from
    one view of the fleet and survive in another."""
    drop = set(exclude or [])
    if not drop:
        return False
    if any(n and n in drop for n in names):
        return True
    return bool(cli) and any(d and cli.startswith(d) for d in drop)


def select_sessions(cwd, exclude):
    """Titled sessions in cwd, minus any named in --exclude (exact title or a
    cliSessionId prefix). A routine that reads its own session sees its own
    prompts as the human's, and finds work it has already done -- excluding
    itself is what makes an automated caller honest."""
    return [s for s in list_sessions(cwd)
            if not dropped_by(exclude, s.get("cliSessionId") or "", s.get("title"))]


def cmd_recent_prompts(args):
    sessions = (select_sessions(args.cwd, args.exclude)
                + untitled_sessions(args.cwd, args.exclude))
    if args.session:
        cli_id, label = resolve_target(args.session, args.cwd)
        sessions = ([s for s in sessions if s.get("cliSessionId") == cli_id]
                    or [{"cliSessionId": cli_id, "cwd": args.cwd, "title": label}])
    prompts = []
    for s in sessions:
        if s.get("cliSessionId"):
            prompts.extend(session_prompts(s))
    if args.since:
        floor = time.time() - parse_duration(args.since)
        prompts = [p for p in prompts if (epoch_of(p["when"]) or 0) >= floor]
    prompts.sort(key=lambda p: p["when"] or "", reverse=True)
    if args.limit > 0:
        prompts = prompts[:args.limit]
    if args.json:
        json.dump(prompts, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0 if prompts else 1
    if not prompts:
        # exit 1, not 0: --since makes this a question with a no answer, and a
        # caller that gates on "did the human say anything" tests the status.
        sys.stderr.write(
            f"no prompts in {args.cwd}"
            + (f" within {args.since}" if args.since else "") + "\n")
        return 1
    for p in prompts:
        text = p["text"]
        if args.chars and len(text) > args.chars:
            text = text[:args.chars].rstrip() + " ..."
        print(f'{local_time(p["when"])}  {p["session"]}')
        print(f'  {p["path"]}:{p["line"]}  {p["uuid"]}')
        for ln in text.split("\n"):
            print(f"  | {ln}" if ln else "  |")
        print()
    return 0


# --- situation: one board, because the two namespaces don't share a name -------
#
# A session is a title to you, a `name` to SendMessage, and a pid to the process
# table, and those three disagree: "Clearances" answers to `homesodamachine-b0`.
# Joining them by name is the mistake waiting to be made, so this joins them by
# cliSessionId, which all three carry. What comes out is the one view an
# automated helper needs before it does anything: who is here, how to reach
# them, whether they are still moving, what they were last asked, and how long
# ago they stopped.


def _peer_idle_module():
    """peer_idle.py is this file's sibling and owns the WORKING/IDLE/FAILED/GONE
    reading. Imported rather than reimplemented; absent, the board still prints
    with the state column blank."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import peer_idle
        return peer_idle
    except Exception:
        return None


def live_states(cwd):
    """Every live session in cwd by id, with the state peer_idle reads off it."""
    pi = _peer_idle_module()
    states = {}
    if pi:
        for sess in pi.live_sessions(cwd):
            row = pi.state_of(sess, cwd)
            if row.get("sessionId"):
                states[row["sessionId"]] = row
    return states


def untitled_sessions(cwd, exclude=None, states=None, peers=None):
    """Live sessions in cwd that were never titled.

    A session is invisible to list-sessions until it is named. That is the right
    default for listing work and the wrong one for every question about who is
    here: it is still a worker, still reachable, and the human still talks to it
    -- a new session is untitled until it earns a name, so the freshest thing he
    said is the likeliest to live in one. Both callers that ask such a question
    read this, and both run it through the same --exclude: a helper is untitled
    by construction, so an exclusion reaching only titled rows would fail for the
    one caller that depends on it, and the helper would read itself as a peer."""
    states = live_states(cwd) if states is None else states
    peers = peer_addresses() if peers is None else peers
    known = {s.get("cliSessionId") for s in list_sessions(cwd)}
    out = []
    for sid in sorted(set(states) | set(peers)):
        if sid in known:
            continue
        name = ((peers.get(sid) or {}).get("name")
                or (states.get(sid) or {}).get("name"))
        if dropped_by(exclude, sid, name):
            continue
        out.append({"cliSessionId": sid, "cwd": cwd, "titleSource": "process",
                    "title": "(" + (name or sid[:8]) + ")"})
    return out


def situation(cwd, exclude=None):
    states = live_states(cwd)
    peers = peer_addresses()
    now = time.time()
    untitled = untitled_sessions(cwd, exclude, states, peers)
    rows = []
    for s in select_sessions(cwd, exclude) + untitled:
        cli = s.get("cliSessionId")
        if not cli:
            continue
        prompts = session_prompts(s)
        last = prompts[-1] if prompts else None
        st = states.get(cli, {})
        rows.append({
            "title": s.get("title"),
            "cliSessionId": cli,
            "cloud": is_cloud(cli),
            "address": (peers.get(cli) or {}).get("name") or (cloud_address(cli) if is_cloud(cli) else None),
            "state": st.get("state", "-"),
            "idle_for": st.get("idle_for") if st.get("state") not in (None, "working") else None,
            "asked_ago": (now - epoch_of(last["when"])) if last and epoch_of(last["when"]) else None,
            "prompts": len(prompts),
            "last_ask": (last or {}).get("text", ""),
            "tail": st.get("tail", ""),
        })
    rows.sort(key=lambda r: (r["asked_ago"] is None, r["asked_ago"] or 0))
    return rows


def cmd_situation(args):
    rows = situation(args.cwd, args.exclude)
    if args.json:
        json.dump(rows, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0 if rows else 1
    if not rows:
        sys.stderr.write(f"no titled sessions in {args.cwd}\n")
        return 1
    def address_of(row):
        return row["address"] or "(relay only)"

    tw = max(len(r["title"] or "") for r in rows)
    aw = max(len(address_of(r)) for r in rows)
    print(f'{"SESSION":<{tw}}  {"ADDRESS":<{aw}}  {"STATE":<8} {"STOPPED":>8} {"ASKED":>8}  LAST')
    for r in rows:
        state = {"working": "working", "idle": "STOPPED", "failed": "FAILED",
                 "gone": "GONE", "unknown": "?"}.get(r["state"], "-")
        stopped = ago(r["idle_for"]) if r["idle_for"] is not None else "-"
        gist = " ".join((r["tail"] or r["last_ask"] or "").split())[:70]
        print(f'{r["title"]:<{tw}}  {address_of(r):<{aw}}  '
              f'{state:<8} {stopped:>8} {ago(r["asked_ago"]):>8}  {gist}')
    return 0


def cmd_board(args):
    """Every agent in this project, both runtimes, and the call that reaches each.

    `situation` answers "who else is here" for Claude. This answers the question
    that has to come first once a second runtime is in the tree: what is the whole
    address space, and which verb reaches which half of it. A Codex task and a
    Claude session are both just a title here; the REACH column is the difference.
    """
    peers = peer_addresses()
    rows = []
    for s in list_sessions(args.cwd):
        cli = s.get("cliSessionId")
        if not cli or cli in (args.exclude or []):
            continue
        if is_cloud(cli):
            reach = cloud_reach(s)
        elif peers.get(cli):
            reach = (f'SendMessage to: {peers[cli]["name"]}' if caller_has_peer_channel()
                     else f'send "{s.get("title")}" (live)')
        else:
            reach = "(no live receiver)"
        rows.append(("claude", s.get("title") or cli[:8], reach,
                     _ms_stamp(s.get("lastActivityAt"))))
    try:
        for t in list_codex_sessions(args.cwd):
            reach = (f'send_message_to_thread threadId: {t["id"]}' if caller_is_codex()
                     else f'send "{t["title"]}"')
            rows.append(("codex", t["title"], reach,
                         _ms_stamp(t.get("recency_at_ms"))))
    except FileNotFoundError:
        sys.stderr.write("[board] no Codex state db found; listing Claude only.\n")
    if args.json:
        json.dump([{"runtime": r, "title": t, "reach": a, "last": w} for r, t, a, w in rows],
                  sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0 if rows else 1
    if not rows:
        sys.stderr.write(f"nothing titled in {args.cwd}\n")
        return 1
    rw = max([len(r[0]) for r in rows] + [len("RUNTIME")])
    tw = max([len(r[1]) for r in rows] + [len("TITLE")])
    aw = max([len(r[2]) for r in rows] + [len("REACH IT WITH")])
    print(f'{"RUNTIME":<{rw}}  {"TITLE":<{tw}}  {"REACH IT WITH":<{aw}}  LAST')
    for runtime, title, reach, when in rows:
        print(f"{runtime:<{rw}}  {title:<{tw}}  {reach:<{aw}}  {when}")
    return 0


def _ms_stamp(ms):
    """Epoch-ms (Codex `recency_at_ms`, Claude `lastActivityAt`) to a readable stamp.

    Claude metadata has carried `lastActivityAt` as both an int and an ISO string
    across builds, so a non-numeric value is passed through rather than dropped.
    """
    if not ms:
        return ""
    if isinstance(ms, str):
        if not ms.isdigit():
            return ms[:16].replace("T", " ")
        ms = int(ms)
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def cmd_list_chats(args):
    for c in list_chats(args.limit):
        print(c.get("name") or "(untitled)")


def cmd_export_session(args):
    sessions = list_sessions(args.cwd)
    if args.all:
        targets = sessions
    elif args.title:
        targets = [s for s in sessions if s["title"] == args.title]
        if not targets:
            # fall back to a raw cliSessionId (full or unique prefix) — how you
            # name a VSCode-extension session without typing its synthesized title
            targets = [s for s in sessions if s.get("cliSessionId", "").startswith(args.title)]
            if len(targets) > 1:
                print(f"{args.title!r} matches {len(targets)} sessions by id prefix; be more specific:", file=sys.stderr)
                for s in targets:
                    print(f"  {s.get('cliSessionId')}  {s['title']}", file=sys.stderr)
                sys.exit(1)
        if not targets:
            print(f"No session titled {args.title!r} (or with that cliSessionId) in {args.cwd}", file=sys.stderr)
            sys.exit(1)
    else:
        print("export-session: provide a title or --all", file=sys.stderr)
        sys.exit(2)
    os.makedirs(args.out, exist_ok=True)
    for s in targets:
        cli_id = s.get("cliSessionId")
        if not cli_id:
            print(f"missing cliSessionId in metadata: {s.get('title')!r}", file=sys.stderr)
            continue
        try:
            records = records_of(s)
        except TranscriptError as exc:
            print(exc, file=sys.stderr)
            continue
        md = render_md(records, args.compact)
        base = safe_name(s["title"])
        md_path = os.path.join(args.out, base + ".md")
        with open(md_path, "w") as f:
            f.write(md)
        print(md_path)


def cmd_export_chat(args):
    cookies = _claude_ai_credentials()
    chats = list_chats(args.limit)
    if args.all:
        targets = chats
    elif args.name:
        targets = [c for c in chats if (c.get("name") or "") == args.name]
        if not targets:
            print(
                f"No chat named {args.name!r} in the top {args.limit}. "
                f"Try 'jsonl2md.py list-chats --limit N' to widen the search.",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        print("export-chat: provide a name or --all", file=sys.stderr)
        sys.exit(2)
    os.makedirs(args.out, exist_ok=True)
    for c in targets:
        chat = fetch_chat(c["uuid"], cookies)
        md = render_md(chat_to_records(chat))
        base = safe_name(c.get("name") or c["uuid"])
        md_path = os.path.join(args.out, base + ".md")
        with open(md_path, "w") as f:
            f.write(md)
        print(md_path)


def cmd_render(args):
    text = open(args.path).read() if args.path else sys.stdin.read()
    sys.stdout.write(render_md(iter_records(text), args.compact))


def cmd_delta(args):
    cli_id, label = resolve_target(args.title, args.cwd)
    try:
        records = records_of(session_for(cli_id, args.cwd))
    except TranscriptError as exc:
        sys.stderr.write(f"{exc}\n")
        sys.exit(1)
    total = len(records)
    file_last = last_uuid(records)

    if args.reset:
        clear_cursor(cli_id)

    if args.tail is not None:
        md = render_tail(records, args.tail, args.compact)
        sys.stdout.write(md + ("\n" if md and not md.endswith("\n") else ""))
        sys.stderr.write(f"[tail {args.tail}] {label} — cursor untouched ({cli_id})\n")
        return

    cur = None if args.reset else read_cursor(cli_id)
    cursor_uuid = cur.get("uuid") if cur else None
    tail, found = split_after_cursor(records, cursor_uuid)

    if cursor_uuid is None and not args.reset and total > FIRST_SHARE_WARN and not args.first_share:
        sys.stderr.write(
            f"No cursor for {label} ({cli_id}); a delta now would emit the ENTIRE "
            f"{total}-record transcript.\n"
            f"  --first-share  emit it all and set this as the baseline\n"
            f"  --tail K       just grab the last K exchanges instead\n")
        sys.exit(2)
    if cursor_uuid is not None and not found:
        sys.stderr.write(
            f"Cursor {cursor_uuid} not in {label} (compaction / fork / clear?); "
            f"emitting the whole transcript. Re-run with --reset to rebaseline.\n")

    md = render_md(tail, args.compact)
    if md.strip():
        sys.stdout.write(md + ("\n" if not md.endswith("\n") else ""))
    else:
        sys.stderr.write(f"(no new user/assistant turns since last share; cursor at {cursor_uuid})\n")

    if args.commit:
        write_cursor(cli_id, file_last, total)
        sys.stderr.write(f"[committed] {label} cursor -> {file_last} ({total} records)\n")
    else:
        sys.stderr.write(
            f"[preview] {label} not marked shared. To mark these as relayed: "
            f"jsonl2md.py delta {args.title!r} --commit\n")


def cloud_head_sequence(cse_id):
    """The newest event's sequence number, in one request. This is where a watch
    starts: a cloud watch streams what is said from now on, and finding 'now'
    must not mean downloading the whole session to look at its last line."""
    page = _cloud_get(f"/v1/code/sessions/{cse_id}/events?limit=1&sort_order=desc")
    data = page.get("data") or []
    return data[0].get("sequence_num") if data else None


def watch_cloud(cse_id, label, interval):
    """Tail a cloud session. The local watch polls a file's size because that is
    what changes when a session speaks; here the sequence number is that same
    signal, and asking for events after it returns the new turns and nothing
    else -- so the poll costs one small request whether or not anything was said."""
    cursor = cloud_head_sequence(cse_id)
    sys.stderr.write(f"[watch] {label}: cloud session, streaming NEW turns from now. Ctrl-C to stop.\n")
    try:
        while True:
            events = cloud_events(cse_id, after=cursor)
            if events:
                cursor = events[-1].get("sequence_num")
                md = render_md(cloud_to_records(events))
                if md.strip():
                    sys.stdout.write(md + ("\n" if not md.endswith("\n") else ""))
                    sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        sys.stderr.write(f"\n[watch] {label}: stopped.\n")
    return 0


def cmd_watch(args):
    cli_id, label = resolve_target(args.title, args.cwd)
    if is_cloud(cli_id):
        return watch_cloud(cli_id, label, args.interval)
    jsonl = jsonl_path_for(cli_id, args.cwd)
    if not os.path.exists(jsonl):
        sys.stderr.write(f"missing transcript: {jsonl}\n")
        sys.exit(1)

    cur = read_cursor(cli_id)
    cursor_uuid = cur.get("uuid") if cur else None
    if cursor_uuid is None:
        cursor_uuid = last_uuid(list(iter_records_safe(open(jsonl).read())))
        sys.stderr.write(f"[watch] {label}: no cursor; streaming only NEW turns from now. Ctrl-C to stop.\n")
    else:
        sys.stderr.write(f"[watch] {label}: resuming from saved cursor. Ctrl-C to stop.\n")

    last_size = -1
    try:
        while True:
            try:
                size = os.path.getsize(jsonl)
            except OSError:
                size = -1
            if size != last_size:
                last_size = size
                records = list(iter_records_safe(open(jsonl).read()))
                file_last = last_uuid(records)
                tail, found = split_after_cursor(records, cursor_uuid)
                if found and tail:
                    md = render_md(tail)
                    if md.strip():
                        sys.stdout.write(md + ("\n" if not md.endswith("\n") else ""))
                        sys.stdout.flush()
                cursor_uuid = file_last  # advance in-memory only; watch never writes the cursor
            time.sleep(args.interval)
    except KeyboardInterrupt:
        sys.stderr.write(f"\n[watch] {label}: stopped (cursor not committed).\n")


def own_session_id(explicit, cwd):
    """The CALLER'S own session — the mailbox `await-reply` watches.

    Never guessed. `send` resolves someone else's session and a wrong answer is loud
    (the message lands in a stranger's context); this resolves the caller's own, and a
    wrong answer is SILENT — you wait forever on a mailbox nobody writes to while the
    reply sits in yours. "The most recently written transcript" is exactly wrong here:
    the agent you are waiting on is the one writing, so freshness picks THEM. So this
    takes a title or an id and nothing else, and the caller's id is discoverable without
    guessing: it is the session-named directory in the scratchpad path the harness gives
    every agent, `/tmp/claude-<uid>/<project>/<SESSION-ID>/scratchpad`."""
    if not explicit:
        env_id = os.environ.get("CLAUDE_SESSION_ID", "").strip()
        if env_id:
            return env_id, env_id
        sys.stderr.write(
            "await-reply needs the session whose mailbox to watch — YOUR OWN, not the one\n"
            "you messaged. Pass its title or cliSessionId. An agent's own id is the\n"
            "session-named directory in its scratchpad path:\n"
            "  /tmp/claude-<uid>/<project>/<SESSION-ID>/scratchpad\n"
            "This is not inferred, because the freshest transcript in a project is the\n"
            "session you are waiting ON, not the one waiting.\n")
        sys.exit(2)
    return resolve_target(explicit, cwd)


def cmd_await_reply(args):
    """Watch explicit legacy --defer replies. Live replies wake the runtime.

    This compatibility watcher does not drain the mailbox or report expired
    messages as replies. Use it in the background only for a legacy receiver.
    """
    cli_id, label = own_session_id(args.title, args.cwd)
    box = os.path.join(RELAY_INBOX_ROOT, cli_id)
    sys.stderr.write(f"[await-reply] watching {label} ({cli_id})\n[await-reply] mailbox: {box}\n")
    deadline = (time.time() + args.timeout) if args.timeout else None
    while True:
        messages = []
        for path in sorted(glob.glob(os.path.join(box, "*.json"))):
            try:
                with open(path) as stream:
                    message = json.load(stream)
                expiry = message.get("expires_at", (message.get("ts") or 0) + DEFERRED_TTL)
                if expiry > time.time() and message.get("text"):
                    messages.append(message)
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        if messages:
            who = ", ".join(dict.fromkeys(m.get("from") or "unknown" for m in messages))
            print(f"RELAY REPLY for {label} — {len(messages)} message(s) from {who}")
            for message in messages:
                text = " ".join(message["text"].split())
                print("  " + text[:200] + ("…" if len(text) > 200 else ""))
            print("(full text arrives via the delivery hook on your next tool call)")
            sys.stdout.flush()
            return
        if deadline and time.time() > deadline:
            print(f"RELAY TIMEOUT for {label} — no reply after {args.timeout:g}s")
            sys.stdout.flush()
            return
        time.sleep(args.interval)


def _label_for_id(cli_id, cwd):
    """Best-effort title for a cliSessionId, for the return address. Never fatal."""
    try:
        for s in list_sessions(cwd):
            if s.get("cliSessionId") == cli_id:
                return s.get("title")
    except Exception:
        pass
    return None


def caller_has_peer_channel():
    """Claude callers can prefer their native SendMessage tool."""
    return bool(os.environ.get("CLAUDECODE"))


def caller_is_codex():
    """A Codex shell; tool availability is checked by the agent, not this process.

    A Claude process launched under Codex can inherit CODEX_THREAD_ID, so its
    own runtime marker takes precedence. --force-relay covers Codex callers
    whose tool list does not expose native task messaging.
    """
    return bool(os.environ.get("CODEX_THREAD_ID")) and not caller_has_peer_channel()


def _delivery_failed(target, exc):
    status = ("Delivery outcome is unknown; inspect the receiver before retrying."
              if exc.uncertain else "Nothing was queued for later delivery.")
    sys.stderr.write(f"[relay] {target['label']!r}: {exc}\n[relay] {status}\n")
    return 2 if exc.uncertain else 1


def _send_codex(args, target):
    """Native tool redirect, or direct input through the running desktop app."""
    if getattr(args, "defer", False):
        sys.stderr.write("[relay] --defer is only for legacy Claude mailboxes. "
                         "Codex delivery is live; nothing was sent.\n")
        return 1
    if caller_is_codex() and not args.force_relay:
        native_args = json.dumps({"threadId": target["id"],
                                  "prompt": "From <your task title>: <your message>"})
        sys.stderr.write(
            f"[relay] {target['label']!r} is a Codex task and you are a Codex caller.\n"
            f"[relay] Prefer native task messaging:\n"
            f"[relay]   mcp__codex_app__send_message_to_thread({native_args})\n"
            f"[relay] Confirm the target with list_threads; use its hostId when supplied.\n"
            f"[relay] Include your own task title and threadId if you need an answer.\n"
            f"[relay] Nothing was sent. If that tool is unavailable, re-run with --force-relay.\n"
        )
        return 1
    reply_label = _label_for_id(args.reply_to, args.cwd) if args.reply_to else None
    text = codex_envelope(args.text, args.sender, args.reply_to, reply_label)
    try:
        receipt = send_codex(target["id"], text, CODEX_HOME)
    except DeliveryError as exc:
        return _delivery_failed(target, exc)
    landed = "accepted into the active turn" if receipt["status"] == "steered" else "started a new turn"
    sys.stderr.write(f"[relay] {target['label']!r}: {landed}; agent reading is not confirmed.\n")
    print(json.dumps(receipt))
    return 0


def _caller_bridge_address():
    """The reply address of a Claude caller: its own session's cloud record,
    when the desktop app has mirrored it. Nothing for a Codex caller."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not (caller_has_peer_channel() and sid):
        return None
    for p in glob.glob(f"{META_ROOT}/*/*/local_*.json"):
        try:
            m = json.load(open(p))
        except Exception:
            continue
        if m.get("cliSessionId") == sid and m.get("bridgeSessionIds"):
            return cloud_address(m["bridgeSessionIds"][-1])
    return None


def cloud_way_back(sender):
    """What a cloud session is told about answering: SendMessage will not carry
    it, a mark in its own reply will. Appended to every message sent there."""
    name = sender or "<the session name you were given>"
    return ("\nYou are a cloud session and cannot message back through SendMessage. To answer, "
            f"or to reach any session on Derek's Mac, write this in your reply and end your turn:\n"
            f'<relay to="{name}">\nyour message\n</relay>\n'
            "A watcher on that Mac delivers it within seconds; the answer arrives here as a "
            "cross-session message. To read a session's transcript instead, write "
            '<relay read="its title" tail="40"/> the same way; it arrives in parts. Mid-task, '
            'without ending your turn, run the mark as a tool call instead: '
            'tools/relay-mark to "name" "message" (or read "title" 40) in the homesodamachine checkout.\n')


def _cloud_record(cse_id):
    """The roster record for a cloud id, or nothing when the roster does not carry it."""
    try:
        for s in cloud_sessions():
            if s.get("id") == cse_id:
                return s
    except TranscriptError:
        pass
    return {}


def _send_cloud(args, target):
    """A session in the cloud or on another machine: one event posted to its
    cloud record, or the native tool when the caller has one."""
    cse_id, label = target["id"], target["label"]
    if getattr(args, "defer", False):
        sys.stderr.write("[relay] --defer is a mailbox on this disk; a cloud session never reads "
                         "it. Nothing was sent.\n")
        return 1
    if caller_has_peer_channel() and not args.force_relay:
        sys.stderr.write(
            f"[relay] {label!r} is reachable through your native peer channel:\n"
            f"[relay]   SendMessage(to: {json.dumps(cloud_address(cse_id))}, message: \"...\")\n"
            f"[relay] Nothing was sent. If that tool is unavailable, re-run with --force-relay.\n"
        )
        return 1
    try:
        token = _cloud_token()
    except TranscriptError as exc:
        return _delivery_failed(target, DeliveryError(f"no cloud grant: {exc}"))
    text = codex_envelope(args.text, args.sender, None, None) + cloud_way_back(args.sender)
    mode = getattr(args, "from_mode", None) or receiver_mode(_cloud_record(cse_id))
    try:
        receipt = send_cloud(cse_id, text, args.sender, token=token, org_uuid=_org_uuid(),
                             mode=mode, from_address=_caller_bridge_address())
    except (DeliveryError, ValueError) as exc:
        if not isinstance(exc, DeliveryError):
            exc = DeliveryError(str(exc))
        return _delivery_failed(target, exc)
    seq = f" (event {receipt['sequenceNum']})" if receipt.get("sequenceNum") else ""
    sys.stderr.write(f"[relay] {label!r}: posted to its cloud record{seq} as {mode}; agent reading is not "
                     f"confirmed. Its answer lands in its own transcript: "
                     f"jsonl2md.py delta {shlex.quote(label)}\n")
    print(json.dumps(receipt))
    return 0


def _defer_claude(args, target):
    """Explicit compatibility path with a finite lifetime; never a send fallback."""
    ttl = getattr(args, "expires_in", DEFERRED_TTL)
    if not 0 < ttl <= 86400:
        sys.stderr.write("[relay] --expires-in must be between 0 and 86400 seconds. Nothing was sent.\n")
        return 1
    box = os.path.join(RELAY_INBOX_ROOT, target["id"])
    os.makedirs(box, exist_ok=True)
    now = time.time()
    msg = {"mode": args.mode, "text": args.text, "from": args.sender,
           "ts": now, "expires_at": now + ttl}
    if args.reply_to:
        msg["reply_to"] = args.reply_to
    dst = os.path.join(box, f"{int(now * 1000):013d}-{uuid.uuid4()}.json")
    tmp = dst + ".tmp"
    with open(tmp, "x") as f:
        json.dump(msg, f)
    os.replace(tmp, dst)
    sys.stderr.write(f"[relay] deferred for {target['label']!r}; expires in {ttl:g}s. "
                     "Delivery requires its next tool call; this does not wake an idle agent.\n")
    print(dst)
    return 0


def cmd_send(args):
    if not args.text.strip():
        sys.stderr.write("[relay] Message is empty. Nothing was sent.\n")
        return 1
    target = resolve_any_target(args.title, args.cwd, getattr(args, "kind", None))
    if target["kind"] == "codex":
        return _send_codex(args, target)
    cli_id, label = target["id"], target["label"]
    if is_cloud(cli_id):
        return _send_cloud(args, target)
    if getattr(args, "defer", False):
        return _defer_claude(args, target)
    peer = peer_addresses().get(cli_id)
    if peer and not args.force_relay and caller_has_peer_channel():
        sys.stderr.write(
            f"[relay] {label} is reachable through your native peer channel:\n"
            f"[relay]   SendMessage(to: {json.dumps(peer['name'])}, message: \"...\")\n"
            f"[relay] Nothing was sent. If that tool is unavailable, re-run with --force-relay.\n"
        )
        return 1
    if not peer:
        return _delivery_failed(target, DeliveryError(
            "no live Claude peer receiver. Open the session in a current Claude app, "
            "or explicitly use --defer --expires-in 300 for its legacy mailbox"))
    text = codex_envelope(args.text, args.sender, args.reply_to, args.reply_to)
    try:
        receipt = send_claude(peer, text, args.sender, SESSIONS_ROOT, mode=getattr(args, "from_mode", None) or "bypass")
    except DeliveryError as exc:
        return _delivery_failed(target, exc)
    sys.stderr.write(f"[relay] {label!r}: submitted to the live Claude receiver; "
                     "agent reading is not confirmed.\n")
    print(json.dumps(receipt))
    return 0


EPILOG = """\
examples:
  # Codex desktop tasks: complete visible dialogue, no tools/reasoning/system context
  jsonl2md.py list-codex-sessions
  jsonl2md.py export-codex-session "Manager 2" --out /tmp

  # Claude Code sessions (current project on disk)
  jsonl2md.py list-sessions
  jsonl2md.py list-sessions --cwd /path/to/other/project
  jsonl2md.py export-session "Professor - done"
  jsonl2md.py export-session "Professor - done" --out ~/Desktop
  jsonl2md.py export-session --all --out ./exports
  jsonl2md.py export-session "VSCode Extension - 303f72e5"  # a VSCode-ext session
  jsonl2md.py export-session 303f72e5                       # ...or by id prefix

  # The last things YOU asked for, newest first, across every session at once
  jsonl2md.py recent-prompts                  # top 5, in full, with timestamp + location
  jsonl2md.py recent-prompts -n 20 --chars 300
  jsonl2md.py recent-prompts --session "PCB clean"
  jsonl2md.py recent-prompts -n 0 --json      # every prompt, machine-readable

  # Is the human here? Exits 1 when nothing was said in the window, so it gates.
  jsonl2md.py recent-prompts --since 1h -n 0 --exclude "My Own Session" || exit 0

  # Who is here, how to reach them, and whether they are still moving
  jsonl2md.py situation
  jsonl2md.py situation --exclude "My Own Session" --json

  # Hold the rules the automated callers depend on. Prints N/N, exits 1 on failure.
  jsonl2md.py selftest

  # Read every session at once: your turns whole, each agent run cut in the middle
  jsonl2md.py export-session --all --compact --out ./compact
  jsonl2md.py export-session --all --compact 3 --out ./tighter
  jsonl2md.py delta "PCB clean" --tail 40 --compact

  # Claude.ai chats (desktop app sidebar)
  jsonl2md.py list-chats
  jsonl2md.py list-chats --limit 50
  jsonl2md.py export-chat "Go to Market Strategy"
  jsonl2md.py export-chat --all --limit 10 --out ./chat-exports

  # Share only what's new since you last shared (the Salon delta flow)
  jsonl2md.py delta "PCB clean"            # preview new turns; cursor untouched
  jsonl2md.py delta "PCB clean" --commit   # same, and mark them shared
  jsonl2md.py delta "PCB clean" --tail 2   # just the last 2 exchanges
  jsonl2md.py watch "PCB clean"            # stream new turns live as they land

  # Resolve across runtimes, then deliver directly to the live receiver.
  # Same-runtime callers are directed to their native tool when it is available.
  jsonl2md.py board
  jsonl2md.py send "Condenser" "The dimensions are ready to review." --from "Funnel mold"
  jsonl2md.py send "Condenser" "..." --force-relay   # live script transport

  # A return address lets the receiver answer through the same live routes.
  jsonl2md.py send "Build time" "Can you check the fit?" --from "Funnel mold" --reply-to "Funnel mold"

  # Explicit legacy Claude delivery: no wake-up, expires after five minutes.
  jsonl2md.py send "Build time" "..." --defer --expires-in 300

  # A session in the cloud, or on another machine: the same verb. A Claude caller
  # is handed the native address; anyone else posts to its cloud record.
  jsonl2md.py send "Ceiling panel" "The 3 mm floor is the limit; see grip-roof-shared-datum" --from "Tower"
  jsonl2md.py delta "Ceiling panel" --tail 2      # its answer is in its own transcript

  # The way back: a cloud session writes <relay to="Time">…</relay> in its reply and
  # this watcher (kept alive by launchd, see install.sh) delivers it into Time.
  jsonl2md.py cloud-inbox
  jsonl2md.py cloud-inbox --session cse_… --once   # one pass over one record
  jsonl2md.py await-reply "My Session Title" --timeout 300  # legacy only, in background

  # Standalone: any Claude Code .jsonl on disk
  jsonl2md.py render path/to/session.jsonl > out.md
  cat session.jsonl | jsonl2md.py render > out.md
"""


# --- selftest ----------------------------------------------------------------

def cmd_cloud_inbox(args):
    """Tail live cloud sessions and deliver their `<relay to=…>` marks locally."""
    from cloud_inbox import Inbox, InboxState
    inbox = Inbox(interval=args.interval, only=args.session or None, cwd=args.cwd,
                  state=InboxState(args.state) if args.state else None)
    if args.once:
        n = inbox.pass_once()
        sys.stderr.write(f"[inbox] one pass: {n} delivered\n")
        return 0
    try:
        if args.poll:
            inbox.run()
        else:
            inbox.run_streams()
    except KeyboardInterrupt:
        sys.stderr.write("\n[inbox] stopped.\n")
    return 0


def cmd_selftest(args):
    """Check speech, session exclusion, and message routing without live delivery."""
    cases, failed = [], []

    def check(name, got, want):
        cases.append(name)
        if got != want:
            failed.append(f"{name}\n    want: {want!r}\n    got:  {got!r}")

    # user_speech: what the human typed survives, what was typed for them does not.
    plain = {"message": {"role": "user", "content": "hello"}}
    check("plain prose is speech", user_speech(plain, "hello"), "hello")
    check("tool result is not speech",
          user_speech({"toolUseResult": {}}, "ok"), "")
    check("sidechain is not speech",
          user_speech({"isSidechain": True}, "ok"), "")
    check("task notification is not speech",
          user_speech({}, "<task-notification>done</task-notification>"), "")
    check("peer message is not speech",
          user_speech({}, "Another Claude session sent a message: hi"), "")
    check("system reminder is cut",
          user_speech({}, "keep <system-reminder>drop</system-reminder>"), "keep")
    check("command envelope renders as the typed line",
          user_speech({}, "<command-name>/relay</command-name>"
                          "<command-args>Corbel</command-args>"), "/relay Corbel")

    # The regression: an unexpanded slash command is flagged isMeta and carries
    # no envelope, so the flag alone cannot tell it from an expanded body.
    check("unexpanded slash command is speech",
          user_speech({"isMeta": True}, "/hourly-help"), "/hourly-help")
    check("unexpanded slash command with args is speech",
          user_speech({"isMeta": True}, "/loop 1h /hourly-help"), "/loop 1h /hourly-help")
    check("expanded command body is not speech",
          user_speech({"isMeta": True}, "# /loop\n\nParse the input below"), "")
    check("meta prose is not speech",
          user_speech({"isMeta": True}, "Caveat: the messages below were generated"), "")
    check("a path is not a slash command",
          user_speech({"isMeta": True}, "/Users/derek/Developer/x.py"), "")
    check("a meta tagged envelope is not speech",
          user_speech({"isMeta": True}, "<local-command-stdout>ok</local-command-stdout>"), "")

    # dropped_by: one rule, so a session cannot be excluded from one view and
    # survive in another.
    check("id prefix excludes", dropped_by(["1820de5e"], "1820de5e-c938-4", None), True)
    check("full id excludes",
          dropped_by(["1820de5e-c938-4"], "1820de5e-c938-4", None), True)
    check("title excludes", dropped_by(["Corbel"], "abc123", "Corbel"), True)
    check("address excludes",
          dropped_by(["homesodamachine-35"], "abc123", None, "homesodamachine-35"), True)
    check("unrelated survives", dropped_by(["Thick"], "abc123", "Corbel"), False)
    check("empty exclude drops nothing", dropped_by([], "abc123", "Corbel"), False)
    check("a name is not a prefix of the id",
          dropped_by(["abc"], "abc123", "Corbel"), True)

    # situation(): the untitled fold-in obeys --exclude. The helper is untitled
    # by construction, so this is the only path its own exclusion travels.
    import types, io
    saved = (globals()["list_sessions"], globals()["peer_addresses"],
             globals()["_peer_idle_module"], globals()["session_prompts"],
             globals()["is_cloud"])
    try:
        globals()["list_sessions"] = lambda cwd: []
        globals()["peer_addresses"] = lambda: {"deadbeef-0000": {"name": "helper-35"}}
        globals()["_peer_idle_module"] = lambda: None
        globals()["session_prompts"] = lambda s: []
        globals()["is_cloud"] = lambda cli: False
        check("untitled row appears with no exclusion",
              [r["title"] for r in situation("/tmp")], ["(helper-35)"])
        check("untitled row is excluded by id",
              [r["title"] for r in situation("/tmp", ["deadbeef"])], [])
        check("untitled row is excluded by address",
              [r["title"] for r in situation("/tmp", ["helper-35"])], [])
        # recent-prompts asks whether the human is here, so it has to look
        # where he talks. A session is untitled until it earns a name.
        check("untitled sessions are offered to callers",
              [s["title"] for s in untitled_sessions("/tmp")], ["(helper-35)"])
        check("untitled sessions honour --exclude by id",
              untitled_sessions("/tmp", ["deadbeef"]), [])
        check("untitled sessions honour --exclude by address",
              untitled_sessions("/tmp", ["helper-35"]), [])

        globals()["session_prompts"] = lambda s: (
            [{"when": "2026-01-01T00:00:00.000Z", "text": "/hourly-help",
              "session": s.get("title"), "path": "x", "line": 1, "uuid": "u"}]
            if s.get("cliSessionId") == "deadbeef-0000" else [])
        buf, real = io.StringIO(), sys.stdout
        ns = types.SimpleNamespace(cwd="/tmp", exclude=None, session=None,
                                   since=None, limit=5, json=False, chars=200)
        try:
            sys.stdout = buf
            rc = cmd_recent_prompts(ns)
        finally:
            sys.stdout = real
        check("the gate reads an untitled session's prompts", rc, 0)
        check("and reports what was typed there",
              "/hourly-help" in buf.getvalue(), True)
    finally:
        (globals()["list_sessions"], globals()["peer_addresses"],
         globals()["_peer_idle_module"], globals()["session_prompts"],
         globals()["is_cloud"]) = saved

    # Redirects send nothing. Cross-runtime sends use live receivers, and a
    # delivery error must never create a delayed mailbox message.
    from contextlib import redirect_stderr, redirect_stdout
    from tempfile import TemporaryDirectory
    from unittest.mock import patch
    routing_cases = [
        ("Codex to Codex redirects", {"CODEX_THREAD_ID": "caller"}, "codex", False, 1, 0, 0),
        ("Codex forced live send", {"CODEX_THREAD_ID": "caller"}, "codex", True, 0, 1, 0),
        ("Claude to Codex steers", {"CLAUDECODE": "1"}, "codex", False, 0, 1, 0),
        ("shell to Codex steers", {}, "codex", False, 0, 1, 0),
        ("nested Claude to Codex steers", {"CLAUDECODE": "1", "CODEX_THREAD_ID": "caller"},
         "codex", False, 0, 1, 0),
        ("Codex to Claude sends live", {"CODEX_THREAD_ID": "caller"}, "claude", False, 0, 0, 1),
        ("Claude peer redirects", {"CLAUDECODE": "1"}, "claude", False, 1, 0, 0),
        ("Claude forced live send", {"CLAUDECODE": "1"}, "claude", True, 0, 0, 1),
    ]
    for name, runtime_env, kind, force, want_rc, want_codex, want_claude in routing_cases:
        target = {"kind": kind, "id": "target-id", "label": "Target"}
        ns = types.SimpleNamespace(title="Target", cwd="/tmp", kind=None,
                                   force_relay=force, mode="interrupt", text="routing check",
                                   sender="Caller", reply_to=None, defer=False)
        output = io.StringIO()
        with TemporaryDirectory() as inbox, \
                patch.dict(os.environ, runtime_env, clear=True), \
                patch.dict(globals(), {
                    "RELAY_INBOX_ROOT": inbox,
                    "resolve_any_target": lambda *a: target,
                    "peer_addresses": lambda: {"target-id": {"name": "Target"}},
                }), \
                patch(__name__ + ".send_codex", return_value={"status": "steered"}) as codex, \
                patch(__name__ + ".send_claude", return_value={"status": "submitted"}) as claude, \
                redirect_stdout(output), redirect_stderr(output):
            rc = cmd_send(ns)
            check(name + ": result", rc, want_rc)
            check(name + ": Codex count", codex.call_count, want_codex)
            check(name + ": Claude count", claude.call_count, want_claude)
            check(name + ": no mailbox", glob.glob(os.path.join(inbox, "*", "*.json")), [])
            if want_codex:
                check(name + ": destination", codex.call_args.args[0], "target-id")
            if kind == "codex" and want_rc == 1:
                check(name + ": native address", '\"threadId\": \"target-id\"' in output.getvalue(), True)

    for prefix in RELAY_PREFIXES + ("<cross-session-message",):
        check("peer envelope is not human speech: " + prefix,
              user_speech({}, prefix + " hello"), "")
    envelope = codex_envelope("message", "Sender", "Title 'quoted'", None, sent_at=0)
    check("send time is visible", "sent 1970-01-01 00:00:00 UTC" in envelope, True)
    check("reply does not request another reply", "--reply-to" in envelope, False)
    check("short source label", envelope.startswith("Agent message from Sender"), True)

    # Cloud targets: every spelling of a record's id is the same target, and the
    # grant is the desktop app's before the Keychain's.
    check("cloud id spellings agree",
          {cloud_ids(x)[0] for x in ("cse_Q1", "session_Q1", "bridge:session_Q1")}, {"cse_Q1"})
    check("cloud address is the native one", cloud_address("cse_Q1"), "bridge:session_Q1")
    check("grant key parses by shape",
          grant_key_fields("acct:A|C:ORG:https://api.anthropic.com:user:inference user:sessions:claude_code"),
          ("C", "ORG", ("user:inference", "user:sessions:claude_code")))
    check("expired desktop grant is not a grant",
          pick_desktop_grant({f"acct:A|{CLOUD_CLIENT_ID}:O:https://api.anthropic.com:{CLOUD_SCOPE}":
                              {"token": "t", "expiresAt": 5000}}, 5000), None)

    for f in failed:
        sys.stderr.write("FAIL " + f + "\n")
    print(f"{len(cases) - len(failed)}/{len(cases)}")
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(
        dest="cmd",
        metavar="{list-codex-sessions,export-codex-session,list-sessions,situation,board,recent-prompts,export-session,list-chats,export-chat,render,delta,watch,send,await-reply,selftest}",
    )

    p_cls = sub.add_parser(
        "list-codex-sessions",
        help="list user-titled, non-archived Codex desktop tasks",
    )
    p_cls.add_argument("--cwd", default=DEFAULT_CWD,
                       help=f"project path to filter by (default: {DEFAULT_CWD})")
    p_cls.set_defaults(func=cmd_list_codex_sessions)

    p_ces = sub.add_parser(
        "export-codex-session",
        help="export complete visible dialogue from Codex task(s) to .md",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_ces.add_argument(
        "title",
        nargs="?",
        help="exact task title, or a thread id / unique prefix "
             "(use 'list-codex-sessions' to see them); omit when using --all",
    )
    p_ces.add_argument("--all", action="store_true",
                       help="export every visible user-titled task in the target cwd")
    p_ces.add_argument("--cwd", default=DEFAULT_CWD,
                       help=f"project path to filter by (default: {DEFAULT_CWD})")
    p_ces.add_argument("--tail", type=int, metavar="K",
                       help="emit only the last K turns, to stdout instead of a file "
                            "(the relay's shortcut for a long task)")
    p_ces.add_argument("--compact", nargs="?", type=int, const=6, default=0, metavar="N",
                       help="coalesce each run of consecutive agent turns and cut its middle, "
                            "keeping N lines at either end (default 6); your own turns are never cut")
    p_ces.add_argument("--out", default=".",
                       help="output directory (default: current dir)")
    p_ces.set_defaults(func=cmd_export_codex_session)

    p_ls = sub.add_parser("list-sessions", help="list titled desktop + VSCode-extension Claude Code sessions")
    p_ls.add_argument("--cwd", default=DEFAULT_CWD,
                     help=f"project path to filter by (default: {DEFAULT_CWD})")
    p_ls.set_defaults(func=cmd_list_sessions)

    p_rp = sub.add_parser(
        "recent-prompts",
        help="what you last asked for, newest first, across every session in --cwd",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_rp.add_argument("-n", "--limit", type=int, default=5,
                      help="how many prompts to show (default: 5; 0 = all)")
    p_rp.add_argument("--session", default=None,
                      help="only this session (exact title or a cliSessionId); "
                           "default is every session in --cwd")
    p_rp.add_argument("--chars", type=int, default=0, metavar="N",
                      help="truncate each prompt to N characters (default: print in full)")
    p_rp.add_argument("--json", action="store_true",
                      help="emit the records as JSON instead of the readable listing")
    p_rp.add_argument("--since", default=None, metavar="DUR",
                      help="only prompts newer than DUR (30s, 90m, 2h, 1d; a bare "
                           "number is hours). Exits 1 when the window is empty, so a "
                           "caller can gate on whether the human is around")
    p_rp.add_argument("--exclude", action="append", default=[], metavar="SESSION",
                      help="leave a session out by title or cliSessionId prefix; "
                           "repeatable. An automated caller passes its own")
    p_rp.add_argument("--cwd", default=DEFAULT_CWD,
                      help=f"project path to filter by (default: {DEFAULT_CWD})")
    p_rp.set_defaults(func=cmd_recent_prompts)

    p_sit = sub.add_parser(
        "situation",
        help="one board: every session, how to reach it, whether it is still moving",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_sit.add_argument("--exclude", action="append", default=[], metavar="SESSION",
                       help="leave a session out by title or cliSessionId prefix; repeatable")
    p_sit.add_argument("--json", action="store_true",
                       help="emit the rows as JSON, each with its full last prompt")
    p_sit.add_argument("--cwd", default=DEFAULT_CWD,
                       help=f"project path to filter by (default: {DEFAULT_CWD})")
    p_sit.set_defaults(func=cmd_situation)

    p_board = sub.add_parser(
        "board",
        help="both runtimes in one roster: every Claude session and Codex task, "
             "and the call that reaches each",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_board.add_argument("--exclude", action="append", default=[], metavar="SESSION",
                         help="leave a session out by cliSessionId; repeatable")
    p_board.add_argument("--json", action="store_true", help="emit the rows as JSON")
    p_board.add_argument("--cwd", default=DEFAULT_CWD,
                         help=f"project path to filter by (default: {DEFAULT_CWD})")
    p_board.set_defaults(func=cmd_board)

    p_es = sub.add_parser(
        "export-session",
        help="export Claude Code session(s) to .md",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_es.add_argument("title", nargs="?",
                     help="exact session title, or a cliSessionId / unique prefix "
                          "(use 'list-sessions' to see them); omit when using --all")
    p_es.add_argument("--all", action="store_true",
                     help="export every visible session in the target cwd")
    p_es.add_argument("--cwd", default=DEFAULT_CWD,
                     help=f"project path to filter by (default: {DEFAULT_CWD})")
    p_es.add_argument("--out", default=".",
                     help="output directory (default: current dir)")
    p_es.add_argument("--compact", nargs="?", type=int, const=6, default=0, metavar="N",
                     help="coalesce each run of consecutive assistant turns and cut its middle, keeping N lines at either end (default 6 when N is omitted); your own turns are never cut")
    p_es.set_defaults(func=cmd_export_session)

    p_lc = sub.add_parser("list-chats", help="list main Claude.ai chats from the desktop app sidebar")
    p_lc.add_argument("--limit", type=int, default=30,
                     help="how many recent chats to fetch (default: 30)")
    p_lc.set_defaults(func=cmd_list_chats)

    p_ec = sub.add_parser(
        "export-chat",
        help="export Claude.ai chat(s) to .md",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_ec.add_argument("name", nargs="?",
                     help="exact chat name (use 'list-chats' to see them); omit when using --all")
    p_ec.add_argument("--all", action="store_true",
                     help="export every chat in the top --limit window")
    p_ec.add_argument("--limit", type=int, default=30,
                     help="how many recent chats to consider (default: 30)")
    p_ec.add_argument("--out", default=".",
                     help="output directory (default: current dir)")
    p_ec.set_defaults(func=cmd_export_chat)

    p_ren = sub.add_parser("render", help="render a JSONL file or stdin to markdown on stdout")
    p_ren.add_argument("path", nargs="?",
                      help="path to a .jsonl file (omit to read from stdin)")
    p_ren.add_argument("--compact", nargs="?", type=int, const=6, default=0, metavar="N",
                      help="coalesce each run of consecutive assistant turns and cut its middle, keeping N lines at either end (default 6 when N is omitted); your own turns are never cut")
    p_ren.set_defaults(func=cmd_render)

    p_delta = sub.add_parser(
        "delta",
        help="emit only the user/assistant turns added since you last shared",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_delta.add_argument("title", help="exact session title (see list-sessions) or a cliSessionId")
    p_delta.add_argument("--cwd", default=DEFAULT_CWD, help=f"project path (default: {DEFAULT_CWD})")
    p_delta.add_argument("--commit", action="store_true",
                        help="advance the saved cursor to the file tail (mark these turns as shared)")
    p_delta.add_argument("--tail", type=int, metavar="K",
                        help="ignore the cursor; emit only the last K exchanges (cursor untouched)")
    p_delta.add_argument("--reset", action="store_true",
                        help="delete the saved cursor and share from the start")
    p_delta.add_argument("--first-share", action="store_true",
                        help="confirm emitting a whole transcript when no cursor exists yet")
    p_delta.add_argument("--compact", nargs="?", type=int, const=6, default=0, metavar="N",
                        help="coalesce each run of consecutive assistant turns and cut its middle, keeping N lines at either end (default 6 when N is omitted); your own turns are never cut")
    p_delta.set_defaults(func=cmd_delta)

    p_watch = sub.add_parser("watch", help="stream new user/assistant turns as the session grows")
    p_watch.add_argument("title", help="exact session title (see list-sessions) or a cliSessionId")
    p_watch.add_argument("--cwd", default=DEFAULT_CWD, help=f"project path (default: {DEFAULT_CWD})")
    p_watch.add_argument("--interval", type=float, default=1.0, help="poll seconds (default: 1.0)")
    p_watch.set_defaults(func=cmd_watch)

    p_send = sub.add_parser(
        "send",
        help="deliver directly to a live agent, steering or waking it",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_send.add_argument("title", help="exact session title (see list-sessions) or a cliSessionId")
    p_send.add_argument("text", help="the message to deliver into that session")
    p_send.add_argument("--mode", choices=["interrupt", "nudge"], default="interrupt",
                        help="with --defer only: interrupt blocks the next tool call; "
                             "nudge adds context without blocking")
    p_send.add_argument("--from", dest="sender", default=None,
                        help="optional label for who is sending (shown to the receiving agent)")
    p_send.add_argument("--reply-to", dest="reply_to", default=None,
                        help="your OWN session/task id or title, given to the receiver as a return address")
    p_send.add_argument("--kind", choices=["claude", "codex"], default=None,
                        help="disambiguate when one title names a session in both runtimes "
                             "(default: resolve across both and fail loud on a collision)")
    p_send.add_argument("--force-relay", action="store_true",
                        help="use the live script transport instead of redirecting to a native tool")
    p_send.add_argument("--from-mode", dest="from_mode", choices=["bypass", "prompting"], default=None,
                        help="the permission class to assert, which must be the RECEIVER's for it to deliver unasked: derived from its cloud record when omitted (bypass for a session on this Mac)"
                             "delivers unasked only from its own class (default: bypass)")
    p_send.add_argument("--defer", action="store_true",
                        help="explicitly use a legacy Claude mailbox instead of live delivery")
    p_send.add_argument("--expires-in", type=float, default=DEFERRED_TTL, metavar="SECONDS",
                        help="--defer lifetime, 0 < seconds <= 86400 (default: 300)")
    p_send.add_argument("--cwd", default=DEFAULT_CWD, help=f"project path (default: {DEFAULT_CWD})")
    p_send.set_defaults(func=cmd_send)

    p_inbox = sub.add_parser(
        "cloud-inbox",
        help="deliver <relay to=…> marks from live cloud sessions into local sessions (daemon)",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_inbox.add_argument("--poll", action="store_true",
                         help="poll each session's events instead of holding its live stream")
    p_inbox.add_argument("--interval", type=float, default=4.0, help="--poll seconds (default: 4)")
    p_inbox.add_argument("--session", action="append", metavar="CSE_ID",
                         help="watch exactly this cloud record (repeatable; default: every live "
                              "session on Anthropic's machines)")
    p_inbox.add_argument("--once", action="store_true", help="one pass, then exit")
    p_inbox.add_argument("--state", default=None, metavar="PATH",
                         help="cursor file (default: ~/.jsonl2md/cloud/inbox.json, the daemon's; a manual "
                              "run against --session should use its own)")
    p_inbox.add_argument("--cwd", default=DEFAULT_CWD, help=f"project for Codex targets (default: {DEFAULT_CWD})")
    p_inbox.set_defaults(func=cmd_cloud_inbox)

    p_await = sub.add_parser(
        "await-reply",
        help="watch a legacy --defer mailbox (live delivery does not need this)",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_await.add_argument("title", nargs="?", default=None,
                         help="YOUR OWN session title or cliSessionId — the mailbox to watch, "
                              "not the session you messaged")
    p_await.add_argument("--timeout", type=float, default=3600.0,
                         help="give up after N seconds and exit anyway (0 = wait forever; "
                              "default 3600)")
    p_await.add_argument("--interval", type=float, default=3.0, help="poll seconds (default: 3.0)")
    p_await.add_argument("--cwd", default=DEFAULT_CWD, help=f"project path (default: {DEFAULT_CWD})")
    p_await.set_defaults(func=cmd_await_reply)

    p_self = sub.add_parser(
        "selftest",
        help="hold the rules the automated callers depend on; prints N/N, exits 1 on failure")
    p_self.set_defaults(func=cmd_selftest)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 0
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
