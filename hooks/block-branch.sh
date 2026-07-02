#!/usr/bin/env bash
# Block reflexive branch creation in the ambient shared worktree. Work happens
# directly on main, in the one shared worktree that several agents share; a
# branch there gives no isolation and just hides work from the others on the
# same checkout. PreToolUse on Bash: deny the git commands that start or publish
# a branch in the ambient repo — checkout -b/-B, switch -c/-C, branch <newname>,
# worktree add, gh pr create, and push -u/--set-upstream to a non-main branch.
# Listing/deleting/renaming branches, returning to main, and pushing main pass.
#
# Scope is the ambient cwd's repo only. A command that explicitly operates on
# another checkout — a leading `cd`/`pushd`, or `git -C` / `--git-dir` — is
# fork/PR work in a separate repo, where feature branches are exactly the point;
# that passes through untouched. The git/gh token is matched only at a command
# boundary, so a branch word inside a commit message, echo, or grep never trips.
#
# Fires at most once per session: the first offending command is denied with the
# calibration below, and once that lesson has landed the guard steps aside for
# the rest of the session rather than walling a deliberate branch.

set -uo pipefail

input=$(cat)
tool_name=$(printf '%s' "$input" | jq -r '.tool_name // empty')
[[ "$tool_name" == "Bash" ]] || exit 0
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')
[[ -n "$cmd" ]] || exit 0

# Out of scope — the command operates on another checkout, not the ambient
# shared worktree. A leading `cd`/`pushd` redirects everything that follows;
# `git -C`/`--git-dir` redirects the git invocation itself. Fork/PR work lives
# in those other repos, where branching is the whole point.
printf '%s' "$cmd" | tr '\n' ' ' | grep -Eq '^[[:space:]]*\(?[[:space:]]*(cd|pushd)[[:space:]]' && exit 0
printf '%s' "$cmd" | grep -Eq 'git[[:space:]]+(-C[[:space:]]|--git-dir)' && exit 0

hit=""
# checkout -b/-B  |  switch -c/-C
printf '%s' "$cmd" | grep -Eq '(^|[;&|(])[[:space:]]*git[[:space:]]+(checkout[[:space:]]+-[bB]|switch[[:space:]]+-[cC])([[:space:]]|$)' && hit=1
# git branch <newname> — a bareword after `branch` creates; -d/-D/-m/-a/-v/--list
# start with '-' and pass, and main/master (returning to the trunk) pass too.
if printf '%s' "$cmd" | grep -Eq '(^|[;&|(])[[:space:]]*git[[:space:]]+branch[[:space:]]+[A-Za-z0-9._/]'; then
  printf '%s' "$cmd" | grep -Eq '(^|[;&|(])[[:space:]]*git[[:space:]]+branch[[:space:]]+(main|master)([[:space:]]|$)' || hit=1
fi
# git worktree add — all work stays in the one shared worktree
printf '%s' "$cmd" | grep -Eq '(^|[;&|(])[[:space:]]*git[[:space:]]+worktree[[:space:]]+add([[:space:]]|$)' && hit=1
# gh pr create — nothing to PR if we never leave main
printf '%s' "$cmd" | grep -Eq '(^|[;&|(])[[:space:]]*gh[[:space:]]+pr[[:space:]]+create([[:space:]]|$)' && hit=1
# git push -u/--set-upstream <remote> <non-main branch>
printf '%s' "$cmd" | perl -ne 'if (/(?:^|[;&|(])\s*git\s+push\b.*?(?:-u|--set-upstream)\s+\S+\s+(?!main(?:\b|\s|$))(?!master(?:\b|\s|$))\S+/) { $f=1 } END { exit($f ? 0 : 1) }' && hit=1

[[ -n "$hit" ]] || exit 0

# Once per session. Derive a stable per-session key (transcript filename, else
# session id), and if this session has already been nudged, step aside.
STATE_DIR="$HOME/.claude/hooks/state"
mkdir -p "$STATE_DIR" 2>/dev/null || true
find "$STATE_DIR" -type f -name 'branch-blocked-*' -mtime +7 -delete 2>/dev/null || true

transcript_path=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
session_id_field=$(printf '%s' "$input" | jq -r '.session_id // empty')
if [[ -n "$transcript_path" ]]; then
  session_marker=$(basename "$transcript_path" .jsonl)
elif [[ -n "$session_id_field" ]]; then
  session_marker="$session_id_field"
else
  session_marker=""
fi

if [[ -n "$session_marker" && -f "$STATE_DIR/branch-blocked-$session_marker" ]]; then
  exit 0
fi
[[ -n "$session_marker" ]] && touch "$STATE_DIR/branch-blocked-$session_marker" 2>/dev/null || true

read -r -d '' reason <<'EOF' || true
lol just commit to main.

We prefer to have conflicts raised early and often. All work of simultaneous agents occurs in the same worktree, and so branching wouldn't even give you any isolation in the first place — you're just confusing other agents. Leave the damn worktree on main, and commit there, and realize that this means you will encounter conflicts, but you will do so in real time, as they happen, and we can better coordinate the conflict resolution there. In practice, this usually means there aren't any conflicts at all, and the worst that happens is you commit someone else's work or they commit yours, and no one ever cares about that — just make sure it's committed (it probably is) and stop worrying about it.
EOF

jq -n --arg reason "$reason" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": $reason
  }
}'
exit 0
