#!/usr/bin/env bash
# Flag residue (justification, defense, decision narrative) in files that were
# written or edited. Runs after the write lands, so the note arrives as context
# rather than a denial — the edit is on disk and the agent revises it. Fail-open
# on any error.
#
# Three stages, each narrowing at a lower cost than the next:
#   1. regex pre-filter on the new content — lenient, tuned for recall
#   2. Haiku on a ±600 char window around the first match — yes/no
#   3. Opus 5 on the whole file, reading the calibration sources themselves —
#      returns the spans that earned the flag and its own reading of them, and
#      can overturn stage 2. An overturned flag emits nothing and does not
#      spend the session's one warning.
#
# Stage 3 is what the agent receives. Stages 1 and 2 decide whether to pay for
# it; a bare stage-2 verdict reaches an agent only when stage 3 fails.
#
# Residue = the author going beyond describing what is, to explain, defend, or
# narrate. See $HOME/Developer/homesodamachine/calibration/Principle.md for the
# discipline; principle/You.md and principle/Framing.md alongside it carry the
# live calibration the principle is distilled from.
#
# Diagnostic log: every invocation appends one JSONL line to
# $HOME/.claude/hooks/logs/residue.jsonl with a "status" field.

set -euo pipefail

CALIBRATION_DIR="$HOME/Developer/homesodamachine/calibration"
LOG_FILE="$HOME/.claude/hooks/logs/residue.jsonl"
WARNED_DIR="$HOME/.claude/hooks/state"
mkdir -p "$(dirname "$LOG_FILE")" "$WARNED_DIR" 2>/dev/null || true

log_status() {
  local status="$1"
  local extra_json="${2:-null}"
  local ts
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  {
    if [[ "$extra_json" == "null" ]]; then
      jq -nc --arg ts "$ts" --arg status "$status" '{ts: $ts, status: $status}'
    else
      jq -nc --arg ts "$ts" --arg status "$status" --argjson extra "$extra_json" '{ts: $ts, status: $status} + $extra'
    fi
  } >> "$LOG_FILE" 2>/dev/null || true
}

# Bail if the calibration files aren't where we'd point the agent.
if [[ ! -f "$CALIBRATION_DIR/Principle.md" ]]; then
  log_status "no_calibration_files"
  exit 0
fi

input=$(cat)
tool_name=$(printf '%s' "$input" | jq -r '.tool_name // empty')
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.notebook_path // empty')

# Per-session loop guard. The hook bothers an agent once per session; after
# that the marker file is in place and subsequent residue writes pass
# through. Session is identified by the transcript path basename (the
# session UUID), falling back to a session_id field if that's not present.
transcript_path=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
session_id_field=$(printf '%s' "$input" | jq -r '.session_id // empty')
if [[ -n "$transcript_path" ]]; then
  session_marker=$(basename "$transcript_path" .jsonl)
elif [[ -n "$session_id_field" ]]; then
  session_marker="$session_id_field"
else
  session_marker=""
fi

if [[ -n "$session_marker" && -f "$WARNED_DIR/residue-warned-$session_marker" ]]; then
  log_status "already_warned_this_session" "$(jq -nc --arg sid "$session_marker" '{session: $sid}')"
  exit 0
fi

# Extract the content being written/edited.
#   Write       -> tool_input.content
#   Edit        -> tool_input.new_string
#   MultiEdit   -> concatenation of tool_input.edits[].new_string
#   NotebookEdit-> tool_input.new_source
case "$tool_name" in
  Write)
    new_content=$(printf '%s' "$input" | jq -r '.tool_input.content // empty')
    ;;
  Edit)
    new_content=$(printf '%s' "$input" | jq -r '.tool_input.new_string // empty')
    ;;
  MultiEdit)
    new_content=$(printf '%s' "$input" | jq -r '.tool_input.edits // [] | map(.new_string // "") | join("\n")')
    ;;
  NotebookEdit)
    new_content=$(printf '%s' "$input" | jq -r '.tool_input.new_source // empty')
    ;;
  *)
    log_status "wrong_tool" "$(jq -nc --arg tool "$tool_name" '{tool: $tool}')"
    exit 0
    ;;
esac

