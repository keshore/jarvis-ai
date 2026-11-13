"""localvoice-ai command line."""
import argparse, json, os, subprocess, sys, urllib.request

from . import config, platform_, sessions, textprep, tts_client

KOKORO_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
KOKORO_FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")
JSON_KEYS = ("last_assistant_message", "last-assistant-message", "assistant_message", "message", "text", "output")


# ---------- processes ----------
def _pidfile():
    return config.path("listener.pid")


def _listener_pid():
    try:
        pid = int(config.read_state("listener.pid"))
        return pid if platform_.pid_alive(pid) else None
    except ValueError:
        return None


def _spawn_listener():
    """Start the listener in the background if it is not running. Returns immediately (it loads its own models)."""
    if _listener_pid():
        return False
    config.ensure()
    log = open(config.path("listener.log"), "ab")
    p = subprocess.Popen([sys.executable, "-m", "localvoice_ai.listener"], stdout=log, stderr=log,
                         stdin=subprocess.DEVNULL, env=os.environ.copy(), **platform_.detach_kwargs())
    config.write_state("listener.pid", str(p.pid))
    return True


def _off():
    """True after `localvoice-ai stop`/`off`: automatic start-up stays disabled until `localvoice-ai on`."""
    return os.path.exists(config.path(".off"))


def _clear_off():
    try:
        os.unlink(config.path(".off"))
    except OSError:
        pass


