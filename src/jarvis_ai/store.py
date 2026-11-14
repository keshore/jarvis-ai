"""Conversation history, kept on this computer only: one SQLite file in Jarvis's folder, readable by you alone.
Nothing here is ever sent anywhere. `retention_days` decides how long conversations stay:
  -1  nothing is saved (the conversation lives in memory until you start a new one or quit)
   0  kept until you delete them
   N  deleted N days after their last message"""
import os, sqlite3, time, uuid

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conv TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                                     role TEXT NOT NULL, text TEXT NOT NULL, t REAL NOT NULL, brain TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS messages_conv ON messages(conv, id);
"""


def _db():
    config.ensure()
    f = config.path("history.db")
    if not os.path.exists(f):
        os.close(os.open(f, os.O_WRONLY | os.O_CREAT, 0o600))          # only you can read it
    db = sqlite3.connect(f, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    return db


def title_of(text):
    t = " ".join(text.split())
    return (t[:57].rstrip() + "...") if len(t) > 60 else (t or "Conversation")


def create(first_text, now=None):
    now = now or time.time()
    cid = uuid.uuid4().hex
    with _db() as db:
        db.execute("INSERT INTO conversations VALUES (?, ?, ?, ?)", (cid, title_of(first_text), now, now))
    return cid


def add(cid, role, text, brain="", now=None):
    now = now or time.time()
    with _db() as db:
        if not db.execute("SELECT 1 FROM conversations WHERE id = ?", (cid,)).fetchone():
            return False                                               # deleted meanwhile: do not bring it back
        db.execute("INSERT INTO messages (conv, role, text, t, brain) VALUES (?, ?, ?, ?, ?)", (cid, role, text, now, brain))
        db.execute("UPDATE conversations SET updated = ? WHERE id = ?", (now, cid))
    return True


def conversations(query="", limit=200):
    """Newest first. `query` searches titles and everything said."""
    with _db() as db:
        if query.strip():
            like = "%" + query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            rows = db.execute("SELECT c.id, c.title, c.created, c.updated, (SELECT COUNT(*) FROM messages m WHERE m.conv = c.id) AS n "
                              "FROM conversations c WHERE c.title LIKE ? ESCAPE '\\' OR EXISTS "
                              "(SELECT 1 FROM messages m WHERE m.conv = c.id AND m.text LIKE ? ESCAPE '\\') ORDER BY c.updated DESC LIMIT ?",
                              (like, like, limit)).fetchall()
        else:
            rows = db.execute("SELECT c.id, c.title, c.created, c.updated, (SELECT COUNT(*) FROM messages m WHERE m.conv = c.id) AS n "
                              "FROM conversations c ORDER BY c.updated DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get(cid):
    with _db() as db:
        c = db.execute("SELECT id, title, created, updated FROM conversations WHERE id = ?", (cid,)).fetchone()
        if not c:
            return None
        ms = db.execute("SELECT role, text, t, brain FROM messages WHERE conv = ? ORDER BY id", (cid,)).fetchall()
    return {**dict(c), "messages": [dict(m) for m in ms]}


def rename(cid, title):
    title = " ".join(str(title).split())[:120]
    if title:
        with _db() as db:
            db.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, cid))


def delete(cid):
    with _db() as db:
        db.execute("DELETE FROM conversations WHERE id = ?", (cid,))


def delete_all():
    with _db() as db:
        db.execute("DELETE FROM conversations")
    with _db() as db:
        db.execute("VACUUM")                                           # the deleted words leave the file too


def purge(days, now=None):
    """Delete conversations whose last message is older than `days`. Returns how many went."""
    if days <= 0:
        return 0
    with _db() as db:
        n = db.execute("DELETE FROM conversations WHERE updated < ?", ((now or time.time()) - days * 86400,)).rowcount
    return n


def export_md(cid):
    c = get(cid)
    if not c:
        return ""
    out = [f"# {c['title']}", "", time.strftime("%d %B %Y, %H:%M", time.localtime(c["created"])), ""]
    for m in c["messages"]:
        out += [("**You:** " if m["role"] == "user" else "**Jarvis:** ") + m["text"], ""]
    return "\n".join(out)
