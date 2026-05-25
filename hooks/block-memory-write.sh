#!/usr/bin/env bash
# Block writes to any Claude project memory file with a Derek-personality error.
# Reads PreToolUse hook JSON from stdin; if the target is anywhere under a
# project's memory/ directory, emits a permissionDecision=deny with the canned message.
#
# Covers:
#   Write / Edit / MultiEdit  -> tool_input.file_path
#   NotebookEdit              -> tool_input.notebook_path
#
# Bash is intentionally NOT covered: no agent has tried that path, and adding
# Bash to the matcher imposes the hook on every shell command for a threat that
# isn't real yet. Reconsider if an agent ever does try `echo > ...memory/...`.

set -euo pipefail

input=$(cat)
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')

if [[ -n "$file_path" && "$file_path" == "$HOME/.claude/projects/"*"/memory/"* ]]; then
  jq -n '{
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": "The lessons we learn are not encoded literally in your memory. The lessons we learn are encoded by example in the changes you make. If you find yourself wanting to write a memory file, please consider how that lesson would be encoded by example in the work you are doing right now."
    }
  }'
fi
