# opencode

OpenCode is the third harness on this machine. This folder gives its sessions what Claude Code
sessions have: the hooks in [`../hooks/`](../hooks/README.md) and the memory notes.

| File | What it is | How it reaches OpenCode |
| --- | --- | --- |
| `claude-hooks/` | A plugin that runs the command hooks named in `~/.claude/settings.json` and in a project's `.claude/settings.json` | symlinked into `~/.config/opencode/plugins/` by `install.sh` |
| `memory.md` | How memory notes are read and written | listed under `instructions` in `~/.config/opencode/opencode.jsonc` |
| `chrome.md` | How to treat Derek's Chrome | the same `instructions` list |
| `examples/opencode.jsonc` | `~/.config/opencode/opencode.jsonc`: the model, the instructions, the Chrome server and the permission rules | hand-curated in place and mirrored here |

A project loads its own memory index with an `instructions` entry in its `opencode.jsonc`, as
homesodamachine's does.

## Hook events

| Claude Code event | OpenCode point | What carries over |
| --- | --- | --- |
| `PreToolUse` | `tool` `execute.before`, then the tool's `permission` `evaluate` | a deny or an ask; the reason becomes the tool's error |
| `PostToolUse` | `tool` `execute.after` | added context or a block reason, appended to the tool's result |
| `UserPromptSubmit` | `session` `prompt` | added context, as a harness note ahead of the prompt; a block refuses the prompt |
| `Stop` | `session` `experimental.idle` | a block, sent to the model as a harness note so the turn continues |

Each hook gets Claude Code's JSON on stdin: `session_id`, `transcript_path`, `cwd`,
`hook_event_name`, and for a tool call `tool_name` and `tool_input` in Claude Code's names.
`edit` is `Edit` with `file_path`, `old_string` and `new_string`; `write` is `Write` with
`file_path` and `content`; `shell` is `Bash` with `command`. A subagent's session reports the id
of the session that started it. `transcript_path` names a file under
`~/.local/state/opencode-claude-hooks/transcripts/` that holds each turn's final message in
Claude Code's record shape, which is what the Stop hook reads.

`~/.local/state/opencode-claude-hooks/bridge.jsonl` gets one line for each hook run that decided
something or failed.

Not carried: `SessionStart` and the events not in the table, `updatedInput`, `continue: false`,
hooks of a type other than `command`, and OpenCode's `patch` tool, which GPT models get in place
of `edit` and `write`.

## Session title

OpenCode's shell tool exports `OPENCODE_SESSION_ID` to every command it runs.
[`jsonl2md.py whoami`](../jsonl2md/README.md#who-you-are-whoami) reads that session's title from
OpenCode's database, so a commit's `Session:` trailer names the session.

## Trying a change

`opencode-cli --standalone run` starts a private server, and `XDG_CONFIG_HOME`, `XDG_DATA_HOME`
and `XDG_STATE_HOME` point it at a scratch config and database. A custom provider whose `baseURL`
is a local script that replays tool calls exercises every hook point with no model host.
