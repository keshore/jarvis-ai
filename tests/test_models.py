from jarvis_ai import config, llm, models


def test_report_names_all_three_models_and_says_what_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(models.config, "path", lambda *a: str(tmp_path.joinpath(*a)))
    monkeypatch.setattr(models, "_hf", lambda name: 0)
    monkeypatch.setattr(llm, "_mlx_available", lambda: False)
    monkeypatch.setattr(llm, "_llama_available", lambda: False)
    monkeypatch.setattr(llm, "_ollama_models", lambda cfg: None)
    monkeypatch.setattr(llm, "ram_gb", lambda: 16)
    cfg = dict(config.DEFAULTS, stt_backend="mlx")
    rs = {r["job"]: r for r in models.rows(cfg)}
    assert set(rs) == {"speech to text", "local LLM", "voice"}
    assert not rs["voice"]["ready"] and "setup" in rs["voice"]["note"] and not rs["speech to text"]["ready"]
    assert rs["local LLM"]["model"] == "qwen3:4b" or ("mlx-lm" in rs["local LLM"]["note"] and "Qwen3-4B" in rs["local LLM"]["model"])
    out = "\n".join(models.report(cfg))
    assert "MISSING" in out and "not set up" in out and "nothing is sent to a cloud" in out


def test_report_shows_size_and_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(models.config, "path", lambda *a: str(tmp_path.joinpath(*a)))
    (tmp_path / "models").mkdir()
    for f in models.KOKORO_FILES:
        (tmp_path / "models" / f).write_bytes(b"x" * 1000)
    monkeypatch.setattr(models, "_hf", lambda name: 1_500_000_000)
    monkeypatch.setattr(llm, "_mlx_available", lambda: False)
    monkeypatch.setattr(llm, "_llama_available", lambda: False)
    monkeypatch.setattr(llm, "_ollama_models", lambda cfg: ["qwen3:8b"])
    monkeypatch.setattr(llm, "ram_gb", lambda: 32)
    cfg = dict(config.DEFAULTS, stt_backend="mlx", llm_backend="ollama")
    rs = {r["job"]: r for r in models.rows(cfg)}
    assert rs["voice"]["ready"] and rs["speech to text"]["ready"] and rs["local LLM"]["ready"]
    assert rs["local LLM"]["model"] == "qwen3:8b" and "32 GB" in rs["local LLM"]["note"]
    assert "1.5 GB" in "\n".join(models.report(cfg)) and "MISSING" not in "\n".join(models.report(cfg))


def test_report_shows_the_built_in_engine(tmp_path, monkeypatch):
    g = tmp_path / "Qwen3-4B-Q4_K_M.gguf"
    g.write_bytes(b"x" * 2_500_000)
    monkeypatch.setattr(models.config, "path", lambda *a: str(tmp_path.joinpath(*a)))
    monkeypatch.setattr(models, "_hf", lambda name: 0)
    monkeypatch.setattr(llm, "_mlx_available", lambda: False)
    monkeypatch.setattr(llm, "_llama_available", lambda: True)
    monkeypatch.setattr(llm, "gguf_path", lambda cfg, download=False: str(g))
    monkeypatch.setattr(llm, "ram_gb", lambda: 16)
    r = models._llm(dict(config.DEFAULTS))
    assert r["engine"] == "llama.cpp (built in)" and r["ready"] and r["model"] == "Qwen3-4B-Q4_K_M.gguf" and "16 GB" in r["note"]
