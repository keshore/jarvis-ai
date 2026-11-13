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
import json, os, re, subprocess, threading, time

from . import agents, config, gate, platform_, sessions, sinks, textprep, tts_client


_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


# ---------- sessions found by the connectors -> the registry the router already uses ----------
def sync():
    found = agents.discover()
    for d in found:
        s = sessions.get(d["id"]) or {"id": d["id"], "created": time.time()}
        s.update(agent=d["agent"], pid=d["pid"], name=d["name"], cwd=d["cwd"], transcript=d["transcript"], busy=d["busy"])
        if not s.get("hooks") or not s.get("sink") or s.get("sink") == "none":
            s.update(sink=d["sink"] or "none", target=d["target"], term=d["term"], app=d.get("app", ""))
        sessions.register(s)
    if found or os.path.isdir(os.path.join(agents.claude_home(), "sessions")):
        live = {d["id"] for d in found}
        for s in sessions.all():                           # a Claude session Claude itself no longer lists has ended: it must not
            if not s.get("pid") and _UUID.match(s["id"]) and s["id"] not in live:      # shadow the live one in the same tab
                sessions.remove(s["id"])
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
_OPEN = re.compile(r"^(?:open|start|launch|create|begin|spin up)(?: up)?(?: a| an)?(?: new)? (?:(?!session\b|agent\b|tab\b)(\w+) )?(?:session |agent |tab )?(?:in|for|on) (.+)$")
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
    m = _OPEN.match(low)
    if m and (m.group(1) or "session" in low or "agent" in low):
        return "open", m.group(2), (m.group(1) or "")
    m = _SWITCH.match(low)
    if m:
        return "switch", m.group(1), ""
    return None


# ---------- looser wording: the local model fills in a fixed form, plain code checks every field ----------
ASK_SYSTEM = """A person spoke to their voice assistant. Fill in ONE line of JSON: {"action": "...", "session": N, "text": "..."}
Actions:
  list    they want to know which sessions are open
  switch  bring session N to the front
  doing   is session N finished or still working
  read    read session N's last reply
  ask     pass an instruction on to session N; "text" is that instruction, copied from their words (drop "ask/tell ... to")
  none    anything else (a coding request, a question, small talk). DEFAULT when unsure.
"session" is the number of a session from the list below, or 0 when no session is meant or you cannot tell.
Sessions:
%s"""


_GENERIC = {"app", "apps", "the", "api", "web", "test", "tests", "new", "old", "main", "dev", "src", "code", "project", "session"}


def _mentions(rest, s):
    """Does the sentence contain a word of this session's name? ('the portal one' -> college-portal-app)"""
    said = [w for w in re.findall(r"[a-z0-9]+", rest.lower()) if len(w) > 2 and w not in _GENERIC]
    name = [w for w in re.findall(r"[a-z0-9]+", (s.get("name", "") + " " + os.path.basename(s.get("cwd", ""))).lower()) if len(w) > 2 and w not in _GENERIC]
    return any(w == h or h.startswith(w) or w.startswith(h) for w in said for h in name)


