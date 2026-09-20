"""User scripts in ~/bin and ~/.local/bin."""
import os

from .. import config
from ..db import upsert
from .common import header_oneliner, is_text_file, npm_prefix


def scan_scripts(c):
    npm_root = npm_prefix()
    pipx_root = os.path.join(config.HOME, ".local", "pipx", "venvs")
    n = 0
    seen = set()
    for d in config.SCAN_DIRS:
        if not os.path.isdir(d):
            continue
        for entry in sorted(os.listdir(d)):
            p = os.path.join(d, entry)
            if entry.endswith((".bak",)) or ".bak-" in entry:
                continue
            if os.path.islink(p):
                tgt = os.path.realpath(p)
                # skip links whose target is already covered by another source
                if tgt.startswith(pipx_root) or tgt.startswith(npm_root):
                    continue
                src = "local"
                oneliner = header_oneliner(tgt) if is_text_file(tgt) else ""
                path = tgt
            elif os.path.isfile(p) and os.access(p, os.X_OK):
                if is_text_file(p):
                    src, oneliner, path = "script", header_oneliner(p), p
                else:
                    src, oneliner, path = "local", "", p
            else:
                continue
            if path in seen:
                continue
            seen.add(path)
            upsert(c, entry, src, "", path, oneliner)
            n += 1
    def short(p):
        p = os.path.expanduser(p)
        return "~" + p[len(config.HOME):] if p.startswith(config.HOME) else p

    print(f"  scripts/local: {n} from {', '.join(short(x) for x in config.SCAN_DIRS)}")
