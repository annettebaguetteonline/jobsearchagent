"""Integrationstests für Jobs-API-Endpoints."""

import pytest

from app.db.database import get_db, init_db
from app.db.models import (
    CompanyCreate,
    EvaluationCreate,
    JobCreate,
    UserCreate,
)
from app.db.queries import (
    create_user,
    get_job_with_details,
    get_jobs_paginated,
    insert_job,
    update_job_status,
    upsert_company,
    upsert_evaluation,
)

USER_ID = "test-user-0001"
TS = "2026-03-20T10:00:00Z"


async def _setup(db):
    """User + Company + 3 Jobs mit Evaluierungen anlegen."""
    await create_user(db, UserCreate(id=USER_ID, name="Test", surname="User"))
    cid = await upsert_company(db, CompanyCreate(name="TechCorp", name_normalized="techcorp"))

    jobs = []
    for i, (title, status, score) in enumerate(
        [
            ("Senior Python Dev", "new", 8.5),
            ("Junior Java Dev", "reviewed", 4.0),
            ("DevOps Engineer", "new", 6.5),
        ]
    ):
        jid = await insert_job(
            db,
            JobCreate(
                canonical_id=f"test-{i}",
                title=title,
                company_id=cid,
                location_raw="Frankfurt",
                work_model="hybrid",
                salary_raw="60.000-80.000",
                first_seen_at=TS,
                last_seen_at=TS,
                status=status,
            ),
        )
        await upsert_evaluation(
            db,
            EvaluationCreate(
                job_id=jid,
                user_id=USER_ID,
                stage1_pass=True,
                evaluated_at=TS,
            ),
        )
        # Stage-2 Score setzen
        await db.execute(
            "UPDATE evaluations SET stage2_score = ?, stage2_recommendation = ? WHERE job_id = ?",
            (score, "APPLY" if score >= 7 else "MAYBE" if score >= 5 else "SKIP", jid),
        )
        await db.commit()
        jobs.append(jid)
    return cid, jobs


@pytest.mark.asyncio
async def test_get_jobs_paginated_returns_all(tmp_db):
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        _, jobs = await _setup(db)
        total, rows = await get_jobs_paginated(db, user_id=USER_ID)
        assert total == 3
        assert len(rows) == 3


@pytest.mark.asyncio
async def test_get_jobs_paginated_filter_status(tmp_db):
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await _setup(db)
        total, rows = await get_jobs_paginated(db, user_id=USER_ID, status="new")
        assert total == 2
        assert all(r["status"] == "new" for r in rows)


@pytest.mark.asyncio
async def test_get_jobs_paginated_filter_min_score(tmp_db):
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await _setup(db)
        total, rows = await get_jobs_paginated(db, user_id=USER_ID, min_score=7.0)
        assert total == 1
        assert rows[0]["title"] == "Senior Python Dev"


@pytest.mark.asyncio
async def test_get_jobs_paginated_sort_by_score(tmp_db):
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await _setup(db)
        _, rows = await get_jobs_paginated(db, user_id=USER_ID, sort_by="score", sort_dir="desc")
        scores = [r["stage2_score"] for r in rows]
        assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_get_jobs_paginated_search(tmp_db):
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await _setup(db)
        total, rows = await get_jobs_paginated(db, user_id=USER_ID, search="Python")
        assert total == 1


@pytest.mark.asyncio
async def test_get_jobs_paginated_pagination(tmp_db):
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await _setup(db)
        total, rows = await get_jobs_paginated(db, user_id=USER_ID, limit=2, offset=0)
        assert total == 3
        assert len(rows) == 2
        _, rows2 = await get_jobs_paginated(db, user_id=USER_ID, limit=2, offset=2)
        assert len(rows2) == 1


@pytest.mark.asyncio
async def test_get_job_with_details(tmp_db):
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        _, jobs = await _setup(db)
        data = await get_job_with_details(db, jobs[0], USER_ID)
        assert data is not None
        assert data["title"] == "Senior Python Dev"
        assert data["company_name"] == "TechCorp"
        assert data["evaluation"] is not None
        assert len(data["sources"]) == 0  # keine Sources eingefügt
        assert isinstance(data["skills"], list)


@pytest.mark.asyncio
async def test_get_job_with_details_not_found(tmp_db):
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await create_user(db, UserCreate(id=USER_ID, name="Test"))
        data = await get_job_with_details(db, 9999, USER_ID)
        assert data is None


@pytest.mark.asyncio
async def test_update_job_status_success(tmp_db):
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        _, jobs = await _setup(db)
        result = await update_job_status(db, jobs[0], "reviewed")
        assert result is True
        data = await get_job_with_details(db, jobs[0], USER_ID)
        assert data["status"] == "reviewed"


@pytest.mark.asyncio
async def test_update_job_status_invalid(tmp_db):
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        _, jobs = await _setup(db)
        with pytest.raises(ValueError, match="Ungültiger Status"):
            await update_job_status(db, jobs[0], "INVALID")


@pytest.mark.asyncio
async def test_update_job_status_not_found(tmp_db):
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await create_user(db, UserCreate(id=USER_ID, name="Test"))
        result = await update_job_status(db, 9999, "reviewed")
        assert result is False
