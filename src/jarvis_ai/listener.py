"""Hands-free, fully local voice input for the assistant.

mic -> speech detector -> local Whisper (mlx-whisper or faster-whisper) -> the assistant. Audio never leaves the machine;
the Whisper model is downloaded once and then cached. What happens to the text is up to the brain you chose (see brain.py).
"""
import collections, os, queue, re, time

import numpy as np
import sounddevice as sd

from . import aec, assistant, brain, config, stt, textprep, tts_client, vad

SR = 16000
BLOCK = vad.BLOCK               # 512 samples = 32 ms (what Silero expects)
MIN_SPEECH = 0.4                 # s; shorter blips are ignored
MAX_UTT = 30.0                   # s
PRE_ROLL = 0.3                   # s kept before speech onset
TTS_TAIL = 0.6                   # s to stay deaf after the voice stops talking

CFG = {}


def tts_until():
    """Time at which the voice expects to be silent (written by the TTS daemon)."""
    try:
        return float(config.read_state("speaking_until", "0") or 0)
    except ValueError:
        return 0.0


def load_glossary():
    words = []
    try:
        with open(config.path("glossary.txt")) as fh:
            words = [w.strip() for w in fh if w.strip() and not w.startswith("#")]
    except OSError:
        pass
    name = (CFG.get("name") or "").strip()
    if name and name.lower() not in [w.lower() for w in words]:
        words.insert(0, name.capitalize())               # so Whisper spells the assistant's name the way we match it
    return ("Terms that may come up: " + ", ".join(words) + ".")[:600] if words else None


STATE = {}


