# Roadmap

1. Glossary-aware transcription (done), instant silence when you type, Escape-interrupt (done).
2. Optional local small-LLM summary for "summarize that" (Qwen3-4B-Instruct-2507 4-bit or Qwen3-1.7B, loaded on demand, unloaded when idle). Extractive stays the default.
3. Silero VAD instead of the volume threshold; headphone barge-in.
4. Focus-follows-voice: route speech to the focused terminal tab.
5. `speak --clipboard` and a clipboard watcher for apps with no hooks.
6. Spoken announcements (needs input, task finished); voice approval of prompts with strict phrases.
7. Linux backend (faster-whisper, aplay); one background process; menu-bar mic indicator.
