"""Hands-free, fully local voice input.

mic -> volume VAD -> local Whisper (mlx-whisper or faster-whisper) -> spoken commands handled here,
everything else sent to the session you are looking at. No audio and no text leaves the machine; the Whisper
model is downloaded once and then cached.
"""
import collections, os, queue, re, threading, time

import numpy as np
import sounddevice as sd

from . import aec, assistant, config, gate, intent, jarvis, llm, platform_, sessions, sinks, stt, textprep, tts_client, vad

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


def speak_last(kind, key, back=0):
    """Read the last reply (back=0) or an earlier one (back=1: the one before that)."""
    raw = ""
    s = sessions.get(key)
    if s and s.get("transcript"):
        from . import agents
        rs = agents.claude_replies(s["transcript"], back + 2)
        raw = rs[-1 - back] if len(rs) > back else ""
        if back and not raw:
            tts_client.speak("There is no earlier reply.", JV())
            return
    raw = raw or textprep.load_last(key) or textprep.load_last(key.split(":")[-1])
    if raw:
        speak_raw(raw, kind)
    else:
        tts_client.speak("I have nothing to read yet.")


HELP_SPOKEN = ("I read your AI's replies aloud. Say stop to quiet me, interrupt to stop the AI, read it all for the whole reply, "
               "summarize that for a short one, or read everything from now on to change the default. Anything else goes to the AI.")


STATE = {}


def JV():
    """Jarvis's own voice, so you can tell it apart from the agent's replies being read out."""
    return CFG.get("jarvis_voice", "")


def voice_command(text, sink, key):
    """Handle the sentence if it is for us. Returns the text to forward to the AI, or None when it was handled here."""
    talking = CFG.get("talk_to", "jarvis") == "jarvis" and llm.usable(CFG)
    kind, val = intent.interpret(text, CFG, use_model=not talking)      # when you talk to Jarvis, the conversation step decides the rest
    if kind == "forward":
        if val != text:
            print(f"  (cleaned up: {val})", flush=True)
        return val
    c = val
    print(f"  (command: {c})", flush=True)
    if c == "stop":
        tts_client.stop()
    elif c == "interrupt":
        tts_client.stop()
        sink.interrupt()
    elif c in ("full", "brief"):
        speak_last(c, key, 1 if jarvis._PREV.search(text) else 0)
    elif c in ("clip_full", "clip_brief"):
        raw = platform_.clipboard()
        if raw.strip():
            textprep.save_last("clipboard", raw)
            speak_raw(raw, "full" if c == "clip_full" else "brief")
        else:
            tts_client.speak("The clipboard is empty.")
    elif c == "help":
        tts_client.speak(HELP_SPOKEN)
    elif c in ("mode_full", "mode_brief"):
        m = c.split("_")[1]
        textprep.set_mode(m)
        tts_client.speak("Okay, I'll read everything." if m == "full" else "Okay, summaries only.")
    return None


