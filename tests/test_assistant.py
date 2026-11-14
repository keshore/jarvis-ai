import json, threading, time, urllib.error, urllib.request

import pytest

from jarvis_ai import assistant, brain, config, keys, ui


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", str(tmp_path))
    monkeypatch.setattr(keys, "_ring", lambda: None)                 # never touch the real keychain in tests
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False); monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return tmp_path


def run(agent, text):
    agent.hear(text)
    for _ in range(200):
        if not agent.busy and agent.turn:
            time.sleep(0.02)
            if not agent.busy:
                return
        time.sleep(0.01)


def test_answer_is_spoken_sentence_by_sentence_and_remembered(home, monkeypatch):
    seen = []
    monkeypatch.setattr(brain, "stream", lambda messages, cfg, cancel=None: (seen.append(messages), iter(["Paris. It ", "is in France. And", " lovely"]))[1])
    said = []
    a = assistant.Assistant(speak=lambda text, voice, add: said.append((text, add)), stop=lambda: None)
    run(a, "what is the capital of France")
    assert said == [("Paris.", False), ("It is in France.", True), ("And lovely.", True)]            # first replaces, the rest queue
    assert a.history[-1] == {"role": "assistant", "content": "Paris. It is in France. And lovely"}
    run(a, "and of Spain")
    assert seen[-1][0]["content"] == "what is the capital of France" and seen[-1][-1] == {"role": "user", "content": "and of Spain"}


def test_stop_silences_and_is_not_sent_to_the_brain(home, monkeypatch):
    monkeypatch.setattr(brain, "stream", lambda *a, **k: pytest.fail("stop must not reach the brain"))
    stopped = []
    a = assistant.Assistant(speak=lambda *x: None, stop=lambda: stopped.append(1))
    a.hear("Stop.")
    assert stopped and a.turn == 0


def test_talking_over_it_drops_the_rest(home, monkeypatch):
    gate = threading.Event()

    def slow(messages, cfg, cancel=None):
        yield "First sentence. "
        gate.wait(2)
        yield "Second sentence. "
    monkeypatch.setattr(brain, "stream", slow)
    said = []
    a = assistant.Assistant(speak=lambda text, voice, add: said.append(text), stop=lambda: None)
    a.hear("tell me a story")
    time.sleep(0.1)
    a.interrupt(); gate.set()
    time.sleep(0.1)
    assert said == ["First sentence."]
    assert a.history[-1] == {"role": "assistant", "content": "First sentence."}       # what you did hear stays as context ("go on")


def test_a_brain_problem_is_said_not_swallowed(home, monkeypatch):
    def broken(messages, cfg, cancel=None):
        raise brain.BrainError("The Claude API key was not accepted. Check it in the settings.")
        yield
    monkeypatch.setattr(brain, "stream", broken)
    said = []
    a = assistant.Assistant(speak=lambda text, voice, add: said.append(text), stop=lambda: None)
    run(a, "hello")
    assert said == ["The Claude API key was not accepted. Check it in the settings."] and a.history == []


def test_brain_choice(home, monkeypatch):
    from jarvis_ai import llm
    cfg = dict(config.DEFAULTS)
    monkeypatch.setattr(llm, "usable", lambda cfg: False)
    assert brain.provider(cfg) is None
    with pytest.raises(brain.BrainError):
        list(brain.stream([{"role": "user", "content": "hi"}], cfg))
    monkeypatch.setattr(llm, "usable", lambda cfg: True)
    assert brain.provider(cfg) == "local"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert brain.provider(cfg) == "claude" and brain.provider(dict(cfg, brain="local")) == "local"
    monkeypatch.delenv("ANTHROPIC_API_KEY"); monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert brain.provider(cfg) == "local" and brain.provider(dict(cfg, openai_model="some-model")) == "openai"
    s = brain.system(dict(cfg, call_me="sir"))
    assert "no tools" in s and "sir" in s and "Jarvis" in s


def test_keys_are_validated_and_need_a_credential_store(home):
    with pytest.raises(ValueError):
        keys.put("anthropic", "has a space")
    with pytest.raises(ValueError):
        keys.put("github", "x")
    with pytest.raises(RuntimeError):
        keys.put("anthropic", "sk-ant-abc")                           # no credential store here: refuse, never write a file


@pytest.fixture
def window(home, monkeypatch):
    heard = []
    agent = type("A", (), {"hear": lambda self, t, typed=False: heard.append(t), "interrupt": lambda self: heard.append("<stop>"),
                           "clear": lambda self: heard.append("<clear>")})()
    monkeypatch.setattr(ui, "voices", lambda: ["af_bella"])
    url, srv = ui.start(agent, dict(config.DEFAULTS))
    yield url, heard
    srv.shutdown()


def call(url, path, body=None, cookie=None, headers=None):
    base = url.split("/?")[0]
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers or {})
    if cookie:
        req.add_header("Cookie", "jarvis=" + cookie)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), e.headers


def test_window_needs_the_secret_and_blocks_other_sites(window):
    url, heard = window
    token = url.split("k=")[1]
    assert call(url, "/")[0] == 403 and call(url, "/?k=wrong")[0] == 403 and call(url, "/state")[0] == 403
    code, page, headers = call(url, "/?k=" + token)
    assert code == 200 and "<title>Jarvis</title>" in page and "HttpOnly" in headers["Set-Cookie"] and "SameSite=Strict" in headers["Set-Cookie"]
    assert token not in page
    assert call(url, "/state?k=" + token)[0] == 403                                        # the secret in the address only opens the page itself
    assert call(url, "/state", cookie=token)[0] == 200
    assert call(url, "/say", {"text": "hi"}, cookie=token)[0] == 403 and heard == []         # a plain form post from another site has no X-Jarvis header
    assert call(url, "/state", cookie=token, headers={"Host": "evil.example"})[0] == 403    # a name pointed at 127.0.0.1
    assert call(url, "/say", {"text": "hi"}, cookie=token, headers={"X-Jarvis": "1"})[0] == 200 and heard == ["hi"]


def test_window_settings_and_keys(window, home):
    url, heard = window
    token = url.split("k=")[1]
    h = {"X-Jarvis": "1"}
    code, body, _ = call(url, "/settings", {"voice": "af_bella", "claude_model": "claude-haiku-5-5", "sink": "exec", "approval": "voice"}, token, h)
    st = json.loads(body)
    assert code == 200 and st["settings"]["claude_model"] == "claude-haiku-5-5"
    saved = json.loads((home / "settings.json").read_text())
    assert saved == {"voice": "af_bella", "claude_model": "claude-haiku-5-5"}                # only the listed settings can be changed from the window
    assert config.load()["claude_model"] == "claude-haiku-5-5" and config.load()["approval"] == "dialog"
    code, body, _ = call(url, "/key", {"name": "anthropic", "value": "sk-ant-secret"}, token, h)
    assert code == 400 and "sk-ant-secret" not in body                                       # no credential store in the test: refused, not written to disk
    assert "sk-ant-secret" not in "".join(p.read_text() for p in home.iterdir() if p.is_file())
    assert call(url, "/key", {"name": "other", "value": "x"}, token, h)[0] == 400
    assert "keys" in st and st["keys"] == {"anthropic": False, "openai": False} and "sk-" not in body
