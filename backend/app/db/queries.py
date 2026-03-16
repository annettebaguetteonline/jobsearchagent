"""Datenbank-Queries: CRUD-Helfer für Jobs, Quellen, Unternehmen, User und Scrape-Runs."""

import json
import logging

import aiosqlite

from app.db.models import (
    CompanyCreate,
    Job,
    JobCreate,
    JobSourceCreate,
    ScrapeRun,
    ScrapeRunStats,
    User,
    UserCreate,
    now_iso,
)

logger = logging.getLogger(__name__)


# ─── User ─────────────────────────────────────────────────────────────────────


async def create_user(db: aiosqlite.Connection, user: UserCreate) -> str:
    """Legt einen neuen User an. Gibt die UUID zurück."""
    await db.execute(
        """
        INSERT INTO users (id, name, surname, profile_json, profile_version, folder)
        VALUES (:id, :name, :surname, :profile_json, :profile_version, :folder)
        """,
        user.model_dump(),
    )
    await db.commit()
    return user.id


async def get_user(db: aiosqlite.Connection, user_id: str) -> User | None:
    """Gibt einen User anhand seiner UUID zurück."""
    rows = list(await db.execute_fetchall("SELECT * FROM users WHERE id = ?", (user_id,)))
    if not rows:
        return None
    return User.model_validate(dict(rows[0]))


async def get_default_user_id(db: aiosqlite.Connection) -> str:
    """Gibt die ID des ältesten Users zurück (Default-User aus Migration 003)."""
    rows = list(await db.execute_fetchall("SELECT id FROM users ORDER BY created_at ASC LIMIT 1"))
    if not rows:
        raise RuntimeError("Keine User in der Datenbank. Migration 003 ausgeführt?")
    return str(rows[0]["id"])


# ─── Unternehmen ──────────────────────────────────────────────────────────────


async def upsert_company(db: aiosqlite.Connection, company: CompanyCreate) -> int:
    """Legt ein neues Unternehmen an oder gibt die ID des vorhandenen zurück."""
    rows = list(
        await db.execute_fetchall(
            "SELECT id FROM companies WHERE name_normalized = ?",
            (company.name_normalized,),
        )
    )
    if rows:
        return int(rows[0]["id"])

    cursor = await db.execute(
        "INSERT INTO companies (name, name_normalized) VALUES (?, ?)",
        (company.name, company.name_normalized),
    )
    await db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


# ─── Stellen ──────────────────────────────────────────────────────────────────


def _row_to_job(row: dict) -> Job:  # type: ignore[type-arg]
    """Wandelt eine DB-Zeile in ein Job-Objekt um."""
    row["is_active"] = bool(row["is_active"])
    return Job.model_validate(row)


async def get_job_by_canonical_id(db: aiosqlite.Connection, canonical_id: str) -> Job | None:
    """Gibt einen Job anhand seiner canonical_id zurück, oder None."""
    rows = list(
        await db.execute_fetchall("SELECT * FROM jobs WHERE canonical_id = ?", (canonical_id,))
    )
    if not rows:
        return None
    return _row_to_job(dict(rows[0]))


async def get_job_by_source_job_id(
    db: aiosqlite.Connection, source_name: str, source_job_id: str
) -> Job | None:
    """Gibt einen Job zurück, dessen Quelle (source_name, source_job_id) bekannt ist.

    Wird für Stage-0-Dedup verwendet: innerhalb einer Quelle ist die eigene ID
    das zuverlässigste Duplikat-Kriterium.
    """
    rows = list(
        await db.execute_fetchall(
            """
            SELECT j.* FROM jobs j
            JOIN job_sources s ON s.job_id = j.id
            WHERE s.source_name = ? AND s.source_job_id = ?
            """,
            (source_name, source_job_id),
        )
    )
    if not rows:
        return None
    return _row_to_job(dict(rows[0]))


async def insert_job(db: aiosqlite.Connection, job: JobCreate) -> int:
    """Fügt einen neuen Job ein und gibt seine ID zurück."""
    cursor = await db.execute(
        """
        INSERT INTO jobs (
            canonical_id, title, company_id, location_raw, location_status,
            work_model, salary_raw, salary_min, salary_max, deadline,
            first_seen_at, last_seen_at, status, is_active, content_hash, raw_text, sector
        ) VALUES (
            :canonical_id, :title, :company_id, :location_raw, :location_status,
            :work_model, :salary_raw, :salary_min, :salary_max, :deadline,
            :first_seen_at, :last_seen_at, :status, :is_active, :content_hash, :raw_text, :sector
        )
        """,
        {**job.model_dump(), "is_active": int(job.is_active)},
    )
    await db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def get_all_job_titles_for_company(db: aiosqlite.Connection, company_id: int) -> list[str]:
    """Gibt alle Jobtitel eines Unternehmens zurück (für Fuzzy-Deduplication)."""
    rows = await db.execute_fetchall(
        "SELECT title FROM jobs WHERE company_id = ? AND is_active = 1",
        (company_id,),
    )
    return [row["title"] for row in rows]


