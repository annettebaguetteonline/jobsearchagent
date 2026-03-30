"""Scraping-API: Scrape-Run starten, Status abfragen und abbrechen."""

import asyncio
import json
import logging
import threading

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

# Aktive Cancel-Events pro Run-ID (nur für laufende Runs)
_cancel_events: dict[int, threading.Event] = {}

# ─── Request / Response-Modelle ───────────────────────────────────────────────


class ScrapeStartRequest(BaseModel):
    sources: list[str] | None = None  # None = alle konfigurierten Quellen


class ScrapeStartResponse(BaseModel):
    run_id: int
    status: str = "started"
    sources: list[str]


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/sources")
async def list_sources() -> dict[str, list[str]]:
    """Gibt die verfügbaren Scraper-Quellen zurück."""
    return {"sources": list(_SCRAPERS.keys())}


@router.post("/start", response_model=ScrapeStartResponse)
async def start_scrape(
    request: ScrapeStartRequest,
    background_tasks: BackgroundTasks,
) -> ScrapeStartResponse:
    """Startet einen Scraping-Durchlauf im Hintergrund.

    Kehrt sofort mit der run_id zurück — Status über GET /scrape/runs/{run_id} abfragen.
    Der Scraper läuft in einem eigenen Thread, sodass die API während des Scans
    weiterhin antwortfähig bleibt.
    """
    sources = _resolve_sources(request.sources)

    async for db in get_db():
        run_id = await create_scrape_run(db)
        break

    cancel_event = threading.Event()
    _cancel_events[run_id] = cancel_event

    # Sync-Wrapper → Starlette führt ihn in einem ThreadPoolExecutor aus,
    # sodass der asyncio Event-Loop des Servers frei bleibt.
    background_tasks.add_task(_run_in_new_loop, run_id, sources, cancel_event)
    logger.info("Scrape-Run %d gestartet: %s", run_id, sources)

    return ScrapeStartResponse(run_id=run_id, sources=sources)


@router.post("/runs/{run_id}/cancel")
async def cancel_scrape(run_id: int) -> dict[str, str]:
    """Bricht einen laufenden Scrape-Run ab.

    Setzt das Cancel-Flag — der laufende Scraper beendet die aktuelle Quelle
    und startet keine weiteren. Status wechselt zu 'cancelled'.
    """
    event = _cancel_events.get(run_id)
    if event is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Kein aktiver Scrape-Run {run_id} gefunden (bereits beendet oder nie gestartet)"
            ),
        )
    event.set()
    logger.info("Cancel-Signal für Scrape-Run %d gesetzt", run_id)
    return {"status": "cancelling"}


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


# ─── Thread-Wrapper ───────────────────────────────────────────────────────────


def _run_in_new_loop(run_id: int, sources: list[str], cancel_event: threading.Event) -> None:
    """Synchroner Einstiegspunkt — wird von Starletttes ThreadPoolExecutor aufgerufen.

    Erstellt einen eigenen asyncio Event-Loop für den Scraper-Thread, sodass
    CPU-intensive Operationen (HTML-Parsing, Fuzzy-Matching) den FastAPI
    Event-Loop nicht blockieren.
    """
    asyncio.run(_run_scrapers(run_id, sources, cancel_event))


# ─── Background-Task ──────────────────────────────────────────────────────────


async def _run_scrapers(run_id: int, sources: list[str], cancel_event: threading.Event) -> None:
    """Führt alle angeforderten Scraper sequenziell aus.

    - Prüft zwischen jeder Quelle ob ein Cancel-Signal gesetzt wurde.
    - Aktualisiert sources_run nach jeder abgeschlossenen Quelle (Fortschritts-Tracking).
    - Setzt Status auf 'cancelled', 'failed' oder 'finished'.
    """
    combined = ScrapeRunStats()
    error_log: list[str] = []
    completed_sources: list[str] = []

    async for db in get_db():
        for source_name in sources:
            if cancel_event.is_set():
                logger.info(
                    "Scrape-Run %d: Cancel-Signal erkannt, stoppe nach %s",
                    run_id,
                    completed_sources,
                )
                break

            scraper = _SCRAPERS[source_name]()
            if source_name == "kimeta":
                known = await get_known_source_job_ids(db, "kimeta")
                scraper.known_job_ids = frozenset(known)
            try:
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

            completed_sources.append(source_name)
            # Fortschritts-Update: abgeschlossene Quellen sofort in DB schreiben
            await db.execute(
                "UPDATE scrape_runs SET sources_run = ? WHERE id = ?",
                (json.dumps(completed_sources), run_id),
            )
            await db.commit()

        # Abgelaufene Stellen nur markieren wenn nicht vorzeitig abgebrochen
        if not cancel_event.is_set():
            combined.expired = await mark_expired_jobs(db)
            if combined.expired:
                logger.info(
                    "Scrape-Run %d: %d Stellen als abgelaufen markiert", run_id, combined.expired
                )

        cancelled = cancel_event.is_set()
        if cancelled:
            final_status = "cancelled"
        elif error_log and combined.new == 0:
            final_status = "failed"
        else:
            final_status = "finished"

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

    # Cleanup: Cancel-Event entfernen
    _cancel_events.pop(run_id, None)

    logger.info(
        "Scrape-Run %d abgeschlossen (%s): %d neu, %d Duplikate, %d/%d Quellen",
        run_id,
        final_status,
        combined.new,
        combined.duplicate,
        len(completed_sources),
        len(sources),
    )
