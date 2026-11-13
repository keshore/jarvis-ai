import json, os

import pytest

from jarvis_ai import jarvis


@pytest.fixture
def home(tmp_path, monkeypatch):
    import importlib
    monkeypatch.setenv("JARVIS_AI_HOME", str(tmp_path))
    from jarvis_ai import config, sessions, textprep
    importlib.reload(config)
    return tmp_path


CFG = {"name": "jarvis", "focus_follows": True}


@pytest.mark.parametrize("said,rest", [
    ("Jarvis, switch to the portal session.", "switch to the portal session."), ("Hey Jarvis what's open?", "what's open?"),
    ("jarvis", ""), ("OK, Jarvis: status", "status"), ("I told Jarvis to stop", None), ("refactor the jarvis module", None),
    ("Jarvisx do it", None),
])
def test_addressed(said, rest):
    assert jarvis.addressed(said, CFG) == rest
    assert jarvis.addressed(said, {"name": ""}) is None


@pytest.mark.parametrize("rest,want", [
    ("what's open?", ("list", "", "")), ("list my sessions", ("list", "", "")), ("status", ("list", "", "")),
    ("switch to the portal session", ("switch", "the portal session", "")), ("can you go to jarvis", ("switch", "jarvis", "")),
    ("is the portal session done yet?", ("doing", "the portal session", "")), ("what's portal doing", ("doing", "portal", "")),
    ("read the portal session's reply", ("read", "the portal session", "")), ("what did portal say", ("read", "portal", "")),
    ("Ask the portal session to run the Tests in apps/admission.", ("ask", "the portal session", "run the Tests in apps/admission")),
    ("refactor the login form", None), ("ask me anything", None), ("stop", None),
])
def test_parse(rest, want):
    assert jarvis.parse(rest) == want


def reg(home, **kw):
    from jarvis_ai import sessions
    s = {"id": "s1", "agent": "claude", "name": "college-portal-app-88", "cwd": "/w/college-portal-app", "sink": "iterm", "target": "TAB", "busy": False, "pid": os.getpid()}
    s.update(kw)
    sessions.register(s)
    return s


def test_list_status_and_unknown_names(home):
    said = []
    reg(home)
    reg(home, id="s2", name="jarvis-ai-3", cwd="/w/jarvis-ai", busy=True)
    assert jarvis.handle("what's open", CFG, speak=said.append)
    assert said[-1] == "2 sessions. college portal app is idle. jarvis ai is working."
    assert jarvis.handle("is jarvis done", CFG, speak=said.append) and said[-1] == "jarvis ai is still working."
    assert jarvis.handle("switch to banana", CFG, speak=said.append) and "not sure which session" in said[-1]
    assert jarvis.handle("refactor the login form", CFG, speak=said.append) is False        # not Jarvis's: falls through to dictation


def test_ask_types_only_after_approval_and_shows_the_exact_text(home, monkeypatch):
    from jarvis_ai import sinks
    sent, said, seen = [], [], []
    reg(home)
    monkeypatch.setattr(sinks.Iterm, "send", lambda self, text: sent.append((self.target(), text)))

    def deny(p, cfg):
        seen.append((p.action, p.text))
        return False
    assert jarvis.handle("ask portal to delete the old migrations", CFG, speak=said.append, approve=deny, background=False)
    assert sent == [] and said[-1] == "Not sent."
    assert seen == [("send to college portal app", "delete the old migrations")]
    assert jarvis.handle("ask portal to run the tests", CFG, speak=said.append, approve=lambda p, cfg: True, background=False)
    assert sent == [("TAB", "run the tests")] and said[-1] == "Sent to college portal app."


def test_ask_refuses_a_session_it_cannot_reach(home):
    said = []
    reg(home, sink="none", target="")
    assert jarvis.handle("ask portal to run the tests", CFG, speak=said.append, approve=lambda p, cfg: pytest.fail("must not ask"), background=False)
    assert "can't type into" in said[-1]


def test_watcher_reads_replies_without_hooks_and_leaves_plugin_sessions_alone(home, monkeypatch):
    from jarvis_ai import agents, sessions, textprep
    tr = home / "t.jsonl"
    tr.write_text("")
    reg(home, transcript=str(tr))
    reg(home, id="s2", name="other", transcript=str(tr), hooks=True)
    monkeypatch.setattr(jarvis, "sync", lambda: [])
    monkeypatch.setattr(sessions, "current", lambda: sessions.get("s1"))
    spoken = []
    w = jarvis.Watcher(CFG, spoken.append)
    w.step()
    with open(tr, "a") as fh:
        fh.write(json.dumps({"type": "assistant", "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": "All tests pass."}]}}) + "\n")
    w.step()
    assert spoken == ["All tests pass."] and textprep.load_last("s1") == "All tests pass."
    monkeypatch.setattr(sessions, "current", lambda: sessions.get("s2"))                    # looking elsewhere: saved, not spoken
    with open(tr, "a") as fh:
        fh.write(json.dumps({"type": "assistant", "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Second."}]}}) + "\n")
    w.step()
    assert spoken == ["All tests pass."] and textprep.load_last("s1") == "Second."


def test_ask_will_not_type_into_an_app_that_holds_two_sessions(home):
    said = []
    reg(home, sink="keystroke", target="", app="Code")
    reg(home, id="s2", name="jarvis-ai-3", cwd="/w/jarvis-ai", sink="keystroke", target="", app="Code")
    assert jarvis.handle("ask jarvis to run the tests", CFG, speak=said.append, approve=lambda p, cfg: pytest.fail("must not ask"), background=False)
    assert "can't pick the tab" in said[-1]


def test_model_is_chosen_by_memory(monkeypatch):
    from jarvis_ai import llm
    for gb, want in ((8, "1.7B"), (16, "4B"), (24, "8B"), (64, "8B")):
        monkeypatch.setattr(llm, "ram_gb", lambda gb=gb: gb)
        assert want in llm.model_name({"llm_model": "auto"})
    assert llm.model_name({"llm_model": "my/model"}) == "my/model"
