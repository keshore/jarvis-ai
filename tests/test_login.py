import os

from jarvis_ai import platform_


def test_login_entry_written_and_removed(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path)); monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    p = platform_.set_login(["/x/python", "-m", "jarvis_ai.cli", "on", "--login"])
    assert str(tmp_path) in p and "--login" in open(p).read()
    if platform_.IS_MAC:
        import plistlib
        d = plistlib.load(open(p, "rb"))
        assert d["ProgramArguments"][-2:] == ["on", "--login"] and d["RunAtLoad"] is True
    platform_.set_login(None)
    assert not os.path.exists(p)
    platform_.set_login(None)                                         # removing twice is fine
