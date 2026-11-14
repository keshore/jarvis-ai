"""Optional local LLM. Everything here is optional: without it "summarize that" falls back to the rule-based
summary and the `llm` sink is unavailable. Backends:

  mlx     mlx-lm, Apple Silicon (4-bit models from the mlx-community)
  ollama  any machine that runs Ollama (https://ollama.com): CPU or GPU, Linux, Windows, macOS
  openai  any server that speaks the OpenAI chat API: llama.cpp, LM Studio, vLLM, Jan, LocalAI ... (set `llm_url`).
          Pointing it at a server on another machine sends your sentences there: keep it on 127.0.0.1 to stay local.
"""
import gc, json, re, threading, time, urllib.request

from . import platform_

_lock = threading.RLock()
_state = {"model": None, "tok": None, "name": None, "timer": None}
_probe = {"t": 0.0, "v": False}

SUMMARY_SYSTEM = (
    "You turn an AI assistant's written reply into what a person would say out loud. "
    "Write two or three short, natural spoken sentences. No markdown, no lists, no code, no symbols. "
    "Say what was done or decided and the key result. If the reply asks the user a question, include it."
)


# ---------- which model ----------
MLX_BY_RAM = ((22, "mlx-community/Qwen3-8B-4bit"), (12, "mlx-community/Qwen3-4B-Instruct-2507-4bit"), (0, "mlx-community/Qwen3-1.7B-4bit"))


OLLAMA_BY_RAM = ((22, "qwen3:8b"), (12, "qwen3:4b"), (0, "qwen3:1.7b"))      # the same family and sizes as the MLX list


def ram_gb():
    """Installed memory in GB; 0.0 when it cannot be read (then the smallest model is chosen)."""
    try:
        if platform_.IS_WIN:
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [
                    (n, ctypes.c_ulonglong) for n in ("ullTotalPhys", "ullAvailPhys", "ullTotalPageFile", "ullAvailPageFile",
                                                      "ullTotalVirtual", "ullAvailVirtual", "ullAvailExtendedVirtual")]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / 2 ** 30
        import os
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 2 ** 30
    except Exception:
        return 0.0


def ollama_name(cfg):
    """`ollama_model = "auto"` picks by memory, like `llm_model` does for MLX."""
    m = cfg.get("ollama_model", "auto")
    if m and m != "auto":
        return m
    gb = ram_gb()
    return next(name for floor, name in OLLAMA_BY_RAM if gb >= floor)


def model_name(cfg):
    """`llm_model = "auto"` picks the largest model that leaves room for Whisper and the voice on this machine."""
    m = cfg.get("llm_model", "auto")
    if m and m != "auto":
        return m
    gb = ram_gb()
    return next(name for floor, name in MLX_BY_RAM if gb >= floor)


# ---------- backend selection ----------
def _mlx_available():
    if not platform_.APPLE_SILICON:
        return False
    try:
        import mlx_lm  # noqa: F401
        return True
    except Exception:
        return False


def _ollama_models(cfg):
    try:
        with urllib.request.urlopen(cfg["ollama_url"].rstrip("/") + "/api/tags", timeout=0.8) as r:
            return [m.get("name", "") for m in json.load(r).get("models", [])]
    except Exception:
        return None


def _mlx_cached(cfg):
    import glob, os
    try:
        from huggingface_hub import snapshot_download
        d = snapshot_download(model_name(cfg), local_files_only=True)
    except Exception:
        return False
    blobs = os.path.join(os.path.dirname(os.path.dirname(d)), "blobs")
    return bool(glob.glob(os.path.join(d, "*.safetensors"))) and not glob.glob(os.path.join(blobs, "*.incomplete"))


def backend(cfg):
    """Which backend can answer right now: 'mlx', 'ollama' or None."""
    want = cfg.get("llm_backend", "auto")
    if want in ("auto", "mlx") and _mlx_available() and _mlx_cached(cfg):
        return "mlx"
    if want in ("auto", "ollama"):
        tags = _ollama_models(cfg)
        if tags is not None and any(t == ollama_name(cfg) or t.split(":")[0] == ollama_name(cfg) for t in tags):
            return "ollama"
    if want in ("auto", "openai") and cfg.get("llm_url") and _openai_up(cfg):
        return "openai"
    return None


