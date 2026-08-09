#!/usr/bin/env bash
# Block a parameter sweep reported as a finding in the assistant's last message.
# A sweep holds every variable but one fixed and reports what moving that one costs,
# so every row it produces is a half-move — one body moved, everything answering to it
# left standing. Reporting the shape of that table as a limit, a trade, or a question
# back to Derek reports the defeat of something built to lose
# (calibration/Chain.md — The sweep is a survey of strawmen).
# Two-stage: cheap regex pre-filter, then Haiku disambiguation to distinguish a SWEEP
# (multiple values of one input, conclusion drawn from the trend) from a SOLVE (a
# threshold inverted from the constraint), a PROBE (one state measured), or a source
# search. Wired on Stop and SubagentStop, so a stint's final report meets it too.
# Fires only when the Chain calibration exists at its expected path; bails silently
# anywhere else. Fail-open on any error.
#
# Diagnostic log: every invocation appends one JSONL line to
# $HOME/.claude/hooks/logs/parameter-sweep.jsonl with a "status" field identifying
# which code path was taken (grep status=\"regex_no_match\" to see what got past the
# pre-filter).

set -euo pipefail

LOG_FILE="$HOME/.claude/hooks/logs/parameter-sweep.jsonl"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

log_status() {
  local status="$1"
  local extra_json="${2:-null}"
  local ts
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  {
    if [[ "$extra_json" == "null" ]]; then
      jq -nc --arg ts "$ts" --arg status "$status" '{ts: $ts, status: $status}'
    else
      jq -nc --arg ts "$ts" --arg status "$status" --argjson extra "$extra_json" '{ts: $ts, status: $status} + $extra'
    fi
  } >> "$LOG_FILE" 2>/dev/null || true
}

# The calibration this hook points at. No Chain.md, no opinion.
CHAIN="$HOME/Developer/homesodamachine/calibration/Chain.md"
if [[ ! -f "$CHAIN" ]]; then
  exit 0
fi

input=$(cat)

# Loop guard — don't re-prompt a revision attempt.
stop_hook_active=$(printf '%s' "$input" | jq -r '.stop_hook_active // false')
if [[ "$stop_hook_active" == "true" ]]; then
  log_status "loop_guard"
  exit 0
fi

transcript_path=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
if [[ -z "$transcript_path" || ! -f "$transcript_path" ]]; then
  log_status "no_transcript"
  exit 0
fi

# The turn's final text, waited for. Reading it is not the one-liner it looks
# like: the last assistant LINE at a turn's end is routinely `thinking` or
# `tool_use` and holds no text, and the record this hook was fired to judge is
# still being written while the hook runs. _last_assistant_text.py carries both,
# and its docstring carries the measurement.
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
set +e
last_text=$(python3 "$HOOK_DIR/_last_assistant_text.py" "$transcript_path")
read_rc=$?
set -e
if [[ $read_rc -eq 1 ]]; then
  log_status "no_assistant_message"
  exit 0
fi
[[ $read_rc -eq 2 ]] && log_status "stale_read"

