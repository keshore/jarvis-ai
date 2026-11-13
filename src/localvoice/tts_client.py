"""Talk to the always-warm text-to-speech daemon over a token-protected loopback socket (works on every OS)."""
import socket, subprocess, sys, time

from . import config, platform_


def _endpoint():
    try:
        port, token = config.read_state("tts.port").split()
        return int(port), token
    except (ValueError, OSError):
        return None


def _send(data: bytes):
    ep = _endpoint()
    if not ep:
        raise OSError("voice daemon is not running")
    s = socket.create_connection(("127.0.0.1", ep[0]), timeout=3)
    try:
        s.sendall(ep[1].encode() + b"\n" + data)
    finally:
        s.close()


def running():
    try:
        _send(b"")
        return True
    except OSError:
        return False


def ensure_server():
    if running():
        return True
    config.ensure()
    log = open(config.path("tts.log"), "ab")
    subprocess.Popen([sys.executable, "-m", "localvoice.tts_server"], stdout=log, stderr=log,
                     stdin=subprocess.DEVNULL, **platform_.detach_kwargs())
    for _ in range(120):
        if running():
            return True
        time.sleep(0.25)
    return False


def speak(text):
    if text and ensure_server():
        _send(text.encode("utf-8"))


def stop():
    if running():
        _send(b"__STOP__")


def stop_server():
    try:
        platform_.kill_pid(int(config.read_state("tts.pid")))
    except (ValueError, OSError):
        pass
