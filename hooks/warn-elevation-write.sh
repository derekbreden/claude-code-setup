#!/usr/bin/env bash
# A speed bump on writes to the elevation every future session reads as Derek:
# any CLAUDE.md or AGENTS.md, and homesodamachine's calibration/. The first
# attempt on a given file is denied with the advisory below; repeating the same
# call goes through. Allowed, not forbidden — the deny is the only PreToolUse
# outcome whose message reaches the model, so the one-bounce IS the warning.
#
# Covers Write / Edit / MultiEdit -> tool_input.file_path (NotebookEdit has no
# business at this elevation but rides the same matcher harmlessly). Bash is
# intentionally NOT covered, same reasoning as block-memory-write.sh.

set -euo pipefail

input=$(cat)
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')
session_id=$(printf '%s' "$input" | jq -r '.session_id // "nosession"')

[[ -n "$file_path" ]] || exit 0

base=$(basename "$file_path")
if [[ "$base" != "CLAUDE.md" && "$base" != "AGENTS.md" \
      && "$file_path" != "$HOME/Developer/homesodamachine/calibration/"* ]]; then
  exit 0
fi

marker="${TMPDIR:-/tmp}/elevation-write-$(printf '%s' "$session_id:$file_path" | md5 -q)"

if [[ -e "$marker" ]]; then
  rm -f "$marker"
  exit 0
fi

touch "$marker"
jq -n --arg f "$file_path" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": ("You are writing to \($f) — the elevation every future session reads as Derek. A rule wanting to be written here is usually a TODO for a gap in the repo: the fix that holds is the artifact — changed geometry, a tool, code that teaches by example (calibration/Principle.md). If this write truly belongs at this elevation, repeat the same call and it will go through.")
  }
}'
