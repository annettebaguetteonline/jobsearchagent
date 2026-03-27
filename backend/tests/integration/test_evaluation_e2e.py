"""End-to-End-Integrationstests für die Evaluierungs-Pipeline.

Jeder Test simuliert einen vollständigen Pipeline-Durchlauf:
Job → Stage 1a (deterministisch) → Stage 1b (Ollama, gemockt) →
Stage 2 (Claude, gemockt) → DB-Verifikation.

Externe Services werden komplett gemockt.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.database import get_db, init_db
from app.db.models import (
    CompanyCreate,
    EvaluationCreate,
    FeedbackCreate,
    Job,
    JobCreate,
    User,
    UserCreate,
    now_iso,
)
from app.db.queries import (
    create_user,
    get_evaluation,
    get_feedback_for_user,
    insert_feedback,
    insert_job,
    mark_needs_reevaluation,
    update_evaluation_stage2,
    update_user_profile,
    upsert_company,
    upsert_evaluation,
)
from app.evaluator.stage1 import Stage1aFilter, Stage1bFilter
from app.evaluator.stage2 import Stage2Result

USER_ID = "test-e2e-user-001"
TS = "2026-03-20T10:00:00Z"
PROFILE_JSON = json.dumps(
    {
        "skills": {
            "programming_languages": ["Python", "SQL"],
            "frameworks": ["FastAPI", "Django"],
            "tools": ["Docker", "Git"],
            "domains": ["Backend", "Data Engineering"],
        },
        "experience": {
            "years_total": 5,
            "current_level": "Senior",
            "leadership": False,
        },
        "preferences": {
            "work_model": "hybrid",
            "min_salary": 65000,
            "max_commute_min": 60,
            "industries": ["Tech", "FinTech"],
        },
        "narrative_profile": (
            "Senior Python Developer mit 5 Jahren Erfahrung in Backend-Entwicklung."
        ),
        "certifications": [],
        "projects_summary": ["Job Search Agent", "Data Pipeline Framework"],
    }
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
async def e2e_db(tmp_db):
    """DB mit User, Company und Profil für E2E-Tests."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await create_user(
            db,
            UserCreate(
                id=USER_ID,
                name="Test",
                surname="User",
                profile_json=PROFILE_JSON,
                profile_version="v1_abc123",
            ),
        )
        cid = await upsert_company(
            db, CompanyCreate(name="TestCo GmbH", name_normalized="testco gmbh")
        )
        yield {"db_path": tmp_db, "company_id": cid}


# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────


async def _insert_test_job(
    db,
    company_id: int,
    canonical_id: str,
    title: str,
    raw_text: str,
    location_raw: str = "Frankfurt",
    work_model: str | None = None,
    salary_raw: str | None = None,
) -> int:
    """Hilfsfunktion: Job einfügen."""
    return await insert_job(
        db,
        JobCreate(
            canonical_id=canonical_id,
            title=title,
            company_id=company_id,
            location_raw=location_raw,
            work_model=work_model,
            salary_raw=salary_raw,
            first_seen_at=TS,
            last_seen_at=TS,
            raw_text=raw_text,
        ),
    )


async def _get_job(db, job_id: int) -> Job:
    """Hilfsfunktion: Job aus DB laden."""
    cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    data = dict(row)
    data["is_active"] = bool(data.get("is_active", 1))
    return Job.model_validate(data)


async def _get_user(db, user_id: str) -> User:
    """Hilfsfunktion: User aus DB laden."""
    cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = await cursor.fetchone()
    assert row is not None
    return User.model_validate(dict(row))


def _make_pipeline(
    stage1a_keywords: list[str] | None = None,
    ollama_response: dict | None = None,
    stage2_result: Stage2Result | None = None,
):
    """Erstelle eine EvaluationPipeline mit gemockten externen Services.

    Umgeht __init__ und setzt die internen Komponenten direkt,
    damit keine externen Services (Ollama, Anthropic, ChromaDB) nötig sind.
    """
    from app.evaluator.pipeline import EvaluationPipeline

    pipeline = object.__new__(EvaluationPipeline)

    # Stage 1a: Deterministischer Filter
    pipeline._stage1a = Stage1aFilter(exclude_keywords=stage1a_keywords or [])

    # Stage 1b: LLM-Vorfilter mit gemocktem OllamaClient
    mock_ollama = AsyncMock()
    if ollama_response is not None:
        mock_ollama.chat_json = AsyncMock(return_value=ollama_response)
    else:
        mock_ollama.chat_json = AsyncMock(return_value={"pass": True, "reason": "OK"})
    pipeline._ollama = mock_ollama
    pipeline._stage1b = Stage1bFilter(client=mock_ollama, model="test-model")

    # RAG: Mock (keine ChromaDB nötig)
    pipeline._rag = MagicMock()
    pipeline._rag.query = AsyncMock(return_value=[])

    # Stage 2: Mock
    mock_stage2 = MagicMock()
    if stage2_result is not None:
        mock_stage2.evaluate_single = AsyncMock(return_value=stage2_result)
    pipeline._stage2 = mock_stage2

    # Batch: Mock
    pipeline._batch = MagicMock()

    return pipeline


