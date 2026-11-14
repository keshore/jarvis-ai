# jarvis-ai

**A voice assistant that lives on your own computer.** You talk, it answers out loud, and you can talk over it.

- **Your voice stays here.** Speech recognition ([Whisper](https://github.com/openai/whisper)) and the voice
  ([Kokoro](https://github.com/hexgrad/kokoro)) run on your machine. Audio is never sent anywhere.
- **Pick the brain.** With no setup the answers come from a model on your machine, and nothing leaves it. Add a Claude or OpenAI
  API key and the answers come from that service instead: then the *text* of what you say is sent to it, the audio still is not.
- **Its own window.** Run `jarvis-ai` and a window opens: the conversation, a box to type in, your past conversations and the settings.
- **History you control.** Conversations are kept in one file on this computer that only you can read, for as long as you choose
  (30 days by default, or not at all). Search, rename, export or delete them.
- **No tools.** Jarvis only talks. It cannot open apps, read files, run commands or change anything on your computer, and it says so
  when asked.
- **Talk over it.** Start speaking and it stops and listens. Say "stop" to silence it.
- **Keys are kept safe.** An API key goes into your system's credential store (Keychain, Credential Manager, Secret Service), never
  into a file or a log, and the window can store or remove it but never show it.

Looking for voice in Claude Code, Codex or other AI tools? That is a separate project, aivoice.

> **Status: early, not released.** Developed and tested on macOS with Apple Silicon. Linux, Intel Macs and Windows are supported by
> design and the portable logic is unit-tested on all three in CI, but the audio path has not been exercised there yet. The window is
> a page in your browser for now; a packaged app with an installer comes later.

## Install

Any machine with Python 3.10 to 3.13 (not 3.14 yet):

```bash
pipx install --python python3.12 git+https://github.com/mintlime-in/jarvis-ai
jarvis-ai setup --llm        # one-time download: voice, Whisper and a local model sized to your memory
jarvis-ai                    # starts it and opens the window
```

**Optional: echo cancellation**, so you can talk over it when it plays through speakers (headphones do not need it):
`pipx inject jarvis-ai aec-audio-processing` (Python 3.11+). It builds a small C++ library, so macOS needs the Xcode Command Line Tools
and Linux a compiler; Windows has a prebuilt wheel.

**Permissions:** allow the microphone the first time. **Linux:** `sudo apt install libportaudio2`.

## Using it

Open the window with `jarvis-ai`, then just talk. "Jarvis, ..." and a plain sentence are the same thing.

| In the window | Does |
|---|---|
| Type in the box | the same as saying it. Enter sends, Shift+Enter adds a line, Esc stops the voice |
| Microphone on / off | stops listening without quitting |
| Copy, Say again | under each answer |
| New conversation | starts fresh; the old one stays in the list |
| A past conversation | opens it and lets you carry on where you left off |
| The badge at the top | says whether your words stay on this computer or go to a cloud service |

```bash
jarvis-ai            # start and open the window
jarvis-ai off        # stop everything and keep it off
jarvis-ai status     # what is running, which models, where answers come from
jarvis-ai login on   # start when you log in
```

## Where answers come from

| Brain | When | What leaves your computer |
|---|---|---|
| Local model | default, after `jarvis-ai setup --llm` | nothing |
| Claude | you saved a Claude API key (from platform.claude.com) in Settings | the text of the conversation, sent to Anthropic |
| OpenAI | you saved an OpenAI key and a model name in Settings | the text of the conversation, sent to OpenAI |

With a key saved, "Automatic" uses the cloud; set "Use" to "Local model only" to keep everything here. Answers from Claude stream in and
are spoken sentence by sentence; the local model answers in one piece.

The local model:

- **Apple Silicon:** `pipx inject jarvis-ai mlx-lm` (or `pip install 'jarvis-ai[llm]'`), then `jarvis-ai setup --llm`.
  Loaded on demand and unloaded after five idle minutes. `llm_model = "auto"` picks a size by memory
  (1.7B under 12 GB, 4B under 22 GB, 8B above); any MLX model name works.
- **Windows, Linux, Intel Macs:** `jarvis-ai setup --llm`. It installs llama.cpp into Jarvis itself (a prebuilt package, nothing to
  compile), fetches a Qwen3 model sized to your memory (1.7B, 4B or 8B) and checks that it answers. If that fails on your machine it
  falls back to [Ollama](https://ollama.com) and offers to install it with your system's installer; nothing is installed without a
  typed yes. Run on a Mac only so far; not yet verified on a real Windows or Linux machine.
- **Any other local server** that speaks the OpenAI chat API (LM Studio, vLLM, Jan): set `llm_url`, e.g.
  `llm_url = "http://127.0.0.1:8080/v1"` (and `llm_api_model` if the server wants a model name). A key, if needed, is read from the
  `JARVIS_AI_LLM_KEY` environment variable. Keep the address on `127.0.0.1`: a server elsewhere receives what you say.

## Settings

Most settings are in the window. The rest live in `~/.jarvis-ai/config.toml`, and any key can be overridden with `JARVIS_AI_<KEY>`.

| Key | Default | Use |
|---|---|---|
| `brain` | auto | `auto`, `claude`, `openai` or `local` |
| `claude_model`, `openai_model` | claude-opus-5-5, none | which cloud model answers |
| `retention_days` | 30 | `-1` saves nothing, `0` keeps until you delete, otherwise days |
| `voice`, `speed`, `speak_answers` | af_bella, 1.05, true | the voice, its speed, and whether answers are spoken at all |
| `name`, `call_me`, `persona` | jarvis, none, calm and dry-witted | its name, what it calls you, its character |
| `end_silence`, `end_silence_short` | 1.1, 0.6 | how long a pause ends a sentence; raise to 1.5 to 2 if you pause to think |
| `wake_word` | none | e.g. `"hey jarvis"`: ignore everything until you say it |
| `stt_model` | big (large-v3-turbo) | on a slow CPU set a smaller one such as `"small.en"` |
| `echo_cancel`, `aec_delay_ms` | auto, 150 | echo cancellation when installed; the speaker-to-microphone delay of your machine |

## Privacy and security

- Audio is turned into text on this computer. The only network use without a cloud key is the one-time model download.
- With a cloud key, the text of the conversation goes to that service, and the window says so at the top.
- History is one SQLite file (`~/.jarvis-ai/history.db`) readable only by your account, kept for `retention_days`. "Delete all
  conversations" also compacts the file so the words are gone from disk. It is protected by file permissions, not encrypted.
- The window is served on `127.0.0.1` only, needs a secret made at each start, rejects other websites, and can never show a saved key.
- No telemetry.

## Troubleshooting

| Symptom | Try |
|---|---|
| The window says nothing can answer | run `jarvis-ai setup --llm`, or save a key in Settings |
| Nothing happens when I talk | the microphone button may be off; then read `~/.jarvis-ai/listener.log` |
| No sound | check the system volume; `jarvis-ai doctor` checks the speakers; log: `~/.jarvis-ai/tts.log` |
| It interrupts itself | install echo cancellation, or use headphones |
| It picks up people talking nearby | set a `wake_word` |
| Install fails on Python 3.14 | pass `--python python3.12` |

## How it works

```
 mic -> speech detector -> Whisper (local) -> the brain (local model, or Claude / OpenAI with your key) -> Kokoro voice (local) -> speakers
                                                     |
                                       window and history (this computer only)
```

More in the [architecture notes](docs/ARCHITECTURE.md) and the [roadmap](ROADMAP.md).

## Contributing

```bash
git clone https://github.com/mintlime-in/jarvis-ai && cd jarvis-ai
pip install -e '.[dev]' && pytest
```

## License

[MIT](LICENSE)
