#!/usr/bin/env bash
# The first memory write of a session bounces once to homesodamachine's
# calibration/principle/Memory.md: what memory on this laptop is for. Every
# later memory write in that session goes through. The deny is the only
# PreToolUse outcome whose message reaches the model, so the one bounce is the
# pointer.
#
# Covers Write / Edit / MultiEdit -> tool_input.file_path and NotebookEdit ->
# tool_input.notebook_path, anywhere under a project's memory/ directory. Bash
# is not covered: Claude Code's memory instructions name the Write tool, and
# Bash in the matcher would put this hook on every shell command.

set -euo pipefail

input=$(cat)

# Nearly every write lands elsewhere; leave before starting jq.
[[ "$input" == *"/memory/"* ]] || exit 0

file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')
[[ "$file_path" == "$HOME/.claude/projects/"*"/memory/"* ]] || exit 0

session_id=$(printf '%s' "$input" | jq -r '.session_id // empty')
state="$HOME/.claude/hooks/state"
marker="$state/memory-calibrated-${session_id:-nosession}"
[[ -e "$marker" ]] && exit 0

mkdir -p "$state"
touch "$marker"
find "$state" -type f -name 'memory-calibrated-*' -mtime +7 -delete 2>/dev/null || true

jq -n --arg room "$HOME/Developer/homesodamachine/calibration/principle/Memory.md" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": ("First memory write of this session. Before making it, read \($room): what memory on this laptop is for. Memory writes go through for the rest of the session.")
  }
}'
