Three Stop hooks for Claude Code that block bad-output patterns: effort estimates, unexplained hedges, and questions-as-disagreement. Each hook is a regex pre-filter followed by a Claude Haiku second-stage classification; the regex is intentionally lenient and the Haiku stage handles disambiguation. Per-hook logs land in `~/.claude/hooks/logs/<hook-name>.jsonl` with a `status` field identifying each code path; `regex_no_match` entries include the last 400 characters of the response so slips through the pre-filter can be found and the pattern extended.

When extending the regex: look at `grep regex_no_match ~/.claude/hooks/logs/<name>.jsonl | tail`, find the shape that slipped, add it to the one-line pattern near the top of the script. Don't worry about false positives at the regex stage — the Haiku stage rejects benign look-alikes.

When extending the Haiku prompt: the examples in the classification prompt are the levers. If Haiku is mis-classifying in one direction, adjust the examples or the definitions in the prompt body, not the regex.

`examples/settings.json` is the wiring example for `~/.claude/settings.json` `hooks.Stop`.
