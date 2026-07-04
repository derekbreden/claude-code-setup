#!/usr/bin/env python3
"""jsonl2md - list and export Claude conversations from the macOS Claude.app as markdown.

Two sources, each with a list verb and an export verb, plus a standalone renderer:

  Claude Code sessions (a project on disk):
    list-sessions          List non-archived, user-titled sessions in --cwd.
    export-session <title> Export one session to .md (filename = title).
    export-session --all   Export every session matching the filter.

  Claude.ai chats (desktop app sidebar):
    list-chats             List the top --limit chats in sidebar order.
    export-chat <name>     Export one chat to .md (filename = chat name).
    export-chat --all      Export every chat in the top --limit window.

  Standalone:
    render <path.jsonl>    Render any Claude Code .jsonl (or stdin) to .md on stdout.

  Cross-session (the write half of relay):
    send <title> <text>    Queue a message injected into another live session on its next tool call.

Sessions are discovered from Claude.app's metadata at
    ~/Library/Application Support/Claude/claude-code-sessions/<workspace>/<device>/local_*.json
with transcripts at
    ~/.claude/projects/<cwd-with-slashes-as-dashes>/<cliSessionId>.jsonl
Chats are fetched from claude.ai using cookies decrypted from the desktop app's cookie store.
"""

import argparse
import glob
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from urllib.request import Request, urlopen

DEFAULT_CWD = "/Users/derekbredensteiner/Developer/homesodamachine"
META_ROOT = os.path.expanduser("~/Library/Application Support/Claude/claude-code-sessions")
JSONL_ROOT = os.path.expanduser("~/.claude/projects")
RELAY_INBOX_ROOT = os.path.expanduser("~/.claude/hooks/relay-inbox")
CLAUDE_APP_DIR = os.path.expanduser("~/Library/Application Support/Claude")
COOKIE_DB = os.path.join(CLAUDE_APP_DIR, "Cookies")
KEYCHAIN_SERVICE = "Claude Safe Storage"
KEYCHAIN_ACCOUNT = "Claude Key"


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
    return role, text.strip()


def render_md(records):
    blocks = []
    for obj in records:
        role, text = extract_message(obj)
        if role not in ("user", "assistant") or not text:
            continue
        label = "User" if role == "user" else "Assistant"
        blocks.append(f"---\n\n# {label}\n\n---\n\n{text}\n")
    return "\n".join(blocks)


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


def render_tail(records, k):
    """Render only the last k user+assistant exchanges (2k text turns). Slices
    the list of turns, not the rendered string, so a turn whose own text
    contains the '# User' delimiter can't split wrong."""
    turns = [(r, t) for r, t in (extract_message(o) for o in records)
             if r in ("user", "assistant") and t]
    if k and k > 0:
        turns = turns[-2 * k:]
    blocks = [f"---\n\n# {'User' if r == 'user' else 'Assistant'}\n\n---\n\n{t}\n"
              for r, t in turns]
    return "\n".join(blocks)


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
    sys.stderr.write(f"No user-titled session {positional!r} in {cwd}, and not a known cliSessionId.\n")
    sys.stderr.write("Run 'jsonl2md.py list-sessions' to see titles, or pass a cliSessionId.\n")
    sys.exit(1)


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
    for s in list_sessions(args.cwd):
        print(s["title"])


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
            print(f"No non-archived user-titled session named {args.title!r} in {args.cwd}", file=sys.stderr)
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
        jsonl = jsonl_path_for(cli_id, s["cwd"])
        if not os.path.exists(jsonl):
            print(f"missing transcript: {jsonl}", file=sys.stderr)
            continue
        md = render_md(iter_records(open(jsonl).read()))
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
    sys.stdout.write(render_md(iter_records(text)))


def cmd_delta(args):
    cli_id, label = resolve_target(args.title, args.cwd)
    jsonl = jsonl_path_for(cli_id, args.cwd)
    if not os.path.exists(jsonl):
        sys.stderr.write(f"missing transcript: {jsonl}\n")
        sys.exit(1)
    records = list(iter_records_safe(open(jsonl).read()))
    total = len(records)
    file_last = last_uuid(records)

    if args.reset:
        clear_cursor(cli_id)

    if args.tail is not None:
        md = render_tail(records, args.tail)
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

    md = render_md(tail)
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


