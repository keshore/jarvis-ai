"""The Jarvis layer: sessions found without a plugin, replies read from transcripts, and commands addressed by name.

  "Jarvis, what's open?"                       -> lists the sessions and whether each is working
  "Jarvis, switch to the portal session"       -> brings that tab or pane to the front
  "Jarvis, is the portal session done?"        -> working / finished
  "Jarvis, read the portal session's reply"    -> reads that session's last reply
  "Jarvis, ask the portal session to run the tests"
                                               -> asks YOU to approve the exact text (gate.py), then types it there
Anything else said to Jarvis, and everything said without the name, is handled as before (voice commands, then
dictation into the session in front).

Safety: what you dictate to the session in front is typed as is. Everything else that would type somewhere goes
through the approval gate first. Session names come from the list of real sessions and are never guessed: two
equally good matches or none means Jarvis asks instead of acting."""
import os, re, subprocess, threading, time

from . import agents, config, gate, platform_, sessions, sinks, textprep, tts_client


# ---------- sessions found by the connectors -> the registry the router already uses ----------
def sync():
    found = agents.discover()
    for d in found:
        s = sessions.get(d["id"]) or {"id": d["id"], "created": time.time()}
        s.update(agent=d["agent"], pid=d["pid"], name=d["name"], cwd=d["cwd"], transcript=d["transcript"], busy=d["busy"])
        if not s.get("hooks") or not s.get("sink") or s.get("sink") == "none":
            s.update(sink=d["sink"] or "none", target=d["target"], term=d["term"], app="")
        sessions.register(s)
    return found


class Watcher(threading.Thread):
    """Keeps the registry current and speaks finished replies of sessions that have no hooks (no plugin needed)."""

    def __init__(self, cfg, speak, interval=1.0):
        super().__init__(daemon=True)
        self.cfg, self.speak, self.interval, self.tails, self._n = cfg, speak, interval, {}, 0

    def step(self):
        if self._n % 3 == 0:
            sync()
        self._n += 1
        for s in sessions.all():
            if s.get("hooks") or not s.get("transcript"):
                continue                                   # the plugin's Stop hook already reads this one
            t = self.tails.get(s["id"])
            if t is None or t.path != s["transcript"]:
                t = self.tails[s["id"]] = agents.Tail(s["transcript"])
            for text in t.poll():
                self.on_reply(s, text)
        for sid in [k for k in self.tails if not sessions.get(k)]:
            del self.tails[sid]

    def on_reply(self, s, text):
        for k in {s["id"], s.get("term", ""), s.get("target", "")} - {""}:
            textprep.save_last(k, text)
        if os.path.exists(config.path(".mute")):
            return
        if self.cfg.get("focus_follows", True):
            cur = sessions.current()
            if cur and cur["id"] != s["id"]:
                print(f"  ({spoken_name(s)} finished; you are looking elsewhere, reply saved)", flush=True)
                return
        print(f"  (reply from {spoken_name(s)}: {len(text)} characters)", flush=True)
        self.speak(text)

    def run(self):
        while True:
            try:
                self.step()
            except Exception as e:
                print("  (watcher:", e, ")", flush=True)
            time.sleep(self.interval)


# ---------- being addressed by name ----------
def addressed(text, cfg):
    """'Jarvis, switch to X' -> 'switch to X'. None when the sentence is not addressed to the assistant."""
    name = (cfg.get("name") or "").strip().lower()
    if not name:
        return None
    m = re.match(rf"^\W*(?:(?:hey|ok|okay|hi|yo)\W+)?{re.escape(name)}\b[\s,.!?:;-]*(.*)$", text.strip(), flags=re.I | re.S)
    return m.group(1).strip() if m else None


def spoken_name(s):
    n = re.sub(r"[-_]+", " ", s.get("name") or os.path.basename(s.get("cwd", "")) or "a session")
    return re.sub(r"\s+\d+$", "", n).strip() or "a session"


_LIST = re.compile(r"^(?:what(?:'s| is| are)?(?: sessions?)?(?: are)? (?:open|running|up|active)|(?:list|show)(?: me)?(?: the| my| all)* sessions|"
                   r"what sessions .*|which sessions .*|status|who(?:'s| is) (?:working|busy))$")
