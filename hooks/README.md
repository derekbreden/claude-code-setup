# claude-code-hooks

Claude Code hooks. Five Stop hooks block specific outputs from the assistant: effort estimates, hedges that don't name a concern, disagreement framed as a question, a turn that ends by offering work the agent could have done, and parameter sweeps reported as a finding — the fourth also wired on SubagentStop, so a subagent's final report meets it before a manager reads it. Three PreToolUse hooks block specific writes: project memory files, content containing residue (justification, defense, decision narrative — the author going beyond describing what is), and underived measurements (bare dimensional literals that should be docgen markers fed from a source constant). A fourth PreToolUse hook runs on `Bash` and blocks branch creation, so work stays on `main` in the one shared worktree; a fifth, also on `Bash`, nudges once per session against flashing firmware with a dirty tree, so flashed binaries map to commits by default. A sixth runs on `WebFetch` and `WebSearch` and denies the first call of each (per tool, per session) with a redirect to Chrome MCP, which is far more reliable. Two hooks inject context instead of blocking: when a prompt carries step-viewer pick text, one points the agent (once per session) at the format's home and at the fact the channel is two-way; when a subagent report or task notification arrives carrying a limit claim, the other names it (once per session) as an inherited fence to probe before relaying.

This is a personal tool, put on GitHub in case it helps someone running similar configurations. It is not a polished, configurable, cross-platform library — read the next section before assuming it'll work for you.

## Who this is for

You'll get value from this if **all** of the following are true:

- You're using **Claude Code** and want it to block specific patterns in the assistant's turns and tool calls.
- For the Stop hooks: you're OK with **Anthropic API charges** for the Haiku second-stage classifications (one small Haiku call per Stop event when the regex pre-filter matches — usually a tiny fraction of turns).
- You're comfortable with **bash + jq + curl + perl** in your hook scripts and editing `~/.claude/settings.json` by hand.

You will *not* get value from this if:

- You want a **UI** for configuring patterns.
- You want **portable, OS-agnostic** hooks (these use `tail -r`/`tac` and other shell quirks).
- You want **fine-grained control over which sessions** a hook applies to (these run on every relevant event globally).

## The hooks

### Stop hooks

These run after each assistant turn. Each one runs a cheap regex pre-filter against the last assistant message; if it matches, a windowed snippet goes to Claude Haiku for disambiguation; if Haiku confirms the targeted pattern, the turn is blocked with a `reason` returned to the assistant.

The message they judge comes from **`_last_assistant_text.py`**, and getting it is not the one-liner it looks like. A turn's closing transcript lines are routinely `thinking` and `tool_use` records — assistant lines holding no text — so the last assistant *line* yields an empty message. And the hook fires while the record it was fired for is still being written, so the newest text on disk belongs to the previous turn. The reader takes the last assistant record that actually carries text, and waits (bounded at 2 s, ending the moment fresh text lands) for one younger than 5 s. A read that never goes fresh is judged anyway and logged `stale_read`, since a turn whose last text predates a long tool run is a legitimate shape.

- **`block-effort-estimate.sh`** — catches phrasings like "this'll take a day", "maybe a few hours", "weeks not months", "a couple of weeks". An effort estimate from an LLM is not tied to reality: it is pattern-matched from training data, where humans wrote estimates of work they were doing — work the LLM will do entirely differently. The block message asks the assistant to rewrite without one.

- **`block-unexplained-hedge.sh`** — catches "I'm not sure", "I might be wrong", "this could be off" when the assistant doesn't name the underlying concern. The block message asks the assistant to explain the concern rather than remove the hedge. Substantive hedges (where the concern is named) pass through; social/habitual hedges get blocked.

- **`block-question-as-disagreement.sh`** — catches "I notice X — was that intended?" / "Did you mean to Y?" / "Is that on purpose?" when the assistant frames a structural disagreement as a question. The block message asks the assistant to state the disagreement directly. Genuine information-gathering questions pass through; disagreement framed as a question gets blocked.

