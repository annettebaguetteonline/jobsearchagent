"""Adzuna API-Scraper.

Breiter Job-Aggregator mit nativem max_days_old-Filter und Standortsuche.
Beschreibungen oft gekürzt (~200-500 Zeichen) — ausreichend für Stage-1-Filterung.

API: https://api.adzuna.com/v1/api/jobs/de/search/{page}
Auth: app_id + app_key (kostenlos auf developer.adzuna.com registrieren).
Rate-Limit: ~250 Requests/Tag, 25 Requests/Minute.
Paginierung: Seitenbasiert, max 50 Ergebnisse pro Seite.

Secrets (Docker):
  infrastructure/secrets/adzuna_app_id.txt
  infrastructure/secrets/adzuna_app_key.txt
"""

import asyncio
import logging

import httpx

from app.core.config import settings
from app.scraper.base import BaseScraper, ScrapedJob

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.adzuna.com/v1/api/jobs/de/search/{page}"
_PAGE_SIZE = 50


def _parse_job(entry: dict[str, object]) -> ScrapedJob | None:
    """Konvertiert einen Adzuna-API-Eintrag in ein ScrapedJob."""
    title = entry.get("title")
    if not title or not isinstance(title, str):
        return None

    url = entry.get("redirect_url")
    if not url or not isinstance(url, str):
        return None

    job_id = entry.get("id")
    source_job_id = str(job_id) if job_id is not None else None

    company_data = entry.get("company") or {}
    company_name = "Unbekannt"
    if isinstance(company_data, dict):
        name = company_data.get("display_name")
        if isinstance(name, str):
            company_name = name

    location_data = entry.get("location") or {}
    location_raw: str | None = None
    if isinstance(location_data, dict):
        display = location_data.get("display_name")
        if isinstance(display, str):
            location_raw = display

    description = entry.get("description") or ""
    raw_text = description if isinstance(description, str) and description else None

    published_at = entry.get("created")
    pub_str = published_at if isinstance(published_at, str) else None

    salary_min = entry.get("salary_min")
    salary_max = entry.get("salary_max")
    salary_raw: str | None = None
    if salary_min is not None and salary_max is not None:
        salary_raw = f"{int(salary_min):,} – {int(salary_max):,} EUR".replace(",", ".")  # type: ignore[call-overload]

    return ScrapedJob(
        title=title,
        company_name=company_name,
        location_raw=location_raw,
        url=url,
        published_at=pub_str,
        raw_text=raw_text,
        source_job_id=source_job_id,
        salary_raw=salary_raw,
        sector=None,
    )


class AdzunaScraper(BaseScraper):
    """Adzuna API-Scraper.

    Überspringt Ausführung wenn app_id/app_key nicht konfiguriert.
    Registrierung: https://developer.adzuna.com
    """

    source_name = "adzuna"
    source_type = "aggregator"

    async def fetch_jobs(self) -> list[ScrapedJob]:
        """Fetcht Jobs über die Adzuna-API."""
        app_id = settings.adzuna_app_id
        app_key = settings.adzuna_app_key

        if not app_id or not app_key:
            logger.warning(
                "[adzuna] API-Keys fehlen — Scraper übersprungen. "
                "infrastructure/secrets/adzuna_app_id.txt und adzuna_app_key.txt anlegen."
            )
            return []

        location = settings.scrape_locations[0] if settings.scrape_locations else "Frankfurt"
        max_days = settings.scrape_posted_within_days or 7

        params: dict[str, str | int] = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": _PAGE_SIZE,
            "max_days_old": max_days,
            "sort_by": "date",
            "where": location,
        }

        jobs: list[ScrapedJob] = []
        page = 1

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            while True:
                url = _BASE_URL.format(page=page)
                try:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[adzuna] API-Fehler (Seite %d): %s", page, exc)
                    break

                results = data.get("results") or []
                if not results:
                    break

                page_jobs = 0
                for entry in results:
                    if not isinstance(entry, dict):
                        continue
                    job = _parse_job(entry)
                    if job is not None:
                        jobs.append(job)
                        page_jobs += 1

                logger.debug("[adzuna] Seite %d: %d Jobs", page, page_jobs)

                # Stopp wenn weniger als eine volle Seite zurückgekommen ist
                if len(results) < _PAGE_SIZE:
                    break

                page += 1
                await asyncio.sleep(0.5)  # Rate-Limit: 25 req/min

        logger.info("[adzuna] Gesamt: %d Jobs", len(jobs))
        return jobs
