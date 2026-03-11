"""Integrationtest-Fixtures — temporäre DB, gemockte externe APIs."""

from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Frische SQLite-DB für jeden Test ohne Seiteneffekte."""
    return tmp_path / "test.db"
