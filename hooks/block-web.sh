#!/usr/bin/env bash
# Block the built-in web tools — nudge once per session (per tool) toward Chrome
# MCP, which is far more reliable than either. WebFetch hits cert failures, stale
# page caches, and stale content Chrome doesn't; WebSearch is not Google and its
# results are weak. PreToolUse on WebFetch|WebSearch: deny the first call of each
# tool in the session with a tool-appropriate redirect to Chrome MCP, then pass
# through — so a session where Chrome MCP genuinely isn't available isn't stuck.
# Mirrors the once-per-session marker used by block-residue.sh /
# block-underived-measurement.sh.
#
# No Haiku stage and no logging — the tool name is unambiguous, nothing to adjudicate.

set -uo pipefail

WARNED_DIR="$HOME/.claude/hooks/state"
mkdir -p "$WARNED_DIR" 2>/dev/null || true

# Garbage-collect stale per-session warned markers (older than 7 days).
find "$WARNED_DIR" -type f \( -name 'webfetch-warned-*' -o -name 'websearch-warned-*' \) -mtime +7 -delete 2>/dev/null || true

input=$(cat)
tool_name=$(printf '%s' "$input" | jq -r '.tool_name // empty')

# Per-tool marker prefix + redirect message. Anything else passes through.
case "$tool_name" in
  WebFetch)
    marker_prefix="webfetch-warned"
    read -r -d '' reason <<'EOF' || true
Please use Chrome MCP instead. It is far more reliable and trustworthy. WebFetch errors are not an excuse for failing to use Chrome MCP.
EOF
    ;;
  WebSearch)
    marker_prefix="websearch-warned"
    read -r -d '' reason <<'EOF' || true
Please use Chrome MCP instead. WebSearch is not Google and its results are weak. Weak WebSearch results are not an excuse for failing to use Chrome MCP.
EOF
    ;;
  *)
    exit 0
    ;;
esac

# Per-session loop guard, per tool. Nudge once per session; after the marker is
# in place, subsequent calls of that tool in the same session pass through (so a
# session where Chrome MCP isn't connected can still fall back).
transcript_path=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
session_id_field=$(printf '%s' "$input" | jq -r '.session_id // empty')
if [[ -n "$transcript_path" ]]; then
  session_marker=$(basename "$transcript_path" .jsonl)
elif [[ -n "$session_id_field" ]]; then
  session_marker="$session_id_field"
else
  session_marker=""
fi

if [[ -n "$session_marker" && -f "$WARNED_DIR/$marker_prefix-$session_marker" ]]; then
  exit 0
fi
[[ -n "$session_marker" ]] && touch "$WARNED_DIR/$marker_prefix-$session_marker" 2>/dev/null || true

jq -n --arg reason "$reason" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": $reason
  }
}'
exit 0
