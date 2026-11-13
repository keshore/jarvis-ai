"""Where your transcribed speech goes. A sink only needs `send(text)` and `interrupt()`.

  iterm      write into an iTerm2 session (macOS)         target = session uuid
  tmux       send keys to a tmux pane                      target = pane id (e.g. %3)
  keystroke  type into the frontmost macOS app (any GUI)   needs Accessibility permission
  exec       run a command, text on stdin, speak its reply (works with ollama, llm, aichat, ...)
  stdout     print the transcript (pipe it anywhere)
"""
import os, subprocess, sys

from . import config


def _osa(script):
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True)


class Sink:
    def __init__(self, cfg):
        self.cfg = cfg

    def target(self):
        return config.read_state("target") or os.environ.get("LOCALVOICE_TARGET", "")

    def send(self, text):
        raise NotImplementedError

    def interrupt(self):
        pass


class Iterm(Sink):
    def _write(self, clause):
        sid = self.target().split(":")[-1]
        if not sid:
            print("  (no target: run `localvoice target` inside the tab you want)", flush=True)
            return
        r = _osa(f'''
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
        if r.stdout.strip() != "ok":
            print("  (could not find the iTerm tab:", (r.stdout or r.stderr).strip(), ")", flush=True)

    def send(self, text):
        esc = text.replace("\\", "\\\\").replace('"', '\\"')
        self._write(f'write text "{esc}"')

    def interrupt(self):
        self._write("write text (ASCII character 27) newline NO")


class Tmux(Sink):
    def send(self, text):
        t = self.target() or os.environ.get("TMUX_PANE", "")
        subprocess.run(["tmux", "send-keys", "-t", t, "-l", text])
        subprocess.run(["tmux", "send-keys", "-t", t, "Enter"])

    def interrupt(self):
        t = self.target() or os.environ.get("TMUX_PANE", "")
        subprocess.run(["tmux", "send-keys", "-t", t, "Escape"])


class Keystroke(Sink):
    def _activate(self):
        app = self.cfg.get("app")
        if app:
            _osa(f'tell application "{app}" to activate')

    def send(self, text):
        self._activate()
        esc = text.replace("\\", "\\\\").replace('"', '\\"')
        _osa(f'tell application "System Events" to keystroke "{esc}"\n'
             f'tell application "System Events" to key code 36')

    def interrupt(self):
        self._activate()
        _osa('tell application "System Events" to key code 53')


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
            from . import tts_client, textprep
            tts_client.speak(textprep.speak_text(reply, self.cfg.get("mode", "brief")))


class Stdout(Sink):
    def send(self, text):
        print(text, flush=True)


SINKS = {"iterm": Iterm, "tmux": Tmux, "keystroke": Keystroke, "exec": Exec, "stdout": Stdout}


def get(cfg):
    name = cfg.get("sink", "iterm")
    if name not in SINKS:
        sys.exit(f"unknown sink '{name}' (choose from {', '.join(SINKS)})")
    return SINKS[name](cfg)
