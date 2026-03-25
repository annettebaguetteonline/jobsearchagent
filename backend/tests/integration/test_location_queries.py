"""Integrationstests für Location-bezogene DB-Queries."""

from pathlib import Path

import pytest

from app.db.database import get_db, init_db
from app.db.models import CompanyCreate, JobCreate, now_iso
from app.db.queries import (
    get_companies_needing_address,
    get_company,
    get_jobs_needing_location_score,
    get_transit_cached,
    insert_job,
    mark_company_address_failed,
    update_company_address,
    update_job_location_status,
    upsert_company,
    upsert_transit_cache,
)

# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────


def _make_company(name: str = "Acme GmbH") -> CompanyCreate:
    return CompanyCreate(name=name, name_normalized=name.lower())


def _make_job(
    canonical_id: str, location_status: str = "unknown", status: str = "new"
) -> JobCreate:
    ts = now_iso()
    return JobCreate(
        canonical_id=canonical_id,
        title="Software Engineer",
        location_status=location_status,
        status=status,
        first_seen_at=ts,
        last_seen_at=ts,
    )


# ─── get_company ─────────────────────────────────────────────────────────────


async def test_get_company_returns_none_for_missing(tmp_db: Path) -> None:
    """get_company gibt None zurück für nicht existierende ID."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        result = await get_company(db, 99999)
        assert result is None
        break


async def test_get_company_returns_full_company(tmp_db: Path) -> None:
    """get_company gibt Company mit allen Feldern zurück."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        company_id = await upsert_company(db, _make_company("Test GmbH"))
        result = await get_company(db, company_id)
        assert result is not None
        assert result.id == company_id
        assert result.name == "Test GmbH"
        assert result.name_normalized == "test gmbh"
        assert result.address_status == "unknown"
        assert result.remote_policy == "unknown"
        assert result.created_at is not None
        assert result.updated_at is not None
        break


# ─── update_company_address ───────────────────────────────────────────────────


async def test_update_company_address_sets_fields(tmp_db: Path) -> None:
    """update_company_address setzt alle Adressfelder korrekt."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        company_id = await upsert_company(db, _make_company())
        await update_company_address(
            db,
            company_id=company_id,
            street="Musterstraße 1",
            city="Frankfurt",
            zip_code="60311",
            lat=50.1109,
            lng=8.6821,
            source="nominatim",
        )
        company = await get_company(db, company_id)
        assert company is not None
        assert company.address_street == "Musterstraße 1"
        assert company.address_city == "Frankfurt"
        assert company.address_zip == "60311"
        assert company.lat == pytest.approx(50.1109)
        assert company.lng == pytest.approx(8.6821)
        assert company.address_source == "nominatim"
        break


async def test_update_company_address_sets_status_found(tmp_db: Path) -> None:
    """update_company_address setzt address_status auf 'found'."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        company_id = await upsert_company(db, _make_company())
        await update_company_address(
            db,
            company_id=company_id,
            street=None,
            city="Berlin",
            zip_code=None,
            lat=52.52,
            lng=13.405,
            source="searxng",
        )
        company = await get_company(db, company_id)
        assert company is not None
        assert company.address_status == "found"
        break


# ─── mark_company_address_failed ─────────────────────────────────────────────


async def test_mark_company_address_failed(tmp_db: Path) -> None:
    """mark_company_address_failed setzt address_status auf 'failed'."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        company_id = await upsert_company(db, _make_company())
        await mark_company_address_failed(db, company_id)
        company = await get_company(db, company_id)
        assert company is not None
        assert company.address_status == "failed"
        break


# ─── transit_cache ────────────────────────────────────────────────────────────


async def test_transit_cache_miss_returns_none(tmp_db: Path) -> None:
    """get_transit_cached gibt None zurück für nicht existierenden Eintrag."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        result = await get_transit_cached(db, company_id=1, origin_hash="abc123")
        assert result is None
        break


