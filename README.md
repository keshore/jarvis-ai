# localvoice

Hands-free voice for **any AI**, running entirely on your machine. Nothing you say, and nothing the AI says back, leaves your computer.

- **You speak** → local Whisper (`mlx-whisper`) → your terminal or app.
- **The AI answers** → local Kokoro-82M voice reads it back, as a short summary or in full, **by your command**.
- **No LLM and no extra tokens.** Summaries are extractive, and spoken commands are matched locally, so the AI never sees them.

> Status: early. macOS on Apple Silicon only for now. The audio parts need a real microphone and were verified by hand; the text logic is unit-tested.

## Quick start

```bash
git clone <this repo> && cd localvoice
./install.sh              # venv in ~/.localvoice, downloads models (~0.8 GB)
localvoice doctor
localvoice start          # run it inside the terminal tab (iTerm2 or tmux) you talk to
```

Then just talk. Say **"stop"** to silence the voice, **"interrupt"** to stop the AI's current turn.

## Voice commands (handled locally, never sent to the AI)

| Say | Does |
|---|---|
| "read it all" / "read everything" | reads the whole last reply |
| "summarize that" / "give me the summary" | reads a short version |
| "read everything from now on" / "summaries only from now on" | sets the default for automatic speech |
| "stop" | silences the voice |
| "interrupt" / "cancel that" | silences it and sends Escape to the AI |

Phrases that name something else ("summarize the auth file") go to the AI as normal.

## Works with

| Tool | Your voice in | Replies read aloud |
|---|---|---|
| Claude Code (terminal) | `iterm` or `tmux` sink | hooks: `adapters/claude-code` |
| Claude Code (desktop Code tab) | `keystroke` sink (untested) | same hooks (untested) |
| Any CLI AI (ollama, llm, aichat, aider, codex, gemini-cli, ...) | type into its terminal, or `sink = "exec"` | pipe its output: `... \| localvoice speak` |
| GUI chat apps (ChatGPT, browsers, ...) | `keystroke` sink | no automatic hook yet; copy the reply, then `pbpaste \| localvoice speak` |

Sinks: `iterm`, `tmux`, `keystroke` (types into the frontmost app: needs Accessibility permission, mind the focus), `exec` (runs a command per utterance and speaks its reply), `stdout`.

### Claude Code

```bash
./adapters/claude-code/install.sh     # installs /localvoice and 3 hooks (merged, backup kept)
```
Then in a session: `/localvoice` (on), `/localvoice big`, `/localvoice off`. Voice is per session; replies of other sessions stay silent.

### Anything else

```bash
ollama run llama3.2 "explain DNS" | localvoice speak            # brief by default
ollama run llama3.2 "explain DNS" | localvoice speak --mode full
localvoice say full                                              # re-read the last reply in full
```

## Configuration

`~/.localvoice/config.toml` (see `examples/config.toml`) and `~/.localvoice/glossary.txt`: terms Whisper should recognise (project names, libraries). Any key can be overridden with `LOCALVOICE_<KEY>`.

## Privacy

The microphone feeds a local volume detector and a local Whisper model. The only network use is the one-time model download (GitHub releases and Hugging Face). No telemetry. The mic stays open while `localvoice` runs: `touch ~/.localvoice/.paused` pauses it, `localvoice stop` ends it.

## Known limits

- The listener goes deaf while the voice is speaking (to avoid hearing itself), so "stop" works between replies, not mid-sentence. Headphone barge-in is on the roadmap.
- Volume-based voice detection can trigger on a noisy room. A proper VAD model is on the roadmap.
- macOS / Apple Silicon only. The player and STT backends are isolated, so Linux (faster-whisper, `aplay`) is a contained port.

See `docs/ARCHITECTURE.md` and `ROADMAP.md`. MIT licensed.
