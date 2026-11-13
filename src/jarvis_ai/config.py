"""Paths, config file and small runtime state. Everything lives under one directory (default ~/.jarvis-ai)."""
import os

try:
    import tomllib
except ModuleNotFoundError:          # Python < 3.11
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None

HOME = os.environ.get("JARVIS_AI_HOME", os.path.expanduser("~/.jarvis-ai"))


def _migrate_legacy():
    """The project used to be called localvoice-ai: move its folder (models, config) once, so nothing is downloaded again."""
    old = os.path.expanduser("~/.localvoice-ai")
    if "JARVIS_AI_HOME" in os.environ or os.path.exists(HOME) or not os.path.isdir(old) or os.path.exists(os.path.join(old, "venv")):
        return
    try:
        os.rename(old, HOME)
    except OSError:
        pass


_migrate_legacy()

DEFAULTS = {
    # --- speech to text ---
    "stt_backend": "auto",            # auto | mlx (Apple Silicon) | faster (any CPU/GPU)
    "stt_model": "big",               # Whisper large-v3-turbo. (Weak CPU? set an explicit smaller name, e.g. "small.en")
    "language": "en",
    # --- text to speech (Kokoro, runs on any CPU) ---
    "voice": "af_heart",
    "speed": 1.05,
    # --- where your speech goes when no session is registered ---
    "sink": "auto",                   # auto | iterm | tmux | keystroke | pty | exec | llm | stdout
    "exec_cmd": "",                   # sink=exec: shell command; transcript on stdin, reply spoken
    "mode": "brief",                  # automatic speech: brief | full
    # --- listening ---
    "vad": "silero",                  # silero (neural, recommended) | volume (plain loudness gate)
    "vad_start": 0.6,                 # speech probability needed to start an utterance
    "vad_end": 0.35,                  # below this for end_silence seconds ends it
    "end_silence": 0.65,              # seconds of quiet that ends an utterance
    "min_threshold": 0.02,            # volume floor (fallback gate, and level check for barge-in)
    "max_threshold": 0.06,            # ceiling: a noisy moment at startup must not make you inaudible
    "echo_cancel": "auto",            # auto (WebRTC AEC if installed: pip install jarvis-ai[aec]) | off
    "aec_delay_ms": 150,              # speaker -> microphone round trip on your machine
    "barge_in": True,                 # talk over the voice to interrupt it
    "barge_ratio": 2.2,               # how much louder than the echo you must be
    "wake_word": "",                  # e.g. "hey claude": ignore speech until you say it (then stay awake)
    "wake_window": 30,                # seconds you can keep talking after the wake word
    "autostart": True,                # the Claude Code plugin enables voice by itself when a session starts
    "focus_follows": True,            # speech goes to the session you are looking at; only it speaks
    "app": "",                        # sink=keystroke: app to bring to front before typing
    # --- optional local LLM (summaries, chat sink). Nothing breaks without it. ---
    "summarizer": "auto",             # auto (use an LLM if one is available) | llm | extractive
    "llm_backend": "auto",            # auto | mlx (Apple Silicon) | ollama (any machine) | openai (any OpenAI-compatible server)
    "llm_url": "",                    # backend openai: e.g. http://127.0.0.1:8080/v1 (llama.cpp), http://127.0.0.1:1234/v1 (LM Studio)
    "llm_api_model": "",              # backend openai: model name, if the server needs one
    "llm_model": "mlx-community/Qwen3-4B-Instruct-2507-4bit",     # backend mlx: any MLX model, or "auto" (picks 1.7B / 4B / 8B by memory)
    "ollama_model": "llama3.2:3b",    # backend ollama
    "ollama_url": "http://127.0.0.1:11434",
    "llm_idle_seconds": 300,          # unload the model from memory after this much idle time
    "llm_max_tokens": 250,
    "name": "jarvis",                 # say it first to talk to the assistant itself: "Jarvis, switch to the portal session". "" turns it off
    "open_cmd": "claude",             # "Jarvis, open a session in <project>": the agent to start there
    "project_dirs": [],               # folders that hold your projects; empty = common ones (~/src, ~/code ...) and those of open sessions
    "discover": True,                 # find agent sessions and read their replies without a plugin (Claude Code today)
    "approval": "dialog",             # how you approve actions taken for you: dialog (a window you click, default) | voice (say yes; weaker)
    "frontend": "commands",           # off | commands (understand loose spoken commands) | assistant (the local LLM sees every sentence; see README)
    "frontend_timeout": 6,            # seconds the local model gets before your sentence is simply forwarded
    "llm_system": "You are a concise voice assistant. Answer in at most three short, natural spoken sentences. "
                  "No markdown, lists, code or symbols.",
}


def path(*parts):
    return os.path.join(HOME, *parts)


def ensure():
    os.makedirs(HOME, exist_ok=True)
    return HOME


def load():
    cfg = dict(DEFAULTS)
    f = path("config.toml")
    if tomllib and os.path.exists(f):
        with open(f, "rb") as fh:
            cfg.update(tomllib.load(fh))
    for k in list(cfg):
        v = os.environ.get("JARVIS_AI_" + k.upper())
        if v is not None:
            d = DEFAULTS.get(k, "")
            cfg[k] = (v.lower() in ("1", "true", "yes", "on")) if isinstance(d, bool) else type(d)(v)
    return cfg


def read_state(name, default=""):
    try:
        with open(path(name)) as fh:
            return fh.read().strip()
    except OSError:
        return default


def write_state(name, value):
    ensure()
    with open(path(name), "w") as fh:
        fh.write(value)


def write_secret(name, value):
    """Write a file only the current user can read (used for the local daemon's token)."""
    ensure()
    fd = os.open(path(name), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(value)