- **`block-closing-offer.sh`** — catches a turn that *ends* on an offer to do work the agent had already scoped: "say the word", "want me to run it?", "let me know if you'd like X". The pre-filter runs over the last 700 characters only, because the failure is stopping on the offer rather than mentioning one mid-turn; Haiku then separates a genuine fork the user must settle from an offer to do the job. The block message says to go do it and end on what landed, and — if it really is a fork — to put the question in the turn's *first* line with a stated default. The pattern and its cost are documented at length in `homesodamachine/calibration/Discretion.md`, whose editor's note records that a repo instruction alone was tested and did not hold.


### PreToolUse hooks

These run before specific tool calls.

- **`block-memory-write.sh`** — catches `Write` / `Edit` / `MultiEdit` / `NotebookEdit` calls whose target path is under any `~/.claude/projects/*/memory/` directory. The deny message asks the assistant to encode the lesson by example in the work it's doing rather than as a memory note. (`Bash` writes to memory paths via `echo >` are intentionally not blocked — the hook would otherwise gate every shell command for a threat that hasn't materialized.)

- **`block-residue.sh`** — catches `Write` / `Edit` / `MultiEdit` / `NotebookEdit` calls whose new content contains residue (justification, defense, decision narrative — the author going beyond describing what is). Two-stage like the Stop hooks: regex pre-filter on the new content, Haiku adjudication on a ±600-char window around the first match. The deny message points the assistant at three calibration files in `~/Developer/homesodamachine/calibration/` — `Principle.md` and the two conversations it distills, `principle/You.md` and `principle/Framing.md` — and asks them to read those before looking at what they wrote. **Fires once per session, not twice** — once an agent has been pointed at the calibration, subsequent residue writes in the same session pass through. A marker file at `~/.claude/hooks/state/residue-warned-<session-id>` records the warning; markers older than 7 days are garbage-collected on each invocation. Skips binary/structured files (`.dxf`, `.json`, `.yaml`, etc.) and the calibration files themselves. Fires only when the calibration files exist at the expected path; bails silently otherwise.

