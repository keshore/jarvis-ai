"""Optional local LLM (mlx-lm). Loaded on first use, unloaded after a quiet period to give the memory back.
Used for the "summarize that" command and by the `llm` sink (talk to a local model instead of a cloud AI)."""
import gc, re, threading

_lock = threading.RLock()
_state = {"model": None, "tok": None, "name": None, "timer": None}

SUMMARY_SYSTEM = (
    "You turn an AI assistant's written reply into what a person would say out loud. "
    "Write two or three short, natural spoken sentences. No markdown, no lists, no code, no symbols. "
    "Say what was done or decided and the key result. If the reply asks the user a question, include it."
)


def available():
    try:
        import mlx_lm  # noqa: F401
        return True
    except Exception:
        return False


def cached(cfg):
    """True only when the weights are fully downloaded (not just the small config files)."""
    import glob, os
    try:
        from huggingface_hub import snapshot_download
        d = snapshot_download(cfg["llm_model"], local_files_only=True)
    except Exception:
        return False
    blobs = os.path.join(os.path.dirname(os.path.dirname(d)), "blobs")
    return bool(glob.glob(os.path.join(d, "*.safetensors"))) and not glob.glob(os.path.join(blobs, "*.incomplete"))


def usable(cfg):
    return available() and cached(cfg)


def loaded():
    return _state["model"] is not None


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


def generate(messages, cfg, max_tokens=None):
    from mlx_lm import load, generate as gen
    with _lock:
        if _state["model"] is None or _state["name"] != cfg["llm_model"]:
            _state["model"], _state["tok"] = load(cfg["llm_model"])
            _state["name"] = cfg["llm_model"]
        model, tok = _state["model"], _state["tok"]
        try:
            prompt = tok.apply_chat_template(messages, add_generation_prompt=True, tokenize=False,
                                             enable_thinking=False)
        except TypeError:
            prompt = tok.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        out = gen(model, tok, prompt=prompt, max_tokens=max_tokens or int(cfg["llm_max_tokens"]), verbose=False)
    _touch(cfg)
    return re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()


def summarize(raw, cfg):
    """Spoken summary of a markdown reply. Code blocks and tables are dropped first; input is capped."""
    from . import textprep
    text = textprep.full_text(textprep.blocks(raw))[:6000]
    out = generate([{"role": "system", "content": SUMMARY_SYSTEM}, {"role": "user", "content": text}],
                   cfg, max_tokens=140)
    return textprep.endp(textprep.inline(out))
