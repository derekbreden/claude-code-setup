---
description: Deliver a message into another live Claude Code session or Codex task when the user asks you to send it. An agent the user only names, describes or relays is context, not a recipient. The write half of /relay.
argument-hint: <target session or task title> — <message to deliver>
allowed-tools: Bash(python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py:*)
---

Send a message into another of the user's agents. Request: **$ARGUMENTS**

**Send only what the user asks you to send.** A `/relay-send` they typed is that ask, and so are
"ask iOS what the header chevron was for", "send it to Readiness", "coordinate with Snap fits",
and a yes to your own "May I message Snap fits?". Each covers the agent and the exchange it
names, not later work.

Everything else the user says about another agent is context: "your peer 'Readiness' is working
on the PCB move", a `/relay` of its transcript, a note on whose files those are. The user is
telling you what else is going on so you can work with them, not handing you a channel, and a
"don't message it" holds for the whole conversation, whatever you find later. When something you
find matters to another agent — you are about to commit a file it is mid-edit in, you found the
bug it is hunting — tell the user and let them decide whether it goes further. Each agent is in
its own conversation with the user; a message lands there as a turn the user did not write and
pulls that agent off what the user is saying to it.

1. Resolve the exact target with `python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py board`.
   The roster includes both runtimes. For an ambiguous title, use its id or `--kind claude|codex`.
   If the intended target is unclear, ask rather than guessing.
2. Use a native tool when available: Claude peers use `SendMessage`; Codex tasks use
   `mcp__codex_app__send_message_to_thread`. The script redirects same-runtime callers to
   these tools without sending anything. A Claude session in the cloud, or on another
   machine, is a Claude peer too: the board prints its address (`bridge:session_…`) and
   `SendMessage` takes it verbatim. Such a session cannot reply here; read its answer with
   `/relay` or `jsonl2md.py delta "<title>"`.
3. For cross-runtime delivery, run:

   ```sh
   python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py send "<target>" "<message>" --from "<your task title>"
   ```

   If a suggested native tool is unavailable, `--force-relay` selects the live script
   transport. It steers an active Codex task or starts an idle task, and submits directly
   to Claude's peer receiver, which wakes an idle session. The target must be open in its
   running desktop runtime.
4. Report the actual result. Acceptance is not a read receipt. A disconnected receiver fails
   the send; nothing is silently queued. Exit status 2 means the outcome is unknown: inspect
   the receiver before retrying. Do not repeat an accepted send while waiting for an answer.

## Replies

Add `--reply-to "<your own id or exact title>"` when you need an answer. A stable id is preferable
when titles may change. The reply follows the same live routes. Continue independent work while
waiting. A reply does not itself need to request another reply.

When a message from another agent asks you something, answer that question through the route it
gives. The answer is the whole exchange: no acknowledgement follows it, and a correction, a status
or a request of your own goes to the user first.

## Writing the message

The receiver does not share your conversation history. Lead with the fact that changes what it
does, identify yourself, and include enough context for it to act. Skip acknowledgements and
status echoes that do not change its work.
