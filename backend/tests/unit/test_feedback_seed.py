"""Unit-Tests für den Feedback-Seed-Mechanismus."""

import textwrap
from pathlib import Path

import pytest

from app.db.database import get_db, init_db
from app.db.models import UserCreate
from app.db.queries import create_user, get_seed_feedback
from app.evaluator.feedback_seed import _load_yaml, load_seed_feedback

USER_ID = "test-seed-user-001"


@pytest.fixture
def valid_seed_file(tmp_path: Path) -> Path:
    """Erstellt eine gültige Seed-YAML-Datei."""
    content = textwrap.dedent(
        """\
        seeds:
          - job_title: "Python Dev"
            company: "TestCo"
            decision: "APPLY"
            reasoning: "Gutes Match"
            model_score: 8.0
            score_delta: 1.0
          - job_title: "Java Dev"
            company: "OtherCo"
            decision: "SKIP"
            reasoning: "Kein Python"
            model_score: 2.0
            score_delta: -1.0
          - job_title: "DevOps"
            company: "CloudCo"
            decision: "MAYBE"
            reasoning: "Teilweise passend"
            model_score: 5.5
            score_delta: 0.5
        """
    )
    seed_file = tmp_path / "test_seeds.yaml"
    seed_file.write_text(content, encoding="utf-8")
    return seed_file


@pytest.fixture
def invalid_seed_file_no_key(tmp_path: Path) -> Path:
    """YAML ohne 'seeds'-Schlüssel."""
    content = "entries:\n  - title: test\n"
    f = tmp_path / "bad_seeds.yaml"
    f.write_text(content, encoding="utf-8")
    return f


@pytest.fixture
def invalid_seed_file_missing_fields(tmp_path: Path) -> Path:
    """YAML mit fehlenden Pflichtfeldern."""
    content = textwrap.dedent(
        """\
        seeds:
          - job_title: "Test"
            company: "TestCo"
        """
    )
    f = tmp_path / "incomplete_seeds.yaml"
    f.write_text(content, encoding="utf-8")
    return f


def test_load_yaml_valid(valid_seed_file: Path) -> None:
    """Gültige YAML-Datei wird korrekt gelesen."""
    seeds = _load_yaml(valid_seed_file)
    assert len(seeds) == 3
    assert seeds[0]["job_title"] == "Python Dev"
    assert seeds[0]["decision"] == "APPLY"
    assert seeds[1]["decision"] == "SKIP"
    assert seeds[2]["decision"] == "MAYBE"


def test_load_yaml_file_not_found() -> None:
    """Nicht existierende Datei wirft FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        _load_yaml(Path("/nonexistent/path/seeds.yaml"))


def test_load_yaml_invalid_structure(invalid_seed_file_no_key: Path) -> None:
    """YAML ohne 'seeds'-Key wirft ValueError."""
    with pytest.raises(ValueError, match="seeds"):
        _load_yaml(invalid_seed_file_no_key)


def test_load_yaml_missing_required_fields(invalid_seed_file_missing_fields: Path) -> None:
    """YAML mit fehlenden Pflichtfeldern wirft ValueError."""
    with pytest.raises(ValueError, match="fehlt"):
        _load_yaml(invalid_seed_file_missing_fields)


async def test_load_seed_feedback_inserts(tmp_db: Path, valid_seed_file: Path) -> None:
    """Seeds werden korrekt in die DB eingefügt."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await create_user(db, UserCreate(id=USER_ID, name="Test"))
        inserted = await load_seed_feedback(db, USER_ID, seed_file=valid_seed_file)
        assert inserted == 3

        seeds = await get_seed_feedback(db, USER_ID)
        assert len(seeds) == 3
        assert all(s.is_seed is True for s in seeds)
        decisions = {s.decision for s in seeds}
        assert decisions == {"APPLY", "SKIP", "MAYBE"}


async def test_load_seed_feedback_idempotent(tmp_db: Path, valid_seed_file: Path) -> None:
    """Wiederholtes Laden fügt keine Duplikate ein."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await create_user(db, UserCreate(id=USER_ID, name="Test"))

        first = await load_seed_feedback(db, USER_ID, seed_file=valid_seed_file)
        assert first == 3

        second = await load_seed_feedback(db, USER_ID, seed_file=valid_seed_file)
        assert second == 0

        seeds = await get_seed_feedback(db, USER_ID)
        assert len(seeds) == 3


async def test_load_seed_feedback_file_not_found(tmp_db: Path) -> None:
    """Nicht existierende Seed-Datei wirft FileNotFoundError."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await create_user(db, UserCreate(id=USER_ID, name="Test"))
        with pytest.raises(FileNotFoundError):
            await load_seed_feedback(db, USER_ID, seed_file=Path("/nonexistent/seeds.yaml"))
