"""Tools installed via `uv tool`."""
import re
import shutil

from ..db import upsert
from ..proc import run
from .common import pypi_oneliner


def scan_uv(c):
    if not shutil.which("uv"):
        return
    out = run(["uv", "tool", "list"], timeout=30)
    n = 0
    for line in out.splitlines():
        m = re.match(r"^(\S+) v?(\S+)\s*$", line.strip())
        if m and not line.strip().startswith("-"):
            name = m.group(1)
            upsert(c, name, "uv", m.group(2), "", pypi_oneliner(name) or f"(uv) {name}")
            n += 1
    print(f"  uv: {n} tools")
