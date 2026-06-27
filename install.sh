#!/usr/bin/env bash
# Wire this repo's Claude Code customizations into ~/.claude.
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
