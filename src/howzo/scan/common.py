"""Helpers shared by the scanners."""
import json
import os
import re
import urllib.request

from .. import config
from ..proc import run


def npm_prefix():
    return run(["npm", "prefix", "-g"]).strip() or os.path.join(config.HOME, ".npm-global")


def pypi_oneliner(name):
    """Short description of a PyPI package ('' on any failure)."""
    try:
        with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json", timeout=8) as r:
            info = json.loads(r.read().decode())
            return (info.get("info", {}).get("summary") or "").strip()
    except Exception:
        return ""


def header_oneliner(path):
    """First meaningful comment line of a script (a natural one-liner)."""
    try:
        with open(path, "r", errors="ignore") as fh:
            for i, line in enumerate(fh):
                if i > 30:
                    break
                s = line.strip()
                if s.startswith("#!") or s in ("#", ""):
                    continue
                m = re.match(r"^#\s*(.{12,160})$", s)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return ""


def is_text_file(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(2) == b"#!"
    except Exception:
        return False
