"""Root-level pytest-Fixtures für alle Tests."""

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
