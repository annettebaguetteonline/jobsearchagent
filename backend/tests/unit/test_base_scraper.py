"""Unit-Tests für BaseScraper-Hilfsfunktionen: PLZ-Strip, canonical_id, Stage-0-Dedup."""

from pathlib import Path

import pytest

from app.scraper.base import _strip_plz, compute_canonical_id, normalize_text

# ─── normalize_text ───────────────────────────────────────────────────────────


def test_normalize_text_lowercase() -> None:
    assert normalize_text("Frankfurt Am Main") == "frankfurt am main"


def test_normalize_text_strips_punctuation() -> None:
    assert normalize_text("Senior, Python-Developer!") == "senior pythondeveloper"


def test_normalize_text_collapses_whitespace() -> None:
    assert normalize_text("  viel   leerzeichen  ") == "viel leerzeichen"


def test_normalize_text_unicode_nfc() -> None:
    # Ä in NFC vs. decomposed form
    assert normalize_text("München") == "münchen"


# ─── _strip_plz ───────────────────────────────────────────────────────────────


def test_strip_plz_removes_5digit_prefix() -> None:
    assert _strip_plz("34117 Kassel") == "Kassel"


def test_strip_plz_removes_4digit_prefix() -> None:
    """4-stellige PLZ (z.B. Österreich) ebenfalls entfernen."""
    assert _strip_plz("1010 Wien") == "Wien"


def test_strip_plz_city_only_unchanged() -> None:
    """Ortsname ohne PLZ bleibt unverändert."""
    assert _strip_plz("Kassel") == "Kassel"


def test_strip_plz_empty_string() -> None:
    assert _strip_plz("") == ""


def test_strip_plz_does_not_remove_inline_numbers() -> None:
    """Zahlen mitten im String werden nicht entfernt."""
    assert _strip_plz("Frankfurt am Main 60311") == "Frankfurt am Main 60311"


# ─── compute_canonical_id ────────────────────────────────────────────────────


def test_canonical_id_plz_and_city_match() -> None:
    """'34117 Kassel' und 'Kassel' ergeben dieselbe canonical_id."""
    id1 = compute_canonical_id("Senior Developer", "Acme GmbH", "34117 Kassel")
    id2 = compute_canonical_id("Senior Developer", "Acme GmbH", "Kassel")
    assert id1 == id2


def test_canonical_id_different_companies_differ() -> None:
    id1 = compute_canonical_id("Developer", "Acme GmbH", "Berlin")
    id2 = compute_canonical_id("Developer", "Other GmbH", "Berlin")
    assert id1 != id2


def test_canonical_id_different_titles_differ() -> None:
    id1 = compute_canonical_id("Senior Developer", "Acme GmbH", "Berlin")
    id2 = compute_canonical_id("Junior Developer", "Acme GmbH", "Berlin")
    assert id1 != id2


def test_canonical_id_is_deterministic() -> None:
    """Gleiche Eingaben → immer gleicher Hash."""
    id1 = compute_canonical_id("Dev", "Acme", "Frankfurt")
    id2 = compute_canonical_id("Dev", "Acme", "Frankfurt")
    assert id1 == id2


def test_canonical_id_is_hex_string() -> None:
    """Ausgabe ist ein 64-Zeichen SHA-256-Hex-String."""
    result = compute_canonical_id("Dev", "Acme", "Berlin")
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


# ─── Integration: Stage-0-Dedup + mark_expired_jobs ──────────────────────────
# Diese Tests benötigen eine echte DB und liegen deshalb hier als async-Tests.
# Sie verwenden tmp_path (pytest built-in) statt des integration-conftest-Fixtures.


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


