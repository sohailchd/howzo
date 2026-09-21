"""SQLite + FTS5 inventory store."""
import os
import sqlite3
import time

from . import config

# How long to wait out a concurrent howzo process (scan in one terminal,
# ask in another) before giving up with 'database is locked'.
BUSY_TIMEOUT = 5.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS tools (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  source TEXT,
  version TEXT,
  path TEXT,
  oneliner TEXT DEFAULT '',
  when_to_use TEXT DEFAULT '',
  help_excerpt TEXT DEFAULT '',
  help_captured_at TEXT,
  scanned_at TEXT
);
CREATE TABLE IF NOT EXISTS vocab (
  word TEXT PRIMARY KEY,
  df INTEGER DEFAULT 1
);
CREATE VIRTUAL TABLE IF NOT EXISTS tools_fts USING fts5(
  name, oneliner, when_to_use, help_excerpt, content='tools', content_rowid='id',
  tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS tools_ai AFTER INSERT ON tools BEGIN
  INSERT INTO tools_fts(rowid, name, oneliner, when_to_use, help_excerpt)
  VALUES (new.id, new.name, new.oneliner, new.when_to_use, new.help_excerpt);
END;
CREATE TRIGGER IF NOT EXISTS tools_ad AFTER DELETE ON tools BEGIN
  INSERT INTO tools_fts(tools_fts, rowid, name, oneliner, when_to_use, help_excerpt)
  VALUES ('delete', old.id, old.name, old.oneliner, old.when_to_use, old.help_excerpt);
END;
CREATE TRIGGER IF NOT EXISTS tools_au AFTER UPDATE ON tools BEGIN
  INSERT INTO tools_fts(tools_fts, rowid, name, oneliner, when_to_use, help_excerpt)
  VALUES ('delete', old.id, old.name, old.oneliner, old.when_to_use, old.help_excerpt);
  INSERT INTO tools_fts(rowid, name, oneliner, when_to_use, help_excerpt)
  VALUES (new.id, new.name, new.oneliner, new.when_to_use, new.help_excerpt);
END;
"""


def db(path=None):
    """Open (creating if needed) the inventory DB at path (default: config.db_path())."""
    p = path or config.db_path()
    d = os.path.dirname(p) or "."
    os.makedirs(d, exist_ok=True)
    try:
        # timeout: wait out a concurrent howzo process (scan in one
        # terminal, ask in another) instead of erroring immediately.
        # connect(timeout=...) is used rather than PRAGMA busy_timeout
        # because executescript does not honor the pragma.
        c = sqlite3.connect(p, timeout=BUSY_TIMEOUT)
        c.row_factory = sqlite3.Row
        c.executescript(SCHEMA)
        # vocab is a derived cache: if it predates the df column, drop it to
        # force a rebuild (schema changes never migrate cache tables)
        cols = [r[1] for r in c.execute("PRAGMA table_info(vocab)")]
        if cols and "df" not in cols:
            c.execute("DROP TABLE vocab")
        c.execute("SELECT count(*) FROM tools")  # probe
        return c
    except sqlite3.DatabaseError as e:
        msg = str(e).lower()
        # "database is locked" is an OperationalError (a DatabaseError
        # subclass) — waiting on it is normal, and deleting the user's index
        # because another howzo process is writing is catastrophic. Only a
        # genuinely unreadable file gets rebuilt.
        if "not a database" not in msg and "malformed" not in msg:
            raise
        print(f"  warning: db corrupted, rebuilding ({p})")
        for f in os.listdir(d):
            if f.startswith("howzo.db"):
                os.remove(os.path.join(d, f))
        c = sqlite3.connect(p, timeout=BUSY_TIMEOUT)
        c.row_factory = sqlite3.Row
        c.executescript(SCHEMA)
        return c


def upsert(c, name, source, version, path, oneliner):
    """Insert a tool row, or update version/path on conflict.

    An empty new oneliner never clobbers an existing description.
    """
    c.execute("INSERT INTO tools(name, source, version, path, oneliner, scanned_at) VALUES(?,?,?,?,?,?) "
              "ON CONFLICT(name) DO UPDATE SET source=excluded.source, version=excluded.version, "
              "path=excluded.path, oneliner=CASE WHEN excluded.oneliner != '' THEN excluded.oneliner ELSE tools.oneliner END, "
              "scanned_at=excluded.scanned_at",
              (name, source, version, path, oneliner, time.strftime("%Y-%m-%d")))