- **`block-underived-measurement.sh`** — catches `Write` / `Edit` / `MultiEdit` / `NotebookEdit` calls that introduce a bare dimensional literal (a value in mm, degrees, or a `⌀`/`ø` diameter) where the dimension is one this project fabricates and so should be a docgen marker fed from a source constant. Two-stage like `block-residue.sh`: a lenient regex pre-filter for measurement-shaped literals, then Haiku adjudication on a ±600-char window that splits a *derivable* project dimension (a wall, bore, boss, fillet, angle of the project's own geometry → nudge) from an *external* value that is correctly a literal (a fastener size, imperial equivalent, vendor spec, raw caliper measurement → pass). Scopes by extension — Markdown is judged whole, `.py`/`.scad` are reduced to their **comment text** so code constants like `boss_annulus = 3.0` don't fire — and strips existing `[value](TAG)` markers first so already-pinned values don't fire. The deny message points the assistant at the repo's `tools/docgen` and the `[value](TAG)` marker syntax. **Fires once per session, not twice**, via `~/.claude/hooks/state/measurement-warned-<session-id>` (same 7-day GC). Applies only inside a repo that carries `tools/docgen` (found by walking up from the target file); bails silently anywhere else.

- **`block-branch.sh`** — catches `Bash` calls whose command creates or publishes a git branch: `git checkout -b`/`-B`, `git switch -c`/`-C`, `git branch <newname>`, `git worktree add`, `gh pr create`, and `git push -u`/`--set-upstream` to a non-`main` branch. Work happens directly on `main` in the one shared worktree, where simultaneous agents surface conflicts in real time; a branch gives no isolation there and just hides work from the other agents on the same checkout. Listing/deleting/renaming branches (`git branch`, `-d`/`-D`, `-m`) and pushing `main` pass through. Hard deny on every match — no Haiku stage, no per-session passthrough; the deny message states the convention.

- **`block-flash-before-commit.sh`** — catches `Bash` calls that *execute* a firmware flash — `tools/flash.sh <env>` (without the build-only `build` arg) or `pio`/`platformio run … -t`/`--target upload` — while the working tree is dirty, and denies them. `pre_build.py` stamps `FW_VERSION` into every build from the git rev, so an uncommitted flash bakes `<sha>-dirty` into the binary: a build that maps to no commit and can't be traced back to the source running on the chip. Dirtiness is the same `git status --porcelain` test `pre_build.py` uses, so it denies exactly the flashes that would stamp `-dirty`; build-only runs, clean-tree flashes, and mere mentions of the script (`cat`/`ls`/`grep tools/flash.sh`) pass. Detection is anchored to command position, so the path appearing as an argument doesn't trip it. **Fires once per session, not twice** — no Haiku stage; after the first nudge, a deliberate retry in the same session passes through (a dirty test-flash on hardware is sometimes the point, unlike branch creation), via a `~/.claude/hooks/state/flash-warned-<session-id>` marker with the same 7-day GC as the other once-per-session hooks. The deny message states the convention and lists what's uncommitted.

- **`block-web.sh`** — catches `WebFetch` and `WebSearch` calls and denies the first of each per session with a message redirecting to Chrome MCP, which is far more reliable: WebFetch hits cert failures and stale page caches Chrome doesn't, and WebSearch is not Google (its results are weak). **Fires once per session per tool, not twice** — after the nudge, subsequent calls of that tool in the same session pass through, so a session where Chrome MCP genuinely isn't connected can still fall back. Marker files at `~/.claude/hooks/state/webfetch-warned-<session-id>` / `websearch-warned-<session-id>` record the warning; markers older than 7 days are garbage-collected on each invocation. No Haiku stage and no logging — the tool name is unambiguous, nothing to adjudicate.

### UserPromptSubmit hooks

- **`note-inherited-fence.sh`** — catches a limit claim arriving from *another* agent — wired on **PostToolUse for `Task|Agent`** (a synchronous subagent's result) and on **UserPromptSubmit for turns carrying a `<task-notification>` block** (a background subagent's result) — and injects `additionalContext` naming it as an inherited fence: a conclusion produced by an agent with the reader's own failure mode, to probe (does it carry its price? what do the run's two ends actually need?) before accumulating it as a tie or relaying it up. Limit-claim regex shapes, no Haiku stage — the note defuses itself on a report that already carries its price. **Fires once per session, not twice**, via `~/.claude/hooks/state/inherited-fence-noted-<session-id>` (same 7-day GC). Fires only when the Fences calibration exists at its expected path; bails silently anywhere else.

