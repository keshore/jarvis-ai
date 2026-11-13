"""Universal CLI adapter (macOS / Linux): `jarvis-ai run -- <any command>`.

Runs any interactive CLI agent (codex, aider, gemini, copilot, ollama run, a REPL...) inside a pseudo-terminal that
passes your keyboard through unchanged. Your spoken sentences are typed into it, and when the program goes quiet
its new output is read aloud. Needs no hooks, no iTerm and no tmux.
Full-screen TUIs redraw a lot, so their output is noisy; prefer a tool's own hook when it has one."""
import os, re, select, shutil, signal, socket, sys, tempfile, time

from . import config, sessions, textprep, tts_client

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Z0-9]|\x1b[=>78]")


def clean_output(raw: bytes) -> str:
    """Terminal bytes -> readable lines (no escapes, redraws collapsed, spinners and box drawing dropped)."""
    t = ANSI.sub("", raw.decode("utf-8", "ignore")).replace("\r\n", "\n")
    lines, prev = [], None
    for ln in t.split("\n"):
        ln = ln.split("\r")[-1]
        ln = "".join(ch for ch in ln if ch >= " " or ch == "\t").strip()
        if not ln or len(re.sub(r"[\W_]", "", ln)) < max(2, len(ln) // 4) or ln == prev:
            continue
        lines.append(ln)
        prev = ln
    return "\n".join(lines)


def run(cmd, speak=True, idle=1.5):
    import fcntl, pty, termios, tty
    sid = f"pty-{os.getpid()}"
    # a short, private (0700) directory: unix socket paths are limited to ~104 characters
    sock_dir = tempfile.mkdtemp(prefix="lv-")
    sock_path = os.path.join(sock_dir, "c.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    srv.listen(4)
    srv.setblocking(False)
    term = os.environ.get("ITERM_SESSION_ID", "").split(":")[-1]
    sessions.register({"id": sid, "sink": "pty", "target": sock_path, "app": "", "term": term,
                       "created": time.time(), "pid": os.getpid()})
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))      # still run the cleanup below

    pid, fd = pty.fork()
    if pid == 0:
        os.execvp(cmd[0], cmd)

    tty_in = sys.stdin.isatty()

    def winch(*_):
        if tty_in:
            size = fcntl.ioctl(sys.stdin.fileno(), termios.TIOCGWINSZ, b"\0" * 8)
            fcntl.ioctl(fd, termios.TIOCSWINSZ, size)

    signal.signal(signal.SIGWINCH, winch)
    winch()
    old = termios.tcgetattr(0) if tty_in else None
    if tty_in:
        tty.setraw(0)

    pending, last_out, awaiting, injected, stdin_open = b"", 0.0, False, "", True
    try:
        while True:
            watch = [fd, srv] + ([0] if stdin_open else [])
            r, _, _ = select.select(watch, [], [], 0.2)
            now = time.time()
            if 0 in r:
                data = os.read(0, 4096)
                if not data:
                    stdin_open = False
                    try:
                        os.write(fd, b"\x04")             # our input ended: tell the program (Ctrl-D)
                    except OSError:
                        pass
                else:
                    os.write(fd, data)
                    if b"\r" in data or b"\n" in data:
                        awaiting, pending, injected = True, b"", ""
            if srv in r:
                conn, _ = srv.accept()
                msg = conn.recv(65536)
                conn.close()
                if msg[:1] == b"T":
                    injected = msg[1:].decode("utf-8", "ignore")
                    os.write(fd, injected.encode() + b"\r")
                    awaiting, pending = True, b""
                elif msg[:1] == b"E":
                    os.write(fd, b"\x1b")
            if fd in r:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                os.write(1, data)
                if awaiting:
                    pending += data
                    last_out = now
            if speak and awaiting and pending and now - last_out > idle:
                text = clean_output(pending)
                lines = text.split("\n")
                if injected and lines and lines[0].strip().endswith(injected.strip()):
                    lines = lines[1:]
                text, awaiting, pending = "\n".join(lines).strip(), False, b""
                if text:
                    textprep.save_last(sid, text)
                    tts_client.speak(textprep.speak_text(text))
    finally:
        if old is not None:
            termios.tcsetattr(0, termios.TCSADRAIN, old)
        sessions.remove(sid)
        srv.close()
        shutil.rmtree(sock_dir, ignore_errors=True)
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass
