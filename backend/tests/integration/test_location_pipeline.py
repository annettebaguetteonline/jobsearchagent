"""Integrationstests für den Location-Pipeline Orchestrator.

Strategie: DB real (tmp_db), alle externen HTTP-Calls gemockt.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.db.database import get_db, init_db
from app.db.models import CompanyCreate, JobCreate, now_iso
from app.db.queries import (
    insert_job,
    upsert_company,
    upsert_transit_cache,
)
from app.location.models import CompanyAddress, TransitResult
from app.location.pipeline import LocationPipeline

# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────


def _make_company(name: str = "Test GmbH") -> CompanyCreate:
    return CompanyCreate(name=name, name_normalized=name.lower())


def _make_job(
    canonical_id: str,
    company_id: int | None = None,
    location_raw: str | None = "60311 Frankfurt am Main",
    work_model: str | None = None,
    raw_text: str | None = None,
) -> JobCreate:
    ts = now_iso()
    return JobCreate(
        canonical_id=canonical_id,
        title="Software Engineer",
        company_id=company_id,
        location_raw=location_raw,
        location_status="unknown",
        work_model=work_model,
        raw_text=raw_text,
        first_seen_at=ts,
        last_seen_at=ts,
    )


def _mock_company_address(lat: float = 50.1109, lng: float = 8.6821) -> CompanyAddress:
    return CompanyAddress(
        street="Teststraße 1",
        city="Frankfurt",
        zip_code="60311",
        lat=lat,
        lng=lng,
        source="impressum",
        status="found",
    )


def _mock_transit_result(
    minutes: int = 45, mode: str = "public_transit", api_used: str = "db_rest"
) -> TransitResult:
    return TransitResult(
        origin_hash="abc123",
        company_id=1,
        transit_minutes=minutes,
        mode=mode,
        api_used=api_used,
    )


# ─── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_remote_job_scores_1_0(tmp_db: Path) -> None:
    """Job mit work_model='remote' → Score 1.0, keine API-Calls."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        job_id = await insert_job(db, _make_job("remote-1", work_model="remote"))

        pipeline = LocationPipeline()
        with (
            patch.object(pipeline._resolver, "resolve", new_callable=AsyncMock) as mock_resolve,
            patch.object(
                pipeline._public_transit,
                "compute_transit_time",
                new_callable=AsyncMock,
            ) as mock_transit,
        ):
            # Lade den Job aus der DB
            cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = await cursor.fetchone()
            from app.db.models import Job

            job = Job(**dict(row))

            score = await pipeline.process_job(db, job)

            assert score.score == 1.0
            assert score.is_remote is True
            assert score.work_model == "remote"
            mock_resolve.assert_not_called()
            mock_transit.assert_not_called()

        await pipeline.close()
        break


@pytest.mark.asyncio
async def test_remote_detected_from_location_raw(tmp_db: Path) -> None:
    """location_raw='Remote' → Score 1.0."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        job_id = await insert_job(db, _make_job("remote-2", location_raw="Remote"))

        pipeline = LocationPipeline()
        cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        from app.db.models import Job

        job = Job(**dict(row))
        score = await pipeline.process_job(db, job)

        assert score.score == 1.0
        assert score.is_remote is True
        await pipeline.close()
        break


@pytest.mark.asyncio
async def test_remote_detected_from_raw_text(tmp_db: Path) -> None:
    """raw_text='100% remote Position', work_model=None → Score 1.0."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        job_id = await insert_job(
            db,
            _make_job(
                "remote-3",
                location_raw="Berlin",
                raw_text="Dies ist eine 100% remote Position.",
            ),
        )

        pipeline = LocationPipeline()
        cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        from app.db.models import Job

        job = Job(**dict(row))
        score = await pipeline.process_job(db, job)

        assert score.score == 1.0
        assert score.is_remote is True
        await pipeline.close()
        break


