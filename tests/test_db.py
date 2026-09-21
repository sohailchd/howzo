from howzo.db import db, upsert


def test_creates_schema(c):
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "tools" in tables
    assert "tools_fts" in tables


def test_upsert_insert_and_update(c):
    upsert(c, "git", "brew", "2.40.0", "https://git-scm.com", "control version control")
    upsert(c, "git", "brew", "2.41.0", "https://git-scm.com", "control version control")
    c.commit()
    row = c.execute("SELECT * FROM tools WHERE name='git'").fetchone()
    assert row["version"] == "2.41.0"
    assert c.execute("SELECT COUNT(*) FROM tools").fetchone()[0] == 1


def test_upsert_keeps_oneliner_when_new_empty(c):
    upsert(c, "tool", "brew", "1", "", "real description")
    upsert(c, "tool", "brew", "2", "", "")  # empty oneliner must not clobber
    c.commit()
    row = c.execute("SELECT oneliner FROM tools WHERE name='tool'").fetchone()
    assert row["oneliner"] == "real description"


def test_fts_stays_in_sync(c):
    upsert(c, "jq", "brew", "1.7", "", "commandline json processor")
    c.execute("DELETE FROM tools WHERE name='jq'")
    c.commit()
    hits = c.execute("SELECT COUNT(*) FROM tools_fts WHERE tools_fts MATCH 'json'").fetchone()[0]
    assert hits == 0


def test_platform_column_migration_is_additive_and_idempotent(tmp_path, monkeypatch):
    # a 0.2.2 database has no tools.platform: opening it must add the column
    # without touching the rows, and opening it again must not fail
    import sqlite3
    from howzo.db import SCHEMA, db
    p = tmp_path / "howzo.db"
    monkeypatch.setenv("HOWZO_DB", str(p))
    old_schema = SCHEMA.replace(",\n  platform TEXT", "")
    assert "platform" not in old_schema
    con = sqlite3.connect(str(p))
    con.executescript(old_schema)
    con.execute("INSERT INTO tools(name, source, path, oneliner) "
                "VALUES('cat', 'system', '/bin/cat', 'concatenate files')")
    con.commit()
    con.close()

    c = db()
    cols = [r[1] for r in c.execute("PRAGMA table_info(tools)")]
    assert "platform" in cols
    assert "man_cache" in {r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    row = c.execute("SELECT * FROM tools WHERE name='cat'").fetchone()
    assert row["oneliner"] == "concatenate files"
    assert row["platform"] is None
    c.close()

    c = db()  # idempotent: the column is already there
    assert "platform" in [r[1] for r in c.execute("PRAGMA table_info(tools)")]
    assert c.execute("SELECT COUNT(*) FROM tools").fetchone()[0] == 1
    c.close()


def test_corrupted_db_rebuilds(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOWZO_DB", str(tmp_path / "howzo.db"))
    p = tmp_path / "howzo.db"
    p.write_bytes(b"this is not a sqlite database at all")
    c = db()
    assert "warning: db corrupted" in capsys.readouterr().out
    assert c.execute("SELECT COUNT(*) FROM tools").fetchone()[0] == 0
    c.close()


def test_locked_db_is_not_deleted(tmp_path, monkeypatch, capsys):
    # regression: 'database is locked' is an OperationalError (a DatabaseError
    # subclass). It must make the caller wait, never delete the user's index.
    import sqlite3
    import threading
    import time
    p = tmp_path / "howzo.db"
    monkeypatch.setenv("HOWZO_DB", str(p))
    first = db()
    first.execute("INSERT INTO tools(name, source) VALUES('x', 'system')")
    first.commit()
    holder = sqlite3.connect(str(p), check_same_thread=False)
    holder.execute("BEGIN EXCLUSIVE")

    def release():
        time.sleep(1.0)
        holder.close()

    threading.Thread(target=release).start()
    second = db()  # waits out the lock (connect timeout) instead of wiping
    assert p.exists()
    assert second.execute("SELECT COUNT(*) FROM tools").fetchone()[0] == 1
    assert "corrupted" not in capsys.readouterr().out
    second.close()
    first.close()
