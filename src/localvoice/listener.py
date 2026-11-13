"""Hands-free, fully local voice input.

mic -> volume VAD -> local Whisper (mlx-whisper or faster-whisper) -> spoken commands handled here,
everything else sent to the session you are looking at. No audio and no text leaves the machine; the Whisper
model is downloaded once and then cached.
"""
import collections, os, queue, re, threading, time

import numpy as np
import sounddevice as sd

from . import config, llm, platform_, sessions, sinks, stt, textprep, tts_client

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

CFG = {}


def tts_until():
    """Time at which the voice expects to be silent (written by the TTS daemon)."""
    try:
        return float(config.read_state("speaking_until", "0") or 0)
    except ValueError:
        return 0.0


def load_glossary():
    try:
        with open(config.path("glossary.txt")) as fh:
            words = [w.strip() for w in fh if w.strip() and not w.startswith("#")]
    except OSError:
        return None
    return ("Terms that may come up: " + ", ".join(words) + ".")[:600] if words else None


# ---------- spoken commands (handled locally: the AI never sees them, zero tokens) ----------
def use_llm():
    s = CFG.get("summarizer", "auto")
    return s == "llm" or (s == "auto" and llm.usable(CFG))


def _llm_brief(raw):
    if not llm.loaded():
        tts_client.speak("One moment.")
    try:
        tts_client.speak(llm.summarize(raw, CFG))
    except Exception as e:
        print("  (local model failed, using the simple summary:", e, ")", flush=True)
        tts_client.speak(textprep.speak_text(raw, "brief"))


def speak_raw(raw, kind):
    if kind == "brief" and use_llm():
        threading.Thread(target=_llm_brief, args=(raw,), daemon=True).start()
    else:
        tts_client.speak(textprep.speak_text(raw, kind))


def speak_last(kind, key):
    raw = textprep.load_last(key) or textprep.load_last(key.split(":")[-1])
    if raw:
        speak_raw(raw, kind)
    else:
        tts_client.speak("I have nothing to read yet.")


def voice_command(text, sink, key):
    """True if the sentence was a command for us."""
    c = textprep.classify(text)
    if c is None:
        return False
    if c == "stop":
        tts_client.stop()
    elif c == "interrupt":
        tts_client.stop()
        sink.interrupt()
    elif c in ("full", "brief"):
        speak_last(c, key)
    elif c in ("clip_full", "clip_brief"):
        raw = platform_.clipboard()
        if raw.strip():
            textprep.save_last("clipboard", raw)
            speak_raw(raw, "full" if c == "clip_full" else "brief")
        else:
            tts_client.speak("The clipboard is empty.")
    elif c in ("mode_full", "mode_brief"):
        m = c.split("_")[1]
        textprep.set_mode(m)
        tts_client.speak("Okay, I'll read everything." if m == "full" else "Okay, summaries only.")
    return True


def route(cfg, default_sink):
    """Which session gets this sentence: the one you are looking at, else the default sink."""
    sess = sessions.current() if cfg.get("focus_follows", True) or len(sessions.all()) == 1 else None
    if sess:
        return sinks.for_session(cfg, sess), sess["id"], f"{sess['id'][:8]} via {sess['sink']}"
    key = default_sink.target() or "default"
    return default_sink, key, f"default sink {cfg['sink']}"


def main():
    cfg = config.load()
    CFG.update(cfg)
    default_sink = sinks.get(cfg)
    glossary = load_glossary()
    end_silence, min_thr = float(cfg["end_silence"]), float(cfg["min_threshold"])

    print(f"summaries: {'local model (' + (llm.backend(cfg) or '?') + ')' if use_llm() else 'simple (no local model; optional)'}", flush=True)
    print(f"loading speech model ({stt.backend_name(cfg)}: {stt.model_name(cfg)}; first run downloads it) ...", flush=True)
    tr = stt.Transcriber(cfg)
    tts_client.ensure_server()

    q = queue.Queue()
    with sd.InputStream(samplerate=SR, channels=1, blocksize=BLOCK, dtype="float32",
                        callback=lambda indata, f, t, s: q.put(indata[:, 0].copy())):
        while time.time() < tts_until() + 0.5:           # never calibrate on our own voice
            time.sleep(0.2)
        while not q.empty():
            q.get()
        noise = [float(np.sqrt(np.mean(q.get() ** 2))) for _ in range(66)]       # ~2 s
        floor = float(np.percentile(noise, 30))                     # ignore bursts (keys, a passing voice)
        thr = min(max(min_thr, floor * 5.0), float(cfg["max_threshold"]))
        wake = f", wake word: {cfg['wake_word']}" if cfg["wake_word"] else ""
        print(f"listening (threshold {thr:.4f}{wake}). Say 'stop' to silence, 'interrupt' to stop the AI.", flush=True)

        recent = collections.deque(maxlen=int((PRE_ROLL + 0.3) * SR / BLOCK))
        buf, speaking, quiet, loud, deaf_until = [], False, 0, 0, 0.0
        paused = config.path(".paused")
        barge_in, ratio = bool(cfg["barge_in"]), float(cfg["barge_ratio"])
        smooth, echo_win, hot = 0.0, collections.deque(), 0
        last_on, learn_until, was_on = 0.0, 0.0, False
        wake_words = (cfg.get("wake_word") or "").lower().split()
        wake_rx = re.compile(r"^[\W_]*" + r"[\W_]+".join(map(re.escape, wake_words)) + r"[\W_]*", re.I) if wake_words else None
        wake_window, awake_until = float(cfg["wake_window"]), 0.0

        while True:
            blk = q.get()
            now = time.time()
            recent.append(blk)
            rms = float(np.sqrt(np.mean(blk ** 2)))
            smooth = 0.7 * smooth + 0.3 * rms                    # ~90 ms envelope
            on = now < tts_until() + 0.25                        # the voice is (about to be) talking

            if on:
                if now - last_on > 1.0:                          # a new spoken reply starts: relearn the echo
                    echo_win.clear(); hot = 0; learn_until = now + 0.4
                last_on = now
            elif was_on and not speaking:
                deaf_until = now + TTS_TAIL                      # let the room tail die out
            was_on = on

            if os.path.exists(paused):
                deaf_until = now + TTS_TAIL

            if on and not speaking:
                if not barge_in:
                    deaf_until = now + TTS_TAIL
                else:
                    while echo_win and now - echo_win[0][0] > 1.5:
                        echo_win.popleft()
                    echo = max((v for _, v in echo_win), default=0.0)
                    limit = max(thr, echo * ratio)
                    if now < learn_until:
                        echo_win.append((now, smooth)); hot = 0
                    else:
                        hot = hot + 1 if smooth > limit else 0
                        if smooth <= limit:
                            echo_win.append((now, smooth))
                    if hot >= 8:                                 # ~0.25 s clearly above the echo: you are talking
                        tts_client.stop()
                        print(f"  (barge-in: level {smooth:.3f} vs echo {echo:.3f})", flush=True)
                        speaking, quiet, hot, deaf_until = True, 0, 0, 0.0
                        buf = list(recent)[-8:]
                    else:
                        continue

            if now < deaf_until:
                buf, speaking, quiet, loud = [], False, 0, 0
                recent.clear()
                while q.qsize() > 50:
                    q.get()
                continue

            if not speaking:
                loud = loud + 1 if rms > thr else 0
                if loud >= 3:
                    speaking, quiet = True, 0
                    buf = list(recent)
                continue

            buf.append(blk)
            quiet = quiet + 1 if rms < thr else 0
            dur = len(buf) * BLOCK / SR
            if quiet * BLOCK / SR < end_silence and dur < MAX_UTT:
                continue

            speech_len = dur - quiet * BLOCK / SR
            audio = np.concatenate(buf)
            buf, speaking, quiet, loud = [], False, 0, 0
            recent.clear()
            if speech_len < MIN_SPEECH:
                continue

            t0 = time.time()
            text, confident = tr.transcribe(audio, glossary)
            if not confident:
                continue                                         # likely a hallucination on noise
            if text.lower().strip(" .!?,") in JUNK or re.fullmatch(r"[\W_]*", text):
                continue
            if wake_rx:
                m = wake_rx.match(text)
                if m:
                    text = text[m.end():].strip()
                    awake_until = time.time() + wake_window
                    if not text:
                        print("  (awake)", flush=True)
                        continue
                elif time.time() > awake_until:
                    print(f"  (ignored, start with '{cfg['wake_word']}'): {text}", flush=True)
                    continue                                     # not for me: ignore room chatter
                else:
                    awake_until = time.time() + wake_window

            sink, key, where = route(cfg, default_sink)
            print(f"> {text}   [{len(audio)/SR:.1f}s audio, {time.time()-t0:.1f}s to transcribe] -> {where}", flush=True)
            if voice_command(text, sink, key):
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
