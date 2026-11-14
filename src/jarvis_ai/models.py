"""One description of the three local models (speech to text, local LLM, voice): which one is used on this machine,
which engine runs it, whether it is downloaded and how much disk it takes. Shown by `status`, `setup` and `doctor`."""
import os

from . import config, llm, platform_, stt

KOKORO_FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")


def _size(path):
    """Bytes under a file or folder; links (the Hugging Face cache uses them) count as what they point to."""
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.realpath(os.path.join(root, f)))
            except OSError:
                pass
    return total


def _hf(name):
    """Bytes of a Hugging Face model already on disk; 0 when it is not downloaded. Never downloads."""
    try:
        from huggingface_hub import snapshot_download
        return _size(snapshot_download(name, local_files_only=True))
    except Exception:
        return 0


def _whisper(cfg):
    backend, name = stt.backend_name(cfg), stt.model_name(cfg)
    if backend == "mlx":
        size = _hf(name)
    else:
        try:
            from faster_whisper.utils import download_model
            size = _size(download_model(name, local_files_only=True))
        except Exception:
            size = 0
    engine = "MLX (Apple GPU)" if backend == "mlx" else "faster-whisper (CPU, or NVIDIA GPU)"
    return {"job": "speech to text", "model": name, "engine": engine, "bytes": size, "ready": size > 0,
            "note": "" if size else "run `jarvis-ai setup`"}


def _llm(cfg):
    want = cfg.get("llm_backend", "auto")
    gb = llm.ram_gb()
    picked = f"picked for {gb:.0f} GB of memory" if gb else "memory size unknown: smallest model"
    if want in ("auto", "mlx") and llm._mlx_available():
        name = llm.model_name(cfg)
        size = _hf(name) if llm._mlx_cached(cfg) else 0
        return {"job": "local LLM", "model": name, "engine": "MLX (Apple GPU)", "bytes": size, "ready": size > 0,
                "note": (picked if cfg.get("llm_model", "auto") == "auto" else "set in config") if size else "optional: run `jarvis-ai setup --llm`"}
    if want in ("auto", "llamacpp") and llm._llama_available() and not (want == "auto" and platform_.APPLE_SILICON and llm._mlx_available()):
        path = llm.gguf_path(cfg)
        size = _size(os.path.realpath(path)) if path else 0
        return {"job": "local LLM", "model": llm.gguf_name(cfg).rsplit("/", 1)[-1], "engine": "llama.cpp (built in)", "bytes": size, "ready": size > 0,
                "note": (picked if cfg.get("gguf_model", "auto") == "auto" else "set in config") if size else "optional: run `jarvis-ai setup --llm`"}
    if want in ("auto", "openai") and cfg.get("llm_url") and want != "ollama":
        up = llm.backend(cfg) == "openai"
        return {"job": "local LLM", "model": cfg.get("llm_api_model") or "(server default)", "engine": f"server at {cfg['llm_url']}",
                "bytes": 0, "ready": up, "note": "" if up else "the server does not answer"}
    name = llm.ollama_name(cfg)
    tags = llm._ollama_models(cfg)
    ready = bool(tags) and any(t == name or t.split(":")[0] == name for t in tags)
    note = (picked if cfg.get("ollama_model", "auto") == "auto" else "set in config") if ready else (
        "optional: run `jarvis-ai setup --llm`")
    if platform_.APPLE_SILICON and not ready and want != "ollama":       # on Apple Silicon the model would run on MLX once mlx-lm is installed
        return {"job": "local LLM", "model": llm.model_name(cfg), "engine": "MLX (Apple GPU)", "bytes": 0, "ready": False,
                "note": "optional: `pipx inject jarvis-ai mlx-lm`, then `jarvis-ai setup --llm`"}
    return {"job": "local LLM", "model": name, "engine": "Ollama", "bytes": 0, "ready": ready, "note": note}


def _voice(cfg):
    paths = [config.path("models", f) for f in KOKORO_FILES]
    ready = all(os.path.exists(p) for p in paths)
    return {"job": "voice", "model": f"Kokoro v1.0, voice {cfg.get('voice', '')}", "engine": "ONNX (CPU)",
            "bytes": sum(_size(p) for p in paths if os.path.exists(p)), "ready": ready, "note": "" if ready else "run `jarvis-ai setup`"}


def rows(cfg):
    return [_whisper(cfg), _llm(cfg), _voice(cfg)]


def report(cfg):
    """The lines `status`, `setup` and `doctor` print."""
    rs = rows(cfg)
    w = max(len(r["model"]) for r in rs)
    e = max(len(r["engine"]) for r in rs)
    out = ["models (all run on this machine; nothing is sent to a cloud):"]
    for r in rs:
        size = f"{r['bytes'] / 1e9:.1f} GB" if r["bytes"] else "      "
        state = "ready" if r["ready"] else "MISSING" if r["job"] != "local LLM" else "not set up"
        out.append(f"  {r['job']:15} {r['model']:{w}}  {r['engine']:{e}}  {size:>7}  {state}" + (f"  ({r['note']})" if r["note"] else ""))
    return out