def _interactive():
    """Voice is for sessions you sit in front of, not scripted (`claude -p`) or SDK runs."""
    return (os.environ.get("CLAUDE_CODE_SESSION_ATTENDED", "1") not in ("0", "false")
            and not os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk"))


def _auto_enable(sid):
    """Plugin path: register the session and make sure the listener is running. No command needed."""
    if _off() or not config.load().get("autostart", True) or os.environ.get("LOCALVOICE_AI_DISABLE") or not _interactive():
        return None
    s = sessions.get(sid)
    if not s:
        s = sessions.detect(sid)
        sessions.register(s)
    config.write_state("last_session", sid)
    _spawn_listener()
    return s


def cmd_setup(a):
    from . import llm, stt
    cfg = config.load()
    config.ensure()
    os.makedirs(config.path("models"), exist_ok=True)
    for f in KOKORO_FILES:
        dest = config.path("models", f)
        if os.path.exists(dest):
            print(f"have {f}")
            continue
        print(f"downloading {f} ...")
        urllib.request.urlretrieve(KOKORO_BASE + f, dest)
    for name in (a.models or [cfg["stt_model"]]):
        print(f"fetching speech model '{name}' for the {stt.backend_name(cfg)} backend ...")
        print("  ->", stt.prefetch(cfg, name)[1])
    if a.llm:
        if platform_.APPLE_SILICON and llm._mlx_available():
            from huggingface_hub import snapshot_download
            print(f"fetching local model {cfg['llm_model']} ...")
            snapshot_download(cfg["llm_model"])
        else:
            print(f"optional local LLM: install Ollama (https://ollama.com) and run:  ollama pull {cfg['ollama_model']}")
    gl = config.path("glossary.txt")
    if not os.path.exists(gl):
        with open(gl, "w") as fh:
            fh.write("# one term per line: names Whisper tends to mishear (project names, libraries, people)\n")
    print("setup done. Next: `localvoice-ai start`")


def cmd_start(a):
    if a.model:
        os.environ["LOCALVOICE_AI_STT_MODEL"] = a.model
    if a.sink:
        os.environ["LOCALVOICE_AI_SINK"] = a.sink
    if a.target:
        config.write_state("target", a.target)
    elif not config.read_state("target"):
        t = os.environ.get("ITERM_SESSION_ID") or os.environ.get("TMUX_PANE") or ""
        if t:
            config.write_state("target", t)
    if a.foreground:
        from . import listener
        return listener.run()
    _clear_off()
    if not _spawn_listener():
        print("listener already running")
        return
    tts_client.ensure_server()
    print(f"started (log: {config.path('listener.log')})")


def _stop_processes():
    pid = _listener_pid()
    if pid:
        platform_.kill_pid(pid)
    tts_client.stop_server()
    try:
        os.unlink(_pidfile())
    except OSError:
        pass
    config.write_state("speaking_until", "0")


def cmd_stop(a):
    _stop_processes()
    config.write_state(".off", "1")
    print("stopped. It stays off (sessions will not restart it) until you run `localvoice-ai on`.")


def cmd_on(a):
    cmd_start(argparse.Namespace(model=None, sink=None, target=None, foreground=False))


def cmd_status(a):
    from . import llm, stt
    cfg = config.load()
    print("listener:", "running" if _listener_pid() else "stopped")
    print("voice server:", "running" if tts_client.running() else "stopped")
    print(f"speech-to-text: {stt.backend_name(cfg)} / {stt.model_name(cfg)}   mode: {textprep.get_mode()}")
    print("local LLM (optional):", llm.backend(cfg) or "not available (summaries use the simple rules)")
    ss = sessions.all()
    print(f"sessions: {len(ss)}")
    for s in ss:
        where = s.get("app") or s.get("target", "")
        print(f"  {s['id'][:8]}  {s['sink']:9} {where}")


def cmd_sessions(a):
    cmd_status(a)


# ---------- speaking ----------
def _muted():
    return os.path.exists(config.path(".mute"))


def cmd_speak(a):
    if _muted() or (a.session and not sessions.get(a.session)):
        return
    raw = sys.stdin.read()
    if a.claude_hook:
        raw = textprep.claude_hook_message(json.loads(raw or "{}"))
    if not raw.strip():
        return
    key = a.key or a.session or config.read_state("target") or "default"
    for k in {key, key.split(":")[-1], "default"}:
        textprep.save_last(k, raw)
    tts_client.speak(textprep.speak_text(raw, a.mode))


def cmd_summarize(a):
    """Summarize stdin with the optional local model and print it (--speak reads it aloud)."""
    from . import llm
    out = llm.summarize(sys.stdin.read(), config.load())
    print(out)
    if a.speak:
        tts_client.speak(out)


def cmd_say(a):
    cur = sessions.current()
    key = a.key or (cur["id"] if cur else "") or config.read_state("target") or "default"
    raw = textprep.load_last(key) or textprep.load_last(key.split(":")[-1]) or textprep.load_last("default")
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
    s = sessions.detect(a.session, a.sink or "", a.target or "", a.app or "")
    sessions.register(s)
    config.write_state("last_session", a.session)
    where = s["app"] or s["target"] or "?"
    print(f"enabled {a.session[:8]} ({s['sink']}: {where})")


def cmd_disable(a):
    sessions.remove(a.session)
    if not sessions.all() and getattr(a, "stop_when_idle", False):
        _stop_processes()
    print("disabled", a.session)


def _dig(d, path):
    for part in path.split("."):
        d = d.get(part) if isinstance(d, dict) else None
    return d if isinstance(d, str) else ""


def _hook_json(a):
    """Generic hook: any tool that can run a command with a JSON payload (stdin or last argument)."""
    payload = a.payload or sys.stdin.read()
    try:
        d = json.loads(payload)
    except ValueError:
        d = {"text": payload}
    raw = _dig(d, a.field) if a.field else next(
        (d[k] for k in JSON_KEYS if isinstance(d, dict) and isinstance(d.get(k), str) and d[k].strip()), "")
    if not raw.strip() or _muted() or (a.session and not sessions.get(a.session)):
        return
    for k in {a.session or "default", "default", config.read_state("target")} - {""}:
        textprep.save_last(k, raw)
    tts_client.speak(textprep.speak_text(raw))


def cmd_hook(a):
    """Entry points for tool adapters: claude-start | claude-prompt | claude-stop | claude-end | json"""
    if a.event == "json":
        return _hook_json(a)
    d = json.loads(a.payload or sys.stdin.read() or "{}")
    sid = d.get("session_id", "")
    if not sid:
        return
    if a.event == "claude-end":
        cmd_disable(argparse.Namespace(session=sid, stop_when_idle=True))
        return
    if a.event == "claude-start":
        _auto_enable(sid)
        return
    s = sessions.get(sid) or (_auto_enable(sid) if a.event == "claude-prompt" else None)
    if not s:
        return
    if a.event == "claude-prompt":
        sessions.refresh(s)                                # it is in front right now: re-learn where it lives
        config.write_state("last_session", sid)
        if not _off():
            _spawn_listener()                              # e.g. after a reboot or a crash
        tts_client.stop()                                  # you are talking now: be quiet
    elif a.event == "claude-stop":
        if _muted():
            return
        raw = textprep.claude_hook_message(d)
        if not raw.strip():
            return
        for k in {sid, s.get("term", ""), s.get("target", "")} - {""}:
            textprep.save_last(k, raw)
        cfg = config.load()
        if cfg.get("focus_follows", True):
            cur = sessions.current()
            if cur and cur["id"] != sid:
                return                                     # you are looking elsewhere: stay quiet (reply is saved)
        tts_client.speak(textprep.speak_text(raw))


def cmd_run(a):
    cmd = [c for c in a.command if c != "--"] if a.command and a.command[0] == "--" else a.command
    if not cmd:
        sys.exit("usage: localvoice-ai run [--no-speak] -- <command> [args...]")
    if platform_.IS_WIN:
        sys.exit("`localvoice-ai run` needs a Unix pseudo-terminal (macOS, Linux, or WSL on Windows).")
    from . import ptyrun
    ptyrun.run(cmd, speak=not a.no_speak, idle=a.idle)


def cmd_doctor(a):
    from . import stt
    cfg = config.load()
    ok = True

    def check(name, cond, hint="", required=True):
        nonlocal ok
        print(("ok   " if cond else ("FAIL " if required else "info ")) + name + ("" if cond else f"  -> {hint}"))
        if required:
            ok &= bool(cond)

    print(f"platform: {sys.platform}, python {sys.version.split()[0]}, speech backend: {stt.backend_name(cfg)}")
    for f in KOKORO_FILES:
        check(f"voice model {f}", os.path.exists(config.path("models", f)), "run `localvoice-ai setup`")
    mods = ["sounddevice", "kokoro_onnx", "pysilero_vad", "mlx_whisper" if stt.backend_name(cfg) == "mlx" else "faster_whisper"]
    for mod in mods:
        try:
            __import__(mod)
            check(f"python module {mod}", True)
        except Exception as e:
            check(f"python module {mod}", False, str(e))
    try:
        import sounddevice as sd
        d = sd.default.device
        check("microphone", d[0] is not None and d[0] >= 0 and sd.query_devices(d[0])["max_input_channels"] > 0, "no input device")
        check("speakers", d[1] is not None and d[1] >= 0 and sd.query_devices(d[1])["max_output_channels"] > 0, "no output device")
    except Exception as e:
        check("audio devices", False, f"{e} (Linux: install PortAudio, e.g. apt install libportaudio2)")
    from . import llm
    check("local LLM", llm.backend(cfg) is not None, "optional: Apple Silicon `pip install 'localvoice-ai[llm]'`, or install Ollama", required=False)
    for tool, why in (("tmux", "tmux sink"), ("osascript", "iterm/keystroke sinks (macOS)"),
                      ("xdotool", "window detection on Linux/X11")):
        import shutil
        check(f"{tool} ({why})", shutil.which(tool) is not None, "only needed for that feature", required=False)
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser(prog="localvoice-ai", description="Local, private, hands-free voice for any AI agent.")
    sp = ap.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("setup", help="download the speech models")
    s.add_argument("--models", nargs="*", help="model names to download (default: the big model)")
    s.add_argument("--llm", action="store_true", help="also set up the optional local LLM")
    s.set_defaults(f=cmd_setup)
    s = sp.add_parser("start", help="start listening + voice in the background")
    s.add_argument("--model", help="explicit model name (default: the big model)"); s.add_argument("--sink"); s.add_argument("--target")
    s.add_argument("-f", "--foreground", action="store_true"); s.set_defaults(f=cmd_start)
    sp.add_parser("stop", help="stop everything and keep it off").set_defaults(f=cmd_stop)
    sp.add_parser("off", help="same as stop").set_defaults(f=cmd_stop)
    sp.add_parser("on", help="turn voice back on").set_defaults(f=cmd_on)
    sp.add_parser("status").set_defaults(f=cmd_status)
    sp.add_parser("sessions", help="list voice-enabled sessions").set_defaults(f=cmd_sessions)
    sp.add_parser("doctor", help="check the installation").set_defaults(f=cmd_doctor)

    s = sp.add_parser("speak", help="read stdin aloud (brief or full per mode)")
    s.add_argument("--mode", choices=["brief", "full"]); s.add_argument("--key"); s.add_argument("--session")
    s.add_argument("--claude-hook", action="store_true", help="stdin is a Claude Code hook payload"); s.set_defaults(f=cmd_speak)
    s = sp.add_parser("summarize", help="summarize stdin with the optional local model")
    s.add_argument("--speak", action="store_true"); s.set_defaults(f=cmd_summarize)
    s = sp.add_parser("say", help="re-read the last reply"); s.add_argument("kind", choices=["brief", "full"])
    s.add_argument("--key"); s.set_defaults(f=cmd_say)
    s = sp.add_parser("mode", help="default for automatic speech"); s.add_argument("mode", choices=["brief", "full"]); s.set_defaults(f=cmd_mode)
    s = sp.add_parser("target", help="send my speech to this terminal/pane"); s.add_argument("value", nargs="?"); s.set_defaults(f=cmd_target)

    s = sp.add_parser("enable", help="mark a session as voice-enabled")
    s.add_argument("session"); s.add_argument("--sink", choices=["iterm", "tmux", "keystroke", "pty"])
    s.add_argument("--target"); s.add_argument("--app", help="keystroke sink: window/app that has the session")
    s.set_defaults(f=cmd_enable)
    s = sp.add_parser("disable"); s.add_argument("session"); s.add_argument("--stop-when-idle", action="store_true"); s.set_defaults(f=cmd_disable)
    s = sp.add_parser("hook", help="entry points for tool adapters")
    s.add_argument("event", choices=["claude-start", "claude-stop", "claude-prompt", "claude-end", "json"])
    s.add_argument("payload", nargs="?", help="json event: payload as an argument (else read from stdin)")
    s.add_argument("--field", help="json event: dotted path of the reply text (default: a few common names)")
    s.add_argument("--session"); s.set_defaults(f=cmd_hook)
    s = sp.add_parser("run", help="run ANY interactive CLI with voice in and out")
    s.add_argument("--no-speak", action="store_true"); s.add_argument("--idle", type=float, default=1.5)
    s.add_argument("command", nargs=argparse.REMAINDER); s.set_defaults(f=cmd_run)

    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
