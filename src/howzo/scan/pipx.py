"""Tools installed via pipx (plus the binaries they provide)."""
import json
import os
import shutil

from ..db import upsert
from ..proc import run
from .common import pypi_oneliner


def scan_pipx(c):
    if not shutil.which("pipx"):
        return
    out = run(["pipx", "list", "--json"], timeout=30)
    try:
        data = json.loads(out)
    except Exception:
        return
    n = 0
    for venv, v in (data.get("venvs") or {}).items():
        main = (v.get("metadata") or {}).get("main_package") or {}
        name = main.get("package") or venv
        ver = main.get("package_version", "")
        upsert(c, name, "pipx", ver, "", pypi_oneliner(name) or f"(pipx) {name}")
        # also index the binaries this package provides (crwl -> crawl4ai)
        for ap in main.get("app_paths") or []:
            base = os.path.basename(ap.get("__Path__", "")) if isinstance(ap, dict) else os.path.basename(str(ap))
            if base and base != name:
                upsert(c, base, "pipx", ver, ap.get("__Path__", ""), f"(binary of pipx {name})")
        n += 1
    print(f"  pipx: {n} packages")
