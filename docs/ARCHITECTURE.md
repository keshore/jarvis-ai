# Architecture

```
 mic -> listener (voice detection, echo cancellation) -> Whisper
                                   |
        "Jarvis, ..."? --yes--> jarvis: fixed patterns, else the local model fills a form that plain code checks
              |no                  |-> list / switch / status / read: done locally
              v                    `-> ask a session / open a session: approval gate (you click) -> typed where you can see it
   spoken command? --yes--> handled locally (zero tokens)
              |no
              v
   the session in front  -> sink: iterm | tmux | keystroke | pty | exec | llm | stdout  -> your AI (the visible, real session)

 your AI's reply -> transcript watcher | pipe | `jarvis-ai run` | clipboard
                 -> brief or full -> voice daemon (Kokoro) -> speakers
```

- **Three tiers of understanding.** Fixed rules first. Then an optional local model (MLX, Ollama or any OpenAI-compatible server) that may
  only choose from a fixed list of actions; code checks every field it returns (the session must be a number from the list we gave it and be
  named in your sentence; the text of a message must consist of words you said). The cloud model does the thinking, in its own visible session.
- **Connectors** (`agents.py`): find live sessions, their folder, busy state, transcript and terminal. Claude Code is read from its own
  session list and transcripts. A terminal device maps to an iTerm tab or tmux pane; any other macOS app is reached through its window.
  Everything read from an agent is data: it is spoken, never executed.
- **Approval gate** (`gate.py`): the model proposes, you approve each action in a dialog (Cancel is the default; silence is no). What you
  dictate to the session in front is typed as said and needs no approval. Proposals and decisions go to `audit.log`.
- **Core** (`src/jarvis_ai`): `listener` (mic, VAD, barge-in, wake word, commands), `stt` (mlx / faster-whisper), `textprep`
  (markdown to speakable text, brief or full, command recognition), `tts_server` / `tts_client` (warm Kokoro daemon on a
  token-protected loopback socket, in-process playback via sounddevice), `sessions` (registry + router), `agents` (connectors), `jarvis` (commands by name, watcher), `intent`, `gate`, `sinks`, `ptyrun`
  (universal CLI wrapper), `llm` (optional: mlx, Ollama or an OpenAI-compatible server), `platform_` (every OS difference in one file), `config`, `cli`.
- **State** (`~/.jarvis-ai`): `config.toml`, `glossary.txt`, `sessions/*.json`, `last/<session>.md` (last reply, for "read it all"),
  `tts.port` (0600), `audit.log` (0600), `mode`, `.off`, `.paused`, logs.
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
