# Relaying context between sessions

A shortcut for pulling one Claude Code session's conversation into another, so you can run
several long-lived sessions — some deliberately adversarial — and route context between
them at your discretion. **You** are the switchboard.

This is not agent-to-agent orchestration. A2A / MCP / "agent-as-tool" all exist to let one
agent call another *without* a human in the routing loop. This is the inverse: the sessions
never address each other; you decide what context crosses, when, and to which thread. The
closest old idea is the **blackboard** — independent workers that share a medium, with a
control component deciding who reads what. You are that control component.

## Two runtimes, one address space

Codex tasks and Claude Code sessions both work this tree, and each ships a channel for
talking to *its own kind* — Claude's `SendMessage` peer channel, Codex's `codex_delegation`
envelope. Neither one crosses. So the relay is what crosses, and it does it by being the
one place that knows both rosters:

```sh
jsonl2md.py board
```

```
RUNTIME  TITLE            REACH IT WITH                       LAST
claude   C14              SendMessage to: C14                 2026-08-28 00:24
claude   Clearances       send "Clearances"                   2026-08-27 20:57
codex    C14 2            send "C14 2"                        2026-08-27 23:28
codex    Storage          send "Storage"                      2026-08-23 01:32
```

The `RUNTIME` column is the whole point. Before it existed, an agent that could not find a
title in its own roster concluded the session did not exist — which is exactly what happened
the first time a Codex task was asked to read a Claude session, and it reported the title
missing rather than looking in the other runtime.

**Reading** either one is the same two verbs with a different spelling: `export-session` /
`delta` for Claude, `export-codex-session` for Codex, both with `--tail K` and `--compact`.

**Writing** is one verb for both. `send` resolves the title on the board and picks the
transport from the runtime it lands in:

| target | transport | when it arrives |
| --- | --- | --- |
| Claude session | a file in `~/.claude/hooks/relay-inbox/<id>/`, drained by a PreToolUse hook | that session's next tool call |
| Codex task | `codex queue --thread <id>`, the app's own follow-up queue | end of its current turn, or when it next runs |

A handful of titles exist in *both* rosters — "Manager", "Build", "Relay". `send` refuses
those rather than picking the runtime it happened to check first; `--kind claude|codex`
settles it.

Because a Codex task has no hook surface, the message it receives carries its own framing:
who sent it, that it is an out-of-band interjection, and the literal shell command that
reaches the sender back. That command is this same script, which is what closes the loop —
Codex answers a Claude session by writing into the Claude mailbox, and the Claude session's
`await-reply` is released by it.

## Pull, not push

The obvious mechanism — injecting a turn into another live session (`send_message`) — is a
dead end here: it is disabled whenever you run with **bypass permissions on**, which is
always. So the relay is a **pull**, not a push:

> Go to the session that needs the context and bring the other session's clean transcript
> into it.

`/relay <source title>`, run in the **destination** session, renders the **source**
session's clean transcript with jsonl2md and reads it in — from either runtime. One step. No messaging, no
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
- **`codex queue` needs the Codex app-server daemon up.** A Claude mailbox is a file and
  keeps until the target next acts; a Codex message goes through the running daemon, and
  `send` fails loud rather than silently dropping it when that is not there.
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
