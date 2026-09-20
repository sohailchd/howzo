import pytest

from howzo import commands
from howzo.db import db, upsert


def _seed(c):
    upsert(c, "pdfq", "pipx", "1.0", "", "rotate and convert pdf files")
    upsert(c, "skill", "brew", "", "", "manage skills")
    upsert(c, "portcheck", "brew", "", "", "check open ports")
    c.commit()


def test_ask_finds_tool(c, capsys):
    _seed(c)
    rc = commands.cmd_ask(["how do I rotate a pdf"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "pdfq" in out
    assert "rotate and convert pdf files" in out


def test_ask_kill_does_not_match_skill(c, capsys):
    _seed(c)
    rc = commands.cmd_ask(["kill a process"])
    out = capsys.readouterr().out
    assert "skill" not in out


def test_ask_port_does_not_match_report(c, capsys):
    upsert(c, "report", "brew", "", "", "build reports")
    upsert(c, "portcheck", "brew", "", "", "check open ports")
    c.commit()
    commands.cmd_ask(["check the port"])
    out = capsys.readouterr().out
    assert "portcheck" in out
    assert "report" not in out


def test_ask_no_match(c, capsys):
    rc = commands.cmd_ask(["quantum flux capacitor"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "no match" in out


def test_ask_empty_query(c, capsys):
    rc = commands.cmd_ask([])
    assert rc == 1
    assert "usage" in capsys.readouterr().out


def test_ask_exact_name_shortcut(c, capsys):
    _seed(c)
    commands.cmd_ask(["pdfq"])
    out = capsys.readouterr().out
    assert out.startswith("pdfq")


def test_whatis(c, capsys):
    _seed(c)
    rc = commands.cmd_whatis(["pdfq"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "rotate and convert pdf files" in out


def test_whatis_unknown(c, capsys):
    rc = commands.cmd_whatis(["nosuchtool"])
    assert rc == 0
    assert "unknown tool: nosuchtool" in capsys.readouterr().out


def test_add(c, capsys):
    rc = commands.cmd_add(["internal-sync", "syncs the staging database"])
    assert rc == 0
    row = c.execute("SELECT * FROM tools WHERE name='internal-sync'").fetchone()
    assert row is not None
    assert row["source"] == "custom"
    assert row["oneliner"] == "syncs the staging database"


def test_add_requires_desc(c, capsys):
    assert commands.cmd_add(["onlyname"]) == 1


def test_list(c, capsys):
    _seed(c)
    rc = commands.cmd_list([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "3 tools" in out
    commands.cmd_list(["--source", "pipx"])
    out = capsys.readouterr().out
    assert "pdfq" in out
    assert "skill" not in out


def test_deep_not_in_inventory(c, capsys):
    rc = commands.cmd_deep(["nosuchtool"])
    assert rc == 1
    assert "not in inventory" in capsys.readouterr().out


def test_scan_preserves_custom_rows_and_help(c, monkeypatch, capsys):
    upsert(c, "mytool", "custom", "", "", "a custom tool")
    upsert(c, "othertool", "brew", "1", "", "brewed tool")
    c.execute("UPDATE tools SET help_excerpt='flag --fast\nusage: othertool' WHERE name='othertool'")
    c.commit()
    # fake scanner that still sees the brew tool (real scanners re-create their rows
    # after cmd_scan wipes the table; the keep-restore only UPDATEs existing rows)
    def fake_brew(conn):
        upsert(conn, "othertool", "brew", "1", "", "brewed tool")
    monkeypatch.setattr(commands, "scanners", lambda: [fake_brew])
    rc = commands.cmd_scan([])
    assert rc == 0
    assert "inventory: 2 tools" in capsys.readouterr().out
    row = c.execute("SELECT * FROM tools WHERE name='mytool'").fetchone()
    assert row["source"] == "custom"
    assert row["oneliner"] == "a custom tool"
    kept = c.execute("SELECT help_excerpt FROM tools WHERE name='othertool'").fetchone()[0]
    assert kept == "flag --fast\nusage: othertool"


class TestMainDispatch:
    def test_no_args_prints_usage(self, capsys):
        from howzo.cli import main
        assert main([]) == 1
        assert "Commands:" in capsys.readouterr().out

    def test_db_command(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("HOWZO_DB", str(tmp_path))
        from howzo.cli import main
        assert main(["db"]) == 0
        assert str(tmp_path) in capsys.readouterr().out

    def test_implicit_ask(self, c, capsys):
        _seed(c)
        from howzo.cli import main
        assert main(["rotate", "a", "pdf"]) == 0
        assert "pdfq" in capsys.readouterr().out

    def test_python_m_entry(self, c, capsys):
        from howzo.cli import main
        _seed(c)
        assert main(["ask", "rotate pdf"]) == 0

    def test_version_flag(self, capsys):
        from howzo import __version__
        from howzo.cli import main
        assert main(["--version"]) == 0
        assert capsys.readouterr().out.strip() == f"howzo {__version__}"

    def test_help_flag(self, capsys):
        from howzo.cli import main
        assert main(["--help"]) == 0
        assert "Commands:" in capsys.readouterr().out
