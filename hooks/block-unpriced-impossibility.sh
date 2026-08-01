#!/usr/bin/env bash
# Block unpriced impossibility claims in the assistant's last message.
# When the agent reports an arrangement limit — "impossible", "no room", "fully
# pinned", "the only option", "an envelope conversation" — without naming what
# would have to move and what moving it costs, prompt the pricing rather than the
# retraction. A limit has two possible authors, the world or the box the agent
# searched, and a claim that names only the pins of the current arrangement has
# not said which (calibration/Fences.md — The route as requirement).
# Two-stage: cheap regex pre-filter, then Haiku disambiguation to distinguish a
# BARE claim (pins only, or the blame assigned to the envelope / a conversation
# upstairs) from a PRICED one (names the move and its cost, or its own search
# box). Wired on Stop and SubagentStop, so a stint's final report meets it too.
# Fires only when the Fences calibration exists at its expected path; bails
# silently anywhere else. Fail-open on any error.
#
# Diagnostic log: every invocation appends one JSONL line to
# $HOME/.claude/hooks/logs/unpriced-impossibility.jsonl with a "status" field
# identifying which code path was taken (grep status="regex_no_match" to see
# what got past the pre-filter).

set -euo pipefail

LOG_FILE="$HOME/.claude/hooks/logs/unpriced-impossibility.jsonl"
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

# The calibration this hook points at. No Fences.md, no opinion.
FENCES="$HOME/Developer/homesodamachine/calibration/Fences.md"
if [[ ! -f "$FENCES" ]]; then
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

# Extract the last assistant message line from the JSONL transcript, reversing
# only the tail. A single message larger than the tail window leaves no complete
# line in it, so an unparseable result falls back to the whole file.
last_line=$( (tail -c 200000 "$transcript_path" 2>/dev/null) | (tail -r 2>/dev/null || tac 2>/dev/null) | grep -m 1 '"type":"assistant"' || true)
if [[ -z "$last_line" ]] || ! printf '%s' "$last_line" | jq -e . >/dev/null 2>&1; then
  last_line=$( (tail -r "$transcript_path" 2>/dev/null || tac "$transcript_path" 2>/dev/null) | grep -m 1 '"type":"assistant"' || true)
fi
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

# Pre-filter: cheap regex for limit-claim shapes.
pattern='(envelope[a-z /-]{0,14}(conversation|bound|problem|question)|needs? the envelope|outside the (current )?envelope|grow (the )?(box|envelope)|[Ii]mpossible|can.?t be done|cannot be done|no room (for|left|anywhere)|there is no room|fully pinned|pinned (on|from) (all|both|every)|exhaust(ed|s)? (the|every|all)|the only (option|place|way|position|route|lane|column|space)|all [a-z0-9-]+ (cross|collide)|every [a-z0-9-]+ (dies|blocked|denied|crosses|collides|fails)|no legal (pose|position|route|path)|nothing (fits|clears)|\bFULL\b)'

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

classification_prompt='You will see a snippet from an AI assistant'\''s report that contains a limit claim ("impossible", "no room", "fully pinned", "the only option", "an envelope conversation", "FULL", etc.). If the limit is about a searched space — geometry, layout, routing, placement, a design'\''s room, an arrangement — classify whether the claim is PRICED or BARE. If the limit is about something else entirely (a policy, an API, a build error, arithmetic), reply "priced" so the message passes.

- priced = the report, in this snippet, names what would have to move to escape the limit and what moving it costs, or states the search bounds it ran and where they stopped. Examples: "No room unless the drip pan moves; the pan is held by rails, and raising it 4mm frees the rung", "I swept x[-14,60] y[176,200] at z=267.5 only — nothing outside this box was tested".
- bare = the claim names only the blockers pinning the current arrangement, assigns the block to something fixed (the envelope, the box), or hands the problem upstairs as someone else'\''s conversation — without naming a move, a cost, or its own search box. Examples: "REAR_PLANE_Y and the tray face and the SeaFlo pin it; an envelope/mounts conversation", "the west column is FULL", "impossible in the current envelope".

Reply with exactly one word: priced or bare.

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
elif [[ "$classification" == bare* ]]; then
  log_status "blocked" "$(jq -nc --arg classification "$classification" '{classification: $classification}')"
  jq -n '{
    "decision": "block",
    "reason": "You reported a limit without its price. A limit has two authors — the world, or the box you searched — and a claim naming only what pins the current arrangement has not said which. Before this sends: state what the blocked thing actually needs (for a run, its two endpoints and the distance between them split by axis — the enclosure'\''s need.py reports this), name what would have to move and what moving it costs, and say which bounds were yours. If the blocker you named is the envelope, look again: the envelope is the one thing that is actually fixed, so it is the one thing your search cannot have priced a move against. \"I did not find the move\" is sendable; \"there is no move\" is not. calibration/Fences.md — The route as requirement."
  }'
else
  log_status "allowed" "$(jq -nc --arg classification "$classification" '{classification: $classification}')"
fi
