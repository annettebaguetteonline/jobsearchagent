"""Integrationstests für Evaluierungs-API-Endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.database import get_db, init_db  # get_db re-exported for seeded_db fixture
from app.db.models import (
    CompanyCreate,
    EvaluationCreate,
    JobCreate,
    UserCreate,
)
from app.db.queries import (
    create_user,
    insert_job,
    update_evaluation_stage2,
    upsert_company,
    upsert_evaluation,
)
from app.main import app

USER_ID = "test-api-user-001"
TS = "2026-03-20T10:00:00Z"


@pytest.fixture
async def seeded_db(tmp_db):
    """DB mit User, Company und Jobs für API-Tests."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await create_user(db, UserCreate(id=USER_ID, name="Test", surname="User"))
        cid = await upsert_company(db, CompanyCreate(name="TestCo", name_normalized="testco"))
        j1 = await insert_job(
            db,
            JobCreate(
                canonical_id="api-j1",
                title="Python Developer",
                company_id=cid,
                location_raw="Frankfurt",
                first_seen_at=TS,
                last_seen_at=TS,
                raw_text="We need a Python developer with FastAPI experience.",
            ),
        )
        j2 = await insert_job(
            db,
            JobCreate(
                canonical_id="api-j2",
                title="Data Engineer",
                company_id=cid,
                location_raw="Berlin",
                first_seen_at=TS,
                last_seen_at=TS,
                raw_text="Looking for a Data Engineer with Spark.",
            ),
        )
        # Evaluierung für Job 1 mit Stage-2
        ev_id = await upsert_evaluation(
            db,
            EvaluationCreate(
                job_id=j1,
                user_id=USER_ID,
                eval_strategy="structured_core",
                stage1_pass=True,
                stage1_reason=None,
                stage1_model="deterministic",
                stage1_ms=2,
                evaluated_at=TS,
                profile_version="v1",
            ),
        )
        await update_evaluation_stage2(
            db,
            ev_id,
            score=8.5,
            score_breakdown='{"skills": 9, "level": 8}',
            recommendation="APPLY",
            match_reasons='["Python match"]',
            missing_skills='["Kubernetes"]',
            salary_estimate="70000-85000",
            summary="Strong candidate",
            application_tips='["Highlight FastAPI"]',
            model="claude-haiku-4-5",
            tokens_used=1500,
            duration_ms=3200,
        )
        yield {"db_path": tmp_db, "job1_id": j1, "job2_id": j2, "eval_id": ev_id, "company_id": cid}


@pytest.fixture
def override_db(seeded_db):
    """Patcht get_db() im evaluation-Modul auf die Test-DB."""
    from app.db.database import get_db as real_get_db

    async def _test_get_db(db_path=None):
        async for db in real_get_db(seeded_db["db_path"]):
            yield db

    with patch("app.api.evaluation.get_db", _test_get_db):
        yield seeded_db


@pytest.fixture
async def client(override_db):
    """Async-HTTP-Client für die FastAPI-App."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_get_results_returns_evaluations(client, override_db):
    """GET /results liefert paginierte Evaluierungen."""
    resp = await client.get("/api/evaluation/results", params={"user_id": USER_ID})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert len(data["results"]) >= 1
    result = data["results"][0]
    assert result["stage2_score"] == 8.5
    assert result["stage2_recommendation"] == "APPLY"


async def test_get_results_filter_by_min_score(client, override_db):
    """GET /results mit min_score filtert korrekt."""
    resp = await client.get(
        "/api/evaluation/results",
        params={"user_id": USER_ID, "min_score": 9.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0


async def test_get_results_filter_by_recommendation(client, override_db):
    """GET /results mit recommendation-Filter."""
    resp = await client.get(
        "/api/evaluation/results",
        params={"user_id": USER_ID, "recommendation": "APPLY"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    for r in data["results"]:
        assert r["stage2_recommendation"] == "APPLY"


async def test_get_stats_returns_aggregation(client, override_db):
    """GET /stats liefert korrekte Aggregation."""
    resp = await client.get("/api/evaluation/stats", params={"user_id": USER_ID})
    assert resp.status_code == 200
    data = resp.json()
    assert data["evaluated"] >= 1
    assert data["stage1_passed"] >= 1
    assert data["stage2_completed"] >= 1
    assert data["avg_score"] is not None
    assert "APPLY" in data["recommendations"]


async def test_submit_feedback_calculates_score_delta(client, override_db):
    """POST /feedback berechnet score_delta korrekt."""
    resp = await client.post(
        "/api/evaluation/feedback",
        json={
            "job_id": override_db["job1_id"],
            "user_id": USER_ID,
            "decision": "APPLY",
            "reasoning": "Sieht gut aus",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] > 0
    # decision=APPLY (9.0) - model_score (8.5) = 0.5
    assert data["score_delta"] == 0.5


async def test_submit_feedback_without_evaluation(client, override_db):
    """POST /feedback ohne bestehende Evaluierung gibt score_delta=None."""
    resp = await client.post(
        "/api/evaluation/feedback",
        json={
            "job_id": override_db["job2_id"],
            "user_id": USER_ID,
            "decision": "SKIP",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] > 0
    assert data["score_delta"] is None


async def test_get_batch_status_not_found(client, override_db):
    """GET /batch/{batch_id} gibt 404 für unbekannten Batch."""
    resp = await client.get("/api/evaluation/batch/nonexistent-batch-123")
    assert resp.status_code == 404


async def test_get_profile_not_found(client, override_db):
    """GET /profile/{user_id} gibt 404 wenn kein Profil vorhanden."""
    resp = await client.get(f"/api/evaluation/profile/{USER_ID}")
    assert resp.status_code == 404
    assert "Kein Profil" in resp.json()["detail"]


async def test_get_profile_user_not_found(client, override_db):
    """GET /profile/{user_id} gibt 404 für unbekannten User."""
    resp = await client.get("/api/evaluation/profile/nonexistent-user")
    assert resp.status_code == 404
    assert "User nicht gefunden" in resp.json()["detail"]


async def test_run_stage2_starts_background_task(client, override_db):
    """POST /run-stage2 startet Background-Task und gibt sofort zurück."""
    with patch("app.api.evaluation._run_stage2_task", new_callable=AsyncMock):
        resp = await client.post(
            "/api/evaluation/run-stage2",
            json={"user_id": USER_ID, "limit": 10, "strategy": "structured_core"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"
        assert data["user_id"] == USER_ID
