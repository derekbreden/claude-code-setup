#!/usr/bin/env python3
"""peer_idle - report which of this project's live Claude Code sessions have stopped.

Nothing wakes an idle session, so a coordinator that parks has no way to learn that a
worker ended its turn with work still owed. This supplies that edge: it watches every
live session in a project and exits the moment one stops, which makes it usable as a
background wake-up rather than something to poll.

    peer_idle.py --once                  # table of every session and its state
    peer_idle.py --ignore Manager        # block until someone else stops, then exit
    peer_idle.py --quorum all            # block until everyone has stopped

A session is WORKING while its last transcript record is a tool call, a tool result, or
an assistant message still in flight -- `stop_reason` of `tool_use` is the only value
that promises another record. Any other terminal reason ends the turn, so the session is
IDLE. A turn that ended on a transport error is FAILED, which is the same stop wearing
the costume of a finished one and the most expensive to miss: the work is mid-flight and
nothing retries it. A session whose process is gone is GONE.

Most stops are not dropped balls. A session parked on a background build ends its turn
too, and the harness wakes it when the build lands. What separates the two is only how
long the stop lasts, so `--dwell` holds a stop until it has persisted that long. A dead
process needs no dwell: nothing is coming to wake it.

Run the watching forms with run_in_background so the exit is the notification.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

SESSIONS = pathlib.Path.home() / ".claude" / "sessions"
PROJECTS = pathlib.Path.home() / ".claude" / "projects"

# A transcript's last record is enough to place it, so only the tail is ever read.
TAIL_BYTES = 262_144

WORKING, IDLE, GONE, UNKNOWN = "working", "idle", "gone", "unknown"
FAILED = "failed"

# The one stop_reason that means another record is coming. Every other terminal value --
# `end_turn`, `stop_sequence`, `max_tokens` -- means the assistant will not act again
# without being spoken to, whether it finished or fell over.
CONTINUES = "tool_use"


def project_dir(cwd: str) -> pathlib.Path:
    """The transcript directory for a working tree, whose name is its path with the
    separators replaced -- the same mangling Claude Code itself writes under."""
    return PROJECTS / cwd.replace("/", "-")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def live_sessions(cwd: str) -> list[dict]:
    """Every session descriptor this project has on disk, newest first.

    A descriptor outlives its process, so the caller gets dead ones too -- a session that
    exited holding work is exactly what this tool exists to surface."""
    out = []
    for f in sorted(SESSIONS.glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if d.get("cwd") != cwd:
            continue
        d["pid"] = d.get("pid") or int(f.stem)
        d["alive"] = alive(d["pid"])
        d.setdefault("name", f"pid-{d['pid']}")
        out.append(d)
    return sorted(out, key=lambda d: d.get("updatedAt", 0), reverse=True)


def tail_records(path: pathlib.Path) -> list[dict]:
    """The decodable records at the end of a transcript.

    The first line of a mid-file read is a fragment, so it is dropped."""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
                fh.readline()
            blob = fh.read()
    except OSError:
        return []
    recs = []
    for line in blob.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            recs.append(json.loads(line))
        except ValueError:
            continue
    return recs


def last_text(rec: dict) -> str:
    content = rec.get("message", {}).get("content")
    if isinstance(content, str):
        return " ".join(content.split())
    if not isinstance(content, list):
        return ""
    for block in reversed(content):
        if isinstance(block, dict) and block.get("type") == "text":
            return " ".join(str(block.get("text", "")).split())
    return ""


def state_of(sess: dict, cwd: str) -> dict:
    """Where a session stands, read off the end of its own transcript."""
    sid = sess.get("sessionId", "")
    path = project_dir(cwd) / f"{sid}.jsonl"
    row = {
        "name": sess["name"],
        "pid": sess["pid"],
        "sessionId": sid,
        "state": UNKNOWN,
        "idle_for": 0.0,
        "tail": "",
    }
    if not path.exists():
        row["state"] = GONE if not sess["alive"] else UNKNOWN
        return row

    row["idle_for"] = max(0.0, time.time() - path.stat().st_mtime)
    turns = [r for r in tail_records(path) if r.get("type") in ("assistant", "user")]
    if not turns:
        row["state"] = UNKNOWN if sess["alive"] else GONE
        return row

    last = turns[-1]
    reason = last.get("message", {}).get("stop_reason")
    ended = (
        last.get("type") == "assistant"
        and reason is not None
        and reason != CONTINUES
    )
    if not sess["alive"]:
        row["state"] = GONE
    elif ended:
        # A turn that died on a transport error looks exactly like one that finished,
        # and is the worse of the two: the work is mid-flight and nothing will retry it.
        # Naming it apart is the whole point -- a stop reported as completion gets read
        # as completion.
        row["state"] = FAILED if "API Error" in last_text(last) else IDLE
    else:
        row["state"] = WORKING
    for rec in reversed(turns):
        text = last_text(rec)
        if text:
            row["tail"] = text
            break
    return row


def snapshot(cwd: str, ignore: set[str]) -> dict[str, dict]:
    rows = {}
    for sess in live_sessions(cwd):
        if sess["name"] in ignore:
            continue
        row = state_of(sess, cwd)
        # One name may carry several descriptors as a session is restarted; the newest
        # descriptor is the live one, and live_sessions already put it first.
        rows.setdefault(row["name"], row)
    return rows


def settled(row: dict, dwell: float) -> bool:
    """Whether a stop has lasted long enough to mean anything.

    A dead process is settled at once -- no notification is coming to revive it. A live
    session that ended its turn may be parked on a background task, so it only counts
    once the stop has outlasted the dwell."""
    if row["state"] in (GONE, FAILED):
        return True
    return row["state"] == IDLE and row["idle_for"] >= dwell


def fmt(row: dict, width: int) -> str:
    mark = {
        WORKING: "·",
        IDLE: "STOPPED",
        FAILED: "FAILED",
        GONE: "GONE",
        UNKNOWN: "?",
    }[row["state"]]
    age = f"{row['idle_for']:6.0f}s" if row["state"] != WORKING else "       "
    return f"  {row['name']:<{width}}  {mark:<8} {age}  {row['tail'][:96]}"


def report(rows: dict[str, dict]) -> None:
    if not rows:
        print("no sessions found")
        return
    width = max(len(n) for n in rows)
    order = {FAILED: 0, GONE: 1, IDLE: 2, UNKNOWN: 3, WORKING: 4}
    for row in sorted(rows.values(), key=lambda r: (order[r["state"]], r["name"])):
        print(fmt(row, width))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="report which live Claude Code sessions in a project have stopped"
    )
    ap.add_argument("--cwd", default=os.getcwd(), help="project path (default: cwd)")
    ap.add_argument("--once", action="store_true", help="print the table and exit")
    ap.add_argument(
        "--ignore",
        action="append",
        default=[],
        help="session name to leave out; repeatable (use it for yourself)",
    )
    ap.add_argument(
        "--quorum",
        choices=("any", "all"),
        default="any",
        help="wake on the first session to stop (any), or once every one has (all)",
    )
    ap.add_argument(
        "--since-now",
        action="store_true",
        help="only wake on sessions that stop after this call; use it when re-arming, "
        "so the ones you were just told about do not fire again",
    )
    ap.add_argument(
        "--dwell",
        type=float,
        default=0.0,
        help="seconds a session must stay stopped before it counts, so a park on a "
        "background build is not mistaken for an abandoned one (a dead process is "
        "reported regardless)",
    )
    ap.add_argument("--interval", type=float, default=5.0, help="poll seconds")
    ap.add_argument(
        "--timeout",
        type=float,
        default=3600.0,
        help="give up after N seconds (0 = wait forever)",
    )
    args = ap.parse_args()

    cwd = str(pathlib.Path(args.cwd).resolve())
    ignore = set(args.ignore)

    if args.once:
        report(snapshot(cwd, ignore))
        return 0

    started = time.time()
    # A session already stopped when the watch begins counts, because it has not been
    # reported to anyone -- waiting for a fresh transition would hide exactly the case
    # that matters, a worker that stopped while the coordinator was busy elsewhere.
    # `--since-now` seeds those as already-known instead, which is what a re-arm wants:
    # the stops it was just woken for are the ones it must not be woken for again.
    prior: dict[str, bool] = {}
    if args.since_now:
        prior = {
            n: settled(r, args.dwell)
            for n, r in snapshot(cwd, ignore).items()
        }
    while True:
        rows = snapshot(cwd, ignore)

        if args.quorum == "all":
            live = [
                r for r in rows.values()
                if r["state"] in (WORKING, IDLE, FAILED)
            ]
            if live and all(settled(r, args.dwell) for r in live):
                print(f"ALL STOPPED — {len(live)} session(s), none working")
                report(rows)
                return 0
        else:
            stopped = [
                r
                for n, r in rows.items()
                if settled(r, args.dwell) and not prior.get(n, False)
            ]
            if stopped:
                for row in stopped:
                    verb = {
                        IDLE: "ended its turn",
                        FAILED: "DIED ON AN API ERROR",
                        GONE: "exited",
                    }.get(row["state"], "stopped")
                    print(f"{row['name']} {verb} — idle {row['idle_for']:.0f}s")
                    if row["tail"]:
                        print(f"  last said: {row['tail'][:400]}")
                print()
                report(rows)
                return 0

        prior = {n: settled(r, args.dwell) for n, r in rows.items()}
        if args.timeout and (time.time() - started) > args.timeout:
            print(f"timeout after {args.timeout:.0f}s — nobody stopped")
            report(rows)
            return 2
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
