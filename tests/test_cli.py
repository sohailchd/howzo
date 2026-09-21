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


def test_scan_system_excerpt_refreshed_not_stale(c, monkeypatch, capsys):
    # keep-restore must not clobber a fresh man-derived system excerpt
    # with the stale pre-rescan value (old artifacts surviving rescans)
    upsert(c, "ifconfig", "system", "", "/sbin/ifconfig", "old oneliner")
    c.execute("UPDATE tools SET help_excerpt='N\x08NA\x08AM\x08ME\x08E stale dirty excerpt', "
              "when_to_use='for netconfig' WHERE name='ifconfig'")
    c.commit()

    def fake_system(conn):
        upsert(conn, "ifconfig", "system", "", "/sbin/ifconfig", "configure network interface parameters")
        conn.execute("UPDATE tools SET help_excerpt='NAME\n  ifconfig - configure network' WHERE name='ifconfig'")

    monkeypatch.setattr(commands, "scanners", lambda: [fake_system])
    assert commands.cmd_scan([]) == 0
    capsys.readouterr()
    row = c.execute("SELECT * FROM tools WHERE name='ifconfig'").fetchone()
    assert row["help_excerpt"].startswith("NAME")
    assert "\x08" not in row["help_excerpt"]
    assert row["when_to_use"] == "for netconfig"


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


def test_scan_applies_hints_only_to_empty(c, monkeypatch, capsys):
    from howzo import hints
    upsert(c, "ifconfig", "system", "", "/sbin/ifconfig", "configure network interface parameters")
    upsert(c, "mytool", "custom", "", "", "a custom tool")
    c.execute("UPDATE tools SET when_to_use='user says so' WHERE name='mytool'")
    c.commit()

    def fake(conn):
        upsert(conn, "ifconfig", "system", "", "/sbin/ifconfig", "configure network interface parameters")

    monkeypatch.setattr(commands, "scanners", lambda: [fake])
    assert commands.cmd_scan([]) == 0
    capsys.readouterr()
    got = c.execute("SELECT when_to_use FROM tools WHERE name='ifconfig'").fetchone()[0]
    assert got == hints.HINTS["ifconfig"]
    assert c.execute("SELECT when_to_use FROM tools WHERE name='mytool'").fetchone()[0] == "user says so"


def test_scan_hints_ipconfig_only_on_windows(c, monkeypatch, capsys):
    from howzo import config, hints
    upsert(c, "ipconfig", "system", "", "/sbin/ipconfig", "view and control IP configuration state")
    c.commit()

    def fake(conn):
        upsert(conn, "ipconfig", "system", "", "/sbin/ipconfig", "view and control IP configuration state")

    monkeypatch.setattr(commands, "scanners", lambda: [fake])
    monkeypatch.setattr(config, "IS_WINDOWS", False)
    assert commands.cmd_scan([]) == 0
    capsys.readouterr()
    assert c.execute("SELECT when_to_use FROM tools WHERE name='ipconfig'").fetchone()[0] == ""

    c.execute("UPDATE tools SET when_to_use='' WHERE name='ipconfig'")
    c.commit()
    monkeypatch.setattr(config, "IS_WINDOWS", True)
    assert commands.cmd_scan([]) == 0
    capsys.readouterr()
    assert c.execute("SELECT when_to_use FROM tools WHERE name='ipconfig'").fetchone()[0] == hints.HINTS["ipconfig"]
