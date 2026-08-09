#!/usr/bin/env python3
"""Print the assistant text a Stop hook was fired to judge.

Two things make the obvious read — take the last line whose type is assistant,
join its text parts — return the wrong message, and both fail silently.

A turn's closing transcript lines are routinely `thinking` and `tool_use`
records. Those are assistant lines carrying no text at all, so the first
assistant line seen from the end yields an empty string and the caller
classifies nothing. The message wanted is the last assistant record that
actually holds text, which can sit several lines further back.

And the Stop hook runs while that record is still being written. Measured on a
live session: the hook fired at :53 and the message it was fired for landed at
:53.768, so the newest text on disk belonged to the previous turn — the hook
read, judged, and passed a message the user had already seen two turns ago.
Waiting for a record younger than FRESH_S is what makes the hook read the turn
it was fired for. The wait is bounded and it ends early the moment fresh text
appears, so the common case costs one poll interval.

stdout: the message text.
exit 0: fresh text.
exit 2: text found, but it never went fresh inside the bound — the caller should
        note the staleness and judge it anyway, since a turn whose last text
        predates a long tool run is a legitimate shape.
exit 1: no assistant text in the transcript at all.
"""
import json
import os
import sys
import time

TAIL_BYTES = 400_000   # far more than one turn; keeps huge transcripts cheap
# The wait has to fit inside the hook's 6 s budget alongside a classifier call
# that curl caps at 3 s, so 2 s is the ceiling that keeps the worst case — stale
# transcript, slow API — clear of the timeout. It buys a wide margin over the
# 0.768 s lag measured on a live session.
MAX_WAIT_S = 2.0
FRESH_S = 5.0          # a record this new belongs to the turn that just ended
POLL_S = 0.1


def last_text_record(path):
    """Return (text, epoch_seconds) for the last assistant record with text."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
                fh.readline()          # discard the partial line at the seek
            blob = fh.read()
    except OSError:
        return None, None

    for line in reversed(blob.splitlines()):
        try:
            rec = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue                   # sidecar records and partial lines
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            continue
        content = (rec.get("message") or {}).get("content") or []
        if not isinstance(content, list):
            continue
        text = "\n".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ).strip()
        if not text:
            continue                   # a thinking or tool_use record
        stamp = rec.get("timestamp")
        try:
            from datetime import datetime
            when = datetime.fromisoformat(
                str(stamp).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            when = None
        return text, when
    return None, None


def main():
    path = sys.argv[1]
    deadline = time.time() + MAX_WAIT_S
    text = None
    while True:
        text, when = last_text_record(path)
        if text is not None and (when is None or time.time() - when <= FRESH_S):
            sys.stdout.write(text)
            return 0
        if time.time() >= deadline:
            break
        time.sleep(POLL_S)

    if text is None:
        return 1
    sys.stdout.write(text)
    return 2


if __name__ == "__main__":
    sys.exit(main())