def model_parse(rest, ss, cfg, speak=None):
    """Ask the local model which of Jarvis's commands was meant. Returns (action, session dict or None, text) or None.
    The model only picks from the list; a session is a number from the list we gave it, never a name it wrote; the text
    of an `ask` must be made of words the person actually said."""
    from . import intent, llm
    if cfg.get("frontend", "commands") == "off" or not llm.usable(cfg) or len(rest.split()) > 40:
        return None
    listing = "\n".join(f"  {i}. {spoken_name(s)}" for i, s in enumerate(ss, 1)) or "  (none)"
    box = {}

    def work():
        try:
            box["out"] = llm.generate([{"role": "system", "content": ASK_SYSTEM % listing}, {"role": "user", "content": rest}], cfg, 120)
        except Exception:
            pass
    th = threading.Thread(target=work, daemon=True)
    th.start()
    wait = float(cfg.get("frontend_timeout", 6))
    if not llm.loaded():                                  # first use, or unloaded after idle: loading takes a few seconds
        if speak:
            speak("One moment.")
        wait = max(wait, 30.0)
    th.join(wait)
    m = re.search(r"\{.*\}", box.get("out", ""), flags=re.S)
    try:
        d = json.loads(m.group(0)) if m else None
    except ValueError:
        d = None
    if not isinstance(d, dict) or d.get("action") not in ("list", "switch", "doing", "read", "ask"):
        return None
    if d["action"] == "list":
        return "list", None, ""
    try:
        n = int(d.get("session") or 0)
    except (TypeError, ValueError):
        n = 0
    if not 1 <= n <= len(ss) or not _mentions(rest, ss[n - 1]):
        return None                                       # the sentence names no session: the model must not pick one for you
    text = str(d.get("text") or "").strip() if d["action"] == "ask" else ""
    if d["action"] == "ask":
        said = set(re.findall(r"[a-z0-9']+", rest.lower()))
        words = re.findall(r"[a-z0-9']+", text.lower())
        if not words or any(w not in said for w in words):
            return None                                   # the model added or changed words: not what you said, so not sent
    return d["action"], ss[n - 1], text


# ---------- opening a new session ----------
SKIP_DIRS = {"node_modules", "venv", ".venv", "dist", "build", "target", "Library", "__pycache__", "vendor"}


def project_roots(cfg, ss):
    roots = [os.path.expanduser(r) for r in cfg.get("project_dirs") or []]
    if not roots:
        roots = [os.path.expanduser(r) for r in ("~/src", "~/code", "~/projects", "~/dev", "~/work", "~/repos", "~/git", "~/Documents/GitHub")]
        roots += [os.path.dirname(s["cwd"]) for s in ss if s.get("cwd")]
    seen, out = set(), []
    for r in roots:
        r = os.path.realpath(r)
        if r not in seen and os.path.isdir(r) and r != os.path.realpath(os.path.expanduser("~")):
            seen.add(r)
            out.append(r)
    return out


def find_project(name, roots, depth=3, limit=4000):
    """Folder someone means by a spoken project name. Returns (path or None, candidates when it is unclear)."""
    cands, n = [], 0
    for root in roots:
        todo = [(root, 0)]
        while todo and n < limit:
            d, lvl = todo.pop()
            try:
                subs = [e for e in os.scandir(d) if e.is_dir(follow_symlinks=False) and not e.name.startswith(".") and e.name not in SKIP_DIRS]
            except OSError:
                continue
            for e in subs:
                n += 1
                cands.append({"id": e.path, "name": e.name, "cwd": e.path})
                if lvl + 1 < depth and not os.path.exists(os.path.join(e.path, ".git")):
                    todo.append((e.path, lvl + 1))        # do not descend into a repository: its folders are not projects
    exact = [c for c in cands if re.sub(r"[^a-z0-9]", "", c["name"].lower()) == re.sub(r"[^a-z0-9]", "", name.lower())]
    if len(exact) == 1:
        return exact[0]["cwd"], []
    hit = agents.find(name, exact or cands)
    if hit:
        return hit["cwd"], []
    words = [w for w in re.findall(r"[a-z0-9]+", name.lower()) if len(w) > 2]
    return None, [c["name"] for c in (exact or cands) if any(w in c["name"].lower() for w in words)][:4]


