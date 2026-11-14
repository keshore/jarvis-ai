"""jarvis-ai command line."""
import argparse, os, subprocess, sys, time, urllib.request

from . import config, platform_, tts_client

KOKORO_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
KOKORO_FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")


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
    p = subprocess.Popen([sys.executable, "-m", "jarvis_ai.listener"], stdout=log, stderr=log,
                         stdin=subprocess.DEVNULL, env=os.environ.copy(), **platform_.detach_kwargs())
    config.write_state("listener.pid", str(p.pid))
    return True


def _off():
    """True after `jarvis-ai off`: automatic start-up stays disabled until `jarvis-ai on`."""
    return os.path.exists(config.path(".off"))


def _clear_off():
    try:
        os.unlink(config.path(".off"))
    except OSError:
        pass


LLAMA_WHEELS = "https://abetlen.github.io/llama-cpp-python/whl/cpu"      # llama-cpp-python's own prebuilt wheels, so nothing has to compile


def _pip_llama():
    """Install the built-in engine into this environment. Prebuilt wheel first; never fatal."""
    print("installing the built-in LLM engine (llama.cpp) ...")
    r = platform_.run([sys.executable, "-m", "pip", "install", "--quiet", "--prefer-binary", "--extra-index-url", LLAMA_WHEELS,
                       "llama-cpp-python"], timeout=1800)
    import importlib
    importlib.invalidate_caches()
    return bool(r and r.returncode == 0)


def _install_ollama(ask=input):
    """Offer to install Ollama with the system's own installer. Nothing is installed without a typed yes."""
    import shutil
    if platform_.IS_WIN and shutil.which("winget"):
        cmd, shown = ["winget", "install", "-e", "--id", "Ollama.Ollama"], "winget install -e --id Ollama.Ollama"
    elif platform_.IS_MAC and shutil.which("brew"):
        cmd, shown = ["brew", "install", "ollama"], "brew install ollama"
    elif platform_.IS_LINUX and shutil.which("curl"):
        cmd, shown = ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"], "curl -fsSL https://ollama.com/install.sh | sh   (asks for your password)"
    else:
        print("  install Ollama from https://ollama.com, then run `jarvis-ai setup --llm` again")
        return False
    if not sys.stdin.isatty():
        print(f"  to install Ollama run:  {shown}\n  then `jarvis-ai setup --llm` again")
        return False
    if ask(f"  Install Ollama now with:  {shown}  ? [y/N] ").strip().lower() not in ("y", "yes"):
        return False
    return subprocess.run(cmd).returncode == 0 and shutil.which("ollama") is not None


def _setup_llm(cfg, llm):
    """The optional local LLM. Apple Silicon: MLX. Elsewhere: llama.cpp built in; if that cannot be installed or run, Ollama."""
    import shutil
    if platform_.APPLE_SILICON and llm._mlx_available():
        from huggingface_hub import snapshot_download
        print(f"fetching local model {llm.model_name(cfg)} ...")
        snapshot_download(llm.model_name(cfg))
        return
    if cfg.get("llm_backend", "auto") in ("auto", "llamacpp") and (llm._llama_available() or (_pip_llama() and llm._llama_available())):
        try:
            print(f"fetching local model {llm.gguf_name(cfg)} ...")
            llm.gguf_path(cfg, download=True)
            llm._gen_llama([{"role": "user", "content": "Say OK."}], cfg, 8)       # prove it loads and answers on this machine
            print("  built-in engine works")
            return
        except Exception as e:
            print(f"  the built-in engine failed here ({e}); using Ollama instead")
    else:
        print("  the built-in engine could not be installed here; using Ollama instead")
    name = llm.ollama_name(cfg)
    if not shutil.which("ollama") and not _install_ollama():
        return
    print(f"fetching local model {name} through Ollama ...")
    if subprocess.run(["ollama", "pull", name]).returncode != 0:
        print(f"  could not fetch it. Start Ollama, then run:  ollama pull {name}")


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
        _setup_llm(cfg, llm)
    gl = config.path("glossary.txt")
    if not os.path.exists(gl):
        with open(gl, "w") as fh:
            fh.write("# one term per line: names Whisper tends to mishear (project names, libraries, people)\n")
    from . import models
    print("\n".join(models.report(cfg)))
    print("setup done. Next: `jarvis-ai on`")


def cmd_on(a):
    if getattr(a, "login", False) and _off():
        return
    if a.model:
        os.environ["JARVIS_AI_STT_MODEL"] = a.model
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
    for f in (_pidfile(), config.path("ui.url")):
        try:
            os.unlink(f)
        except OSError:
            pass
    config.write_state("speaking_until", "0")


