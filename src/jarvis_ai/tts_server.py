"""Persistent local TTS daemon (Kokoro-82M on ONNX: runs on any CPU). Keeps the model loaded so speech starts fast.
A new message interrupts the one being spoken; long text is chunked so playback starts after the first chunk.
Audio is played in-process with sounddevice, so there is no per-OS player to depend on."""
import os, queue, re, secrets, socket, threading, time

import sounddevice as sd
from kokoro_onnx import Kokoro

from . import aec, config

cfg = config.load()
MODELS = config.path("models")
k = Kokoro(os.path.join(MODELS, "kokoro-v1.0.onnx"), os.path.join(MODELS, "voices-v1.0.bin"))
latest = queue.Queue()
gen = 0
ref_seq = 0
lock = threading.Lock()
PUBLISH_REF = cfg.get("echo_cancel", "auto") != "off"


def mark_speaking(until):
    """Tell the listener when we expect to stop talking (0 = silent). Lets it separate echo from you."""
    try:
        config.write_state("speaking_until", repr(until))
    except OSError:
        pass


def stop_playback():
    mark_speaking(0.0)
    try:
        sd.stop()
    except Exception:
        pass


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
    while True:
        text, my_gen, voice = latest.get()
        if my_gen != gen:
            continue
        ready = queue.Queue(maxsize=2)

        def producer():
            for c in chunks(text):
                if my_gen != gen:
                    break
                try:
                    samples, sr = k.create(c, voice=voice or cfg["voice"], speed=float(cfg["speed"]), lang="en-us")
                except Exception:
                    continue
                ready.put((samples, sr))
            ready.put(None)

        threading.Thread(target=producer, daemon=True).start()
        while True:
            item = ready.get()
            if item is None:
                break
            samples, sr = item
            with lock:
                if my_gen != gen:
                    continue
                t_play = time.time()
                mark_speaking(t_play + len(samples) / sr)
                if PUBLISH_REF:
                    global ref_seq
                    ref_seq += 1
                    try:
                        aec.publish(samples, sr, t_play, ref_seq)      # lets the listener cancel our own echo
                    except OSError:
                        pass
                sd.play(samples, sr)
            sd.wait()


def main():
    global gen
    config.ensure()
    from . import tts_client
    if tts_client.running():                       # another daemon won the race: do not run a second copy
        return
    token = secrets.token_hex(16)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    config.write_state("tts.pid", str(os.getpid()))
    config.write_secret("tts.port", f"{srv.getsockname()[1]} {token}")
    threading.Thread(target=worker, daemon=True).start()
    while True:
        conn, _ = srv.accept()
        conn.settimeout(3)
        data = b""
        try:
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
        except OSError:
            pass
        conn.close()
        head, _, body = data.partition(b"\n")
        if head.decode("ascii", "ignore") != token:
            continue                                  # not us: ignore
        text = body.decode("utf-8", "ignore").strip()
        if not text:
            continue                                  # empty ping: used to test that the daemon is up
        gen += 1
        stop_playback()
        if text != "__STOP__":
            m = re.match(r"__VOICE:([a-z]{2}_[a-z0-9]+)__\n?", text)      # optional per-message voice (Jarvis's own voice)
            voice = m.group(1) if m else ""
            latest.put((text[m.end():] if m else text, gen, voice))


if __name__ == "__main__":
    main()
