# hooks

Claude Code hooks, referenced by absolute path from `~/.claude/settings.json`; `examples/settings.json` is that file's `hooks` block, verbatim. Two Stop hooks judge the assistant's final message: one blocks effort estimates, and one refuses a stop that claims to be waiting on background work nothing is running — that one also runs on SubagentStop, so a subagent's final report meets it before a manager reads it. Two PostToolUse hooks read what a write left on disk and hand back a note rather than a denial: residue (justification, defense, decision narrative — the author going beyond describing what is), and underived measurements (bare dimensional literals that should be docgen markers fed from a source constant). Eight PreToolUse hooks gate tool calls: one on every tool delivers relay messages queued for the session; one on writes is a one-bounce speed bump at the elevation every future session reads as Derek (CLAUDE.md, AGENTS.md, the calibration); five on `Bash` deny branch creation, a firmware flash from a dirty tree, an `rg` search with `.gitignore` disabled, a video publish that hasn't cleared the floor, and a sleep loop on a harness task's own output file; one on `WebFetch` and `WebSearch` denies the first call of each per session with a redirect to Chrome MCP. One hook injects context: when a prompt carries step-viewer pick text, it points the agent at the format's home and at the fact the channel is two-way. A SessionStart hook reaps helper forks still running after the turn that spawned them. Three scripts sit in the tree unwired: `block-question-as-disagreement.sh`, `block-commit-curation.sh`, and `note-inherited-fence.sh`.

This is a personal tool, put on GitHub in case it helps someone running similar configurations. It is not a polished, configurable, cross-platform library — read the next section before assuming it'll work for you.

## Who this is for

You'll get value from this if **all** of the following are true:

- You're using **Claude Code** and want it to block specific patterns in the assistant's turns and tool calls.
- For the two-stage hooks: you're OK with **Anthropic API charges** — one small Haiku call per event when the regex pre-filter matches (a tiny fraction of events), and for the residue hook an Opus call on the whole file when Haiku says yes.
- You're comfortable with **bash + jq + curl + perl** in your hook scripts and editing `~/.claude/settings.json` by hand.

You will *not* get value from this if:

- You want a **UI** for configuring patterns.
- You want **portable, OS-agnostic** hooks (these use `tail -r`/`tac` and other shell quirks).
- You want **fine-grained control over which sessions** a hook applies to (these run on every relevant event globally).
- You aren't working in `~/Developer/homesodamachine`. Several hooks carry paths into that tree — the calibration the residue hook reads, the viewer the pick-text note points at, the publish chain the floor guard checks — and outside it they bail silently or need their paths changed.

## The hooks

### Stop and SubagentStop

The message these judge comes from **`_last_assistant_text.py`**, and getting it is not the one-liner it looks like. A turn's closing transcript lines are routinely `thinking` and `tool_use` records — assistant lines holding no text — so the last assistant *line* yields an empty message. And the hook fires while the record it was fired for is still being written, so the newest text on disk belongs to the previous turn. The reader takes the last assistant record that actually carries text, and waits (bounded at 2 s, ending the moment fresh text lands) for one younger than 5 s. A read that never goes fresh is judged anyway and logged `stale_read`, since a turn whose last text predates a long tool run is a legitimate shape.

- **`block-effort-estimate.sh`** — Stop. Catches phrasings like "this'll take a day", "maybe a few hours", "weeks not months", "a couple of weeks". An effort estimate from an LLM is not tied to reality: it is pattern-matched from training data, where humans wrote estimates of work they were doing — work the LLM will do entirely differently. Two-stage: a regex pre-filter, then Haiku on a ±800-char window around the match. The block message asks the assistant to rewrite without one.

- **`block-unwatched-wait.sh`** — Stop and SubagentStop. Refuses a stop whose final message says it is holding, parked, or waiting for a job to report, when none of the background jobs this transcript launched is still alive. Nothing wakes a stopped agent except a job exiting, and from inside the agent a dead job and a slow one are the same silence; one night's fleet produced the false wait five times across two agents, each ending in a manager reading the observable state and sending a wake-up. The regex gates a process check, and there is no API call: a running background shell holds its own `tasks/<id>.output` open on fd 1 and 2, so a live `sleep` shows handles on it and a finished job shows none, read per job id named in the transcript. What passes: a wait on a person; a live subagent, seen by its JSONL's write recency; a tasks directory the hook cannot find; anything the regex does not match.