def cmd_open(a=None):
    """What a bare `jarvis-ai` does: turn it on if needed and open the window."""
    import webbrowser
    if not _listener_pid():
        _clear_off()
        _spawn_listener()
        print("starting Jarvis (the first start loads the models) ...")
    for _ in range(360):
        url = config.read_state("ui.url")
        if url and _listener_pid():
            webbrowser.open(url)
            print("Jarvis is open in your browser. `jarvis-ai off` stops it.")
            return
        time.sleep(0.5)
    print(f"Jarvis did not start. See {config.path('listener.log')}")


def cmd_stop(a):
    _stop_processes()
    config.write_state(".off", "1")
    print("stopped. It stays off until you run `jarvis-ai` or `jarvis-ai on`.")


def cmd_login(a):
    """Start at login: a per-user entry that runs `jarvis-ai on` unless you turned it off."""
    p = platform_.login_file()
    if a.state == "on":
        platform_.set_login([sys.executable, "-m", "jarvis_ai.cli", "on", "--login"])
        print(f"Jarvis starts when you log in ({p}).\nIt stays off if you ran `jarvis-ai off`. Undo with `jarvis-ai login off`.")
    elif a.state == "off":
        platform_.set_login(None)
        print("Jarvis no longer starts at login.")
    else:
        print(f"start at login: {'on' if os.path.exists(p) else 'off'} ({p})")


def cmd_status(a):
    from . import models
    cfg = config.load()
    print("listener:", "running" if _listener_pid() else "stopped")
    print("voice server:", "running" if tts_client.running() else "stopped")
    print("\n".join(models.report(cfg)))
    from . import brain
    print(f"answers come from: {brain.describe(cfg)}")


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
    from . import models
    for r in models.rows(cfg):
        gb = f", {r['bytes'] / 1e9:.1f} GB" if r["bytes"] else ""
        check(f"{r['job']}: {r['model']} on {r['engine']}{gb}", r["ready"], r["note"], required=r["job"] != "local LLM")
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
    sys.exit(0 if ok else 1)


HELP_TOP = """Jarvis: a voice assistant on your own computer. Run `jarvis-ai` with nothing after it to open its window.

  setup       one-time download of the speech models (about 2 GB); --llm also sets up the local model
  doctor      check the microphone, speakers and models
  on / off    start it in the background, or stop everything and keep it off
  status      what is running, which models, where answers come from
  login on    start by itself when you log in (login off undoes it)

while talking, say "stop" to silence it, or just start talking over it.
"""
HELP_END = """'jarvis-ai <command> -h' shows the options of one command.
files: ~/.jarvis-ai/config.toml, listener.log, tts.log      docs: https://github.com/mintlime-in/jarvis-ai"""


def _suggest(choices):
    """Unknown or abbreviated command: say what was probably meant instead of listing everything."""
    import difflib
    if len(sys.argv) < 2 or sys.argv[1].startswith("-") or sys.argv[1] in choices:
        return
    w = sys.argv[1]
    near = [c for c in choices if c.startswith(w)] or difflib.get_close_matches(w, list(choices), n=2, cutoff=0.5)
    shown = " or ".join(f"'{c}'" for c in near[:3])
    sys.exit(f"jarvis-ai: unknown command '{w}'" + (f" (did you mean {shown}?)" if near else "") + "\nrun 'jarvis-ai -h' for the commands")


def main():
    ap = argparse.ArgumentParser(prog="jarvis-ai", description=HELP_TOP, epilog=HELP_END,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True, metavar="<command>", title=argparse.SUPPRESS)

    s = sp.add_parser("setup", help="download the speech models")
    s.add_argument("--models", nargs="*", help="model names to download (default: the big model)")
    s.add_argument("--llm", action="store_true", help="also set up the optional local LLM")
    s.set_defaults(f=cmd_setup)
    s = sp.add_parser("on", help="turn voice on")
    s.add_argument("--model", help="speech model name (default: the big model)")
    s.add_argument("-f", "--foreground", action="store_true", help="run in this terminal and show the log")
    s.add_argument("--login", action="store_true", help=argparse.SUPPRESS)      # set by the login entry: do nothing if you turned it off
    s.set_defaults(f=cmd_on)
    sp.add_parser("off", help="stop everything and keep it off").set_defaults(f=cmd_stop)
    sp.add_parser("status", help="what is running, which models").set_defaults(f=cmd_status)
    s = sp.add_parser("login", help="start at login: on | off"); s.add_argument("state", nargs="?", choices=["on", "off", "status"], default="status")
    s.set_defaults(f=cmd_login)
    sp.add_parser("doctor", help="check the installation").set_defaults(f=cmd_doctor)


    ap._subparsers._group_actions.clear(); sp._choices_actions = []   # the grouped text above replaces argparse's flat list; every command stays callable
    if len(sys.argv) == 1:
        return cmd_open()
    _suggest(sp.choices)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
