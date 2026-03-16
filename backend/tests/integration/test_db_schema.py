"""Integrationstests: Datenbankschema, Migrationen und CRUD-Queries."""

from pathlib import Path

import aiosqlite
import pytest

from app.db.database import get_db, init_db
from app.db.models import CompanyCreate, JobCreate, JobSourceCreate, UserCreate, now_iso
from app.db.queries import (
    create_user,
    get_default_user_id,
    get_job_by_canonical_id,
    get_user,
    insert_job,
    insert_job_source,
    update_job_last_seen,
    upsert_company,
)

# ─── Schema & Migrations ──────────────────────────────────────────────────────


async def test_init_db_creates_all_tables(tmp_db: Path) -> None:
    """init_db legt alle erwarteten Tabellen an."""
    await init_db(tmp_db)

    expected_tables = {
        "companies",
        "transit_cache",
        "jobs",
        "job_sources",
        "evaluations",
        "feedback",
        "preference_patterns",
        "cover_letters",
        "job_skills",
        "skill_trends",
        "scrape_runs",
        "clarification_queue",
        "users",
        "_migrations",
    }

    async for db in get_db(tmp_db):
        rows = await db.execute_fetchall("SELECT name FROM sqlite_master WHERE type='table'")
        actual = {row["name"] for row in rows}
        assert expected_tables <= actual, f"Fehlende Tabellen: {expected_tables - actual}"
        break


async def test_init_db_is_idempotent(tmp_db: Path) -> None:
    """init_db kann mehrfach aufgerufen werden ohne Fehler."""
    await init_db(tmp_db)
    await init_db(tmp_db)  # zweiter Aufruf darf keinen Fehler werfen


async def test_migration_recorded(tmp_db: Path) -> None:
    """Angewandte Migrationen werden in _migrations eingetragen."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        rows = await db.execute_fetchall("SELECT filename FROM _migrations")
        filenames = [row["filename"] for row in rows]
        assert "001_initial_schema.sql" in filenames
        break


async def test_wal_mode_enabled(tmp_db: Path) -> None:
    """WAL-Modus ist aktiv."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        rows = await db.execute_fetchall("PRAGMA journal_mode")
        assert rows[0][0] == "wal"
        break


async def test_foreign_keys_enabled(tmp_db: Path) -> None:
    """Foreign-Key-Enforcement ist aktiv."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        rows = await db.execute_fetchall("PRAGMA foreign_keys")
        assert rows[0][0] == 1
        break


# ─── CRUD: Unternehmen ────────────────────────────────────────────────────────


async def test_upsert_company_creates_new(tmp_db: Path) -> None:
    """upsert_company legt ein neues Unternehmen an."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        company_id = await upsert_company(
            db, CompanyCreate(name="Acme GmbH", name_normalized="acme gmbh")
        )
        assert company_id > 0
        break


async def test_upsert_company_returns_existing_id(tmp_db: Path) -> None:
    """upsert_company gibt die ID zurück wenn das Unternehmen schon existiert."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        id1 = await upsert_company(db, CompanyCreate(name="Acme GmbH", name_normalized="acme gmbh"))
        id2 = await upsert_company(db, CompanyCreate(name="Acme GmbH", name_normalized="acme gmbh"))
        assert id1 == id2
        break


# ─── CRUD: Jobs ───────────────────────────────────────────────────────────────


async def test_insert_and_get_job(tmp_db: Path) -> None:
    """insert_job + get_job_by_canonical_id: Round-Trip funktioniert."""
    await init_db(tmp_db)

    ts = now_iso()
    job = JobCreate(
        canonical_id="abc123",
        title="Senior Python Developer",
        location_raw="Frankfurt",
        first_seen_at=ts,
        last_seen_at=ts,
    )

    async for db in get_db(tmp_db):
        job_id = await insert_job(db, job)
        assert job_id > 0

        retrieved = await get_job_by_canonical_id(db, "abc123")
        assert retrieved is not None
        assert retrieved.title == "Senior Python Developer"
        assert retrieved.location_raw == "Frankfurt"
        assert retrieved.status == "new"
        break


async def test_get_job_nonexistent_returns_none(tmp_db: Path) -> None:
    """get_job_by_canonical_id gibt None zurück wenn kein Job gefunden."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        result = await get_job_by_canonical_id(db, "does-not-exist")
        assert result is None
        break


async def test_update_job_last_seen(tmp_db: Path) -> None:
    """update_job_last_seen aktualisiert den Zeitstempel."""
    await init_db(tmp_db)
    ts = now_iso()

    async for db in get_db(tmp_db):
        job_id = await insert_job(
            db,
            JobCreate(
                canonical_id="xyz789",
                title="Backend Engineer",
                first_seen_at=ts,
                last_seen_at=ts,
            ),
        )
        new_ts = "2099-01-01T00:00:00Z"
        await update_job_last_seen(db, job_id, new_ts)

        rows = await db.execute_fetchall("SELECT last_seen_at FROM jobs WHERE id = ?", (job_id,))
        assert rows[0]["last_seen_at"] == new_ts
        break


