"""Talk to the always-warm text-to-speech daemon over a unix socket."""
import os, socket, subprocess, sys, time

from . import config


def _send(data: bytes):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(3)
    s.connect(config.sock_path())
    s.sendall(data)
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
                     stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(80):
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
