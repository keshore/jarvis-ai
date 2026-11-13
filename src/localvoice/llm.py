"""Optional local LLM. Everything here is optional: without it "summarize that" falls back to the rule-based
summary and the `llm` sink is unavailable. Backends:

  mlx     mlx-lm, Apple Silicon (4-bit models from the mlx-community)
  ollama  any machine that runs Ollama (https://ollama.com): CPU or GPU, Linux, Windows, macOS
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
        d = snapshot_download(cfg["llm_model"], local_files_only=True)
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
        if tags is not None and any(t == cfg["ollama_model"] or t.split(":")[0] == cfg["ollama_model"] for t in tags):
            return "ollama"
    return None


def usable(cfg):
    now = time.time()
    if now - _probe["t"] > 20:                      # do not poll Ollama on every command
        _probe["t"], _probe["v"] = now, backend(cfg) is not None
    return _probe["v"]


def loaded():
    """True when no slow model load is needed (used to say 'one moment' only when it will take a while)."""
    return _state["model"] is not None or _state["name"] == "ollama"


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
        if _state["model"] is None or _state["name"] != cfg["llm_model"]:
            _state["model"], _state["tok"] = load(cfg["llm_model"])
            _state["name"] = cfg["llm_model"]
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
    body = json.dumps({"model": cfg["ollama_model"], "messages": messages, "stream": False,
                       "keep_alive": f"{int(cfg['llm_idle_seconds'])}s",
                       "options": {"num_predict": max_tokens}}).encode()
    req = urllib.request.Request(cfg["ollama_url"].rstrip("/") + "/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        _state["name"] = "ollama"
        return json.load(r)["message"]["content"]


# ---------- public ----------
def generate(messages, cfg, max_tokens=None):
    b = backend(cfg)
    if b is None:
        raise RuntimeError("no local LLM available (install mlx-lm on Apple Silicon, or run Ollama)")
    n = max_tokens or int(cfg["llm_max_tokens"])
    out = _gen_mlx(messages, cfg, n) if b == "mlx" else _gen_ollama(messages, cfg, n)
    return re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()


def summarize(raw, cfg):
    """Spoken summary of a markdown reply. Code blocks and tables are dropped first; input is capped."""
    from . import textprep
    text = textprep.full_text(textprep.blocks(raw))[:6000]
    out = generate([{"role": "system", "content": SUMMARY_SYSTEM}, {"role": "user", "content": text}], cfg, 140)
    return textprep.endp(textprep.inline(out))