def _make_stage2_result(
    score: float = 8.0,
    recommendation: str = "APPLY",
) -> Stage2Result:
    """Erstelle ein Stage2Result für Tests."""
    return Stage2Result(
        score=score,
        score_breakdown={
            "skills": 9.0,
            "level": 8.0,
            "domain": 7.5,
            "location": 8.0,
            "potential": 8.0,
        },
        recommendation=recommendation,
        match_reasons=[
            "Starkes Python-Profil",
            "FastAPI-Erfahrung passt",
            "Gehaltsrange im Zielbereich",
        ],
        missing_skills=["Kubernetes", "Terraform"],
        salary_estimate="70000-85000",
        summary="Starker Kandidat mit solidem Backend-Profil.",
        application_tips=[
            "FastAPI-Projekte hervorheben",
            "Docker-Erfahrung betonen",
        ],
        model="claude-haiku-4-5",
        tokens_used=1200,
        duration_ms=800,
        strategy="structured_core",
    )


# ─── Test 1: Happy Path ─────────────────────────────────────────────────────


async def test_happy_path_full_evaluation(e2e_db) -> None:
    """Vollständiger Durchlauf: Job → 1a PASS → 1b PASS → Stage 2 → APPLY.

    Prüft dass alle DB-Felder korrekt geschrieben werden.
    """
    async for db in get_db(e2e_db["db_path"]):
        job_id = await _insert_test_job(
            db,
            e2e_db["company_id"],
            canonical_id="e2e-happy-001",
            title="Senior Python Developer",
            raw_text=(
                "Wir suchen einen erfahrenen Python-Entwickler mit FastAPI-Kenntnissen. "
                "Gehalt: 70.000-85.000 EUR. Hybrid-Modell möglich. "
                "Anforderungen: Python, SQL, Docker, REST-APIs."
            ),
            work_model="hybrid",
        )

        job = await _get_job(db, job_id)
        user = await _get_user(db, USER_ID)

        stage2_result = _make_stage2_result(score=8.0, recommendation="APPLY")
        pipeline = _make_pipeline(
            ollama_response={
                "pass": True,
                "reason": "Gutes Skill-Match: Python, FastAPI",
                "extracted": {
                    "salary_min": 70000,
                    "salary_max": 85000,
                    "work_model": "hybrid",
                },
            },
            stage2_result=stage2_result,
        )

        try:
            result = await pipeline.process_job(db, job, user)
        finally:
            await pipeline.close()

        # Verifiziere Rückgabe
        assert result.stage1a_passed is True
        assert result.stage1b_passed is True
        assert result.stage2_result is not None
        assert result.stage2_result.score == 8.0
        assert result.stage2_result.recommendation == "APPLY"

        # Verifiziere DB-Zustand
        ev = await get_evaluation(db, job_id, USER_ID)
        assert ev is not None
        assert ev.stage1_pass is True
        assert ev.stage2_score == 8.0
        assert ev.stage2_recommendation == "APPLY"
        assert ev.stage2_model == "claude-haiku-4-5"


# ─── Test 2: Stage 1a Keyword-Skip ──────────────────────────────────────────


