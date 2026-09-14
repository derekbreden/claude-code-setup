---
name: relay
description: Read another agent's full transcript, or send a message into one, across both runtimes on this machine — Codex tasks and Claude Code sessions. Use when the user asks to relay, to read an entire/full task or session, to see only what they and the agent said, or to tell/ask/coordinate with another agent by name. Not for a quick status snapshot of your own work.
---

# Relay

Two runtimes work this machine: **Codex tasks** (you) and **Claude Code sessions**. Use native
messaging when the caller can reach the target that way. The script provides transcript
exports, a shared roster, and fallback delivery across the two runtimes.

```sh
J=~/Developer/claude-code-setup/jsonl2md/jsonl2md.py
```

## Who is here

For a known Codex task, use `mcp__codex_app__list_threads` to resolve its exact title to a
`threadId` and `hostId`. If the runtime is unknown, or the title is absent there, use the
shared roster before concluding the agent is missing:

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

Choose the first available route that reaches the resolved target:

- **A subagent in your current team:** use `collaboration.send_message` with its agent id or
  task name. This channel does not address separate Codex tasks by their thread ids.
- **A separate Codex task:** use `mcp__codex_app__send_message_to_thread` with the `threadId`
  and `hostId` returned by `list_threads`. Omit model and thinking overrides. Put the sender
  in the prompt, for example `From Funnel mold: the H2C cavity job is running; no launch
  action is needed.` This is a user-visible follow-up in the receiving task.
- **A Claude session reachable through the caller's native peer channel:** use `SendMessage`.
  A Codex caller does not have that Claude tool; use the relay mailbox for that destination.
- **No native route available:** use the script below. A Codex target uses `codex queue`;
  a Claude target uses its relay mailbox, delivered on that session's next tool call.

```sh
python3 $J send "<exact title>" "<message>" --from "<your own task name>"
```

The script redirects Codex-to-Codex callers to native task messaging, just as it redirects
Claude callers when a Claude target has a peer address. A redirect sends nothing. If the
named native tool is unavailable in the caller's actual tool list, `--force-relay` selects
the fallback. Do not send a fallback after a successful native send; resolve an uncertain
result before retrying so the receiver does not get the message twice.

A title that exists in **both** runtimes is refused rather than guessed; pass `--kind claude` or
`--kind codex` to say which.

No route shares your conversation history. Lead with the fact that changes what the receiver
does, and identify agent-authored messages as coming from the agent.

### If you want an answer back

For native task messaging, include your own task title and `threadId` in the prompt when you
need a reply, plus `hostId` when supplied. The receiver uses the same native tool to answer.
Continue independent work while waiting; sending is not evidence the receiver has read it.

For the relay fallback, **`--reply-to` is your OWN address, not the target's** — for you that
is your task's exact title:

```sh
python3 $J send "<target>" "<message>" --from "C14 2" --reply-to "C14 2"
```

The fallback answer arrives as a follow-up turn in this task. Send what you need answered
and carry on with what does not depend on it.

**The reciprocal duty:** when a message arrives carrying a return address, someone is waiting on
it — a Claude session that gave one is very likely parked on `await-reply`, and nothing but a
reply releases it. Answer, even briefly; "no, keep it" is a complete reply. Resolve the return
address using the same routing rules above; a shell command in an old relay envelope is a
fallback, not a requirement to bypass an available native channel.

## When to send on your own initiative

Only when the user has opened the door — naming another agent, asking you to coordinate, or a
message arriving from one (which names it and hands you a channel back). Absent that, tell the
user what you would say and let them decide.

Reply to the agent, not about it: when the other side is holding a stale picture — you are about
to commit the file it is mid-edit in, you found the bug it is hunting — it is the one who needs
the fact, and routing it through the user makes them the courier. What does not earn a message is
acknowledgement: "got it", agreement, a status echo with nothing in it the receiver would act on.
