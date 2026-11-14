"""Local text prep: what to say out loud. Stdlib only. No LLM, no network, no tokens."""
import os, re, json

from . import config


# ---------- mode ----------
def get_mode():
    m = config.read_state("mode") or config.load().get("mode", "brief")
    return m if m in ("brief", "full") else "brief"


def set_mode(m):
    if m in ("brief", "full"):
        config.write_state("mode", m)


# ---------- markdown -> speakable blocks ----------
def inline(s):
    s = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", s)      # links -> their text
    s = re.sub(r"https?://\S+", "", s)                     # bare urls
    s = re.sub(r"`([^`]*)`", r"\1", s)                     # inline code: say the word
    s = re.sub(r"\*+|~~", "", s)                           # bold / italic / strike
    s = re.sub(r"(?<!\w)_+|_+(?!\w)", "", s)               # _emphasis_
    s = re.sub(r"(?<=\w)_(?=\w)", " ", s)                  # snake_case -> snake case
    return re.sub(r"\s+", " ", s).strip()


def blocks(raw):
    t = re.sub(r"```.*?```", "\n\n", raw, flags=re.S)      # fenced code: skipped
    t = re.sub(r"```.*\Z", "", t, flags=re.S)              # unclosed fence
    items, buf = [], []

    def flush():
        if buf:
            txt = inline(" ".join(buf))
            if txt:
                items.append(("p", txt))
            buf.clear()

    for para in re.split(r"\n\s*\n", t):
        for line in para.splitlines():
            l = line.strip()
            if not l or l.startswith("|") or re.fullmatch(r"[-*_=\s]{3,}", l):
                continue                                    # tables, rules
            m = re.match(r"#{1,6}\s*(.+)", l)
            if m:
                flush(); txt = inline(m.group(1))
                if txt: items.append(("h", txt))
                continue
            m = re.match(r"(?:[-*+]|\d+[.)])\s+(.+)", l)
            if m:
                flush(); txt = inline(m.group(1))
                if txt: items.append(("li", txt))
                continue
            buf.append(re.sub(r"^>\s?", "", l))
        flush()
    return items


def endp(s):
    return s if re.search(r"[.!?:;,]$", s) else s + "."


def sentences(s):
    return [x for x in re.split(r"(?<=[.!?])\s+", s) if x]


def full_text(items):
    t = " ".join(endp(x) for _, x in items if x)
    return re.sub(r"(\s*\.){2,}", ".", t).strip()


def brief_text(items):
    full = full_text(items)
    if len(full) <= 260:
        return full
    prose = [x for k, x in items if k == "p"] or [x for _, x in items]
    if not prose:
        return ""
    ss = sentences(prose[0])
    lead = ss[0]
    if len(lead) < 50 and len(ss) > 1:
        lead += " " + ss[1]
    if len(lead) > 240:
        lead = lead[:240].rsplit(" ", 1)[0] + "."
    out = endp(lead)
    # always voice a question aimed at you, from the tail of the reply
    tail = []
    for _, x in items[-3:]:
        tail += sentences(x)
    qs = [s for s in tail if s.endswith("?")]
    if qs and qs[-1] not in out:
        out += " " + qs[-1]
    if len(full) > 2 * len(out):
        out += " Details are on screen."
    return out


# ---------- spoken-command recognition (used by the listener) ----------
def norm(text):
    t = text.lower().strip()
    t = re.sub(r"[.,!?\"']", "", t)
    t = re.sub(r"^(?:please |can you |could you |hey claude )+", "", t)
    return re.sub(r"\s+", " ", t).strip()


_MODE_FULL = re.compile(r"^(?:read (?:everything|it all|all|the full (?:response|reply|answer)) "
                        r"(?:from now on|always|by default|every time)|(?:full|read ?everything|read ?all) mode)$")
_MODE_BRIEF = re.compile(r"^(?:(?:summaries only|only (?:read )?summaries|just (?:the )?summar(?:y|ies)|"
                         r"read (?:only )?summaries|read (?:the )?summary) "
                         r"(?:from now on|always|by default|every time)|(?:brief|summary|summaries|short) mode)$")