async def test_transit_cache_upsert_then_get(tmp_db: Path) -> None:
    """upsert_transit_cache schreiben, dann lesen — korrekte Minuten."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        company_id = await upsert_company(db, _make_company())
        await upsert_transit_cache(
            db,
            company_id=company_id,
            origin_hash="hash_a",
            transit_minutes=42,
            api_used="vvs",
            ttl_days=90,
        )
        result = await get_transit_cached(db, company_id=company_id, origin_hash="hash_a")
        assert result == 42
        break


async def test_transit_cache_expired_returns_none(tmp_db: Path) -> None:
    """Abgelaufener Eintrag (ttl_days=0) wird nicht zurückgegeben."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        company_id = await upsert_company(db, _make_company())
        await upsert_transit_cache(
            db,
            company_id=company_id,
            origin_hash="hash_exp",
            transit_minutes=15,
            api_used="vvs",
            ttl_days=0,
        )
        result = await get_transit_cached(db, company_id=company_id, origin_hash="hash_exp")
        assert result is None
        break


async def test_transit_cache_upsert_overwrites(tmp_db: Path) -> None:
    """Zweimaliges Schreiben überschreibt mit dem neueren Wert."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        company_id = await upsert_company(db, _make_company())
        await upsert_transit_cache(
            db, company_id=company_id, origin_hash="hash_b", transit_minutes=30, api_used="vvs"
        )
        await upsert_transit_cache(
            db, company_id=company_id, origin_hash="hash_b", transit_minutes=55, api_used="vvs"
        )
        result = await get_transit_cached(db, company_id=company_id, origin_hash="hash_b")
        assert result == 55
        break


# ─── get_companies_needing_address ────────────────────────────────────────────


async def test_get_companies_needing_address(tmp_db: Path) -> None:
    """Nur Companies mit address_status='unknown' werden zurückgegeben."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        id_unknown = await upsert_company(db, _make_company("Unknown Co"))
        id_found = await upsert_company(db, _make_company("Found Co"))
        id_failed = await upsert_company(db, _make_company("Failed Co"))

        await update_company_address(
            db,
            id_found,
            street=None,
            city="Frankfurt",
            zip_code=None,
            lat=50.1,
            lng=8.6,
            source="db",
        )
        await mark_company_address_failed(db, id_failed)

        results = await get_companies_needing_address(db)
        result_ids = [r[0] for r in results]
        assert id_unknown in result_ids
        assert id_found not in result_ids
        assert id_failed not in result_ids
        break


# ─── get_jobs_needing_location_score ─────────────────────────────────────────


async def test_get_jobs_needing_location_score(tmp_db: Path) -> None:
    """Nur aktive Jobs mit location_status='unknown' und passendem Status werden zurückgegeben."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        id_match = await insert_job(db, _make_job("job-1", location_status="unknown", status="new"))
        id_already_scored = await insert_job(
            db, _make_job("job-2", location_status="scored", status="new")
        )
        id_expired = await insert_job(
            db, _make_job("job-3", location_status="unknown", status="expired")
        )
        id_ignored = await insert_job(
            db, _make_job("job-4", location_status="unknown", status="ignored")
        )

        results = await get_jobs_needing_location_score(db)
        result_ids = [j.id for j in results]
        assert id_match in result_ids
        assert id_already_scored not in result_ids
        assert id_expired not in result_ids
        assert id_ignored not in result_ids
        break


# ─── update_job_location_status ──────────────────────────────────────────────


async def test_update_job_location_status(tmp_db: Path) -> None:
    """update_job_location_status ändert den Status korrekt."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        job_id = await insert_job(db, _make_job("job-status-test"))
        await update_job_location_status(db, job_id, "scored")

        rows = await db.execute_fetchall("SELECT location_status FROM jobs WHERE id = ?", (job_id,))
        assert rows[0]["location_status"] == "scored"
        break