# ─── CRUD: job_sources ────────────────────────────────────────────────────────


async def test_insert_job_source(tmp_db: Path) -> None:
    """insert_job_source fügt eine Quelle ein."""
    await init_db(tmp_db)
    ts = now_iso()

    async for db in get_db(tmp_db):
        job_id = await insert_job(
            db,
            JobCreate(
                canonical_id="src-test",
                title="DevOps Engineer",
                first_seen_at=ts,
                last_seen_at=ts,
            ),
        )
        source_id = await insert_job_source(
            db,
            JobSourceCreate(
                job_id=job_id,
                url="https://www.stepstone.de/job/123",
                source_name="stepstone",
                source_type="aggregator",
                first_seen_at=ts,
                last_seen_at=ts,
            ),
        )
        assert source_id > 0
        break


async def test_insert_duplicate_source_url_updates_last_seen(tmp_db: Path) -> None:
    """insert_job_source bei doppelter URL: kein Fehler, last_seen_at aktualisiert."""
    await init_db(tmp_db)
    ts = now_iso()

    async for db in get_db(tmp_db):
        job_id = await insert_job(
            db,
            JobCreate(
                canonical_id="dup-src-test",
                title="SRE Engineer",
                first_seen_at=ts,
                last_seen_at=ts,
            ),
        )
        source = JobSourceCreate(
            job_id=job_id,
            url="https://www.stepstone.de/job/duplicate",
            source_name="stepstone",
            source_type="aggregator",
            first_seen_at=ts,
            last_seen_at=ts,
        )
        id1 = await insert_job_source(db, source)

        new_ts = "2099-06-01T00:00:00Z"
        source2 = source.model_copy(update={"last_seen_at": new_ts})
        id2 = await insert_job_source(db, source2)

        assert id1 == id2
        rows = await db.execute_fetchall(
            "SELECT last_seen_at FROM job_sources WHERE id = ?", (id1,)
        )
        assert rows[0]["last_seen_at"] == new_ts
        break


async def test_migration_002_columns_exist(tmp_db: Path) -> None:
    """Migration 002: source_job_id in job_sources und sector in jobs vorhanden."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        rows = await db.execute_fetchall("PRAGMA table_info(job_sources)")
        col_names = {row["name"] for row in rows}
        assert "source_job_id" in col_names, "source_job_id fehlt in job_sources"

        rows = await db.execute_fetchall("PRAGMA table_info(jobs)")
        col_names = {row["name"] for row in rows}
        assert "sector" in col_names, "sector fehlt in jobs"
        break


async def test_migration_003_users_table(tmp_db: Path) -> None:
    """Migration 003: users-Tabelle und evaluations.user_id sind vorhanden."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        rows = await db.execute_fetchall("PRAGMA table_info(users)")
        col_names = {row["name"] for row in rows}
        assert "id" in col_names
        assert "profile_json" in col_names

        rows = await db.execute_fetchall("PRAGMA table_info(evaluations)")
        col_names = {row["name"] for row in rows}
        assert "user_id" in col_names, "user_id fehlt in evaluations"
        break


async def test_migration_003_default_user_exists(tmp_db: Path) -> None:
    """Migration 003: Default-User ist in der users-Tabelle vorhanden."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        rows = await db.execute_fetchall(
            "SELECT id FROM users WHERE id = '00000000-0000-0000-0000-000000000001'"
        )
        assert rows, "Default-User fehlt"
        break


# ─── CRUD: Users ──────────────────────────────────────────────────────────────


async def test_create_and_get_user(tmp_db: Path) -> None:
    """create_user + get_user: Round-Trip funktioniert."""
    await init_db(tmp_db)

    user = UserCreate(id="11111111-0000-0000-0000-000000000001", name="Max", surname="Lotz")

    async for db in get_db(tmp_db):
        returned_id = await create_user(db, user)
        assert returned_id == user.id

        retrieved = await get_user(db, user.id)
        assert retrieved is not None
        assert retrieved.name == "Max"
        assert retrieved.surname == "Lotz"
        break


async def test_get_user_nonexistent_returns_none(tmp_db: Path) -> None:
    """get_user gibt None zurück wenn kein User gefunden."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        result = await get_user(db, "does-not-exist")
        assert result is None
        break


async def test_get_default_user_id(tmp_db: Path) -> None:
    """get_default_user_id gibt die ID des ältesten Users zurück."""
    await init_db(tmp_db)

    async for db in get_db(tmp_db):
        default_id = await get_default_user_id(db)
        assert default_id == "00000000-0000-0000-0000-000000000001"
        break


async def test_foreign_key_constraint_enforced(tmp_db: Path) -> None:
    """job_sources → jobs: Foreign-Key-Constraint wird durchgesetzt."""
    await init_db(tmp_db)
    ts = now_iso()

    async for db in get_db(tmp_db):
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                """
                INSERT INTO job_sources
                (job_id, url, source_name, source_type, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (99999, "https://example.com/job", "stepstone", "aggregator", ts, ts),
            )
            await db.commit()
        break