_SWITCH = re.compile(r"^(?:(?:switch|go|jump|change|move)(?: over| back)? to|take me to|bring up|focus(?: on)?|show(?: me)?) (.+)$")
_ASK = re.compile(r"^(?:ask|tell) (.+?) to (.+)$", re.S | re.I)
_DOING = re.compile(r"^(?:is (.+?) (?:done|finished|ready|still working|working|busy)(?: yet)?|what(?:'s| is) (.+?) doing|how(?:'s| is) (.+?) doing)$")
_READ = re.compile(r"^(?:read(?: me)? (.+?)(?:'s)? (?:last )?(?:reply|answer|response|message)|what did (.+?) (?:say|reply|answer))$")


def parse(rest):
    """Spoken sentence (already without the name) -> (action, session words, text) or None."""
    t = re.sub(r"[.!?]+$", "", rest.strip())
    low = re.sub(r"^(?:please |can you |could you |would you )+", "", t.lower())
    t = t[len(t) - len(low):]
    if _LIST.match(low):
        return "list", "", ""
    for name, rx in (("doing", _DOING), ("read", _READ)):
        m = rx.match(low)
        if m:
            return name, next(g for g in m.groups() if g), ""
    m = _ASK.match(t) if _ASK.match(low) else None
    if m:
        return "ask", m.group(1), m.group(2).strip()
    m = _SWITCH.match(low)
    if m:
        return "switch", m.group(1), ""
    return None


def focus(s):
    """Bring the session's tab or pane to the front. True if we could."""
    if s.get("sink") == "iterm" and platform_.IS_MAC:
        r = platform_.osascript(f'''
tell application "iTerm2"
  repeat with w in windows
    repeat with t in tabs of w
      repeat with x in sessions of t
        if id of x is "{re.sub(r"[^A-Za-z0-9-]", "", s.get("target", ""))}" then
          select w
          select t
          select x
          activate
          return "ok"
        end if
      end repeat
    end repeat
  end repeat
  return "missing"
end tell''')
        return bool(r and (r.stdout or "").strip() == "ok")
    if s.get("sink") == "tmux":
        try:
            pane = s.get("target", "")
            return subprocess.run(["tmux", "select-window", "-t", pane], timeout=3).returncode == 0 and \
                subprocess.run(["tmux", "select-pane", "-t", pane], timeout=3).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    return False


def handle(rest, cfg, speak=None, say_reply=None, approve=gate.approve, background=True):
    """Run a sentence addressed to Jarvis. True if it was one of Jarvis's own commands (handled here)."""
    speak = speak or tts_client.speak
    p = parse(rest)
    if not p:
        return False
    action, who, text = p
    ss = [s for s in sessions.all() if s.get("agent") or s.get("sink") == "pty"]
    if action == "list":
        if not ss:
            speak("No sessions are open.")
        else:
            parts = [f"{spoken_name(s)} is {'working' if s.get('busy') else 'idle'}" for s in ss]
            speak(f"{len(ss)} session{'s' if len(ss) != 1 else ''}. " + ". ".join(parts) + ".")
        return True
    s = agents.find(who, ss)
    if not s:
        names = ", ".join(spoken_name(x) for x in ss) or "none"
        speak(f"I'm not sure which session you mean. Open sessions: {names}.")
        return True
    name = spoken_name(s)
    if action == "doing":
        speak(f"{name} is still working." if s.get("busy") else f"{name} is finished.")
    elif action == "read":
        raw = textprep.load_last(s["id"])
        (say_reply or (lambda r: speak(textprep.speak_text(r))))(raw) if raw else speak(f"I have no reply from {name} yet.")
    elif action == "switch":
        speak(f"Switched to {name}." if focus(s) else f"I can't bring {name} to the front. It is not in iTerm or tmux.")
    elif action == "ask":
        if s.get("sink") in ("", "none", None):
            speak(f"I can't type into {name}. It is not in iTerm or tmux.")
            return True

        def go():
            prop = gate.Proposal(f"send to {name}", text, {"session": s["id"]})
            if approve(prop, cfg):
                sinks.for_session(cfg, s).send(text)
                speak(f"Sent to {name}.")
            else:
                speak("Not sent.")
        threading.Thread(target=go, daemon=True).start() if background else go()
    return True
