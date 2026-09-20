import json
import os

from howzo.db import upsert
from howzo import scan as scan_pkg
from howzo.scan import brew, npm, pipx, uv, scripts, system, path, npx


def test_scanners_platform_selection(monkeypatch):
    from howzo import config
    monkeypatch.setattr(config, "IS_WINDOWS", False)
    assert scan_pkg.scan_system in scan_pkg.scanners()
    assert scan_pkg.scan_path not in scan_pkg.scanners()
    monkeypatch.setattr(config, "IS_WINDOWS", True)
    assert scan_pkg.scan_path in scan_pkg.scanners()
    assert scan_pkg.scan_system not in scan_pkg.scanners()


def test_brew_scanner(c, monkeypatch):
    monkeypatch.setattr(brew.shutil, "which", lambda n: "/opt/homebrew/bin/brew" if n == "brew" else None)

    def fake_run(cmd, timeout=30):
        if cmd[:3] == ["brew", "list", "--versions"]:
            return "git 2.40.0\nnode 22.0.0\n"
        if cmd[:2] == ["brew", "info"]:
            names = cmd[3:]
            return json.dumps({"formulae": [
                {"name": n, "versions": {"stable": "1.0"},
                 "description": f"{n} desc", "homepage": "https://example.com"}
                for n in names]})
        return ""

    monkeypatch.setattr(brew, "run", fake_run)
    brew.scan_brew(c)
    c.commit()
    row = c.execute("SELECT * FROM tools WHERE name='git'").fetchone()
    assert row["source"] == "brew"
    assert row["oneliner"] == "git desc"
    assert row["version"] == "1.0"


def test_brew_scanner_skipped_when_missing(c, monkeypatch, capsys):
    monkeypatch.setattr(brew.shutil, "which", lambda n: None)
    brew.scan_brew(c)
    assert c.execute("SELECT COUNT(*) FROM tools").fetchone()[0] == 0
    assert "brew" not in capsys.readouterr().out


def test_npm_scanner(c, monkeypatch, tmp_path):
    monkeypatch.setattr(npm.shutil, "which", lambda n: "/usr/bin/npm" if n == "npm" else None)
    bindir = tmp_path / "npmg" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "pi").write_text("#!/bin/sh\n")
    monkeypatch.setattr(npm, "npm_prefix", lambda: str(tmp_path / "npmg"))

    def fake_run(cmd, timeout=30):
        if cmd[:4] == ["npm", "ls", "-g", "--depth=0"]:
            return json.dumps({"dependencies": {"pkg-a": {"version": "1.2.3"}}})
        if cmd[:3] == ["npm", "view", "pkg-a"]:
            return "pkg-a does things\n"
        return ""

    monkeypatch.setattr(npm, "run", fake_run)
    npm.scan_npm(c)
    c.commit()
    row = c.execute("SELECT * FROM tools WHERE name='pkg-a'").fetchone()
    assert row["version"] == "1.2.3"
    assert row["oneliner"] == "pkg-a does things"
    bin_row = c.execute("SELECT * FROM tools WHERE name='pi'").fetchone()
    assert bin_row["oneliner"] == "(npm global binary)"


def test_pipx_scanner(c, monkeypatch):
    monkeypatch.setattr(pipx.shutil, "which", lambda n: "/x/pipx" if n == "pipx" else None)
    payload = {"venvs": {"/home/u/.local/pipx/venvs/crawl4ai": {
        "metadata": {"main_package": {"package": "crawl4ai", "package_version": "0.5.0",
                                      "app_paths": [{"__Path__": "/home/u/.local/bin/crwl"}]}}}}}
    monkeypatch.setattr(pipx, "run", lambda cmd, timeout=30: json.dumps(payload))
    monkeypatch.setattr(pipx, "pypi_oneliner", lambda name: "web crawler")
    pipx.scan_pipx(c)
    c.commit()
    assert c.execute("SELECT COUNT(*) FROM tools WHERE name IN ('crawl4ai','crwl')").fetchone()[0] == 2
    row = c.execute("SELECT * FROM tools WHERE name='crwl'").fetchone()
    assert row["oneliner"] == "(binary of pipx crawl4ai)"
    assert row["path"] == "/home/u/.local/bin/crwl"


