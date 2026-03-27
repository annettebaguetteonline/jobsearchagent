"""Integration-Tests für den Evaluierungs-Pipeline Orchestrator.

DB real (tmp_db), alle externen Calls (Ollama, Anthropic) gemockt.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from app.db.database import init_db
from app.db.models import Job, JobCreate, User, UserCreate, now_iso
from app.db.queries import create_user, insert_job
from app.evaluator.models import ExtractedFields, JobSkillExtracted, Stage1bResult
from app.evaluator.pipeline import (
    EvaluationPipeline,
    _create_evaluation,
    _save_extracted_fields,
)
from app.evaluator.stage2 import Stage2Result

# ─── Fixtures ────────────────────────────────────────────────────────────────


async def _setup_db(db_path: Path) -> aiosqlite.Connection:
    """Initialisiere Test-DB und gib Connection zurück."""
    await init_db(db_path)
    db = await aiosqlite.connect(str(db_path))
    db.row_factory = aiosqlite.Row
    return db


async def _create_test_user(
    db: aiosqlite.Connection,
    user_id: str = "test-user-1",
) -> User:
    """Erstelle einen Test-User mit Profil."""
    profile = {
        "skills": {
            "primary": ["Python", "FastAPI"],
            "secondary": ["Docker"],
            "domains": ["Backend"],
        },
        "experience": {
            "total_years": 5,
            "levels_held": ["Senior"],
            "industries": ["FinTech"],
        },
        "preferences": {
            "locations": ["Frankfurt"],
            "min_level": "Senior",
            "avoid": [],
        },
        "narrative_profile": "Backend-Entwickler.",
    }
    await create_user(
        db,
        UserCreate(
            id=user_id,
            name="Test",
            surname="User",
            profile_json=json.dumps(profile),
            profile_version="v1",
        ),
    )
    rows = list(await db.execute_fetchall("SELECT * FROM users WHERE id = ?", (user_id,)))
    return User.model_validate(dict(rows[0]))


async def _create_test_job(
    db: aiosqlite.Connection,
    title: str = "Python Developer",
    raw_text: str = "Senior Python Developer gesucht.",
    company_id: int | None = None,
) -> Job:
    """Erstelle einen Test-Job."""
    ts = now_iso()
    job_id = await insert_job(
        db,
        JobCreate(
            canonical_id=f"test-{title.lower().replace(' ', '-')}",
            title=title,
            company_id=company_id,
            location_raw="Frankfurt",
            first_seen_at=ts,
            last_seen_at=ts,
            raw_text=raw_text,
        ),
    )
    cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    return Job.model_validate(dict(row))


def _make_mock_stage1a(passed: bool = True) -> MagicMock:
    """Mock Stage1aFilter."""
    stage1a = MagicMock()
    result = MagicMock()
    result.passed = passed
    result.reason = "OK" if passed else "Keyword-Ausschluss: SAP"
    result.model = "deterministic"
    result.duration_ms = 0
    result.stage = "1a"
    stage1a.check.return_value = result
    return stage1a


def _make_mock_stage1b(
    passed: bool = True,
    extracted: ExtractedFields | None = None,
) -> AsyncMock:
    """Mock Stage1bFilter."""
    stage1b = AsyncMock()
    result = Stage1bResult(
        passed=passed,
        reason="Passt" if passed else "Nicht relevant",
        model="mistral-nemo:12b",
        duration_ms=2500,
        extracted_fields=extracted,
    )
    stage1b.check = AsyncMock(return_value=result)
    return stage1b


def _make_mock_stage2_result() -> Stage2Result:
    """Mock Stage2Result."""
    return Stage2Result(
        score=7.5,
        score_breakdown={
            "skills": 8.0,
            "level": 7.0,
            "domain": 7.5,
            "location": 8.0,
            "potential": 6.0,
        },
        recommendation="APPLY",
        match_reasons=["Python passt"],
        missing_skills=["Kubernetes"],
        salary_estimate="65.000-80.000 EUR",
        summary="Gute Stelle.",
        application_tips=["Kubernetes-Erfahrung hervorheben"],
        model="claude-haiku-4-5",
        tokens_used=1500,
        duration_ms=3000,
        strategy="structured_core",
    )


# ─── DB-Hilfsfunktionen Tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_evaluation(tmp_db: Path) -> None:
    """Evaluation wird in DB erstellt."""
    db = await _setup_db(tmp_db)
    try:
        user = await _create_test_user(db)
        job = await _create_test_job(db)

        eval_id = await _create_evaluation(db, job.id, user.id, "structured_core")
        assert eval_id > 0

        rows = list(await db.execute_fetchall("SELECT * FROM evaluations WHERE id = ?", (eval_id,)))
        assert len(rows) == 1
        assert rows[0]["job_id"] == job.id
        assert rows[0]["user_id"] == user.id
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_save_extracted_fields_salary(tmp_db: Path) -> None:
    """Extrahierte Gehaltsfelder werden in jobs geschrieben (nur bei NULL)."""
    db = await _setup_db(tmp_db)
    try:
        job = await _create_test_job(db)

        fields = ExtractedFields(
            salary_min=60000,
            salary_max=80000,
            work_model="hybrid",
        )
        count = await _save_extracted_fields(db, job.id, fields)
        assert count >= 2

        # Prüfe DB
        cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job.id,))
        row = await cursor.fetchone()
        assert row is not None
        assert row["salary_min"] == 60000
        assert row["salary_max"] == 80000
        assert row["work_model"] == "hybrid"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_save_extracted_fields_no_overwrite(tmp_db: Path) -> None:
    """Bereits vorhandene Felder werden NICHT überschrieben (COALESCE)."""
    db = await _setup_db(tmp_db)
    try:
        ts = now_iso()
        job_id = await insert_job(
            db,
            JobCreate(
                canonical_id="test-existing",
                title="Test",
                first_seen_at=ts,
                last_seen_at=ts,
                work_model="remote",  # Bereits gesetzt
            ),
        )

        fields = ExtractedFields(work_model="onsite")
        await _save_extracted_fields(db, job_id, fields)

        cursor = await db.execute("SELECT work_model FROM jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        assert row is not None
        assert row["work_model"] == "remote"  # Nicht überschrieben
    finally:
        await db.close()


# ─── Pipeline Tests (mit Mocks) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_job_full_pipeline(tmp_db: Path) -> None:
    """Vollständiger Pipeline-Durchlauf: 1a PASS -> 1b PASS -> Stage 2."""
    db = await _setup_db(tmp_db)
    try:
        user = await _create_test_user(db)
        job = await _create_test_job(db)

        with patch.object(EvaluationPipeline, "__init__", lambda self: None):
            pipeline = EvaluationPipeline.__new__(EvaluationPipeline)
            pipeline._stage1a = _make_mock_stage1a(passed=True)
            pipeline._stage1b = _make_mock_stage1b(
                passed=True,
                extracted=ExtractedFields(salary_min=65000, salary_max=80000),
            )
            pipeline._stage2 = AsyncMock()
            pipeline._stage2.evaluate_single = AsyncMock(return_value=_make_mock_stage2_result())

            result = await pipeline.process_job(db, job, user)

        assert result.stage1a_passed is True
        assert result.stage1b_passed is True
        assert result.stage2_result is not None
        assert result.stage2_result.score == 7.5
        assert result.stage2_result.recommendation == "APPLY"
        assert result.extracted_fields is not None
        assert result.extracted_fields.salary_min == 65000
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_process_job_stage1a_skip(tmp_db: Path) -> None:
    """Stage 1a SKIP -> keine weiteren Stages."""
    db = await _setup_db(tmp_db)
    try:
        user = await _create_test_user(db)
        job = await _create_test_job(db, title="SAP Berater")

        with patch.object(EvaluationPipeline, "__init__", lambda self: None):
            pipeline = EvaluationPipeline.__new__(EvaluationPipeline)
            pipeline._stage1a = _make_mock_stage1a(passed=False)
            pipeline._stage1b = _make_mock_stage1b()
            pipeline._stage2 = AsyncMock()

            result = await pipeline.process_job(db, job, user)

        assert result.stage1a_passed is False
        assert result.stage1b_passed is None  # Nicht ausgeführt
        assert result.stage2_result is None
        pipeline._stage1b.check.assert_not_called()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_process_job_stage1b_skip(tmp_db: Path) -> None:
    """Stage 1a PASS, Stage 1b SKIP -> kein Stage 2."""
    db = await _setup_db(tmp_db)
    try:
        user = await _create_test_user(db)
        job = await _create_test_job(db, title="Krankenpfleger")

        with patch.object(EvaluationPipeline, "__init__", lambda self: None):
            pipeline = EvaluationPipeline.__new__(EvaluationPipeline)
            pipeline._stage1a = _make_mock_stage1a(passed=True)
            pipeline._stage1b = _make_mock_stage1b(passed=False)
            pipeline._stage2 = AsyncMock()

            result = await pipeline.process_job(db, job, user)

        assert result.stage1a_passed is True
        assert result.stage1b_passed is False
        assert result.stage2_result is None
        pipeline._stage2.evaluate_single.assert_not_called()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_process_job_no_profile_raises(tmp_db: Path) -> None:
    """User ohne Profil -> ValueError."""
    db = await _setup_db(tmp_db)
    try:
        await create_user(
            db,
            UserCreate(id="no-profile", name="NoProfile"),
        )
        user_rows = list(await db.execute_fetchall("SELECT * FROM users WHERE id = 'no-profile'"))
        user = User.model_validate(dict(user_rows[0]))
        job = await _create_test_job(db)

        with patch.object(EvaluationPipeline, "__init__", lambda self: None):
            pipeline = EvaluationPipeline.__new__(EvaluationPipeline)
            pipeline._stage1a = _make_mock_stage1a()

            with pytest.raises(ValueError, match="kein Profil"):
                await pipeline.process_job(db, job, user)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_process_job_extracted_fields_saved(tmp_db: Path) -> None:
    """Extrahierte Felder aus Stage 1b werden in der DB gespeichert."""
    db = await _setup_db(tmp_db)
    try:
        user = await _create_test_user(db)
        job = await _create_test_job(db)

        extracted = ExtractedFields(
            salary_min=70000,
            salary_max=90000,
            work_model="hybrid",
            skills=[
                JobSkillExtracted(skill="Python", skill_type="required", confidence=0.95),
            ],
        )

        with patch.object(EvaluationPipeline, "__init__", lambda self: None):
            pipeline = EvaluationPipeline.__new__(EvaluationPipeline)
            pipeline._stage1a = _make_mock_stage1a(passed=True)
            pipeline._stage1b = _make_mock_stage1b(passed=True, extracted=extracted)
            pipeline._stage2 = AsyncMock()
            pipeline._stage2.evaluate_single = AsyncMock(return_value=_make_mock_stage2_result())

            await pipeline.process_job(db, job, user)

        # Prüfe DB
        cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job.id,))
        row = await cursor.fetchone()
        assert row is not None
        assert row["salary_min"] == 70000
        assert row["work_model"] == "hybrid"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_process_batch_stage1(tmp_db: Path) -> None:
    """Batch Stage 1: Mehrere Jobs, verschiedene Ergebnisse."""
    db = await _setup_db(tmp_db)
    try:
        user = await _create_test_user(db)
        await _create_test_job(db, title="Python Dev")
        await _create_test_job(
            db,
            title="Java Dev",
            raw_text="Java Spring Boot Entwickler gesucht.",
        )
        await _create_test_job(
            db,
            title="SAP Consultant",
            raw_text="SAP S/4HANA Berater.",
        )

        async def stage1b_side_effect(
            job: Job, profile: object, raw_text_limit: int = 1500
        ) -> Stage1bResult:
            return Stage1bResult(
                passed=True,
                reason="OK",
                model="mistral-nemo:12b",
                duration_ms=2000,
            )

        with patch.object(EvaluationPipeline, "__init__", lambda self: None):
            pipeline = EvaluationPipeline.__new__(EvaluationPipeline)
            pipeline._stage1a = _make_mock_stage1a(passed=True)
            pipeline._stage1b = AsyncMock()
            pipeline._stage1b.check = AsyncMock(side_effect=stage1b_side_effect)

            result = await pipeline.process_batch_stage1(db, user.id, limit=10)

        assert result.processed == 3
        assert result.passed >= 1
        assert result.errors == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_process_batch_stage1_mixed_results(tmp_db: Path) -> None:
    """Batch Stage 1: Mix aus PASS, 1a-SKIP."""
    db = await _setup_db(tmp_db)
    try:
        user = await _create_test_user(db)
        await _create_test_job(db, title="Good Job")
        await _create_test_job(db, title="Bad Job")

        def stage1a_side_effect(job: Job) -> MagicMock:
            result = MagicMock()
            if "Bad" in job.title:
                result.passed = False
                result.reason = "Keyword: Bad"
            else:
                result.passed = True
                result.reason = "OK"
            result.model = "deterministic"
            result.duration_ms = 0
            return result

        with patch.object(EvaluationPipeline, "__init__", lambda self: None):
            pipeline = EvaluationPipeline.__new__(EvaluationPipeline)
            pipeline._stage1a = MagicMock()
            pipeline._stage1a.check = MagicMock(side_effect=stage1a_side_effect)
            pipeline._stage1b = _make_mock_stage1b(passed=True)

            result = await pipeline.process_batch_stage1(db, user.id, limit=10)

        assert result.processed == 2
        assert result.skipped_1a == 1
        assert result.passed == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_evaluation_written_to_db(tmp_db: Path) -> None:
    """Nach process_job sind alle Felder in der evaluations-Tabelle."""
    db = await _setup_db(tmp_db)
    try:
        user = await _create_test_user(db)
        job = await _create_test_job(db)

        with patch.object(EvaluationPipeline, "__init__", lambda self: None):
            pipeline = EvaluationPipeline.__new__(EvaluationPipeline)
            pipeline._stage1a = _make_mock_stage1a(passed=True)
            pipeline._stage1b = _make_mock_stage1b(passed=True)
            pipeline._stage2 = AsyncMock()
            pipeline._stage2.evaluate_single = AsyncMock(return_value=_make_mock_stage2_result())

            await pipeline.process_job(db, job, user)

        # Prüfe evaluations-Tabelle
        rows = list(
            await db.execute_fetchall(
                "SELECT * FROM evaluations WHERE job_id = ? AND user_id = ?",
                (job.id, user.id),
            )
        )
        assert len(rows) == 1
        assert rows[0]["stage1_pass"] == 1
        assert rows[0]["stage2_score"] == 7.5
        assert rows[0]["stage2_recommendation"] == "APPLY"
    finally:
        await db.close()
