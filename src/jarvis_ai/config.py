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
    "voice": "af_bella",
    "speed": 1.05,
    "mode": "brief",                  # summaries: brief | full
    # --- listening ---
    "vad": "silero",                  # silero (neural, recommended) | volume (plain loudness gate)
    "vad_start": 0.6,                 # speech probability needed to start an utterance
    "vad_end": 0.35,                  # below this for end_silence seconds ends it
    "end_silence": 1.1,               # seconds of quiet that ends a sentence. Speak slowly or pause to think? raise it (1.5 to 2)
    "end_silence_short": 0.6,         # ... for something very short like "stop", so commands stay quick
    "min_threshold": 0.02,            # volume floor (fallback gate, and level check for barge-in)
    "max_threshold": 0.06,            # ceiling: a noisy moment at startup must not make you inaudible
    "echo_cancel": "auto",            # auto (WebRTC AEC if installed: pip install jarvis-ai[aec]) | off
    "aec_delay_ms": 150,              # speaker -> microphone round trip on your machine
    "barge_in": True,                 # talk over the voice to interrupt it
    "barge_ratio": 2.2,               # how much louder than the echo you must be
    "wake_word": "",                  # e.g. "hey jarvis": ignore speech until you say it (then stay awake)
    "wake_window": 30,                # seconds you can keep talking after the wake word
    # --- the local model (the brain when no cloud key is given) ---
    "llm_backend": "auto",            # auto | mlx (Apple Silicon) | llamacpp (built in, any machine) | ollama | openai (any OpenAI-compatible server)
    "llm_url": "",                    # backend openai: e.g. http://127.0.0.1:8080/v1 (llama.cpp), http://127.0.0.1:1234/v1 (LM Studio)
    "llm_api_model": "",              # backend openai: model name, if the server needs one
    "llm_model": "auto",     # backend mlx: any MLX model, or "auto" (picks 1.7B / 4B / 8B by memory)
    "gguf_model": "auto",             # backend llamacpp (built in; Windows, Linux, Intel Macs): auto = Qwen3 1.7B / 4B / 8B by installed memory
    "llm_ctx": 8192,                  # backend llamacpp: context window in tokens
    "ollama_model": "auto",           # backend ollama; auto = qwen3 1.7b / 4b / 8b by installed memory
    "ollama_url": "http://127.0.0.1:11434",
    "llm_idle_seconds": 300,          # unload the model from memory after this much idle time
    "llm_max_tokens": 250,
    # --- Jarvis ---
    "name": "jarvis",                 # its name: "Jarvis, ..." works the same as a plain sentence; Whisper is told to expect it
    "persona": "",                    # Jarvis's character in one line; empty = calm, dry-witted British assistant
    "call_me": "",                    # what Jarvis calls you now and then, e.g. "sir" or your name
    "brain": "auto",                  # auto | claude | openai | local. auto: a Claude key if you gave one, else an OpenAI key, else the local model
    "claude_model": "claude-opus-5-5",
    "openai_model": "",               # e.g. the model name your OpenAI account offers; empty = OpenAI is not used
    "openai_url": "https://api.openai.com/v1",
    "retention_days": 30,             # conversation history: -1 = save nothing, 0 = keep until you delete it, N = delete after N days
    "speak_answers": True,            # false = answers appear in the window only
    "ui": True,                       # the window: a page served on this machine only
    "ui_port": 0,                     # 0 = pick a free port
}


def path(*parts):
    return os.path.join(HOME, *parts)


def ensure():
    os.makedirs(HOME, exist_ok=True)
    return HOME


SETTINGS = ("name", "voice", "speed", "brain", "claude_model", "openai_model", "openai_url", "call_me", "persona",
            "retention_days", "speak_answers")                         # what the window may change


def load_settings():
    import json
    try:
        with open(path("settings.json")) as fh:
            d = json.load(fh)
        return {k: v for k, v in d.items() if k in SETTINGS and isinstance(v, type(DEFAULTS[k]))} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(changes):
    """Settings made in the window. Only the names in SETTINGS, only values of the right type; never an API key."""
    import json
    d = load_settings()
    for k, v in changes.items():
        if k in SETTINGS:
            want = type(DEFAULTS[k])
            if want is bool:
                v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
            d[k] = want(v) if not isinstance(v, want) else v
    write_secret("settings.json", json.dumps(d, indent=1))
    return d


def load():
    cfg = dict(DEFAULTS)
    f = path("config.toml")
    if tomllib and os.path.exists(f):
        with open(f, "rb") as fh:
            cfg.update(tomllib.load(fh))
    cfg.update(load_settings())
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
