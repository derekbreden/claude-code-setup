# opencode

OpenCode is the third harness on this machine. This folder gives its sessions what Claude Code
sessions have: the hooks in [`../hooks/`](../hooks/README.md) and the memory notes.

| File | What it is | How it reaches OpenCode |
| --- | --- | --- |
| `claude-hooks/` | A plugin that runs the command hooks named in `~/.claude/settings.json` and in a project's `.claude/settings.json` | symlinked into `~/.config/opencode/plugins/` by `install.sh` |
| `shell-tools/` | A plugin that puts `shell-tools/bin/` first on the path of every shell command, so `grep` and `find` are the ones Claude Code's shell runs | symlinked into `~/.config/opencode/plugins/` by `install.sh` |
| `inkling-thinking/` | A plugin that keeps Inkling 2 Mini's thinking in its context from one tool step to the next | symlinked into `~/.config/opencode/plugins/` by `install.sh` |
| `memory.md` | How memory notes are read and written | listed under `instructions` in `~/.config/opencode/opencode.jsonc` |
| `chrome.md` | How to treat Derek's Chrome | the same `instructions` list |
| `examples/opencode.jsonc` | `~/.config/opencode/opencode.jsonc`: the model and its context window, the instructions, the Chrome server and the permission rules | hand-curated in place and mirrored here |

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

## Shell tools

In Claude Code's Bash tool on this Mac, `grep` and `find` are shell functions over the ugrep and
bfs built into the `claude` binary: ignore files are honoured, and `.git` and binary files are
skipped. OpenCode's shell tool runs the system's. A whole-tree `grep -r` there walks build outputs
and caches, runs for minutes, passes its timeout and is left running in the background.

`shell-tools/bin/grep` and `shell-tools/bin/find` are those two commands as scripts, with the same
arguments Claude Code's shell snapshot passes, and the plugin puts that folder at the front of
`PATH` in the shell tool's `create.before` hook. Each falls back to the system command when
`~/.local/bin/claude` is missing.

## Inkling 2 Mini

Two things let Inkling 2 Mini weigh what it finds against what it was asked. Without both, it
finds that a request rests on something untrue and goes on building.

The lab streams each thinking block with an empty signature, and OpenCode replays only signed
thinking, so the model sees its earlier tool calls without its reasons. `inkling-thinking/` adds a
placeholder signature to each unsigned block in the lab's stream, and OpenCode then sends the
thinking back on the next step.

OpenCode takes the model's context window to be 1,048,576 tokens and summarizes a session only
near that size, so the request stays in front of the model word for word and each step re-reads
everything. `limit.input` for the model in `opencode.jsonc` is 131,072, which makes OpenCode
summarize from about 111,000 tokens. The model then works from a summary it wrote itself, with its
own doubts in it. `limit.context` set to the same number moves the summary to the same point but
leaves the summary request about 10,000 output tokens, and a summary that needs more ends the
session with "Compaction summary reached the output token limit".

## Effort

Derek runs every model at max effort. OpenCode's own default sends Claude adaptive thinking with no
effort named and sends Inkling no thinking setting at all, and its picker's choice lasts only for
the session it was made in. In `opencode.jsonc` each model's `body` entry names max effort, and
OpenCode sends a `body` entry on every request, over whatever the picker says. A headless run can
also name it in the model id: `anthropic/claude-opus-5-5#max`.

## Session title

OpenCode's shell tool exports `OPENCODE_SESSION_ID` to every command it runs.
[`jsonl2md.py whoami`](../jsonl2md/README.md#who-you-are-whoami) reads that session's title from
OpenCode's database, so a commit's `Session:` trailer names the session. It reads the session's
model from the same row, so the commit's `Model:` trailer and a memory note's `model` line name
the model that wrote them.

## Trying a change

`opencode-cli --standalone run` starts a private server, and `XDG_CONFIG_HOME`, `XDG_DATA_HOME`
and `XDG_STATE_HOME` point it at a scratch config and database. A custom provider whose `baseURL`
is a local script that replays tool calls exercises every hook point with no model host.