async def mark_expired_jobs(db: aiosqlite.Connection) -> int:
    """Setzt is_active=0 und status='expired' für Jobs deren Deadline abgelaufen ist.

    Läuft nach jedem Scrape-Run. Gibt die Anzahl neu abgelaufener Jobs zurück.
    """
    ts = now_iso()
    cursor = await db.execute(
        """
        UPDATE jobs
        SET is_active = 0, status = 'expired', updated_at = ?
        WHERE deadline IS NOT NULL
          AND deadline < ?
          AND is_active = 1
          AND status NOT IN ('applying', 'applied', 'interview', 'offer')
        """,
        (ts, ts),
    )
    await db.commit()
    return cursor.rowcount or 0


# ─── Quellen ──────────────────────────────────────────────────────────────────


async def insert_job_source(db: aiosqlite.Connection, source: JobSourceCreate) -> int:
    """Fügt eine neue Job-Quelle ein und gibt ihre ID zurück.

    Bei doppelter URL (UNIQUE-Constraint): last_seen_at aktualisieren, ID zurückgeben.
    """
    try:
        cursor = await db.execute(
            """
            INSERT INTO job_sources (
                job_id, url, source_name, source_type, is_canonical,
                first_seen_at, last_seen_at, source_job_id
            ) VALUES (
                :job_id, :url, :source_name, :source_type, :is_canonical,
                :first_seen_at, :last_seen_at, :source_job_id
            )
            """,
            {**source.model_dump(), "is_canonical": int(source.is_canonical)},
        )
        await db.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid
    except aiosqlite.IntegrityError:
        # URL bereits vorhanden – last_seen_at aktualisieren
        await db.execute(
            "UPDATE job_sources SET last_seen_at = ? WHERE url = ?",
            (source.last_seen_at, source.url),
        )
        await db.commit()
        rows = list(
            await db.execute_fetchall("SELECT id FROM job_sources WHERE url = ?", (source.url,))
        )
        return int(rows[0]["id"])


async def get_known_source_job_ids(db: aiosqlite.Connection, source_name: str) -> set[str]:
    """Gibt alle bekannten source_job_ids für eine Quelle zurück."""
    rows = await db.execute_fetchall(
        "SELECT DISTINCT source_job_id FROM job_sources "
        "WHERE source_name = ? AND source_job_id IS NOT NULL",
        (source_name,),
    )
    return {row["source_job_id"] for row in rows}


async def source_url_exists(db: aiosqlite.Connection, url: str) -> bool:
    """Prüft ob eine URL bereits als Quelle bekannt ist."""
    rows = await db.execute_fetchall("SELECT 1 FROM job_sources WHERE url = ?", (url,))
    return bool(rows)


async def update_job_last_seen(db: aiosqlite.Connection, job_id: int, ts: str) -> None:
    """Aktualisiert last_seen_at — markiert den Job als noch aktiv."""
    await db.execute(
        "UPDATE jobs SET last_seen_at = ?, updated_at = ? WHERE id = ?",
        (ts, ts, job_id),
    )
    await db.commit()


# ─── Scrape-Runs ──────────────────────────────────────────────────────────────


async def create_scrape_run(db: aiosqlite.Connection) -> int:
    """Legt einen neuen Scrape-Run an und gibt seine ID zurück."""
    cursor = await db.execute(
        "INSERT INTO scrape_runs (started_at, status) VALUES (?, 'running')",
        (now_iso(),),
    )
    await db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def finish_scrape_run(
    db: aiosqlite.Connection,
    run_id: int,
    stats: ScrapeRunStats,
    sources: list[str],
    error_log: list[str] | None = None,
    status: str = "finished",
) -> None:
    """Schließt einen Scrape-Run ab und speichert die Statistiken."""
    await db.execute(
        """
        UPDATE scrape_runs
        SET finished_at = ?, status = ?, sources_run = ?, stats = ?, error_log = ?
        WHERE id = ?
        """,
        (
            now_iso(),
            status,
            json.dumps(sources),
            json.dumps(stats.model_dump()),
            json.dumps(error_log) if error_log else None,
            run_id,
        ),
    )
    await db.commit()


async def get_scrape_run(db: aiosqlite.Connection, run_id: int) -> ScrapeRun | None:
    """Gibt einen Scrape-Run anhand seiner ID zurück."""
    rows = list(await db.execute_fetchall("SELECT * FROM scrape_runs WHERE id = ?", (run_id,)))
    if not rows:
        return None
    row = dict(rows[0])
    return ScrapeRun(
        id=row["id"],
        started_at=row["started_at"],
        finished_at=row.get("finished_at"),
        status=row["status"],
        sources_run=json.loads(row["sources_run"]) if row.get("sources_run") else None,
        stats=ScrapeRunStats(**json.loads(row["stats"])) if row.get("stats") else None,
        error_log=json.loads(row["error_log"]) if row.get("error_log") else None,
    )
