"""Hands-free, fully local voice input.

mic -> volume VAD -> local Whisper (mlx-whisper) -> spoken commands handled here | everything else to the sink.
No audio and no text leaves the machine; the Whisper model is downloaded once and then cached.
"""
import collections, os, queue, re, subprocess, sys, time

import numpy as np
import sounddevice as sd

from . import config, sinks, textprep, tts_client

SR = 16000
BLOCK = 480                      # 30 ms
MIN_SPEECH = 0.4                 # s; shorter blips are ignored
MAX_UTT = 30.0                   # s
PRE_ROLL = 0.3                   # s kept before speech onset
TTS_TAIL = 0.6                   # s to stay deaf after the voice stops talking

JUNK = {"", "you", "thank you", "thanks", "thanks for watching", "bye", "goodbye",
        "we'll see you next time", "see you next time", "see you in the next video",
        "thank you for watching", "thanks for listening", "i'll see you next time",
        "subtitles by the amara.org community"}

_tts = [0.0, False]


def tts_playing():
    """True while any local player is speaking (polled at most 4x/sec)."""
    now = time.time()
    if now - _tts[0] > 0.25:
        _tts[0] = now
        _tts[1] = any(subprocess.run(["pgrep", "-x", p], capture_output=True).returncode == 0
                      for p in ("afplay", "paplay", "aplay", "ffplay"))
    return _tts[1]


def load_glossary():
    try:
        words = [w.strip() for w in open(config.path("glossary.txt")) if w.strip() and not w.startswith("#")]
    except OSError:
        return None
    return ("Terms that may come up: " + ", ".join(words) + ".")[:600] if words else None


def speak_last(kind, sink):
    key = sink.target() or "default"
    raw = textprep.load_last(key)
    tts_client.speak(textprep.speak_text(raw, kind) if raw else "I have nothing to read yet.")


def voice_command(text, sink):
    """Spoken commands are handled locally and never reach the AI (zero tokens). True if handled."""
    c = textprep.classify(text)
    if c is None:
        return False
    if c == "stop":
        tts_client.stop()
    elif c == "interrupt":
        tts_client.stop()
        sink.interrupt()
    elif c in ("full", "brief"):
        speak_last(c, sink)
    elif c in ("mode_full", "mode_brief"):
        m = c.split("_")[1]
        textprep.set_mode(m)
        tts_client.speak("Okay, I'll read everything." if m == "full" else "Okay, summaries only.")
    return True


def main():
    import mlx_whisper
    cfg = config.load()
    sink = sinks.get(cfg)
    model = cfg["stt_model"]
    glossary = load_glossary()
    end_silence, min_thr = float(cfg["end_silence"]), float(cfg["min_threshold"])

    print(f"loading {model} (first run downloads it) ...", flush=True)
    mlx_whisper.transcribe(np.zeros(SR, dtype=np.float32), path_or_hf_repo=model, language=cfg["language"])
    tts_client.ensure_server()

    q = queue.Queue()
    with sd.InputStream(samplerate=SR, channels=1, blocksize=BLOCK, dtype="float32",
                        callback=lambda indata, f, t, s: q.put(indata[:, 0].copy())):
        noise = [float(np.sqrt(np.mean(q.get() ** 2))) for _ in range(40)]
        thr = max(min_thr, float(np.median(noise)) * 5.0)
        print(f"listening (sink={cfg['sink']}, threshold {thr:.4f}). Say 'stop' to silence, 'interrupt' to stop the AI.",
              flush=True)

        pre = collections.deque(maxlen=int(PRE_ROLL * SR / BLOCK))
        buf, speaking, quiet, loud, deaf_until = [], False, 0, 0, 0.0
        paused = config.path(".paused")

        while True:
            blk = q.get()
            now = time.time()
            if tts_playing() or os.path.exists(paused):
                deaf_until = now + TTS_TAIL
            if now < deaf_until:
                buf, speaking, quiet, loud = [], False, 0, 0
                pre.clear()
                while q.qsize() > 50:
                    q.get()
                continue

            rms = float(np.sqrt(np.mean(blk ** 2)))
            if not speaking:
                pre.append(blk)
                loud = loud + 1 if rms > thr else 0
                if loud >= 3:
                    speaking, quiet = True, 0
                    buf = list(pre)
                continue

            buf.append(blk)
            quiet = quiet + 1 if rms < thr else 0
            dur = len(buf) * BLOCK / SR
            if quiet * BLOCK / SR < end_silence and dur < MAX_UTT:
                continue

            speech_len = dur - quiet * BLOCK / SR
            audio = np.concatenate(buf)
            buf, speaking, quiet, loud = [], False, 0, 0
            pre.clear()
            if speech_len < MIN_SPEECH:
                continue

            t0 = time.time()
            res = mlx_whisper.transcribe(audio, path_or_hf_repo=model, language=cfg["language"],
                                         condition_on_previous_text=False, initial_prompt=glossary)
            text = res["text"].strip()
            segs = res.get("segments") or []
            if segs and (max(s.get("no_speech_prob", 0) for s in segs) > 0.5
                         or min(s.get("avg_logprob", 0) for s in segs) < -1.0):
                continue                                   # likely a hallucination on noise
            if text.lower().strip(" .!?,") in JUNK or re.fullmatch(r"[\W_]*", text):
                continue
            print(f"> {text}   [{len(audio)/SR:.1f}s audio, {time.time()-t0:.1f}s to transcribe]", flush=True)
            if voice_command(text, sink):
                continue
            sink.send(text)
            while not q.empty():
                q.get()


def run():
    try:
        main()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
