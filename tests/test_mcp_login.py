import io, json, os

from jarvis_ai import mcp, platform_


def rpc(*msgs, **kw):
    out = io.StringIO()
    mcp.serve(io.StringIO("\n".join(m if isinstance(m, str) else json.dumps(m) for m in msgs) + "\n"), out, **kw)
    return [json.loads(l) for l in out.getvalue().splitlines()]


def test_mcp_handshake_and_speak():
    said, stopped = [], []
    r = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "speak", "arguments": {"text": "Build is green."}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "stop_speaking"}},
            speak=said.append, stop=lambda: stopped.append(1))
    assert [x["id"] for x in r] == [1, 2, 3, 4]                       # the notification got no reply
    assert r[0]["result"]["serverInfo"]["name"] == "jarvis-ai"
    assert {t["name"] for t in r[1]["result"]["tools"]} == {"speak", "stop_speaking"}
    assert said == ["Build is green."] and r[2]["result"]["isError"] is False and stopped == [1]


def test_mcp_bad_input_is_an_error_not_a_crash():
    said = []
    r = rpc("not json", {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "speak", "arguments": {"text": 5}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "type_keys", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 3, "method": "nope"}, [1], speak=said.append)
    assert r[0]["error"]["code"] == -32700 and r[1]["result"]["isError"] and r[2]["result"]["isError"]
    assert r[3]["error"]["code"] == -32601 and r[4]["error"]["code"] == -32600 and said == []


def test_login_entry_written_and_removed(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path)); monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    p = platform_.set_login(["/x/python", "-m", "jarvis_ai.cli", "login-start"])
    assert str(tmp_path) in p and "login-start" in open(p).read()
    if platform_.IS_MAC:
        import plistlib
        d = plistlib.load(open(p, "rb"))
        assert d["ProgramArguments"][-1] == "login-start" and d["RunAtLoad"] is True
    platform_.set_login(None)
    assert not os.path.exists(p)
    platform_.set_login(None)                                         # removing twice is fine