def open_session(path, cmd):
    """Start `cmd` in `path` in a new terminal tab or window that you can see. True if a terminal was opened."""
    import shlex
    line = f"cd {shlex.quote(path)} && {cmd}"
    if os.environ.get("TMUX") or (not platform_.IS_MAC and agents._tmux_ttys()):
        try:
            return subprocess.run(["tmux", "new-window", "-c", path, cmd], timeout=5).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    if platform_.IS_MAC:
        esc = line.replace("\\", "\\\\").replace('"', '\\"')
        if platform_.front_app().lower().startswith("iterm") or agents._iterm_ttys():
            r = platform_.osascript(f'''
tell application "iTerm2"
  activate
  if (count of windows) = 0 then
    create window with default profile
  else
    tell current window to create tab with default profile
  end if
  tell current session of current window to write text "{esc}"
  return "ok"
end tell''')
        else:
            r = platform_.osascript(f'tell application "Terminal"\nactivate\ndo script "{esc}"\nreturn "ok"\nend tell')
        return bool(r and (r.stdout or "").strip() == "ok")
    return False


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
    if s.get("sink") == "keystroke" and s.get("app"):
        platform_.activate_app(s["app"])                  # the app comes to the front; we cannot pick a tab inside it
        return True
    return False


def handle(rest, cfg, speak=None, say_reply=None, approve=gate.approve, background=True):
    """Run a sentence addressed to Jarvis. True if it was one of Jarvis's own commands (handled here)."""
    speak = speak or tts_client.speak
    ss = [s for s in sessions.all() if s.get("agent") or s.get("sink") == "pty"]
    p, s = parse(rest), None
    if p:
        action, who, text = p
    else:
        mp = model_parse(rest, ss, cfg, speak)
        if not mp:
            return False
        action, s, text = mp
        who = ""
        print(f"  (understood as: {action}{' ' + spoken_name(s) if s else ''}{': ' + text if text else ''})", flush=True)
    if action == "list":
        if not ss:
            speak("No sessions are open.")
        else:
            parts = [f"{spoken_name(x)} is {'working' if x.get('busy') else 'idle'}" for x in ss]
            speak(f"{len(ss)} session{'s' if len(ss) != 1 else ''}. " + ". ".join(parts) + ".")
        return True
    if action == "open":
        return _open(who, text, cfg, ss, speak, approve, background)
    s = s or agents.find(who, ss)
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
        speak(f"Switched to {name}." if focus(s) else f"I can't bring {name} to the front.")
    elif action == "ask":
        if s.get("sink") in ("", "none", None):
            speak(f"I can't type into {name}. It is not in a terminal I can reach.")
            return True
        if s.get("sink") == "keystroke" and sum(1 for x in ss if x.get("sink") == "keystroke" and x.get("app") == s.get("app")) > 1:
            speak(f"{name} shares its app with another session and I can't pick the tab, so I won't type there. Switch to it and say it yourself.")
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


def _open(who, agent_word, cfg, ss, speak, approve, background):
    cmds = cfg.get("agent_commands") or {"claude": "claude", "codex": "codex", "gemini": "gemini", "aider": "aider", "copilot": "copilot"}
    cmd = cmds.get(agent_word) if agent_word in cmds else cfg.get("open_cmd", "claude")
    path, maybe = find_project(who, project_roots(cfg, ss))
    if not path:
        speak(f"I found more than one match: {', '.join(maybe)}. Say the full name." if maybe else f"I can't find a project called {who}.")
        return True

    def go():
        prop = gate.Proposal("open a session", f"Run:  {cmd}\nIn:   {path}", {"cmd": cmd, "path": path})
        if not approve(prop, cfg):
            speak("Not opened.")
        elif open_session(path, cmd):
            speak(f"Opened {os.path.basename(path).replace('-', ' ')}.")
        else:
            speak("I couldn't open a terminal here. This works in iTerm, Terminal and tmux.")
    threading.Thread(target=go, daemon=True).start() if background else go()
    return True


# ---------- you talk to Jarvis; Jarvis answers what it can and asks before involving the agent ----------
# Two separate steps, on purpose. Small talk is answered WITHOUT the project conversation, so it cannot misstate the work.
# Questions about the work are answered ONLY from the conversation, or not at all. (One combined prompt made the model
# invent answers in testing; the split did not.)
PERSONA = "a calm, dry-witted British assistant: polite, brief, quietly confident, with the occasional understated joke"

