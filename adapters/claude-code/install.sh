#!/bin/bash
# Installs the /localvoice skill and merges the three hooks into ~/.claude/settings.json (existing hooks are kept).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
command -v localvoice >/dev/null || { echo "install localvoice first (see top-level README)"; exit 1; }
command -v jq >/dev/null || { echo "jq is required (brew install jq)"; exit 1; }
mkdir -p "$HOME/.claude/skills/localvoice"
cp "$HERE/skills/localvoice/SKILL.md" "$HOME/.claude/skills/localvoice/SKILL.md"
S="$HOME/.claude/settings.json"; [ -f "$S" ] || echo '{}' > "$S"
cp "$S" "$S.bak"
LV="$(command -v localvoice)"   # absolute path: hooks must not depend on PATH
HOOKS="$(sed "s#\"localvoice #\"$LV #" "$HERE/hooks.json")"
jq --argjson add "[$HOOKS]" '
  .hooks = ((.hooks // {}) as $cur
    | reduce ($add[0].hooks | to_entries[]) as $e ($cur;
        .[$e.key] = ((.[$e.key] // []) + $e.value | unique_by(.hooks[0].command))))' "$S.bak" > "$S"
echo "Installed. Restart Claude Code, then type /localvoice. (backup: $S.bak)"
