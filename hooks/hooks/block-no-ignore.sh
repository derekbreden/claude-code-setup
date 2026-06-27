#!/usr/bin/env bash
# Block ripgrep searches that disable .gitignore. rg respects .gitignore by
# default, and that is the whole point here: the real signal lives in tracked
# files, while web/node_modules and the Python venvs hold tens of thousands of
# vendored lines. --no-ignore (and --no-ignore-vcs), --unrestricted, and -u/-uu
# drag all of that back into the results and bury what is being searched for —
# which is how a search turns into a false negative read off a truncated screen.
#
# PreToolUse on Bash: fire when a command-segment that invokes `rg` carries one
# of those flags. The flag is scoped to the rg segment, so a downstream
# `| sort -u` or `python -u` does not trip it. grep -r and find flood the same
# way with no flag to catch (they do not honor .gitignore at all), so they stay
# out of reach — this catches only the rg spelling.
#
# Nudge once per session, then pass through: a deliberate retry (you really do
# want an ignored tree, scoped to a path) is allowed. Per-session marker + 7-day
# GC, mirroring block-flash-before-commit.sh / block-web.sh. The deny message
# carries the calibration, in the register it was given.

set -uo pipefail

input=$(cat)
tool_name=$(printf '%s' "$input" | jq -r '.tool_name // empty')
[[ "$tool_name" == "Bash" ]] || exit 0
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')
[[ -n "$cmd" ]] || exit 0

# Fire only when an rg invocation itself carries an ignore-disabling flag. Split
# on shell separators and inspect each segment independently, so a downstream
# `| sort -u` is not read as rg's -u. --no-ignore covers --no-ignore-vcs and the
# other --no-ignore-* variants; -u/-uu (lowercase; -U is multiline, a different
# flag) and bundled shorts like -iu count; --unrestricted is the long form of -u.
hit=$(printf '%s' "$cmd" | perl -ne '
  for my $seg (split /\|\||&&|[;&|]/) {
    next unless $seg =~ m{(^|\s)(?:[A-Za-z_]\w*=\S+\s+)*(?:sudo\s+)?(?:\./|[^\s/]*/)?rg(\s|$)};
    if ($seg =~ /--no-ignore/ || $seg =~ /--unrestricted/ || $seg =~ /(^|\s)-[A-Za-z]*u[A-Za-z]*(\s|$)/) {
      print "1"; last;
    }
  }
')
[[ -n "$hit" ]] || exit 0

# Nudge once per session, then pass through. Per-session marker + 7-day GC,
# mirroring block-flash-before-commit.sh / block-web.sh.
WARNED_DIR="$HOME/.claude/hooks/state"
mkdir -p "$WARNED_DIR" 2>/dev/null || true
find "$WARNED_DIR" -type f -name 'noignore-warned-*' -mtime +7 -delete 2>/dev/null || true
transcript_path=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
session_id_field=$(printf '%s' "$input" | jq -r '.session_id // empty')
if [[ -n "$transcript_path" ]]; then
  session_marker=$(basename "$transcript_path" .jsonl)
elif [[ -n "$session_id_field" ]]; then
  session_marker="$session_id_field"
else
  session_marker=""
fi
if [[ -n "$session_marker" && -f "$WARNED_DIR/noignore-warned-$session_marker" ]]; then
  exit 0
fi
[[ -n "$session_marker" ]] && touch "$WARNED_DIR/noignore-warned-$session_marker" 2>/dev/null || true

read -r -d '' reason <<'EOF' || true
There is no point in searching gitignored files here — you are doing a ***very*** silly thing.

rg respects .gitignore for a reason: the real signal is in tracked files, while web/node_modules and the Python venvs hold tens of thousands of vendored lines. --no-ignore / -u / --unrestricted drags all of that back in and buries what you are looking for — which is exactly how a real search turns into a false negative read off a truncated screen. Drop the flag and let rg respect .gitignore.

If you genuinely need an ignored tree, scope it to a path (rg <pattern> web/node_modules/<pkg>) instead of unleashing it on the whole repo. If you really meant it, re-run as-is and it will go through — this fires once per session.
EOF

jq -n --arg reason "$reason" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": $reason
  }
}'
exit 0
