"""Integrationstests für Evaluierungs-bezogene DB-Queries."""

import pytest

from app.db.database import get_db, init_db
from app.db.models import (
    CompanyCreate,
    EvaluationCreate,
    FeedbackCreate,
    JobCreate,
    JobSkillCreate,
    UserCreate,
)
from app.db.queries import (
    create_user,
    get_evaluation,
    get_feedback_for_user,
    get_jobs_needing_evaluation,
    get_jobs_needing_stage2,
    get_seed_feedback,
    get_user,
    insert_feedback,
    insert_job,
    mark_needs_reevaluation,
    update_evaluation_stage1,
    update_evaluation_stage2,
    update_user_profile,
    upsert_company,
    upsert_evaluation,
    upsert_job_skills,
)

USER_ID = "test-user-0001"
TS = "2026-03-20T10:00:00Z"


async def _setup_user_and_job(db):
    """Hilfsfunktion: User + Company + Job anlegen."""
    await create_user(
        db,
        UserCreate(id=USER_ID, name="Test", surname="User"),
    )
    company_id = await upsert_company(
        db,
        CompanyCreate(name="TestCo", name_normalized="testco"),
    )
    job_id = await insert_job(
        db,
        JobCreate(
            canonical_id="test-job-001",
            title="Python Developer",
            company_id=company_id,
            location_raw="Frankfurt",
            first_seen_at=TS,
            last_seen_at=TS,
            raw_text="We are looking for a Python developer with Django experience.",
        ),
    )
    return job_id


@pytest.mark.asyncio
async def test_upsert_evaluation_insert(tmp_db):
    """Neue Evaluierung anlegen, ID > 0."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        job_id = await _setup_user_and_job(db)
        eval_id = await upsert_evaluation(
            db,
            EvaluationCreate(
                job_id=job_id,
                user_id=USER_ID,
                eval_strategy="structured_core",
                stage1_pass=True,
                stage1_reason=None,
                stage1_model="deterministic",
                stage1_ms=2,
                evaluated_at=TS,
                profile_version="abc123",
            ),
        )
        assert eval_id > 0


@pytest.mark.asyncio
async def test_upsert_evaluation_conflict_updates(tmp_db):
    """Zweimal upsert → gleiche ID, Felder aktualisiert."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        job_id = await _setup_user_and_job(db)
        ev = EvaluationCreate(
            job_id=job_id,
            user_id=USER_ID,
            eval_strategy="structured_core",
            stage1_pass=True,
            stage1_reason=None,
            stage1_model="deterministic",
            stage1_ms=2,
            evaluated_at=TS,
            profile_version="v1",
        )
        id1 = await upsert_evaluation(db, ev)
        ev2 = ev.model_copy(update={"profile_version": "v2", "stage1_ms": 5})
        id2 = await upsert_evaluation(db, ev2)
        assert id1 == id2
        result = await get_evaluation(db, job_id, USER_ID)
        assert result is not None
        assert result.profile_version == "v2"
        assert result.stage1_ms == 5


@pytest.mark.asyncio
async def test_get_evaluation_returns_none(tmp_db):
    """Nicht existierende Evaluierung → None."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        result = await get_evaluation(db, 9999, "nonexistent-user")
        assert result is None


@pytest.mark.asyncio
async def test_get_jobs_needing_evaluation(tmp_db):
    """2 Jobs: 1 mit Eval, 1 ohne → nur der ohne."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await create_user(db, UserCreate(id=USER_ID, name="Test"))
        cid = await upsert_company(db, CompanyCreate(name="Co", name_normalized="co"))
        j1 = await insert_job(
            db,
            JobCreate(
                canonical_id="j1",
                title="Job 1",
                company_id=cid,
                first_seen_at=TS,
                last_seen_at=TS,
            ),
        )
        j2 = await insert_job(
            db,
            JobCreate(
                canonical_id="j2",
                title="Job 2",
                company_id=cid,
                first_seen_at=TS,
                last_seen_at=TS,
            ),
        )
        await upsert_evaluation(
            db,
            EvaluationCreate(
                job_id=j1,
                user_id=USER_ID,
                evaluated_at=TS,
            ),
        )
        jobs = await get_jobs_needing_evaluation(db, USER_ID)
        assert len(jobs) == 1
        assert jobs[0].id == j2


@pytest.mark.asyncio
async def test_get_jobs_needing_stage2(tmp_db):
    """Eval mit stage1_pass=1, stage2_score=NULL → enthalten."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        job_id = await _setup_user_and_job(db)
        eval_id = await upsert_evaluation(
            db,
            EvaluationCreate(
                job_id=job_id,
                user_id=USER_ID,
                stage1_pass=True,
                evaluated_at=TS,
            ),
        )
        results = await get_jobs_needing_stage2(db, USER_ID)
        assert len(results) == 1
        assert results[0] == (job_id, eval_id)


@pytest.mark.asyncio
async def test_update_evaluation_stage1(tmp_db):
    """Stage-1-Felder korrekt geschrieben."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        job_id = await _setup_user_and_job(db)
        eval_id = await upsert_evaluation(
            db,
            EvaluationCreate(
                job_id=job_id,
                user_id=USER_ID,
                evaluated_at=TS,
            ),
        )
        await update_evaluation_stage1(
            db,
            eval_id,
            stage1_pass=False,
            stage1_reason="exclude_keyword: Praktikum",
            stage1_model="deterministic",
            stage1_ms=1,
        )
        ev = await get_evaluation(db, job_id, USER_ID)
        assert ev is not None
        assert ev.stage1_pass is False
        assert ev.stage1_reason == "exclude_keyword: Praktikum"
        assert ev.stage1_model == "deterministic"


