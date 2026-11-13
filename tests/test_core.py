import importlib, json, os, socket, sys, threading, time
import pytest


@pytest.fixture
def lv(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_AI_HOME", str(tmp_path))
    from jarvis_ai import config, sessions, textprep, tts_client
    for m in (config, sessions, textprep, tts_client):
        importlib.reload(m)
    return tmp_path


def test_session_registry(lv):
    from jarvis_ai import sessions
    s = {"id": "abc", "sink": "iterm", "target": "T1", "app": "", "term": "T1"}
    sessions.register(s)
    assert sessions.get("abc")["target"] == "T1"
    assert [x["id"] for x in sessions.all()] == ["abc"]
    sessions.remove("abc")
    assert sessions.get("abc") is None and sessions.all() == []


def test_router_follows_focus(lv, monkeypatch):
    from jarvis_ai import sessions, platform_
    sessions.register({"id": "a", "sink": "iterm", "target": "TA", "app": "", "term": "TA"})
    sessions.register({"id": "b", "sink": "iterm", "target": "TB", "app": "", "term": "TB"})
    sessions.register({"id": "c", "sink": "keystroke", "target": "", "app": "Claude", "term": ""})
    monkeypatch.setattr(platform_, "front_app", lambda: "iTerm2")
    monkeypatch.setattr(platform_, "iterm_focused", lambda: "TB")
    assert sessions.current()["id"] == "b"
    monkeypatch.setattr(platform_, "iterm_focused", lambda: "TA")
    assert sessions.current()["id"] == "a"
    monkeypatch.setattr(platform_, "front_app", lambda: "Claude")          # a desktop app is in front
    assert sessions.current()["id"] == "c"


def test_router_falls_back_to_last_used(lv, monkeypatch):
    from jarvis_ai import sessions, platform_, config
    sessions.register({"id": "a", "sink": "tmux", "target": "%1", "app": "", "term": ""})
    sessions.register({"id": "b", "sink": "tmux", "target": "%2", "app": "", "term": ""})
    monkeypatch.setattr(platform_, "front_app", lambda: "Safari")
    assert sessions.current() is None                                       # ambiguous
    config.write_state("last_session", "b")
    assert sessions.current()["id"] == "b"


def test_detect_picks_sink_from_environment(lv, monkeypatch):
    from jarvis_ai import sessions, platform_
    monkeypatch.delenv("ITERM_SESSION_ID", raising=False)
    monkeypatch.setenv("TMUX_PANE", "%7")
    assert sessions.detect("x")["sink"] == "tmux"
    monkeypatch.delenv("TMUX_PANE")
    monkeypatch.setattr(platform_, "front_app", lambda: "Some App")
    s = sessions.detect("y")
    assert s["sink"] == "keystroke" and s["app"] == "Some App"


def test_last_reply_roundtrip(lv):
    from jarvis_ai import textprep
    assert textprep.load_last("k") == ""
    textprep.save_last("k", "hello")
    assert textprep.load_last("k") == "hello"


def test_hook_json_extracts_reply(lv, monkeypatch):
    from jarvis_ai import cli, tts_client, textprep
    said = []
    monkeypatch.setattr(tts_client, "speak", lambda t: said.append(t))
    a = type("A", (), {"payload": json.dumps({"type": "agent-turn-complete", "last-assistant-message": "All done here."}),
                       "field": None, "session": None})()
    cli._hook_json(a)
    assert said == ["All done here."] and textprep.load_last("default") == "All done here."
    said.clear()
    a.payload, a.field = json.dumps({"a": {"b": "nested reply"}}), "a.b"
    cli._hook_json(a)
    assert said == ["nested reply."]


def test_hook_json_respects_session_gate(lv, monkeypatch):
    from jarvis_ai import cli, tts_client
    said = []
    monkeypatch.setattr(tts_client, "speak", lambda t: said.append(t))
    a = type("A", (), {"payload": '{"message": "hi"}', "field": None, "session": "not-enabled"})()
    cli._hook_json(a)
    assert said == []


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


def test_clean_output_strips_terminal_noise():
    from jarvis_ai import ptyrun
    raw = b"\x1b[2K\rthinking...\r\x1b[32mHere is the answer.\x1b[0m\r\n\xe2\x94\x80\xe2\x94\x80\xe2\x94\x80\r\nSecond line.\r\nSecond line.\r\n"
    assert ptyrun.clean_output(raw) == "Here is the answer.\nSecond line."


@pytest.mark.skipif(sys.platform.startswith("win"), reason="needs a Unix pseudo-terminal")
def test_pty_wrapper_end_to_end(lv, monkeypatch, tmp_path):
    """Run a tiny echo REPL under `jarvis-ai run`, inject a sentence over the control socket, read its reply."""
    import subprocess
    env = dict(os.environ, JARVIS_AI_HOME=str(lv))
    prog = "import sys\nfor l in sys.stdin:\n    print('REPLY TO: ' + l.strip(), flush=True)\n"
    p = subprocess.Popen([sys.executable, "-m", "jarvis_ai.cli", "run", "--no-speak", "--",
                          sys.executable, "-u", "-c", prog], env=env, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    from jarvis_ai import sessions, sinks, config
    importlib.reload(sessions)
    deadline, s = time.time() + 8, None
    while time.time() < deadline and not s:
        time.sleep(0.2)
        ss = sessions.all()
        s = ss[0] if ss else None
    if not s:
        p.kill(); print(p.stderr.read().decode())
    assert s and s["sink"] == "pty"
    sinks.for_session(config.load(), s).send("hello world")
    time.sleep(1.0)
    p.stdin.close()
    out = p.stdout.read().decode()
    p.wait(timeout=10)
    assert "REPLY TO: hello world" in out


def _hook(cli, event, sid="s1", payload=None):
    import argparse
    p = json.dumps(payload or {"session_id": sid})
    cli.cmd_hook(argparse.Namespace(event=event, payload=p, field=None, session=None))


@pytest.fixture
def plugin_env(lv, monkeypatch):
    from jarvis_ai import cli, tts_client
    spawned, said = [], []
    monkeypatch.setattr(cli, "_spawn_listener", lambda: spawned.append(1) or True)
    monkeypatch.setattr(tts_client, "speak", lambda t: said.append(t))
    monkeypatch.setattr(tts_client, "stop", lambda: None)
    monkeypatch.delenv("JARVIS_AI_DISABLE", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ATTENDED", "1")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    monkeypatch.setenv("TMUX_PANE", "%9")
    monkeypatch.delenv("ITERM_SESSION_ID", raising=False)
    return cli, spawned, said


def test_plugin_enables_session_by_itself(plugin_env):
    from jarvis_ai import sessions
    cli, spawned, said = plugin_env
    _hook(cli, "claude-start")
    s = sessions.get("s1")
    assert s and s["sink"] == "tmux" and s["target"] == "%9" and spawned          # no /jarvis-ai needed
    _hook(cli, "claude-stop", payload={"session_id": "s1", "last_assistant_message": "All done."})
    assert said == ["All done."]
    _hook(cli, "claude-end")
    assert sessions.get("s1") is None


def test_plugin_enables_lazily_on_first_prompt(plugin_env):
    from jarvis_ai import sessions
    cli, spawned, _ = plugin_env
    _hook(cli, "claude-prompt")                      # plugin installed mid-session: SessionStart never ran
    assert sessions.get("s1") and spawned


def test_plugin_skips_scripted_and_opted_out_sessions(plugin_env, monkeypatch):
    from jarvis_ai import sessions, config
    cli, spawned, _ = plugin_env
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ATTENDED", "0")
    _hook(cli, "claude-start", sid="scripted")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ATTENDED", "1")
    monkeypatch.setenv("JARVIS_AI_DISABLE", "1")
    _hook(cli, "claude-start", sid="optout")
    monkeypatch.delenv("JARVIS_AI_DISABLE")
    config.write_state(".off", "1")                  # after `jarvis-ai stop` it stays off
    _hook(cli, "claude-start", sid="stopped")
    assert sessions.all() == [] and not spawned


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
    monkeypatch.setattr(sys, "argv", ["jarvis-ai", "sta"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert "start" in str(e.value) and "status" in str(e.value)


def test_stale_hook_sessions_are_forgotten(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_AI_HOME", str(tmp_path))
    from jarvis_ai import sessions
    sessions.register({"id": "old", "sink": "iterm", "target": "T", "created": time.time() - 13 * 3600})
    sessions.register({"id": "fresh", "sink": "iterm", "target": "U", "created": time.time() - 13 * 3600, "seen": time.time()})
    assert [s["id"] for s in sessions.all()] == ["fresh"]


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
