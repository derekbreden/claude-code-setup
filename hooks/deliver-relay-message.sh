#!/usr/bin/env bash
# Deliver explicitly deferred relay messages for this session — the receive half
# of `jsonl2md.py send --defer`. Live sends use the native peer receiver. A sender
# using the legacy compatibility path drops a message
# file into ~/.claude/hooks/relay-inbox/<sessionId>/;
# this PreToolUse hook (matcher "*") drains that mailbox on the target's next
# tool call and injects the message, then removes it.
#
# The free path is a single directory test: sessions nobody has messaged have no
# mailbox dir, so this exits 0 (allow) immediately — no work, no cost. Only when
# a message is actually queued does it do anything. It NEVER denies except to
# carry a queued message, and always drains (rm) what it delivers, so a delivered
# message can't re-fire and jam the agent.
#
# Two modes, set per message by the sender:
#   interrupt -> permissionDecision "deny": the imminent tool is blocked and the
#                message is put in front of the agent (mirrors block-web.sh).
#   nudge     -> additionalContext: the message rides along without blocking.

set -uo pipefail

input=$(cat)

# Session id == the transcript's basename (== cliSessionId), the same key the
# sender resolves a title to. Fall back to the session_id field.
transcript_path=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
if [[ -n "$transcript_path" ]]; then
  session_id=$(basename "$transcript_path" .jsonl)
else
  session_id=$(printf '%s' "$input" | jq -r '.session_id // empty')
fi
[[ -n "$session_id" ]] || exit 0

box="${HSM_RELAY_INBOX_ROOT:-$HOME/.claude/hooks/relay-inbox}/$session_id"
[[ -d "$box" ]] || exit 0        # the free path: no mailbox, nothing to do

# Queued messages, oldest first (bash sorts glob results; filenames are
# zero-padded-millis-prefixed, so lexical == chronological). The sender writes
# via a .tmp the *.json glob ignores, so we never read a half-written file.
shopt -s nullglob
files=("$box"/*.json)
shopt -u nullglob
[[ ${#files[@]} -gt 0 ]] || exit 0

now=$(date +%s)
mode="nudge"
body=""
for f in "${files[@]}"; do
  # Concurrent tools can run hooks together. Only one hook claims each message.
  original="$f"
  mv "$original" "$original.delivering" 2>/dev/null || continue
  f="$original.delivering"
  # Preserve expired/malformed messages for inspection without injecting stale
  # instructions. Legacy messages without expires_at have a five-minute lifetime.
  if ! jq -e --argjson now "$now" '(.expires_at // ((.ts // 0) + 300)) as $expiry | ($expiry | type) == "number" and $expiry > $now' "$f" >/dev/null 2>&1; then
    mkdir -p "$box/expired"
    mv "$f" "$box/expired/$(basename "$original")"
    continue
  fi
  mtext=$(jq -r '.text // empty' "$f" 2>/dev/null)
  mmode=$(jq -r '.mode // "interrupt"' "$f" 2>/dev/null)
  mfrom=$(jq -r '.from // empty' "$f" 2>/dev/null)
  mrepl=$(jq -r '.reply_to // empty' "$f" 2>/dev/null)
  msent=$(jq -r 'if (.ts | type) == "number" then .ts | strftime("%Y-%m-%d %H:%M:%S UTC") else "time unknown" end' "$f" 2>/dev/null)
  rm -f "$f"
  [[ -z "$mtext" ]] && continue
  [[ "$mmode" == "interrupt" ]] && mode="interrupt"
  [[ -n "$body" ]] && body+=$'\n'
  body+="Agent message from ${mfrom:-unknown} · sent ${msent}"$'\n\n'"${mtext}"$'\n'
  # An answer need not request another answer. Quote the address as shell data.
  if [[ -n "$mrepl" ]]; then
    printf -v reply_target '%q' "$mrepl"
    body+=$'\n'"Reply to ${mrepl}:"$'\n'"python3 ~/Developer/claude-code-setup/jsonl2md/jsonl2md.py send ${reply_target} '<your answer>' --from '<your task title>'"$'\n'
  fi
done

[[ -n "$body" ]] || exit 0

message="$body"

if [[ "$mode" == "interrupt" ]]; then
  jq -n --arg reason "$message" '{
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": $reason
    }
  }'
else
  jq -n --arg ctx "$message" '{
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "additionalContext": $ctx
    }
  }'
fi
exit 0