- **`note-pick-text.sh`** — catches user prompts carrying step-viewer pick text (the STEP viewer's copy blobs: `file:`/`solid:`/`edge:`/`faceA:`/`faceB:`/`click:` lines, recognized by their three-decimal coordinate triples) and injects `additionalContext` instead of blocking anything. The note points the agent at the format's home (`web/public/js/viewer/pick-format.js`, with verbatim samples in `web/tests/pick-format.test.js`), asks it to echo its decoded identification of each pick before changing geometry, and tells it the part nothing in a pasted blob reveals: the channel is two-way — the viewer's Find box accepts the same format pasted back, opens the `file:` line's file, and highlights every pick, so the agent should emit pick lines when pointing the user at geometry, composed from CadQuery geometry with the viewer repo's `hardware/scripts/pick_text.py` (round-trip tested against the parser). **Fires once per session, not twice**, via `~/.claude/hooks/state/pick-noted-<session-id>` (same 7-day GC). Applies only inside a repo that carries the viewer (found by walking up from cwd); bails silently anywhere else. No Haiku stage and no logging — the coordinate-triple signature is unambiguous, nothing to adjudicate.

### SessionStart hooks

- **`reap-abandoned-forks.sh`** — signals Claude CLI helper forks still running after the turn that spawned them. A fork carries `--fork-session` and `--no-session-persistence`, resumes a session id, and leaves `--tools` and `--setting-sources` empty; a windowed session carries `--replay-user-messages`, `--include-partial-messages` and `--permission-prompt-tool`, and neither fork flag. Both members of a session's process pair — the `disclaimer` wrapper and the `claude` it execs — carry the same argv, so both are taken together. `is_candidate` holds the tests: the fork argv, none of the three window flags, age past `HSM_REAP_MIN_AGE_S` (600 s), cpu under `HSM_REAP_MAX_CPU` (1.0), no children other than its own pair member, and no pid on the hook's own ancestor chain. An ancestor chain shorter than two entries spares every pid. SIGTERM, then SIGKILL to whatever is left. `HSM_REAP_DRY_RUN=1` or `--dry-run` reports and signals nothing. stdout stays empty — a SessionStart hook's stdout is injected as context — and a sweep reports on stderr. A fork runs with `--setting-sources=` empty and loads no user settings, so it never runs this. No Haiku stage: the tests are flags, an age and a pid.

## How the Stop hooks work

Each Stop hook follows the same shape:

1. Read the assistant's last turn from the session transcript JSONL.
2. Strip backtick-delimited spans (so docs that quote the hook's own trigger patterns don't fire the hook on itself).
3. Run a **cheap regex pre-filter** against the last turn. If nothing matches, exit silently.
4. If the regex matches, extract a window of context around the match — **±800 chars**.
5. Send the window to **Claude Haiku 4.5** with a classification prompt that distinguishes the targeted pattern from the look-alike (effort vs projection; substantive vs social hedge; genuine question vs disagreement-framed-as-question; sweep vs solve, probe or comparison).
6. If Haiku classifies as the targeted pattern, emit a `block` decision with a `reason`.

The two-stage design keeps API cost down (most turns never reach Haiku) while keeping the catch precise (Haiku sees real context, not just the matched fragment).

## Logging

The regex + Haiku Stop hooks, `block-residue.sh`, `block-underived-measurement.sh`, and `note-inherited-fence.sh` each append one JSONL line per event to `~/.claude/hooks/logs/<hook-name>.jsonl` with a `status` field identifying which code path was taken:

- `loop_guard` — re-entry from a revision attempt, skipped (Stop hooks only)
- `no_transcript` / `no_assistant_message` / `empty_or_short_text` / `empty_after_strip` — nothing to check (Stop hooks)
- `wrong_tool` / `skipped_calibration` / `skipped_non_prose` / `empty_or_short` / `no_calibration_files` — file or tool filtered out (`block-residue.sh` only)
- `skipped_filetype` / `no_docgen_repo` / `empty_after_strip` — file filtered out: not `.md`/`.py`/`.scad`, not inside a `tools/docgen` repo, or no prose left after stripping comments and markers (`block-underived-measurement.sh` only)
- `already_warned_this_session` — session marker exists from a prior nudge in the same session; hook passes through (`block-residue.sh` and `block-underived-measurement.sh`)
- `regex_no_match` — pre-filter didn't match; **Stop-hook log lines include `last_400_chars` of the response so you can see what slipped through**
- `no_api_key` — `~/.claude/anthropic_api_key` is missing
- `haiku_no_response` — Haiku call made but empty response (timeout, network failure, etc.)
- `stale_read` — the reader's wait expired and the message judged is the newest text on disk, which may predate this turn; the run continues and logs its verdict as usual
- `regex_match` — the pre-filter matched, logged **before** the window, the API call and the verdict. A `regex_match` with no verdict line after it is an invocation that died — timeout, or a stage exiting non-zero — and without it a death and a clean miss are the same silence
- `allowed` — Haiku classified as the look-alike; no block emitted
- `blocked` — Haiku classified as the targeted pattern; block was emitted

The verdict is read as the **first word** of Haiku's reply. With `max_tokens: 5` it answers bare (`effort`) about as often as it opens a sentence (`effort. The flagged phrase`), and a whole-string compare reads the second shape as a word matching no case — which falls through to allowed.

The `regex_no_match` lines are the diagnostic surface for tuning. If a pattern slips through in normal use, grep the log:

```sh
grep regex_no_match ~/.claude/hooks/logs/effort-estimate.jsonl | tail
```

Identify the shape that got past, add it to the regex pattern in the script.

`block-memory-write.sh`, `block-web.sh`, and `note-pick-text.sh` do not log. They are structurally much simpler (a path comparison and a tool-name match, respectively) and have no two-stage decision to diagnose.

## Installing

1. Clone this repo somewhere on your machine.
2. `chmod +x hooks/*.sh`.
3. Drop your Anthropic API key into `~/.claude/anthropic_api_key` (for the Stop hooks; plain text, one line, no quotes).
4. Wire the hooks up in `~/.claude/settings.json` — see `examples/settings.json` for the shape.

For paths in `settings.json`: the example uses `$HOME/.claude/hooks/...` which assumes you've copied the scripts into that directory. An alternative is to point `settings.json` directly at your clone (e.g. `$HOME/path/to/claude-code-hooks/hooks/...`). That keeps a single source of truth on disk: edit in the clone, run from the clone, commit and push from the clone.

## Tuning

The regex pattern is one line near the top of each Stop-hook script. Extend it as you find slips in the log. The Haiku stage filters out matches that don't fit the pattern definition: a regex that matches widely costs an API call per match but does not block on the look-alike.

The classification prompts are also in each script. If Haiku classifies in a direction other than what you want, the prompt is where you'd adjust the examples or definitions.

The `reason` message — what the assistant sees when blocked — is a `jq -n` literal near the bottom of each script. Rewrite it however you want it to read.

## Files

- `hooks/_last_assistant_text.py` — the turn's final text, waited for (shared by the four two-stage Stop hooks)
- `hooks/block-effort-estimate.sh` — effort-estimate hook (Stop, regex + Haiku two-stage)
- `hooks/block-unexplained-hedge.sh` — hedge hook (Stop, regex + Haiku two-stage)
- `hooks/block-question-as-disagreement.sh` — question-as-disagreement hook (Stop, regex + Haiku two-stage)
- `hooks/block-memory-write.sh` — memory-write hook (PreToolUse, path comparison only)
- `hooks/block-residue.sh` — residue hook (PreToolUse, regex + Haiku two-stage)
- `hooks/block-underived-measurement.sh` — underived-measurement hook (PreToolUse, regex + Haiku two-stage)
- `hooks/block-branch.sh` — branch-creation hook (PreToolUse on Bash, command-pattern match)
- `hooks/block-flash-before-commit.sh` — flash-guard hook (PreToolUse on Bash, command-pattern match + `git status --porcelain` dirty check)
- `hooks/block-web.sh` — web-tool-redirect hook (PreToolUse on WebFetch|WebSearch, once-per-session-per-tool nudge to Chrome MCP)
- `hooks/note-pick-text.sh` — step-viewer pick-text note (UserPromptSubmit, once-per-session context injection)
- `hooks/note-inherited-fence.sh` — inherited-fence note (PostToolUse on Task|Agent + UserPromptSubmit on task-notification turns, once-per-session context injection)
- `hooks/reap-abandoned-forks.sh` — abandoned-fork reaper (SessionStart, argv shape + age + cpu + ancestor chain, no Haiku stage)
- `examples/settings.json` — example `~/.claude/settings.json` snippet wiring all fifteen hooks
