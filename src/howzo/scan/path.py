"""Windows: executables found on PATH (System32, Program Files, node, cargo, ...)."""
import os

from ..db import upsert

WINDOWS_EXTS = (".exe", ".cmd", ".bat", ".ps1")


def scan_path(c):
    path_env = os.environ.get("Path") or os.environ.get("PATH") or ""
    names, seen = [], set()
    for d in path_env.split(os.pathsep):
        if not d:
            continue
        # npm's global bin dir is already covered with versions/descriptions by scan_npm
        if os.path.basename(d.rstrip("\\/")).lower() == "npm":
            continue
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for e in entries:
            if e.lower().endswith(WINDOWS_EXTS) and e not in seen:
                seen.add(e)
                names.append((e, os.path.join(d, e)))
    print(f"  path: {len(names)} executables")
    for name, p in names:
        upsert(c, name, "path", "", p, "")
