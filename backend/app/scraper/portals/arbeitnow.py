"""Arbeitnow API-Scraper.

Kostenlose, offene Job-API mit Volltext-Beschreibungen.
Schwerpunkt: Tech- und englischsprachige Stellen in Deutschland.

API: https://www.arbeitnow.com/api/job-board-api
Auth: Keine.
Volltext: Ja (HTML in `description`).
Pagination: `links.next` in Response.
Datumsfilter: Client-seitig über Unix-Timestamp `created_at`.
Ortsfilter: Client-seitig über `remote` + `location`.
"""

import asyncio
import html
import logging
from datetime import UTC, datetime

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.scraper.base import BaseScraper, ScrapedJob

logger = logging.getLogger(__name__)

_API_URL = "https://www.arbeitnow.com/api/job-board-api"
_MAX_RETRIES = 3
_DEFAULT_RETRY_WAIT = 60  # Sekunden (Fallback wenn kein Retry-After-Header)


def _strip_html(raw_html: str) -> str:
    """Entfernt HTML-Tags und normalisiert Whitespace."""
    text = BeautifulSoup(html.unescape(raw_html), "html.parser").get_text(separator=" ")
    return " ".join(text.split())


def _is_location_match(location: str, remote: bool) -> bool:
    """Gibt True zurück wenn der Job zu einem der konfigurierten Standorte passt."""
    if remote:
        return True
    loc_lower = location.lower()
    return any(target.lower() in loc_lower for target in settings.scrape_locations)


def _parse_job(entry: dict[str, object]) -> ScrapedJob | None:
    """Konvertiert einen API-Eintrag in ein ScrapedJob."""
    title = entry.get("title")
    if not title or not isinstance(title, str):
        return None

    url = entry.get("url")
    if not url or not isinstance(url, str):
        return None

    slug = entry.get("slug")
    source_job_id = slug if isinstance(slug, str) else None

    company = entry.get("company_name")
    company_name = company if isinstance(company, str) else "Unbekannt"

    location = entry.get("location") or ""
    location_str = location if isinstance(location, str) else ""

    remote = bool(entry.get("remote", False))
    work_model = "remote" if remote else None

    description = entry.get("description") or ""
    raw_text = _strip_html(description) if isinstance(description, str) else None

    created_at = entry.get("created_at")
    published_at: str | None = None
    if isinstance(created_at, int):
        published_at = (
            datetime.fromtimestamp(created_at, tz=UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

    return ScrapedJob(
        title=title,
        company_name=company_name,
        location_raw=location_str or None,
        url=url,
        published_at=published_at,
        raw_text=raw_text,
        source_job_id=source_job_id,
        work_model=work_model,
        sector=None,
    )


class ArbeitnowScraper(BaseScraper):
    """Arbeitnow API-Scraper.

    Holt alle Jobs aus dem öffentlichen Feed und filtert lokal nach
    Datum und Standort / Remote-Flag.
    """

    source_name = "arbeitnow"
    source_type = "aggregator"

    async def fetch_jobs(self) -> list[ScrapedJob]:
        """Fetcht alle passenden Jobs aus der Arbeitnow-API."""
        max_days = settings.scrape_posted_within_days
        cutoff = datetime.now(tz=UTC).timestamp() - max_days * 86_400

        jobs: list[ScrapedJob] = []
        next_url: str | None = _API_URL
        page = 0

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            retries = 0
            while next_url:
                try:
                    resp = await client.get(next_url)
                    resp.raise_for_status()
                    data = resp.json()
                    retries = 0  # Reset nach Erfolg
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 429 and retries < _MAX_RETRIES:
                        wait = int(exc.response.headers.get("Retry-After", _DEFAULT_RETRY_WAIT))
                        retries += 1
                        logger.info(
                            "[arbeitnow] Rate-Limit (429), warte %ds (Versuch %d/%d)",
                            wait,
                            retries,
                            _MAX_RETRIES,
                        )
                        await asyncio.sleep(wait)
                        continue  # gleiche URL nochmal versuchen
                    logger.warning("[arbeitnow] HTTP-Fehler (Seite %d): %s", page, exc)
                    break
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[arbeitnow] Fehler (Seite %d): %s", page, exc)
                    break

                page += 1
                entries = data.get("data") or []
                if not entries:
                    break

                page_jobs = 0
                date_exhausted = False
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue

                    # Datumsfilter: ältere Einträge → Feed ist sortiert → abbrechen
                    created_at = entry.get("created_at")
                    if isinstance(created_at, int) and created_at < cutoff:
                        date_exhausted = True
                        continue

                    location = entry.get("location") or ""
                    remote = bool(entry.get("remote", False))
                    if not _is_location_match(str(location), remote):
                        continue

                    job = _parse_job(entry)
                    if job is not None:
                        jobs.append(job)
                        page_jobs += 1

                logger.debug("[arbeitnow] Seite %d: %d neue Jobs", page, page_jobs)

                # Feed läuft von neu → alt; sobald alle Einträge der Seite zu alt → stop
                if date_exhausted and page_jobs == 0:
                    break

                links = data.get("links") or {}
                next_url = links.get("next") if isinstance(links, dict) else None
                if next_url:
                    await asyncio.sleep(1.0)

        logger.info("[arbeitnow] Gesamt: %d Jobs", len(jobs))
        return jobs
