# Architecture

```
 mic -> listener -> Whisper (mlx | faster-whisper) -> spoken command? --yes--> handled here (zero tokens)
         (VAD)                                              |no
                                                            v
                                   router: the session you are looking at (iTerm tab / app / pane / wrapped CLI)
                                                            |
                                   sink: iterm | tmux | keystroke | pty | exec | llm | stdout  --> your AI

 your AI -> hook / pipe / `localvoice-ai run` / clipboard -> textprep (brief | full) -> voice daemon (Kokoro, ONNX) -> speakers
```

- **Core** (`src/localvoice_ai`): `listener` (mic, VAD, barge-in, wake word, commands), `stt` (mlx / faster-whisper), `textprep`
  (markdown to speakable text, brief or full, command recognition), `tts_server` / `tts_client` (warm Kokoro daemon on a
  token-protected loopback socket, in-process playback via sounddevice), `sessions` (registry + router), `sinks`, `ptyrun`
  (universal CLI wrapper), `llm` (optional, mlx or Ollama), `platform_` (every OS difference in one file), `config`, `cli`.
- **Adapters** (`adapters/*`): thin glue per tool. `adapters/claude-code` is a Claude Code plugin (hooks only; the engine does the work).
- **State** (`~/.localvoice-ai`): `config.toml`, `glossary.txt`, `sessions/*.json`, `last/<session>.md` (last reply, for "read it all"),
  `tts.port` (0600), `mode`, `.off`, `.paused`, logs.
- **No LLM in the loop by default.** Brief = first sentence of the first prose paragraph, any question aimed at you, and a note
  when a lot was left out. Code blocks, tables and URLs are never read.
- **Echo handling:** the voice daemon publishes when it expects to stop talking; the listener learns the speaker echo level and
  treats clearly louder speech as barge-in.
