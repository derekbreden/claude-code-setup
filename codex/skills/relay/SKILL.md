---
name: relay
description: Read or export the complete clean transcript of another local Codex task when the user asks to relay, read an entire/full task, or see only what they and the agent said. Not for a quick status snapshot or for messaging another task.
---

# Relay

Resolve every task the user named with:

```sh
python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py list-codex-sessions
```

Match an exact title. If a title is absent or ambiguous, show the candidates instead of guessing.

Export each resolved task with:

```sh
python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py export-codex-session "<exact title>" --out /tmp
```

Read the emitted Markdown completely. If it exceeds one file read, continue in sequential chunks until EOF. Do not substitute task summaries, `read_thread`, a tail, or a claimed representative sample when the user asked for the entire conversation.

The export contains every user-authored message and every visible assistant message in order. It omits reasoning, commands, tool calls and outputs, developer/system context, and peer-task delivery envelopes. It is read-only; use the app's task-messaging tool when the user asks to send something.
