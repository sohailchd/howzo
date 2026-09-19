"""Global npm packages (plus the binaries they install)."""
import json
import os
import shutil

from ..db import upsert
from ..proc import run
from .common import npm_prefix


def scan_npm(c):
    if not shutil.which("npm"):
        return
    out = run(["npm", "ls", "-g", "--depth=0", "--json"], timeout=60)
    try:
        deps = json.loads(out).get("dependencies", {})
    except Exception:
        return
    print(f"  npm: {len(deps)} global packages")
    for name, info in deps.items():
        desc = run(["npm", "view", name, "description"], timeout=15).strip()
        upsert(c, name, "npm", info.get("version", ""), "", desc)
    # binaries npm installs (link name != package name, e.g. pi)
    bindir = os.path.join(npm_prefix(), "bin")
    if os.path.isdir(bindir):
        for entry in os.listdir(bindir):
            if entry in deps:
                continue
            upsert(c, entry, "npm", "", os.path.join(bindir, entry), "(npm global binary)")
