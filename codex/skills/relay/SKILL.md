---
name: relay
description: Read another agent's full transcript, or send a message into one, across both runtimes on this machine — Codex tasks and Claude Code sessions. Use when the user asks to relay, to read an entire/full task or session, to see only what they and the agent said, or asks you to tell, ask or coordinate with another agent. An agent the user only names, describes or relays is context, not a recipient. Not for a quick status snapshot of your own work.
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

## When to send

**Send only what the user asks you to send.** "Ask iOS what the header chevron was for", "send it
to Readiness", "coordinate with Snap fits", and a yes to your own "May I message Snap fits?" are
asks. Each covers the agent and the exchange it names, not later work.

Everything else the user says about another agent is context: "your peer 'Readiness' is working
on the PCB move", a relay of its transcript, a note on whose files those are. The user is telling
you what else is going on so you can work with them, not handing you a channel, and a "don't
message it" holds for the whole task, whatever you find later. When something you find matters to
another agent — you are about to commit a file it is mid-edit in, you found the bug it is hunting
— tell the user and let them decide whether it goes further. Each agent is in its own conversation
with the user; a message lands there as a turn the user did not write and pulls that agent off
what the user is saying to it.

When a message from another agent asks you something, answer that question through the route it
gives. The answer is the whole exchange: no acknowledgement follows it, and a correction, a status
or a request of your own goes to the user first.

## Sending a message into another agent

Choose the first available route that reaches the resolved target:

- **A subagent in your current team:** use `collaboration.send_message` with its agent id or
  task name. This channel does not address separate Codex tasks by their thread ids.
- **A separate Codex task:** use `mcp__codex_app__send_message_to_thread` with the `threadId`
  and `hostId` returned by `list_threads`. Omit model and thinking overrides. Put the sender
  in the prompt, for example `From Funnel mold: the user asks which cavity depth your H2C
  job printed.` This is a user-visible follow-up in the receiving task.
- **A Claude session reachable through the caller's native peer channel:** use `SendMessage`.
  A Codex caller reaches that same live receiver with the script below.
- **Cross-runtime or no native tool available:** use the script below. It steers an active
  Codex task or starts an idle task, and submits directly to a Claude peer receiver, which
  wakes an idle session. The target must be open in its running desktop runtime.
- **A Claude session in the cloud, or on another machine:** the same script verb. The board
  lists it with what it is; the script posts the message to its cloud record, the way the
  CLI's own peer messaging does. It cannot answer you through the relay: read its reply in
  its own transcript with `delta`.

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

Live replies enter the active turn or wake the idle receiver. Continue independent work while
waiting. A reply does not itself need `--reply-to`.
