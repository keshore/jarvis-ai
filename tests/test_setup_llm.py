import pytest

from jarvis_ai import cli, llm, platform_


@pytest.fixture
def other_os(monkeypatch):
    """A machine that is not Apple Silicon, with nothing installed."""
    ran = []
    monkeypatch.setattr(platform_, "APPLE_SILICON", False)
    monkeypatch.setattr(llm, "ram_gb", lambda: 16)
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, **kw: ran.append(cmd) or type("R", (), {"returncode": 0})())
    return ran


def test_builtin_engine_is_installed_fetched_and_proven(other_os, monkeypatch, capsys):
    state = {"installed": False}
    monkeypatch.setattr(llm, "_llama_available", lambda: state["installed"])
    monkeypatch.setattr(cli, "_pip_llama", lambda: state.update(installed=True) or True)
    got = []
    monkeypatch.setattr(llm, "gguf_path", lambda cfg, download=False: got.append(download) or "/m.gguf")
    monkeypatch.setattr(llm, "_gen_llama", lambda m, cfg, n: "OK")
    cli._setup_llm({"llm_backend": "auto"}, llm)
    assert got == [True] and other_os == [] and "built-in engine works" in capsys.readouterr().out      # Ollama never touched


def test_falls_back_to_ollama_when_the_engine_cannot_be_installed(other_os, monkeypatch, capsys):
    monkeypatch.setattr(llm, "_llama_available", lambda: False)
    monkeypatch.setattr(cli, "_pip_llama", lambda: False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)
    cli._setup_llm({"llm_backend": "auto"}, llm)
    assert other_os == [["ollama", "pull", "qwen3:4b"]] and "using Ollama instead" in capsys.readouterr().out


def test_falls_back_to_ollama_when_the_engine_does_not_run(other_os, monkeypatch):
    monkeypatch.setattr(llm, "_llama_available", lambda: True)
    monkeypatch.setattr(llm, "gguf_path", lambda cfg, download=False: "/m.gguf")
    monkeypatch.setattr(llm, "_gen_llama", lambda m, cfg, n: (_ for _ in ()).throw(OSError("illegal instruction")))
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ollama" if name == "ollama" else None)
    cli._setup_llm({"llm_backend": "auto"}, llm)
    assert other_os == [["ollama", "pull", "qwen3:4b"]]


def test_ollama_is_never_installed_without_a_typed_yes(other_os, monkeypatch):
    monkeypatch.setattr(platform_, "IS_MAC", True); monkeypatch.setattr(platform_, "IS_WIN", False)
    monkeypatch.setattr("shutil.which", lambda name: "/opt/brew" if name == "brew" else None)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    assert cli._install_ollama(ask=lambda q: "y") is False and other_os == []          # not a terminal: only prints the command
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    assert cli._install_ollama(ask=lambda q: "") is False and other_os == []           # Enter means no
    assert cli._install_ollama(ask=lambda q: "no") is False and other_os == []
    cli._install_ollama(ask=lambda q: "y")
    assert other_os == [["brew", "install", "ollama"]]


def test_gguf_model_follows_memory(monkeypatch):
    for gb, want in ((8, "1.7B"), (16, "4B"), (32, "8B"), (0, "1.7B")):
        monkeypatch.setattr(llm, "ram_gb", lambda gb=gb: gb)
        assert f"Qwen3-{want}-" in llm.gguf_name({"gguf_model": "auto"})
    assert llm.gguf_name({"gguf_model": "/x/my.gguf"}) == "/x/my.gguf"
