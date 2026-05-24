#!/usr/bin/env bash
# Block disagreement-framed-as-question in the assistant's last message.
# When the agent has a structural reservation and frames it as a question
# ("I notice X — was that intended?") instead of stating it directly, prompt
# the direct statement. Two-stage: regex pre-filter for question shapes that
# typically carry skepticism, then Haiku disambiguation to distinguish a
# genuine question (needs information to proceed) from a disagreement wearing
# question's clothes (has a view, asking-not-stating).
# Fail-open on any error.
#
# Diagnostic log: every invocation appends one JSONL line to
# $HOME/.claude/hooks/logs/question-as-disagreement.jsonl with a "status" field
# identifying which code path was taken, so slips can be diagnosed after the
# fact (grep for status="regex_no_match" to see what got past the pre-filter).

set -euo pipefail

LOG_FILE="$HOME/.claude/hooks/logs/question-as-disagreement.jsonl"
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

# Pre-filter: cheap regex for question shapes that typically carry skepticism.
pattern='([Ii][ \-]+(notice|noticed|see)[^.!?]+\?|(was|is)[ ]+that[ ]+(intended|intentional|on[ \-]+purpose|deliberate)\??|did[ ]+you[ ]+(mean|intend)[ ]+to[^.!?]*\??|is[ ]+that[ ]+(intentional|on[ \-]+purpose|by[ \-]+design)\??)'

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

classification_prompt='You will see a snippet from an AI assistant'\''s response that contains a question shape ("I notice X — was that intended?", "Did you mean to Y?", "Is that on purpose?", etc.). Classify whether this is a GENUINE question (the agent needs information to proceed and is asking) or a DISAGREEMENT framed as a question (the agent has a structural view that something is wrong/suboptimal, and is asking-not-stating to soften the contradiction).

- genuine = the agent does not have a view yet; needs information. Examples: "Are you using PostgreSQL or MySQL?", "Should this run on every page load or just on the first one?".
- disagreement = the agent already has a view that something is wrong/off, and is framing it as a question rather than stating the disagreement directly. The question implies the answer the agent expects to receive. Examples: "I notice the file uses synchronous I/O — was that intended?" (agent thinks it should be async), "Did you mean to set timeout to 30000? That is quite long." (agent thinks the timeout is too long).

Reply with exactly one word: genuine or disagreement.

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
elif [[ "$classification" == "disagreement" ]]; then
  log_status "blocked" "$(jq -nc --arg classification "$classification" '{classification: $classification}')"
  jq -n '{
    "decision": "block",
    "reason": "You framed disagreement as a question. State the concern directly — what do you think is wrong, and what would you do differently? If you have already raised this earlier and it did not seem to land, I may have skimmed past it; that is okay. Repeat the concern fully and directly — do not soften it back into a question because you suspect it was missed. Repetition is welcome here."
  }'
else
  log_status "allowed" "$(jq -nc --arg classification "$classification" '{classification: $classification}')"
fi