# Skip the calibration files themselves — they contain residue-vocabulary by
# nature and shouldn't trigger the hook that points at them.
case "$file_path" in
  */calibration/*)
    log_status "skipped_calibration" "$(jq -nc --arg file "$file_path" '{file: $file}')"
    exit 0
    ;;
esac

# Skip project memory. The repo describes what is; memory is where the why and
# the provenance go — which surfaces Derek fitted by hand, which an agent
# invented, what he said before it reached the tree — so it carries rationale
# by design.
case "$file_path" in
  "$HOME"/.claude/projects/*/memory/*)
    log_status "skipped_memory" "$(jq -nc --arg file "$file_path" '{file: $file}')"
    exit 0
    ;;
esac

# Skip binary / structured files where residue-prevention doesn't apply.
case "$file_path" in
  *.dxf|*.png|*.jpg|*.jpeg|*.gif|*.svg|*.pdf|*.bin|*.zip|*.tar|*.gz|*.3mf|*.stl|*.obj|*.json|*.lock|*.toml|*.yaml|*.yml)
    log_status "skipped_non_prose" "$(jq -nc --arg file "$file_path" '{file: $file}')"
    exit 0
    ;;
esac

if [[ -z "$new_content" || ${#new_content} -lt 60 ]]; then
  log_status "empty_or_short" "$(jq -nc --argjson len "${#new_content}" '{len: $len}')"
  exit 0
fi

# Strip backtick-delimited spans (fenced blocks and inline code) before pattern
# matching. Documentation quoting trigger patterns should not classify as
# residue. Stage 2 gets the unstripped text, so a span it quotes is a substring
# of what is on disk.
raw_new_content="$new_content"
new_content=$(printf '%s' "$new_content" | perl -0pe 's/```.*?```//gs; s/`[^`\n]+`//g' 2>/dev/null || printf '%s' "$new_content")
if [[ -z "$new_content" || ${#new_content} -lt 60 ]]; then
  log_status "empty_after_strip"
  exit 0
fi

# Pre-filter: cheap regex for candidate residue surface forms.
#   - history narrative: previously, originally, used to be, switched from,
#     changed from, moved away from, no longer
#   - decision narrative: we chose / considered / rejected / decided, the
#     rationale, the reason(s) is/are/why/for, the reasoning behind, chosen /
#     selected / picked because, intentionally [verb], deliberately [verb]
#   - defense against alternatives: rather than (verb|article), instead of
#     (verb|article), alternatives considered / ruled out / rejected, designs
#     considered / ruled out / rejected, trade-off, not a compromise / substitute,
#     because the alternative, specifically so, would otherwise
#   - claim of rightness: is the right / correct X
#   - stale value kept beside its replacement: superseded, a rough/early
#     estimate that something later replaced (was X, now Y) — not honest
#     provisional values (TBD, open item), which are clutter, not residue
# The pattern is intentionally lenient — false positives are cheap (one Haiku
# call) but false negatives are silent slips. Extend when the log shows
# something getting past. Recent additions: replaces, former (the former
# X), there is/are no <X>, not a <X> choice.
pattern='([Pp]reviously|[Oo]riginally|[Uu]sed[ \-]+to[ \-]+(be|use|have|do|exist)|[Ss]witched[ \-]+from|[Cc]hanged[ \-]+from|[Mm]oved[ \-]+away[ \-]+from|[Nn]o[ \-]+longer|[Ww]e[ \-]+(chose|considered|rejected|decided)|[Tt]he[ \-]+rationale|[Rr]ather[ \-]+than[ \-]+(using|having|going[ \-]+with|choosing|doing|the|a|an)|[Ii]nstead[ \-]+of[ \-]+(using|having|going[ \-]+with|choosing|the|a|an)|[Aa]lternatives?[ \-]+(considered|ruled[ \-]+out|rejected)|[Dd]esigns?[ \-]+(considered|ruled[ \-]+out|rejected)|[Tt]rade[ \-]?offs?|[Nn]ot[ \-]+a[ \-]+(compromise|substitute)|[Bb]ecause[ \-]+the[ \-]+alternative|[Tt]he[ \-]+reasoning[ \-]+behind|[Tt]he[ \-]+(reason|reasons)[ \-]+(is|are|why|for)|[Cc]hosen[ \-]+because|[Ss]elected[ \-]+because|[Pp]icked[ \-]+because|[Ii]ntentionally[ \-]+[[:alpha:]]+|[Dd]eliberately[ \-]+[[:alpha:]]+|[Ss]pecifically[ \-]+so[ \-]+[[:alpha:]]|[Ii]s[ \-]+the[ \-]+(right|correct)[ \-]+[[:alpha:]]|[Ww]ould[ \-]+otherwise|[Ss]uperseded|[Rr]eplaces[ \-]|[ \-][Ff]ormer|[Tt]here[ \-]+(is|are|was|were)[ \-]+no[ \-]|[Nn]ot[ \-]+a[ \-]+[[:alpha:]/]+[ \-]+choice|([Rr]ough|[Ee]arly|[Ii]nitial|[Pp]reliminary|[Bb]allpark|[Ff]irst[ \-]?pass)[ \-]+estimate)'

if ! printf '%s\n' "$new_content" | grep -qE "$pattern"; then
  log_status "regex_no_match" "$(jq -nc --argjson len "${#new_content}" '{len: $len}')"
  exit 0
fi

# Window: ±600 chars around the first match position. Position-based rather
# than line-based, so very long unbroken paragraphs still get the match in view.
window=$(printf '%s' "$new_content" | awk -v pat="$pattern" '
  { full = full $0 "\n" }
  END {
    if (match(full, pat)) {
      start = RSTART - 600
      if (start < 1) start = 1
      end = RSTART + RLENGTH + 600
      if (end > length(full)) end = length(full)
      print substr(full, start, end - start + 1)
    }
  }
')

api_key_file="$HOME/.claude/anthropic_api_key"
if [[ ! -f "$api_key_file" ]]; then
  log_status "no_api_key"
  exit 0
fi
api_key=$(cat "$api_key_file")

classification_prompt='You will see a snippet from a file an AI assistant is about to write or edit. Classify whether the snippet contains RESIDUE — the author going beyond describing what currently is, to explain, defend, justify, or narrate.

- residue = explains WHY something is the way it is by reference to alternatives that were rejected, decisions that were made, or how it came to be; OR keeps a stale value alongside the one that replaced it — the old number kept beside the new, a value marked superseded or a rough/early estimate that something later replaced (the "was X, now Y" pattern). Goes beyond present-tense description into justification, defense, or history. (An honest provisional value with nothing stale kept beside it — "dimensions TBD", "rough estimate $50 pending the quote", an "open item" — is clutter, not residue: classify it describing.) Examples:
  - "We chose to ship the umbilical pre-assembled rather than separately because customers would otherwise have to thread tubes through the shank"
  - "Designs ruled out: split halves, living hinge, C-clip, tab-and-slot"
  - "Previously the plate was solid; switching to open channels lets the customer slide it on"
  - "This is not a compromise — it is the same product as a can"
  - "The rationale is that the customer needs to install one-handed"
  - "Quoted $9/part (rough early estimate, superseded by the $27.83 quote below)"

- describing = states facts, motion, or geometry without defending or justifying. Words like "rather than", "previously", or "originally" can appear here without being residue if they describe what is, not defend a choice. Examples:
  - "The rim arc extends counterclockwise rather than clockwise"
  - "The plate slides laterally from below onto the dangling umbilical"
  - "Originally signed by the manufacturer at the factory"
  - "Each cylinder seats in its terminal pocket"

Reply with exactly one word: residue or describing.

Snippet:
'

body=$(jq -n \
  --arg model "claude-haiku-4-5" \
  --arg prompt "$classification_prompt" \
  --arg msg "$window" \
  '{
    model: $model,
    max_tokens: 10,
    messages: [{role: "user", content: ($prompt + $msg)}]
  }')

response=$(curl -sS https://api.anthropic.com/v1/messages \
  -H "x-api-key: $api_key" \
  -H "content-type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  --max-time 8 \
  -d "$body" 2>/dev/null || echo '{}')

# Take the first verdict word that appears. Asked for one word, Haiku sometimes
# runs on past it, and max_tokens cuts it mid-sentence — an equality test drops
# that reply on the floor as neither verdict.
classification=$(printf '%s' "$response" | jq -r '.content[0].text // empty' | tr '[:upper:]' '[:lower:]' | grep -oE 'residue|describing' | head -1 || true)

if [[ -z "$classification" ]]; then
  log_status "haiku_no_response"
  exit 0
fi
if [[ "$classification" != "residue" ]]; then
  log_status "allowed" "$(jq -nc --arg classification "$classification" '{classification: $classification}')"
  exit 0
fi

# ---------------------------------------------------------------------------
# Stage 3 — Opus 5, against the whole file and the calibration sources.
# ---------------------------------------------------------------------------

FILE_MAX=60000

cal_block=""
for cal_f in "Principle.md" "principle/Framing.md" "principle/You.md"; do
  if [[ -f "$CALIBRATION_DIR/$cal_f" ]]; then
    cal_block="${cal_block}=== ${cal_f} ===
$(cat "$CALIBRATION_DIR/$cal_f")

"
  fi
done

file_block=""
file_note=""
if [[ -n "$file_path" && -f "$file_path" ]]; then
  file_bytes=$(wc -c < "$file_path" 2>/dev/null | tr -d ' ' || echo 0)
  if [[ "$file_bytes" =~ ^[0-9]+$ ]] && (( file_bytes > FILE_MAX )); then
    file_block=$(head -c "$FILE_MAX" "$file_path" 2>/dev/null || true)
    file_note=" [truncated to the first $FILE_MAX of $file_bytes bytes]"
  else
    file_block=$(cat "$file_path" 2>/dev/null || true)
  fi
else
  file_note=" [not readable from disk; only the edit is shown]"
fi

opus_instructions='A cheap classifier flagged the edit below as RESIDUE in this repo. You are the check on that.

Two jobs:
  1. Confirm or overturn the flag.
  2. If you confirm, name the exact text that earned it, and give the agent your own reading of what that text does.

The calibration is the source. Read it as the conversations it is, not as a rule to apply — its own claim is that the lesson lives in the rooms and not in any summary of them, and that includes any summary you are about to write.

Anchor on <edit>: that is what the agent just wrote and what the flag is about. <file> is context — text there that the edit did not write is not the agent'"'"'s to answer for right now.

Reply with JSON and nothing else:
{
  "verdict": "residue" | "describing",
  "spans": ["...", "..."],
  "analysis": "..."
}

  spans   — verbatim substrings of <edit>, copied exactly, each the smallest
            piece of text that earns the flag. At most 6. Omit when the verdict
            is describing.
  analysis — your own reading, addressed to the agent in second person. Say what
            these spans do to someone reading this file cold. You are one reader
            working from one window into this repo: name where you are unsure,
            and do not write a complete-feeling account of the file — the agent
            still has to look at what you did not name, and an account that
            feels finished is the exact failure the calibration describes. Under
            250 words. Prose, no headings, no bullet list.

Overturn freely. The pre-filter is tuned to over-fire, and honest present-tense
description that happens to contain a trigger phrase is describing.'

opus_body=$(jq -n \
  --arg model "claude-opus-5" \
  --arg instr "$opus_instructions" \
  --arg cal "$cal_block" \
  --arg fpath "${file_path}${file_note}" \
  --arg fbody "$file_block" \
  --arg edit "$raw_new_content" \
  '{
    model: $model,
    max_tokens: 16000,
    messages: [{role: "user", content: (
      $instr
      + "\n\n<calibration>\n" + $cal + "</calibration>\n\n"
      + "<file path=\"" + $fpath + "\">\n" + $fbody + "\n</file>\n\n"
      + "<edit>\n" + $edit + "\n</edit>\n"
    )}]
  }' 2>/dev/null || echo '')

opus_verdict=""
opus_spans=""
opus_analysis=""
opus_fail=""

if [[ -z "$opus_body" ]]; then
  opus_fail="body_build_failed"
else
  opus_response=$(curl -sS https://api.anthropic.com/v1/messages \
    -H "x-api-key: $api_key" \
    -H "content-type: application/json" \
    -H "anthropic-version: 2023-06-01" \
    --max-time 55 \
    -d "$opus_body" 2>/dev/null || echo '{}')

  opus_text=$(printf '%s' "$opus_response" | jq -r '[.content[]? | select(.type == "text") | .text] | join("")' 2>/dev/null || echo '')
  opus_stop=$(printf '%s' "$opus_response" | jq -r '.stop_reason // empty' 2>/dev/null || echo '')
  # Slice from the first brace to the last, so a fence or a sentence of preamble
  # around the object doesn't cost the reading.
  opus_json=$(printf '%s' "$opus_text" | perl -0ne 's/\A[^{]*//s; s/[^}]*\z//s; print' 2>/dev/null || printf '%s' "$opus_text")

  if [[ -z "$opus_json" ]] || ! printf '%s' "$opus_json" | jq -e 'type == "object"' >/dev/null 2>&1; then
    if [[ "$opus_stop" == "max_tokens" ]]; then
      opus_fail="truncated"
    else
      opus_fail="unparseable"
    fi
  else
    opus_verdict=$(printf '%s' "$opus_json" | jq -r '.verdict // empty' | tr -d '[:space:].' | tr '[:upper:]' '[:lower:]')
    opus_spans=$(printf '%s' "$opus_json" | jq -r '[.spans // [] | .[] | "  - " + (. | tostring)] | join("\n")' 2>/dev/null || echo '')
    opus_analysis=$(printf '%s' "$opus_json" | jq -r '.analysis // empty' 2>/dev/null || echo '')
    if [[ "$opus_verdict" != "residue" && "$opus_verdict" != "describing" ]]; then
      opus_fail="no_verdict"
    fi
  fi
