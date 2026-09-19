"""Subprocess helpers (cross-platform, failure-tolerant)."""
import shutil
import subprocess


def which_cmd(name):
    """Resolve a command to an executable path.

    Needed so Windows .cmd/.bat shims (npm, pipx, ...) resolve correctly;
    falls back to the bare name so a missing command fails softly in run().
    """
    return shutil.which(name) or name


def run(cmd, timeout=30):
    """Run cmd and return stdout. Never raises; returns '' on any failure."""
    try:
        r = subprocess.run([which_cmd(cmd[0])] + list(cmd[1:]),
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return r.stdout or ""
    except Exception:
        return ""
