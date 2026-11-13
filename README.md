# localvoice-ai

[![PyPI](https://img.shields.io/pypi/v/localvoice-ai)](https://pypi.org/project/localvoice-ai/)
[![Python](https://img.shields.io/pypi/pyversions/localvoice-ai)](https://pypi.org/project/localvoice-ai/)
[![tests](https://github.com/keshore/localvoice-ai/actions/workflows/test.yml/badge.svg)](https://github.com/keshore/localvoice-ai/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/keshore/localvoice-ai/blob/main/LICENSE)

**Talk to your AI agent hands-free and hear its answers, entirely on your own machine.**
Speech recognition ([Whisper](https://github.com/openai/whisper)) and the voice ([Kokoro](https://github.com/hexgrad/kokoro)) are local
models. What you say and what the AI says back never leave your computer.

- **Talk, don't type.** Your speech is typed into the session you are looking at.
- **Hear the answer your way.** Brief by default. Say *"read it all"* for the whole reply, *"summarize that"* for a summary.
- **Talk over it.** Start speaking and it stops and listens (barge-in). Reliable on speakers too with the optional echo cancellation.
- **No extra tokens.** Spoken commands are matched locally and the AI never sees them. The default summary is rule-based.
- **Optional local LLM** for nicer summaries, or to chat with directly. Silently skipped if you do not have one.
- **Works with** Claude Code (as a plugin), Codex, Copilot CLI, aider, ollama, desktop apps: anything with a terminal or a text box.

> **Status: early (v0.3).** Developed and tested on macOS with Apple Silicon. Linux, Intel Macs and Windows are supported by design and the
> portable logic is unit-tested on all three in CI, but the audio path has not been exercised there yet. Reports and fixes are welcome.

## Install

**1. The engine.** Any machine with Python 3.10 to 3.13 (not 3.14 yet):

```bash
pipx install --python python3.12 localvoice-ai      # brew install pipx   (or: pip install pipx)
localvoice-ai setup                                 # one-time download: voice ~330 MB + Whisper model ~1.6 GB
localvoice-ai doctor                                # checks microphone, speakers and models
```

No pipx? From a clone, `./install.sh` does the same with a private virtual environment:

```bash
git clone https://github.com/keshore/localvoice-ai && cd localvoice-ai && ./install.sh
```

**2. The Claude Code plugin** (Claude Code 2.1.275 or later):

```
/plugin marketplace add keshore/localvoice-ai
/plugin install localvoice-ai@localvoice-ai
```

The same from a terminal: `claude plugin marketplace add keshore/localvoice-ai`, then `claude plugin install localvoice-ai@localvoice-ai`.
Check with `claude plugin list`. Then **start a new Claude Code session**: sessions that were already open when you installed the plugin have no hooks.
That is all: there is no command to run. When a session starts, voice switches itself on, loads the models in
the background (about ten seconds) and listens. When your last session closes, everything stops and gives its memory back.

**Optional: echo cancellation**, so you can interrupt the voice when it plays through speakers (headphones do not need it):
`pipx inject localvoice-ai aec-audio-processing` (or `pip install 'localvoice-ai[aec]'`; Python 3.11+). It builds a small C++ library, so macOS needs the
Xcode Command Line Tools and Linux a compiler; Windows has a prebuilt wheel. Without it everything still works, with a weaker interruption check.

**Permissions (macOS):** allow the microphone for your terminal app the first time. Controlling iTerm2 or typing into other apps
asks for *Automation* / *Accessibility* access. **Linux:** `sudo apt install libportaudio2`. For the `keystroke` sink on Linux or
Windows also `pip install 'localvoice-ai[keys]'`.

## Using it

Just talk. Say **"stop"** to silence the voice and **"interrupt"** to stop the AI's current turn.

| Say | Does (handled locally, never sent to the AI) |
|---|---|
| "read it all" / "read everything" | reads the whole last reply |
| "summarize that" / "give me the summary" | reads a short version (uses the local LLM if you have one) |
| "read everything from now on" / "summaries only from now on" | sets the default for every reply |
| "read the clipboard" / "summarize the clipboard" | reads what you copied (for apps with no hook) |
| "stop" | silences the voice |
| "interrupt" / "cancel that" | silences it and presses Escape in the AI |

Anything that names something else, like "summarize the auth file", goes to the AI as normal.

```bash
localvoice-ai off        # stop everything and keep it off
localvoice-ai on         # turn it back on
localvoice-ai status     # what is running, which sessions, which model
```
`LOCALVOICE_AI_DISABLE=1` keeps voice off for a single session.

### Several sessions

Your speech goes to **the session you are looking at** (the iTerm tab in front, or the desktop app in front), and only that session
reads its reply aloud. A reply that finishes in a background session is saved, so "read it all" works once you switch to it.

## Any other agent

| You want | Use |
|---|---|
| Read any command's output aloud | `some-agent ... \| localvoice-ai speak` |
| A tool with a hook or notify command that sends JSON | `localvoice-ai hook json` (Codex: `notify = ["localvoice-ai", "hook", "json"]` in `~/.codex/config.toml`; unverified) |
| Any interactive CLI, no hooks needed | `localvoice-ai run -- aider` (voice in and out; macOS, Linux, WSL) |
| A desktop or browser chat window | speech is typed into the focused window (`keystroke` sink); copy a reply and say "read the clipboard" |
| Talk to a local model directly | `localvoice-ai start --sink llm` (needs the optional LLM) |

Where your speech goes is called a *sink*: `iterm`, `tmux`, `keystroke` (types into whatever has focus, so mind where the cursor is),
`pty`, `exec`, `llm`, `stdout`.

## Optional local LLM

Nothing needs it. When one is available, "summarize that" uses it instead of the rule-based summary.

- **Apple Silicon:** `pipx inject localvoice-ai mlx-lm` (or `pip install 'localvoice-ai[llm]'`), then `localvoice-ai setup --llm`.
  Qwen3-4B, 2.3 GB, loaded on demand and unloaded after five idle minutes.
- **Any machine:** install [Ollama](https://ollama.com) and run `ollama pull llama3.2:3b`. It is detected automatically.

## Configuration

`~/.localvoice-ai/config.toml` (see the [example](https://github.com/keshore/localvoice-ai/blob/main/examples/config.toml)) and
`~/.localvoice-ai/glossary.txt` (names Whisper should recognise: project names, libraries, people). Any key can be overridden with
`LOCALVOICE_AI_<KEY>`.

| Key | Default | Use |
|---|---|---|
| `wake_word` | none | e.g. `"hey claude"`: ignore everything until you say it, then stay awake for `wake_window` seconds |
| `stt_model` | big (large-v3-turbo) | on a slow CPU set a smaller one such as `"small.en"` |
| `vad` | silero | `silero` (neural speech detector, recommended) or `volume` (plain loudness gate) |
| `echo_cancel`, `aec_delay_ms` | auto, 150 | echo cancellation when installed; the speaker-to-microphone delay of your machine (150 fits a MacBook Pro) |
| `barge_ratio` | 2.2 | only without echo cancellation: how much louder than the echo you must be to interrupt |
| `mode` | brief | `brief` or `full` |
| `voice`, `speed` | af_heart, 1.05 | Kokoro voice and speed |

## Privacy

The microphone feeds a local volume detector and a local Whisper model. The only network use is the one-time model download (GitHub
releases and Hugging Face). There is no telemetry. The microphone is open while it runs: `touch ~/.localvoice-ai/.paused` pauses
it and `localvoice-ai off` ends it. The voice daemon listens on `127.0.0.1` only and requires a secret token that changes on every start.

## Troubleshooting

| Symptom | Try |
|---|---|
| Nothing happens when I talk | `localvoice-ai status`, then read `~/.localvoice-ai/listener.log`. A line `(ignored, start with 'hey claude')` means a wake word is set. |
| No sound | check the system volume is not muted; `localvoice-ai doctor` checks the speakers; log: `~/.localvoice-ai/tts.log` |
| Typing by voice works but replies are silent | the plugin is not installed (`claude plugin list` should show `localvoice-ai`), or that session started before it was: start a new one. `localvoice-ai status` lists the sessions voice knows about. |
| The voice interrupts itself | install the echo cancellation extra, or raise `barge_ratio` (try 3), or use headphones |
| It does not notice me talking over it | install the echo cancellation extra (speakers feed the voice back into the mic), or use headphones; tune `aec_delay_ms` |
| It picks up other people talking nearby | set a `wake_word`. Fans, keyboards and music are already ignored by the speech detector. |
| `pipx` or install fails on Python 3.14 | pass `--python python3.12`; 3.14 is not supported yet |
| First start is slow | the Whisper model loads on every start (about ten seconds); it stays loaded while a session is open |

## Known limits

- Without the echo cancellation extra, interrupting on laptop speakers relies on a loudness heuristic that can miss you. Headphones are always reliable.
- With it, the first second or so of an interruption can be clipped, and `aec_delay_ms` is tuned on one MacBook Pro; other machines may need a different value.
- The speech detector separates speech from noise, not one speaker from another: use a `wake_word` if people talk near you.
- `localvoice-ai run` needs a Unix pseudo-terminal (macOS, Linux, WSL). Full-screen terminal UIs redraw constantly, so prefer a tool's own hook.
- Reading replies aloud needs a hook, a pipe, `run` or the clipboard. Chat apps in a window expose none, so there is no automatic
  read-back there yet.

## How it works

```
 mic -> Whisper (local) -> spoken command? -- yes --> handled here, the AI never sees it
                                  | no
                                  v
                   the session you are looking at -> your AI

 your AI's reply -> hook / pipe / run / clipboard -> brief or full -> Kokoro voice (local) -> speakers
```

More in the [architecture notes](https://github.com/keshore/localvoice-ai/blob/main/docs/ARCHITECTURE.md) and the
[roadmap](https://github.com/keshore/localvoice-ai/blob/main/ROADMAP.md).

## Contributing

```bash
git clone https://github.com/keshore/localvoice-ai && cd localvoice-ai
pip install -e '.[dev]' && pytest
```
Issues and pull requests are welcome, especially reports from Linux, Windows and Intel Macs.

## License

[MIT](https://github.com/keshore/localvoice-ai/blob/main/LICENSE)
