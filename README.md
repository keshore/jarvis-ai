# localvoice

Hands-free voice for **any AI agent**, running entirely on your own machine. What you say and what the AI says
back never leave your computer: speech recognition (Whisper) and the voice (Kokoro) are local models.

- **Talk, don't type.** Your speech is typed into the session you are looking at.
- **Hear the answer, your way.** Brief by default; say *"read it all"* for the whole reply, *"summarize that"* for a summary.
- **Talk over it.** Start speaking and it stops and listens (barge-in).
- **No extra tokens.** Spoken commands are matched locally; the AI never sees them. The default summary is rule-based.
- **Optional local LLM** for nicer summaries or to chat with directly. Skipped silently if you do not have one.
- **Works with** Claude Code (plugin), Codex, Copilot CLI, aider, ollama, desktop apps, or anything with a terminal or a text box.

> Status: early (v0.2). Developed and tested on macOS / Apple Silicon. Linux, Intel Macs and Windows are supported by design and
> by unit tests in CI, but the audio path has not been exercised there yet. Issues and reports welcome.

## Install

**1. The engine** (any machine, Python 3.10-3.13):

```bash
pipx install git+https://github.com/keshore/localvoice      # PyPI: `pipx install localvoice-ai` once published
localvoice setup          # downloads the voice (~330 MB) and the Whisper model (~1.6 GB), once
localvoice doctor         # checks microphone, speakers and models
```

**2. The Claude Code plugin**, if you use Claude Code (Claude Code 2.1.275 or later):

```
/plugin install localvoice --marketplace keshore/localvoice
```

That is all: there is no command to run. When a session starts, voice switches itself on, loads the models in the
background and listens. Just talk. When your last session closes, everything stops and frees its memory.

Linux needs PortAudio (`apt install libportaudio2`); on Linux/Windows the `keystroke` sink also needs `pip install 'localvoice-ai[keys]'`.

## Using it

Speak normally. Say **"stop"** to silence the voice, **"interrupt"** to stop the AI's current turn.

| Say | Does (handled locally, never sent to the AI) |
|---|---|
| "read it all" / "read everything" | reads the whole last reply |
| "summarize that" / "give me the summary" | reads a short version (local LLM if you have one) |
| "read everything from now on" / "summaries only from now on" | sets the default |
| "read the clipboard" / "summarize the clipboard" | reads what you copied (for apps with no hook) |
| "stop" | silences the voice |
| "interrupt" / "cancel that" | silences it and presses Escape in the AI |

Phrases that name something else ("summarize the auth file") go to the AI as normal.
`localvoice off` stops everything and keeps it off; `localvoice on` turns it back on; `LOCALVOICE_DISABLE=1` skips a session.

### Several sessions

Your speech goes to **the session you are looking at** (the iTerm tab in front, or the desktop app in front), and only that session
reads its reply aloud. A reply that finishes in a background session is saved, so "read it all" works once you switch to it.

## Any other agent

| How | Use |
|---|---|
| Read any command's output aloud | `some-agent ... \| localvoice speak` |
| Tool has a hook / notify command with JSON | `localvoice hook json` (e.g. Codex: `notify = ["localvoice", "hook", "json"]` in `~/.codex/config.toml`; unverified) |
| Any interactive CLI, no hooks needed | `localvoice run -- aider` (voice in and out; macOS/Linux) |
| A GUI app (chat window) | speech is typed into it (`keystroke` sink); copy a reply and say "read the clipboard" |
| Talk to a local model directly | `localvoice start --sink llm` (needs the optional LLM) |

Sinks, i.e. where your speech goes: `iterm`, `tmux`, `keystroke` (types into the focused window: mind the focus), `pty`, `exec`, `llm`, `stdout`.

## Optional local LLM

Nothing needs it. If one is available, "summarize that" uses it instead of the rule-based summary.
- **Apple Silicon:** `pipx inject localvoice-ai mlx-lm` (or `pip install 'localvoice-ai[llm]'`), then `localvoice setup --llm` (Qwen3-4B, 2.3 GB, loaded on demand, unloaded after 5 idle minutes).
- **Any machine:** install [Ollama](https://ollama.com) and `ollama pull llama3.2:3b`. It is detected automatically.

## Configuration

`~/.localvoice/config.toml` (see `examples/config.toml`) and `~/.localvoice/glossary.txt` (names Whisper should recognise).
Every key can be overridden with `LOCALVOICE_<KEY>`. Useful ones: `wake_word = "hey claude"` (ignore room chatter until you say it),
`barge_ratio` (raise if it interrupts itself, lower if it misses you; headphones are most reliable), `stt_model` (default is the big
Whisper model; on a slow CPU set a smaller one such as `"small.en"`), `voice`, `speed`, `mode`.

## Privacy

The microphone feeds a local volume detector and a local Whisper model. The only network use is the one-time model download
(GitHub releases and Hugging Face). No telemetry. The mic is open while it runs: `touch ~/.localvoice/.paused` pauses it,
`localvoice off` ends it. The voice daemon listens on `127.0.0.1` only and requires a per-run secret token.

## Known limits

- Barge-in on laptop speakers is a level heuristic, not true echo cancellation.
- Volume-based voice detection can trigger in a noisy room: use `wake_word`.
- `localvoice run` needs a Unix pseudo-terminal (macOS, Linux, WSL). Full-screen TUIs redraw a lot, so prefer a tool's own hook.
- Reading replies aloud needs a hook, a pipe, `run`, or the clipboard: GUI chat apps expose none, so there is no automatic read-back there yet.

See `docs/ARCHITECTURE.md` and `ROADMAP.md`. MIT licensed.
