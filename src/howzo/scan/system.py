"""System binaries on Unix (/bin, /sbin, /usr/bin, /usr/sbin, /usr/local/bin) via man pages."""
import os
import time

from ..db import upsert
from ..helptext import man_oneliner

# /bin and /sbin are real directories on macOS and hold sbin-only tools
# (ifconfig, route, ping, traceroute); on merged-usr Linux they're symlinks
# and the name-based dedup below keeps things from double-indexing.
SYSTEM_DIRS = ("/usr/bin", "/usr/sbin", "/usr/local/bin", "/bin", "/sbin")


def candidate_dirs():
    """Every PATH dir (user's effective order first, so the recorded path is
    the binary the shell would actually run), plus the standard system dirs
    as a fallback for minimal/cron-like PATHs. Only tools with a man page
    end up indexed, so this stays cheap."""
    dirs = []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        d = d.strip()
        if d and d not in dirs:
            dirs.append(d)
    for d in SYSTEM_DIRS:
        if d not in dirs:
            dirs.append(d)
    return dirs


def scan_system(c):
    names, seen, paths = [], set(), {}
    for d in candidate_dirs():
        if not os.path.isdir(d):
            continue
        for n in os.listdir(d):
            if n not in seen:
                seen.add(n)
                names.append(n)
                paths[n] = d
    print(f"  system: {len(names)} binaries, fetching man pages (slow part)...")
    n = 0
    for name in names:
        oneliner, excerpt = man_oneliner(name)
        if oneliner or excerpt:
            upsert(c, name, "system", "", f"{paths[name]}/{name}", oneliner)
            if excerpt:
                c.execute("UPDATE tools SET help_excerpt=?, help_captured_at=? WHERE name=? AND (help_excerpt='' OR source='system')",
                          (excerpt, time.strftime("%Y-%m-%d"), name))
            n += 1
    print(f"  system: {n} indexed with man text")
