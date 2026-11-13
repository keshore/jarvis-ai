"""localvoice command line."""
import argparse, json, os, signal, subprocess, sys, time, urllib.request

from . import config, textprep, tts_client

KOKORO_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
KOKORO_FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")
WHISPER = {"small": "mlx-community/whisper-small.en-mlx", "big": "mlx-community/whisper-large-v3-turbo"}


# ---------- processes ----------
def _pidfile():
    return config.path("listener.pid")


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _listener_pid():
    try:
        pid = int(open(_pidfile()).read())
        return pid if _alive(pid) else None
    except (OSError, ValueError):
        return None


def cmd_setup(a):
    config.ensure()
    os.makedirs(config.path("models"), exist_ok=True)
    for f in KOKORO_FILES:
        dest = config.path("models", f)
        if os.path.exists(dest):
            print(f"have {f}")
            continue
        print(f"downloading {f} ...")
        urllib.request.urlretrieve(KOKORO_BASE + f, dest)
    from huggingface_hub import snapshot_download
    for name in (a.models or ["small"]):
        repo = WHISPER.get(name, name)
        print(f"fetching speech model {repo} ...")
        snapshot_download(repo)
    gl = config.path("glossary.txt")
    if not os.path.exists(gl):
        open(gl, "w").write("# one term per line: names Whisper tends to mishear (project names, libraries, people)\n")
    print("setup done. Next: `localvoice start`")


def cmd_start(a):
    if a.model:
        os.environ["LOCALVOICE_STT_MODEL"] = WHISPER.get(a.model, a.model)
    if a.sink:
        os.environ["LOCALVOICE_SINK"] = a.sink
    if a.target:
        config.write_state("target", a.target)
    elif not config.read_state("target"):
        t = os.environ.get("ITERM_SESSION_ID") or os.environ.get("TMUX_PANE") or ""
        if t:
            config.write_state("target", t)
    if a.foreground:
        from . import listener
        return listener.run()
    if _listener_pid():
        print("listener already running")
        return
    config.ensure()
    log = open(config.path("listener.log"), "ab")
    p = subprocess.Popen([sys.executable, "-m", "localvoice.listener"], stdout=log, stderr=log,
                         stdin=subprocess.DEVNULL, start_new_session=True, env=os.environ.copy())
    open(_pidfile(), "w").write(str(p.pid))
    tts_client.ensure_server()
    print(f"started (log: {config.path('listener.log')})")


def cmd_stop(a):
    pid = _listener_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)
    subprocess.run(["pkill", "-f", "localvoice.tts_server"])
    try:
        os.unlink(_pidfile())
    except OSError:
        pass
    print("stopped")


def cmd_status(a):
    print("listener:", "running" if _listener_pid() else "stopped")
    print("voice server:", "running" if tts_client.running() else "stopped")
    print("mode:", textprep.get_mode(), "| sink:", config.load()["sink"], "| target:", config.read_state("target") or "(none)")
    print("enabled sessions:", len(os.listdir(config.path("active"))) if os.path.isdir(config.path("active")) else 0)


# ---------- speaking ----------
def _gate(session):
    return not session or os.path.exists(config.path("active", session))


def cmd_speak(a):
    if os.path.exists(config.path(".mute")) or not _gate(a.session):
        return
    raw = sys.stdin.read()
    if a.claude_hook:
        raw = textprep.claude_hook_message(json.loads(raw or "{}"))
    if not raw.strip():
        return
    key = a.key or config.read_state("target") or os.environ.get("ITERM_SESSION_ID", "") or "default"
    for k in {key, key.split(":")[-1]}:
        textprep.save_last(k, raw)
    tts_client.speak(textprep.speak_text(raw, a.mode))


def cmd_say(a):
    key = a.key or config.read_state("target") or "default"
    raw = textprep.load_last(key) or textprep.load_last(key.split(":")[-1])
    tts_client.speak(textprep.speak_text(raw, a.kind) if raw else "I have nothing to read yet.")


def cmd_mode(a):
    textprep.set_mode(a.mode)
    print("mode:", a.mode)


def cmd_target(a):
    t = a.value or os.environ.get("ITERM_SESSION_ID") or os.environ.get("TMUX_PANE") or ""
    if not t:
        sys.exit("no target: pass one, or run inside iTerm2 / tmux")
    config.write_state("target", t)
    print("target:", t)


