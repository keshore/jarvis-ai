"""Paths, config file and small runtime state. Everything lives under one directory (default ~/.localvoice)."""
import os

try:
    import tomllib
except ModuleNotFoundError:          # Python < 3.11
    tomllib = None

HOME = os.environ.get("LOCALVOICE_HOME", os.path.expanduser("~/.localvoice"))

DEFAULTS = {
    "stt_model": "mlx-community/whisper-small.en-mlx",   # or mlx-community/whisper-large-v3-turbo
    "language": "en",
    "voice": "af_heart",              # Kokoro voice
    "speed": 1.05,
    "sink": "iterm",                  # iterm | tmux | keystroke | exec | stdout
    "exec_cmd": "",                   # sink=exec: shell command; transcript on stdin, reply spoken
    "mode": "brief",                  # default for automatic speech: brief | full
    "end_silence": 0.65,              # seconds of quiet that ends an utterance
    "min_threshold": 0.02,            # floor for the volume threshold
    "max_threshold": 0.06,            # ceiling: a noisy moment at startup must not make you inaudible
    "barge_in": True,                 # talk over the voice to interrupt it
    "barge_ratio": 2.2,               # how much louder than the echo you must be (raise if it self-interrupts)
    "summarizer": "auto",             # "summarize that": auto (local LLM if installed) | llm | extractive
    "llm_model": "mlx-community/Qwen3-4B-Instruct-2507-4bit",   # or Qwen3-1.7B-4bit (1 GB)
    "llm_idle_seconds": 300,          # unload the model from memory after this much idle time
    "llm_max_tokens": 250,
    "llm_system": "You are a concise voice assistant. Answer in at most three short, natural spoken sentences. "
                  "No markdown, lists, code or symbols.",
    "wake_word": "",                  # e.g. "hey claude": ignore speech until you say it (then stay awake)
    "wake_window": 30,                # seconds you can keep talking after the wake word
    "app": "",                        # sink=keystroke: app to bring to front before typing
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
        v = os.environ.get("LOCALVOICE_" + k.upper())
        if v is not None:
            d = DEFAULTS[k]
            cfg[k] = (v.lower() in ("1", "true", "yes", "on")) if isinstance(d, bool) else type(d)(v)
    return cfg


def read_state(name, default=""):
    try:
        return open(path(name)).read().strip()
    except OSError:
        return default


def write_state(name, value):
    ensure()
    with open(path(name), "w") as fh:
        fh.write(value)


def sock_path():
    return path("tts.sock")