if [[ ${#last_text} -lt 40 ]]; then
  log_status "empty_or_short_text" "$(jq -nc --argjson len "${#last_text}" '{text_len: $len}')"
  exit 0
fi

# Strip inline code spans but KEEP fenced blocks and tables — a sweep's evidence is
# usually the table itself, and stripping it would hide the thing being classified.
last_text=$(printf '%s' "$last_text" | perl -0pe 's/`[^`\n]+`//g' 2>/dev/null || printf '%s' "$last_text")
if [[ -z "$last_text" || ${#last_text} -lt 40 ]]; then
  log_status "empty_after_strip"
  exit 0
fi

# Pre-filter: cheap regex for sweep shapes — the act, the grid, or a trend read off one.
pattern='([Ss]wept|[Ss]weep(ing|s)?\b|[Ss]can(ned|ning)\b|the scan\b|[Ss]ampl(ed|ing) (the|each|across|over)|grid search|[Ss]tepp(ed|ing) (through|across|over)|[Ii]terat(ed|ing) over (the )?(values|positions|stations|poses|offsets)|at each (step|value|position|station|offset)|tried (values|positions|stations|poses|several|each)|from the first millimetre|costs? [a-z ]{0,20} from the first|every millimetre of|per (mm|millimetre|degree) of (travel|west|east|rise|drop)|\| *[0-9.]+ ?mm *\|.*\| *[0-9.]+ *\|)'

if ! printf '%s\n' "$last_text" | grep -qE "$pattern"; then
  excerpt=$(printf '%s' "$last_text" | tail -c 400)
  log_status "regex_no_match" "$(jq -nc --argjson len "${#last_text}" --arg excerpt "$excerpt" '{text_len: $len, last_400_chars: $excerpt}')"
  exit 0
fi

# A match is logged here, before the stages that can fail. Everything past this
# point can die — the API call times out, a stage exits non-zero under `set -e`,
# the hook's own timeout kills the process — and none of it writes a line. A
# `regex_match` with no verdict after it is that death; without this line the
# death and a clean miss are the same silence.
matched_span=$(printf '%s\n' "$last_text" | grep -oE "$pattern" | head -1 || true)
log_status "regex_match" "$(jq -nc --arg span "$matched_span" '{matched: $span}')"

# Window: ±20 lines around the first matching line, wide enough to carry a table with
# it. Sliced by line rather than by character offset — the pattern carries escaped
# pipes for table rows, and awk's regex flavour does not take them.
match_line=$(printf '%s\n' "$last_text" | grep -nE "$pattern" | head -1 | cut -d: -f1 || true)
if [[ -z "$match_line" ]]; then
  log_status "window_empty"
  exit 0
fi
start=$(( match_line - 20 ))
[[ $start -lt 1 ]] && start=1
window=$(printf '%s\n' "$last_text" | sed -n "${start},$(( match_line + 20 ))p" || true)

if [[ -z "$window" ]]; then
  log_status "window_empty" "$(jq -nc --arg span "$matched_span" '{matched: $span}')"
  exit 0
fi

api_key_file="$HOME/.claude/anthropic_api_key"
if [[ ! -f "$api_key_file" ]]; then
  log_status "no_api_key"
  exit 0
fi
api_key=$(cat "$api_key_file")

classification_prompt='You will see a snippet from an AI assistant'\''s report in a 3D CAD repository. Classify whether it reports a PARAMETER SWEEP as a finding.

- sweep = the report varies ONE input (a position, an offset, a travel, an angle) across several values, shows what each value did to some quality metric, and draws a conclusion from the trend — a limit, a trade-off, a "costs from the first millimetre", a recommendation, or a question back to the user asking them to pick a value. The giveaway is a table or list of sampled input values with an outcome beside each, used as evidence.
- fine = anything else. In particular these are all fine and must be classified fine: a SOLVE that inverts a constraint to get a threshold directly ("the minimum angle that reaches R25.4 is 36.81 degrees"); a PROBE that measures ONE configuration ("at this station the bore lands 0.25 mm off the wall"); a comparison of the CURRENT state against a TARGET state ("was R19.78, now R25.40"); a search through SOURCE CODE or files; a list of distinct design candidates or bodies that is not one input varied across values; reporting gate results; or a sweep that is described only as something the report is NOT doing or is being told not to do.

Reply with exactly one word: sweep or fine.

Snippet:
'

body=$(jq -n \
  --arg model "claude-haiku-4-5" \
  --arg prompt "$classification_prompt" \
  --arg msg "$window" \
  '{
    model: $model,
    max_tokens: 5,
    messages: [{role: "user", content: ($prompt + $msg)}]
  }')

response=$(curl -sS https://api.anthropic.com/v1/messages \
  -H "x-api-key: $api_key" \
  -H "content-type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  --max-time 3 \
  -d "$body" 2>/dev/null || echo '{}')

# The verdict is the reply's FIRST WORD. `max_tokens` is 5 and Haiku spends them
# opening a sentence as often as answering bare, so the reply arrives as either
# "sweep" or "sweep. The table". Reading the first alphabetic run takes the
# verdict out of both shapes and keeps the logged value legible, which a prefix
# test on the whole run-on string does not. The budget stays at 5: latency here
# is what kills invocations.
classification=$(printf '%s' "$response" | jq -r '.content[0].text // empty' | tr '[:upper:]' '[:lower:]' | grep -oE '[a-z]+' | head -1 || true)

if [[ -z "$classification" ]]; then
  log_status "haiku_no_response"
elif [[ "$classification" == "sweep" ]]; then
  log_status "blocked" "$(jq -nc --arg classification "$classification" '{classification: $classification}')"
  jq -n '{
    "decision": "block",
    "reason": "You are reporting a sweep. Each row of it is a half-move — one body travelled and everything that answers to it left standing — so the trend you read off it is the cost of mutilating the machine, not the cost of the move. Before this sends: state the target as the condition it has to meet, print the chain (every derivation reading the body you are moving, and everything reading those), move all of it in one commit, and let the gates price the whole rearrangement. They are exact; you do not need to approach them by sampling. If a link in the chain has no answer you can derive, that link is the one line Derek needs — send that, not the table. If the whole move is built and goes red, commit it red with the unanswered link named. calibration/Chain.md."
  }'
else
  log_status "allowed" "$(jq -nc --arg classification "$classification" '{classification: $classification}')"
fi
