---
name: relay
description: Read another agent's full transcript, or send a message into one, across both runtimes on this machine — Codex tasks and Claude Code sessions. Use when the user asks to relay, to read an entire/full task or session, to see only what they and the agent said, or to tell/ask/coordinate with another agent by name. Not for a quick status snapshot of your own work.
---

# Relay

Two runtimes work this machine: **Codex tasks** (you) and **Claude Code sessions**. They share
the tree and the user routes between them. This skill reads either one, and writes into either
one, through a single tool.

```sh
J=~/Developer/claude-code-setup/jsonl2md/jsonl2md.py
```

## Who is here

One roster, both runtimes, with the call that reaches each:

```sh
python3 $J board
```

The `RUNTIME` column is the thing to read. **A title in one runtime does not exist in the other**
— "C14" may be a Claude session while "C14 2" is your own task. If `list-codex-sessions` cannot
find a title, that is not evidence the session is missing; it is evidence the title belongs to
the other runtime. Check `board` before reporting anything absent.

## Reading a transcript

Match an **exact** title. If a title is absent or ambiguous, show the candidates instead of
guessing.

A Claude Code session:

```sh
python3 $J list-sessions
python3 $J export-session "<exact title>" --out /tmp     # prints the .md path it wrote
python3 $J delta "<exact title>" --tail 40               # just the last 40 exchanges, to stdout
```

One of your own Codex tasks:

```sh
python3 $J list-codex-sessions
python3 $J export-codex-session "<exact title>" --out /tmp
python3 $J export-codex-session "<exact title>" --tail 40
```

Read the emitted Markdown **completely**. If it exceeds one file read, continue in sequential
chunks until EOF. Do not substitute a summary, a tail, or a claimed representative sample when
the user asked for the entire conversation. To carry a long transcript whole rather than only
its end, add `--compact` to either verb: the user's own turns come through intact and each run
of agent messages is cut in the middle, marked with what it removed.

The export contains every user-authored message and every visible agent message in order. It
omits reasoning, commands, tool calls and outputs, developer/system context, and peer-task
delivery envelopes.

## Sending a message into another agent

```sh
python3 $J send "<exact title>" "<message>" --from "<your own task name>"
```

One verb, both runtimes — it resolves the title on `board` and picks the transport:

- a **Claude session** gets a file in its relay mailbox, which its delivery hook injects on that
  session's next tool call;
- a **Codex task** gets the message through `codex queue`, delivered as a follow-up turn.

A title that exists in **both** runtimes is refused rather than guessed; pass `--kind claude` or
`--kind codex` to say which.

The receiver sees your message text and nothing else — no shared history, no thread. Lead with
the fact that changes what it does.

### If you want an answer back

Delivery is one-way. When your message asks something, give a return address so the other agent
is told how to reach you. **`--reply-to` is your OWN address, not the target's** — for you that is
your task's exact title:

```sh
python3 $J send "<target>" "<message>" --from "C14 2" --reply-to "C14 2"
```

The answer arrives as a follow-up turn in this task, the same way this message did. You cannot
block waiting for it, so send what you need answered and carry on with what does not depend on it.

**The reciprocal duty:** when a message arrives carrying a return address, someone is waiting on
it — a Claude session that gave one is very likely parked on `await-reply`, and nothing but a
reply releases it. Answer, even briefly; "no, keep it" is a complete reply. The envelope you
receive carries the exact command to send it with.

## When to send on your own initiative

Only when the user has opened the door — naming another agent, asking you to coordinate, or a
message arriving from one (which names it and hands you a channel back). Absent that, tell the
user what you would say and let them decide.

Reply to the agent, not about it: when the other side is holding a stale picture — you are about
to commit the file it is mid-edit in, you found the bug it is hunting — it is the one who needs
the fact, and routing it through the user makes them the courier. What does not earn a message is
acknowledgement: "got it", agreement, a status echo with nothing in it the receiver would act on.
