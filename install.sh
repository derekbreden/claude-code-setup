#!/usr/bin/env bash
# Wire this repo's Claude Code and Codex customizations into their clients.
#
# This is the single place that registers everything touching ~/.claude, so the
# convention can't drift: add an artifact, register it here. Re-runnable.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1) Slash commands MUST live under ~/.claude/commands/ (no settings entry exists
#    for them), so symlink each tracked command file into place.
mkdir -p "$HOME/.claude/commands"
for cmd in "$REPO"/jsonl2md/commands/*.md; do
  [ -e "$cmd" ] || continue
  ln -sfn "$cmd" "$HOME/.claude/commands/$(basename "$cmd")"
  echo "command  -> ~/.claude/commands/$(basename "$cmd")"
done

# 2) Hooks are referenced by ABSOLUTE PATH from ~/.claude/settings.json (there is
#    no ~/.claude/hooks/ auto-load). This script keeps them executable and prints
#    the base path to use; it does not rewrite the hand-curated settings.json.
chmod +x "$REPO"/hooks/*.sh 2>/dev/null || true
echo
echo "hooks live at: $REPO/hooks/"
echo "reference them in ~/.claude/settings.json as:  $REPO/hooks/<name>.sh"

# 3) Codex discovers personal skills under ~/.codex/skills/. Keep the tracked
#    source here and expose the directory itself, so edits take effect without a
#    copied installation drifting away from the repo.
mkdir -p "$HOME/.codex/skills"
ln -sfn "$REPO/codex/skills/relay" "$HOME/.codex/skills/relay"
echo
echo "skill    -> ~/.codex/skills/relay"

# 4) The cloud inbox watcher is a LaunchAgent: it tails every live cloud session
#    and delivers their <relay to=…> marks into local sessions, so it has to be
#    up whenever the Mac is, not only while some session remembers to run it.
#    The plist is rendered from the tracked template (launchd resolves nothing
#    itself: no $HOME, no PATH lookup) and (re)bootstrapped in the login domain.
LABEL="com.derekbredensteiner.relay-cloud-inbox"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
# The interpreter must import `cryptography` (the desktop token cache is
# decrypted with it); the first python3 on PATH is not always the one that can.
PYTHON=""
for candidate in /opt/homebrew/bin/python3 "$(command -v python3)" /usr/local/bin/python3 /usr/bin/python3; do
  if [ -x "$candidate" ] && "$candidate" -c "import cryptography" 2>/dev/null; then PYTHON="$candidate"; break; fi
done
[ -n "$PYTHON" ] || { echo "no python3 with the cryptography module found; pip install cryptography" >&2; exit 1; }
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.jsonl2md/cloud"
sed -e "s|__PYTHON__|$PYTHON|g" -e "s|__REPO__|$REPO|g" -e "s|__HOME__|$HOME|g" \
  "$REPO/launchd/$LABEL.plist.in" > "$PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo
echo "agent    -> $PLIST  (log: ~/.jsonl2md/cloud/inbox.log)"
