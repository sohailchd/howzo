"""Platform constants and paths.

The database location can be overridden with the HOWZO_DB environment
variable, a full path to the DB file (the test suite points it at a
temporary file).
"""
import os
import sys

IS_WINDOWS = os.name == "nt"
HOME = os.path.expanduser("~")


def platform_name():
    """'windows', 'macos', or 'linux' — the platform seeds rank against."""
    if IS_WINDOWS:
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


# Directories scanned for user scripts (see scan/scripts.py)
SCAN_DIRS = [os.path.join(HOME, "bin"), os.path.join(HOME, ".local", "bin")]


def db_dir():
    override = os.environ.get("HOWZO_DB")
    if override:
        # a directory override holds howzo.db (see db_path); a file override
        # lives in its parent. The corruption-rebuild path deletes *this*
        # directory's howzo.db files, so resolving to the wrong one matters.
        return override if os.path.isdir(override) else os.path.dirname(os.path.abspath(override))
    if IS_WINDOWS:
        return os.path.join(os.environ.get("LOCALAPPDATA") or HOME, "howzo")
    return os.path.join(HOME, ".local", "share", "howzo")


def db_path():
    override = os.environ.get("HOWZO_DB")
    if override:
        # documented as either the DB file or the directory holding it
        return os.path.join(override, "howzo.db") if os.path.isdir(override) else override
    return os.path.join(db_dir(), "howzo.db")
