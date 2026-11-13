"""Persistent local TTS daemon (Kokoro-82M via ONNX). Keeps the model loaded so speech starts fast.
A new message interrupts the one being spoken; long text is chunked so playback starts after the first chunk."""
import os, queue, re, socket, subprocess, tempfile, threading

import soundfile as sf
from kokoro_onnx import Kokoro

from . import config

cfg = config.load()
MODELS = config.path("models")
k = Kokoro(os.path.join(MODELS, "kokoro-v1.0.onnx"), os.path.join(MODELS, "voices-v1.0.bin"))
latest = queue.Queue()
gen = 0
play = None
lock = threading.Lock()


def player_cmd(path):
    for c in (["afplay"], ["paplay"], ["aplay", "-q"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]):
        if subprocess.run(["which", c[0]], capture_output=True).returncode == 0:
            return c + [path]
    raise RuntimeError("no audio player found (afplay/paplay/aplay/ffplay)")


def stop_playback():
    with lock:
        if play and play.poll() is None:
            play.terminate()


def chunks(text, limit=280):
    out, cur = [], ""
    for sent in re.split(r"(?<=[.!?:;])\s+", text):
        if cur and len(cur) + len(sent) + 1 > limit:
            out.append(cur)
            cur = sent
        else:
            cur = (cur + " " + sent).strip()
    if cur:
        out.append(cur)
    return out


def worker():
    global play
    while True:
        text, my_gen = latest.get()
        if my_gen != gen:
            continue
        ready = queue.Queue(maxsize=2)

        def producer():
            for c in chunks(text):
                if my_gen != gen:
                    break
                try:
                    samples, sr = k.create(c, voice=cfg["voice"], speed=float(cfg["speed"]), lang="en-us")
                except Exception:
                    continue
                fd, path = tempfile.mkstemp(suffix=".wav")
                os.close(fd)
                sf.write(path, samples, sr)
                ready.put(path)
            ready.put(None)

        threading.Thread(target=producer, daemon=True).start()
        while True:
            path = ready.get()
            if path is None:
                break
            with lock:
                if my_gen != gen:
                    os.unlink(path)
                    continue
                play = subprocess.Popen(player_cmd(path))
            play.wait()
            os.unlink(path)


def main():
    global gen
    config.ensure()
    sock = config.sock_path()
    if os.path.exists(sock):
        os.unlink(sock)
    threading.Thread(target=worker, daemon=True).start()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock)
    os.chmod(sock, 0o600)
    srv.listen(8)
    while True:
        conn, _ = srv.accept()
        data = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
        conn.close()
        text = data.decode("utf-8", "ignore").strip()
        if not text:
            continue                       # empty ping: used to test that the daemon is up
        gen += 1
        stop_playback()
        if text != "__STOP__":
            latest.put((text, gen))


if __name__ == "__main__":
    main()
