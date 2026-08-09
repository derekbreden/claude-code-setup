#!/usr/bin/env bash
# Block effort estimates in the assistant's last message.
# Two-stage detection: cheap regex pre-filter, then Haiku disambiguation on a
# window of context around the candidate phrase(s). Fail-open on any error.
#
# Diagnostic log: every invocation appends one JSONL line to
# $HOME/.claude/hooks/logs/effort-estimate.jsonl with a "status" field
# identifying which code path was taken, so slips can be diagnosed after the
# fact (grep for status="regex_no_match" to see what got past the pre-filter).

set -euo pipefail

LOG_FILE="$HOME/.claude/hooks/logs/effort-estimate.jsonl"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# Append one JSONL line to the log. Fail-open on any error so the hook never
# breaks because of logging.
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

input=$(cat)

# Loop guard — don't re-block a revision attempt.
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

# Strip backtick-delimited spans (fenced blocks and inline code) before pattern
# matching. Documentation that quotes the hook's own trigger patterns should
# not be classified as live agent speech.
last_text=$(printf '%s' "$last_text" | perl -0pe 's/```.*?```//gs; s/`[^`\n]+`//g' 2>/dev/null || printf '%s' "$last_text")
if [[ -z "$last_text" || ${#last_text} -lt 40 ]]; then
  log_status "empty_after_strip"
  exit 0
fi

# Pre-filter: cheap regex for candidate effort-estimate shapes.
# If nothing matches, skip the Haiku call entirely.
# The pattern is intentionally lenient — false positives are cheap (one Haiku
# call) but false negatives are silent slips. Extend it when the log shows
# something getting past.
pattern='([Hh]alf[ \-]+(an?[ ]+)?(hour|day|week|month)|[Aa]n?[ ]+(afternoon|evening|morning|hour|day|week|month|year)s?|[Aa][ ]+few[ ]+(minutes?|hours?|days?|weeks?|months?)|[Aa][ ]+couple[ ]+(of[ ]+)?(minutes?|hours?|days?|weeks?|months?|years?)|(one|two|three|four|five|six|seven|eight|nine|ten)[ ]+(minutes?|hours?|days?|weeks?|months?|years?)|~?[0-9]+[ ]*-?[ ]*(min(ute)?s?|hours?|hrs?|days?|weeks?|wks?|months?|years?|yrs?)([^[:alpha:]]|$)|(minutes?|hours?|days?|weeks?|months?|years?)[ \-]*ish|weeks?[ ]+(,[ ]+)?not[ ]+months?|months?[ ]+(,[ ]+)?not[ ]+weeks?|time-to-[a-z]+|(should|would|will|might)[ ]+take|takes?[ ]+(about|roughly|a)|multi-year|several[ ]+(years?|months?|weeks?))'

if ! printf '%s\n' "$last_text" | grep -qE "$pattern"; then
  # Log the last 400 chars of the response so a future "why didn't this fire?"
  # investigation has the actual text to look at without needing the transcript.
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

# Window: ±800 chars around the first match position. Position-based rather
# than line-based, so very long unbroken paragraphs still get the match in view.
# `|| true` because a non-zero awk under `set -e` takes the whole hook down
# unlogged, and a hook that cannot classify must fail open, not vanish.
window=$(printf '%s' "$last_text" | awk -v pat="$pattern" '
  { full = full $0 "\n" }
  END {
    if (match(full, pat)) {
      start = RSTART - 800
      if (start < 1) start = 1
      end = RSTART + RLENGTH + 800
      if (end > length(full)) end = length(full)
      print substr(full, start, end - start + 1)
    }
  }
' || true)

if [[ -z "$window" ]]; then
  log_status "window_empty" "$(jq -nc --arg span "$matched_span" '{matched: $span}')"
  exit 0
fi

# Highlight: the exact span the regex matched, widened outward to whole
# whitespace-delimited tokens plus a little context, then handed to Haiku as
# "here is the text that triggered this check." This points the classifier at
# the trigger-in-situ — e.g. the bare match "28 min" surfaces as the token it
# actually lives in, "DIP-28 mini.tsx" — so a misfire buried in a long window
# is easy to recognize as a non-duration. The widening is deliberate: a bare
# fragment shown in isolation reads like a real time and biases the classifier
# the wrong way, so the span always carries its surrounding words. Empty (and
# the prompt falls back to no highlight) if extraction fails or the span runs
# long, which keeps the call byte-identical to the un-highlighted path.
highlight=$(printf '%s' "$last_text" | awk -v pat="$pattern" '
  { full = full $0 "\n" }
  END {
    if (match(full, pat)) {
      pad = 12
      s = RSTART - pad; if (s < 1) s = 1
      e = RSTART + RLENGTH + pad; if (e > length(full)) e = length(full)
      while (s > 1 && substr(full, s-1, 1) !~ /[ \t\r\n]/) s--
      while (e < length(full) && substr(full, e+1, 1) !~ /[ \t\r\n]/) e++
      span = substr(full, s, e - s + 1)
      gsub(/[ \t\r\n]+/, " ", span)
      sub(/^ +/, "", span); sub(/ +$/, "", span)
      if (length(span) <= 90) print span
    }
  }
' || true)

api_key_file="$HOME/.claude/anthropic_api_key"
if [[ ! -f "$api_key_file" ]]; then
  log_status "no_api_key"
  exit 0
fi
api_key=$(cat "$api_key_file")

# Instructions + the three-way definitions. The highlight line (if any) and the
# reply instruction are appended in the jq body assembly below.
classification_defs='A cheap regex flagged a possible time/effort estimate in the snippet below. The regex is deliberately lenient and frequently misfires on things that are not durations at all — part numbers ("DIP-28"), filenames ("mini.tsx"), version numbers, quantities, dimensions ("2.54mm"). Decide which of THREE cases applies.

- effort = the text estimates how long someone (especially the assistant itself) will spend doing work. Examples: "this will take a few hours", "half a day of work", "weeks not months", "~4 hours", "maybe a half-day of careful work", "multi-year project".
- projection = the text describes outcomes, properties, regulatory cadences, or durations of states (NOT work effort). Examples: "guaranteed multi-year loss", "bottle goes flat overnight", "tank lasts months", "for as long as the service operates", "every 5 years on 3AL aluminum", "happily for a year".
- none = there is no actual time estimate in the snippet; the regex misfired on text that is not a duration at all.'

# The highlight names the trigger span AND warns about the failure mode that
# naming a span introduces: focusing on a time-shaped fragment pulls attention
# off the surrounding word ("soak", "render", "Xometry", "ago") that marks it a
# process/machine/vendor/past duration rather than work-effort. Measured on 59
# real flagged windows: the bare "read it in context" phrasing was net-negative
# (it over-blocked projections); this projection-aware phrasing was the clear
# winner — it keeps the real effort catches and fixes projection misfires the
# un-highlighted prompt blocked.
if [[ -n "$highlight" ]]; then
  hl_line=$(printf 'The exact text the regex flagged is: "%s". Decide from the surrounding context, not this fragment alone — these same words often describe a process/cure/soak, a machine/compute/render, a vendor lead time, or a past/elapsed duration, none of which are work-effort. Call it effort only if the context shows someone estimating how long their own hands-on work will take.' "$highlight")
else
  hl_line=""
fi

body=$(jq -n \
  --arg model "claude-haiku-4-5" \
  --arg defs "$classification_defs" \
  --arg hl "$hl_line" \
  --arg msg "$window" \
  '{
    model: $model,
    max_tokens: 5,
    messages: [{role: "user", content: (
      $defs + "\n\n"
      + (if $hl == "" then "" else $hl + "\n\n" end)
      + "Reply with exactly one word: effort, projection, or none.\n\nSnippet:\n"
      + $msg
    )}]
  }')

response=$(curl -sS https://api.anthropic.com/v1/messages \
  -H "x-api-key: $api_key" \
  -H "content-type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  --max-time 3 \
  -d "$body" 2>/dev/null || echo '{}')

# The verdict is the reply's FIRST WORD. `max_tokens` is 5 and Haiku spends them
# opening a sentence as often as answering bare, so the reply arrives as either
# "effort" or "effort. The flagged phrase" — and a whole-string read of the
# second one is a word that matches no case, which falls to allowed. Reading the
# first alphabetic run takes the verdict out of both shapes and keeps the logged
# value legible. The budget stays at 5: latency here is what kills invocations.
classification=$(printf '%s' "$response" | jq -r '.content[0].text // empty' | tr '[:upper:]' '[:lower:]' | grep -oE '[a-z]+' | head -1 || true)

if [[ -z "$classification" ]]; then
  log_status "haiku_no_response"
elif [[ "$classification" == "effort" ]]; then
  log_status "blocked" "$(jq -nc --arg classification "$classification" --arg highlight "$highlight" '{classification: $classification, highlight: $highlight}')"
  jq -n '{
    "decision": "block",
    "reason": "An effort estimate from you is not tied to reality. It is pattern-matched from training data, where humans wrote estimates of work they were doing — work you will do entirely differently. Rewrite the response without putting a number on how long anything will take."
  }'
else
  log_status "allowed" "$(jq -nc --arg classification "$classification" --arg highlight "$highlight" '{classification: $classification, highlight: $highlight}')"
fi
