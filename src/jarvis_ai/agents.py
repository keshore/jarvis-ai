"""Agent connectors: how Jarvis finds, reads and reaches the AI sessions on this machine WITHOUT a plugin or hooks.

A connector answers three questions for one kind of agent:
  discover()        which sessions are alive, where they run (folder, terminal) and whether they are busy
  reply reader      the text of a finished reply (`Tail`), read from the agent's own transcript
  how to reach it   which sink types into it (iTerm tab, tmux pane; found from the session's terminal device)

Connectors here: Claude Code (any OS). Any other CLI works through `jarvis-ai run -- <cmd>` (the pty connector),
and tools with a notify command through `jarvis-ai hook json`. Everything a connector reads is DATA: it is spoken
or shown, never executed and never treated as an instruction."""
import glob, json, os, re, shutil, subprocess

from . import platform_


# ---------- which terminal owns a tty (so we can type into the right tab/pane on any OS) ----------
def _iterm_ttys():
    if not platform_.IS_MAC:
        return {}
    r = platform_.osascript('''
tell application "System Events" to if not (exists process "iTerm2") then return ""
tell application "iTerm2"
  set out to ""
  repeat with w in windows
    repeat with t in tabs of w
      repeat with s in sessions of t
        set out to out & (id of s) & "|" & (tty of s) & linefeed
      end repeat
    end repeat
  end repeat
  return out
end tell''')
    out = {}
    for line in ((r.stdout if r else "") or "").splitlines():
        sid, _, tty = line.partition("|")
        if tty:
            out[tty.strip()] = sid.strip()
    return out


def _tmux_ttys():
    if not shutil.which("tmux"):
        return {}
    try:
        r = subprocess.run(["tmux", "list-panes", "-a", "-F", "#{pane_tty}|#{pane_id}"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return {}
    return dict(line.split("|", 1) for line in r.stdout.splitlines() if "|" in line)


def _tty_of(pid):
    if platform_.IS_WIN:
        return ""
    try:
        t = subprocess.run(["ps", "-o", "tty=", "-p", str(pid)], capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return "" if not t or t.startswith("?") else ("/dev/" + t if not t.startswith("/dev/") else t)


def app_of(pid):
    """macOS: the visible app that hosts this process (Terminal, VS Code, Warp, Ghostty, Claude ...), as the system names it."""
    if not platform_.IS_MAC:
        return ""
    p = int(pid)
    for _ in range(12):
        try:
            out = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(p)], capture_output=True, text=True, timeout=3).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
        if not out:
            return ""
        ppid, _, comm = out.partition(" ")
        if ".app/Contents/MacOS/" in comm:
            try:
                asn = subprocess.run(["lsappinfo", "find", f"pid={p}"], capture_output=True, text=True, timeout=3).stdout
            except (OSError, subprocess.SubprocessError):
                asn = ""
            m = re.search(r'"([^"]+)"', asn)
            if m:
                return m.group(1)                         # a real, visible app
        try:
            p = int(ppid)
        except ValueError:
            return ""
        if p <= 1:
            return ""
    return ""


def reach(tty, iterm=None, tmux=None):
    """(sink, target) for a terminal device. tmux wins over iTerm: a pane inside a tab must get the keys."""
    if not tty:
        return "", ""
    tmux = _tmux_ttys() if tmux is None else tmux
    if tty in tmux:
        return "tmux", tmux[tty]
    iterm = _iterm_ttys() if iterm is None else iterm
    if tty in iterm:
        return "iterm", iterm[tty]
    return "", ""


# ---------- Claude Code ----------
def claude_home():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def claude_transcript(sid, cwd):
    base = os.path.join(claude_home(), "projects")
    p = os.path.join(base, re.sub(r"[^A-Za-z0-9]", "-", cwd or ""), sid + ".jsonl")
    if os.path.exists(p):
        return p
    hits = glob.glob(os.path.join(base, "*", sid + ".jsonl"))
    return hits[0] if hits else p


def claude_sessions(iterm=None, tmux=None):
    """Live interactive Claude Code sessions, from Claude's own registry (~/.claude/sessions/<pid>.json)."""
    out = []
    files = glob.glob(os.path.join(claude_home(), "sessions", "*.json"))
    if not files:
        return out
    iterm = _iterm_ttys() if iterm is None else iterm
    tmux = _tmux_ttys() if tmux is None else tmux
    for f in files:
        try:
            with open(f) as fh:
                d = json.load(fh)
            pid, sid = int(d["pid"]), str(d["sessionId"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if d.get("kind", "interactive") != "interactive" or not platform_.pid_alive(pid):
            continue
        cwd = str(d.get("cwd") or "")
        sink, target = reach(_tty_of(pid), iterm, tmux)
        app = ""
        if not sink:
            app = app_of(pid)                             # any other terminal or app: type into its window when it is in front
            sink = "keystroke" if app else ""
        out.append({"app": app, "id": sid, "agent": "claude", "pid": pid, "cwd": cwd, "name": str(d.get("name") or os.path.basename(cwd) or sid[:8]),
                    "busy": d.get("status") == "busy", "sink": sink, "target": target, "term": target if sink == "iterm" else "",
                    "transcript": claude_transcript(sid, cwd)})
    return out


def _claude_text(msg):
    c = msg.get("content")
    if isinstance(c, str):
        return c
    return "\n".join(b.get("text", "") for b in c or [] if isinstance(b, dict) and b.get("type") == "text").strip()


class Tail:
    """Follows one transcript and yields each finished reply once. Starts at the end: old replies are not re-read."""

    def __init__(self, path):
        self.path, self.pos, self.buf = path, None, ""

    def poll(self):
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return []
        if self.pos is None or size < self.pos:           # first look, or the file was replaced
            self.pos = size
            return []
        if size == self.pos:
            return []
        with open(self.path, "rb") as fh:
            fh.seek(self.pos)
            chunk = fh.read(size - self.pos)
        self.pos = size
        self.buf += chunk.decode("utf-8", "ignore")
        *lines, self.buf = self.buf.split("\n")           # keep a half-written last line for the next poll
        done = []
        for line in lines:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            m = d.get("message") or {}
            if d.get("type") == "assistant" and not d.get("isSidechain") and m.get("stop_reason") == "end_turn":
                text = _claude_text(m)
                if text:
                    done.append(text)
        return done


CONNECTORS = {"claude": claude_sessions}


def discover():
    """Every reachable agent session on this machine, from all connectors."""
    iterm, tmux = _iterm_ttys(), _tmux_ttys()
    out = []
    for fn in CONNECTORS.values():
        try:
            out += fn(iterm, tmux)
        except Exception as e:                            # one broken connector must not silence the others
            print("  (connector failed:", e, ")", flush=True)
    return out


def find(name, ss):
    """The session someone means by a spoken name ('the portal session', 'jarvis'). None if unclear."""
    want = re.sub(r"\b(the|session|tab|project|one|claude|agent|window)\b", " ", name.lower())
    words = [w for w in re.findall(r"[a-z0-9]+", want) if len(w) > 1]
    if not words:
        return None
    scored = []
    for s in ss:
        hay = re.findall(r"[a-z0-9]+", (s.get("name", "") + " " + os.path.basename(s.get("cwd", ""))).lower())
        score = sum(1 for w in words if any(h == w or (len(w) > 2 and (h.startswith(w) or w.startswith(h))) for h in hay))
        if score:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    if not scored or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        return None                                       # nothing, or two equally good matches: do not guess
    return scored[0][1]
