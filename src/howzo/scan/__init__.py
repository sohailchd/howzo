"""Inventory scanners: one module per tool source.

`scanners()` returns the scanner callables appropriate for this platform,
in the order they should run.
"""
from .. import config
from .brew import scan_brew
from .npm import scan_npm
from .pipx import scan_pipx
from .uv import scan_uv
from .scripts import scan_scripts
from .system import scan_system
from .path import scan_path
from .npx import scan_npx_history


def scanners():
    return [scan_brew, scan_npm, scan_pipx, scan_uv, scan_scripts,
            scan_path if config.IS_WINDOWS else scan_system, scan_npx_history]