@pytest.mark.asyncio
async def test_update_evaluation_stage2(tmp_db):
    """Alle Stage-2-Felder korrekt geschrieben."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        job_id = await _setup_user_and_job(db)
        eval_id = await upsert_evaluation(
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
            eval_id,
            score=8.5,
            score_breakdown='{"skills": 9, "level": 8, "domain": 8, "location": 9, "potential": 8}',
            recommendation="APPLY",
            match_reasons='["Python experience", "Django skills"]',
            missing_skills='["Kubernetes"]',
            salary_estimate="65000-80000",
            summary="Strong Python candidate",
            application_tips='["Highlight Django projects"]',
            model="claude-haiku-4-5",
            tokens_used=1500,
            duration_ms=3200,
            location_score=0.95,
            location_effective_minutes=15,
        )
        ev = await get_evaluation(db, job_id, USER_ID)
        assert ev is not None
        assert ev.stage2_score == 8.5
        assert ev.stage2_recommendation == "APPLY"
        assert ev.stage2_model == "claude-haiku-4-5"
        assert ev.location_score == 0.95


@pytest.mark.asyncio
async def test_insert_feedback(tmp_db):
    """Feedback einfügen und per get_feedback_for_user abrufen."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        job_id = await _setup_user_and_job(db)
        fb_id = await insert_feedback(
            db,
            FeedbackCreate(
                job_id=job_id,
                user_id=USER_ID,
                decision="APPLY",
                reasoning="Looks great",
                model_score=8.5,
                model_recommendation="APPLY",
                score_delta=0.0,
                decided_at=TS,
            ),
        )
        assert fb_id > 0
        feedbacks = await get_feedback_for_user(db, USER_ID)
        assert len(feedbacks) == 1
        assert feedbacks[0].decision == "APPLY"


@pytest.mark.asyncio
async def test_get_seed_feedback(tmp_db):
    """Nur is_seed=1 Feedbacks zurückgeben."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        job_id = await _setup_user_and_job(db)
        await insert_feedback(
            db,
            FeedbackCreate(
                job_id=job_id,
                user_id=USER_ID,
                decision="APPLY",
                decided_at=TS,
                is_seed=True,
            ),
        )
        # Zweiten Job + nicht-Seed-Feedback
        j2 = await insert_job(
            db,
            JobCreate(
                canonical_id="j2",
                title="Other Job",
                first_seen_at=TS,
                last_seen_at=TS,
            ),
        )
        await insert_feedback(
            db,
            FeedbackCreate(
                job_id=j2,
                user_id=USER_ID,
                decision="SKIP",
                decided_at=TS,
                is_seed=False,
            ),
        )
        seeds = await get_seed_feedback(db, USER_ID)
        assert len(seeds) == 1
        assert seeds[0].is_seed is True


@pytest.mark.asyncio
async def test_upsert_job_skills(tmp_db):
    """Skills einfügen, Anzahl prüfen, Duplikat-Update."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        job_id = await _setup_user_and_job(db)
        skills = [
            JobSkillCreate(
                job_id=job_id,
                skill="Python",
                skill_type="required",
                confidence=0.95,
            ),
            JobSkillCreate(
                job_id=job_id,
                skill="Django",
                skill_type="required",
                confidence=0.90,
            ),
            JobSkillCreate(
                job_id=job_id,
                skill="Docker",
                skill_type="nice_to_have",
                confidence=0.7,
            ),
        ]
        count = await upsert_job_skills(db, job_id, skills)
        assert count == 3
        # Update: gleicher Skill, neuer Typ
        updated = [
            JobSkillCreate(
                job_id=job_id,
                skill="Docker",
                skill_type="required",
                confidence=0.9,
            ),
        ]
        count2 = await upsert_job_skills(db, job_id, updated)
        assert count2 == 1


@pytest.mark.asyncio
async def test_mark_needs_reevaluation(tmp_db):
    """Alle Evaluierungen eines Users markieren."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await create_user(db, UserCreate(id=USER_ID, name="Test"))
        cid = await upsert_company(db, CompanyCreate(name="Co", name_normalized="co"))
        j1 = await insert_job(
            db,
            JobCreate(
                canonical_id="j1",
                title="Job 1",
                company_id=cid,
                first_seen_at=TS,
                last_seen_at=TS,
            ),
        )
        j2 = await insert_job(
            db,
            JobCreate(
                canonical_id="j2",
                title="Job 2",
                company_id=cid,
                first_seen_at=TS,
                last_seen_at=TS,
            ),
        )
        await upsert_evaluation(
            db,
            EvaluationCreate(
                job_id=j1,
                user_id=USER_ID,
                evaluated_at=TS,
            ),
        )
        await upsert_evaluation(
            db,
            EvaluationCreate(
                job_id=j2,
                user_id=USER_ID,
                evaluated_at=TS,
            ),
        )
        updated = await mark_needs_reevaluation(db, USER_ID)
        assert updated == 2
        ev1 = await get_evaluation(db, j1, USER_ID)
        assert ev1 is not None
        assert ev1.needs_reevaluation is True


@pytest.mark.asyncio
async def test_update_user_profile(tmp_db):
    """Profil-JSON und Version aktualisieren."""
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await create_user(
            db,
            UserCreate(
                id=USER_ID,
                name="Test",
                profile_json=None,
                profile_version=None,
            ),
        )
        await update_user_profile(
            db,
            USER_ID,
            profile_json='{"skills": ["Python"]}',
            profile_version="sha256_abc",
        )
        user = await get_user(db, USER_ID)
        assert user is not None
        assert user.profile_json == '{"skills": ["Python"]}'
        assert user.profile_version == "sha256_abc"
