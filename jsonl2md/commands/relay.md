---
description: Pull another of my Claude Code sessions' clean transcript INTO this one — renders it with jsonl2md and reads it in. Local only; no cross-session messaging.
argument-hint: <source session title or hint>
disable-model-invocation: true
allowed-tools: Bash(python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py:*), Read
---

Relay the contents of another of the user's Claude Code sessions INTO this one. You do it locally: render that session's clean transcript with our shared exporter and read it into context. There is NO cross-session messaging here — you never write to or notify the other session, you just read its transcript off disk.

Session to pull in: **$ARGUMENTS**

Steps:

1. **Find it.** Run:
   `python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py list-sessions`
   Match $ARGUMENTS to exactly one title. If it's ambiguous or not listed, show the candidates and ask which — never guess. It's the source, so it must not be this current session. (Add `--cwd <path>` if the session lives in a different project.)

2. **Render its clean transcript.** Run:
   `python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py export-session "<matched title>" --out /tmp`
   It prints the path of the `.md` it wrote. For a very long session, instead grab the tail:
   `python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py delta "<matched title>" --tail 40`
   (prints the last 40 exchanges to stdout — no file).

3. **Read it in.** Read the `.md` it wrote (or use the delta stdout). Then give the user a 2–4 line orientation: what that session was doing and where it left off, and ask what they want to bring over or do with it here.

Pull one session per invocation. Read-only: this never writes to, messages, or disturbs the source session.
