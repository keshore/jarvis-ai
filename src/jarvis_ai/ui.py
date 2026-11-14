"""Jarvis's window: a page served to this machine only.

Safety of the little web server:
- it listens on 127.0.0.1, on a port picked at start
- every request needs the secret made at start (in the address the first time, then a cookie only this page can send)
- the Host header must be this machine, so another website cannot reach it by pointing a name at 127.0.0.1
- changes need a header a plain web form cannot send, so another website cannot post to it
- an API key can be stored or removed here, never read back"""
import json, os, secrets, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import assistant, brain, config, keys, llm
from .ui_page import PAGE

MAX_BODY = 20_000


def voices():
    try:
        import numpy as np
        return sorted(np.load(config.path("models", "voices-v1.0.bin")).keys())
    except Exception:
        return []


def state(cfg=None):
    cfg = cfg or config.load()
    return {"status": assistant.status(), "paused": os.path.exists(config.path(".paused")),
            "brain": brain.provider(cfg), "brain_text": brain.describe(cfg),
            "keys": {n: keys.has(n) for n in keys.ENV}, "local": llm.backend(cfg) or "",
            "settings": {k: cfg.get(k) for k in config.SETTINGS}, "voices": voices()}


def make_handler(jarvis, token, port):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):                           # nothing about requests goes to the log (addresses carry the secret)
            pass

        def _send(self, code, body=b"", ctype="application/json", extra=()):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _allowed(self, query=None):
            if self.headers.get("Host", "") not in hosts:
                return False
            cookie = self.headers.get("Cookie", "")
            got = next((c.split("=", 1)[1] for c in cookie.replace(" ", "").split(";") if c.startswith("jarvis=")), "")
            if not got and query is not None:
                got = (query.get("k") or [""])[0]
            return secrets.compare_digest(got, token)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if not self._allowed(q if u.path == "/" else None):
                return self._send(403, {"error": "open Jarvis from its own icon or command"})
            if u.path == "/":
                csp = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src data:"
                return self._send(200, PAGE.encode(), "text/html",
                                  [("Set-Cookie", f"jarvis={token}; HttpOnly; SameSite=Strict; Path=/"), ("Content-Security-Policy", csp)])
            if u.path == "/state":
                return self._send(200, state())
            if u.path == "/events":
                try:
                    last = int((q.get("last") or ["0"])[0])
                except ValueError:
                    last = 0
                return self._send(200, assistant.EVENTS.since(last))
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._allowed() or self.headers.get("X-Jarvis") != "1":
                return self._send(403, {"error": "not allowed"})
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if n > MAX_BODY:
                    return self._send(413, {"error": "too long"})
                d = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(d, dict):
                    raise ValueError
            except ValueError:
                return self._send(400, {"error": "bad request"})
            p = urlparse(self.path).path
            try:
                if p == "/say":
                    jarvis.hear(str(d.get("text", ""))[:4000], typed=True)
                elif p == "/stop":
                    jarvis.interrupt()
                elif p == "/clear":
                    jarvis.clear()
                elif p == "/mic":
                    f = config.path(".paused")
                    if d.get("on"):
                        if os.path.exists(f):
                            os.unlink(f)
                        assistant.status("listening")
                    else:
                        config.write_state(".paused", "1")
                        assistant.status("paused")
                elif p == "/settings":
                    config.save_settings({k: v for k, v in d.items() if k in config.SETTINGS})
                elif p == "/key":
                    name = str(d.get("name", ""))
                    if name not in keys.ENV:
                        return self._send(400, {"error": "unknown key"})
                    if d.get("value"):
                        keys.put(name, str(d["value"]))
                    else:
                        keys.remove(name)
                else:
                    return self._send(404, {"error": "not found"})
            except (ValueError, RuntimeError, TypeError) as e:
                return self._send(400, {"error": str(e)})
            self._send(200, state())

    return H


def start(jarvis, cfg):
    """Serve the window in the background. Returns its address (with the secret); also written to ui.url for the launcher."""
    token = secrets.token_urlsafe(24)
    srv = ThreadingHTTPServer(("127.0.0.1", int(cfg.get("ui_port", 0))), BaseHTTPRequestHandler)
    port = srv.server_address[1]
    srv.RequestHandlerClass = make_handler(jarvis, token, port)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/?k={token}"
    config.write_secret("ui.url", url)
    return url, srv
