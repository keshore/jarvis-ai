# localvoice

Hands-free voice for **any AI**, running entirely on your machine. Nothing you say, and nothing the AI says back, leaves your computer.

- **You speak** → local Whisper (`mlx-whisper`) → your terminal or app.
- **The AI answers** → local Kokoro-82M voice reads it back, as a short summary or in full, **by your command**.
- **No extra tokens.** Spoken commands are matched locally, so the AI never sees them, and the default "brief" summary is rule-based.
- **Talk over it.** Barge-in: start speaking while it is reading and it stops and listens.
- **Optional local LLM** (`mlx-lm`, 4-bit Qwen) for better "summarize that" summaries, or as the AI you talk to (`sink = "llm"`). Loaded on demand, unloaded when idle.

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

## Local LLM (optional)

```bash
./install.sh --llm                 # or: pip install 'localvoice[llm]' && localvoice setup --llm
```
- **"Summarize that"** then uses the local model (`summarizer = "auto"`), falling back to the rule-based summary if the model is not installed. Try it: `cat reply.md | localvoice summarize --speak`.
- **Talk to a local model instead of a cloud AI:** `localvoice start --sink llm`. Short conversation memory, reply printed and spoken.
- Default model `mlx-community/Qwen3-4B-Instruct-2507-4bit` (2.3 GB); `Qwen3-1.7B-4bit` (1 GB) if memory is tight. Unloaded after `llm_idle_seconds` (300) of silence.

## Room noise and talking over it

- **Wake word:** set `wake_word = "hey claude"` in `config.toml`. Speech that does not start with it is ignored; after you say it you can keep talking for `wake_window` seconds (30).
- **Barge-in** (`barge_in = true`): while the voice speaks, the listener learns the echo level and interrupts the voice when you are `barge_ratio` (2.2) times louder than it for ~0.25 s. Headphones make this very reliable; on speakers raise the ratio if it interrupts itself, lower it if it misses you.

## Configuration

`~/.localvoice/config.toml` (see `examples/config.toml`) and `~/.localvoice/glossary.txt`: terms Whisper should recognise (project names, libraries). Any key can be overridden with `LOCALVOICE_<KEY>`.

## Privacy

The microphone feeds a local volume detector and a local Whisper model. The only network use is the one-time model download (GitHub releases and Hugging Face). No telemetry. The mic stays open while `localvoice` runs: `touch ~/.localvoice/.paused` pauses it, `localvoice stop` ends it.

## Known limits

- Barge-in on laptop speakers is a level heuristic, not true echo cancellation. Headphones are reliable; speakers may need `barge_ratio` tuning.
- Volume-based voice detection can trigger on a noisy room. A proper VAD model is on the roadmap.
- macOS / Apple Silicon only. The player and STT backends are isolated, so Linux (faster-whisper, `aplay`) is a contained port.

See `docs/ARCHITECTURE.md` and `ROADMAP.md`. MIT licensed.
