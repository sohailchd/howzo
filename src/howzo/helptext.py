"""Human-readable text extraction: man pages and --help output."""
import os
import re
import shutil
import subprocess

MAN_AVAILABLE = shutil.which("man") is not None

# man(1) emits underlined text as char+backspace+char (e.g. 'N\x08N A\x08A').
# Drop the pre-backspace char, then any stray backspaces.
_UNDERLINE = re.compile(r".\x08")


def _clean_man(out):
    return _UNDERLINE.sub("", out).replace("\x08", "")


def _parse_man(out):
    """Pull (oneliner, excerpt) out of raw man-page text."""
    if not out.strip():
        return "", ""
    lines = _clean_man(out).splitlines()
    oneliner, excerpt = "", "\n".join(lines[:60])[:3500]
    try:  # NAME section first line: "name - description" (man may use – or -)
        i = next(j for j, l in enumerate(lines) if l.strip() == "NAME")
        for l in lines[i+1:i+6]:
            s = l.strip()
            if not s:
                continue
            cuts = [j for j in (s.find("-"), s.find("–")) if j > 0]
            if cuts:
                oneliner = s[min(cuts)+1:].strip()
                break
    except StopIteration:
        pass
    return oneliner, excerpt


def man_oneliner(name):
    """(oneliner, excerpt) from `man name`; ('', '') if man is missing/empty."""
    if not MAN_AVAILABLE:
        return "", ""
    try:
        p = subprocess.run(["man", name], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=8)
        out = p.stdout or ""
    except Exception:
        return "", ""
    return _parse_man(out)


def capture_help(name, path=""):
    """Run `tool --help` (then -h) and return the first 4000 chars, or None."""
    p = path or shutil.which(name)
    if not p or not os.path.exists(p):
        return None
    for flag in ("--help", "-h"):
        try:
            r = subprocess.run([p, flag], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=5)
            out = (r.stdout or r.stderr).strip()
            if len(out) > 60:
                return out[:4000]
        except Exception:
            continue
    return None
