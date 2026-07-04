#!/usr/bin/env bash
# Deliver relay messages queued for this session — the receive half of
# `jsonl2md.py send`. A second session (an agent acting for the user, watching
# this one) drops a message file into ~/.claude/hooks/relay-inbox/<sessionId>/;
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

box="$HOME/.claude/hooks/relay-inbox/$session_id"
[[ -d "$box" ]] || exit 0        # the free path: no mailbox, nothing to do

# Queued messages, oldest first (bash sorts glob results; filenames are
# zero-padded-millis-prefixed, so lexical == chronological). The sender writes
# via a .tmp the *.json glob ignores, so we never read a half-written file.
shopt -s nullglob
files=("$box"/*.json)
shopt -u nullglob
[[ ${#files[@]} -gt 0 ]] || exit 0

mode="nudge"
body=""
for f in "${files[@]}"; do
  mtext=$(jq -r '.text // empty' "$f" 2>/dev/null)
  mmode=$(jq -r '.mode // "interrupt"' "$f" 2>/dev/null)
  mfrom=$(jq -r '.from // empty' "$f" 2>/dev/null)
  [[ -z "$mtext" ]] && continue
  [[ "$mmode" == "interrupt" ]] && mode="interrupt"
  if [[ -n "$mfrom" ]]; then
    body+="• (from ${mfrom}) ${mtext}"$'\n'
  else
    body+="• ${mtext}"$'\n'
  fi
done

# Drain unconditionally — a message is delivered at most once, even on a parse
# miss, so it can never loop back and block every subsequent tool call.
rm -f "${files[@]}" 2>/dev/null || true

[[ -n "$body" ]] || exit 0

header="📬 RELAYED MESSAGE — the user injected this into your session out-of-band, from a second Claude Code session watching your work. It is a direct interjection from the user; give it the same weight as anything the user types. Read it, then adjust course before continuing:"
message="${header}"$'\n\n'"${body}"

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
