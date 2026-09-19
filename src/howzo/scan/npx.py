"""On-demand npx/bunx/dlx packages mined from shell history."""
import os
import re

from .. import config
from ..db import upsert
from ..proc import run

NPX_RE = re.compile(r"\b(npx|bunx|pnpm dlx)\s+(@?[a-z0-9][a-z0-9-]*(?:/@[a-z0-9-]+)?)(?:@[a-z0-9.]+)?")


def history_files():
    cands = [os.path.join(config.HOME, ".zsh_history"),
             os.path.join(config.HOME, ".bash_history")]
    appdata = os.environ.get("APPDATA")
    if appdata:
        cands.append(os.path.join(appdata, "Microsoft", "Windows", "PowerShell",
                                  "PSReadLine", "ConsoleHost_history.txt"))
    return [h for h in cands if os.path.exists(h)]


def scan_npx_history(c):
    """Index npx/bunx/dlx packages actually used (from shell history)."""
    hist = next(iter(history_files()), None)
    if not hist:
        return
    pkgs = set()
    try:
        with open(hist, errors="ignore") as fh:
            for line in fh:
                for m in NPX_RE.finditer(line):
                    pkgs.add(m.group(2))
    except Exception:
        return
    known = {r["name"] for r in c.execute("SELECT name FROM tools")}
    n = 0
    for pkg in sorted(pkgs):
        base = pkg.split("/")[-1]
        if base in known:
            continue  # already covered by a real install
        desc = run(["npm", "view", pkg, "description"], timeout=15).strip()
        upsert(c, base, "npx", "", f"npx {pkg}", desc or f"(npx {pkg} - used from shell history)")
        n += 1
    print(f"  npx history: {n} on-demand packages (from {os.path.basename(hist)})")
