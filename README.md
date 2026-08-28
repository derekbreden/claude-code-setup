# claude-code-setup

My Claude Code customizations for macOS, plus the Codex half of the relay. Two
runtimes work this machine — Claude Code sessions and Codex tasks — and the relay
spans both: either one can read the other's clean transcript, and either one can
send a message into the other. One `install.sh` wires it all into both clients.

| Folder | What it is | How it reaches the client |
| --- | --- | --- |
| `hooks/` | Bash guardrail hooks (Stop, PreToolUse, PostToolUse, UserPromptSubmit, SessionStart) — effort estimates, unexplained hedges, residue, abandoned forks, etc. | referenced by absolute path from `~/.claude/settings.json` |
| `jsonl2md/` | Session export, the cross-runtime `board`/`send` verbs, `delta`/`watch`, and the `/relay` + `/relay-send` commands (`commands/`, doc in `SALON.md`) | `jsonl2md.py` is a CLI; `commands/*.md` are symlinked into `~/.claude/commands/` |
| `codex/` | The Codex `relay` skill: read either runtime's transcript, send into either runtime | symlinked into `~/.codex/skills/relay/` |

The mechanisms differ by design: Claude hooks are discovered through `settings.json`,
Claude slash commands under `~/.claude/commands/`, and Codex skills under
`~/.codex/skills/`. `install.sh` performs all three registrations.

## Install

```sh
./install.sh
```

Symlinks every `jsonl2md/commands/*.md` into `~/.claude/commands/`, the Codex relay skill
into `~/.codex/skills/`, ensures the hooks are executable, and prints the base path to
reference them from `~/.claude/settings.json`. Re-runnable. The `settings.json` hook
entries are hand-curated and not rewritten by the script.

See [`jsonl2md/SALON.md`](jsonl2md/SALON.md) for the `/relay` pull shortcut — bringing one
session's clean transcript into another — the `delta`/`watch` tools behind it, and the
cross-runtime channel between Claude and Codex.
