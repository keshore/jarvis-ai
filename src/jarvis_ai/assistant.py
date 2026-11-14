"""Jarvis as its own assistant: you speak (or type), the brain answers, the answer is spoken sentence by sentence.
It has no tools and touches nothing on the machine. This module holds the conversation in progress, saves it to the
local history when you allow that, and emits the events the window shows."""
import re, threading, time

from . import brain, config, store, textprep, tts_client

MAX_TURNS = 12                     # exchanges sent to the brain as context
_SENT = re.compile(r"(.+?[.!?…]+[\"')\]]*)(?:\s+|$)", re.S)


# ---------- events: what the window follows live ----------
class Events:
    """An append-only list with a wake-up, so several open windows can follow along."""

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
            if last > self.n:                                  # the window is older than this run of Jarvis: start over
                last = 0
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
        self.load, self.lock = cfg_loader, threading.Lock()
        self.cancel, self.turn, self.busy = threading.Event(), 0, 0
        self.conv, self.title, self.messages = "", "", []       # the conversation on screen; conv is "" until it is saved
        self._speak = speak or (lambda text, voice, add: tts_client.speak(text, voice, add=add))
        self._stop = stop or tts_client.stop
        self._purged = 0.0

    # --- which conversation ---
    def snapshot(self):
        with self.lock:
            return {"id": self.conv, "title": self.title, "messages": list(self.messages), "saved": bool(self.conv)}

    def new(self):
        """Start a fresh conversation. The old one stays in the history (if history is on)."""
        self.interrupt()
        with self.lock:
            self.conv, self.title, self.messages = "", "", []
        EVENTS.emit("opened", conv="")

    def open(self, cid):
        """Continue a saved conversation: its last exchanges become the brain's context again."""
        c = store.get(cid)
        if not c:
            return False
        self.interrupt()
        with self.lock:
            self.conv, self.title = c["id"], c["title"]
            self.messages = [{"role": m["role"], "text": m["text"], "t": m["t"], "brain": m["brain"]} for m in c["messages"]]
        EVENTS.emit("opened", conv=cid)
        return True

    def rename(self, cid, title):
        store.rename(cid, title)
        if cid == self.conv:
            self.title = (store.get(cid) or {}).get("title", self.title)
        EVENTS.emit("history")

    def forget(self, cid):
        store.delete(cid)
        if cid == self.conv:
            self.new()
        EVENTS.emit("history")

    def forget_all(self):
        store.delete_all()
        self.new()
        EVENTS.emit("history")

    def housekeeping(self, cfg, force=False):
        """Apply the retention setting, at most once an hour (or at once when the setting changes)."""
        if force or time.time() - self._purged > 3600:
            self._purged = time.time()
            days = int(cfg.get("retention_days", 30))
            if days > 0 and store.purge(days):
                if self.conv and not store.get(self.conv):
                    self.conv = ""                               # the open one was old enough to go: keep it on screen, unsaved
                EVENTS.emit("history")

    # --- talking ---
    def interrupt(self):
        """You started talking, or said stop: drop the answer in progress and be quiet."""
        self.cancel.set()
        self._stop()

    def say_again(self, text):
        cfg = self.load()
        self.interrupt()
        self._speak(textprep.endp(textprep.inline(str(text)[:4000])), cfg.get("voice", ""), False)

    def hear(self, text, typed=False):
        """A sentence from you. Answers in the background so the microphone keeps listening (you can talk over it)."""
        text = text.strip()
        if not text:
            return
        if textprep.classify(text) in ("stop", "interrupt"):
            self.interrupt()
            return
        self.interrupt()
        self.cancel = threading.Event()
        self.turn += 1
        cfg = self.load()
        self.housekeeping(cfg)
        self._record("user", text, cfg)
        self.busy += 1                                         # before the thread starts, so "thinking" shows at once
        threading.Thread(target=self._answer, args=(self.cancel, self.turn, cfg), daemon=True).start()

    def _record(self, role, text, cfg, which=""):
        """Add a line to the conversation on screen and, when history is on, to the saved one."""
        m = {"role": role, "text": text, "t": time.time(), "brain": which}
        created = False
        with self.lock:
            self.messages.append(m)
            if int(cfg.get("retention_days", 30)) >= 0:
                if not self.conv:
                    first = next((x["text"] for x in self.messages if x["role"] == "user"), text)
                    self.conv, self.title, created = store.create(first), store.title_of(first), True
                    for old in self.messages[:-1]:               # lines said while history was off, now part of a saved conversation
                        store.add(self.conv, old["role"], old["text"], old["brain"], old["t"])
                if not store.add(self.conv, role, text, which, m["t"]):
                    self.conv = ""                               # it was deleted from another window: carry on unsaved
            conv = self.conv
        EVENTS.emit("message", conv=conv, role=role, text=text, brain=which)
        if created:
            EVENTS.emit("history")

    def _answer(self, cancel, turn, cfg):
        voice, aloud = cfg.get("voice", ""), bool(cfg.get("speak_answers", True))
        which = brain.provider(cfg) or ""
        with self.lock:
            past = [{"role": m["role"], "content": m["text"]} for m in self.messages if m["role"] in ("user", "assistant")]
        messages = past[-(MAX_TURNS * 2 + 1):]
        while messages and messages[0]["role"] != "user":        # the API wants the first turn to be yours
            messages.pop(0)
        said, buf, first, problem = "", "", True, ""
        try:
            for piece in brain.stream(messages, cfg, cancel):
                if cancel.is_set():
                    break
                said += piece
                buf += piece
                EVENTS.emit("writing", turn=turn, text=said)
                while aloud:                                   # speak each sentence as soon as it is complete
                    m = _SENT.match(buf)
                    if not m or m.end() == len(buf) and not buf.endswith((" ", "\n")):
                        break
                    self._say(m.group(1), voice, first, cancel)
                    first, buf = False, buf[m.end():]
            if aloud and buf.strip() and not cancel.is_set():
                self._say(buf, voice, first, cancel)
        except brain.BrainError as e:
            problem = str(e)
        except Exception as e:                                 # never let a bug in a provider silence the assistant
            problem = f"Something went wrong ({type(e).__name__})."
        self.busy -= 1
        said = said.strip()
        EVENTS.emit("written", turn=turn)
        if problem:
            EVENTS.emit("problem", text=problem)
            if aloud and not cancel.is_set():
                self._speak(problem, voice, False)
        elif said:
            self._record("assistant", said, cfg, which)       # what you did hear stays as context, even when cut off

    def _say(self, sentence, voice, first, cancel):
        spoken = textprep.endp(textprep.inline(sentence)).strip()
        if spoken and not cancel.is_set():
            self._speak(spoken, voice, not first)
