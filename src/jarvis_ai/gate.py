"""The approval gate for anything that acts on your behalf (used by the planned Jarvis mode).

Rules, all enforced here in plain code, never by a language model:
  * a model can only PROPOSE; nothing runs unless `approve()` returns True
  * every approval is for one proposal only, expires, and is never remembered ("always yes" does not exist)
  * you approve exactly what you see: the full text is shown, and text too long to review is refused, not truncated
  * the default way to approve is a dialog you click: nobody can say it, play it or inject it through a microphone
  * spoken approval is optional (`approval = "voice"`), matched with strict patterns, and only for the proposal just read to you
  * everything not clearly a yes is a no (timeout, error, unsupported platform, ambiguous wording)
  * every proposal and decision is written to ~/.jarvis-ai/audit.log"""
import json, os, re, subprocess, sys, threading, time, uuid

from . import config

MAX_REVIEW_CHARS = 1500
DIALOG_TIMEOUT = 45                  # seconds; no click means no
VOICE_WINDOW = 15                    # seconds a spoken proposal stays answerable


class Proposal:
    def __init__(self, action, text, args=None):
        self.id, self.action, self.text, self.args, self.created = uuid.uuid4().hex[:8], action, text, args or {}, time.time()


def audit(event, p, **extra):
    try:
        path = config.path("audit.log")
        fresh = not os.path.exists(path)
        with open(path, "a") as fh:
            fh.write(json.dumps({"t": round(time.time(), 1), "event": event, "id": p.id, "action": p.action, "text": p.text[:2000], **extra}) + "\n")
        if fresh:
            os.chmod(path, 0o600)
    except OSError:
        pass


# ---------- dialog (default) ----------
_APPLESCRIPT = """on run argv
  try
    set r to display dialog (item 2 of argv) with title (item 1 of argv) buttons {"Cancel", "Approve"} default button "Cancel" cancel button "Cancel" with icon caution giving up after (item 3 of argv as integer)
    if gave up of r then return "timeout"
    return button returned of r
  on error
    return "cancel"
  end try
end run"""


def _dialog(p, timeout=DIALOG_TIMEOUT):
    if sys.platform == "darwin":
        cmd = ["osascript", "-e", _APPLESCRIPT, f"jarvis-ai: approve {p.action}?", p.text, str(timeout)]
    elif sys.platform.startswith("linux") and __import__("shutil").which("zenity"):
        cmd = ["zenity", "--question", "--title", f"jarvis-ai: approve {p.action}?", "--text", p.text.replace("&", "&amp;").replace("<", "&lt;"),
               "--ok-label", "Approve", "--cancel-label", "Cancel", "--timeout", str(timeout)]
    else:
        return False, "no dialog available on this platform"
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
    except (OSError, subprocess.SubprocessError):
        return False, "dialog failed"
    if sys.platform == "darwin":
        return r.stdout.strip() == "Approve", r.stdout.strip() or "cancel"
    return r.returncode == 0, "approve" if r.returncode == 0 else "cancel"


# ---------- spoken approval (optional) ----------
_YES = re.compile(r"^(?:yes|yeah|yep|approve|approved|confirm|confirmed|go ahead|do it|send it|yes (?:please|send it|do it|go ahead|approve))$")
_NO = re.compile(r"^(?:no|nope|cancel|stop|don'?t|do not|never ?mind|abort|reject)")


def is_yes(text):
    """Strict: the WHOLE sentence must be a plain yes. 'yes but delete everything' is not a yes."""
    return bool(_YES.match(re.sub(r"[^\w\s']", "", text.lower()).strip()))


class VoiceApproval:
    """One pending spoken proposal at a time. `offer()` after the proposal has been read out; `hear()` with each sentence."""

    def __init__(self, window=VOICE_WINDOW, clock=time.time):
        self.window, self.clock, self._p, self._until, self._lock = window, clock, None, 0.0, threading.Lock()
        self._event, self._ok = threading.Event(), False

    def offer(self, p):
        with self._lock:
            self._p, self._until, self._ok = p, self.clock() + self.window, False
            self._event.clear()

    def hear(self, text):
        """True if this sentence was consumed as the answer to the pending proposal."""
        with self._lock:
            if self._p is None or self.clock() > self._until:
                self._p = None
                return False
            if is_yes(text):
                self._ok = True
            elif not _NO.match(text.lower().strip()):
                return False                      # unrelated speech neither approves nor cancels
            self._p = None                        # one shot
            self._event.set()
            return True

    def wait(self):
        self._event.wait(self.window + 1)
        with self._lock:
            ok, self._ok, self._p = self._ok, False, None
        return ok


# ---------- the entry point ----------
def approve(p, cfg=None, voice=None, speak=None):
    """True only if the user clearly approved THIS proposal now."""
    cfg = cfg or config.load()
    mode = cfg.get("approval", "dialog")
    audit("proposed", p, mode=mode)
    if len(p.text) > MAX_REVIEW_CHARS:
        audit("denied", p, reason="too long to review")
        return False
    if mode == "voice" and voice is not None and speak is not None:
        speak(f"{p.action}: {p.text}. Say yes to approve.")
        voice.offer(p)
        ok, how = voice.wait(), "voice"
    else:
        ok, how = _dialog(p)
    audit("approved" if ok else "denied", p, how=how if isinstance(how, str) else "dialog")
    return bool(ok)
