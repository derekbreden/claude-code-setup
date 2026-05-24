#!/usr/bin/env bash
# Block unexplained hedges in the assistant's last message.
# When the agent hedges ("I'm not sure", "might be wrong", etc.) without
# saying what the underlying concern is, prompt expansion rather than removal.
# Two-stage: cheap regex pre-filter, then Haiku disambiguation to distinguish
# substantive hedging (carries information) from social/habitual hedging
# (politeness, throat-clearing — no real concern to explain).
# Fail-open on any error.
#
# Diagnostic log: every invocation appends one JSONL line to
# $HOME/.claude/hooks/logs/unexplained-hedge.jsonl with a "status" field
# identifying which code path was taken, so slips can be diagnosed after the
# fact (grep for status="regex_no_match" to see what got past the pre-filter).

set -euo pipefail

LOG_FILE="$HOME/.claude/hooks/logs/unexplained-hedge.jsonl"
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

# Extract the last assistant message line from the JSONL transcript.
last_line=$( (tail -r "$transcript_path" 2>/dev/null || tac "$transcript_path" 2>/dev/null) | grep -m 1 '"type":"assistant"' || true)
if [[ -z "$last_line" ]]; then
  log_status "no_assistant_message"
  exit 0
fi

last_text=$(printf '%s' "$last_line" | jq -r '(.message.content // []) | map(select(.type == "text") | .text) | join("\n")' 2>/dev/null || true)
if [[ -z "$last_text" || ${#last_text} -lt 40 ]]; then
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

# Pre-filter: cheap regex for candidate hedging shapes.
pattern='([Ii]'\''m[ \-]+not[ \-]+(entirely|totally|fully|really|completely|quite)?[ ]*(sure|certain)|[Ii]'\''m[ \-]+uncertain|though[ \-]+[Ii]'\''m[ \-]+not[ \-]+(sure|certain)|(might|could|may)[ \-]+be[ \-]+wrong|[Ii][ \-]+think[ \-]+this[ \-]+(might|may)|may[ \-]+not[ \-]+be[ \-]+the[ \-]+(best|right|ideal)|[Ii]'\''m[ \-]+hesitant)'

if ! printf '%s\n' "$last_text" | grep -qE "$pattern"; then
  excerpt=$(printf '%s' "$last_text" | tail -c 400)
  log_status "regex_no_match" "$(jq -nc --argjson len "${#last_text}" --arg excerpt "$excerpt" '{text_len: $len, last_400_chars: $excerpt}')"
  exit 0
fi

# Window: ±800 chars around the first match position.
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
')

api_key_file="$HOME/.claude/anthropic_api_key"
if [[ ! -f "$api_key_file" ]]; then
  log_status "no_api_key"
  exit 0
fi
api_key=$(cat "$api_key_file")

classification_prompt='You will see a snippet from an AI assistant'\''s response that contains a hedging phrase ("I'\''m not sure", "might be wrong", "this could be wrong", etc.). Classify whether the hedge reflects a SUBSTANTIVE concern (the agent has a real reservation it could explain in more detail if asked) or SOCIAL hedging (politeness, habitual softening, throat-clearing — no underlying concern to elaborate on).

- substantive = the hedge is carrying information. There is something the agent could surface and explain if invited. Examples: "I'\''m not sure this addresses what you actually asked — the question seemed to be about X, not Y", "This might be wrong because the data model assumes Z which may not hold here".
- social = the hedge is softening / politeness / habit. Nothing material is being withheld. Examples: "I'\''m not sure if this is what you wanted, but here is the answer", "This might be a small point, but the import order matters here".

Reply with exactly one word: substantive or social.

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

classification=$(printf '%s' "$response" | jq -r '.content[0].text // empty' | tr -d '[:space:].' | tr '[:upper:]' '[:lower:]')

if [[ -z "$classification" ]]; then
  log_status "haiku_no_response"
elif [[ "$classification" == "substantive" ]]; then
  log_status "blocked" "$(jq -nc --arg classification "$classification" '{classification: $classification}')"
  jq -n '{
    "decision": "block",
    "reason": "You hedged. The hedge probably reflects a deeper concern. Do not remove the hedge — explain what you are concerned about, and why. If you have already raised this earlier and it did not seem to land, I may have skimmed past it; that is okay. Repeat the concern fully — do not soften it because you suspect it was missed. Repetition is welcome here."
  }'
else
  log_status "allowed" "$(jq -nc --arg classification "$classification" '{classification: $classification}')"
fi
