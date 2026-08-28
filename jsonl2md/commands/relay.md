---
description: Pull other agents' clean transcripts INTO this one — Claude Code sessions and Codex tasks alike, rendered with jsonl2md and read in. Local only; no cross-session messaging.
argument-hint: <source session title(s) or hint>
disable-model-invocation: true
allowed-tools: Bash(python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py:*), Read
---

Relay the contents of the user's other agents INTO this one. Two runtimes work this machine — **Claude Code sessions** and **Codex tasks** — and both are readable the same way: render the clean transcript with our shared exporter and read it into context. There is NO cross-session messaging here — you never write to or notify those sessions, you just read their transcripts off disk.

Request: **$ARGUMENTS**

Steps:

1. **Find them.** Run:
   `python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py board`
   That is one roster across both runtimes, with a `RUNTIME` column saying which each title
   belongs to. **A title absent from one runtime is not a missing session — it is a session in
   the other one**, so read the whole board before reporting anything unfindable.
   Separate the session names from everything else in $ARGUMENTS — the arguments usually carry a job as well as the names ("read X and Y, then finish what they leave undone"). **Every session named anywhere in $ARGUMENTS is one to pull**, whether it's the leading argument or named only inside the job. Match each one to exactly one title. If one is ambiguous or not listed, show its candidates and ask which — never guess — and pull the ones that did resolve while you wait. They're the sources, so none may be this current session. (Add `--cwd <path>` if a session lives in a different project.)

2. **Render each clean transcript.** The verb follows the runtime the board named.

   A **Claude** session:
   `python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py export-session "<matched title>" --out /tmp`
   It prints the path of the `.md` it wrote. For a very long one, instead grab the tail:
   `python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py delta "<matched title>" --tail 40`

   A **Codex** task:
   `python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py export-codex-session "<matched title>" --out /tmp`
   with the same tail shortcut: `export-codex-session "<matched title>" --tail 40`

   Both tails print to stdout — no file. To carry a long transcript whole rather than only its
   end, add `--compact` to either: the user's turns come through intact and each run of agent
   messages is cut in the middle, marked with what it removed.

3. **Read them in.** Read each `.md` it wrote (or use the delta stdout). Then give the user a 2–4 line orientation **per session** — what it was doing and where it left off — plus a line on how they relate when they share a tree. Then ask what they want to bring over or do here, unless $ARGUMENTS already told you.

**Pull every session the arguments name, all of them, in this one invocation.** Don't go pulling sessions the user didn't name — that is the limit, and it is the only one. If taking them all in full would crowd this context, reach for `delta --tail` on the longer ones rather than deferring any of them: splitting one request across several `/relay` calls buys nothing, since the transcripts land in the same context either way, and it makes the user ask twice for what they asked once.

Read-only: this never writes to, messages, or disturbs the source sessions.

To send a message the other way — interject into a live session or Codex task — use `/relay-send`. That one is model-invocable, so if this relay leaves you with something another session needs in order to act, sending it is yours to do; its own body carries the rules for when. (This command is not model-invocable: landing whole transcripts in your context is the user's call to make. That's about who starts a relay, not how many sessions one relay may carry.)

If what you send asks a question, arm `await-reply` in the background before you stop — nothing wakes an idle session, so a reply you have not armed for is one you will never see. `/relay-send` carries the exact incantation.