def usable(cfg):
    now = time.time()
    if now - _probe["t"] > 20:                      # do not poll Ollama on every command
        _probe["t"], _probe["v"] = now, backend(cfg) is not None
    return _probe["v"]


def loaded():
    """True when no slow model load is needed (used to say 'one moment' only when it will take a while)."""
    return _state["model"] is not None or _state["name"] in ("ollama", "openai")


# ---------- mlx ----------
def _unload():
    with _lock:
        _state.update(model=None, tok=None, name=None)
    gc.collect()
    try:
        import mlx.core as mx
        (getattr(mx, "clear_cache", None) or mx.metal.clear_cache)()
    except Exception:
        pass


def _touch(cfg):
    if _state["timer"]:
        _state["timer"].cancel()
    t = threading.Timer(float(cfg["llm_idle_seconds"]), _unload)
    t.daemon = True
    t.start()
    _state["timer"] = t


def _gen_mlx(messages, cfg, max_tokens):
    from mlx_lm import load, generate as gen
    with _lock:
        name = model_name(cfg)
        if _state["model"] is None or _state["name"] != name:
            _state["model"], _state["tok"] = load(name)
            _state["name"] = name
        model, tok = _state["model"], _state["tok"]
        try:
            prompt = tok.apply_chat_template(messages, add_generation_prompt=True, tokenize=False, enable_thinking=False)
        except TypeError:
            prompt = tok.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        out = gen(model, tok, prompt=prompt, max_tokens=max_tokens, verbose=False)
    _touch(cfg)
    return out


# ---------- ollama ----------
def _gen_ollama(messages, cfg, max_tokens):
    body = json.dumps({"model": ollama_name(cfg), "messages": messages, "stream": False, "think": False,
                       "keep_alive": f"{int(cfg['llm_idle_seconds'])}s",
                       "options": {"num_predict": max_tokens}}).encode()
    req = urllib.request.Request(cfg["ollama_url"].rstrip("/") + "/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        _state["name"] = "ollama"
        return json.load(r)["message"]["content"]


# ---------- any OpenAI-compatible server ----------
def _openai_req(cfg, path, body=None, timeout=120):
    import os
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("JARVIS_AI_LLM_KEY", "")            # from the environment only: never stored in the config file
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(cfg["llm_url"].rstrip("/") + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _openai_up(cfg):
    try:
        _openai_req(cfg, "/models", timeout=1.5)
        return True
    except Exception:
        return False


def _gen_openai(messages, cfg, max_tokens):
    body = {"messages": messages, "max_tokens": max_tokens, "stream": False}
    if cfg.get("llm_api_model"):
        body["model"] = cfg["llm_api_model"]
    out = _openai_req(cfg, "/chat/completions", body)
    _state["name"] = "openai"
    return out["choices"][0]["message"]["content"] or ""


# ---------- public ----------
def generate(messages, cfg, max_tokens=None):
    b = backend(cfg)
    if b is None:
        raise RuntimeError("no local LLM available (install mlx-lm on Apple Silicon, run Ollama, or set llm_url to an OpenAI-compatible server)")
    n = max_tokens or int(cfg["llm_max_tokens"])
    out = {"mlx": _gen_mlx, "ollama": _gen_ollama, "openai": _gen_openai}[b](messages, cfg, n)
    return re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()


def summarize(raw, cfg):
    """Spoken summary of a markdown reply. Code blocks and tables are dropped first; input is capped."""
    from . import textprep
    text = textprep.full_text(textprep.blocks(raw))[:6000]
    out = generate([{"role": "system", "content": SUMMARY_SYSTEM}, {"role": "user", "content": text}], cfg, 140)
    return textprep.endp(textprep.inline(out))
