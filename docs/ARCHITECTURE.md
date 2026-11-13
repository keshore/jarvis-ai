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
- **Voice detection:** Silero VAD (ONNX, via `pysilero-vad`) gives a speech probability per 32 ms block; `vad.Segmenter` turns that into utterances
  with hysteresis (starts at 0.6 for three blocks, ends below 0.35 for 0.65 s, keeps a pre-roll). A volume gate is the fallback.
  Measured on test audio: real speech 89% detected; white noise, key clicks and tones 0%, where a loudness threshold fired 100%, 21% and 100%.
- **Echo cancellation (optional):** the voice daemon publishes what it plays (`ref.bin`/`ref.json` with a start time); the listener aligns it with each
  microphone block using the audio device's own timestamps and runs WebRTC's canceller (`aec-audio-processing`). On a MacBook Pro recording, the voice's
  echo was suppressed 11 to 18 dB and its "speech" score fell from 0.93 to 0.09 to 0.23, so what remains that sounds like speech is you.
  In an end-to-end run with a second voice talking over the first, the loudness heuristic never noticed it; echo cancellation did.
- **No LLM in the loop by default.** Brief = first sentence of the first prose paragraph, any question aimed at you, and a note
  when a lot was left out. Code blocks, tables and URLs are never read.
- **Fallback without echo cancellation:** the daemon publishes when it expects to stop talking; the listener learns the speaker echo level and
  treats clearly louder, speech-like sound as barge-in.
