#!/usr/bin/env bash
# Block sleeping on a background task's own output file. PreToolUse on Bash: deny a
# command that both sleeps and names a harness task file (`.../tasks/<id>.output`),
# which is the shape of `until [ -s … ]; do sleep 10; done`, `until grep -q … ; do
# sleep 15; done`, and `sleep 180; cat …/tasks/….output`.
#
# The harness re-invokes the session when a background task exits. A wait spent on a
# clock instead is time bought for nothing, and it is bounded by the Bash timeout
# rather than by the job — a poll that outlives its 600 s ceiling returns empty
# having watched a job that finished ten minutes earlier.
#
# Scope is deliberately narrow. Sleeping on something the harness does NOT track — a
# CI run, a deploy, a dev server's port, another agent's lock — is the legitimate
# use and passes untouched; only a task file the harness itself created trips this.
#
# Fires at most once per session, like the branch guard: the first offender is denied
# with the calibration below, and after that the guard steps aside.

set -uo pipefail

input=$(cat)
tool_name=$(printf '%s' "$input" | jq -r '.tool_name // empty')
[[ "$tool_name" == "Bash" ]] || exit 0
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')
[[ -n "$cmd" ]] || exit 0

flat=$(printf '%s' "$cmd" | tr '\n' ' ')

# The pattern as DATA rather than as the command being run — a heredoc, an inline script, an
# echo, a grep over transcripts. Those mention the shape without waiting on anything, and a
# guard that cannot tell the difference denies the tests written for it.
printf '%s' "$flat" | grep -Eq '<<-?[[:space:]]*['"'"'"]?[A-Za-z_]+' && exit 0
printf '%s' "$flat" | grep -Eq '(python3?|node|perl|ruby)[[:space:]]+-[ce][[:space:]]' && exit 0
printf '%s' "$flat" | grep -Eq '^[[:space:]]*(echo|printf)([[:space:]]|$)' && exit 0

# Both halves must be present: a wait on a clock, and a harness task file.
printf '%s' "$flat" | grep -Eq '(^|[;&|( ])sleep[[:space:]]+[0-9.]' || exit 0
printf '%s' "$flat" | grep -Eq '/tasks/[A-Za-z0-9_-]+\.output' || exit 0

STATE_DIR="$HOME/.claude/hooks/state"
mkdir -p "$STATE_DIR" 2>/dev/null || true
find "$STATE_DIR" -type f -name 'task-sleep-poll-*' -mtime +7 -delete 2>/dev/null || true

transcript_path=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
session_id_field=$(printf '%s' "$input" | jq -r '.session_id // empty')
if [[ -n "$transcript_path" ]]; then
  session_marker=$(basename "$transcript_path" .jsonl)
elif [[ -n "$session_id_field" ]]; then
  session_marker="$session_id_field"
else
  session_marker=""
fi

if [[ -n "$session_marker" && -f "$STATE_DIR/task-sleep-poll-$session_marker" ]]; then
  exit 0
fi
[[ -n "$session_marker" ]] && touch "$STATE_DIR/task-sleep-poll-$session_marker" 2>/dev/null || true

read -r -d '' reason <<'EOF' || true
You don't have to wait for that. Background tasks wake you when they exit.

Launch it, then go do something else — read the file you're about to change, write the
next script, answer the question you're holding. The completion notification arrives on
its own and carries the output path with it. Sleeping is buying time you already have.

It is also worse than doing nothing, in three ways one session measured on itself:

  - the poll is bounded by the Bash timeout, not by the job. Two of its waits hit the
    600 s ceiling and came back empty, having watched a job that had exited ten minutes
    earlier — 20 minutes of dead wait, no output.
  - `sleep 180; cat .../tasks/x.output` pays the full 180 s even when the job took 12.
  - a `| tail -4` on the polled output throws away the start of the log, which is where
    the build lock prints whether anything else was competing for the cores. A run whose
    banner you truncated is a timing you cannot interpret.

If you genuinely need to block until something finishes — the very next thing you do
depends on it and nothing else can usefully happen — say so and run it in the
foreground. That is honest and it is bounded by the job.

Sleeping on something the harness does NOT track is fine and this guard ignores it: a CI
run, a deploy, a port coming up, another agent's lock file. It only stops you polling a
task file the harness created for you and is already watching.
EOF

jq -n --arg reason "$reason" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": $reason
  }
}'
exit 0
