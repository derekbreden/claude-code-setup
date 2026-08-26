#!/usr/bin/env bash
# Block a stop that claims to be waiting on background work nothing is running.
# Stop and SubagentStop: if the turn's final message says it is holding, parked, or
# waiting for a job to report, and none of the background jobs THIS transcript
# launched is still alive, refuse the stop.
#
# Nothing wakes a stopped agent except a job exiting. An agent that stops believing
# it is waiting reports that belief in the same words a real wait would use. One
# night's fleet produced it five times across two agents:
#
#   "Holding for the background verification notification."   — job already reaped
#   "Holding for that notification now."                      — no job at all
#   "I'll pick this back up as soon as the background task reports completion."
#
# Each ended in a manager reading the observable state and sending a wake-up. From
# inside the agent, a dead job and a slow one are the same silence.
#
# A running background shell holds its own `tasks/<id>.output` open on fd 1 and 2: a
# live `sleep` shows two zsh and two sleep handles on it, a finished job shows none.
# That is the signal this hook reads, per job id named in the transcript.
#
# The regex gates whether the process check runs. No API call; it works offline.
#
# What passes: a wait on a person; a live subagent, seen by its JSONL's write
# recency; a tasks directory this hook cannot find; anything the regex does not
# match. A stop is refused only with a job-shaped wait in the text and no live
# process behind it.
#
# Diagnostic log: one JSONL line per invocation to
# $HOME/.claude/hooks/logs/unwatched-wait.jsonl, "status" naming the path taken.

set -uo pipefail

LOG_FILE="$HOME/.claude/hooks/logs/unwatched-wait.jsonl"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# A subagent JSONL written within this window is being written by a live agent. An
# agent mid-tool-call goes quiet for stretches, so the window is wide.
RECENT_S=180

log_status() {
  local status="$1" extra_json="${2:-null}" ts
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  {
    if [[ "$extra_json" == "null" ]]; then
      jq -nc --arg ts "$ts" --arg status "$status" '{ts: $ts, status: $status}'
    else
      jq -nc --arg ts "$ts" --arg status "$status" --argjson extra "$extra_json" \
        '{ts: $ts, status: $status} + $extra'
    fi
  } >> "$LOG_FILE" 2>/dev/null || true
}

input=$(cat)

# Loop guard — a revision attempt must be able to stop.
stop_hook_active=$(printf '%s' "$input" | jq -r '.stop_hook_active // false')
if [[ "$stop_hook_active" == "true" ]]; then
  log_status "loop_guard"
  exit 0
fi

transcript_path=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
if [[ -z "$transcript_path" || ! -f "$transcript_path" ]]; then
  log_status "no_transcript"
  exit 0
fi

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
last_text=$(python3 "$HOOK_DIR/_last_assistant_text.py" "$transcript_path")
read_rc=$?
if [[ $read_rc -eq 1 ]]; then
  log_status "no_assistant_message"
  exit 0
fi
[[ $read_rc -eq 2 ]] && log_status "stale_read"
if [[ -z "$last_text" ]]; then
  log_status "empty_text"
  exit 0
fi

# Strip code spans. A hook's own documentation, or a script that greps for these
# phrases, is not an agent claiming to wait.
stripped=$(printf '%s' "$last_text" \
  | perl -0pe 's/```.*?```//gs; s/`[^`\n]+`//g' 2>/dev/null || printf '%s' "$last_text")
[[ -n "$stripped" ]] && last_text="$stripped"

# A wait on a person ends the turn correctly — the user's next message wakes the
# session. Checked ahead of the job patterns, which "waiting for your call" also matches.
if printf '%s\n' "$last_text" | grep -qEi \
  '(wait(ing)?|hold(ing)?|stand(ing)? by|park(ed)?)[^.!?]{0,40}(on|for)[^.!?]{0,20}\b(you|your|Derek|the user|word from|a decision|confirmation|input|answer from you)\b'; then
  log_status "waiting_on_person"
  exit 0
fi

# Does the closing message claim a machine-shaped wait? Two halves must both appear:
# a parked posture, and a thing that is supposed to fire.
posture='(hold(ing)?|wait(ing)?|park(ed|ing)?|stopping here|stop(ping)? (here )?(rather than|with)|resum(e|ing)|pick (this|it) back up|no further (polling|action)|sole live background|nothing further queued|until (it|they|that) (reports?|lands?|finishes|completes?|fires?))'
object='(notification|notif|background (job|task|command|child|children)|tracked (wait|job)|bounded (job|wait)|completion|the build|the derive|the regen|verification|it to (report|land|finish|complete|fire|notify)|reports? back|wakes? me|wake-?up)'

if ! printf '%s\n' "$last_text" | grep -qEi "$posture"; then
  log_status "no_posture_match"
  exit 0
fi
if ! printf '%s\n' "$last_text" | grep -qEi "$object"; then
  log_status "no_object_match"
  exit 0
fi

matched=$(printf '%s\n' "$last_text" | grep -oEi "$posture[^.!?]{0,80}" | head -1)

