"""Root-level pytest-Fixtures für alle Tests."""

from pathlib import Path

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Frische SQLite-DB für jeden Test ohne Seiteneffekte."""
    return tmp_path / "test.db"
