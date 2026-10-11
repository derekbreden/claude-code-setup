# hooks

Wired by absolute path in `~/.claude/settings.json`; `examples/settings.json` is that file's
`hooks` block. Each script's header says how it works.

| Hook | Runs on | Does |
| --- | --- | --- |
| `block-effort-estimate.sh` | Stop | Blocks an effort estimate in the final message (regex, then Haiku). |
| `block-residue.sh` | after a write | Notes justification, defense or decision narrative in what was written (regex, Haiku, then Opus). |
| `block-underived-measurement.sh` | after a write | Notes a hand-written dimension that should be a docgen marker (regex, then Haiku). |
| `warn-elevation-write.sh` | before a write | Bounces the first write per session to a CLAUDE.md, AGENTS.md or `calibration/`. |
| `block-memory-write.sh` | before a write | Bounces the first memory write per session to homesodamachine's `calibration/principle/Memory.md`. |
| `block-branch.sh` | before Bash | Denies starting or publishing a git branch in the shared checkout. |
| `block-task-sleep-poll.sh` | before Bash | Denies sleeping on a background task's own output file. |
| `block-web.sh` | before WebFetch, WebSearch | Denies each tool's first call per session, redirecting to Chrome. |
| `note-pick-text.sh` | a prompt | Points a prompt carrying `/3d` pick text at the format and the Find box. |

`_last_assistant_text.py` reads the final message for the Stop hook. The three model-calling
hooks read `~/.claude/anthropic_api_key` and log one line per run to `~/.claude/hooks/logs/`.