@pytest.mark.asyncio
async def test_full_pipeline_flow(tmp_db: Path) -> None:
    """Job mit Location → Resolve Address (mock) → Transit (mock) → Score berechnet."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        company_id = await upsert_company(db, _make_company())
        job_id = await insert_job(
            db,
            _make_job("full-1", company_id=company_id, work_model="onsite"),
        )

        pipeline = LocationPipeline()

        mock_address = _mock_company_address()
        mock_public = _mock_transit_result(minutes=45, mode="public_transit")
        mock_car = _mock_transit_result(minutes=30, mode="car", api_used="osrm")

        with (
            patch.object(
                pipeline._resolver,
                "resolve",
                new_callable=AsyncMock,
                return_value=mock_address,
            ),
            patch.object(
                pipeline._public_transit,
                "compute_transit_time",
                new_callable=AsyncMock,
                return_value=mock_public,
            ),
            patch.object(
                pipeline._car_routing,
                "compute_driving_time",
                new_callable=AsyncMock,
                return_value=mock_car,
            ),
            patch.object(
                pipeline,
                "_get_home_coords",
                new_callable=AsyncMock,
                return_value=(50.0, 8.0),
            ),
        ):
            cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = await cursor.fetchone()
            from app.db.models import Job

            job = Job(**dict(row))
            score = await pipeline.process_job(db, job)

            assert score.score > 0.0
            assert score.score <= 1.0
            assert score.transit_minutes_public == 45
            assert score.transit_minutes_car == 30
            assert score.work_model == "onsite"
            assert score.is_remote is False

        # Prüfe DB-Status
        cursor = await db.execute("SELECT location_status FROM jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        assert row["location_status"] == "resolved"

        await pipeline.close()
        break


@pytest.mark.asyncio
async def test_transit_cache_hit(tmp_db: Path) -> None:
    """Zweiter Job gleiche Firma → kein zweiter Transit-Call für ÖPNV."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        company_id = await upsert_company(db, _make_company())

        # Cache füllen
        from app.location.transit import hash_home_address

        origin_hash = hash_home_address("Frankfurt, Germany")
        await upsert_transit_cache(db, company_id, origin_hash, 42, "db_rest", ttl_days=90)

        job_id = await insert_job(
            db,
            _make_job("cache-1", company_id=company_id, work_model="onsite"),
        )

        pipeline = LocationPipeline()
        mock_address = _mock_company_address()
        mock_car = _mock_transit_result(minutes=25, mode="car", api_used="osrm")

        with (
            patch.object(
                pipeline._resolver,
                "resolve",
                new_callable=AsyncMock,
                return_value=mock_address,
            ),
            patch.object(
                pipeline._public_transit,
                "compute_transit_time",
                new_callable=AsyncMock,
            ) as mock_public_transit,
            patch.object(
                pipeline._car_routing,
                "compute_driving_time",
                new_callable=AsyncMock,
                return_value=mock_car,
            ),
            patch.object(
                pipeline,
                "_get_home_coords",
                new_callable=AsyncMock,
                return_value=(50.0, 8.0),
            ),
        ):
            cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = await cursor.fetchone()
            from app.db.models import Job

            job = Job(**dict(row))
            score = await pipeline.process_job(db, job)

            # ÖPNV aus Cache, kein API-Call
            mock_public_transit.assert_not_called()
            assert score.transit_minutes_public == 42
            assert score.transit_minutes_car == 25

        await pipeline.close()
        break


@pytest.mark.asyncio
async def test_batch_processing(tmp_db: Path) -> None:
    """3 Jobs → alle verarbeitet, Ergebnisse korrekt."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        # 3 Remote-Jobs für einfaches Testen
        for i in range(3):
            await insert_job(db, _make_job(f"batch-{i}", work_model="remote"))

        pipeline = LocationPipeline()
        results = await pipeline.process_batch(db, limit=10)

        assert len(results) == 3
        for _job_id, score in results:
            assert score.score == 1.0
            assert score.is_remote is True

        await pipeline.close()
        break


@pytest.mark.asyncio
async def test_address_resolution_failure(tmp_db: Path) -> None:
    """Resolver gibt None → location_status='failed'."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        company_id = await upsert_company(db, _make_company())
        job_id = await insert_job(
            db,
            _make_job("fail-1", company_id=company_id, work_model="onsite"),
        )

        pipeline = LocationPipeline()

        with patch.object(
            pipeline._resolver,
            "resolve",
            new_callable=AsyncMock,
            return_value=None,
        ):
            cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = await cursor.fetchone()
            from app.db.models import Job

            job = Job(**dict(row))
            score = await pipeline.process_job(db, job)

            # Kein Transit → Score 0.5 (konservativ)
            assert score.score == 0.5
            assert score.transit_minutes_public is None
            assert score.transit_minutes_car is None

        # DB-Status = failed
        cursor = await db.execute("SELECT location_status FROM jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        assert row["location_status"] == "failed"

        await pipeline.close()
        break


@pytest.mark.asyncio
async def test_both_transit_modes(tmp_db: Path) -> None:
    """Prüfe dass ÖPNV und Auto beide abgefragt werden."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        company_id = await upsert_company(db, _make_company())
        job_id = await insert_job(
            db,
            _make_job("both-1", company_id=company_id, work_model="onsite"),
        )

        pipeline = LocationPipeline()
        mock_address = _mock_company_address()
        mock_public = _mock_transit_result(minutes=50, mode="public_transit")
        mock_car = _mock_transit_result(minutes=35, mode="car", api_used="osrm")

        with (
            patch.object(
                pipeline._resolver,
                "resolve",
                new_callable=AsyncMock,
                return_value=mock_address,
            ),
            patch.object(
                pipeline._public_transit,
                "compute_transit_time",
                new_callable=AsyncMock,
                return_value=mock_public,
            ) as mock_pt,
            patch.object(
                pipeline._car_routing,
                "compute_driving_time",
                new_callable=AsyncMock,
                return_value=mock_car,
            ) as mock_cr,
            patch.object(
                pipeline,
                "_get_home_coords",
                new_callable=AsyncMock,
                return_value=(50.0, 8.0),
            ),
        ):
            cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = await cursor.fetchone()
            from app.db.models import Job

            job = Job(**dict(row))
            score = await pipeline.process_job(db, job)

            # Beide Transit-Modes aufgerufen
            mock_pt.assert_called_once()
            mock_cr.assert_called_once()

            assert score.transit_minutes_public == 50
            assert score.transit_minutes_car == 35

        await pipeline.close()
        break
