---
description: Deliver a message into another live Claude Code session or Codex task. The write half of /relay.
argument-hint: <target session or task title> — <message to deliver>
allowed-tools: Bash(python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py:*)
---

Send a message into another of the user's agents. Request: **$ARGUMENTS**

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
when titles may change. The reply follows the same live routes; no watcher needs to be armed.
Continue independent work while waiting. Answer questions and send facts that change what the
other agent should do. A reply does not itself need to request another reply.

## Legacy Claude receivers

A session without a peer socket needs to be opened in a current Claude runtime for live
messages. To intentionally leave a message for its next tool call, use `--defer --expires-in 300`.
The default lifetime is five minutes. The delivery hook archives expired messages under
`~/.claude/hooks/relay-inbox/<sessionId>/expired/` and omits them from the agent's input.
`--mode interrupt` blocks that next tool call; `--mode nudge` attaches context without blocking.
These modes apply only to deferred messages. `await-reply` is a compatibility watcher for
explicitly deferred replies, to be run in the background only on a legacy receiver.

## Coordination

Send when the user has asked you to communicate or coordinate with the other agent. Lead with
the fact that changes what the receiver does, identify yourself, and include enough context
for it to act. The receiver does not share your conversation history. Skip acknowledgements
and status echoes that do not change its work.
