# jarvis-ai

[![PyPI](https://img.shields.io/pypi/v/jarvis-ai)](https://pypi.org/project/jarvis-ai/)
[![Python](https://img.shields.io/pypi/pyversions/jarvis-ai)](https://pypi.org/project/jarvis-ai/)
[![tests](https://github.com/keshore/jarvis-ai/actions/workflows/test.yml/badge.svg)](https://github.com/keshore/jarvis-ai/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/keshore/jarvis-ai/blob/main/LICENSE)

**Talk to your AI agent hands-free and hear its answers, entirely on your own machine.**
Speech recognition ([Whisper](https://github.com/openai/whisper)) and the voice ([Kokoro](https://github.com/hexgrad/kokoro)) are local
models. What you say and what the AI says back never leave your computer.

- **Talk, don't type.** Your speech is typed into the session you are looking at.
- **Hear the answer your way.** Brief by default. Say *"read it all"* for the whole reply, *"summarize that"* for a summary.
- **Call it by name.** *"Jarvis, what's open?"*, *"Jarvis, switch to the portal session"*, *"Jarvis, ask the portal session to run the tests"*.
- **No plugin needed.** It finds your AI sessions by itself and reads their replies from the agents' own transcripts.
- **Nothing happens behind your back.** You see the real session. Anything Jarvis would type on its own needs your click on an approval window first.
- **Talk over it.** Start speaking and it stops and listens (barge-in). Reliable on speakers too with the optional echo cancellation.
- **Any local LLM, or none.** MLX, Ollama, or any OpenAI-compatible server (llama.cpp, LM Studio, vLLM) understands loosely worded requests. Without one, fixed phrases still work.
- **Works with** Claude Code, Codex, Copilot CLI, aider, ollama, desktop apps: anything with a terminal or a text box.

> **Status: early (v0.3).** Developed and tested on macOS with Apple Silicon. Linux, Intel Macs and Windows are supported by design and the
> portable logic is unit-tested on all three in CI, but the audio path has not been exercised there yet. Reports and fixes are welcome.

## Install

**1. The engine.** Any machine with Python 3.10 to 3.13 (not 3.14 yet):

```bash
pipx install --python python3.12 jarvis-ai      # brew install pipx   (or: pip install pipx)
jarvis-ai setup                                 # one-time download: voice ~330 MB + Whisper model ~1.6 GB
jarvis-ai doctor                                # checks microphone, speakers and models
```

No pipx? From a clone, `./install.sh` does the same with a private virtual environment:

```bash
git clone https://github.com/keshore/jarvis-ai && cd jarvis-ai && ./install.sh
```

**2. Start it:** `jarvis-ai on`. It finds running Claude Code sessions by itself, in any terminal or app. In iTerm2 and tmux it reaches the exact tab or pane; in any
other app on macOS (Terminal, VS Code, Warp, Ghostty ...) it works through that app's window; elsewhere it types into the window in front. `jarvis-ai off` stops it.

**Optional: the Claude Code plugin** starts and stops voice together with your sessions, so you never run `on` / `off`
(Claude Code 2.1.275 or later):

```
/plugin marketplace add keshore/jarvis-ai
/plugin install jarvis-ai@jarvis-ai
```

**Optional: echo cancellation**, so you can interrupt the voice when it plays through speakers (headphones do not need it):
`pipx inject jarvis-ai aec-audio-processing` (or `pip install 'jarvis-ai[aec]'`; Python 3.11+). It builds a small C++ library, so macOS needs the
Xcode Command Line Tools and Linux a compiler; Windows has a prebuilt wheel. Without it everything still works, with a weaker interruption check.

**Permissions (macOS):** allow the microphone for your terminal app the first time. Controlling iTerm2 or typing into other apps
asks for *Automation* / *Accessibility* access. **Linux:** `sudo apt install libportaudio2`. For the `keystroke` sink on Linux or
Windows also `pip install 'jarvis-ai[keys]'`.

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

You do not need the exact words: "read me the whole thing", "say it all", "give me the short version" also work, with no model.
With the optional local LLM, other short requests ("I'd like to hear everything it said") are understood too.
Anything that names something else, like "summarize the auth file", goes to the AI as normal.

```bash
jarvis-ai off        # stop everything and keep it off
jarvis-ai on         # turn it back on
jarvis-ai status     # what is running, which sessions, which model
```
`JARVIS_AI_DISABLE=1` keeps voice off for a single session.

### You talk to Jarvis, Jarvis talks to the agent

With a local model, what you say goes to Jarvis first (`talk_to = "jarvis"`, the default), not straight into the agent:

- **Small talk** ("good morning", "tell me a joke") is answered by Jarvis in character. This step never sees your project, so it cannot misstate it.
- **Questions about the work** ("how many tests pass?", "explain that more simply", "summarize what it said about the upload") are answered
  from the session's own conversation, and only when the answer is stated there.
- **Anything else** (a task, or a question the conversation does not answer): Jarvis asks *"That one needs Claude. Shall I ask?"* A plain
  **yes** sends your words to the agent; **no** drops it. "Ask Claude ..." sends directly.
- "Summarize the previous response" and "read the one before that" reach back to earlier replies.

Jarvis speaks in its own voice (`jarvis_voice`), so you can tell it from the agent's replies being read out. Set `persona` and `call_me`
to change its character and what it calls you. `talk_to = "agent"` restores plain dictation; `confirm_agent = "never"` passes things on without asking.
Without a local model it behaves like `talk_to = "agent"`.

Measured with Qwen3-8B on a test conversation (28 sentences): no invented facts; it answered or chatted where it could and asked for the rest.
Qwen3-4B invented an answer twice, so the larger model is the default where memory allows (`llm_model = "auto"`).

### Commands for Jarvis itself

Start a sentence with the name (`name` in the config, default "jarvis"):

| Say | Does |
|---|---|
| "Jarvis, what's open?" | lists your sessions and whether each is working or idle |
| "Jarvis, switch to the portal session" | brings that tab or pane to the front (iTerm2, tmux) |
| "Jarvis, is the portal session done?" | working or finished |
| "Jarvis, read the portal session's reply" | reads that session's last reply |
| "Jarvis, ask the portal session to run the tests" | shows an approval window with the exact text, then types it there |
| "Jarvis, open a session in the portal project" | finds the folder, shows an approval window with the command and path, then opens a new tab running your agent (`open_cmd`, default `claude`; "start a codex session in ..." picks another) |

With a local model, looser wording works too ("have the portal one rebuild the image"). The model only fills in a form; code checks that
the session is one you named and that the message is made of your own words.

Sessions are matched by project folder or session name. If two match equally, or none, Jarvis says so and does nothing.
What you dictate to the session in front is typed as you said it. Everything else that would type somewhere needs your approval:
a window with **Approve** / **Cancel** (Cancel is the default, no answer means no). Every proposal and decision is written to
`~/.jarvis-ai/audit.log`. `approval = "voice"` allows a spoken "yes" instead: weaker, because anyone who can be heard can say it.

### Several sessions

Your speech goes to **the session you are looking at** (the iTerm tab in front, or the desktop app in front), and only that session
reads its reply aloud. A reply that finishes in a background session is saved, so "read it all" works once you switch to it.

## Any other agent

| You want | Use |
|---|---|
| Read any command's output aloud | `some-agent ... \| jarvis-ai speak` |
| A tool with a hook or notify command that sends JSON | `jarvis-ai hook json` (Codex: `notify = ["jarvis-ai", "hook", "json"]` in `~/.codex/config.toml`; unverified) |
| Any interactive CLI, no hooks needed | `jarvis-ai run -- aider` (voice in and out; macOS, Linux, WSL) |
| A desktop or browser chat window | speech is typed into the focused window (`keystroke` sink); copy a reply and say "read the clipboard" |
| Talk to a local model directly | `jarvis-ai start --sink llm` (needs the optional LLM) |

Where your speech goes is called a *sink*: `iterm`, `tmux`, `keystroke` (types into whatever has focus, so mind where the cursor is),
`pty`, `exec`, `llm`, `stdout`.

## Optional local LLM

Nothing needs it. When one is available, "summarize that" uses it instead of the rule-based summary.

- **Apple Silicon:** `pipx inject jarvis-ai mlx-lm` (or `pip install 'jarvis-ai[llm]'`), then `jarvis-ai setup --llm`.
  Qwen3-4B, 2.3 GB, loaded on demand and unloaded after five idle minutes. `llm_model = "auto"` picks a size by memory
  (1.7B under 12 GB, 4B under 22 GB, 8B above); any MLX model name works.
- **Any machine:** install [Ollama](https://ollama.com) and run `ollama pull llama3.2:3b`. It is detected automatically.
- **Any other local server** that speaks the OpenAI chat API (llama.cpp, LM Studio, vLLM, Jan): set `llm_url`, e.g.
  `llm_url = "http://127.0.0.1:8080/v1"` (and `llm_api_model` if the server wants a model name). A key, if needed, is read from the
  `JARVIS_AI_LLM_KEY` environment variable. Keep the address on `127.0.0.1`: a server elsewhere receives what you say.

### The local model between you and the AI (`frontend`)

The local model can only pick from a fixed list of actions, and everything spoken back comes from fixed text, so it cannot make up an answer. If it is unsure, slow (`frontend_timeout`, 6 s), unavailable or answers in
a wrong format, your sentence goes to the AI exactly as you said it. At `assistant` level a cleaned-up sentence is used only if it stays
close to what you said, and the listener log shows `(cleaned up: ...)`, `(command: ...)` or `(answered locally: ...)` for every decision.
Each sentence waits for the model first (about a second on a 3 to 4B model), so `commands` limits this to short sentences.

## Configuration

`~/.jarvis-ai/config.toml` (see the [example](https://github.com/keshore/jarvis-ai/blob/main/examples/config.toml)) and
`~/.jarvis-ai/glossary.txt` (names Whisper should recognise: project names, libraries, people). Any key can be overridden with
`JARVIS_AI_<KEY>`.

| Key | Default | Use |
|---|---|---|
| `wake_word` | none | e.g. `"hey claude"`: ignore everything until you say it, then stay awake for `wake_window` seconds |
| `stt_model` | big (large-v3-turbo) | on a slow CPU set a smaller one such as `"small.en"` |
| `vad` | silero | `silero` (neural speech detector, recommended) or `volume` (plain loudness gate) |
| `echo_cancel`, `aec_delay_ms` | auto, 150 | echo cancellation when installed; the speaker-to-microphone delay of your machine (150 fits a MacBook Pro) |
| `barge_ratio` | 2.2 | only without echo cancellation: how much louder than the echo you must be to interrupt |
| `name` | jarvis | the word that addresses the assistant itself; `""` turns that off |
| `open_cmd`, `project_dirs` | claude, common folders | what "open a session" starts, and where your projects live |
| `discover` | true | find agent sessions and read their replies without a plugin |
| `approval` | dialog | `dialog` (click to approve) or `voice` (say yes; weaker) |
| `talk_to`, `confirm_agent` | jarvis, always | talk to Jarvis first (or `agent` for plain dictation); ask before passing things to the agent |
| `persona`, `call_me`, `jarvis_voice` | dry-witted British assistant, none, bm_george | Jarvis's character, what it calls you, its Kokoro voice |
| `frontend` | commands | `off`: exact phrases only. `commands`: loose wording, plus the local LLM for short unusual requests. `assistant`: the local LLM sees every sentence, of any length: it can run a command or forward your sentence lightly cleaned of dictation slips |
| `mode` | brief | `brief` or `full` |
| `voice`, `speed` | af_heart, 1.05 | Kokoro voice and speed |

## Privacy

The microphone feeds a local volume detector and a local Whisper model. The only network use is the one-time model download (GitHub
releases and Hugging Face). There is no telemetry. The microphone is open while it runs: `touch ~/.jarvis-ai/.paused` pauses
it and `jarvis-ai off` ends it. The voice daemon listens on `127.0.0.1` only and requires a secret token that changes on every start.

## Troubleshooting

| Symptom | Try |
|---|---|
| Nothing happens when I talk | `jarvis-ai status`, then read `~/.jarvis-ai/listener.log`. A line `(ignored, start with 'hey claude')` means a wake word is set. |
| No sound | check the system volume is not muted; `jarvis-ai doctor` checks the speakers; log: `~/.jarvis-ai/tts.log` |
| Typing by voice works but replies are silent | the plugin is not installed (`claude plugin list` should show `jarvis-ai`), or that session started before it was: start a new one. `jarvis-ai status` lists the sessions voice knows about. |
| The voice interrupts itself | install the echo cancellation extra, or raise `barge_ratio` (try 3), or use headphones |
| It does not notice me talking over it | install the echo cancellation extra (speakers feed the voice back into the mic), or use headphones; tune `aec_delay_ms` |
| It picks up other people talking nearby | set a `wake_word`. Fans, keyboards and music are already ignored by the speech detector. |
| `pipx` or install fails on Python 3.14 | pass `--python python3.12`; 3.14 is not supported yet |
| First start is slow | the Whisper model loads on every start (about ten seconds); it stays loaded while a session is open |

## Known limits

- Without the echo cancellation extra, interrupting on laptop speakers relies on a loudness heuristic that can miss you. Headphones are always reliable.
- With it, the first second or so of an interruption can be clipped, and `aec_delay_ms` is tuned on one MacBook Pro; other machines may need a different value.
- The speech detector separates speech from noise, not one speaker from another: use a `wake_word` if people talk near you.
- `jarvis-ai run` needs a Unix pseudo-terminal (macOS, Linux, WSL). Full-screen terminal UIs redraw constantly, so prefer a tool's own hook.
- Finding sessions without a plugin reads Claude Code's own session list and transcripts. These are internal files and may change with a Claude Code update; the plugin is the fallback. Other agents use `run`, a hook or a pipe.
- Picking one tab among several needs iTerm2 or tmux. In other apps Jarvis can bring the app to the front, and types into a session that is not in front only when it is the only session in that app.
- Reading replies aloud needs a transcript (Claude Code), a hook, a pipe, `run` or the clipboard. Chat apps in a window expose none, so there is no automatic
  read-back there yet.

## How it works

```
 mic -> Whisper (local) -> spoken command? -- yes --> handled here, the AI never sees it
                                  | no
                                  v
                   the session you are looking at -> your AI

 your AI's reply -> hook / pipe / run / clipboard -> brief or full -> Kokoro voice (local) -> speakers
```

More in the [architecture notes](https://github.com/keshore/jarvis-ai/blob/main/docs/ARCHITECTURE.md) and the
[roadmap](https://github.com/keshore/jarvis-ai/blob/main/ROADMAP.md).

## Contributing

```bash
git clone https://github.com/keshore/jarvis-ai && cd jarvis-ai
pip install -e '.[dev]' && pytest
```
Issues and pull requests are welcome, especially reports from Linux, Windows and Intel Macs.

## License

[MIT](https://github.com/keshore/jarvis-ai/blob/main/LICENSE)