def cmd_watch(args):
    cli_id, label = resolve_target(args.title, args.cwd)
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


def cmd_send(args):
    cli_id, label = resolve_target(args.title, args.cwd)
    box = os.path.join(RELAY_INBOX_ROOT, cli_id)
    os.makedirs(box, exist_ok=True)
    msg = {"mode": args.mode, "text": args.text, "from": args.sender, "ts": time.time()}
    # Unique per-message file (maildir-style: no clobber, no lock). Write to a
    # .tmp the receiver's *.json glob ignores, then atomically rename it in.
    dst = os.path.join(box, f"{int(time.time() * 1000):013d}-{os.getpid()}.json")
    tmp = dst + ".tmp"
    with open(tmp, "w") as f:
        json.dump(msg, f)
    os.replace(tmp, dst)
    sys.stderr.write(
        f"[relay] queued {args.mode} message for {label} ({cli_id}); "
        f"it lands on that session's next tool call.\n"
    )
    print(dst)


EPILOG = """\
examples:
  # Claude Code sessions (current project on disk)
  jsonl2md.py list-sessions
  jsonl2md.py list-sessions --cwd /path/to/other/project
  jsonl2md.py export-session "Professor - done"
  jsonl2md.py export-session "Professor - done" --out ~/Desktop
  jsonl2md.py export-session --all --out ./exports

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

  # Interject into another live session (delivered on its next tool call)
  jsonl2md.py send "Autorouter" "stop and reconsider whether fix 1 is still needed"
  jsonl2md.py send "Autorouter" "looks good, keep going" --mode nudge

  # Standalone: any Claude Code .jsonl on disk
  jsonl2md.py render path/to/session.jsonl > out.md
  cat session.jsonl | jsonl2md.py render > out.md
"""


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(
        dest="cmd",
        metavar="{list-sessions,export-session,list-chats,export-chat,render,delta,watch,send}",
    )

    p_ls = sub.add_parser("list-sessions", help="list non-archived, user-titled Claude Code sessions")
    p_ls.add_argument("--cwd", default=DEFAULT_CWD,
                     help=f"project path to filter by (default: {DEFAULT_CWD})")
    p_ls.set_defaults(func=cmd_list_sessions)

    p_es = sub.add_parser(
        "export-session",
        help="export Claude Code session(s) to .md",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_es.add_argument("title", nargs="?",
                     help="exact session title (use 'list-sessions' to see them); omit when using --all")
    p_es.add_argument("--all", action="store_true",
                     help="export every visible session in the target cwd")
    p_es.add_argument("--cwd", default=DEFAULT_CWD,
                     help=f"project path to filter by (default: {DEFAULT_CWD})")
    p_es.add_argument("--out", default=".",
                     help="output directory (default: current dir)")
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
    p_delta.set_defaults(func=cmd_delta)

    p_watch = sub.add_parser("watch", help="stream new user/assistant turns as the session grows")
    p_watch.add_argument("title", help="exact session title (see list-sessions) or a cliSessionId")
    p_watch.add_argument("--cwd", default=DEFAULT_CWD, help=f"project path (default: {DEFAULT_CWD})")
    p_watch.add_argument("--interval", type=float, default=1.0, help="poll seconds (default: 1.0)")
    p_watch.set_defaults(func=cmd_watch)

    p_send = sub.add_parser(
        "send",
        help="queue a message to inject into another live session on its next tool call",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_send.add_argument("title", help="exact session title (see list-sessions) or a cliSessionId")
    p_send.add_argument("text", help="the message to deliver into that session")
    p_send.add_argument("--mode", choices=["interrupt", "nudge"], default="interrupt",
                        help="interrupt: block the target's next tool call with the message "
                             "(default); nudge: attach it without blocking")
    p_send.add_argument("--from", dest="sender", default=None,
                        help="optional label for who is sending (shown to the receiving agent)")
    p_send.add_argument("--cwd", default=DEFAULT_CWD, help=f"project path (default: {DEFAULT_CWD})")
    p_send.set_defaults(func=cmd_send)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