def test_uv_scanner(c, monkeypatch):
    monkeypatch.setattr(uv.shutil, "which", lambda n: "/x/uv" if n == "uv" else None)
    monkeypatch.setattr(uv, "run", lambda cmd, timeout=30:
                        "ruff v0.4.0\n  /opt/venvs/ruff/bin/ruff\nhttpie v3.2.2\n  /opt/venvs/httpie/bin/http\n")
    monkeypatch.setattr(uv, "pypi_oneliner", lambda name: f"{name} summary")
    uv.scan_uv(c)
    c.commit()
    row = c.execute("SELECT * FROM tools WHERE name='ruff'").fetchone()
    assert row["version"] == "0.4.0"
    assert row["oneliner"] == "ruff summary"
    assert c.execute("SELECT COUNT(*) FROM tools").fetchone()[0] == 2


def test_scripts_scanner(c, monkeypatch, tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "myscript"
    script.write_text("#!/bin/sh\n# my cool helper for testing\nexit 0\n")
    script.chmod(0o755)
    monkeypatch.setattr(scripts.config, "SCAN_DIRS", [str(bindir)])
    monkeypatch.setattr(scripts, "npm_prefix", lambda: str(tmp_path / "npm"))
    scripts.scan_scripts(c)
    c.commit()
    row = c.execute("SELECT * FROM tools WHERE name='myscript'").fetchone()
    assert row["source"] == "script"
    assert row["oneliner"] == "my cool helper for testing"


def test_system_scanner(c, monkeypatch, tmp_path):
    bdir = tmp_path / "usr" / "bin"
    bdir.mkdir(parents=True)
    (bdir / "lsx").write_text("x")
    (bdir / "grep").write_text("x")
    monkeypatch.setattr(system, "SYSTEM_DIRS", (str(bdir),))
    monkeypatch.setattr(system, "man_oneliner",
                        lambda name: ("print lines matching a pattern", "NAME\n  grep - print lines")
                        if name == "grep" else ("", ""))
    system.scan_system(c)
    c.commit()
    row = c.execute("SELECT * FROM tools WHERE name='grep'").fetchone()
    assert row["oneliner"] == "print lines matching a pattern"
    assert c.execute("SELECT help_excerpt FROM tools WHERE name='grep'").fetchone()[0].startswith("NAME")
    # binary without a man page is skipped
    assert c.execute("SELECT COUNT(*) FROM tools WHERE name='lsx'").fetchone()[0] == 0


def test_system_scanner_walks_path_dirs(c, monkeypatch, tmp_path):
    # tools in custom PATH dirs (e.g. ~/.cargo/bin/cargo) get indexed;
    # standard dirs stay covered even when PATH is minimal; on name clash
    # the PATH-dir binary wins (it's the one the shell would run)
    custom = tmp_path / "cargo-bin"
    custom.mkdir()
    (custom / "cargo").write_text("x")
    (custom / "grep").write_text("x")
    std = tmp_path / "usr-bin"
    std.mkdir()
    (std / "grep").write_text("x")
    monkeypatch.setattr(system, "SYSTEM_DIRS", (str(std),))
    monkeypatch.setenv("PATH", str(custom))
    monkeypatch.setattr(system, "man_oneliner",
                        lambda name: (f"{name} - fake man", f"NAME\n  {name} - fake"))
    system.scan_system(c)
    c.commit()
    assert c.execute("SELECT COUNT(*) FROM tools").fetchone()[0] == 2
    assert c.execute("SELECT path FROM tools WHERE name='cargo'").fetchone()[0] == str(custom / "cargo")
    assert c.execute("SELECT path FROM tools WHERE name='grep'").fetchone()[0] == str(custom / "grep")


def test_candidate_dirs_path_first_then_system(monkeypatch, tmp_path):
    custom = tmp_path / "custom"
    monkeypatch.setattr(system, "SYSTEM_DIRS", ("/nonexistent-a", "/nonexistent-b"))
    monkeypatch.setenv("PATH", str(custom) + ":")
    dirs = system.candidate_dirs()
    assert dirs[0] == str(custom)
    assert "/nonexistent-a" in dirs and "/nonexistent-b" in dirs


def test_system_scanner_keeps_claimed_names(c, monkeypatch, tmp_path):
    # names already indexed by richer scanners (brew/npm/pipx/uv/script)
    # keep their source+version; unclaimed binaries in the same dirs
    # (cask/app tools) still get indexed
    upsert(c, "qpdf", "brew", "12.1.0", "", "manipulate PDF files")
    homebrew = tmp_path / "homebrew-bin"
    homebrew.mkdir()
    (homebrew / "qpdf").write_text("x")
    (homebrew / "ghostty").write_text("x")
    monkeypatch.setattr(system, "SYSTEM_DIRS", ())
    monkeypatch.setenv("PATH", str(homebrew))
    monkeypatch.setattr(system, "man_oneliner",
                        lambda name: (f"{name} - fake man", f"NAME\n  {name} - fake"))
    system.scan_system(c)
    c.commit()
    row = c.execute("SELECT * FROM tools WHERE name='qpdf'").fetchone()
    assert row["source"] == "brew" and row["version"] == "12.1.0"
    assert c.execute("SELECT COUNT(*) FROM tools WHERE name='ghostty'").fetchone()[0] == 1


def test_system_scanner_records_found_dir(c, monkeypatch, tmp_path):
    # sbin-only tool (like macOS /sbin/ifconfig) must be indexed with its real path
    sbindir = tmp_path / "sbin"
    sbindir.mkdir()
    (sbindir / "ifconfig").write_text("x")
    monkeypatch.setattr(system, "SYSTEM_DIRS", (str(tmp_path / "missing"), str(sbindir)))
    monkeypatch.setenv("PATH", "")  # isolate from the real environment
    monkeypatch.setattr(system, "man_oneliner",
                        lambda name: ("configure network interface drivers", "NAME\n  ifconfig - configure")
                        if name == "ifconfig" else ("", ""))
    system.scan_system(c)
    c.commit()
    path = c.execute("SELECT path FROM tools WHERE name='ifconfig'").fetchone()[0]
    assert path == str(sbindir / "ifconfig")


def test_path_scanner_indexes_executables(c, monkeypatch, tmp_path):
    bindir = tmp_path / "bindir"
    bindir.mkdir()
    for name in ("tool1.exe", "tool2.cmd", "notes.txt"):
        (bindir / name).write_text("x")
    npm_dir = tmp_path / "Roaming" / "npm"
    npm_dir.mkdir(parents=True)
    (npm_dir / "npm.cmd").write_text("x")
    monkeypatch.setenv("Path", f"{bindir}{os.pathsep}{npm_dir}")
    path.scan_path(c)
    c.commit()
    names = {r[0] for r in c.execute("SELECT name FROM tools")}
    assert "tool1.exe" in names
    assert "tool2.cmd" in names
    assert "notes.txt" not in names
    assert "npm.cmd" not in names  # npm dir covered by scan_npm


def test_npx_history_scanner(c, monkeypatch, tmp_path):
    hist = tmp_path / ".zsh_history"
    hist.write_text("npx create-next-app@latest myapp\nbunx typescript tsc x\npnpm dlx some-tool\nls\n")
    monkeypatch.setattr(npx.config, "HOME", str(tmp_path))
    monkeypatch.setattr(npx, "run", lambda cmd, timeout=30: "desc for x\n" if "view" in cmd else "")
    upsert(c, "existing", "brew", "1", "", "already installed")
    c.commit()
    npx.scan_npx_history(c)
    c.commit()
    names = {r[0] for r in c.execute("SELECT name FROM tools")}
    assert {"create-next-app", "typescript", "some-tool"} <= names
    row = c.execute("SELECT * FROM tools WHERE name='create-next-app'").fetchone()
    assert row["source"] == "npx"
    # version is intentionally stripped: `npx create-next-app` picks the latest
    assert row["path"] == "npx create-next-app"


def test_npx_history_skips_already_installed(c, monkeypatch, tmp_path):
    hist = tmp_path / ".zsh_history"
    hist.write_text("npx jq input.json\n")
    monkeypatch.setattr(npx.config, "HOME", str(tmp_path))
    monkeypatch.setattr(npx, "run", lambda cmd, timeout=30: "")
    upsert(c, "jq", "brew", "1.7", "", "json processor")
    c.commit()
    npx.scan_npx_history(c)
    c.commit()
    assert c.execute("SELECT COUNT(*) FROM tools").fetchone()[0] == 1
