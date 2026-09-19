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


def test_corrupted_db_rebuilds(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOWZO_DB", str(tmp_path))
    p = tmp_path / "howzo.db"
    p.write_bytes(b"this is not a sqlite database at all")
    c = db()
    assert "warning: db corrupted" in capsys.readouterr().out
    assert c.execute("SELECT COUNT(*) FROM tools").fetchone()[0] == 0
    c.close()
