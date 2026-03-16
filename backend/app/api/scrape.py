"""Scraping-API: Scrape-Run starten und Status abfragen."""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.db.database import get_db
from app.db.models import ScrapeRun, ScrapeRunStats, now_iso
from app.db.queries import (
    create_scrape_run,
    get_known_source_job_ids,
    get_scrape_run,
    mark_expired_jobs,
)
from app.scraper.portals.adzuna import AdzunaScraper
from app.scraper.portals.arbeitnow import ArbeitnowScraper
from app.scraper.portals.arbeitsagentur import ArbeitsagenturScraper
from app.scraper.portals.interamt import InteramtScraper
from app.scraper.portals.jobboerse import JobboerseScraper
from app.scraper.portals.jooble import JoobleScraper
from app.scraper.portals.kimeta import KimetaScraper
from app.scraper.portals.service_bund import ServiceBundScraper
from app.scraper.portals.stellenmarkt import StellenmarktScraper

logger = logging.getLogger(__name__)

router = APIRouter()

# ─── Scraper-Registry ─────────────────────────────────────────────────────────

_SCRAPERS: dict[str, type] = {
    "service_bund": ServiceBundScraper,
    "arbeitsagentur": ArbeitsagenturScraper,
    "interamt": InteramtScraper,
    "arbeitnow": ArbeitnowScraper,
    "stellenmarkt": StellenmarktScraper,
    "adzuna": AdzunaScraper,
    "jooble": JoobleScraper,
    "jobboerse": JobboerseScraper,
    "kimeta": KimetaScraper,
}

# ─── Request / Response-Modelle ───────────────────────────────────────────────


class ScrapeStartRequest(BaseModel):
    sources: list[str] | None = None  # None = alle konfigurierten Quellen


class ScrapeStartResponse(BaseModel):
    run_id: int
    status: str = "started"
    sources: list[str]


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/start", response_model=ScrapeStartResponse)
async def start_scrape(
    request: ScrapeStartRequest,
    background_tasks: BackgroundTasks,
) -> ScrapeStartResponse:
    """Startet einen Scraping-Durchlauf im Hintergrund.

    Kehrt sofort mit der run_id zurück — Status über GET /scrape/runs/{run_id} abfragen.
    Typischer Aufruf: `curl -X POST /api/scrape/start`
    """
    sources = _resolve_sources(request.sources)

    async for db in get_db():
        run_id = await create_scrape_run(db)
        await db.execute(
            "UPDATE scrape_runs SET sources_run = ? WHERE id = ?",
            (json.dumps(sources), run_id),
        )
        await db.commit()
        break

    background_tasks.add_task(_run_scrapers, run_id, sources)
    logger.info("Scrape-Run %d gestartet: %s", run_id, sources)

    return ScrapeStartResponse(run_id=run_id, sources=sources)


@router.get("/runs/{run_id}", response_model=ScrapeRun)
async def get_run(run_id: int) -> ScrapeRun:
    """Gibt den Status und die Statistiken eines Scrape-Runs zurück."""
    async for db in get_db():
        run = await get_scrape_run(db, run_id)
        break

    if run is None:
        raise HTTPException(status_code=404, detail=f"Scrape-Run {run_id} nicht gefunden")
    return run


# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────


def _resolve_sources(requested: list[str] | None) -> list[str]:
    """Gibt die zu verwendenden Quellen zurück (Default: alle registrierten)."""
    if requested:
        unknown = set(requested) - _SCRAPERS.keys()
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unbekannte Quellen: {sorted(unknown)}. "
                f"Verfügbar: {sorted(_SCRAPERS.keys())}",
            )
        return list(requested)
    return list(_SCRAPERS.keys())


# ─── Background-Task ──────────────────────────────────────────────────────────


async def _run_scrapers(run_id: int, sources: list[str]) -> None:
    """Führt alle angeforderten Scraper sequenziell aus.

    Verwendet den bereits angelegten run_id — kein doppelter DB-Eintrag.
    """
    combined = ScrapeRunStats()
    error_log: list[str] = []
    final_status = "finished"

    async for db in get_db():
        for source_name in sources:
            scraper = _SCRAPERS[source_name]()
            if source_name == "kimeta":
                known = await get_known_source_job_ids(db, "kimeta")
                scraper.known_job_ids = frozenset(known)
            try:
                # run_id übergeben → kein neuer Run wird innerhalb des Scrapers angelegt
                stats = await scraper.run(db, run_id=run_id)
                combined.fetched += stats.fetched
                combined.new += stats.new
                combined.duplicate += stats.duplicate
                combined.skipped += stats.skipped
                combined.errors += stats.errors
            except Exception as exc:  # noqa: BLE001
                msg = f"Scraper [{source_name}] fehlgeschlagen: {exc}"
                logger.error(msg)
                error_log.append(msg)

        # Abgelaufene Stellen markieren (deadline < now → is_active=0, status='expired')
        combined.expired = await mark_expired_jobs(db)
        if combined.expired:
            logger.info(
                "Scrape-Run %d: %d Stellen als abgelaufen markiert", run_id, combined.expired
            )

        final_status = "failed" if error_log and combined.new == 0 else "finished"
        await db.execute(
            """
            UPDATE scrape_runs
            SET finished_at = ?, status = ?, stats = ?, error_log = ?
            WHERE id = ?
            """,
            (
                now_iso(),
                final_status,
                json.dumps(combined.model_dump()),
                json.dumps(error_log) if error_log else None,
                run_id,
            ),
        )
        await db.commit()
        break

    logger.info(
        "Scrape-Run %d abgeschlossen (%s): %d neu, %d Duplikate",
        run_id,
        final_status,
        combined.new,
        combined.duplicate,
    )
