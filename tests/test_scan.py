import json
import os
import time

from howzo.db import upsert
from howzo import scan as scan_pkg
from howzo.scan import brew, npm, pipx, uv, scripts, system, path, npx


def _fake_bin_dir(tmp_path, *names):
    """A dir of executable fake binaries (os.access(..., X_OK) must pass)."""
    bdir = tmp_path / "bin"
    bdir.mkdir(exist_ok=True)
    for n in names:
        (bdir / n).write_text("x")
        os.chmod(bdir / n, 0o755)
    return bdir


def _counting_man(calls, oneliner=None, excerpt=None):
    def man(name):
        calls.append(name)
        return (oneliner if oneliner is not None else f"{name} one-liner",
                excerpt if excerpt is not None else f"NAME\n  {name} - fake")
    return man


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
    for n in ("lsx", "grep"):  # fake binaries must look real: executable
        (bdir / n).write_text("x")
        os.chmod(bdir / n, 0o755)
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
    for n in ("cargo", "grep"):  # fake binaries must look real: executable
        (custom / n).write_text("x")
        os.chmod(custom / n, 0o755)
    std = tmp_path / "usr-bin"
    std.mkdir()
    (std / "grep").write_text("x")
    os.chmod(std / "grep", 0o755)
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
    for n in ("qpdf", "ghostty"):  # fake binaries must look real: executable
        (homebrew / n).write_text("x")
        os.chmod(homebrew / n, 0o755)
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
    os.chmod(sbindir / "ifconfig", 0o755)
    monkeypatch.setattr(system, "SYSTEM_DIRS", (str(tmp_path / "missing"), str(sbindir)))
    monkeypatch.setenv("PATH", "")  # isolate from the real environment
    monkeypatch.setattr(system, "man_oneliner",
                        lambda name: ("configure network interface drivers", "NAME\n  ifconfig - configure")
                        if name == "ifconfig" else ("", ""))
    system.scan_system(c)
    c.commit()
    path = c.execute("SELECT path FROM tools WHERE name='ifconfig'").fetchone()[0]
    assert path == str(sbindir / "ifconfig")


def test_system_scanner_man_cache_skips_unchanged_binaries(c, monkeypatch, tmp_path):
    # man is a subprocess per binary (~1,500 of them): the second scan must
    # come from man_cache instead of re-forking man for everything
    bdir = _fake_bin_dir(tmp_path, "alpha", "beta")
    monkeypatch.setattr(system, "SYSTEM_DIRS", (str(bdir),))
    monkeypatch.setenv("PATH", "")
    calls = []
    monkeypatch.setattr(system, "man_oneliner", _counting_man(calls))
    system.scan_system(c)
    c.commit()
    assert sorted(calls) == ["alpha", "beta"]
    assert c.execute("SELECT COUNT(*) FROM man_cache").fetchone()[0] == 2

    calls.clear()
    system.scan_system(c)
    c.commit()
    assert calls == []  # every man page came from the cache
    assert c.execute("SELECT COUNT(*) FROM tools WHERE source='system'").fetchone()[0] == 2


def test_system_scanner_refetches_when_the_binary_changes(c, monkeypatch, tmp_path):
    bdir = _fake_bin_dir(tmp_path, "alpha")
    monkeypatch.setattr(system, "SYSTEM_DIRS", (str(bdir),))
    monkeypatch.setenv("PATH", "")
    calls = []
    monkeypatch.setattr(system, "man_oneliner", _counting_man(calls))
    system.scan_system(c)
    c.commit()
    calls.clear()
    os.utime(bdir / "alpha", (time.time() + 5, time.time() + 5))
    system.scan_system(c)
    c.commit()
    assert calls == ["alpha"]  # mtime moved: the cache entry is stale


def test_system_scanner_caches_missing_man_pages(c, monkeypatch, tmp_path):
    # a name with no man page must not be re-forked on every rescan
    bdir = _fake_bin_dir(tmp_path, "ghost")
    monkeypatch.setattr(system, "SYSTEM_DIRS", (str(bdir),))
    monkeypatch.setenv("PATH", "")
    calls = []
    monkeypatch.setattr(system, "man_oneliner", _counting_man(calls, oneliner="", excerpt=""))
    system.scan_system(c)
    c.commit()
    assert calls == ["ghost"]
    row = c.execute("SELECT * FROM man_cache WHERE name='ghost'").fetchone()
    assert row is not None and row["oneliner"] == "" and row["excerpt"] == ""

    calls.clear()
    system.scan_system(c)
    c.commit()
    assert calls == []
    assert c.execute("SELECT COUNT(*) FROM tools").fetchone()[0] == 0


def test_system_scanner_skips_unchanged_upserts(c, monkeypatch, tmp_path):
    # an identical path+oneliner row is left exactly as it is: no write, so
    # no FTS update trigger churn on a rescan
    bdir = _fake_bin_dir(tmp_path, "alpha")
    monkeypatch.setattr(system, "SYSTEM_DIRS", (str(bdir),))
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(system, "man_oneliner",
                        lambda name: ("alpha one-liner", "NAME\n  alpha - fake"))
    upsert(c, "alpha", "system", "", str(bdir / "alpha"), "alpha one-liner")
    c.execute("UPDATE tools SET scanned_at='1999-01-01', help_excerpt='kept excerpt' "
              "WHERE name='alpha'")
    c.commit()
    system.scan_system(c)
    c.commit()
    row = c.execute("SELECT * FROM tools WHERE name='alpha'").fetchone()
    assert row["scanned_at"] == "1999-01-01"     # untouched: no upsert ran
    assert row["help_excerpt"] == "kept excerpt"
    assert row["oneliner"] == "alpha one-liner"


def test_system_scanner_rewrites_a_changed_row(c, monkeypatch, tmp_path):
    # the mirror image: a different oneliner must be written
    bdir = _fake_bin_dir(tmp_path, "alpha")
    monkeypatch.setattr(system, "SYSTEM_DIRS", (str(bdir),))
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(system, "man_oneliner",
                        lambda name: ("brand new one-liner", "NAME\n  alpha - fake"))
    upsert(c, "alpha", "system", "", str(bdir / "alpha"), "stale one-liner")
    c.execute("UPDATE tools SET scanned_at='1999-01-01' WHERE name='alpha'")
    c.commit()
    system.scan_system(c)
    c.commit()
    row = c.execute("SELECT * FROM tools WHERE name='alpha'").fetchone()
    assert row["oneliner"] == "brand new one-liner"
    assert row["scanned_at"] != "1999-01-01"


def test_man_cache_survives_the_tools_wipe(c, monkeypatch, tmp_path):
    # cmd_scan empties tools before scanning; the man cache must not be part
    # of that wipe or a rescan would re-fork every man page
    seed_man = _fake_bin_dir(tmp_path, "alpha")
    monkeypatch.setattr(system, "SYSTEM_DIRS", (str(seed_man),))
    monkeypatch.setenv("PATH", "")
    calls = []
    monkeypatch.setattr(system, "man_oneliner", _counting_man(calls))
    system.scan_system(c)
    c.commit()
    c.execute("DELETE FROM tools")
    c.commit()
    calls.clear()
    system.scan_system(c)
    c.commit()
    assert calls == []
    assert c.execute("SELECT oneliner FROM tools WHERE name='alpha'").fetchone()[0] \
        == "alpha one-liner"


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