fi

# Overturned. Nothing is emitted and the session keeps its one warning.
if [[ -z "$opus_fail" && "$opus_verdict" == "describing" ]]; then
  log_status "overturned" "$(jq -nc --arg file "$file_path" --arg session "$session_marker" '{file: $file, session: $session, stage1: "residue", stage3: "describing"}')"
  exit 0
fi

# Garbage-collect stale per-session warned markers (older than 7 days). The
# markers are empty files, but the directory shouldn't grow without bound.
# Runs here rather than at entry: the directory only grows on the path that
# writes a marker, and every invocation paid for the sweep at entry.
find "$WARNED_DIR" -type f -name 'residue-warned-*' -mtime +7 -delete 2>/dev/null || true
# Mark this session as warned. Subsequent residue writes in the same
# session will pass through — the agent has the calibration context now
# and the decision is theirs.
if [[ -n "$session_marker" ]]; then
  touch "$WARNED_DIR/residue-warned-$session_marker" 2>/dev/null || true
fi

read_the_source="Read $CALIBRATION_DIR/Principle.md and the conversations it points at (principle/You.md and principle/Framing.md, alongside it)."

if [[ -n "$opus_fail" ]]; then
  log_status "flagged_stage3_failed" "$(jq -nc --arg file "$file_path" --arg session "$session_marker" --arg reason "$opus_fail" '{file: $file, session: $session, stage3_fail: $reason}')"
  context="The edit you just made was caught as residue, and it is already on disk. The reading that normally names the spans did not come back ($opus_fail), so this arrives with the verdict alone and nowhere in particular to look.

$read_the_source Then look at what you wrote and revise what needs revising — and if after reading you still want what you had, leave it.

This hook bothers you once per session, not twice."
else
  closing="$read_the_source Those are the source; the reading above is not. Then look at what you wrote and revise what needs revising — including text the second agent did not name, and including none of it, if after reading you still want what you had. The spans above are where one reader looked, not the bounds of what is there.

This hook bothers you once per session, not twice."
  log_status "flagged" "$(jq -nc --arg file "$file_path" --arg session "$session_marker" --argjson spans "$(printf '%s' "$opus_json" | jq -c '.spans // []')" --arg analysis "$opus_analysis" '{file: $file, session: $session, stage1: "residue", stage3: "residue", spans: $spans, analysis: $analysis}')"
  context="The edit you just made was caught as residue, and it is already on disk.

A second agent read this file against the calibration and marked these spans:

$opus_spans

Its reading — one agent's, not a ruling:

$opus_analysis

$closing"
fi

jq -n --arg ctx "$context" '{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": $ctx
  }
}'
