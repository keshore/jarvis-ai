import pytest

from jarvis_ai import intent, llm


@pytest.mark.parametrize("phrase,kind", [
    ("read me the whole thing", "full"), ("can you read all of it out loud", "full"), ("say it all", "full"),
    ("give me the short version please", "brief"), ("summarize it quickly", "brief"), ("tell me the gist", "brief"),
    ("read the auth file", None), ("read me the whole auth file", None), ("fix the bug in the summary page", None),
    ("what is the weather", None), ("read", None),
])
def test_loose(phrase, kind):
    assert intent.loose(phrase) == kind


CFG = {"frontend": "commands", "frontend_timeout": 2}


def fake(monkeypatch, reply):
    monkeypatch.setattr(llm, "usable", lambda cfg: True)
    monkeypatch.setattr(llm, "generate", lambda messages, cfg, n=None: reply() if callable(reply) else reply)


def test_builtin_and_loose_need_no_model(monkeypatch):
    monkeypatch.setattr(llm, "usable", lambda cfg: (_ for _ in ()).throw(AssertionError("model must not be used")))
    assert intent.interpret("stop", CFG) == ("command", "stop")
    assert intent.interpret("read me the whole thing", CFG) == ("command", "full")


def test_no_model_forwards_unchanged(monkeypatch):
    monkeypatch.setattr(llm, "usable", lambda cfg: False)
    assert intent.interpret("could you maybe give me the long version", CFG) == ("forward", "could you maybe give me the long version")


def test_model_interprets_a_short_unusual_request(monkeypatch):
    fake(monkeypatch, 'Sure: {"action": "full", "text": "", "say": ""}')
    assert intent.interpret("I would like to hear everything it said", CFG) == ("command", "full")


@pytest.mark.parametrize("reply", ["no json at all", '{"action": "rm -rf", "text": "x"}', "{broken", "", '{"action": "forward"}'])
def test_bad_or_unsure_model_output_forwards_the_original(monkeypatch, reply):
    fake(monkeypatch, reply)
    assert intent.interpret("refactor the login form", CFG) == ("forward", "refactor the login form")


def test_model_failure_and_timeout_fail_open(monkeypatch):
    def boom():
        raise RuntimeError("model crashed")
    fake(monkeypatch, boom)
    assert intent.interpret("refactor the login form", CFG)[0] == "forward"
    import time
    fake(monkeypatch, lambda: time.sleep(5))
    assert intent.interpret("refactor the login form", {**CFG, "frontend_timeout": 0.2}) == ("forward", "refactor the login form")


def test_long_sentences_skip_the_model_at_commands_level(monkeypatch):
    fake(monkeypatch, '{"action": "stop"}')
    long = "please refactor the login form so that it validates the email address before it submits anything"
    assert intent.interpret(long, CFG) == ("forward", long)


def test_assistant_level_cleans_but_never_invents_replies(monkeypatch):
    acfg = {"frontend": "assistant", "frontend_timeout": 2}
    fake(monkeypatch, '{"action": "answer", "say": "I know the answer to everything."}')           # no free-form answers exist any more
    assert intent.interpret("what does the stop function do", acfg) == ("forward", "what does the stop function do")
    fake(monkeypatch, '{"action": "help"}')
    assert intent.interpret("what can you do", acfg) == ("command", "help")
    fake(monkeypatch, '{"action": "help"}')
    assert intent.interpret("what does the stop function do", acfg) == ("forward", "what does the stop function do")   # model misroute caught
    fake(monkeypatch, '{"action": "forward", "text": "Fix the login form."}')
    assert intent.interpret("fix the log in form", acfg) == ("forward", "Fix the login form.")
    assert intent.interpret("fix the log in form", CFG) == ("forward", "fix the log in form")      # cleaning is assistant-level only
    fake(monkeypatch, '{"action": "forward", "text": "Delete the production database."}')          # rewrite drifts too far
    assert intent.interpret("fix the log in form", acfg) == ("forward", "fix the log in form")


def test_a_one_off_request_does_not_change_the_default(monkeypatch):
    fake(monkeypatch, '{"action": "mode_full"}')
    assert intent.interpret("I would like to hear everything it said", CFG) == ("command", "full")
    fake(monkeypatch, '{"action": "mode_brief"}')
    assert intent.interpret("from now on just the highlights", CFG) == ("command", "mode_brief")
