---
description: Interject into another of my live agents — a Claude Code session or a Codex task — by queueing a message it picks up on its next turn. The write half of /relay.
argument-hint: <target session or task title> — <message to deliver>
allowed-tools: Bash(python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py:*)
---

Send a message INTO another of the user's live agents. Unlike `/relay` (which pulls a transcript in here, read-only), this writes.

Two runtimes work this machine and one verb reaches both — `send` resolves the title and picks the transport:

- a **Claude Code session** gets a file in its relay mailbox, which its delivery hook injects on that session's **next tool call**. Poll-on-action, not push: a working agent gets it within a tool call or two; a fully idle one waits until it next acts.
- a **Codex task** gets it through `codex queue`, delivered as a follow-up turn. A running task is interrupted at the end of its current turn; a parked one takes it when it next runs. The tool says which of the two happened.

Request: **$ARGUMENTS**

Steps:

1. **Resolve the target.** Run:
   `python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py board`
   One roster across both runtimes, with a `RUNTIME` column. Match the target from $ARGUMENTS to exactly one title. If ambiguous or absent, show the candidates and ask — never guess. It must not be this current session. (Add `--cwd <path>` if it lives in another project.)

   A handful of titles exist in **both** runtimes. `send` refuses those rather than guessing; pass `--kind claude` or `--kind codex` to say which.

2. **Confirm the message.** From $ARGUMENTS, separate the target from the message text. If the user hasn't given explicit text — e.g. they asked you to "tell them to reconsider" after reviewing that session via `/relay` — draft the message, show it, and confirm before sending. Keep it to what the receiving agent needs: it sees only this text, not our conversation.

3. **Send it.** Run:
   `python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py send "<matched title>" "<message>" --from "<label>"`
   For a Claude target the default mode is **interrupt** — it blocks the target's next tool call and puts the message in front of it; `--mode nudge` attaches it without blocking (gentler, but the agent may sail past it). A Codex target has no such distinction: a queued message is always read, and `--mode nudge` is ignored with a note. `--from` tags who's speaking, and is worth setting either way — the receiver sees the text and nothing else.

4. **Report** what it printed — the queued mailbox path for a Claude target, or the queued/delivered line for a Codex one. This never reads or disturbs the target's transcript.

## If you want an answer, arm the watcher before you stop

Delivery is one-way and poll-on-action. **Nothing wakes an idle session.** The moment you end your turn you have guaranteed you will not see the reply — it lands in your mailbox and sits there, because the hook that delivers it only runs on *your next tool call*, and an agent that has stopped makes none. Writing "tell me if you want it reverted" and then stopping is not a question; it is a message you have arranged never to receive the answer to.

So when your message asks anything, or when what you do next depends on what comes back:

```bash
python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py send "<target>" "<message>" --reply-to <YOUR OWN cliSessionId>
python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py await-reply <YOUR OWN cliSessionId> --timeout 3600
```

Run the second one with **`run_in_background: true`**. It blocks until something lands in your mailbox and then exits, and that exit is your wake-up — one notification, no polling on your part. `--timeout 0` waits indefinitely; the default hour is usually the right ceiling.

- **`--reply-to` is your own id, not the target's.** It rides along as a return address, and the receiving agent is told plainly that you are parked and that silence blocks you. A Codex receiver gets the literal shell command that reaches you, since it has no relay tooling of its own beyond this same script.
- **Your own id is in your scratchpad path** — `/tmp/claude-<uid>/<project>/<SESSION-ID>/scratchpad`. `await-reply` will not infer it, deliberately: the freshest transcript in a shared project belongs to the session you are waiting *on*, so guessing picks exactly the wrong mailbox and then waits forever in silence.
- **It does not drain the mailbox.** The delivery hook still hands you the full text, properly framed, on your next tool call; `await-reply` only tells you someone answered.

**The reciprocal duty:** when a message arrives carrying a return address, the sender is blocked on it. Answer, even briefly — "no, keep it" is a complete reply. Leaving it unanswered strands another agent until its timeout runs out.

## Reaching for this yourself

This command is model-invocable: when the user has pointed you at another agent — "coordinate with X", "that's the other agent working on this", "the Codex agent is taking that over" — sending is yours to do, not something to hand back. You do not need the slash command to do it; step 3's `send` is a plain Bash call and the same rules apply either way.

Three rules, because this WRITES into a context that is not yours:

- **Only when the user has opened the door.** Naming another session, or asking you to keep goals coordinated, is that door. A message arriving from a session by relay is that door too — it names the session and hands you a live channel back to it. Absent any door, tell the user what you would say and let them decide.
- **Reply to the session, not about it.** When a relayed message leaves the other agent holding a stale picture — you are about to commit the file it is mid-edit in, you found the bug it is hunting, the premise it acted on has moved — that agent is the one who needs the fact, and routing it through the user makes them the courier. Send it. What does not earn an interrupt is acknowledgement: "got it", "thanks", agreement, a status echo with nothing in it the receiver would act on. Say those to the user, or not at all.
- **Send what the receiver needs to act, not what you did.** It sees this text and nothing else — no shared history, no thread. Lead with the fact that changes its behavior. If the message would only be interesting, it is not worth an interrupt: use `--mode nudge` or skip it.
