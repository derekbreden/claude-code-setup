# Relaying context between sessions

A shortcut for pulling one Claude Code session's conversation into another, so you can run
several long-lived sessions — some deliberately adversarial — and route context between
them at your discretion. **You** are the switchboard.

This is not agent-to-agent orchestration. A2A / MCP / "agent-as-tool" all exist to let one
agent call another *without* a human in the routing loop. This is the inverse: the sessions
never address each other; you decide what context crosses, when, and to which thread. The
closest old idea is the **blackboard** — independent workers that share a medium, with a
control component deciding who reads what. You are that control component.

## Pull, not push

The obvious mechanism — injecting a turn into another live session (`send_message`) — is a
dead end here: it is disabled whenever you run with **bypass permissions on**, which is
always. So the relay is a **pull**, not a push:

> Go to the session that needs the context and bring the other session's clean transcript
> into it.

`/relay <source title>`, run in the **destination** session, renders the **source**
session's clean transcript with jsonl2md and reads it in. One step. No messaging, no
confirmation dialog, no idle-session problem — it's just a local tool reading a local file,
so it works in bypass mode where `send_message` cannot.

```
/relay PCB Viewer     # pull PCB Viewer's clean transcript into here
/relay Adversary      # bring the adversarial thread's reasoning over to weigh it
```

## Under the hood

No cross-session messaging. A session running on this machine is a file on this disk, and
reading it costs nothing; a session running on Anthropic's machines — one started in the
Code section of the desktop app — has its title and its transcript only on the server, so
that one is fetched, with the OAuth grant `claude` already signed in with. Either way the
verbs are the same:

- `jsonl2md.py list-sessions` — resolve the title (lists your user-titled sessions),
- `jsonl2md.py export-session "<title>" --out /tmp` — render the clean transcript
  (user/assistant text only; tool calls and thinking stripped),
- then read the `.md`.

Finer control:
- `jsonl2md.py delta "<title>"` — only what's new since you last pulled (per-session cursor;
  advances only on `--commit`).
- `jsonl2md.py delta "<title>" --tail K` — just the last K exchanges.
- `jsonl2md.py watch "<title>"` — stream a session's new turns live.

## You stay the switchboard

You initiate every pull — you run `/relay` in the thread where you want the context, and you
decide what to carry over from what it brings in. Nothing crosses on its own. To move context
the other direction, go to the other session and pull this one. There is no autonomous channel
to open or close; running the command *is* the act of routing.

## Limits

- The source must be a **user-titled, non-archived** session — that's what `list-sessions`
  shows. (For others, pass a `cliSessionId`, or render by transcript path.)
- It's a **snapshot at pull time**; re-run `/relay` (or `delta`) to refresh.
- **One direction per pull** — you route by choosing where you run it.
- A **cloud session is read-only from here**. `send` refuses it: the relay mailbox is a
  directory under this HOME that a session picks up on its next tool call, and a worker on
  someone else's machine never looks in it. Type into that one in the desktop app.
- Cloud sessions are matched to a project by **git remote**, since a cloud worker has no
  working directory — two checkouts of one repo see the same cloud sessions.
- `JSONL2MD_NO_CLOUD=1` skips the cloud entirely, for a caller that wants no network.

## The command

`/relay` is a custom slash command (not a `CLAUDE.md` stanza — that would load into every
agent every turn; a command's body enters context only when you invoke it). It's tracked at
[`commands/relay.md`](commands/relay.md) and symlinked into `~/.claude/commands/` by
`install.sh`. Works in the macOS app: type `/` and pick `relay`. `disable-model-invocation`
keeps it user-only — the agent never fires it on its own.
