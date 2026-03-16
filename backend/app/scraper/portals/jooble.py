"""Jooble API-Scraper.

Großer Job-Aggregator (67+ Länder). Liefert nur Snippets (~200-300 Zeichen),
kein Volltext — ausreichend für Stage-1-Filterung.

API: POST https://jooble.org/api/{api_key}
Auth: API-Key in URL (kostenlos: https://jooble.org/api/about).
Datumsfilter: Kein nativer Parameter — client-seitig über `updated`-Feld.
Volltext: Nein (nur `snippet`).

Secrets (Docker):
  infrastructure/secrets/jooble_api_key.txt
"""

import asyncio
import logging
from datetime import UTC, datetime

import httpx

from app.core.config import settings
from app.scraper.base import BaseScraper, ScrapedJob

logger = logging.getLogger(__name__)

_BASE_URL = "https://jooble.org/api/{api_key}"


def _parse_updated(updated_str: str | None) -> str | None:
    """Konvertiert Jooble-Datumsformat → ISO-8601 UTC.

    Format: '2025-12-01T00:00:00.0000000' (ohne Zeitzone → als UTC behandeln).
    """
    if not updated_str:
        return None
    # Trunkieren auf Sekunden
    raw = updated_str[:19]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)  # noqa: DTZ007
            return dt.replace(tzinfo=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        except ValueError:
            continue
    return None


def _is_recent(updated_str: str | None, max_days: int) -> bool:
    """Gibt True zurück wenn der Job nicht älter als max_days ist."""
    if not updated_str or max_days <= 0:
        return True
    iso = _parse_updated(updated_str)
    if not iso:
        return True
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(tz=UTC) - dt).days <= max_days
    except Exception:  # noqa: BLE001
        return True


def _parse_job(entry: dict[str, object]) -> ScrapedJob | None:
    """Konvertiert einen Jooble-Eintrag in ein ScrapedJob."""
    title = entry.get("title")
    if not title or not isinstance(title, str):
        return None

    url = entry.get("link")
    if not url or not isinstance(url, str):
        return None

    job_id = entry.get("id")
    source_job_id = str(job_id) if job_id is not None else None

    company = entry.get("company") or ""
    company_name = company if isinstance(company, str) and company else "Unbekannt"

    location = entry.get("location") or ""
    location_raw = location if isinstance(location, str) and location else None

    snippet = entry.get("snippet") or ""
    raw_text = snippet if isinstance(snippet, str) and snippet else None

    salary = entry.get("salary") or ""
    salary_raw = salary if isinstance(salary, str) and salary else None

    updated = entry.get("updated")
    published_at = _parse_updated(updated if isinstance(updated, str) else None)

    return ScrapedJob(
        title=title.strip(),
        company_name=company_name,
        location_raw=location_raw,
        url=url,
        published_at=published_at,
        raw_text=raw_text,
        source_job_id=source_job_id,
        salary_raw=salary_raw,
        sector=None,
    )


class JoobleScraper(BaseScraper):
    """Jooble API-Scraper.

    Überspringt Ausführung wenn jooble_api_key nicht konfiguriert.
    Registrierung: https://jooble.org/api/about
    """

    source_name = "jooble"
    source_type = "aggregator"

    async def fetch_jobs(self) -> list[ScrapedJob]:
        """Fetcht Jobs über die Jooble-API."""
        api_key = settings.jooble_api_key

        if not api_key:
            logger.warning(
                "[jooble] API-Key fehlt — Scraper übersprungen. "
                "infrastructure/secrets/jooble_api_key.txt anlegen."
            )
            return []

        location = settings.scrape_locations[0] if settings.scrape_locations else "Frankfurt"
        max_days = settings.scrape_posted_within_days or 7

        base_body: dict[str, str] = {
            "location": location,
            "radius": str(settings.scrape_radius_km),
        }

        jobs: list[ScrapedJob] = []
        page = 1
        api_url = _BASE_URL.format(api_key=api_key)

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            while True:
                body = {**base_body, "page": str(page)}
                try:
                    resp = await client.post(api_url, json=body)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[jooble] API-Fehler (Seite %d): %s", page, exc)
                    break

                entries = data.get("jobs") or []
                if not entries:
                    break

                page_jobs = 0
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    updated = entry.get("updated")
                    if not _is_recent(updated if isinstance(updated, str) else None, max_days):
                        continue
                    job = _parse_job(entry)
                    if job is not None:
                        jobs.append(job)
                        page_jobs += 1

                logger.debug("[jooble] Seite %d: %d Jobs", page, page_jobs)

                if not entries:
                    break

                page += 1
                await asyncio.sleep(1.0)

        logger.info("[jooble] Gesamt: %d Jobs", len(jobs))
        return jobs
