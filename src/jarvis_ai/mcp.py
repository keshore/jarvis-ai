"""A minimal MCP server over stdio (newline-delimited JSON-RPC 2.0), with no extra dependency.
It lets any agent that speaks MCP use the voice: `speak` reads text aloud, `stop_speaking` silences it.
Nothing here can type, approve or run anything: speaking is the only effect."""
import json, sys

from . import __version__, tts_client

PROTOCOL = "2024-11-05"
TOOLS = [
    {"name": "speak", "description": "Read text aloud to the user through the speakers of this machine. Use short, plain sentences.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string", "description": "What to say"}}, "required": ["text"]}},
    {"name": "stop_speaking", "description": "Stop the voice at once.", "inputSchema": {"type": "object", "properties": {}}},
]
MAX_CHARS = 4000


def call(name, args, speak=None, stop=None):
    """-> (text, is_error)"""
    if name == "speak":
        text = args.get("text") if isinstance(args, dict) else None
        if not isinstance(text, str) or not text.strip():
            return "`text` must be a non-empty string", True
        (speak or tts_client.speak)(text[:MAX_CHARS])
        return "spoken" + (f" (first {MAX_CHARS} characters)" if len(text) > MAX_CHARS else ""), False
    if name == "stop_speaking":
        (stop or tts_client.stop)()
        return "stopped", False
    return f"unknown tool: {name}", True


def handle(msg, **kw):
    """One JSON-RPC message in -> the response dict, or None for notifications."""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        return None                                        # notifications (e.g. notifications/initialized) get no reply
    ok = lambda result: {"jsonrpc": "2.0", "id": mid, "result": result}
    if method == "initialize":
        return ok({"protocolVersion": PROTOCOL, "capabilities": {"tools": {}}, "serverInfo": {"name": "jarvis-ai", "version": __version__}})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        text, err = call(params.get("name"), params.get("arguments") or {}, **kw)
        return ok({"content": [{"type": "text", "text": text}], "isError": err})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def serve(stdin=None, stdout=None, **kw):
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            out = handle(msg, **kw) if isinstance(msg, dict) else {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
        if out is not None:
            stdout.write(json.dumps(out) + "\n")
            stdout.flush()
