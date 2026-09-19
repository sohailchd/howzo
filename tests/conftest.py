"""Shared fixtures: make src/ importable without installation, isolate the DB."""
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def c(tmp_path, monkeypatch):
    """A fresh, empty howzo database in a temp dir (via HOWZO_DB)."""
    from howzo.db import db
    monkeypatch.setenv("HOWZO_DB", str(tmp_path))
    conn = db()
    yield conn
    conn.close()
