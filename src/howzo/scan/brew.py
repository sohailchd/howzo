"""Homebrew formulae (macOS and Linuxbrew)."""
import json
import shutil

from ..db import upsert
from ..proc import run


def scan_brew(c):
    if not shutil.which("brew"):
        return
    out = run(["brew", "list", "--versions"], timeout=60)
    names = []
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0] and not parts[0].startswith("("):
            names.append(parts[0])
    print(f"  brew: {len(names)} formulae, fetching descriptions...")

    def ingest(out):
        try:
            data = json.loads(out)
        except Exception:
            return False
        for f in data.get("formulae", []):
            ver = (f.get("versions") or {}).get("version") or (f.get("versions") or {}).get("stable", "")
            upsert(c, f["name"], "brew", str(ver), f.get("homepage", ""), f.get("description", ""))
        return True

    for i in range(0, len(names), 40):
        chunk = names[i:i+40]
        if not ingest(run(["brew", "info", "--json=v2", *chunk], timeout=120)):
            # chunk poisoned (e.g. untrusted tap) -> per-name, tolerate failures
            for n in chunk:
                if "/" in n:
                    continue
                ingest(run(["brew", "info", "--json=v2", n], timeout=30))
