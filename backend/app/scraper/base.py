"""Basis-Scraper: abstrakte Klasse, ScrapedJob-Modell und gemeinsame Logik."""

import hashlib
import logging
import re
import unicodedata
from abc import ABC, abstractmethod

import aiosqlite
from pydantic import BaseModel

from app.db.models import CompanyCreate, JobCreate, JobSourceCreate, ScrapeRunStats, now_iso
from app.db.queries import (
    create_scrape_run,
    finish_scrape_run,
    get_all_job_titles_for_company,
    get_job_by_canonical_id,
    get_job_by_source_job_id,
    insert_job,
    insert_job_source,
    update_job_last_seen,
    update_job_raw_text,
    upsert_company,
)

logger = logging.getLogger(__name__)

# Fuzzy-Match-Schwellwert: Titel-Ähnlichkeit > 85% bei gleicher Firma → Duplikat
_FUZZY_THRESHOLD = 0.85


# ─── Zwischen-Modell ──────────────────────────────────────────────────────────


class ScrapedJob(BaseModel):
    """Rohdaten eines gescrapten Jobs — vor DB-Verarbeitung.

    Subklassen befüllen dieses Modell; die Basis-Klasse übernimmt
    Company-Upsert, Deduplication und DB-Insert.
    """

    title: str
    company_name: str
    location_raw: str | None = None
    work_model: str | None = None
    url: str
    published_at: str | None = None
    deadline: str | None = None
    salary_raw: str | None = None
    raw_text: str | None = None
    source_job_id: str | None = None  # Quell-native ID für Stage-0-Dedup
    sector: str | None = None  # 'public'|'private'|None


# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────


def normalize_text(text: str) -> str:
    """Normalisiert Text für canonical_id-Berechnung.

    - Unicode NFC
    - Lowercase, Strip
    - Satzzeichen entfernen
    - Mehrfache Leerzeichen kollabieren
    """
    text = unicodedata.normalize("NFC", text)
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _strip_plz(location: str) -> str:
    """Entfernt führende PLZ damit quell-übergreifend gleich normalisiert wird.

    Beispiele:
      '34117 Kassel'  → 'Kassel'
      '80331 München' → 'München'
      'Kassel'        → 'Kassel'  (unverändert)
    """
    return re.sub(r"^\d{4,5}\s+", "", location)


