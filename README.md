# claude-code-setup

My Claude Code customizations for macOS, plus the Codex half of the relay and the OpenCode
half of the hooks. Claude Code sessions and Codex tasks work this machine, and the relay
spans both: either one can read the other's clean transcript, and either one can
send a message into the other. Claude sessions that are not on this machine — running
in the cloud from the desktop app's Code tab, or bridged from another computer — are
read and messaged the same way, through their cloud records. Native messaging is
preferred within each runtime; the relay supplies cross-runtime delivery and a fallback
when native tools are absent. OpenCode sessions run the same hooks and read the same memory
notes; the relay does not reach them. One `install.sh` wires it all into the three clients.

| Folder | What it is | How it reaches the client |
| --- | --- | --- |
| `hooks/` | Bash guardrail hooks (Stop, PreToolUse, PostToolUse, UserPromptSubmit) — effort estimates, residue, etc. | referenced by absolute path from `~/.claude/settings.json` |
| `jsonl2md/` | Session export, the cross-runtime `board`/`send` verbs, `delta`/`watch`, and the `/relay` + `/relay-send` commands (`commands/`, doc in `SALON.md`) | `jsonl2md.py` is a CLI; `commands/*.md` are symlinked into `~/.claude/commands/` |
| `codex/` | The Codex `relay` skill: read either runtime's transcript, send into either runtime | symlinked into `~/.codex/skills/relay/` |
| `opencode/` | The plugin that runs these hooks inside OpenCode, the plugin that gives its shell Claude Code's `grep` and `find`, the plugin that keeps Inkling 2 Mini's thinking between steps, and the memory and Chrome instructions its sessions get (doc in `opencode/README.md`) | the plugins are symlinked into `~/.config/opencode/plugins/`; the instructions are named in `~/.config/opencode/opencode.jsonc` |
| `offload/` | Moves archived sessions' transcripts into iCloud Drive behind symlinks and evicts the local copies (doc in `offload/README.md`) | an hourly LaunchAgent rendered from `launchd/` |

The mechanisms differ by design: Claude hooks are discovered through `settings.json`,
Claude slash commands under `~/.claude/commands/`, Codex skills under
`~/.codex/skills/`, OpenCode plugins under `~/.config/opencode/plugins/`, and the offload job
by launchd. `install.sh` performs all five registrations.

## Install

```sh
./install.sh
```

Symlinks every `jsonl2md/commands/*.md` into `~/.claude/commands/`, the Codex relay skill
into `~/.codex/skills/`, the OpenCode plugins into `~/.config/opencode/plugins/`, ensures
the hooks are executable, prints the base path to reference them from
`~/.claude/settings.json`, and renders and loads the transcript-offload LaunchAgent.
Re-runnable. The `settings.json` hook entries and `~/.config/opencode/opencode.jsonc` are
hand-curated and not rewritten by the script.

See [`jsonl2md/SALON.md`](jsonl2md/SALON.md) for the `/relay` pull shortcut — bringing one
session's clean transcript into another — the `delta`/`watch` tools behind it, and the
cross-runtime channel between Claude and Codex.
