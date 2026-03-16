"""Bundesagentur für Arbeit — REST-API-Scraper (Typ A).

Offizielle öffentliche API der Bundesagentur für Arbeit (Jobsuche).

API-Dokumentation:
  https://jobsuche.api.bund.dev/

Endpoint:
  GET https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs

Authentifizierung:
  Header: X-API-Key: jobboerse-jobsuche  (öffentlicher Key, keine Registrierung nötig)

Rate-Limit: 1.000 Requests/Stunde.
"""

import asyncio
import logging

import httpx

from app.core.config import settings
from app.scraper.base import BaseScraper, ScrapedJob

logger = logging.getLogger(__name__)

_BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
_DETAIL_URL_TEMPLATE = (
    "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/stelle/{refnr}"
)
_JOB_URL_TEMPLATE = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
_API_KEY = "jobboerse-jobsuche"
_PAGE_SIZE = 100
_DETAIL_SLEEP = 0.5  # Sekunden zwischen Detail-Requests

# ─── Hilfsfunktionen (rein, testbar ohne HTTP) ────────────────────────────────


def _build_job_url(refnr: str) -> str:
    """Baut die Detail-URL für ein Stellenangebot."""
    return _JOB_URL_TEMPLATE.format(refnr=refnr)


def _parse_published_at(date_str: str | None) -> str | None:
    """Konvertiert YYYY-MM-DD zu ISO-8601 UTC-Zeitstempel."""
    if not date_str:
        return None
    # Einfaches Datum ohne Uhrzeit → Mitternacht UTC
    if "T" not in date_str and len(date_str) == 10:
        return f"{date_str}T00:00:00Z"
    return date_str


def _parse_stellenangebot(s: dict[str, object]) -> ScrapedJob | None:
    """Wandelt ein API-Response-Objekt in ein ScrapedJob um."""
    titel = s.get("titel")
    if not titel or not isinstance(titel, str):
        return None

    refnr = s.get("refnr")
    if not refnr or not isinstance(refnr, str):
        return None

    arbeitgeber = s.get("arbeitgeber")
    company = arbeitgeber if isinstance(arbeitgeber, str) else "Unbekannt"

    arbeitsort = s.get("arbeitsort")
    location_raw: str | None = None
    if isinstance(arbeitsort, dict):
        ort = arbeitsort.get("ort")
        plz = arbeitsort.get("plz")
        if ort and isinstance(ort, str):
            location_raw = f"{plz} {ort}".strip() if plz and isinstance(plz, str) else ort

    raw_date = s.get("aktuelleVeroeffentlichungsdatum")
    published_at = _parse_published_at(raw_date if isinstance(raw_date, str) else None)

    beruf = s.get("beruf")
    sector = beruf if isinstance(beruf, str) else None

    return ScrapedJob(
        title=titel,
        company_name=company,
        location_raw=location_raw,
        url=_build_job_url(refnr),
        published_at=published_at,
        source_job_id=refnr,
        sector=sector,
    )


async def _fetch_stellenbeschreibung(client: httpx.AsyncClient, refnr: str) -> str | None:
    """Fetcht die Volltext-Beschreibung eines Stellenangebots via BA-Detail-API."""
    url = _DETAIL_URL_TEMPLATE.format(refnr=refnr)
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
        beschreibung = data.get("stellenbeschreibung")
        if isinstance(beschreibung, str) and beschreibung.strip():
            return beschreibung.strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[arbeitsagentur] Detail-Fehler %s: %s", refnr, exc)
    return None


# ─── Scraper-Klasse ────────────────────────────────────────────────────────────


class ArbeitsagenturScraper(BaseScraper):
    """Bundesagentur für Arbeit REST-API-Scraper (Typ A).

    Paginiert die Jobsuche-API vollständig durch.
    Kein künstliches Limit — alle verfügbaren Jobs werden abgerufen.
    """

    source_name = "arbeitsagentur"
    source_type = "portal"

    async def fetch_jobs(self) -> list[ScrapedJob]:
        """Fetcht alle Jobs via BA-Jobsuche-API."""
        params: dict[str, str | int] = {
            "wo": settings.home_address,
            "umkreis": settings.scrape_radius_km,
            "veroeffentlichtseit": settings.scrape_posted_within_days or 30,
            "angebotsart": 1,  # nur Arbeitsstellen (keine Praktika/Ausbildung)
            "pav": "false",  # keine Personalvermittler
            "size": _PAGE_SIZE,
        }

        jobs: list[ScrapedJob] = []
        page = 1
        total: int | None = None

        async with httpx.AsyncClient(
            headers={"X-API-Key": _API_KEY},
            timeout=30.0,
        ) as client:
            while True:
                try:
                    resp = await client.get(_BASE_URL, params={**params, "page": page})
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[arbeitsagentur] API-Fehler (Seite %d): %s", page, exc)
                    break

                stellenangebote = data.get("stellenangebote") or []
                if not stellenangebote:
                    break

                if total is None:
                    total = int(data.get("maxErgebnisse", 0))
                    logger.info("[arbeitsagentur] Gesamt verfügbar: %d Jobs", total)

                page_jobs: list[ScrapedJob] = []
                for s in stellenangebote:
                    if isinstance(s, dict):
                        job = _parse_stellenangebot(s)
                        if job is not None:
                            page_jobs.append(job)

                # Detail-Fetch für Volltext
                for job in page_jobs:
                    if job.source_job_id:
                        job.raw_text = await _fetch_stellenbeschreibung(client, job.source_job_id)
                        await asyncio.sleep(_DETAIL_SLEEP)

                jobs.extend(page_jobs)
                page_count = len(page_jobs)
                logger.debug("[arbeitsagentur] Seite %d: %d Jobs", page, page_count)

                if len(jobs) >= (total or 0):
                    break

                page += 1
                await asyncio.sleep(0.3)  # Rate-Limit respektieren

        logger.info("[arbeitsagentur] Gesamt geholt: %d Jobs", len(jobs))
        return jobs
