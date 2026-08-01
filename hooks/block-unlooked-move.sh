#!/usr/bin/env bash
# Stop hook: in a turn that edited the enclosure's placement (_contents.py) or routing
# (_lines.py), block unless the last look is newer than those files' newest mtime.
#
# The mtime is the authority and the transcript supplies only this session's history, so a look
# taken before ANY agent's edit is stale — several sessions share one working tree, and a body
# moves under a render that has already been taken. A look is a render-view.js or look.sh run,
# or a Read of a .png. The condition clears on the next look; the stop_hook_active guard holds
# a turn to one block.
#
# A session that edited nothing passes, so another agent's edit alone does not block a turn.
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

# One marker per relevant tool call, each carrying the turn's epoch — one record per line, where
# a command carrying newlines would span lines.
#
#   EDIT — placement (_contents.py) or routing (_lines.py) was changed
#   LOOK — a render was taken, or a rendered .png was read
markers=$(jq -r '
  select(.type == "assistant")
  | (.timestamp // "") as $ts
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
  | . + " " + ((try ($ts | sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601) catch 0) | tostring)
' "$transcript_path" 2>/dev/null || true)

edits=$(printf '%s\n' "$markers" | grep -c '^EDIT ' || true)
if [[ "${edits:-0}" -eq 0 ]]; then
  log_status "no_placement_edits"
  exit 0
fi

looks=$(printf '%s\n' "$markers" | grep -c '^LOOK ' || true)
last_look=$(printf '%s\n' "$markers" | awk '$1 == "LOOK" { t = $2 } END { print t + 0 }')

# Newest mtime of the placement and routing source anywhere in the repo — every edition's copy,
# by whichever agent last wrote it.
src_mtime=$(find "$repo" \( -name node_modules -o -name .git \) -prune -o \
  -type f \( -name '_contents.py' -o -name '_lines.py' \) -print 2>/dev/null \
  | while IFS= read -r f; do stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null; done \
  | sort -n | tail -n 1)
src_mtime=${src_mtime:-0}

extra=$(jq -nc --argjson e "${edits:-0}" --argjson l "${looks:-0}" \
  --argjson look "${last_look:-0}" --argjson src "${src_mtime:-0}" \
  '{edits: $e, looks: $l, last_look: $look, src_mtime: $src}')

if [[ "$last_look" -ge "$src_mtime" ]]; then
  log_status "looked" "$extra"
  exit 0
fi

log_status "blocked" "$extra"

if [[ "${looks:-0}" -eq 0 ]]; then
  headline="You moved a body and have not looked at it."
else
  headline="Your look is stale — placement or routing source was written after it, which in this tree may have been another session."
fi

reason="${headline}

This turn edited _contents.py or _lines.py. The tables report bounding boxes.

    tools/look.sh <body>[,<body>...]        e.g. tools/look.sh fluid-23,fluid-27

Three orthographic views, subject solid, everything else in frame as edges, on a millimetre grid with numbered ticks. Read the PNGs it prints. The whole-machine elevations are already built beside the STEP — enclosure-assembly.top.png / .front.png / .right.png — and reading one of those counts.

What the tables do not carry: whether the part occupies the space its box claims, whether two lines cross where swapping their ports would let them run parallel, whether a face is nearly-but-not flush with its neighbour.

More in calibration/Fences.md. This clears on the next look."

jq -n --arg reason "$reason" '{"decision": "block", "reason": $reason}'
exit 0
