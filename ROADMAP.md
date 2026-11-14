# Roadmap

Nothing is released yet. jarvis-ai is a personal voice assistant. Voice for AI coding tools (Claude Code, Codex, Cursor ...) moved to
its own project, aivoice.

**Built**
- Ears and voice on your machine: Whisper, Kokoro, neural voice detection, echo cancellation, talking over it, waiting for the whole sentence.
- A brain that is a local model (MLX, llama.cpp, Ollama) or Claude / OpenAI with your API key; keys in the system credential store.
- Its own window: conversation, typing, past conversations with search, rename, export, delete; settings.
- History on this computer only, with retention you choose.

**Next**
1. A packaged app with an installer per system, so no command line is needed.
2. More brains: GitHub Copilot and other sign-ins, where their terms allow it.
3. Tools, one at a time, each behind an approval you click.
4. Answers that start sooner with the local model (it answers in one piece today).
5. Audio verified on Linux, Intel Macs and Windows.
