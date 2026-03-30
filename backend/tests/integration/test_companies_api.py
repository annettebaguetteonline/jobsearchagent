"""Integrationstests für Companies-API."""

import pytest

from app.db.database import get_db, init_db
from app.db.models import CompanyCreate
from app.db.queries import get_company, upsert_company


@pytest.mark.asyncio
async def test_get_company_returns_data(tmp_db):
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        cid = await upsert_company(
            db, CompanyCreate(name="TestCorp GmbH", name_normalized="testcorp gmbh")
        )
        company = await get_company(db, cid)
        assert company is not None
        assert company.name == "TestCorp GmbH"
        assert company.address_status == "unknown"


@pytest.mark.asyncio
async def test_get_company_not_found(tmp_db):
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        company = await get_company(db, 9999)
        assert company is None


@pytest.mark.asyncio
async def test_company_search_by_name(tmp_db):
    await init_db(tmp_db)
    async for db in get_db(tmp_db):
        await upsert_company(db, CompanyCreate(name="Alpha GmbH", name_normalized="alpha gmbh"))
        await upsert_company(db, CompanyCreate(name="Beta AG", name_normalized="beta ag"))
        cursor = await db.execute(
            "SELECT id, name FROM companies WHERE name LIKE ? ORDER BY name LIMIT 20",
            ("%Alpha%",),
        )
        rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0]["name"] == "Alpha GmbH"
