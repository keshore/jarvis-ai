"""Understanding what you meant, beyond exact phrases. Three levels (config `frontend`):

  off        only the built-in phrases (textprep.classify) are commands
  commands   (default) built-in phrases, loose wording without any model, then, if a local LLM exists, short sentences that
             look like a request to the voice are interpreted by it. Everything else goes to the AI untouched.
  assistant  the local LLM sees every sentence: it may run a command or forward the sentence to the AI, lightly cleaned of dictation slips.

Guard rails: the model can only pick from a fixed list of actions; unsure, too slow, unavailable or malformed means the
original sentence goes to the AI unchanged; a cleaned-up sentence is used only if it stays close to what you said."""
import difflib, json, re, threading

from . import llm, textprep

ACTIONS = ("forward", "full", "brief", "stop", "interrupt", "mode_full", "mode_brief", "clip_full", "clip_brief", "help")
_STANDING = re.compile(r"from now on|always|by default|every time|going forward|each time|from here on")
_ABOUT_ME = re.compile(r"\b(you|your|yourself|jarvis|voice|assistant)\b")
MAX_WORDS_COMMANDS = 12          # `commands` level: only short sentences are even considered

_FILLER = set("it that this me the reply response answer message thing out loud aloud to of in please can you could would "
              "now again one more time a for hey claude just give version all whole full entire complete completely fully everything".split())
_READ = {"read", "say", "speak", "tell", "play", "repeat"}
_FULL_W = {"all", "whole", "full", "entire", "complete", "completely", "fully", "everything", "detail", "details", "detailed", "long", "longer"}
_BRIEF_W = {"summary", "summarize", "summarise", "summarized", "short", "shorter", "brief", "briefly", "gist", "tldr", "tl;dr", "quick", "quickly"}


_Q = (r"(?:be quiet|quiet|silence|shut up|hush|enough|that's enough|thats enough|stop|stop it|stop talking|stop reading|hold on|wait|pause|"
      r"one second|one moment|hang on)")
_QUIET = re.compile(rf"^(?:ok(?:ay)? |please |jarvis |hey )*{_Q}(?: {_Q})*(?: please| now| for a (?:second|moment|minute|bit)| jarvis| thanks)*$")


def loose(text):
    """Looser wording for the two most common requests, with no model: 'read me the whole thing', 'say all of it'."""
    words = re.sub(r"[^\w\s;']", " ", text.lower()).split()
    if 1 <= len(words) <= 7 and _QUIET.search(" ".join(words)) and not any(w in ("the", "this", "that") and i > 3 for i, w in enumerate(words)):
        return "stop"                                   # "be quiet for a second", "okay that's enough", "hold on"
    if not 2 <= len(words) <= 9:
        return None
    rest = [w for w in words if w not in _READ]
    if len(rest) == len(words) and not (set(words) & _BRIEF_W):
        return None
    if any(w not in _FILLER | _FULL_W | _BRIEF_W | _READ for w in words):
        return None                                     # names something else ("read the auth file"): not ours
    if set(words) & _BRIEF_W:
        return "brief"
    if set(words) & _FULL_W and set(words) & _READ:
        return "full"
    return None


SYSTEM = """You sit between a person and their AI coding agent. They talk; you decide what happens to each sentence.
Reply with ONE line of JSON only: {"action": "...", "text": "...", "say": "..."}

Actions:
  forward    the sentence is for the coding agent (anything about code, files, tasks, questions to the agent). DEFAULT.
  full       read the agent's last reply aloud in full
  brief      read a short summary of the agent's last reply
  stop       be quiet now
  interrupt  stop the agent's current work
  mode_full  from now on read every reply in full
  mode_brief from now on read only summaries
  clip_full / clip_brief   read / summarize the clipboard
  help       the person asks what YOU (the voice assistant) can do or how to use you
mode_full / mode_brief only when they clearly say "from now on", "always" or "by default"; a one-off request is full / brief.
"text" is only for forward: the sentence with obvious speech-to-text slips fixed. Never add, remove or reorder ideas.
When unsure, use forward with the sentence unchanged."""


def _parse(out):
    m = re.search(r"\{.*\}", out, flags=re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    return d if isinstance(d, dict) and d.get("action") in ACTIONS else None


def _ask(text, cfg):
    box = {}

    def work():
        try:
            box["out"] = llm.generate([{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}], cfg, 120)
        except Exception:
            pass

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(float(cfg.get("frontend_timeout", 6)))
    return _parse(box.get("out", "")) if "out" in box else None      # None on timeout/failure: fail open


def interpret(text, cfg, use_model=True):
    """-> ("command", name) | ("forward", text to send on). `use_model=False`: only the fixed and loose phrases decide
    (used when you talk to Jarvis, where the conversation step handles everything else)."""
    c = textprep.classify(text) or loose(text)
    if c:
        return "command", c
    level = cfg.get("frontend", "commands") if use_model else "off"
    if level == "off" or not llm.usable(cfg):
        return "forward", text
    if level == "commands" and len(text.split()) > MAX_WORDS_COMMANDS:
        return "forward", text
    d = _ask(text, cfg)
    if not d or d["action"] == "forward":
        cleaned = (d or {}).get("text") if level == "assistant" else None
        if cleaned and isinstance(cleaned, str) and difflib.SequenceMatcher(None, text.lower(), cleaned.lower()).ratio() >= 0.8:
            return "forward", cleaned.strip()
        return "forward", text
    action = d["action"]
    if action == "help" and not _ABOUT_ME.search(text.lower()):
        return "forward", text                          # a question about the code, not about the voice: the AI should get it
    if action in ("mode_full", "mode_brief") and not _STANDING.search(text.lower()):
        action = action[len("mode_"):]                  # "I'd like to hear everything" is a one-off, not a new default
    return "command", action
