import json, os, subprocess

import pytest

from jarvis_ai import gate


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_AI_HOME", str(tmp_path))
    import importlib
    from jarvis_ai import config
    importlib.reload(config)
    importlib.reload(gate)
    return tmp_path


@pytest.mark.parametrize("t,ok", [("yes", True), ("Yes, please.", True), ("send it!", True), ("go ahead", True),
                                  ("yes but also delete everything", False), ("no", False), ("maybe", False),
                                  ("yes yes yes", False), ("I said yes earlier", False), ("", False)])
def test_is_yes_is_strict(t, ok):
    assert gate.is_yes(t) is ok


def test_voice_approval_is_one_shot_and_expires():
    now = [100.0]
    v = gate.VoiceApproval(window=10, clock=lambda: now[0])
    assert v.hear("yes") is False                           # nothing pending: not consumed, approves nothing
    v.offer(gate.Proposal("send", "x"))
    assert v.hear("what time is it") is False               # unrelated speech does not answer it
    assert v.hear("yes") is True and v._ok is True
    assert v.hear("yes") is False                           # one shot: a second yes approves nothing
    v.offer(gate.Proposal("send", "x"))
    now[0] += 11
    assert v.hear("yes") is False                           # expired
    v.offer(gate.Proposal("send", "x"))
    assert v.hear("cancel") is True and v._ok is False


def fake_run(monkeypatch, out="", code=0, boom=None):
    def run(cmd, **kw):
        if boom:
            raise boom
        run.cmd = cmd
        return subprocess.CompletedProcess(cmd, code, out, "")
    monkeypatch.setattr(gate.subprocess, "run", run)
    return run


def test_dialog_only_an_explicit_approve_counts(monkeypatch):
    monkeypatch.setattr(gate.sys, "platform", "darwin")
    for out, want in (("Approve\n", True), ("Cancel\n", False), ("timeout\n", False), ("", False), ("approve!\n", False)):
        fake_run(monkeypatch, out)
        assert gate.approve(gate.Proposal("send", "fix it")) is want, out


def test_dialog_failure_and_unsupported_platform_deny(monkeypatch):
    monkeypatch.setattr(gate.sys, "platform", "darwin")
    fake_run(monkeypatch, boom=OSError("no osascript"))
    assert gate.approve(gate.Proposal("send", "x")) is False
    monkeypatch.setattr(gate.sys, "platform", "win32")
    assert gate.approve(gate.Proposal("send", "x")) is False


def test_text_is_passed_as_an_argument_not_spliced_into_the_script(monkeypatch):
    monkeypatch.setattr(gate.sys, "platform", "darwin")
    run = fake_run(monkeypatch, "Cancel")
    nasty = 'x" & (do shell script "touch /tmp/pwned") & "'
    gate.approve(gate.Proposal("send", nasty))
    assert nasty in run.cmd and nasty not in run.cmd[2]


def test_too_long_to_review_is_refused_without_showing_anything(monkeypatch):
    run = fake_run(monkeypatch, "Approve")
    assert gate.approve(gate.Proposal("send", "a" * (gate.MAX_REVIEW_CHARS + 1))) is False
    assert not hasattr(run, "cmd")


def test_voice_mode_speaks_the_exact_text_and_needs_a_yes():
    said, v = [], gate.VoiceApproval(window=0.3)
    p = gate.Proposal("send", "refactor the login form")
    import threading
    threading.Timer(0.05, lambda: v.hear("yes")).start()
    assert gate.approve(p, {"approval": "voice"}, voice=v, speak=said.append) is True
    assert "refactor the login form" in said[0]
    assert gate.approve(gate.Proposal("send", "y"), {"approval": "voice"}, voice=v, speak=said.append) is False     # silence is no


def test_audit_log_records_and_is_private(home, monkeypatch):
    monkeypatch.setattr(gate.sys, "platform", "darwin")
    fake_run(monkeypatch, "Cancel")
    gate.approve(gate.Proposal("send", "hello"))
    path = home / "audit.log"
    events = [json.loads(l)["event"] for l in path.read_text().splitlines()]
    assert events == ["proposed", "denied"]
    if os.name != "nt":                                         # Windows has no unix permission bits
        assert oct(os.stat(path).st_mode)[-3:] == "600"
