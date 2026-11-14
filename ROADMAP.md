# Roadmap

Nothing below is released yet: everything since 0.3.1 lives on `main` and ships together as the first `jarvis-ai` release.

**Direction (2026-11):** Jarvis is its own assistant, like Siri: local ears and voice, a brain that is either a local model or a
cloud service you give a key for, its own window, and no tools for now. Driving other agents' sessions is switched off.

**Next for the assistant**
1. A packaged app with an installer per system, so no command line is needed (the window is a browser page today).
2. More brains: GitHub Copilot and other sign-ins, where their terms allow it.
3. Tools, one at a time, each behind the approval gate.
4. Answers that start sooner with the local model (it answers in one piece today; Claude streams).

**Built**
- Ears and voice: Whisper, Kokoro, neural voice detection, echo cancellation, barge-in.
- Sessions found by themselves (Claude Code), replies read from transcripts, any terminal or app on macOS, tmux anywhere.
- "Jarvis, ..." commands: list, switch, status, read, ask (with approval), open a session (with approval).
- Loose wording through an optional local model (MLX, Ollama, any OpenAI-compatible server), checked by plain code.
- Approval gate with an audit log. The model proposes; only you approve.
- Announcements when a background session finishes; start at login (`jarvis-ai login on`).

**Next**
1. Connectors for more agents (Codex, Gemini CLI, Copilot CLI) and for the Claude desktop app's own sessions.
2. A small status window: what Jarvis heard, open sessions, pending approval.
3. Audio verified on Linux, Intel Macs and Windows (CI covers the portable logic only).
4. Homebrew tap; start at login verified across a real login on each system.
5. An announcement when a session waits for your permission; auto-calibrated echo delay, prebuilt echo-canceller wheels.