### PostToolUse

These run after a write has landed, so what they return arrives as context: the edit is on disk and the agent revises it.

- **`block-residue.sh`** — `Write` / `Edit` / `MultiEdit` / `NotebookEdit`. Flags residue (justification, defense, decision narrative — the author going beyond describing what is) in the new content. Three stages, each narrowing at a lower cost than the next: a lenient regex pre-filter on the new content; Haiku on a ±600-char window around the first match, yes/no; then Opus 5 on the whole file, reading the calibration sources themselves (`Principle.md`, `principle/You.md` and `principle/Framing.md` in `~/Developer/homesodamachine/calibration/`), which returns the spans that earned the flag and its own reading of them, and can overturn stage 2 — an overturned flag emits nothing and does not spend the session's one warning. Stage 3 is what the agent receives; a bare stage-2 verdict reaches an agent only when stage 3 fails. **Fires once per session, not twice** — a marker at `~/.claude/hooks/state/residue-warned-<session-id>` records the warning, and markers older than 7 days are garbage-collected on each invocation. Skips binary/structured files (`.dxf`, `.json`, `.yaml`, etc.), the calibration files themselves, and project memory under `~/.claude/projects/*/memory/`, which carries rationale by design. Bails silently when the calibration files aren't at the expected path.

- **`block-underived-measurement.sh`** — `Write` / `Edit` / `MultiEdit` / `NotebookEdit`. Flags a bare dimensional literal (a value in mm, degrees, or a `⌀`/`ø` diameter) where the dimension is one this project fabricates and so should be a docgen marker fed from a source constant. Two-stage: a lenient regex pre-filter for measurement-shaped literals, then Haiku on a ±600-char window that splits a *derivable* project dimension (a wall, bore, boss, fillet, angle of the project's own geometry → note) from an *external* value that is correctly a literal (a fastener size, imperial equivalent, vendor spec, raw caliper measurement → pass). Scopes by extension — Markdown is judged whole, `.py`/`.scad` are reduced to their **comment text** so code constants like `boss_annulus = 3.0` don't fire — and strips existing `[value](TAG)` markers first so already-pinned values don't fire. The note points the assistant at the repo's `tools/docgen` and the `[value](TAG)` marker syntax. **Fires once per session, not twice**, via `~/.claude/hooks/state/measurement-warned-<session-id>` (same 7-day GC). Applies only inside a repo that carries `tools/docgen` (found by walking up from the target file); bails silently anywhere else. After a Haiku call the log line also carries the window it saw and Haiku's raw reply, so a misclassification is diagnosable from the log alone.

### PreToolUse

These run before specific tool calls. A deny is the only PreToolUse outcome whose message reaches the model, so the once-per-session hooks deny the first call and step aside after.

- **`deliver-relay-message.sh`** — matcher `*`. The receive half of `jsonl2md.py send`: another agent acting for the user — a Claude Code session, or a Codex task reaching across runtimes with the same script — drops a message file into `~/.claude/hooks/relay-inbox/<sessionId>/`, and this hook drains that mailbox on the target's next tool call, injects the message, and removes it. Sessions nobody has messaged have no mailbox dir, so the common path is one directory test and an allow. Two modes, set per message by the sender: `interrupt` denies the imminent tool and puts the message in front of the agent; `nudge` rides along as `additionalContext` without blocking. It never denies except to carry a queued message, and always removes what it delivers, so a delivered message can't re-fire.

- **`warn-elevation-write.sh`** — `Write` / `Edit` / `MultiEdit` / `NotebookEdit`. A speed bump on writes to the elevation every future session reads as Derek: any CLAUDE.md or AGENTS.md, and homesodamachine's `calibration/`. The first attempt on a given file is denied with an advisory — a rule wanting to be written there is usually a TODO for a gap in the repo — and repeating the same call goes through. Allowed, not forbidden: the one bounce is the warning. `Bash` is not covered.

- **`block-branch.sh`** — `Bash`. Catches commands that create or publish a git branch: `git checkout -b`/`-B`, `git switch -c`/`-C`, `git branch <newname>`, `git worktree add`, `gh pr create`, and `git push -u`/`--set-upstream` to a non-`main` branch. Work happens directly on `main` in the one shared worktree, where simultaneous agents surface conflicts in real time; a branch gives no isolation there and just hides work from the other agents on the same checkout. Listing/deleting/renaming branches (`git branch`, `-d`/`-D`, `-m`), returning to `main`, and pushing `main` pass. Scope is the ambient cwd's repo only: a command that explicitly operates on another checkout — a leading `cd`/`pushd`, or `git -C`/`--git-dir` — is fork/PR work where branches are the point, and passes untouched. The git/gh token is matched only at a command boundary, so a branch word inside a commit message, echo, or grep never trips. **Fires at most once per session**: the first offending command is denied with the convention, and the guard steps aside for the rest of the session rather than walling a deliberate branch.

- **`block-flash-before-commit.sh`** — `Bash`. Catches commands that *execute* a firmware flash — `tools/flash.sh <env>` (without the build-only `build` arg) or `pio`/`platformio run … -t`/`--target upload` — while the working tree is dirty, and denies them. `pre_build.py` stamps `FW_VERSION` into every build from the git rev, so an uncommitted flash bakes `<sha>-dirty` into the binary: a build that maps to no commit and can't be traced back to the source running on the chip. Dirtiness is the same `git status --porcelain` test `pre_build.py` uses, so it denies exactly the flashes that would stamp `-dirty`; build-only runs, clean-tree flashes, and mere mentions of the script (`cat`/`ls`/`grep tools/flash.sh`) pass. Detection is anchored to command position, so the path appearing as an argument doesn't trip it. **Fires once per session, not twice** — after the first nudge, a deliberate retry in the same session passes through (a dirty test-flash on hardware is sometimes the point), via a `~/.claude/hooks/state/flash-warned-<session-id>` marker with the same 7-day GC. The deny message states the convention and lists what's uncommitted.

- **`block-no-ignore.sh`** — `Bash`. Denies an `rg` invocation that disables `.gitignore`: `--no-ignore` and the other `--no-ignore-*` variants, `--unrestricted`, and `-u`/`-uu` (bundled shorts like `-iu` count; `-U` is multiline and does not). `rg` respects `.gitignore` by default and that is the point: the real signal lives in tracked files, while `web/node_modules` and the Python venvs hold tens of thousands of vendored lines that bury a search and turn it into a false negative read off a truncated screen. The flag is scoped to the `rg` segment of a pipeline, so a downstream `| sort -u` or `python -u` does not trip it; `grep -r` and `find` flood the same way with no flag to catch, and stay out of reach. **Nudges once per session, then passes through** — a deliberate retry scoped to a path is allowed. Per-session marker + 7-day GC.

- **`block-publish-below-floor.sh`** — `Bash`. Catches `marketing/thumbnail/make.sh <source> <output> "HEADLINE"`, the first ship action of the video publish chain (`marketing/video/workflow.md`), when the cut it is building for has no overlays sidecar — a feature-stripped cut with no title card, freeze, or SFX, against "the pipeline is the floor" (`marketing/video/principles.md`). It derives the working dir from the source-frame arg by walking up to the dir holding `cutlist.json`; sidecar present passes silently, sidecar absent redirects, working dir not locatable passes (fail-open). Anchored to command position, so `cat`/`ls`/`grep` of the script don't match. **Nudges once per session, then passes through** — a music-bed Tier-2 clip legitimately ships without overlays. Per-session marker + 7-day GC.

- **`block-task-sleep-poll.sh`** — `Bash`. Denies a command that both sleeps and names a harness task file (`.../tasks/<id>.output`) — the shape of `until [ -s … ]; do sleep 10; done` and `sleep 180; cat …/tasks/….output`. The harness re-invokes the session when a background task exits; a wait spent on a clock is time bought for nothing, and it is bounded by the Bash timeout rather than by the job. Sleeping on something the harness does not track — a CI run, a deploy, a dev server's port, another agent's lock — passes untouched, and so does the pattern as data (a heredoc, an inline script, an echo, a grep over transcripts). **Fires at most once per session**, like the branch guard.

- **`block-web.sh`** — `WebFetch` and `WebSearch`. Denies the first call of each per session with a message redirecting to Chrome MCP, which is far more reliable: WebFetch hits cert failures and stale page caches Chrome doesn't, and WebSearch is not Google (its results are weak). **Fires once per session per tool, not twice** — after the nudge, subsequent calls of that tool in the same session pass through, so a session where Chrome MCP genuinely isn't connected can still fall back. Marker files at `~/.claude/hooks/state/webfetch-warned-<session-id>` / `websearch-warned-<session-id>` record the warning; markers older than 7 days are garbage-collected on each invocation. No Haiku stage and no logging — the tool name is unambiguous, nothing to adjudicate.

### UserPromptSubmit

- **`note-pick-text.sh`** — catches user prompts carrying step-viewer pick text (the STEP viewer's copy blobs: `file:`/`solid:`/`edge:`/`faceA:`/`faceB:`/`click:` lines, recognized by their three-decimal coordinate triples) and injects `additionalContext` instead of blocking anything. The note points the agent at the format's home (`web/public/js/viewer/pick-format.js`, with verbatim samples in `web/tests/pick-format.test.js`), asks it to echo its decoded identification of each pick before changing geometry, and tells it the part nothing in a pasted blob reveals: the channel is two-way — the viewer's Find box accepts the same format pasted back, opens the `file:` line's file, and highlights every pick, so the agent should emit pick lines when pointing the user at geometry, composed from CadQuery geometry with the viewer repo's `hardware/scripts/pick_text.py` (round-trip tested against the parser). **Fires once per session, not twice**, via `~/.claude/hooks/state/pick-noted-<session-id>` (same 7-day GC). Applies only inside a repo that carries the viewer (found by walking up from cwd); bails silently anywhere else. No Haiku stage and no logging — the coordinate-triple signature is unambiguous, nothing to adjudicate.

### SessionStart

- **`reap-abandoned-forks.sh`** — signals Claude CLI helper forks still running after the turn that spawned them. A fork carries `--fork-session` and `--no-session-persistence`, resumes a session id, and leaves `--tools` and `--setting-sources` empty; a windowed session carries `--replay-user-messages`, `--include-partial-messages` and `--permission-prompt-tool`, and neither fork flag. Both members of a session's process pair — the `disclaimer` wrapper and the `claude` it execs — carry the same argv, so both are taken together. `is_candidate` holds the tests: the fork argv, none of the three window flags, age past `HSM_REAP_MIN_AGE_S` (600 s), cpu under `HSM_REAP_MAX_CPU` (1.0), no children other than its own pair member, and no pid on the hook's own ancestor chain. An ancestor chain shorter than two entries spares every pid. SIGTERM, then SIGKILL to whatever is left. `HSM_REAP_DRY_RUN=1` or `--dry-run` reports and signals nothing. stdout stays empty — a SessionStart hook's stdout is injected as context — and a sweep reports on stderr. A fork runs with `--setting-sources=` empty and loads no user settings, so it never runs this. No Haiku stage: the tests are flags, an age and a pid.

### In the tree, not wired

- **`block-question-as-disagreement.sh`** — Stop. Catches "I notice X — was that intended?" / "Did you mean to Y?" / "Is that on purpose?" when the assistant frames a structural disagreement as a question. Two-stage like the effort hook; the block message asks the assistant to state the disagreement directly. Genuine information-gathering questions pass through.

- **`note-inherited-fence.sh`** — PostToolUse on `Task|Agent` (a synchronous subagent's result) and UserPromptSubmit on turns carrying a `<task-notification>` block (a background subagent's result). Catches a limit claim arriving from *another* agent and injects `additionalContext` naming it as an inherited fence: a conclusion produced by an agent with the reader's own failure mode, to probe (does it carry its price? what do the run's two ends actually need?) before accumulating it as a tie or relaying it up. Limit-claim regex shapes, no Haiku stage; once per session. It points at `~/Developer/homesodamachine/calibration/Fences.md` and fires only when that file exists, which the tree no longer carries.

- **`block-commit-curation.sh`** — PreToolUse on `Bash`. Denies the git moves an agent makes to keep another agent's changes out of its commit: the curate family (`git add -p/-i/-e`, `restore --staged`, `reset` other than `--soft`, `apply --cached/--index`, `rm --cached`) and the discard family (`reset --hard`, `clean` other than a dry run, `checkout`/`restore` of a worktree path, `checkout -p`, `stash` push), the second with a data-loss line in the message. In the one shared worktree every simultaneous agent's in-progress work shows in `git status`, so a diff bigger than what you touched is the normal state, and `git add -A && git commit` is the fix. Hard deny, every time. `git add -A`/`<files>`/`.`, every form of `git commit`, `reset --soft`, `stash pop/list/show/apply/drop`, `clean -n`, `checkout <branch>`, `git rm <file>` and `git apply <patch>` pass.

## How the two-stage hooks work

The effort hook on Stop and the residue and measurement hooks on PostToolUse follow the same shape:

1. Read the text to judge: the assistant's final message from the session transcript, or the new content of the write.
2. Reduce it to what is judged — the Stop hook and the residue hook strip backtick-delimited spans (so docs that quote a hook's own trigger patterns don't fire the hook on itself); the measurement hook keeps Markdown whole, reduces `.py`/`.scad` to comment text, and strips existing markers.
3. Run a **cheap regex pre-filter**. If nothing matches, exit silently.
4. If the regex matches, extract a window of context around the match — ±800 chars for the Stop hook, ±600 for the write hooks.
5. Send the window to **Claude Haiku 4.5** with a classification prompt that distinguishes the targeted pattern from the look-alike (effort vs projection; residue vs description; derivable dimension vs external literal).
6. If Haiku classifies as the targeted pattern, emit the block or the note. The residue hook adds a third stage — Opus 5 on the whole file against the calibration — which can overturn Haiku.

The staging keeps API cost down (most events never reach a model) while keeping the catch precise (the model sees real context, not just the matched fragment).

## Logging

`block-effort-estimate.sh`, `block-unwatched-wait.sh`, `block-residue.sh`, `block-underived-measurement.sh`, `reap-abandoned-forks.sh`, and the unwired `block-question-as-disagreement.sh` and `note-inherited-fence.sh` each append one JSONL line per event to `~/.claude/hooks/logs/<hook-name>.jsonl` with a `status` field identifying which code path was taken:

- `loop_guard` — re-entry from a revision attempt, skipped (Stop hooks)
- `no_transcript` / `no_assistant_message` / `empty_or_short_text` / `empty_text` / `empty_after_strip` / `window_empty` — nothing to check (Stop hooks)
- `wrong_tool` / `skipped_calibration` / `skipped_memory` / `skipped_non_prose` / `empty_or_short` / `no_calibration_files` — file or tool filtered out (`block-residue.sh`)
- `skipped_filetype` / `no_docgen_repo` / `empty_after_strip` — file filtered out: not `.md`/`.py`/`.scad`, not inside a `tools/docgen` repo, or no prose left after stripping comments and markers (`block-underived-measurement.sh`)
- `already_warned_this_session` — session marker exists from a prior nudge in the same session; hook passes through (`block-residue.sh` and `block-underived-measurement.sh`); `lost_claim_race` — a parallel invocation claimed the session's one warning first (`block-underived-measurement.sh`)
- `regex_no_match` — pre-filter didn't match; **Stop-hook log lines include `last_400_chars` of the response so you can see what slipped through**
- `no_api_key` — `~/.claude/anthropic_api_key` is missing
- `haiku_no_response` — Haiku call made but empty response (timeout, network failure, etc.)
- `stale_read` — the reader's wait expired and the message judged is the newest text on disk, which may predate this turn; the run continues and logs its verdict as usual
- `regex_match` — the pre-filter matched, logged **before** the window, the API call and the verdict (`block-effort-estimate.sh`). A `regex_match` with no verdict line after it is an invocation that died — timeout, or a stage exiting non-zero — and without it a death and a clean miss are the same silence
- `allowed` — the model classified as the look-alike; nothing emitted
- `blocked` — a Stop hook emitted a block
- `flagged` — a write hook emitted its note; `overturned` — the residue hook's third stage disagreed with Haiku and nothing was emitted
- `no_posture_match` / `no_object_match` / `no_tasks_dir` / `waiting_on_person` / `allowed_live` — the wait hook's pass paths: no wait-shaped text, no job named in it, no tasks directory to check, a wait on a person, a live process behind the wait

The verdict is read as the **first word** of Haiku's reply. With `max_tokens: 5` it answers bare (`effort`) about as often as it opens a sentence (`effort. The flagged phrase`), and a whole-string compare reads the second shape as a word matching no case — which falls through to allowed.

The `regex_no_match` lines are the diagnostic surface for tuning. If a pattern slips through in normal use, grep the log:

```sh
grep regex_no_match ~/.claude/hooks/logs/effort-estimate.jsonl | tail
```

Identify the shape that got past, add it to the regex pattern in the script.

`block-web.sh`, `note-pick-text.sh`, the `Bash` guards, `warn-elevation-write.sh` and `deliver-relay-message.sh` do not log. They are a tool-name match, a prompt-text match, command-pattern matches, a path test and a directory test, with no staged decision to diagnose.

## Installing

1. Clone this repo somewhere on your machine.
2. Run `./install.sh` from the repo root — it makes the hooks executable and prints the base path to reference them by.
3. Drop your Anthropic API key into `~/.claude/anthropic_api_key` (for the two-stage hooks; plain text, one line, no quotes).
4. Wire the hooks up in `~/.claude/settings.json` by absolute path into the clone — `examples/settings.json` is the live wiring, verbatim. One source of truth on disk: edit in the clone, run from the clone, commit and push from the clone.

## Tuning

The regex pattern is one line near the top of each two-stage script. Extend it as you find slips in the log. The Haiku stage filters out matches that don't fit the pattern definition: a regex that matches widely costs an API call per match but does not block on the look-alike.

The classification prompts are also in each script. If Haiku classifies in a direction other than what you want, the prompt is where you'd adjust the examples or definitions.

The `reason` message — what the assistant sees when blocked — is a `jq -n` literal near the bottom of each script. Rewrite it however you want it to read.

## Files

- `hooks/_last_assistant_text.py` — the turn's final text, waited for (shared by the Stop hooks)
- `hooks/block-effort-estimate.sh` — effort-estimate hook (Stop, regex + Haiku two-stage)
- `hooks/block-unwatched-wait.sh` — unwatched-wait hook (Stop + SubagentStop, regex + process check)
- `hooks/block-residue.sh` — residue note (PostToolUse on writes, regex + Haiku + Opus three-stage)
- `hooks/block-underived-measurement.sh` — underived-measurement note (PostToolUse on writes, regex + Haiku two-stage)
- `hooks/deliver-relay-message.sh` — relay inbox delivery (PreToolUse on every tool, mailbox drain)
- `hooks/warn-elevation-write.sh` — elevation speed bump (PreToolUse on writes, one bounce per file per session)
- `hooks/block-branch.sh` — branch-creation guard (PreToolUse on Bash, command-pattern match, once per session)
- `hooks/block-flash-before-commit.sh` — flash guard (PreToolUse on Bash, command-pattern match + `git status --porcelain` dirty check, once per session)
- `hooks/block-no-ignore.sh` — rg ignore guard (PreToolUse on Bash, command-pattern match, once per session)
- `hooks/block-publish-below-floor.sh` — publish floor guard (PreToolUse on Bash, command-pattern match + sidecar check, once per session)
- `hooks/block-task-sleep-poll.sh` — task-file sleep-poll guard (PreToolUse on Bash, command-pattern match, once per session)
- `hooks/block-web.sh` — web-tool redirect (PreToolUse on WebFetch|WebSearch, once per session per tool)
- `hooks/note-pick-text.sh` — step-viewer pick-text note (UserPromptSubmit, once-per-session context injection)
- `hooks/reap-abandoned-forks.sh` — abandoned-fork reaper (SessionStart, argv shape + age + cpu + ancestor chain)
- `hooks/block-question-as-disagreement.sh` — question-as-disagreement hook (Stop, regex + Haiku two-stage; not wired)
- `hooks/block-commit-curation.sh` — commit-curation guard (PreToolUse on Bash, command-pattern match; not wired)
- `hooks/note-inherited-fence.sh` — inherited-fence note (PostToolUse on Task|Agent + UserPromptSubmit on task-notification turns, once per session; not wired, and inert without `calibration/Fences.md`)
- `examples/settings.json` — the `hooks` block of `~/.claude/settings.json`, verbatim
