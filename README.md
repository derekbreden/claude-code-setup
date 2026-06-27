# claude-code-setup

My Claude Code customizations for macOS, in one repo. Each area is a top-level
folder; one `install.sh` wires them into `~/.claude`.

| Folder | What it is | How it reaches Claude Code |
| --- | --- | --- |
| `hooks/` | Bash guardrail hooks (Stop + PreToolUse) — effort estimates, unexplained hedges, residue, etc. | referenced by absolute path from `~/.claude/settings.json` |
| `jsonl2md/` | Session export + `delta`/`watch` relay tool, the `/relay` slash command (`commands/`), and the Salon Protocol (`SALON.md`) | `jsonl2md.py` is a CLI; `commands/relay.md` is symlinked into `~/.claude/commands/` |

The two mechanisms differ by design: hooks are only discovered via `settings.json`
path entries (there is no `~/.claude/hooks/` auto-load), and slash commands are only
discovered under `~/.claude/commands/`. Neither can adopt the other's wiring — so
`install.sh` is the one place that performs both, and the rule is simply: **anything
that wires into `~/.claude` gets registered in `install.sh`.**

## Install

```sh
./install.sh
```

Symlinks every `jsonl2md/commands/*.md` into `~/.claude/commands/`, ensures the hooks
are executable, and prints the base path to reference them from `~/.claude/settings.json`.
Re-runnable. The `settings.json` hook entries are hand-curated and not rewritten by the
script.

See [`jsonl2md/SALON.md`](jsonl2md/SALON.md) for the human-mediated session-to-session
relay workflow that ties the `delta` tool and the `/relay` command together.
