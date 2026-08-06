#!/usr/bin/env bash
# Reap Claude CLI forks still running after the turn that spawned them.
#
# A helper fork carries `--fork-session` and `--no-session-persistence`, resumes
# a session id, and leaves `--tools` and `--setting-sources` empty. A windowed
# session carries `--replay-user-messages`, `--include-partial-messages` and
# `--permission-prompt-tool`, and carries neither fork flag. Both members of a
# session's process pair — the `disclaimer` wrapper and the `claude` it execs —
# carry the same argv.
#
# `is_candidate` holds the tests and echoes `take` or the test that spared the
# pid. A pid on this hook's own ancestor chain is spared. An ancestor chain
# shorter than two entries spares every pid.
#
# Wired on SessionStart. A fork runs with `--setting-sources=` empty and loads
# no user settings.
#
# stdout stays empty — a SessionStart hook's stdout is injected as context. A
# sweep reports on stderr. Exits 0 on every path.
#
# HSM_REAP_DRY_RUN=1, or `--dry-run`, reports and signals nothing.
# HSM_REAP_MIN_AGE_S sets the age floor, HSM_REAP_MAX_CPU the cpu ceiling.
#
# Diagnostic log: one JSONL line per invocation at
# $HOME/.claude/hooks/logs/reap-forks.jsonl, carrying every candidate examined
# and the verdict on it.

set -uo pipefail

LOG_FILE="$HOME/.claude/hooks/logs/reap-forks.jsonl"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

MIN_AGE_S="${HSM_REAP_MIN_AGE_S:-600}"
MAX_CPU="${HSM_REAP_MAX_CPU:-1.0}"
DRY_RUN="${HSM_REAP_DRY_RUN:-0}"
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

CLI_RE='claude-code/[^ ]*/claude\.app/Contents/MacOS/claude'

log_line() {
  jq -nc --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg status "$1" \
         --argjson min_age "$MIN_AGE_S" --arg took "$2" --argjson examined "$3" \
         '{ts:$ts, status:$status, min_age_s:$min_age, took:$took, examined:$examined}' \
     >> "$LOG_FILE" 2>/dev/null || true
}

# This hook's own ancestor chain: the shell, the session that ran the hook, its
# disclaimer wrapper, the app. /usr/bin/env bash here is 3.2, so a space-
# delimited string rather than a set.
SELF_PIDS=""
p=$$
while [[ -n "$p" && "$p" != "0" && "$p" != "1" ]]; do
  SELF_PIDS="$SELF_PIDS $p"
  p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
done
SELF_DEPTH=$(echo $SELF_PIDS | wc -w | tr -d ' ')

if (( SELF_DEPTH < 2 )); then
  log_line "self_chain_unavailable" "" '[]'
  exit 0
fi

on_self_chain() { [[ " $SELF_PIDS " == *" $1 "* ]]; }

is_fork_argv() { [[ "$1" == *--fork-session* && "$1" == *--no-session-persistence* ]]; }

# etime is [[dd-]hh:]mm:ss; darwin ps has no etimes.
age_seconds() {
  local e="$1" d=0 h=0 m s parts
  [[ "$e" == *-* ]] && { d="${e%%-*}"; e="${e#*-}"; }
  IFS=: read -ra parts <<<"$e"
  case "${#parts[@]}" in
    3) h="${parts[0]}"; m="${parts[1]}"; s="${parts[2]}" ;;
    2) m="${parts[0]}"; s="${parts[1]}" ;;
    *) echo 0; return ;;
  esac
  echo $(( 10#$d * 86400 + 10#$h * 3600 + 10#$m * 60 + 10#$s ))
}

# $1 pid, $2 cpu, $3 etime, $4 argv
is_candidate() {
  local pid="$1" cpu="$2" etime="$3" cmd="$4" age kids k kcmd

  on_self_chain "$pid"                             && { echo "self_ancestor"; return; }
  [[ "$cmd" =~ $CLI_RE ]]                          || { echo "not_claude_cli"; return; }
  is_fork_argv "$cmd"                              || { echo "not_a_fork"; return; }
  [[ "$cmd" == *--replay-user-messages* ]]         && { echo "has_window"; return; }
  [[ "$cmd" == *--include-partial-messages* ]]     && { echo "has_window"; return; }
  [[ "$cmd" == *--permission-prompt-tool* ]]       && { echo "has_window"; return; }

  age=$(age_seconds "$etime")
  (( age >= MIN_AGE_S ))                           || { echo "too_young"; return; }

  awk -v c="$cpu" -v m="$MAX_CPU" 'BEGIN{exit !(c < m)}' || { echo "busy"; return; }

  kids=$(pgrep -P "$pid" 2>/dev/null | tr '\n' ' ')
  for k in $kids; do
    kcmd=$(ps -o command= -p "$k" 2>/dev/null)
    is_fork_argv "$kcmd" || { echo "has_children"; return; }
  done

  echo "take"
}

TAKE=()
EXAMINED='[]'

while IFS= read -r line; do
  [[ "$line" =~ ^[[:space:]]*([0-9]+)[[:space:]]+([0-9]+)[[:space:]]+([0-9.]+)[[:space:]]+([^[:space:]]+)[[:space:]]+(.*)$ ]] || continue
  pid="${BASH_REMATCH[1]}"; ppid="${BASH_REMATCH[2]}"
  cpu="${BASH_REMATCH[3]}"; etime="${BASH_REMATCH[4]}"; cmd="${BASH_REMATCH[5]}"

  [[ "$cmd" == *--fork-session* ]] || continue

  verdict=$(is_candidate "$pid" "$cpu" "$etime" "$cmd")
  EXAMINED=$(jq -c --argjson pid "$pid" --argjson ppid "$ppid" --arg cpu "$cpu" \
                  --arg etime "$etime" --arg verdict "$verdict" \
                  '. + [{pid:$pid, ppid:$ppid, cpu:$cpu, etime:$etime, verdict:$verdict}]' \
             <<<"$EXAMINED" 2>/dev/null) || EXAMINED='[]'
  [[ "$verdict" == "take" ]] && TAKE+=("$pid")
done < <(ps -Ao pid=,ppid=,pcpu=,etime=,command= 2>/dev/null)

if (( ${#TAKE[@]} == 0 )); then
  log_line "nothing_to_reap" "" "$EXAMINED"
  exit 0
fi

if [[ "$DRY_RUN" == "1" ]]; then
  echo "reap-abandoned-forks: would take ${#TAKE[@]} abandoned fork process(es): ${TAKE[*]}" >&2
  log_line "dry_run" "${TAKE[*]}" "$EXAMINED"
  exit 0
fi

for pid in "${TAKE[@]}"; do kill -TERM "$pid" 2>/dev/null; done
sleep 2
for pid in "${TAKE[@]}"; do kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null; done

STILL=()
for pid in "${TAKE[@]}"; do kill -0 "$pid" 2>/dev/null && STILL+=("$pid"); done

echo "reap-abandoned-forks: cleared ${#TAKE[@]} abandoned fork process(es) from an earlier session" >&2
if (( ${#STILL[@]} > 0 )); then
  echo "reap-abandoned-forks: survived: ${STILL[*]}" >&2
  log_line "reaped_partial" "${TAKE[*]}" "$EXAMINED"
else
  log_line "reaped" "${TAKE[*]}" "$EXAMINED"
fi

exit 0
