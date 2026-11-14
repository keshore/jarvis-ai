"""Jarvis as its own assistant: you speak (or type), the brain answers, the answer is spoken sentence by sentence.
It has no tools and touches nothing on the machine. This module holds the conversation and the events the window shows."""
import json, re, threading, time

from . import brain, config, textprep, tts_client

MAX_TURNS = 12                     # exchanges kept as context for the brain
_SENT = re.compile(r"(.+?[.!?…]+[\"')\]]*)(?:\s+|$)", re.S)


# ---------- events: what the window shows ----------
class Events:
    """An append-only list with a wake-up, so several open windows can follow along and a reload shows the history."""

    def __init__(self, keep=400):
        self.items, self.keep, self.n, self.cond = [], keep, 0, threading.Condition()

    def emit(self, kind, **data):
        with self.cond:
            self.n += 1
            self.items.append({"id": self.n, "type": kind, "t": time.time(), **data})
            del self.items[:-self.keep]
            self.cond.notify_all()

    def since(self, last, timeout=25.0):
        with self.cond:
            if not any(e["id"] > last for e in self.items):
                self.cond.wait(timeout)
            return [e for e in self.items if e["id"] > last]


EVENTS = Events()
_state = {"status": "starting"}


def status(s=None):
    """starting | listening | hearing | thinking | speaking | paused"""
    if s and s != _state["status"]:
        _state["status"] = s
        EVENTS.emit("status", status=s)
    return _state["status"]


# ---------- the conversation ----------
class Assistant:
    def __init__(self, cfg_loader=config.load, speak=None, stop=None):
        self.load, self.history, self.lock = cfg_loader, [], threading.Lock()
        self.cancel, self.turn, self.busy = threading.Event(), 0, 0
        self._speak = speak or (lambda text, voice, add: tts_client.speak(text, voice, add=add))
        self._stop = stop or tts_client.stop

    def interrupt(self):
        """You started talking, or said stop: drop the answer in progress and be quiet."""
        self.cancel.set()
        self._stop()

    def clear(self):
        self.interrupt()
        with self.lock:
            self.history.clear()
        EVENTS.emit("cleared")

    def hear(self, text, typed=False):
        """A sentence from you. Answers in the background so the microphone keeps listening (you can talk over it)."""
        text = text.strip()
        if not text:
            return
        if textprep.classify(text) in ("stop", "interrupt"):
            self.interrupt()
            EVENTS.emit("you", text=text, typed=typed)
            return
        self.interrupt()
        self.cancel = threading.Event()
        self.turn += 1
        EVENTS.emit("you", text=text, typed=typed)
        threading.Thread(target=self._answer, args=(text, self.cancel, self.turn), daemon=True).start()

    def _answer(self, text, cancel, turn):
        cfg = self.load()
        voice = cfg.get("voice", "")
        with self.lock:
            messages = self.history[-MAX_TURNS * 2:] + [{"role": "user", "content": text}]
        self.busy += 1
        said, buf, first = "", "", True
        try:
            for piece in brain.stream(messages, cfg, cancel):
                if cancel.is_set():
                    break
                said += piece
                buf += piece
                EVENTS.emit("jarvis", turn=turn, text=said, done=False)
                while True:                                   # speak each sentence as soon as it is complete
                    m = _SENT.match(buf)
                    if not m or m.end() == len(buf) and not buf.endswith((" ", "\n")):
                        break
                    self._say(m.group(1), voice, first, cancel)
                    first, buf = False, buf[m.end():]
            if buf.strip() and not cancel.is_set():
                self._say(buf, voice, first, cancel)
        except brain.BrainError as e:
            said = str(e)
            EVENTS.emit("error", text=said)
            if not cancel.is_set():
                self._speak(said, voice, False)
        except Exception as e:                                 # never let a bug in a provider silence the assistant
            said = ""
            EVENTS.emit("error", text=f"Something went wrong ({type(e).__name__}).")
        else:
            said = said.strip()
            if said:
                with self.lock:
                    self.history += [{"role": "user", "content": text}, {"role": "assistant", "content": said}]
                    del self.history[:-MAX_TURNS * 2]
        self.busy -= 1
        EVENTS.emit("jarvis", turn=turn, text=said, done=True, cut=cancel.is_set())

    def _say(self, sentence, voice, first, cancel):
        spoken = textprep.endp(textprep.inline(sentence)).strip()
        if spoken and not cancel.is_set():
            self._speak(spoken, voice, not first)


def dump(e):
    return json.dumps(e, ensure_ascii=False)
