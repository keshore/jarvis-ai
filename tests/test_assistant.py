import json, threading, time, urllib.error, urllib.request

import pytest

from jarvis_ai import assistant, brain, config, keys, store, ui


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
    assert a.messages[-1]["role"] == "assistant" and a.messages[-1]["text"] == "Paris. It is in France. And lovely"
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
    assert a.messages[-1]["text"] == "First sentence."                                  # what you did hear stays as context ("go on")


def test_a_brain_problem_is_said_not_swallowed(home, monkeypatch):
    def broken(messages, cfg, cancel=None):
        raise brain.BrainError("The Claude API key was not accepted. Check it in the settings.")
        yield
    monkeypatch.setattr(brain, "stream", broken)
    said = []
    a = assistant.Assistant(speak=lambda text, voice, add: said.append(text), stop=lambda: None)
    run(a, "hello")
    assert said == ["The Claude API key was not accepted. Check it in the settings."]
    assert [m["role"] for m in a.messages] == ["user"]


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
                           "new": lambda self: heard.append("<new>"), "housekeeping": lambda self, cfg, force=False: heard.append("<purge>"),
                           "snapshot": lambda self: {"id": "", "title": "", "messages": [], "saved": False}})()
    monkeypatch.setattr(ui, "voices", lambda: [{"id": "af_bella", "label": "Bella, American woman"}])
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
    assert config.load()["claude_model"] == "claude-haiku-5-5"
    code, body, _ = call(url, "/key", {"name": "anthropic", "value": "sk-ant-secret"}, token, h)
    assert code == 400 and "sk-ant-secret" not in body                                       # no credential store in the test: refused, not written to disk
    assert "sk-ant-secret" not in "".join(p.read_text() for p in home.iterdir() if p.is_file())
    assert call(url, "/key", {"name": "other", "value": "x"}, token, h)[0] == 400
    assert "keys" in st and st["keys"] == {"anthropic": False, "openai": False} and "sk-" not in body


def test_history_is_saved_reopened_and_continued(home, monkeypatch):
    seen = []
    monkeypatch.setattr(brain, "stream", lambda messages, cfg, cancel=None: (seen.append(messages), iter(["Noted."]))[1])
    a = assistant.Assistant(speak=lambda *x: None, stop=lambda: None)
    run(a, "remember that my cat is called Miso")
    cid = a.conv
    assert cid and store.get(cid)["title"] == "remember that my cat is called Miso"
    assert [m["role"] for m in store.get(cid)["messages"]] == ["user", "assistant"] and store.get(cid)["messages"][1]["brain"] == ""
    a.new()
    assert a.conv == "" and a.messages == [] and store.get(cid)                      # a new conversation does not delete the old one
    b = assistant.Assistant(speak=lambda *x: None, stop=lambda: None)                  # after a restart
    assert b.open(cid) and not b.open("nope")
    run(b, "what is my cat called")
    assert seen[-1][0] == {"role": "user", "content": "remember that my cat is called Miso"}     # the saved lines are context again
    assert len(store.get(cid)["messages"]) == 4 and [c["id"] for c in store.conversations()] == [cid]
    assert [c["id"] for c in store.conversations("miso")] == [cid] and store.conversations("100%_x") == []
    assert "**You:** remember" in store.export_md(cid)
    b.rename(cid, "  The   cat ")
    assert store.get(cid)["title"] == "The cat"
    b.forget(cid)
    assert store.get(cid) is None and b.conv == "" and b.messages == []


def test_nothing_is_saved_when_history_is_off(home, monkeypatch):
    monkeypatch.setattr(brain, "stream", lambda messages, cfg, cancel=None: iter(["Sure."]))
    a = assistant.Assistant(cfg_loader=lambda: dict(config.DEFAULTS, retention_days=-1), speak=lambda *x: None, stop=lambda: None)
    run(a, "this is private")
    assert a.conv == "" and len(a.messages) == 2 and store.conversations() == []
    assert not (home / "history.db").exists() or "private" not in (home / "history.db").read_bytes().decode("latin1")


def test_old_conversations_expire_and_delete_all_empties_the_file(home):
    import time
    old = store.create("old one", now=time.time() - 40 * 86400)
    store.add(old, "user", "ancient secret words", now=time.time() - 40 * 86400)
    new = store.create("new one")
    store.add(new, "user", "hello")
    assert store.purge(0) == 0 and store.purge(-1) == 0 and len(store.conversations()) == 2      # 0 and -1 never delete by age
    assert store.purge(30) == 1 and [c["id"] for c in store.conversations()] == [new] and store.get(old) is None
    assert (home / "history.db").stat().st_mode & 0o077 == 0 or __import__("sys").platform.startswith("win")
    store.delete_all()
    assert store.conversations() == [] and b"hello" not in (home / "history.db").read_bytes()
    assert store.add(new, "user", "late line") is False                                           # a deleted conversation is not revived


def test_window_history_endpoints(home, monkeypatch):
    monkeypatch.setattr(brain, "stream", lambda messages, cfg, cancel=None: iter(["Hello there."]))
    monkeypatch.setattr(ui, "voices", lambda: [{"id": "af_bella", "label": "Bella, American woman"}])
    said = []
    a = assistant.Assistant(speak=lambda text, voice, add: said.append(text), stop=lambda: None)
    url, srv = ui.start(a, dict(config.DEFAULTS))
    try:
        token, h = url.split("k=")[1], {"X-Jarvis": "1"}
        run(a, "good morning")
        code, body, _ = call(url, "/conversations", cookie=token)
        rows = json.loads(body)
        assert code == 200 and rows[0]["title"] == "good morning" and rows[0]["n"] == 2
        cid = rows[0]["id"]
        snap = json.loads(call(url, "/conversation", cookie=token)[1])
        assert snap["id"] == cid and [m["text"] for m in snap["messages"]] == ["good morning", "Hello there."]
        assert "**Jarvis:** Hello there." in call(url, "/export?id=" + cid, cookie=token)[1]
        assert call(url, "/export?id=" + cid)[0] == 403                                             # history needs the secret too
        assert call(url, "/again", {"text": "Hello there."}, token, h)[0] == 200 and said[-1] == "Hello there."
        assert call(url, "/preview", {"voice": "zz_nobody"}, token, h)[0] == 400
        assert json.loads(call(url, "/new", {}, token, h)[1])["conversation"]["id"] == ""
        assert json.loads(call(url, "/open", {"id": cid}, token, h)[1])["conversation"]["title"] == "good morning"
        assert call(url, "/open", {"id": "missing"}, token, h)[0] == 404
        assert json.loads(call(url, "/settings", {"retention_days": "7", "speak_answers": False}, token, h)[1])["settings"]["retention_days"] == 7
        assert config.load()["speak_answers"] is False
        assert call(url, "/delete_all", {}, token, h)[0] == 200 and store.conversations() == []
    finally:
        srv.shutdown()
