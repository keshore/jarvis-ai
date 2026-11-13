"""Where your transcribed speech goes. A sink needs only `send(text)` and `interrupt()`.

  iterm      write into an iTerm2 tab                        (macOS)            target = tab uuid
  tmux       send keys to a tmux pane                        (macOS/Linux/WSL)  target = pane id, e.g. %3
  keystroke  type into the focused window of any app         (all OSes)         app = window to bring to front
  pty        type into a program started with `jarvis-ai run -- <cmd>`         (macOS/Linux)
  exec       run a command per sentence, speak its reply (ollama, llm, aichat ...)
  llm        talk to the built-in local model (mlx-lm or Ollama), with a short memory
  stdout     print the transcript (pipe it anywhere)
"""
import os, socket, subprocess, sys, threading

from . import config, platform_


class Sink:
    def __init__(self, cfg, target="", app=""):
        self.cfg, self._target, self.app = cfg, target, app

    def target(self):
        return self._target or config.read_state("target") or os.environ.get("JARVIS_AI_TARGET", "")

    def send(self, text):
        raise NotImplementedError

    def interrupt(self):
        pass


class Iterm(Sink):
    def _write(self, clause):
        sid = self.target().split(":")[-1]
        if not platform_.IS_MAC:
            print("  (the iterm sink only works on macOS; use tmux, keystroke or pty)", flush=True)
            return
        if not sid:
            print("  (no iTerm tab known for this session)", flush=True)
            return
        r = platform_.osascript(f'''
tell application "iTerm2"
  repeat with w in windows
    repeat with t in tabs of w
      repeat with s in sessions of t
        if id of s is "{sid}" then
          tell s to {clause}
          return "ok"
        end if
      end repeat
    end repeat
  end repeat
  return "missing"
end tell''')
        if not r or (r.stdout or "").strip() != "ok":
            print("  (could not find the iTerm tab:", (r.stdout or r.stderr or "").strip() if r else "osascript failed", ")", flush=True)

    def send(self, text):
        esc = text.replace("\\", "\\\\").replace('"', '\\"')
        self._write(f'write text "{esc}"')

    def interrupt(self):
        self._write("write text (ASCII character 27) newline NO")      # Escape


class Tmux(Sink):
    def _pane(self):
        return self.target() or os.environ.get("TMUX_PANE", "")

    def send(self, text):
        subprocess.run(["tmux", "send-keys", "-t", self._pane(), "-l", text])
        subprocess.run(["tmux", "send-keys", "-t", self._pane(), "Enter"])

    def interrupt(self):
        subprocess.run(["tmux", "send-keys", "-t", self._pane(), "Escape"])


class Keystroke(Sink):
    """Types into whatever window is in front. Mind the focus: your words go where the cursor is."""

    def _app(self):
        return self.app or self.cfg.get("app", "")

    def send(self, text):
        platform_.activate_app(self._app())
        platform_.type_text(text)

    def interrupt(self):
        platform_.activate_app(self._app())
        platform_.press_escape()


class Pty(Sink):
    def _msg(self, payload):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(self.target())
            s.sendall(payload)
        except OSError as e:
            print("  (the wrapped program is gone:", e, ")", flush=True)
        finally:
            s.close()

    def send(self, text):
        self._msg(b"T" + text.encode("utf-8"))

    def interrupt(self):
        self._msg(b"E")


class Exec(Sink):
    def send(self, text):
        cmd = self.cfg.get("exec_cmd")
        if not cmd:
            print("  (sink=exec needs exec_cmd in config.toml)", flush=True)
            return
        r = subprocess.run(cmd, shell=True, input=text, capture_output=True, text=True)
        reply = (r.stdout or "").strip()
        if reply:
            print(reply, flush=True)
            from . import textprep, tts_client
            tts_client.speak(textprep.speak_text(reply, self.cfg.get("mode", "brief")))


class Llm(Sink):
    """Talk to the local model directly: keeps a short conversation, prints and speaks each reply."""

    def __init__(self, cfg, target="", app=""):
        super().__init__(cfg, target, app)
        self.history = []
        self.lock = threading.Lock()

    def target(self):
        return "llm"

    def send(self, text):
        threading.Thread(target=self._reply, args=(text,), daemon=True).start()

    def _reply(self, text):
        from . import llm, textprep, tts_client
        with self.lock:
            self.history = (self.history + [{"role": "user", "content": text}])[-20:]
            msgs = [{"role": "system", "content": self.cfg["llm_system"]}] + self.history
            try:
                reply = llm.generate(msgs, self.cfg)
            except Exception as e:
                print("  (local model error:", e, ")", flush=True)
                self.history.pop()
                return
            self.history.append({"role": "assistant", "content": reply})
        print("\n" + reply + "\n", flush=True)
        textprep.save_last("llm", reply)
        tts_client.speak(textprep.speak_text(reply))


class Null(Sink):
    """A session Jarvis can read (its replies) but cannot type into: it is not in a terminal we know how to reach."""

    def send(self, text):
        print("  (cannot type into this session: it is not in iTerm or tmux. Use `jarvis-ai run -- <cmd>` or the keystroke sink.)", flush=True)


class Stdout(Sink):
    def send(self, text):
        print(text, flush=True)


SINKS = {"iterm": Iterm, "tmux": Tmux, "keystroke": Keystroke, "pty": Pty, "exec": Exec, "llm": Llm, "stdout": Stdout, "none": Null}


def auto_name():
    if os.environ.get("ITERM_SESSION_ID") and platform_.IS_MAC:
        return "iterm"
    if os.environ.get("TMUX_PANE"):
        return "tmux"
    return "keystroke"


def get(cfg):
    """The default sink, used when no session is registered."""
    name = cfg.get("sink", "auto")
    name = auto_name() if name == "auto" else name
    if name not in SINKS:
        sys.exit(f"unknown sink '{name}' (choose from {', '.join(SINKS)})")
    return SINKS[name](cfg)


def for_session(cfg, s):
    return SINKS[s["sink"]](cfg, s.get("target", ""), s.get("app", ""))