# ---------- sessions (used by tool adapters) ----------
def cmd_enable(a):
    os.makedirs(config.path("active"), exist_ok=True)
    open(config.path("active", a.session), "w").close()
    t = a.target or os.environ.get("ITERM_SESSION_ID") or os.environ.get("TMUX_PANE") or ""
    if t:
        config.write_state("target", t)
    print("enabled", a.session)


def cmd_disable(a):
    try:
        os.unlink(config.path("active", a.session))
    except OSError:
        pass
    left = os.listdir(config.path("active")) if os.path.isdir(config.path("active")) else []
    if not left and a.stop_when_idle:
        cmd_stop(a)
    print("disabled", a.session)


def cmd_hook(a):
    """Claude Code hook entry points: localvoice hook claude-stop | claude-prompt | claude-end"""
    d = json.loads(sys.stdin.read() or "{}")
    sid = d.get("session_id", "")
    if not sid:
        return
    if a.event == "claude-end":
        cmd_disable(argparse.Namespace(session=sid, stop_when_idle=True))
        return
    if not os.path.exists(config.path("active", sid)):
        return
    t = os.environ.get("ITERM_SESSION_ID") or os.environ.get("TMUX_PANE") or ""
    if a.event == "claude-prompt":
        if t:
            config.write_state("target", t)
        tts_client.stop()                                  # you are talking now: be quiet
    elif a.event == "claude-stop":
        if os.path.exists(config.path(".mute")):
            return
        raw = textprep.claude_hook_message(d)
        if raw.strip():
            for k in {t, t.split(":")[-1], sid} - {""}:
                textprep.save_last(k, raw)
            tts_client.speak(textprep.speak_text(raw))


def cmd_doctor(a):
    ok = True

    def check(name, cond, hint=""):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  -> {hint}"))
        ok &= bool(cond)

    check("platform is macOS", sys.platform == "darwin", "Linux/Windows backends are not implemented yet")
    for f in KOKORO_FILES:
        check(f"model {f}", os.path.exists(config.path("models", f)), "run `localvoice setup`")
    for mod in ("sounddevice", "soundfile", "kokoro_onnx", "mlx_whisper"):
        try:
            __import__(mod)
            check(f"python module {mod}", True)
        except Exception as e:
            check(f"python module {mod}", False, str(e))
    check("osascript (iterm/keystroke sinks)", subprocess.run(["which", "osascript"], capture_output=True).returncode == 0)
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser(prog="localvoice", description="Local, private, hands-free voice for any AI.")
    sp = ap.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("setup", help="download the speech models"); s.add_argument("--models", nargs="*", help="small big or a HF repo")
    s.set_defaults(f=cmd_setup)
    s = sp.add_parser("start", help="start listening + voice in the background")
    s.add_argument("--model", help="small | big | HF repo"); s.add_argument("--sink"); s.add_argument("--target")
    s.add_argument("-f", "--foreground", action="store_true"); s.set_defaults(f=cmd_start)
    sp.add_parser("stop", help="stop everything").set_defaults(f=cmd_stop)
    sp.add_parser("status").set_defaults(f=cmd_status)
    sp.add_parser("doctor", help="check the installation").set_defaults(f=cmd_doctor)

    s = sp.add_parser("speak", help="read stdin aloud (brief or full per mode)")
    s.add_argument("--mode", choices=["brief", "full"]); s.add_argument("--key"); s.add_argument("--session")
    s.add_argument("--claude-hook", action="store_true", help="stdin is a Claude Code hook payload"); s.set_defaults(f=cmd_speak)
    s = sp.add_parser("say", help="re-read the last reply"); s.add_argument("kind", choices=["brief", "full"])
    s.add_argument("--key"); s.set_defaults(f=cmd_say)
    s = sp.add_parser("mode", help="default for automatic speech"); s.add_argument("mode", choices=["brief", "full"]); s.set_defaults(f=cmd_mode)
    s = sp.add_parser("target", help="send my speech to this terminal/pane"); s.add_argument("value", nargs="?"); s.set_defaults(f=cmd_target)

    s = sp.add_parser("enable", help="mark a session as voice-enabled"); s.add_argument("session"); s.add_argument("--target"); s.set_defaults(f=cmd_enable)
    s = sp.add_parser("disable"); s.add_argument("session"); s.add_argument("--stop-when-idle", action="store_true"); s.set_defaults(f=cmd_disable)
    s = sp.add_parser("hook", help="entry points for tool adapters"); s.add_argument("event", choices=["claude-stop", "claude-prompt", "claude-end"]); s.set_defaults(f=cmd_hook)

    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
