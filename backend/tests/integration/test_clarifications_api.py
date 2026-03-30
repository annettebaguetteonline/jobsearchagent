"""Integrationstests für Clarification-Queue-API."""

import pytest

from app.db.database import get_db, init_db
from app.db.models import CompanyCreate, JobCreate, UserCreate, now_iso
from app.db.queries import create_user, insert_job, upsert_company

USER_ID = "test-user-0001"
TS = "2026-03-20T10:00:00Z"


async def _create_clarification(db, entity_type, entity_id, issue_type, severity="yellow"):
    """Hilfsfunktion: Klärungsbedarf anlegen."""
    cursor = await db.execute(
        """
        INSERT INTO clarification_queue (entity_type, entity_id, issue_type, priority, severity)
        VALUES (?, ?, ?, 'normal', ?)
        """,
        (entity_type, entity_id, issue_type, severity),
    )
    await db.commit()
    return cursor.lastrowid


@pytest.mark.asyncio
async def test_list_clarifications_empty(tmp_db):
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await create_user(db, UserCreate(id=USER_ID, name="Test"))
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM clarification_queue WHERE resolved = 0"
        )
        row = await cursor.fetchone()
        assert row["cnt"] == 0


@pytest.mark.asyncio
async def test_list_clarifications_with_items(tmp_db):
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await create_user(db, UserCreate(id=USER_ID, name="Test"))
        cid = await upsert_company(db, CompanyCreate(name="TestCo", name_normalized="testco"))
        jid = await insert_job(
            db,
            JobCreate(
                canonical_id="j1",
                title="Test Job",
                company_id=cid,
                first_seen_at=TS,
                last_seen_at=TS,
            ),
        )
        await _create_clarification(db, "job", jid, "address_unknown", "red")
        await _create_clarification(db, "company", cid, "website_unknown", "yellow")

        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM clarification_queue WHERE resolved = 0"
        )
        row = await cursor.fetchone()
        assert row["cnt"] == 2


@pytest.mark.asyncio
async def test_resolve_clarification(tmp_db):
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await create_user(db, UserCreate(id=USER_ID, name="Test"))
        cid = await upsert_company(db, CompanyCreate(name="TestCo", name_normalized="testco"))
        cl_id = await _create_clarification(db, "company", cid, "website_unknown")

        await db.execute(
            """
            UPDATE clarification_queue
            SET resolved = 1, resolved_at = ?, resolved_by = 'manual'
            WHERE id = ?
            """,
            (now_iso(), cl_id),
        )
        await db.commit()

        cursor = await db.execute("SELECT resolved FROM clarification_queue WHERE id = ?", (cl_id,))
        row = await cursor.fetchone()
        assert row["resolved"] == 1


@pytest.mark.asyncio
async def test_update_url_sets_careers_url(tmp_db):
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await create_user(db, UserCreate(id=USER_ID, name="Test"))
        cid = await upsert_company(db, CompanyCreate(name="TestCo", name_normalized="testco"))
        cl_id = await _create_clarification(db, "company", cid, "website_unknown")

        # URL setzen
        await db.execute(
            "UPDATE companies SET careers_url = ? WHERE id = ?",
            ("https://testco.de/karriere", cid),
        )
        await db.execute(
            "UPDATE clarification_queue SET resolved = 1, resolved_by = 'manual' WHERE id = ?",
            (cl_id,),
        )
        await db.commit()

        cursor = await db.execute("SELECT careers_url FROM companies WHERE id = ?", (cid,))
        row = await cursor.fetchone()
        assert row["careers_url"] == "https://testco.de/karriere"
