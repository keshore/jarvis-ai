# Architecture

```
 mic -> listener (voice detection, echo cancellation, barge-in) -> Whisper (local)
                                                                   |
                                                                   v
                         assistant: the conversation, sentence-by-sentence speech, history
                                   |                      |
                     brain: local model | Claude | OpenAI   store: history.db (this computer only)
                                   |
                         voice daemon (Kokoro) -> speakers
 window (ui.py, 127.0.0.1 only) <-> assistant: events, typing, settings, keys, history
```

- **listener**: microphone, Silero voice detection, WebRTC echo cancellation (optional), barge-in, wake word, sentence joining; hands each
  sentence to the assistant. Audio never leaves the machine.
- **assistant**: holds the conversation on screen, sends the last exchanges to the brain, speaks each finished sentence as it arrives,
  stops when you talk over it, records what was said to the history (unless retention is "don't save").
- **brain**: picks the source of answers (`brain` setting) and streams text. It has no tools. Errors come back as plain sentences.
- **keys**: API keys in the operating system's credential store via `keyring`; environment variables as a fallback.
- **store**: SQLite in `~/.jarvis-ai/history.db` (0600); search, rename, delete, export, expiry by `retention_days`.
- **ui / ui_page**: a self-contained page (no external files) served on 127.0.0.1 with a per-start secret, a Host check and a header
  check against other websites. Keys can be saved or removed there, never read.
- **llm**: the local model: MLX on Apple Silicon, llama.cpp elsewhere, Ollama or any OpenAI-compatible server as alternatives.
- **tts_server / tts_client**: a warm Kokoro daemon on a token-protected loopback socket; sentences can be queued.
- **State** (`~/.jarvis-ai`): `config.toml`, `settings.json` (what the window changed), `history.db`, `ui.url` (0600), `tts.port` (0600), logs.
