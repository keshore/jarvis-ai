"""Everything that differs per operating system lives here. Each function degrades gracefully: when a
capability is missing it returns an empty value instead of raising, and the caller falls back."""
import os, re, shutil, subprocess, sys

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")
APPLE_SILICON = IS_MAC and os.uname().machine == "arm64"


def run(cmd, timeout=3, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    except Exception:
        return None


def _out(cmd, **kw):
    r = run(cmd, **kw)
    return (r.stdout or "").strip() if r and r.returncode == 0 else ""


def osascript(script):
    return run(["osascript", "-e", script])


# ---------- what is in front? (used to route your voice to the right session) ----------
def front_app():
    """Name (macOS), window title (Windows) or window name (Linux/X11) of the focused window; '' if unknown."""
    try:
        if IS_MAC:
            asn = _out(["lsappinfo", "front"])
            m = re.match(r'\s*"([^"]+)"', _out(["lsappinfo", "info", "-only", "name", asn]))
            return m.group(1) if m else ""
        if IS_WIN:
            import ctypes
            u = ctypes.windll.user32
            h = u.GetForegroundWindow()
            n = u.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, buf, n + 1)
            return buf.value
        if shutil.which("xdotool"):
            return _out(["xdotool", "getactivewindow", "getwindowname"])
    except Exception:
        pass
    return ""


def iterm_focused():
    """UUID of the iTerm2 tab in front (macOS only)."""
    if not IS_MAC:
        return ""
    r = osascript('tell application "iTerm2" to return id of current session of current window')
    return (r.stdout or "").strip() if r and r.returncode == 0 else ""


def activate_app(name):
    if IS_MAC and name:
        osascript(f'tell application "{name}" to activate')


# ---------- typing into whatever has focus ----------
def type_text(text, enter=True):
    """Type text into the focused window. macOS: AppleScript (needs Accessibility permission).
    Elsewhere: pynput (pip install 'jarvis-ai[keys]'; on Wayland use X11 or tmux)."""
    if IS_MAC:
        esc = text.replace("\\", "\\\\").replace('"', '\\"')
        osascript(f'tell application "System Events" to keystroke "{esc}"'
                  + ('\ntell application "System Events" to key code 36' if enter else ""))
        return True
    try:
        from pynput.keyboard import Controller, Key
        k = Controller()
        k.type(text)
        if enter:
            k.press(Key.enter); k.release(Key.enter)
        return True
    except Exception as e:
        print(f"  (cannot type: {e}; install pynput: pip install 'jarvis-ai[keys]')", flush=True)
        return False


def press_escape():
    if IS_MAC:
        osascript('tell application "System Events" to key code 53')
        return
    try:
        from pynput.keyboard import Controller, Key
        k = Controller(); k.press(Key.esc); k.release(Key.esc)
    except Exception:
        pass


# ---------- clipboard ----------
def clipboard():
    if IS_MAC:
        return _out(["pbpaste"])
    if IS_WIN:
        return _out(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"], timeout=5)
    for cmd in (["wl-paste", "-n"], ["xclip", "-selection", "clipboard", "-o"], ["xsel", "-ob"]):
        if shutil.which(cmd[0]):
            return _out(cmd)
    return ""


# ---------- processes ----------
def detach_kwargs():
    if IS_WIN:
        return {"creationflags": 0x00000008 | 0x00000200}     # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    return {"start_new_session": True}


def pid_alive(pid):
    try:
        if IS_WIN:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, 0, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
            return False
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def kill_pid(pid):
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        else:
            import signal
            os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
