---
name: localvoice
description: Turn fully local, hands-free voice on or off for this session (speech in via local Whisper, speech out via local Kokoro). Nothing leaves the machine.
disable-model-invocation: true
argument-hint: "[off | status | big | small]"
allowed-tools: Bash(localvoice:*)
---

Run only the commands below and show their output verbatim, nothing else.

- No argument, `on`, `small` or `big`: run `localvoice enable "$CLAUDE_CODE_SESSION_ID"` and then `localvoice start --model <small|big>` (default `small`).
- `off`: run `localvoice disable "$CLAUDE_CODE_SESSION_ID" --stop-when-idle`.
- `status`: run `localvoice status`.

If `$ARGUMENTS` is anything else, run nothing and list these options. Add no commentary and edit no files.
