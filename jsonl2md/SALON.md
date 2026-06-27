# The Salon Protocol

A way to run several Claude Code sessions as a **salon** — independent, long-lived
conversation threads (some of them deliberately adversarial) — and route curated
excerpts between them, with **you** as the switchboard.

This is not agent-to-agent orchestration. A2A / MCP / "agent-as-tool" all exist to
let one agent call another *without* a human in the routing loop. The salon is the
inverse: the agents never address each other; you hand-carry what crosses, when it
crosses, and to whom. The value is your editorial judgment. The closest old idea is
the **blackboard** architecture — anonymous knowledge sources that only read/write a
shared medium, with a *control component* deciding who acts next. You are that control
component.

## The one rule

You stay the mediator. You **open** a connection by naming a peer and authorizing a
relay; you **close** it by withholding the next authorization. Nothing crosses between
two threads unless you, per message, send it.

## The two primitives

| Need | Tool | Why it fits |
| --- | --- | --- |
| **Read** "what's new in thread A since I last shared" | `jsonl2md.py delta "<A title>"` | per-session cursor; previews by default, advances only on `--commit` |
| **Cross** an excerpt into live thread B | `mcp__ccd_session_mgmt__send_message(session_id, message)` | lands as a labelled `From {A title}` user turn; **always asks you to confirm**; disabled in unsupervised/bypass mode |
| **Find** B's `session_id` | `mcp__ccd_session_mgmt__list_sessions()` / `search_session_transcripts(query)` | the confirm dialog + the `From {title}` label are your guards against a wrong target |

`send_message`'s mandatory confirm is the gate. You can read the exact outgoing
payload and decline (or decline and ask A to trim) before anything crosses. That is
the switchboard, enforced by the harness, not by discipline.

## The physical limit (set expectations here)

**No mechanism wakes an idle session.** `send_message` *enqueues* a user turn in B; B
acts on it the next time B runs. If B is parked at its prompt, the relayed turn sits
unread until you focus B and let it go. So:

- "Real-time" only exists while both threads are actively looping.
- Otherwise the salon is a **human-clocked mailbox** — which is the point. You are the clock.

Don't try to build around this. The hooks can't fix it (`Stop` hooks fire only when a
session takes a turn; a parked session takes none), and a daemon can't fix it
(`send_message` is the only injection seam, and it always prompts and always queues).

## The workflow

### Open
Decide the pairing. In thread A, get B's id:

```
mcp__ccd_session_mgmt__list_sessions()
```

Then tell A, in plain language, the standing instruction — this *is* the open:

> You are relaying to session **"<B title>"** (id `<uuid>`). When I say **relay**, call
> `send_message` to that id with **only your most recent finding**, verbatim, no preamble.
> If I say **relay since last**, I'll paste the new turns; relay exactly those.

(Because the binding lives in A's context, re-state it after a compaction, or pin it
in the project's `CLAUDE.md`.)

### Relay (A → B)
Type `relay`. A calls `send_message(session_id=<B>, message="<its last finding>")`. You
confirm (or decline). On confirm it lands in B as a `From {A}` user turn. B treats it
like any prompt on its next turn.

For a multi-turn delta instead of "last finding," run the cursor:

```
jsonl2md.py delta "<A title>"            # preview the new turns
jsonl2md.py delta "<A title>" --commit   # once you've actually relayed them
```

Paste that into A's `relay`, or straight into B yourself.

### Reply (B → A)
B, seeing a `From {A}` turn, replies by calling `send_message` back to A's id (tell B
once, or include "reply via send_message to id `<A-uuid>`" in the relayed payload). You
confirm the return hop in B's window. It lands in A as `From {B}`. Two symmetric,
independently-confirmed sends = a genuine round-trip, no copy-paste-back.

### Close
Stop authorizing relays — decline the next confirm, or tell A "stop relaying to B."
Silence is closed; there's no background channel to tear down. To fully drop the
binding, clear A's instruction.

## Honest limits

- **Idle peers don't auto-process** (see above) — nudge B's window for the relay to land.
- **Two confirms per round-trip.** That friction *is* the mediation; it's also friction.
- **Off in bypass/unsupervised mode** — `send_message` is unavailable when running headless.
- **No edit-in-flight.** The confirm is accept/decline; to alter a payload, decline and
  ask the agent to rephrase.
- **Echo risk.** A relayed turn becomes a real user turn in B's transcript, so a later
  `delta "B"` will re-emit it. Curate; don't ping-pong the same text.

## Invoking it: the `/relay` command

Don't put this in `CLAUDE.md`. A `CLAUDE.md` stanza is **ambient** — it loads into every
agent in the project on every turn, including the ones that will never relay. Use a
custom slash command instead: its body enters context **only when you type `/relay`, only
in that chat**, and is invisible to every other session until then.

The command is tracked in this repo at [`commands/relay.md`](commands/relay.md) and
symlinked into `~/.claude/commands/relay.md` (user scope — available in every chat,
ambient cost zero):

```
/relay PCB Viewer
/relay PCB Viewer — just the divider-net via count, nothing else
/relay Adversary — does the pour clearance survive a 0.2 mm shift?
```

It resolves the peer via `list_sessions`, picks the payload (your most recent finding,
or the text you named after a `—`), and calls `send_message` — which always shows you the
confirm dialog. The command is marked `disable-model-invocation`, so only you can fire it;
the agent never relays on its own.

Works the same in the macOS app: type `/` in the prompt box (or **+** → **Slash
commands**) and pick `relay`. To scope it to one project instead of everywhere, link (or
copy) the file into that project's `.claude/commands/relay.md`.

**Install** — from the monorepo root, `./install.sh` symlinks this command (and any
other `jsonl2md/commands/*.md`) into `~/.claude/commands/`. By hand, equivalently:

```sh
ln -sfn "$(pwd)/commands/relay.md" ~/.claude/commands/relay.md   # run from this jsonl2md/ dir
```
