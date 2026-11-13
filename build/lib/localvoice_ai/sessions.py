"""Registry of voice-enabled sessions. A session is anything you talk to: a Claude Code tab, a Codex pane,
a desktop app, a wrapped CLI. Each records HOW to reach it (sink/target/app) and which terminal tab it
lives in (term), so the listener can send your speech to the one you are looking at."""
import json, os, re, time

from . import config, platform_


def _dir():
    return config.path("sessions")


def _file(sid):
    return os.path.join(_dir(), re.sub(r"[^\w.-]", "_", sid) + ".json")


def register(s):
    os.makedirs(_dir(), exist_ok=True)
    with open(_file(s["id"]), "w") as fh:
        json.dump(s, fh)


def get(sid):
    try:
        with open(_file(sid)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def all():
    out = []
    try:
        for name in sorted(os.listdir(_dir())):
            try:
                with open(os.path.join(_dir(), name)) as fh:
                    s = json.load(fh)
            except (OSError, ValueError):
                continue
            if s.get("pid") and not platform_.pid_alive(s["pid"]):        # wrapped program is gone
                remove(s["id"])
                continue
            out.append(s)
    except OSError:
        pass
    return out


def remove(sid):
    try:
        os.unlink(_file(sid))
    except OSError:
        pass


def detect(session, sink="", target="", app=""):
    """Work out how to reach the session that is calling us, from its environment."""
    iterm = os.environ.get("ITERM_SESSION_ID", "").split(":")[-1]
    tmux = os.environ.get("TMUX_PANE", "")
    if not sink:
        sink = "iterm" if iterm else "tmux" if tmux else "keystroke"
    if sink == "iterm":
        target = target or iterm
    elif sink == "tmux":
        target = target or tmux
    elif sink == "keystroke":
        app = app or platform_.front_app()      # the app you just typed /localvoice-ai into is in front
    return {"id": session, "sink": sink, "target": target, "app": app, "term": iterm, "created": time.time()}


def refresh(s):
    """Called when you submit a prompt in this session: it is in front right now, so re-learn where it is."""
    iterm = os.environ.get("ITERM_SESSION_ID", "").split(":")[-1]
    changed = False
    if iterm and s.get("term") != iterm:
        s["term"] = iterm
        if s["sink"] == "iterm":
            s["target"] = iterm
        changed = True
    if s["sink"] == "keystroke" and not iterm:
        front = platform_.front_app()
        if front and front != s.get("app"):
            s["app"], changed = front, True
    if changed:
        register(s)
    return s


def current():
    """The session you are looking at now, or None if it cannot be told."""
    ss = all()
    if not ss:
        return None
    front = platform_.front_app()
    f = platform_.iterm_focused() if front.lower().startswith("iterm") else ""
    for s in ss:
        if f and f in (s.get("term"), s.get("target") if s["sink"] == "iterm" else None):
            return s
    for s in ss:
        if s["sink"] == "keystroke" and s.get("app") and front and s["app"].lower() in front.lower():
            return s
    last = config.read_state("last_session")
    for s in ss:
        if s["id"] == last:
            return s
    return ss[0] if len(ss) == 1 else None
