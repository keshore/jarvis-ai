import json, os

from jarvis_ai import agents


def line(kind, text=None, stop=None, side=False, tool=False):
    content = [{"type": "tool_use", "name": "Bash"}] if tool else [{"type": "text", "text": text}]
    return json.dumps({"type": kind, "isSidechain": side, "message": {"role": kind, "stop_reason": stop, "content": content}}) + "\n"


def test_tail_reads_only_new_finished_replies(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(line("assistant", "old reply", "end_turn"))
    t = agents.Tail(str(p))
    assert t.poll() == []                                                 # history is not re-read
    with open(p, "a") as fh:
        fh.write(line("user", "do it") + line("assistant", "working on it", "tool_use") + line("assistant", tool=True, stop="tool_use"))
    assert t.poll() == []                                                 # turn not finished
    with open(p, "a") as fh:
        fh.write(line("assistant", "sub agent says hi", "end_turn", side=True) + line("assistant", "All done.", "end_turn"))
    assert t.poll() == ["All done."] and t.poll() == []


def test_tail_waits_for_a_half_written_line_and_survives_garbage(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text("")
    t = agents.Tail(str(p))
    t.poll()
    full = line("assistant", "Finished.", "end_turn")
    with open(p, "a") as fh:
        fh.write("not json\n" + full[:30])
    assert t.poll() == []
    with open(p, "a") as fh:
        fh.write(full[30:])
    assert t.poll() == ["Finished."]
    assert agents.Tail(str(tmp_path / "missing.jsonl")).poll() == []


def test_claude_sessions_come_from_claudes_own_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    (tmp_path / "sessions").mkdir()
    me = os.getpid()
    (tmp_path / "sessions" / f"{me}.json").write_text(json.dumps({"pid": me, "sessionId": "abc", "cwd": "/w/college-portal-app", "name": "portal-1", "status": "busy", "kind": "interactive"}))
    (tmp_path / "sessions" / "1.json").write_text(json.dumps({"pid": 99999999, "sessionId": "dead", "cwd": "/x"}))
    (tmp_path / "sessions" / "2.json").write_text(json.dumps({"pid": me, "sessionId": "bg", "cwd": "/x", "kind": "background"}))
    (tmp_path / "sessions" / "3.json").write_text("{broken")
    monkeypatch.setattr(agents, "_tty_of", lambda pid: "/dev/ttys009")
    monkeypatch.setattr(agents, "app_of", lambda pid: "")
    ss = agents.claude_sessions(iterm={"/dev/ttys009": "TAB-1"}, tmux={})
    assert [s["id"] for s in ss] == ["abc"]
    s = ss[0]
    assert (s["sink"], s["target"], s["busy"], s["name"]) == ("iterm", "TAB-1", True, "portal-1")
    assert s["transcript"].endswith(os.path.join("projects", "-w-college-portal-app", "abc.jsonl"))
    assert agents.claude_sessions(iterm={"/dev/ttys009": "TAB-1"}, tmux={"/dev/ttys009": "%4"})[0]["sink"] == "tmux"      # pane inside a tab
    assert agents.claude_sessions(iterm={}, tmux={})[0]["sink"] == ""                                                     # readable, not reachable


def test_find_by_spoken_name_never_guesses():
    ss = [{"id": "1", "name": "college-portal-app-88", "cwd": "/w/college-portal-app"}, {"id": "2", "name": "jarvis-ai-3", "cwd": "/w/jarvis-ai"},
          {"id": "3", "name": "portal-docs", "cwd": "/w/portal-docs"}]
    assert agents.find("the jarvis session", ss)["id"] == "2"
    assert agents.find("college portal", ss)["id"] == "1"
    assert agents.find("portal", ss) is None                 # two sessions match equally: ask, do not guess
    assert agents.find("the session", ss) is None and agents.find("banana", ss) is None


def test_a_session_in_any_other_app_is_reached_through_that_app(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    (tmp_path / "sessions").mkdir()
    me = os.getpid()
    (tmp_path / "sessions" / f"{me}.json").write_text(json.dumps({"pid": me, "sessionId": "abc", "cwd": "/w/x", "kind": "interactive"}))
    monkeypatch.setattr(agents, "_tty_of", lambda pid: "/dev/ttys009")
    monkeypatch.setattr(agents, "app_of", lambda pid: "Code")
    s = agents.claude_sessions(iterm={}, tmux={})[0]
    assert (s["sink"], s["app"]) == ("keystroke", "Code")
    monkeypatch.setattr(agents, "app_of", lambda pid: "")
    assert agents.claude_sessions(iterm={}, tmux={})[0]["sink"] == ""


def test_context_reaches_back_for_what_was_asked_about(tmp_path):
    p = tmp_path / "c.jsonl"
    turns = [("user", "who is the president"), ("assistant", "Donald Trump is the President. He began his second term in 2025.")]
    for i in range(12):
        turns += [("user", f"question {i}"), ("assistant", f"Filler reply number {i}. " + "Nothing relevant here. " * 30)]
    p.write_text("".join(json.dumps({"type": k, "message": {"content": [{"type": "text", "text": t}]}}) + "\n" for k, t in turns))
    recent = agents.claude_context(str(p), 2500)
    assert "Trump" not in recent and "number 11" in recent                     # plain: only the newest fits
    found = agents.claude_context(str(p), 2500, query="tell me about Donald Trump from the history")
    assert "second term in 2025" in found and "number 11" in found and "older parts left out" in found
    assert found.index("Trump") < found.index("number 11")                      # still in order