def route(cfg, default_sink):
    """Which session gets this sentence: the one you are looking at, else the default sink."""
    sess = sessions.current() if cfg.get("focus_follows", True) or len(sessions.all()) == 1 else None
    if sess and sess.get("sink") not in ("", "none", None):
        return sinks.for_session(cfg, sess), sess["id"], f"{sess.get('name') or sess['id'][:8]} via {sess['sink']}"
    if sess:                                               # known session in a terminal we cannot address: type into the front window
        return default_sink, sess["id"], f"{sess.get('name') or sess['id'][:8]} via default sink {cfg['sink']}"
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
    agent = None
    if not cfg.get("discover", False):                       # Jarvis is its own assistant: what you say goes to its brain, nowhere else
        from . import brain
        agent = assistant.Assistant()
        print(f"assistant: answers come from {brain.describe(cfg)}; no tools, nothing on this machine is touched", flush=True)
        if cfg.get("ui", True):
            from . import ui
            ui.start(agent, cfg)
            print("window: run `jarvis-ai` to open it", flush=True)
    if cfg.get("discover", False):
        jarvis.Watcher(cfg, lambda raw: speak_raw(raw, textprep.get_mode()),
                       announce=lambda line: tts_client.speak(line, JV())).start()
        print("sessions: found automatically; replies are read from the agents' transcripts", flush=True)

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
        print(f"listening (threshold {thr:.4f}{wake}). Say 'stop' to silence, 'interrupt' to stop the AI.", flush=True)

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
            if agent:
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
                        if agent:
                            agent.interrupt()                    # also drop the rest of the answer being written
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
                if jarvis.dangling(text):
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

            if agent:
                print(f"> {text}   [{len(audio)/SR:.1f}s audio, {time.time()-t0:.1f}s to transcribe]", flush=True)
                agent.hear(jarvis.addressed(text, cfg) or text)   # "Jarvis, ..." and plain sentences are the same thing here
                continue
            rest = jarvis.addressed(text, cfg)
            if rest is not None:
                print(f"> {text}   [to {cfg['name']}]", flush=True)
                if not rest:
                    tts_client.speak("Yes?")
                    continue
                if jarvis.handle(rest, cfg, say_reply=lambda raw: speak_raw(raw, "brief")):
                    continue
                text = rest                                      # not one of Jarvis's own commands: treat it like any sentence
            sink, key, where = route(cfg, default_sink)
            print(f"> {text}   [{len(audio)/SR:.1f}s audio, {time.time()-t0:.1f}s to transcribe] -> {where}", flush=True)
            pend = STATE.pop("pending", None)                   # Jarvis asked "shall I ask Claude?": a plain yes sends it, once
            if pend and time.time() < pend[2]:
                if gate.is_yes(text) or jarvis.casual_yes(text):
                    print(f"> {text}   [yes: sent to the agent: {pend[0]}]", flush=True)
                    pend[1].send(pend[0])
                    tts_client.speak("Asking now.", JV())
                    continue
                if gate._NO.match(text.lower().strip()):
                    print(f"> {text}   [no]", flush=True)
                    tts_client.speak("Very well.", JV())
                    continue
                if jarvis._IN_HISTORY.search(text):               # "but it's already in the history": look harder before asking again
                    print(f"> {text}   [looking again in the conversation]", flush=True)
                    kind, words = jarvis.talk(pend[0], sessions.get(key), cfg, lambda s: tts_client.speak(s, JV()), None, deep=True)
                    if kind == "say":
                        print(f"  (Jarvis: {words})", flush=True)
                        tts_client.speak(words, JV())
                    else:
                        STATE["pending"] = (pend[0], pend[1], time.time() + 25, pend[3])
                        tts_client.speak("I can't find that in what I've seen. Shall I ask?", JV())
                    continue
                if len(text.split()) <= 4 and not textprep.classify(text) and pend[3] < 2:
                    # a short reply that is neither yes nor no: do not treat it as a new request, ask once more
                    STATE["pending"] = (pend[0], pend[1], time.time() + 25, pend[3] + 1)
                    print("  (Jarvis: Was that a yes?)", flush=True)
                    tts_client.speak("Sorry, was that a yes?", JV())
                    continue
            m = jarvis._TO_AGENT.match(text.strip())
            if m:                                                # "ask Claude": skip Jarvis, go straight to the agent
                text = m.group(1).strip() or STATE.get("last_local", "")
                if not text:
                    tts_client.speak("Ask it what?", JV())
                    continue
                print(f"  (to the agent: {text})", flush=True)
                sink.send(text)
                continue
            fwd = voice_command(text, sink, key)
            if fwd is None:
                continue
            if cfg.get("talk_to", "jarvis") == "jarvis":         # you talk to Jarvis; it answers, or asks before using the agent
                sess = sessions.get(key)
                mem = STATE.setdefault("memory", [])
                kind, words = jarvis.talk(fwd, sess, cfg, lambda s: tts_client.speak(s, JV()), mem)
                if kind == "say":
                    mem.append((fwd, words))
                    del mem[:-4]
                    STATE["last_local"] = fwd                    # "ask Claude" after this sends the same sentence on
                    print(f"  (Jarvis: {words})", flush=True)
                    tts_client.speak(words, JV())
                    continue
                if llm.usable(cfg) and cfg.get("confirm_agent", "always") == "always":
                    STATE["pending"] = (fwd, sink, time.time() + 25, 0)
                    line = jarvis.ask_line(sess)
                    print(f"  (Jarvis: {line})", flush=True)
                    tts_client.speak(line, JV())
                    continue
            sink.send(fwd)
            while not q.empty():
                q.get()


def run():
    try:
        main()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
