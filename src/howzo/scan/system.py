"""System binaries on Unix (/usr/bin, /usr/sbin, /usr/local/bin) via man pages."""
import os
import time

from ..db import upsert
from ..helptext import man_oneliner

SYSTEM_DIRS = ("/usr/bin", "/usr/sbin", "/usr/local/bin")


def scan_system(c):
    names, seen = [], set()
    for d in SYSTEM_DIRS:
        if not os.path.isdir(d):
            continue
        for n in os.listdir(d):
            if n not in seen:
                seen.add(n)
                names.append(n)
    print(f"  system: {len(names)} binaries, fetching man pages (slow part)...")
    n = 0
    for name in names:
        oneliner, excerpt = man_oneliner(name)
        if oneliner or excerpt:
            upsert(c, name, "system", "", f"/usr/bin/{name}", oneliner)
            if excerpt:
                c.execute("UPDATE tools SET help_excerpt=?, help_captured_at=? WHERE name=? AND (help_excerpt='' OR source='system')",
                          (excerpt, time.strftime("%Y-%m-%d"), name))
            n += 1
    print(f"  system: {n} indexed with man text")