def main():
    cfg = config.load()
    CFG.update(cfg)
    glossary = load_glossary()
    end_silence, min_thr = float(cfg["end_silence"]), float(cfg["min_threshold"])

    print(f"loading speech model ({stt.backend_name(cfg)}: {stt.model_name(cfg)}; first run downloads it) ...", flush=True)
    tr = stt.Transcriber(cfg)
    tts_client.ensure_server()
    agent = assistant.Assistant()
    print(f"assistant: answers come from {brain.describe(cfg)}; no tools, nothing on this machine is touched", flush=True)
    if cfg.get("ui", True):
        from . import ui
        ui.start(agent, cfg)
        print("window: run `jarvis-ai` to open it", flush=True)

    q = queue.Queue()
    def on_audio(indata, frames, tinfo, status):
        # the wall-clock time this block was captured, from the audio device's own clock (not when we get round to it)
        q.put((indata[:, 0].copy(), time.time() - (tinfo.currentTime - tinfo.inputBufferAdcTime)))

    with sd.InputStream(samplerate=SR, channels=1, blocksize=BLOCK, dtype="float32", callback=on_audio):
        while time.time() < tts_until() + 0.5:           # never calibrate on our own voice
            time.sleep(0.2)
        while not q.empty():
            q.get()
        noise = [float(np.sqrt(np.mean(q.get()[0] ** 2))) for _ in range(66)]       # ~2 s
        floor = float(np.percentile(noise, 30))                     # ignore bursts (keys, a passing voice)
        thr = min(max(min_thr, floor * 5.0), float(cfg["max_threshold"]))
        wake = f", wake word: {cfg['wake_word']}" if cfg["wake_word"] else ""
        print(f"listening (threshold {thr:.4f}{wake}). Say 'stop' to silence it.", flush=True)

        recent = collections.deque(maxlen=int(2.0 * SR / BLOCK))      # ~2 s of the latest audio
        seg = vad.Segmenter(start=float(cfg["vad_start"]), end=float(cfg["vad_end"]), end_silence=end_silence,
                            min_speech=MIN_SPEECH, pre_roll=PRE_ROLL, max_utt=MAX_UTT, end_silence_short=float(cfg.get("end_silence_short", end_silence)))
        detector = vad.make(cfg, thr)
        ec = aec.make(cfg)
        timeline = aec.RefTimeline() if ec else None
        print(f"voice detection: {detector.name}; echo cancellation: {'WebRTC' if ec else 'off (loudness heuristic)'}", flush=True)
        deaf_until = 0.0
        paused = config.path(".paused")
        barge_in, ratio = bool(cfg["barge_in"]), float(cfg["barge_ratio"])
        smooth, echo_win, hot = 0.0, collections.deque(), 0
        last_on, learn_until, was_on = 0.0, 0.0, False
        wake_words = (cfg.get("wake_word") or "").lower().split()
        wake_rx = re.compile(r"^[\W_]*" + r"[\W_]+".join(map(re.escape, wake_words)) + r"[\W_]*", re.I) if wake_words else None
        wake_window, awake_until = float(cfg["wake_window"]), 0.0

        while True:
            blk, t_cap = q.get()
            now = time.time()
            if ec:                                               # remove our own voice from what the mic heard
                timeline.poll()
                blk = ec.process(blk, timeline.block(t_cap, len(blk)))
            recent.append(blk)
            rms = float(np.sqrt(np.mean(blk ** 2)))
            p = detector.prob(blk)                               # speech probability of this block
            smooth = 0.7 * smooth + 0.3 * rms                    # ~90 ms level envelope
            on = now < tts_until() + 0.25                        # the voice is (about to be) talking

            if on:
                if now - last_on > 1.0:                          # a new spoken reply starts: relearn the echo
                    echo_win.clear(); hot = 0; learn_until = now + 0.4
                last_on = now
            elif was_on and not seg.active:
                deaf_until = now + TTS_TAIL                      # let the room tail die out
            was_on = on

            is_paused = os.path.exists(paused)
            if is_paused:
                deaf_until = now + TTS_TAIL
            assistant.status("paused" if is_paused else "speaking" if on else "hearing" if seg.active
                             else "thinking" if agent.busy else "listening")

            if on and not seg.active:
                if not barge_in:
                    deaf_until = now + TTS_TAIL
                else:
                    if ec:                                       # echo is gone: speech-like sound left over is you
                        echo = 0.0
                        hot = hot + 1 if (p >= 0.6 and rms > 0.008) else 0
                    else:
                        while echo_win and now - echo_win[0][0] > 1.5:
                            echo_win.popleft()
                        echo = max((v for _, v in echo_win), default=0.0)
                        limit = max(thr, echo * ratio)
                        if now < learn_until:
                            echo_win.append((now, smooth)); hot = 0
                        else:
                            # clearly louder than the echo AND speech-like (a door slam or a key click is not you)
                            hot = hot + 1 if (smooth > limit and p >= 0.5) else 0
                            if smooth <= limit:
                                echo_win.append((now, smooth))
                    if hot >= 8:                                 # ~0.25 s: you are talking over the voice
                        tts_client.stop()
                        agent.interrupt()                        # also drop the rest of the answer being written
                        print(f"  (barge-in: level {smooth:.3f} vs echo {echo:.3f})", flush=True)
                        hot, deaf_until = 0, 0.0
                        seg.start_from(list(recent)[-45:])           # keep ~1.4 s from before we noticed: your first words
                    else:
                        continue

            if now < deaf_until:
                seg.reset(); detector.reset(); recent.clear()
                while q.qsize() > 50:
                    q.get()
                continue

            audio = seg.push(blk, p)
            late = None
            if audio is None:
                fr = STATE.get("fragment")
                if not fr or seg.active or time.time() - fr[1] < 3.5:
                    continue
                late, audio = STATE.pop("fragment")[0], []       # you never finished the sentence: take what you said

            t0 = time.time()
            if late is None:
                text, confident = tr.transcribe(audio, glossary)
                if not confident:
                    continue                                     # likely a hallucination on noise
                if textprep.noise(text):
                    continue
                fr = STATE.pop("fragment", None)
                if fr and time.time() - fr[1] < 12:              # the rest of a sentence you paused in
                    text = fr[0] + " " + text
                if textprep.dangling(text):
                    STATE["fragment"] = (re.sub(r"[.\u2026\s]+$", "", text), time.time())
                    print(f"> {text}   (waiting for the rest)", flush=True)
                    continue
            else:
                text = late
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

            print(f"> {text}   [{len(audio)/SR:.1f}s audio, {time.time()-t0:.1f}s to transcribe]", flush=True)
            agent.hear(textprep.addressed(text, cfg) or text)    # "Jarvis, ..." and a plain sentence are the same thing here


def run():
    try:
        main()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
