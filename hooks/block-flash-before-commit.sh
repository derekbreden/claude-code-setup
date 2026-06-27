#!/usr/bin/env bash
# Block flashing firmware with a dirty working tree. pre_build.py stamps
# FW_VERSION into every build from the git rev, so an uncommitted flash bakes
# "<sha>-dirty" into the binary — a build that matches no commit and can't be
# traced back to the source running on the chip. Commit first and the board
# maps to exactly one commit.
#
# PreToolUse on Bash: deny when the command EXECUTES a flash and the tree is
# dirty. A flash is `tools/flash.sh <env>` (without the build-only `build`
# arg) or `pio`/`platformio run ... -t/--target upload`. Detection is anchored
# to command position, so mentions of the script (cat/ls/grep tools/flash.sh)
# don't trip it. Dirtiness is the SAME test pre_build.py uses — plain
# `git status --porcelain` — so this denies exactly the cases that would stamp
# -dirty, and nothing else. Build-only runs and clean-tree flashes pass.
#
# Nudge once per session, then pass through: unlike branch creation, a dirty
# flash is sometimes the point (testing uncommitted changes on hardware), so a
# deliberate retry in the same session is allowed. Mirrors the per-session
# marker used by block-web.sh / block-residue.sh. The deny message carries the
# convention, in the register it was given.

set -uo pipefail

input=$(cat)
tool_name=$(printf '%s' "$input" | jq -r '.tool_name // empty')
[[ "$tool_name" == "Bash" ]] || exit 0
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')
[[ -n "$cmd" ]] || exit 0

is_flash=""

# tools/flash.sh <env> — uploads unless the build-only `build` arg is present.
# Anchored to a command-segment start (optionally via env-assignments, sudo, or
# a shell interpreter and a leading path), so `cat tools/flash.sh` doesn't match.
if printf '%s' "$cmd" | grep -Eq '(^|[;&|]|&&|\|\|)[[:space:]]*([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]+[[:space:]]+)*(sudo[[:space:]]+)?(bash[[:space:]]+|sh[[:space:]]+|zsh[[:space:]]+)?(\./|[^[:space:];&|]*/)?tools/flash\.sh([[:space:]]|$)'; then
  printf '%s' "$cmd" | grep -Eq 'tools/flash\.sh[[:space:]]+[A-Za-z0-9_]+[[:space:]]+build([[:space:]]|$)' || is_flash=1
fi

# pio/platformio run ... -t/--target upload
if printf '%s' "$cmd" | grep -Eq '(^|[;&|]|&&|\|\|)[[:space:]]*([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]+[[:space:]]+)*(sudo[[:space:]]+)?(pio|platformio)[[:space:]]+run([[:space:]]|$)' \
   && printf '%s' "$cmd" | grep -Eq '(-t|--target)[[:space:]]+upload([[:space:]]|$)'; then
  is_flash=1
fi

[[ -n "$is_flash" ]] || exit 0

# Clean tree → nothing to warn about. Same dirtiness test pre_build.py uses:
# plain porcelain (untracked included; gitignored files like the regenerated
# fw_version.h headers don't count). Bail silently if this isn't a git repo.
dirty=$(git status --porcelain 2>/dev/null) || exit 0
[[ -n "$dirty" ]] || exit 0

# Nudge once per session, then pass through. Unlike branch creation, a dirty
# flash is sometimes the point (testing uncommitted changes on hardware), so a
# deliberate retry is allowed. Per-session marker + 7-day GC, mirroring
# block-web.sh / block-residue.sh.
WARNED_DIR="$HOME/.claude/hooks/state"
mkdir -p "$WARNED_DIR" 2>/dev/null || true
find "$WARNED_DIR" -type f -name 'flash-warned-*' -mtime +7 -delete 2>/dev/null || true
transcript_path=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
session_id_field=$(printf '%s' "$input" | jq -r '.session_id // empty')
if [[ -n "$transcript_path" ]]; then
  session_marker=$(basename "$transcript_path" .jsonl)
elif [[ -n "$session_id_field" ]]; then
  session_marker="$session_id_field"
else
  session_marker=""
fi
if [[ -n "$session_marker" && -f "$WARNED_DIR/flash-warned-$session_marker" ]]; then
  exit 0
fi
[[ -n "$session_marker" ]] && touch "$WARNED_DIR/flash-warned-$session_marker" 2>/dev/null || true

rev=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
dirtylist=$(printf '%s\n' "$dirty" | head -n 20)

reason="Commit first, then flash.

pre_build.py stamps FW_VERSION from the git rev, so flashing now bakes \"${rev}-dirty\" into the binary — and a -dirty build matches no commit, so later you can't look at the board and say which source it's running. Committing is cheap here: you're on main, conflicts are fine, and then the chip maps to exactly one commit.

Uncommitted right now:
${dirtylist}

Commit what's pending (even WIP — it still gets a real rev), then re-run. If you do need a dirty test-flash, re-run as-is and it'll go through — this fires once per session."

jq -n --arg reason "$reason" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": $reason
  }
}'
exit 0
