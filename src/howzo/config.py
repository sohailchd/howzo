"""Platform constants and paths.

The database location can be overridden with the HOWZO_DB environment
variable (the test suite uses this to run against temp directories).
"""
import os

IS_WINDOWS = os.name == "nt"
HOME = os.path.expanduser("~")

# Directories scanned for user scripts (see scan/scripts.py)
SCAN_DIRS = [os.path.join(HOME, "bin"), os.path.join(HOME, ".local", "bin")]


def db_dir():
    override = os.environ.get("HOWZO_DB")
    if override:
        return override
    if IS_WINDOWS:
        return os.path.join(os.environ.get("LOCALAPPDATA") or HOME, "howzo")
    return os.path.join(HOME, ".local", "share", "howzo")


def db_path():
    return os.path.join(db_dir(), "howzo.db")