# --- Locate this session's tasks directory -----------------------------------
# Background jobs launched by a SUBAGENT land in the PARENT session's tasks dir, so
# both transcript shapes resolve to the same place:
#   .../projects/<project>/<session>.jsonl
#   .../projects/<project>/<session>/subagents/agent-<id>.jsonl
if [[ "$transcript_path" == */subagents/agent-*.jsonl ]]; then
  session_dir=$(dirname "$(dirname "$transcript_path")")
  subagent_dir=$(dirname "$transcript_path")
else
  session_dir="${transcript_path%.jsonl}"
  subagent_dir="$session_dir/subagents"
fi
session_id=$(basename "$session_dir")
project_name=$(basename "$(dirname "$session_dir")")

tasks_dir=""
for cand in /private/tmp/claude-*/"$project_name"/"$session_id"/tasks \
            /tmp/claude-*/"$project_name"/"$session_id"/tasks; do
  [[ -d "$cand" ]] && { tasks_dir="$cand"; break; }
done
if [[ -z "$tasks_dir" ]]; then
  log_status "no_tasks_dir" "$(jq -nc --arg s "$session_id" '{session: $s}')"
  exit 0
fi

# --- Measure liveness ---------------------------------------------------------
# Only jobs this transcript launched. Sibling agents share the tasks directory.
# Newline-delimited rather than arrays: bash 3.2 is what /usr/bin/env bash resolves
# to here, so no mapfile, and an empty array is an unbound variable under set -u.
job_ids=$(grep -o 'Command running in background with ID: [A-Za-z0-9_-]\{1,\}' \
  "$transcript_path" 2>/dev/null | awk '{print $NF}' | sort -u)
job_count=0
[[ -n "$job_ids" ]] && job_count=$(printf '%s\n' "$job_ids" | grep -c .)

# A live background shell holds its output file open on stdout and stderr.
live_job=""
if [[ -n "$job_ids" ]]; then
  while IFS= read -r id; do
    [[ -n "$id" && -e "$tasks_dir/$id.output" ]] || continue
    if [[ -n "$(lsof -t -- "$tasks_dir/$id.output" 2>/dev/null | head -1)" ]]; then
      live_job="$id"; break
    fi
  done <<< "$job_ids"
fi

# A live subagent is live work too. Recency of its own transcript is the signal —
# it is being written continuously while the agent runs.
live_agent=""
if [[ -z "$live_job" && -d "$subagent_dir" ]]; then
  agent_ids=$(grep -o 'agentId: [A-Za-z0-9_-]\{1,\}' "$transcript_path" 2>/dev/null \
    | awk '{print $NF}' | sort -u)
  now=$(date +%s)
  if [[ -n "$agent_ids" ]]; then
    while IFS= read -r aid; do
      f="$subagent_dir/agent-$aid.jsonl"
      [[ -n "$aid" && -f "$f" ]] || continue
      mtime=$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null || echo 0)
      if (( now - mtime < RECENT_S )); then live_agent="$aid"; break; fi
    done <<< "$agent_ids"
  fi
fi

if [[ -n "$live_job" || -n "$live_agent" ]]; then
  log_status "allowed_live" "$(jq -nc --arg job "$live_job" --arg agent "$live_agent" \
    --arg m "$matched" '{live_job: $job, live_agent: $agent, matched: $m}')"
  exit 0
fi

log_status "blocked" "$(jq -nc --arg m "$matched" --argjson n "$job_count" \
  '{matched: $m, jobs_launched_this_transcript: $n}')"

read -r -d '' reason <<'EOF' || true
You are about to stop on a wait that nothing will end.

Your closing message says you are holding for something to report. Checked against the
running processes: none of the background jobs this transcript launched is alive. Their
output files have no process holding them open, which is what a finished, killed, or
never-started job looks like.

Nothing wakes a stopped agent except a job exiting. If you stop now, you do not wait —
you end, silently, believing otherwise, and the next thing that happens is a person or a
manager noticing you never came back.

This is not a judgment about your wording. It is the process table.

Do one of these instead:

  - Check the state yourself, now. Read the output file, sample the artifact, run the
    verification in the foreground. If the job died, its output says why; if it finished,
    the answer is already on disk and the wait was over before you asked for it.
  - Re-arm a real wait, and confirm it is real. Launch it with run_in_background and
    read the launch result — an id and an output path come back. That job exiting
    re-invokes you. A plain-text sentence that you are holding does not; it is the shape
    that failed here five times in one night across two agents.
  - Finish and report. If the work is done except for a confirmation you cannot get,
    say what stands, what is unverified, and stop on that. A turn that ends with a
    stated state is worth more than one that ends waiting for a bell that will not ring.

If you are genuinely waiting on something outside the harness — a peer's build lock, a
deploy, another session — say which, and say what will bring you back to it. A wait no
one can name is the one that never ends.
EOF

jq -n --arg reason "$reason" '{decision: "block", reason: $reason}'
exit 0
