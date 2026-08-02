---
description: Pull other Claude Code sessions' clean transcripts INTO this one — renders them with jsonl2md and reads them in. Local only; no cross-session messaging.
argument-hint: <source session title(s) or hint>
disable-model-invocation: true
allowed-tools: Bash(python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py:*), Read
---

Relay the contents of the user's other Claude Code sessions INTO this one. You do it locally: render each session's clean transcript with our shared exporter and read it into context. There is NO cross-session messaging here — you never write to or notify those sessions, you just read their transcripts off disk.

Request: **$ARGUMENTS**

Steps:

1. **Find them.** Run:
   `python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py list-sessions`
   Separate the session names from everything else in $ARGUMENTS — the arguments usually carry a job as well as the names ("read X and Y, then finish what they leave undone"). **Every session named anywhere in $ARGUMENTS is one to pull**, whether it's the leading argument or named only inside the job. Match each one to exactly one title. If one is ambiguous or not listed, show its candidates and ask which — never guess — and pull the ones that did resolve while you wait. They're the sources, so none may be this current session. (Add `--cwd <path>` if a session lives in a different project.)

2. **Render each clean transcript.** For each matched title:
   `python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py export-session "<matched title>" --out /tmp`
   It prints the path of the `.md` it wrote. For a very long session, instead grab the tail:
   `python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py delta "<matched title>" --tail 40`
   (prints the last 40 exchanges to stdout — no file).

3. **Read them in.** Read each `.md` it wrote (or use the delta stdout). Then give the user a 2–4 line orientation **per session** — what it was doing and where it left off — plus a line on how they relate when they share a tree. Then ask what they want to bring over or do here, unless $ARGUMENTS already told you.

**Pull every session the arguments name, all of them, in this one invocation.** Don't go pulling sessions the user didn't name — that is the limit, and it is the only one. If taking them all in full would crowd this context, reach for `delta --tail` on the longer ones rather than deferring any of them: splitting one request across several `/relay` calls buys nothing, since the transcripts land in the same context either way, and it makes the user ask twice for what they asked once.

Read-only: this never writes to, messages, or disturbs the source sessions.

To send a message the other way — interject into a live session — use `/relay-send`. That one is model-invocable, so if this relay leaves you with something another session needs in order to act, sending it is yours to do; its own body carries the rules for when. (This command is not model-invocable: landing whole transcripts in your context is the user's call to make. That's about who starts a relay, not how many sessions one relay may carry.)

If what you send asks a question, arm `await-reply` in the background before you stop — nothing wakes an idle session, so a reply you have not armed for is one you will never see. `/relay-send` carries the exact incantation.
