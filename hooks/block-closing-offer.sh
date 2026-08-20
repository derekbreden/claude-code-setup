#!/usr/bin/env bash
# Block a turn that ends by OFFERING work the agent could have done.
# "Say the word and I'll land it", "want me to run it?", "let me know if you'd
# like X" — on work already measured, already understood, already asked for.
# Two-stage: regex pre-filter over the turn's TAIL (the offer lives at the end,
# which is the least-read position on the page), then Haiku disambiguation to
# separate a real fork only the user can settle from an offer to do the job.
# Fail-open on any error.
#
# Why this exists: homesodamachine/calibration/Discretion.md. Its editor's note
# records that CLAUDE.md already said "Always commit and push to main. Don't ask.
# Just do it," and a session read that file and then ended six turns on an offer
# anyway. The example was tested and did not hold; this is the escalation.
#
# Diagnostic log: $HOME/.claude/hooks/logs/closing-offer.jsonl, one JSONL line
# per invocation with a "status" field naming the code path taken.

set -euo pipefail

LOG_FILE="$HOME/.claude/hooks/logs/closing-offer.jsonl"
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

input=$(cat)

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

# Strip code spans: a hook or a doc that quotes these phrases is not offering.
last_text=$(printf '%s' "$last_text" | perl -0pe 's/```.*?```//gs; s/`[^`\n]+`//g' 2>/dev/null || printf '%s' "$last_text")
if [[ -z "$last_text" || ${#last_text} -lt 40 ]]; then
  log_status "empty_after_strip"
  exit 0
fi

# THE TAIL IS THE TARGET. An offer mid-turn ("I can do X, and here it is") is
# narration; the failure this catches is a turn that STOPS on one. 700 chars is
# about the last two paragraphs.
tail_text=$(printf '%s' "$last_text" | tail -c 700)

pattern='([Ss]ay[ ]+the[ ]+word|[Jj]ust[ ]+say[ ]+the[ ]+word|[Ww]ant[ ]+me[ ]+to[^?]{0,120}\?|[Ww]ould[ ]+you[ ]+like[ ]+me[ ]+to[^?]{0,120}\?|[Ss]hall[ ]+I[^?]{0,120}\?|[Ll]et[ ]+me[ ]+know[ ]+if[ ]+you[ ]?.?d?[ ]*(like|want|prefer)|[Ii][ ]+can[^.!?]{0,80}if[ ]+you[ ]?.?d?[ ]*(like|want)|[Hh]appy[ ]+to[^.!?]{0,60}if[ ]+you|[Ss]hould[ ]+I[ ]+(go[ ]+ahead|proceed|run|land|commit|push)[^?]{0,120}\?|[Ii]f[ ]+you[ ]+want[ ]+me[ ]+to)'

if ! printf '%s\n' "$tail_text" | grep -qE "$pattern"; then
  log_status "regex_no_match" "$(jq -nc --argjson len "${#last_text}" --arg excerpt "$tail_text" '{text_len: $len, tail: $excerpt}')"
  exit 0
fi

matched_span=$(printf '%s\n' "$tail_text" | grep -oE "$pattern" | head -1 || true)
log_status "regex_match" "$(jq -nc --arg span "$matched_span" '{matched: $span}')"

api_key_file="$HOME/.claude/anthropic_api_key"
if [[ ! -f "$api_key_file" ]]; then
  log_status "no_api_key"
  exit 0
fi
api_key=$(cat "$api_key_file")

classification_prompt='You will see the closing passage of an AI coding agent'\''s turn. It contains an offer shape ("say the word", "want me to X?", "let me know if you'\''d like"). Classify the offer.

- work = the agent is offering to do WORK it has already scoped and could simply have done: run a command it named, apply a fix it described, land or push a change, extend the task it was given. The user would have to reply "yes" to get a thing the agent already knew how to make. This includes offers wrapped around a follow-up the agent itself identified as owed.
- decision = the agent genuinely cannot proceed without the user, because the answer is a preference, a fork with materially different outcomes, an approval for something reaching outside the user'\''s own systems, or information the agent has no way to obtain. Not merely "the agent felt unsure".

Reply with exactly one word: work or decision.

Closing passage:
'

body=$(jq -n \
  --arg model "claude-haiku-4-5" \
  --arg prompt "$classification_prompt" \
  --arg msg "$tail_text" \
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

classification=$(printf '%s' "$response" | jq -r '.content[0].text // empty' | tr '[:upper:]' '[:lower:]' | grep -oE '[a-z]+' | head -1 || true)

if [[ -z "$classification" ]]; then
  log_status "haiku_no_response"
elif [[ "$classification" == "work" ]]; then
  log_status "blocked" "$(jq -nc --arg classification "$classification" '{classification: $classification}')"
  jq -n '{
    "decision": "block",
    "reason": "You ended your turn offering to do work you had already scoped. Go do it, then end on what landed. The offer sits in the least-read position on the page, so the likely outcome of stopping here is that nobody reads it and nothing lands. If the directive force of the request was ambiguous, the tie goes to acting: do it, commit it, and say which part you guessed at. If it is genuinely a fork only the user can settle, put the question in the FIRST line of your turn, not the last, and say what you will do by default if they do not answer."
  }'
else
  log_status "allowed" "$(jq -nc --arg classification "$classification" '{classification: $classification}')"
fi
