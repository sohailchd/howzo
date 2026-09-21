"""Platform constants and paths.

The database location can be overridden with the HOWZO_DB environment
variable, a full path to the DB file (the test suite points it at a
temporary file).
"""
import os

IS_WINDOWS = os.name == "nt"
HOME = os.path.expanduser("~")

# Directories scanned for user scripts (see scan/scripts.py)
SCAN_DIRS = [os.path.join(HOME, "bin"), os.path.join(HOME, ".local", "bin")]


def db_dir():
    override = os.environ.get("HOWZO_DB")
    if override:
        return os.path.dirname(os.path.abspath(override))
    if IS_WINDOWS:
        return os.path.join(os.environ.get("LOCALAPPDATA") or HOME, "howzo")
    return os.path.join(HOME, ".local", "share", "howzo")


def db_path():
    override = os.environ.get("HOWZO_DB")
    if override:
        return override
    return os.path.join(db_dir(), "howzo.db")
