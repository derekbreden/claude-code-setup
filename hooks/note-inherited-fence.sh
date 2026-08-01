#!/usr/bin/env bash
# Note an inherited fence at the seam where it enters: a subagent report, or a
# task notification, that carries a limit claim — "impossible", "no room",
# "fully pinned", "the only option", "an envelope conversation". A conclusion
# inside another agent's report was produced by an agent with the reader's own
# failure mode, and a manager that relays it unprobed becomes its second author
# (calibration/Fences.md — The inherited fence, The route as requirement).
# Injects context rather than blocking. Runs on PostToolUse for Task|Agent
# (synchronous subagent results) and on UserPromptSubmit for turns carrying a
# <task-notification> block (background results). No Haiku stage: the note
# defuses itself on a report that already carries its price. Fires once per
# session, not twice. Fires only when the Fences calibration exists at its
# expected path; bails silently anywhere else. Fail-open on any error.
#
# Diagnostic log: every invocation appends one JSONL line to
# $HOME/.claude/hooks/logs/inherited-fence.jsonl with a "status" field (grep
# status="regex_no_match" to see what got past the pre-filter).

set -euo pipefail

LOG_FILE="$HOME/.claude/hooks/logs/inherited-fence.jsonl"
WARNED_DIR="$HOME/.claude/hooks/state"
mkdir -p "$(dirname "$LOG_FILE")" "$WARNED_DIR" 2>/dev/null || true

# Garbage-collect stale per-session warned markers (older than 7 days).
find "$WARNED_DIR" -name 'inherited-fence-noted-*' -mtime +7 -delete 2>/dev/null || true

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
event=$(printf '%s' "$input" | jq -r '.hook_event_name // empty')

# The text to judge, by event. PostToolUse: every string in the subagent's
# result. UserPromptSubmit: the prompt, and only on a task-notification turn —
# an ordinary user prompt is not a report.
case "$event" in
  PostToolUse)
    tool_name=$(printf '%s' "$input" | jq -r '.tool_name // empty')
    if [[ "$tool_name" != "Task" && "$tool_name" != "Agent" ]]; then
      log_status "wrong_tool" "$(jq -nc --arg tool "$tool_name" '{tool: $tool}')"
      exit 0
    fi
    text=$(printf '%s' "$input" | jq -r '[.tool_response | .. | strings] | join("\n")' 2>/dev/null || true)
    ;;
  UserPromptSubmit)
    text=$(printf '%s' "$input" | jq -r '.prompt // empty')
    if [[ "$text" != *"<task-notification>"* ]]; then
      log_status "not_a_notification"
      exit 0
    fi
    ;;
  *)
    log_status "wrong_event" "$(jq -nc --arg event "$event" '{event: $event}')"
    exit 0
    ;;
esac

if [[ -z "$text" || ${#text} -lt 40 ]]; then
  log_status "empty_or_short_text"
  exit 0
fi

# Strip backtick-delimited spans (fenced blocks and inline code) before pattern
# matching, so a report quoting trigger patterns as code does not fire.
text=$(printf '%s' "$text" | perl -0pe 's/```.*?```//gs; s/`[^`\n]+`//g' 2>/dev/null || printf '%s' "$text")

# Pre-filter: the same limit-claim shapes block-unpriced-impossibility.sh takes.
pattern='(envelope[a-z /-]{0,14}(conversation|bound|problem|question)|needs? the envelope|outside the (current )?envelope|grow (the )?(box|envelope)|[Ii]mpossible|can.?t be done|cannot be done|no room (for|left|anywhere)|there is no room|fully pinned|pinned (on|from) (all|both|every)|exhaust(ed|s)? (the|every|all)|the only (option|place|way|position|route|lane|column|space)|all [a-z0-9-]+ (cross|collide)|every [a-z0-9-]+ (dies|blocked|denied|crosses|collides|fails)|no legal (pose|position|route|path)|nothing (fits|clears)|\bFULL\b)'

if ! printf '%s\n' "$text" | grep -qE "$pattern"; then
  log_status "regex_no_match"
  exit 0
fi

# Claim this session's single note atomically; a racer that lost the claim
# passes through.
transcript_path=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
session_id_field=$(printf '%s' "$input" | jq -r '.session_id // empty')
if [[ -n "$transcript_path" ]]; then
  session_marker=$(basename "$transcript_path" .jsonl)
elif [[ -n "$session_id_field" ]]; then
  session_marker="$session_id_field"
else
  session_marker=""
fi
if [[ -n "$session_marker" ]]; then
  if ! mkdir "$WARNED_DIR/inherited-fence-noted-$session_marker" 2>/dev/null; then
    log_status "already_noted_this_session" "$(jq -nc --arg sid "$session_marker" '{session: $sid}')"
    exit 0
  fi
fi

log_status "noted" "$(jq -nc --arg event "$event" '{event: $event}')"

note="The report that just arrived carries a limit claim — impossible / no room / pinned / the only / envelope. A conclusion inside another agent's report is an inherited fence (calibration/Fences.md — The inherited fence): it was produced by an agent with your failure mode, and relaying it onward unprobed makes you its second author. Before accumulating it as a tie or handing it up: does the claim name what would have to move and what moving it costs, or only the pins of the current arrangement? For a run, what do its two ends actually need — the enclosure's need.py prints span, axis split and detour per run — and does the run belong in the region it is blocked in at all? If the claim already carries its price, carry on — this fires once a session."

jq -n --arg event "$event" --arg note "$note" '{
  "hookSpecificOutput": {
    "hookEventName": $event,
    "additionalContext": $note
  }
}'