_FULL = re.compile(r"^read (?:(?:it|that|this) (?:all|in full|out loud|aloud|out|to me)(?: out loud| aloud)?|"
                   r"(?:all|everything|(?:the )?(?:whole|full|entire|complete) "
                   r"(?:response|reply|answer|thing|message))(?: out loud| aloud| out| to me)?)$")
_BRIEF = re.compile(r"^(?:(?:give me |read |say )?(?:the )?(?:summary|short version|gist|tl;?dr|brief version)"
                    r"(?: of (?:that|it|this))?|summari[sz]e (?:it|that|this)(?: for me| to me| out loud| briefly)?)$")
_CLIP_FULL = re.compile(r"^read (?:the |my )?clipboard(?: out loud| aloud)?$|^read (?:what i (?:just )?copied|the copied text)$")
_CLIP_BRIEF = re.compile(r"^summari[sz]e (?:the |my )?clipboard$|^summari[sz]e (?:what i (?:just )?copied|the copied text)$")
_STOP = re.compile(r"^(?:stop|be quiet|quiet|shut up|stop talking|stop reading)$")
_INTERRUPT = re.compile(r"^(?:interrupt|cancel|cancel that|stop that|stop working|abort|escape)$")


def classify(text):
    t = norm(text)
    m = re.match(r"^(read|repeat|say|summari[sz]e|give me|recap)\b.*\b(?:(?:previous|earlier|prior) (?:response|reply|answer|message|one|thing)|"
                 r"one before(?: that)?|before that)(?: again| out loud| aloud| for me| to me)*$", t)
    if m and len(t.split()) <= 10:                       # "summarize the previous response": which reply is decided by the caller
        return "full" if m.group(1) in ("read", "repeat", "say") else "brief"
    for name, rx in (("clip_full", _CLIP_FULL), ("clip_brief", _CLIP_BRIEF), ("mode_full", _MODE_FULL), ("mode_brief", _MODE_BRIEF), ("full", _FULL),
                     ("brief", _BRIEF), ("stop", _STOP), ("interrupt", _INTERRUPT)):
        if rx.match(t):
            return name
    return None


# ---------- storage of the last reply per key (session / pane / tab) ----------
def _last_path(key):
    return config.path("last", re.sub(r"[^\w.-]", "_", key) + ".md")


def save_last(key, raw):
    os.makedirs(config.path("last"), exist_ok=True)
    with open(_last_path(key), "w") as fh:
        fh.write(raw)


def load_last(key):
    try:
        return open(_last_path(key)).read()
    except OSError:
        return ""


def speak_text(raw, mode=None):
    """What to say for a reply, in the given mode ('full' or 'brief')."""
    items = blocks(raw)
    return full_text(items) if (mode or get_mode()) == "full" else brief_text(items)


# ---------- what the microphone picks up that is not speech to act on ----------
JUNK = {"", "you", "thank you", "thanks", "thanks for watching", "bye", "goodbye",
        "we'll see you next time", "see you next time", "see you in the next video",
        "thank you for watching", "thanks for listening", "i'll see you next time",
        "subtitles by the amara.org community"}

# thinking noises ("Hmm.", "Mmm.", "Uh...") are not something to act on; "mm-hmm" and "uh-huh" are left alone (they mean yes)
FILLER = re.compile(r"(?:h+m+|m{2,}|u+h+|u+m+|e+r+m*|a+h+)(?:[\s,.!?\u2026]+(?:h+m+|m{2,}|u+h+|u+m+|e+r+m*|a+h+))*")


def noise(text):
    """True for what should be dropped unheard: Whisper's stock phrases on silence, bare punctuation, thinking noises."""
    t = text.lower().strip(" .!?,\u2026")
    return t in JUNK or bool(re.fullmatch(r"[\W_]*", text)) or bool(FILLER.fullmatch(t))
