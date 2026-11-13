# Roadmap

Nothing below is released yet: everything since 0.3.1 lives on `main` and ships together as the first `jarvis-ai` release.

**Built**
- Ears and voice: Whisper, Kokoro, neural voice detection, echo cancellation, barge-in.
- Sessions found without a plugin (Claude Code), replies read from transcripts, any terminal or app on macOS, tmux anywhere.
- "Jarvis, ..." commands: list, switch, status, read, ask (with approval), open a session (with approval).
- Loose wording through an optional local model (MLX, Ollama, any OpenAI-compatible server), checked by plain code.
- Approval gate with an audit log. The model proposes; only you approve.

**Next**
1. Connectors for more agents (Codex, Gemini CLI, Copilot CLI) and for the Claude desktop app's own sessions.
2. A small status window: what Jarvis heard, open sessions, pending approval.
3. Audio verified on Linux, Intel Macs and Windows (CI covers the portable logic only).
4. Start at login without the plugin; Homebrew tap.
5. Announcements ("the portal session needs your input"), auto-calibrated echo delay, prebuilt echo-canceller wheels.
6. MCP server so agents can call `speak` themselves.
