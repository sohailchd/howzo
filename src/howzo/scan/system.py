"""System binaries on Unix: every PATH dir + /bin, /sbin, /usr/bin, /usr/sbin,
/usr/local/bin, via man pages.

A full scan sees ~1,500 binaries and `man` is one subprocess each — the slow
part of the whole scan. Two things keep it bounded:

* `man_cache` remembers the (path, mtime) a name was read from, so nothing
  changed since the last scan is never re-forked. Negative results (no man
  page) are cached too.
* the still-uncached names are fetched on a small thread pool. All sqlite
  writes stay on the calling thread — a connection is not thread-safe.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor

from ..db import upsert
from ..helptext import man_oneliner

# /bin and /sbin are real directories on macOS and hold sbin-only tools
# (ifconfig, route, ping, traceroute); on merged-usr Linux they're symlinks
# and the name-based dedup below keeps things from double-indexing.
SYSTEM_DIRS = ("/usr/bin", "/usr/sbin", "/usr/local/bin", "/bin", "/sbin")

# sources whose rows carry richer metadata (versions, package names);
# the man walk must not relabel those binaries as plain system tools
CLAIMED_SOURCES = ("brew", "npm", "pipx", "uv", "script")

# enough concurrency to hide man's fork/exec latency without thrashing the box
MAN_WORKERS = 8


def candidate_dirs():
    """Every PATH dir (user's effective order first, so the recorded path is
    the binary the shell would actually run), minus the active venv's bin
    (the inventory describes the machine, not this project), plus the
    standard system dirs as a fallback for minimal/cron-like PATHs. Only
    tools with a man page end up indexed, so this stays cheap."""
    dirs = []
    venv = os.environ.get("VIRTUAL_ENV")
    venv_bin = os.path.join(venv.rstrip("/"), "bin") if venv else ""
    for d in os.environ.get("PATH", "").split(os.pathsep):
        d = d.strip()
        if d and d not in dirs and d != venv_bin:
            dirs.append(d)
    for d in SYSTEM_DIRS:
        if d not in dirs:
            dirs.append(d)
    return dirs


def _mtime(path):
    """Modification time of the binary, or None when it cannot be stat'ed."""
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


def cached_man(cache, name, path, mtime):
    """(oneliner, excerpt) from the man cache, or None when it is stale."""
    row = cache.get(name)
    if row is None or mtime is None or row["mtime"] is None:
        return None
    if row["path"] == path and abs(row["mtime"] - mtime) < 1e-6:
        return (row["oneliner"] or "", row["excerpt"] or "")
    return None


def store_man(c, name, path, mtime, oneliner, excerpt):
    """Remember what `man name` said for this binary revision."""
    c.execute("INSERT INTO man_cache(name, path, mtime, oneliner, excerpt, captured_at) "
              "VALUES(?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET path=excluded.path, "
              "mtime=excluded.mtime, oneliner=excluded.oneliner, "
              "excerpt=excluded.excerpt, captured_at=excluded.captured_at",
              (name, path, -1.0 if mtime is None else mtime, oneliner or "",
               excerpt or "", time.strftime("%Y-%m-%d")))


def unchanged(c, name, path, oneliner):
    """True when the row already holds this exact path and oneliner, so the
    upsert (and its FTS update trigger) can be skipped."""
    row = c.execute("SELECT path, oneliner FROM tools WHERE name=?", (name,)).fetchone()
    return (row is not None and (row["path"] or "") == (path or "")
            and (row["oneliner"] or "") == (oneliner or ""))


def scan_system(c):
    # names already indexed by the richer scanners keep their rows
    claimed = {r[0] for r in c.execute(
        "SELECT name FROM tools WHERE source IN (%s)" % ",".join("?" * len(CLAIMED_SOURCES)),
        CLAIMED_SOURCES)}
    names, seen, paths = [], set(), {}
    for d in candidate_dirs():
        if not os.path.isdir(d):
            continue
        for n in os.listdir(d):
            if n in seen or n in claimed:
                continue
            # skip non-executables (man pages for them are noise); on Unix
            # X_OK is the executable bit, which is what we actually need
            if not os.access(os.path.join(d, n), os.X_OK):
                continue
            seen.add(n)
            names.append(n)
            paths[n] = d
    print(f"  system: {len(names)} binaries, fetching man pages (slow part)...")
    cache = {r["name"]: r for r in c.execute("SELECT * FROM man_cache")}
    results, pending = {}, []
    for name in names:
        path = "%s/%s" % (paths[name], name)
        mtime = _mtime(path)
        hit = cached_man(cache, name, path, mtime)
        if hit is not None:
            results[name] = hit
        else:
            pending.append((name, path, mtime))
    if pending:
        # man subprocesses in parallel; every sqlite write below stays on
        # this thread, because a connection is not thread-safe
        with ThreadPoolExecutor(max_workers=MAN_WORKERS) as pool:
            fetched = list(pool.map(lambda item: man_oneliner(item[0]), pending))
        for (name, path, mtime), (oneliner, excerpt) in zip(pending, fetched):
            results[name] = (oneliner, excerpt)
            store_man(c, name, path, mtime, oneliner, excerpt)
    print(f"  system: {len(names) - len(pending)} man pages from cache, "
          f"{len(pending)} fetched")
    n = 0
    for name in names:
        oneliner, excerpt = results[name]
        if not (oneliner or excerpt):
            continue
        path = "%s/%s" % (paths[name], name)
        if not unchanged(c, name, path, oneliner):
            upsert(c, name, "system", "", path, oneliner)
            if excerpt:
                c.execute("UPDATE tools SET help_excerpt=?, help_captured_at=? WHERE name=? AND (help_excerpt='' OR source='system')",
                          (excerpt, time.strftime("%Y-%m-%d"), name))
            n += 1
    print(f"  system: {n} rows written with man text")