def compute_canonical_id(title: str, company: str, location: str) -> str:
    """SHA256(norm_title|norm_company|norm_location_ohne_PLZ)."""
    key = (
        f"{normalize_text(title)}|{normalize_text(company)}|{normalize_text(_strip_plz(location))}"
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _fuzzy_ratio(a: str, b: str) -> float:
    """Ähnlichkeitsmaß via difflib.SequenceMatcher (0.0–1.0)."""
    from difflib import SequenceMatcher

    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


# ─── Basis-Klasse ─────────────────────────────────────────────────────────────


class BaseScraper(ABC):
    """Abstrakte Basis für alle Scraper-Typen (A, B, C).

    Subklassen implementieren `fetch_jobs` und setzen `source_name`/`source_type`.
    Die Template-Method `run` übernimmt Company-Upsert, Deduplication,
    DB-Insert und Scrape-Run-Logging.
    """

    source_name: str
    source_type: str  # 'aggregator'|'portal'|'direct'|'ats'

    @abstractmethod
    async def fetch_jobs(self) -> list[ScrapedJob]:
        """Holt rohe Job-Daten aus der Quelle.

        Noch keine Deduplication — das übernimmt `run`.
        """
        ...

    async def run(self, db: aiosqlite.Connection, run_id: int | None = None) -> ScrapeRunStats:
        """Template-Method: vollständiger Scraping-Durchlauf.

        Wenn run_id übergeben wird (z.B. vom API-Endpoint), wird dieser Run
        verwendet und am Ende abgeschlossen. Andernfalls wird ein neuer Run erstellt
        (nützlich für standalone-Aufrufe / Tests).
        """
        owns_run = run_id is None
        effective_run_id: int
        if owns_run:
            effective_run_id = await create_scrape_run(db)
        else:
            assert run_id is not None
            effective_run_id = run_id
        stats = ScrapeRunStats()
        error_log: list[str] = []

        try:
            raw_jobs = await self.fetch_jobs()
            stats.fetched = len(raw_jobs)
            logger.info("[%s] %d Jobs geholt", self.source_name, stats.fetched)

            for scraped in raw_jobs:
                try:
                    result = await self._process_job(db, scraped)
                    if result == "new":
                        stats.new += 1
                    elif result == "duplicate":
                        stats.duplicate += 1
                    else:
                        stats.skipped += 1
                except Exception as exc:  # noqa: BLE001
                    stats.errors += 1
                    msg = f"Fehler bei Job '{scraped.title}': {exc}"
                    logger.warning(msg)
                    error_log.append(msg)

        except Exception as exc:  # noqa: BLE001
            msg = f"Scraper-Fehler [{self.source_name}]: {exc}"
            logger.error(msg)
            error_log.append(msg)
            if owns_run:
                await finish_scrape_run(
                    db, effective_run_id, stats, [self.source_name], error_log, status="failed"
                )
            raise

        if owns_run:
            await finish_scrape_run(
                db, effective_run_id, stats, [self.source_name], error_log or None
            )
        logger.info(
            "[%s] Fertig: %d neu, %d Duplikat, %d übersprungen, %d Fehler",
            self.source_name,
            stats.new,
            stats.duplicate,
            stats.skipped,
            stats.errors,
        )
        return stats

    async def _process_job(self, db: aiosqlite.Connection, scraped: ScrapedJob) -> str:
        """Verarbeitet einen einzelnen Job.

        Flow:
        1. Company-Upsert (immer — Firma muss bekannt sein)
        2. Stage 0 Dedup — Source-Job-ID-Match (innerhalb einer Quelle):
           - Treffer → last_seen_at updaten + Source-URL upserten → 'duplicate'
        3. Stage 1 Dedup — canonical_id Hash-Match:
           - Job existiert → last_seen_at updaten + Source-URL upserten → 'duplicate'
        4. Stage 2 Dedup — Fuzzy-Match:
           - Ähnlicher Titel + gleiche Firma → 'duplicate'
        5. Neu → Job + Source einfügen → 'new'

        Gibt zurück: 'new' | 'duplicate' | 'skipped'
        """
        ts = now_iso()

        # 1. Company-Upsert
        company_id = await upsert_company(
            db,
            CompanyCreate(
                name=scraped.company_name,
                name_normalized=normalize_text(scraped.company_name),
            ),
        )

        # 2. Stage 0 — Source-Job-ID-Match (schnellster Pfad, nur wenn ID bekannt)
        if scraped.source_job_id:
            existing = await get_job_by_source_job_id(db, self.source_name, scraped.source_job_id)
            if existing:
                logger.debug(
                    "Duplikat (source_job_id=%s): %s @ %s",
                    scraped.source_job_id,
                    scraped.title,
                    scraped.company_name,
                )
                await update_job_last_seen(db, existing.id, ts)
                # Fülle raw_text nach, falls bestehender Job keine hat
                if scraped.raw_text and not existing.raw_text:
                    await update_job_raw_text(db, existing.id, scraped.raw_text)
                    logger.debug(
                        "[%s] raw_text nachgefüllt für job_id=%d",
                        self.source_name,
                        existing.id,
                    )
                await insert_job_source(
                    db,
                    JobSourceCreate(
                        job_id=existing.id,
                        url=scraped.url,
                        source_name=self.source_name,
                        source_type=self.source_type,
                        is_canonical=False,
                        first_seen_at=ts,
                        last_seen_at=ts,
                        source_job_id=scraped.source_job_id,
                    ),
                )
                return "duplicate"

        canonical_id = compute_canonical_id(
            scraped.title,
            scraped.company_name,
            scraped.location_raw or "",
        )

        # 3. Stage 1 — Hash-Match
        existing = await get_job_by_canonical_id(db, canonical_id)
        if existing:
            logger.debug("Duplikat (Hash): %s @ %s", scraped.title, scraped.company_name)
            await update_job_last_seen(db, existing.id, ts)
            # Fülle raw_text nach, falls bestehender Job keine hat
            if scraped.raw_text and not existing.raw_text:
                await update_job_raw_text(db, existing.id, scraped.raw_text)
                logger.debug(
                    "[%s] raw_text nachgefüllt für job_id=%d",
                    self.source_name,
                    existing.id,
                )
            await insert_job_source(
                db,
                JobSourceCreate(
                    job_id=existing.id,
                    url=scraped.url,
                    source_name=self.source_name,
                    source_type=self.source_type,
                    is_canonical=False,
                    first_seen_at=ts,
                    last_seen_at=ts,
                    source_job_id=scraped.source_job_id,
                ),
            )
            return "duplicate"

        # 4. Stage 2 — Fuzzy-Match: gleiche Firma, ähnlicher Titel
        existing_titles = await get_all_job_titles_for_company(db, company_id)
        for existing_title in existing_titles:
            if _fuzzy_ratio(scraped.title, existing_title) >= _FUZZY_THRESHOLD:
                logger.debug("Duplikat (Fuzzy): '%s' ≈ '%s'", scraped.title, existing_title)
                return "duplicate"

        # 5. Neuen Job einfügen
        job_id = await insert_job(
            db,
            JobCreate(
                canonical_id=canonical_id,
                title=scraped.title,
                company_id=company_id,
                location_raw=scraped.location_raw,
                work_model=scraped.work_model,
                salary_raw=scraped.salary_raw,
                deadline=scraped.deadline,
                first_seen_at=ts,
                last_seen_at=ts,
                raw_text=scraped.raw_text,
                sector=scraped.sector,
            ),
        )

        # 6. Quelle einfügen
        await insert_job_source(
            db,
            JobSourceCreate(
                job_id=job_id,
                url=scraped.url,
                source_name=self.source_name,
                source_type=self.source_type,
                is_canonical=False,
                first_seen_at=ts,
                last_seen_at=ts,
                source_job_id=scraped.source_job_id,
            ),
        )

        logger.debug("Neu: %s @ %s", scraped.title, scraped.company_name)
        return "new"
