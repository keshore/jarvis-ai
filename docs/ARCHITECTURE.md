# Architecture

```
 mic ─▶ listener ─▶ Whisper (local) ─▶ voice commands? ──yes──▶ handled here (zero tokens)
         (VAD)                              │no
                                            ▼
                                         SINK ─▶ iTerm2 | tmux | keystroke | exec | stdout ─▶ your AI

 your AI ─▶ adapter / pipe ─▶ `localvoice speak` ─▶ textprep (brief | full) ─▶ TTS daemon (Kokoro) ─▶ speakers
```

- **Core** (`src/localvoice`): `listener` (mic, VAD, STT, commands), `textprep` (markdown to speakable text, brief or full, command recognition), `tts_server` / `tts_client` (warm Kokoro daemon on a unix socket, chunked playback), `sinks`, `config`, `cli`.
- **Adapters** (`adapters/*`): thin glue per tool. Anything that can run a command with the reply on stdin is an adapter.
- **State** (`~/.localvoice`): `config.toml`, `glossary.txt`, `target`, `mode`, `last/<key>.md` (last reply per tab or session, for "read it all"), `active/` (voice-enabled sessions), sockets and logs.
- **No LLM in the loop.** "Brief" takes the first sentence of the first prose paragraph, any question aimed at you, and a note when a lot was left out. Code blocks, tables and URLs are never read.
- **Echo avoidance:** the listener ignores the mic while a player process is running, plus a short tail.
