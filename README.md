# claude-stop-hooks

Three Stop hooks for Claude Code that block specific bad-output patterns: effort estimates, unexplained hedges, and disagreement-framed-as-question.

This is a personal tool, put on GitHub in case it helps someone running similar configurations. It is not a polished, configurable, cross-platform library — read the next section before assuming it'll work for you.

## Who this is for

You'll get value from this if **all** of the following are true:

- You're using **Claude Code** and want to customize what its assistant turns are allowed to contain.
- You're OK with **Anthropic API charges** for the Haiku second-stage classifications (one small Haiku call per Stop event when the regex pre-filter matches — usually a tiny fraction of turns).
- You're comfortable with **bash + jq + curl + perl** in your hook scripts and editing `~/.claude/settings.json` by hand.

You will *not* get value from this if:

- You want a **UI** for configuring patterns.
- You want **portable, OS-agnostic** hooks (these use `tail -r`/`tac` and other shell quirks).
- You want **fine-grained control over which sessions** a hook applies to (these run on every Stop event globally).

## The three hooks

- **`block-effort-estimate.sh`** — catches phrasings like "this'll take a day", "maybe a few hours", "weeks not months", "a couple of weeks". Effort estimates from an LLM are pattern-matched from training data, not measurements of anything the assistant will actually do. The block message asks the assistant to rephrase without putting a number on duration.

- **`block-unexplained-hedge.sh`** — catches "I'm not sure", "I might be wrong", "this could be off" when the assistant doesn't say what the underlying concern is. The block message asks the assistant to either drop the hedge or explain what it's hedging about. Substantive hedges (where the concern is named) pass through; social/habitual hedges get blocked.

- **`block-question-as-disagreement.sh`** — catches "I notice X — was that intended?" / "Did you mean to Y?" / "Is that on purpose?" when the assistant is using a question to soften a structural disagreement. The block message asks the assistant to state the disagreement directly. Genuine information-gathering questions pass through; disagreements wearing question's clothes get blocked.

## How they work

Each hook runs on Claude Code's `Stop` event and follows the same structure:

1. Read the assistant's last turn from the session transcript JSONL.
2. Strip backtick-delimited spans (so docs that quote the hook's own trigger patterns don't fire the hook on itself).
3. Run a **cheap regex pre-filter** against the last turn. If nothing matches, exit silently.
4. If the regex matches, extract a **±800-char window** of context around the match.
5. Send the window to **Claude Haiku 4.5** with a classification prompt that distinguishes the bad pattern from a benign look-alike (effort vs projection; substantive vs social hedge; genuine question vs disagreement).
6. If Haiku classifies as the bad pattern, emit a `block` decision with a corrective `reason`.

The two-stage design keeps API cost down (most turns never reach Haiku) while still being precise (Haiku sees real context, not just the matched fragment).

## Logging

Each hook appends one JSONL line per Stop event to `~/.claude/hooks/logs/<hook-name>.jsonl` with a `status` field identifying which code path was taken:

- `loop_guard` — re-entry from a revision attempt, skipped
- `no_transcript` / `no_assistant_message` / `empty_or_short_text` / `empty_after_strip` — nothing to check
- `regex_no_match` — pre-filter didn't match; **includes `last_400_chars` of the response so you can see what slipped through**
- `no_api_key` — `~/.claude/anthropic_api_key` is missing
- `haiku_no_response` — Haiku call made but empty response (timeout, network failure, etc.)
- `allowed` — Haiku classified as the benign look-alike
- `blocked` — Haiku classified as the bad pattern; block was emitted

The `regex_no_match` lines are the diagnostic surface for tuning. If you spot a slip in normal use, grep the log for the closing fragment of the response and look at the excerpt:

```sh
grep regex_no_match ~/.claude/hooks/logs/effort-estimate.jsonl | tail
```

Identify the shape that got past, add it to the regex pattern in the script, done.

## Installing

1. Clone or download this repo.
2. `chmod +x` the hooks you want to use.
3. Copy them into `~/.claude/hooks/` (or wherever you keep your hooks).
4. Drop your Anthropic API key into `~/.claude/anthropic_api_key` (plain text, one line, no quotes).
5. Wire the hooks up in `~/.claude/settings.json` under `hooks.Stop` — see `examples/settings.json` for the shape.

## Tuning

The regex pattern is one line near the top of each script. Extend it as you find slips in the log. The Haiku stage protects you from over-broadening: false positives at the regex stage cost an API call but don't produce false blocks.

The classification prompts are also in each script. If Haiku is mis-classifying in a specific direction, the prompt is where you'd adjust the examples or instructions.

The `reason` message — what the assistant sees when blocked — is a `jq -n` literal near the bottom of each script. Rephrase it however you'd want a corrective note from yourself to read.

## Files

- `hooks/block-effort-estimate.sh` — effort-estimate hook
- `hooks/block-unexplained-hedge.sh` — hedge hook
- `hooks/block-question-as-disagreement.sh` — question-as-disagreement hook
- `examples/settings.json` — example `~/.claude/settings.json` snippet wiring all three hooks