async def test_stage1a_keyword_skip(e2e_db) -> None:
    """Job mit Ausschluss-Keyword 'Chefarzt' → sofortiger SKIP, keine LLM-Calls.

    Stage 1a ist deterministisch — kein Ollama oder Anthropic nötig.
    """
    async for db in get_db(e2e_db["db_path"]):
        job_id = await _insert_test_job(
            db,
            e2e_db["company_id"],
            canonical_id="e2e-skip-keyword-001",
            title="Chefarzt Innere Medizin",
            raw_text="Klinikum sucht Chefarzt für die Abteilung Innere Medizin.",
        )

        job = await _get_job(db, job_id)
        user = await _get_user(db, USER_ID)

        mock_ollama_chat = AsyncMock()
        pipeline = _make_pipeline(
            stage1a_keywords=["chefarzt", "praktikum", "werkstudent"],
        )
        # Ersetze den Ollama-Mock um Aufrufe zu tracken
        pipeline._ollama.chat_json = mock_ollama_chat

        try:
            result = await pipeline.process_job(db, job, user)
        finally:
            await pipeline.close()

        # Verifiziere: Stage 1a SKIP
        assert result.stage1a_passed is False
        assert result.stage1b_passed is None

        # Verifiziere DB-Zustand
        ev = await get_evaluation(db, job_id, USER_ID)
        assert ev is not None
        assert ev.stage1_pass is False
        assert ev.stage1_reason is not None
        assert "chefarzt" in ev.stage1_reason.lower()
        assert ev.stage1_model == "deterministic"
        assert ev.stage2_score is None  # Stage 2 nicht erreicht

        # Sicherstellen dass keine LLM-Calls gemacht wurden
        mock_ollama_chat.assert_not_called()
        pipeline._stage2.evaluate_single.assert_not_called()


# ─── Test 3: Stage 1b Feld-Mismatch ─────────────────────────────────────────


async def test_stage1b_field_mismatch_skip(e2e_db) -> None:
    """Job mit falschem Fachgebiet → Ollama gibt SKIP zurück."""
    async for db in get_db(e2e_db["db_path"]):
        job_id = await _insert_test_job(
            db,
            e2e_db["company_id"],
            canonical_id="e2e-field-skip-001",
            title="Zahntechniker (m/w/d)",
            raw_text="Dentallabor sucht Zahntechniker mit CAD/CAM-Erfahrung.",
        )

        job = await _get_job(db, job_id)
        user = await _get_user(db, USER_ID)

        pipeline = _make_pipeline(
            ollama_response={
                "pass": False,
                "reason": "Falsches Fachgebiet: Medizin statt IT",
                "extracted": {},
            },
        )

        try:
            result = await pipeline.process_job(db, job, user)
        finally:
            await pipeline.close()

        # Verifiziere: Stage 1b SKIP
        assert result.stage1a_passed is True
        assert result.stage1b_passed is False

        # Verifiziere DB-Zustand
        ev = await get_evaluation(db, job_id, USER_ID)
        assert ev is not None
        assert ev.stage1_pass is False
        assert ev.stage1_reason is not None
        assert ev.stage2_score is None

        # Ollama wurde aufgerufen, Anthropic nicht
        pipeline._ollama.chat_json.assert_called_once()
        pipeline._stage2.evaluate_single.assert_not_called()


# ─── Test 4: Feld-Extraktion ────────────────────────────────────────────────


async def test_field_extraction_updates_db(e2e_db) -> None:
    """Stage 1b extrahiert Gehalt und Work-Model → jobs-Tabelle wird aktualisiert."""
    async for db in get_db(e2e_db["db_path"]):
        job_id = await _insert_test_job(
            db,
            e2e_db["company_id"],
            canonical_id="e2e-extract-001",
            title="Backend Developer Python",
            raw_text=(
                "Wir bieten: Gehalt 60.000-75.000 EUR, Remote-Option, "
                "moderner Tech-Stack mit Python und PostgreSQL."
            ),
            salary_raw=None,
            work_model=None,
        )

        # Prüfe: vor Pipeline kein salary_min/max und kein work_model
        job_before = await _get_job(db, job_id)
        assert job_before.salary_min is None
        assert job_before.salary_max is None
        assert job_before.work_model is None

        user = await _get_user(db, USER_ID)

        stage2_result = _make_stage2_result(score=7.5, recommendation="MAYBE")
        pipeline = _make_pipeline(
            ollama_response={
                "pass": True,
                "reason": "Python-Match, gutes Gehalt",
                "extracted": {
                    "salary_min": 60000,
                    "salary_max": 75000,
                    "work_model": "remote",
                    "skills": [
                        {"skill": "Python", "type": "required", "confidence": 0.95},
                        {"skill": "PostgreSQL", "type": "required", "confidence": 0.9},
                    ],
                },
            },
            stage2_result=stage2_result,
        )

        try:
            _ = await pipeline.process_job(db, job_before, user)
        finally:
            await pipeline.close()

        # Verifiziere: Jobs-Tabelle wurde mit extrahierten Feldern aktualisiert
        job_after = await _get_job(db, job_id)
        assert job_after.salary_min == 60000
        assert job_after.salary_max == 75000
        assert job_after.work_model == "remote"

        # Verifiziere: Skills wurden in job_skills eingefügt
        cursor = await db.execute(
            "SELECT skill, skill_type FROM job_skills WHERE job_id = ? ORDER BY skill",
            (job_id,),
        )
        skills = await cursor.fetchall()
        skill_names = [row["skill"] for row in skills]
        assert "PostgreSQL" in skill_names
        assert "Python" in skill_names


