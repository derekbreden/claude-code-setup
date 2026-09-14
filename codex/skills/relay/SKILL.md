---
name: relay
description: Read another agent's full transcript, or send a message into one, across both runtimes on this machine — Codex tasks and Claude Code sessions. Use when the user asks to relay, to read an entire/full task or session, to see only what they and the agent said, or to tell/ask/coordinate with another agent by name. Not for a quick status snapshot of your own work.
---

# Relay

Two runtimes work this machine: **Codex tasks** (you) and **Claude Code sessions**. Use native
messaging when the caller can reach the target that way. The script provides transcript
exports, a shared roster, and live delivery across the two runtimes.

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
  A Codex caller reaches that same live receiver with the script below.
- **Cross-runtime or no native tool available:** use the script below. It steers an active
  Codex task or starts an idle task, and submits directly to a Claude peer receiver, which
  wakes an idle session. The target must be open in its running desktop runtime.
- **A Claude session in the cloud, or on another machine:** the same script verb. The board
  lists it with what it is; the script posts the message to its cloud record, the way the
  CLI's own peer messaging does. A cloud session answers with a `<relay to="<your title>">`
  mark in its reply, which the cloud-inbox watcher on this Mac delivers into your task; the
  message you send already tells it so. It reads a local transcript with
  `<relay read="<title>" tail="40"/>`, answered the same way.

```sh
python3 $J send "<exact title>" "<message>" --from "<your own task name>"
```

The script redirects Codex-to-Codex callers to native task messaging, just as it redirects
Claude callers when a Claude target has a peer address. A redirect sends nothing. If the
named native tool is unavailable in the caller's actual tool list, `--force-relay` selects
the live script transport. A failed live send does not create a delayed queue. Exit status
2 means delivery is uncertain: inspect the receiver before retrying. Never repeat an accepted
send just because the receiver has not answered yet.

A title that exists in **both** runtimes is refused rather than guessed; pass `--kind claude` or
`--kind codex` to say which. A cloud record's id works as a title in every spelling
(`cse_…`, `session_…`, `bridge:session_…`).

No route shares your conversation history. Lead with the fact that changes what the receiver
does, and identify agent-authored messages as coming from the agent.

### If you want an answer back

For native task messaging, include your own task title and `threadId` in the prompt when you
need a reply, plus `hostId` when supplied. The receiver uses the same native tool to answer.
Continue independent work while waiting; sending is not evidence the receiver has read it.

With the script, **`--reply-to` is your OWN address, not the target's**. Prefer your stable
task id; an exact, unambiguous title also works:

```sh
python3 $J send "<target>" "<message>" --from "C14 2" --reply-to "C14 2"
```

Live replies enter the active turn or wake the idle receiver. No `await-reply` watcher is
needed. Continue independent work while waiting. Answer a question or send a correction when
it changes what the sender should do. A reply does not itself need `--reply-to`.

### Legacy Claude sessions

When a Claude session has no live receiver, open it in a current runtime. If delivery on its
next tool call is specifically wanted, use `--defer --expires-in 300`. This explicit mailbox
path does not wake an idle session; `--mode interrupt|nudge` applies only here. Expired messages
are retained under the mailbox's `expired/` directory and omitted from delivery. The default
lifetime is five minutes, including old mailbox entries without an explicit expiry.

## When to send on your own initiative

Only when the user has opened the door — naming another agent, asking you to coordinate, or a
message arriving from one (which names it and hands you a channel back). Absent that, tell the
user what you would say and let them decide.

Reply to the agent, not about it: when the other side is holding a stale picture — you are about
to commit the file it is mid-edit in, you found the bug it is hunting — it is the one who needs
the fact, and routing it through the user makes them the courier. What does not earn a message is
acknowledgement: "got it", agreement, a status echo with nothing in it the receiver would act on.
