#!/usr/bin/env bash
# Stop hook: block a turn whose last edit to the enclosure's placement (_contents.py) or routing
# (_lines.py) came after its last look.
#
# A look is a render-view.js or look.sh run, or a Read of a .png. The condition clears on the
# next look; the stop_hook_active guard holds a turn to one block.
#
# Scoped to a repo carrying tools/render/render-view.js, silent elsewhere. Fail-open.
#
# Diagnostic log: $HOME/.claude/hooks/logs/unlooked-move.jsonl, one JSONL line per invocation
# with a "status" field, as the other hooks carry.

set -uo pipefail

LOG_FILE="$HOME/.claude/hooks/logs/unlooked-move.jsonl"
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

# Scope: a repo carrying the renderer, found by walking up from cwd.
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty')
[[ -n "$cwd" ]] || cwd=$PWD
repo=""
d="$cwd"
while [[ "$d" != "/" && -n "$d" ]]; do
  if [[ -f "$d/tools/render/render-view.js" ]]; then repo="$d"; break; fi
  d=$(dirname "$d")
done
if [[ -z "$repo" ]]; then
  log_status "no_render_repo"
  exit 0
fi

# One marker per relevant tool call, in transcript order — one token per record, where a command
# carrying newlines would span lines.
#
#   EDIT — placement (_contents.py) or routing (_lines.py) was changed
#   LOOK — a render was taken, or a rendered .png was read
markers=$(jq -r '
  select(.type == "assistant")
  | (.message.content // [])[]
  | select(.type == "tool_use")
  | if (.name | test("^(Edit|Write|MultiEdit|NotebookEdit)$"))
       and ((.input.file_path // "") | test("(_contents|_lines)\\.py$"))
    then "EDIT"
    elif (.name == "Bash") and ((.input.command // "") | test("render-view\\.js|look\\.sh"))
    then "LOOK"
    elif (.name == "Read") and ((.input.file_path // "") | test("\\.png$"))
    then "LOOK"
    else empty
    end
' "$transcript_path" 2>/dev/null || true)

if [[ -z "$markers" ]]; then
  log_status "no_placement_edits"
  exit 0
fi

last=$(printf '%s\n' "$markers" | grep -E '^(EDIT|LOOK)$' | tail -n 1)
edits=$(printf '%s\n' "$markers" | grep -c '^EDIT$' || true)
looks=$(printf '%s\n' "$markers" | grep -c '^LOOK$' || true)

if [[ "$last" != "EDIT" ]]; then
  log_status "looked" "$(jq -nc --argjson e "${edits:-0}" --argjson l "${looks:-0}" '{edits: $e, looks: $l}')"
  exit 0
fi

log_status "blocked" "$(jq -nc --argjson e "${edits:-0}" --argjson l "${looks:-0}" '{edits: $e, looks: $l}')"

reason="You moved a body and have not looked at it.

This turn edited _contents.py or _lines.py, and no render was taken after that edit. The tables report bounding boxes.

    tools/look.sh <body>[,<body>...]        e.g. tools/look.sh fluid-23,fluid-27

Three orthographic views, subject solid, everything else in frame as edges, on a millimetre grid with numbered ticks. Read the PNGs it prints. The whole-machine elevations are already built beside the STEP — enclosure-assembly.top.png / .front.png / .right.png — and reading one of those counts.

What the tables do not carry: whether the part occupies the space its box claims, whether two lines cross where swapping their ports would let them run parallel, whether a face is nearly-but-not flush with its neighbour.

More in calibration/Fences.md. This clears on the next look."

jq -n --arg reason "$reason" '{"decision": "block", "reason": $reason}'
exit 0