CHAT_SYSTEM = """You are Jarvis, %(persona)s. You are the voice %(user)s talks to while they work with an AI coding agent.
Decide what they just said to you:
- Small talk (a greeting, thanks, a joke, how they or you feel, a question about you yourself): reply
  CHAT: <one or two short spoken sentences, in character>
- Anything else (their work, code, a task, a factual question, the news, the weather, the time): reply with the single word WORK
You know nothing about their project, the outside world, the time or the weather, so never state such facts. No emoji, no markdown.%(extra)s"""

ANSWER_SYSTEM = """You are Jarvis, a voice assistant between a person and their AI coding agent (%(agent)s).
Below is their recent conversation with the agent, oldest first. The person now says something to YOU.
If they ask about, or ask you to summarize, repeat or explain, something that is clearly stated in the conversation: do so in at
most four short spoken sentences, plain words, no markdown, using ONLY what the conversation says. "It", "that" and "the last
one" mean the agent's most recent reply unless they say "previous" or "earlier".
In every other case reply with exactly the single word ASK. That includes: the answer is not in the conversation, you are not
sure, it needs new work, code changes, running something, checking files, or an opinion or advice the conversation does not contain.
Never guess. Never invent file names, numbers or results.
Speak directly to them as "you". Never describe what they are asking or what you are about to do: just say the answer.
What "this project" is comes from the project's README, not from what was discussed."""

ASK_LINES = ("That one needs {agent}. Shall I ask?", "I'd have to put that to {agent}. Shall I?", "That's beyond what I've seen. Shall I ask {agent}?",
             "{agent} would know. Want me to ask?")

_POLITE = re.compile(r"^(?:(?:please|jarvis|hey|ok|okay|so|and|well|now|no|yes|yeah|right|actually|but|then|also)[\s,.]+|(?:can|could|would|will) you (?:please )?|i(?:'d| would) like you to |i want you to )+", re.I)
_QUESTION = re.compile(r"^(?:what|why|how|when|where|who|which|whose|did|does|do|is|are|was|were|has|have|had|remind me|tell me|"
                       r"explain|summari[sz]e|recap|repeat|go over|walk me through|say (?:that|it) again|what about|give me (?:the|a) (?:summary|gist|short|key|main))\b", re.I)
_REQUEST = re.compile(r"^(?:go ahead|let's|lets|you should|make|add|fix|run|create|update|change|remove|delete|write|build|implement|do it|"
                      r"deploy|install|refactor|rename|commit|push|revert|undo|open|close|start|stop|test|check|look (?:at|into)|find|search|show me the (?:code|file|diff))\b", re.I)
_TO_AGENT = re.compile(r"^(?:ask (?:claude|codex|the agent|it|him|her|them)|tell (?:claude|codex|the agent|it)|send (?:that|it|this)(?: to (?:claude|codex|the agent|it))?|"
                       r"pass (?:that|it) on|check with (?:claude|codex|the agent))\b[\s,:]*(.*)$", re.I | re.S)
_PREV = re.compile(r"\b(?:previous|earlier|the one before|before that|second to last|prior)\b", re.I)
_WORKY = re.compile(r"\b(code|file|files|test|tests|bug|build|deploy|commit|branch|migration|database|server|error|function|api|repo|"
                    r"pull request|merge|script|query|table|endpoint|package|install|log|logs|weather|news|temperature)\b|[\w-]+\.(?:py|ts|tsx|js|json|md|sql|toml|yml|yaml)\b|\d{2,}", re.I)
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+")


_META = re.compile(r"\b(?:the (?:person|user) (?:is|was|wants|asks|asked|has|said|says|seems)|i will (?:explain|summarize|answer|describe|provide)|"
                   r"they are asking|likely referring)\b", re.I)
_DANGLE = set("and but or so because to the a an of about with for that if when which who can could would will should is are was i we you it "
              "please then also like my your this these those".split())