# ─── Test 5: Re-Evaluierung nach Profiländerung ─────────────────────────────


async def test_reevaluation_on_profile_update(e2e_db) -> None:
    """Profiländerung setzt needs_reevaluation=1 → erneuter Pipeline-Lauf."""
    async for db in get_db(e2e_db["db_path"]):
        job_id = await _insert_test_job(
            db,
            e2e_db["company_id"],
            canonical_id="e2e-reeval-001",
            title="Python Developer",
            raw_text="Python Developer mit Django-Erfahrung gesucht.",
        )

        # Initiale Evaluierung anlegen
        await upsert_evaluation(
            db,
            EvaluationCreate(
                job_id=job_id,
                user_id=USER_ID,
                eval_strategy="structured_core",
                stage1_pass=True,
                stage1_reason=None,
                stage1_model="deterministic",
                stage1_ms=1,
                evaluated_at=TS,
                profile_version="v1_abc123",
            ),
        )

        # Profil aktualisieren → needs_reevaluation setzen
        new_profile = json.dumps({"skills": {"programming_languages": ["Python", "Go", "Rust"]}})
        await update_user_profile(db, USER_ID, new_profile, "v2_def456")
        updated = await mark_needs_reevaluation(db, USER_ID)
        assert updated == 1

        # Verifiziere: needs_reevaluation ist gesetzt
        ev = await get_evaluation(db, job_id, USER_ID)
        assert ev is not None
        assert ev.needs_reevaluation is True


# ─── Test 6: Feedback-Speicherung und -Abruf ────────────────────────────────


async def test_feedback_storage_and_retrieval(e2e_db) -> None:
    """Feedback speichern → abrufen → score_delta verifizieren."""
    async for db in get_db(e2e_db["db_path"]):
        job_id = await _insert_test_job(
            db,
            e2e_db["company_id"],
            canonical_id="e2e-feedback-001",
            title="ML Engineer",
            raw_text="ML Engineer mit Python und TensorFlow.",
        )

        # Evaluierung anlegen mit Stage-2-Score
        ev_id = await upsert_evaluation(
            db,
            EvaluationCreate(
                job_id=job_id,
                user_id=USER_ID,
                stage1_pass=True,
                evaluated_at=TS,
            ),
        )

        await update_evaluation_stage2(
            db,
            ev_id,
            score=7.0,
            score_breakdown='{"skills": 7}',
            recommendation="MAYBE",
            match_reasons='["Python match"]',
            missing_skills='["TensorFlow"]',
            salary_estimate=None,
            summary="Teilweise passend",
            application_tips='["ML-Projekte hervorheben"]',
            model="claude-haiku-4-5",
            tokens_used=1200,
            duration_ms=2800,
        )

        # Feedback speichern
        fb_id = await insert_feedback(
            db,
            FeedbackCreate(
                job_id=job_id,
                user_id=USER_ID,
                decision="APPLY",
                reasoning="ML ist spannend, TensorFlow kann ich lernen",
                model_score=7.0,
                model_recommendation="MAYBE",
                score_delta=2.0,  # APPLY (9.0) - model_score (7.0)
                decided_at=now_iso(),
            ),
        )
        assert fb_id > 0

        # Feedback abrufen
        feedbacks = await get_feedback_for_user(db, USER_ID)
        assert len(feedbacks) == 1
        fb = feedbacks[0]
        assert fb.decision == "APPLY"
        assert fb.model_score == 7.0
        assert fb.score_delta == 2.0
        assert fb.reasoning == "ML ist spannend, TensorFlow kann ich lernen"
        assert fb.job_id == job_id