async def test_stage0_dedup_source_job_id(tmp_db: Path) -> None:
    """Stage-0-Dedup: gleiche source_job_id innerhalb einer Quelle → 'duplicate'."""
    from app.db.database import get_db, init_db
    from app.db.models import JobCreate, JobSourceCreate, now_iso
    from app.db.queries import insert_job, insert_job_source
    from app.scraper.base import BaseScraper, ScrapedJob

    await init_db(tmp_db)

    ts = now_iso()

    class _FakeScraper(BaseScraper):
        source_name = "test_source"
        source_type = "portal"

        async def fetch_jobs(self) -> list[ScrapedJob]:
            return []

    async for db in get_db(tmp_db):
        # Job + Source manuell einfügen (source_job_id="999")
        job_id = await insert_job(
            db,
            JobCreate(
                canonical_id="test-hash-abc",
                title="Test Job",
                first_seen_at=ts,
                last_seen_at=ts,
            ),
        )
        await insert_job_source(
            db,
            JobSourceCreate(
                job_id=job_id,
                url="https://example.com/job/999",
                source_name="test_source",
                source_type="portal",
                first_seen_at=ts,
                last_seen_at=ts,
                source_job_id="999",
            ),
        )

        # Neuen ScrapedJob mit gleicher source_job_id einreichen
        scraped = ScrapedJob(
            title="Test Job (leicht anders)",
            company_name="Test Firma",
            url="https://example.com/job/999?ref=new",
            source_job_id="999",
        )
        result = await _FakeScraper()._process_job(db, scraped)
        assert result == "duplicate"
        break


async def test_mark_expired_jobs(tmp_db: Path) -> None:
    """mark_expired_jobs: Jobs mit abgelaufener Deadline werden deaktiviert."""
    from app.db.database import get_db, init_db
    from app.db.models import JobCreate, now_iso
    from app.db.queries import insert_job, mark_expired_jobs

    await init_db(tmp_db)
    ts = now_iso()

    async for db in get_db(tmp_db):
        # Job mit abgelaufener Deadline
        await insert_job(
            db,
            JobCreate(
                canonical_id="expired-job",
                title="Abgelaufene Stelle",
                deadline="2020-01-01T00:00:00Z",
                first_seen_at=ts,
                last_seen_at=ts,
            ),
        )
        # Job ohne Deadline
        await insert_job(
            db,
            JobCreate(
                canonical_id="no-deadline-job",
                title="Stelle ohne Frist",
                deadline=None,
                first_seen_at=ts,
                last_seen_at=ts,
            ),
        )
        # Job mit zukünftiger Deadline
        await insert_job(
            db,
            JobCreate(
                canonical_id="future-deadline-job",
                title="Zukünftige Stelle",
                deadline="2099-12-31T23:59:00Z",
                first_seen_at=ts,
                last_seen_at=ts,
            ),
        )

        count = await mark_expired_jobs(db)
        assert count == 1  # nur "Abgelaufene Stelle"

        rows = await db.execute_fetchall(
            "SELECT canonical_id, is_active, status FROM jobs WHERE deadline IS NOT NULL"
        )
        expired = {r["canonical_id"]: r for r in rows}
        assert expired["expired-job"]["is_active"] == 0
        assert expired["expired-job"]["status"] == "expired"
        assert expired["future-deadline-job"]["is_active"] == 1
        assert expired["future-deadline-job"]["status"] == "new"
        break


async def test_mark_expired_jobs_skips_active_applications(tmp_db: Path) -> None:
    """mark_expired_jobs überspringt Jobs im Bewerbungsprozess."""
    from app.db.database import get_db, init_db
    from app.db.models import JobCreate, now_iso
    from app.db.queries import insert_job, mark_expired_jobs

    await init_db(tmp_db)
    ts = now_iso()

    async for db in get_db(tmp_db):
        job_id = await insert_job(
            db,
            JobCreate(
                canonical_id="applying-job",
                title="Bewerbung läuft",
                deadline="2020-01-01T00:00:00Z",
                status="applying",
                first_seen_at=ts,
                last_seen_at=ts,
            ),
        )
        count = await mark_expired_jobs(db)
        assert count == 0  # Job im Bewerbungsprozess bleibt unberührt

        rows = await db.execute_fetchall("SELECT status FROM jobs WHERE id = ?", (job_id,))
        assert rows[0]["status"] == "applying"
        break