def dangling(text):
    """Did the sentence stop half way ('Can you...', '... and')? Then the next thing you say belongs to it."""
    t = text.strip()
    if t.endswith("...") or t.endswith("\u2026"):
        return True
    if t.endswith(("?", "!")):
        return False
    words = re.findall(r"[a-z']+", t.lower())
    return len(words) >= 2 and words[-1] in _DANGLE


_WHO = re.compile(r"^(?:(?:who|what) are you|what(?:'s| is) your name|what (?:can|do) you do|what are you (?:for|capable of)|introduce yourself)\b", re.I)
ABOUT_ME = ("I'm Jarvis. I listen, answer what I can from your sessions, and pass the rest to {agent}. "
            "With your permission, naturally.")


def bare(text):
    """The sentence without politeness in front: 'can you please summarize that' -> 'summarize that'."""
    return _POLITE.sub("", text.strip())


def looks_like_question(text):
    """A question, or a request to explain / summarize / repeat: things Jarvis may answer itself. Work orders are not."""
    t = bare(text)
    return bool(t) and not _REQUEST.match(t) and bool(_QUESTION.match(t) or text.strip().endswith("?"))


def agent_label(s):
    return {"claude": "Claude", "codex": "Codex"}.get((s or {}).get("agent", ""), "the agent")


def _generate(messages, cfg, n, speak, timeout_key="answer_timeout"):
    from . import llm
    box = {}

    def work():
        try:
            box["out"] = llm.generate(messages, cfg, n)
        except Exception:
            pass
    th = threading.Thread(target=work, daemon=True)
    th.start()
    wait = float(cfg.get(timeout_key, 12))
    if not llm.loaded():
        if speak:
            speak("One moment.")
        wait = max(wait, 40.0)
    th.join(wait)
    return box.get("out", "").strip()


def _memory(memory):
    return "".join(f"They said: {q}\nYou said: {a}\n" for q, a in (memory or [])[-3:])


def talk(text, s, cfg, speak=None, memory=None):
    """What Jarvis does with a sentence said to it. Returns ("say", words) when Jarvis answers itself (small talk, or from the
    conversation), or ("agent", "") when the agent is needed. Work orders never reach the model: they are the agent's."""
    from . import llm
    t = bare(text)
    if not llm.usable(cfg) or not t or _REQUEST.match(t):
        return "agent", ""
    if _WHO.match(t):                                       # about itself: fixed words, so it never misdescribes what it can do
        return "say", ABOUT_ME.format(agent=agent_label(s))
    ctx = agents.claude_context(s["transcript"], int(cfg.get("answer_context_chars", 12000))) if s and s.get("transcript") else ""
    notes = project_notes(s)
    if notes:                                              # so "what is this project about?" can be answered before the agent said anything
        ctx = f"(The project's own README, for background:)\n{notes}\n\n(The conversation:)\n{ctx or '(nothing yet)'}"
    question, mem = looks_like_question(text), _memory(memory)
    small = bool(_SMALL.match(t)) and not _WORKY.search(t)

    def chat():
        if _WORKY.search(t) or _about_the_work(t, ctx):
            return None                                    # it refers to the work: small talk must not answer it
        who = (cfg.get("call_me") or "").strip()
        system = CHAT_SYSTEM % {"persona": cfg.get("persona") or PERSONA, "user": who or "the person",
                                "extra": f"\nAddress them as {who} now and then, not in every reply." if who else ""}
        out = _generate([{"role": "system", "content": system}, {"role": "user", "content": (f"EARLIER:\n{mem}\n" if mem else "") + f"THEY NOW SAY: {text}"}], cfg, 90, speak)
        m = re.match(r"^CHAT\s*:\s*(.+)$", out, flags=re.S)
        if not m and small and out and not re.match(r"^\W*(WORK|ASK)\b", out):
            m = re.match(r"^(.+)$", out, flags=re.S)       # obvious small talk answered without the "CHAT:" label
        words = _EMOJI.sub("", textprep.inline(m.group(1))).strip() if m else ""
        return words if words and len(words) <= 400 and not _WORKY.search(words) else None

    def answer():
        if len(ctx) < 80:
            return None                                    # nothing to ground an answer on
        out = _generate([{"role": "system", "content": ANSWER_SYSTEM % {"agent": agent_label(s)}},
                         {"role": "user", "content": f"CONVERSATION:\n{ctx}\n\n" + (f"EARLIER BETWEEN YOU AND THEM:\n{mem}\n" if mem else "") + f"THE PERSON NOW SAYS TO YOU: {text}"}], cfg, 200, speak)
        words = _EMOJI.sub("", textprep.inline(out)).strip()
        if not words or re.search(r"\bASK\b", words) or len(words) > 800 or _META.search(words):
            return None                                    # unsure, rambling, or narrating instead of answering: the agent gets it
        return words

    # obvious small talk: chat. A question: the conversation first, small talk only if that has no answer. Anything else: chat or the agent.
    steps = (chat,) if small else (answer, chat) if question else (chat,)
    for step in steps:
        words = step()
        if words:
            return "say", words
    return "agent", ""


