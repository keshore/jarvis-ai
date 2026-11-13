# Roadmap

Done: brief/full by voice, barge-in, wake word, focus-follows-voice, optional local LLM (mlx / Ollama), portable STT/TTS backends,
session registry, `localvoice-ai run` for any CLI, Claude Code plugin with automatic start.

Next:
1. (PyPI done) Homebrew tap.
2. Exercise and fix the audio path on Linux, Intel Macs and Windows (CI covers only the portable logic today).
3. Silero VAD instead of the volume threshold; real echo cancellation (macOS voice-processing I/O, WebRTC AEC elsewhere).
4. MCP server (`localvoice-ai mcp`) so Cursor, Copilot, Codex and others can call `speak` natively.
5. Adapters verified against Codex, Gemini CLI and Copilot CLI hooks; reading replies from GUI chat apps (accessibility APIs).
6. Spoken announcements (needs input, task finished); voice approval of prompts with strict phrases.
