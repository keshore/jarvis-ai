import importlib, json, os, socket, sys, threading
import pytest


@pytest.fixture
def lv(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_AI_HOME", str(tmp_path))
    from jarvis_ai import config, textprep, tts_client
    for m in (config, textprep, tts_client):
        importlib.reload(m)
    return tmp_path


def test_last_reply_roundtrip(lv):
    from jarvis_ai import textprep
    assert textprep.load_last("k") == ""
    textprep.save_last("k", "hello")
    assert textprep.load_last("k") == "hello"


def test_stt_aliases():
    from jarvis_ai import stt
    assert stt.model_name({"stt_model": "small", "language": "en"}, "faster") == "small.en"
    assert stt.model_name({"stt_model": "small", "language": "de"}, "faster") == "small"
    assert stt.model_name({"stt_model": "small", "language": "en"}, "mlx").startswith("mlx-community/")
    assert stt.model_name({"stt_model": "my/custom", "language": "en"}, "faster") == "my/custom"


def test_llm_is_optional(lv):
    from jarvis_ai import llm, config
    cfg = config.load()
    cfg["llm_backend"], cfg["ollama_url"] = "ollama", "http://127.0.0.1:9"      # nothing listens there
    assert llm.backend(cfg) is None
    with pytest.raises(RuntimeError):
        llm.generate([{"role": "user", "content": "hi"}], cfg)


def test_voice_daemon_rejects_bad_token(lv):
    """The client sends '<token>\\n<text>' to the port recorded in tts.port; a server must check the token."""
    from jarvis_ai import config, tts_client
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    config.write_secret("tts.port", f"{srv.getsockname()[1]} secrettoken")
    got = []

    def serve():
        c, _ = srv.accept()
        data = b""
        while True:
            chunk = c.recv(4096)
            if not chunk:
                break
            data += chunk
        got.append(data)

    t = threading.Thread(target=serve, daemon=True); t.start()
    tts_client._send(b"hello")
    t.join(2)
    assert got == [b"secrettoken\nhello"]
    if os.name == "posix":
        assert oct(os.stat(config.path("tts.port")).st_mode & 0o777) == "0o600"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="needs a Unix pseudo-terminal")
def test_default_model_is_the_big_one():
    from jarvis_ai import config, stt
    cfg = config.DEFAULTS
    assert cfg["stt_model"] == "big"
    assert stt.model_name(cfg, "faster") == "large-v3-turbo"
    assert stt.model_name(cfg, "mlx") == "mlx-community/whisper-large-v3-turbo"


def test_cli_help_hides_plumbing_and_suggests(capsys, monkeypatch):
    import pytest
    from jarvis_ai import cli
    monkeypatch.setattr(sys, "argv", ["jarvis-ai", "-h"])
    with pytest.raises(SystemExit):
        cli.main()
    out = capsys.readouterr().out
    assert "doctor" in out and "off" in out and "{" not in out
    assert "enable  " not in out.split("more (rarely needed)")[0]
    monkeypatch.setattr(sys, "argv", ["jarvis-ai", "s"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert "setup" in str(e.value) and "status" in str(e.value)


def test_old_localvoice_folder_is_moved_once(tmp_path, monkeypatch):
    import importlib
    from jarvis_ai import config
    (tmp_path / ".localvoice-ai" / "models").mkdir(parents=True)
    (tmp_path / ".localvoice-ai" / "models" / "m.bin").write_text("x")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))          # Windows reads this one
    monkeypatch.delenv("JARVIS_AI_HOME", raising=False)
    try:
        importlib.reload(config)
        assert (tmp_path / ".jarvis-ai" / "models" / "m.bin").read_text() == "x" and not (tmp_path / ".localvoice-ai").exists()
    finally:
        monkeypatch.setenv("JARVIS_AI_HOME", str(tmp_path / "x"))
        importlib.reload(config)


def test_any_openai_compatible_server_can_be_the_local_model(monkeypatch):
    import http.server, threading
    from jarvis_ai import llm
    seen = {}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            self._send({"data": []})

        def do_POST(self):
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen["auth"] = self.headers.get("Authorization")
            self._send({"choices": [{"message": {"content": "<think>hmm</think>Hello there."}}]})

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        cfg = {"llm_backend": "openai", "llm_url": f"http://127.0.0.1:{srv.server_port}/v1", "llm_api_model": "any", "llm_max_tokens": 50,
               "ollama_url": "http://127.0.0.1:9", "ollama_model": "x", "llm_model": "x"}
        monkeypatch.setenv("JARVIS_AI_LLM_KEY", "secret")
        assert llm.backend(cfg) == "openai"
        assert llm.generate([{"role": "user", "content": "hi"}], cfg) == "Hello there."
        assert seen["body"]["model"] == "any" and seen["auth"] == "Bearer secret"
        assert llm.backend({**cfg, "llm_url": "http://127.0.0.1:9/v1"}) is None            # unreachable server: no backend, features fall back
    finally:
        srv.shutdown()