_SMALL = re.compile(r"^(?:hi|hello|hey|good (?:morning|afternoon|evening|night)|thanks|thank you|cheers|nice|great|well done|good job|tell me a joke|"
                    r"(?:make|crack) (?:me )?(?:a )?joke|how are you|how(?:'s| is) it going|how are you (?:doing|holding up)|who are you|what are you|"
                    r"what(?:'s| is) your name|are you there|you there|i(?:'m| am) (?:tired|exhausted|bored|back|done|hungry)|never ?mind|sorry)\b", re.I)
_STOPWORDS = set("about after again before could doing every first going other really should their there these thing things think those where which while would "
                 "what when your yours being right still today please thanks great maybe might never always".split())


def _about_the_work(t, ctx):
    """Does the sentence use a distinctive word from the conversation? ('the timetable page' when the agent wrote about a timetable)"""
    words = {w for w in re.findall(r"[a-z]{5,}", t.lower())} - _STOPWORDS
    return bool(words) and bool(words & set(re.findall(r"[a-z]{5,}", ctx.lower())))


def project_notes(s, limit=3500):
    """The start of the project's README, as background Jarvis may answer from. Read as data, like everything else."""
    cwd = (s or {}).get("cwd") or ""
    if not cwd:
        return ""
    for name in ("README.md", "README.rst", "README.txt", "README", "readme.md"):
        try:
            with open(os.path.join(cwd, name), encoding="utf-8", errors="ignore") as fh:
                text = fh.read(limit * 2)
        except OSError:
            continue
        text = re.sub(r"<!--.*?-->|!\[[^\]]*\]\([^)]*\)|\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)", "", text, flags=re.S)       # badges, images, comments
        return text.strip()[:limit]
    return ""


_YES_WORD = r"(?:yes|yeah|yep|yup|ya|sure|ok|okay|alright|absolutely|definitely|of course|please do|go ahead|go for it|do it|do that|ask|ask it|ask (?:claude|cloud|codex|him|her|them)|send it)"
_YES = re.compile(rf"^{_YES_WORD}(?:\W+{_YES_WORD})*((?:\W+\w+){{0,4}})$")
_NOPE = re.compile(r"\b(no|not|don't|dont|but|wait|never|cancel|stop|instead|except|also|and)\b")


def casual_yes(text):
    """A relaxed yes for "shall I ask Claude?": 'sure', 'yep, ask Claude', 'okay go ahead'. Only used to pass YOUR OWN words on
    to the session in front, never for anything Jarvis composed (that needs the approval window)."""
    t = re.sub(r"[^\w\s']", " ", text.lower())
    t = re.sub(r"\b(?:please|then|well|jarvis|just|oh|um|uh)\b", " ", t)       # politeness and fillers do not change a yes
    m = _YES.match(re.sub(r"\s+", " ", t).strip())
    return bool(m) and not _NOPE.search(m.group(1) or "")


def ask_line(s):
    import random
    return random.choice(ASK_LINES).format(agent=agent_label(s))
