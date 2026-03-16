"""Jobbörse.de SSR-Scraper.

~1,2 Mio. aktive Stellenanzeigen. Server-seitig gerendert (kein JS nötig).
Kein aggressiver Bot-Schutz.

Domain: https://www.xn--jobbrse-d1a.de (Punycode für jobbörse.de)
Suche:  /stellenangebote/?was={keyword}&wo={location}&zeitraum={days}&page={n}
Detail: /stellenanzeige/{id}/

Datumsfilter: Native via `zeitraum`-Parameter (Tage).
Standortfilter: Native via `wo`-Parameter.
Rate-Limiting: 2s zwischen Detail-Requests, 3s zwischen Standorten.
"""

import asyncio
import logging
import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, Tag

from app.core.config import settings
from app.scraper.base import BaseScraper, ScrapedJob

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.xn--jobbrse-d1a.de"
_SEARCH_PATH = "/stellenangebote/"
_DEBUG_PATH = Path("data/jobboerse_debug.html")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _extract_job_id(url: str) -> str | None:
    match = re.search(r"/stellenanzeige/(\d+)/", url)
    return match.group(1) if match else None


_RE_JOB_URL = re.compile(r"/stellenanzeige/\d+/")


def _parse_listing(container: Tag) -> tuple[str, str, str | None, str | None] | None:
    """Extrahiert (title, url, company, location) aus einem Listing-Container."""
    # Titel + URL: erster <a>-Link im Container
    link = container.find("a", href=True)
    if not link or not isinstance(link, Tag):
        return None

    title = link.get_text(strip=True)
    href = str(link["href"])
    if not title or not href:
        return None

    url = href if href.startswith("http") else _BASE_URL + href

    # Nur echte Stellenanzeige-URLs akzeptieren (Filter gegen Sidebar/Widgets)
    if not _RE_JOB_URL.search(url):
        return None

    # Firma und Ort: Text-Elemente nach dem Link
    texts = [t.strip() for t in container.stripped_strings if t.strip() and t.strip() != title]
    company = texts[0] if texts else None
    location = texts[1] if len(texts) > 1 else None

    return title, url, company, location


def _find_listing_containers(soup: BeautifulSoup) -> list[Tag]:
    """Findet alle Job-Listing-Container auf der Suchergebnisseite."""
    # Primäre Selektoren (verifiziert aus Live-Analyse)
    containers = soup.find_all("div", class_="stellenanzeige")
    if containers:
        return [c for c in containers if isinstance(c, Tag)]

    # Fallback: article-Tags
    containers = soup.find_all("article")
    if containers:
        return [c for c in containers if isinstance(c, Tag)]

    return []


def _find_next_page_url(soup: BeautifulSoup, current_page: int) -> str | None:
    """Findet die URL der nächsten Seite in der Pagination."""
    # Suche nach Link mit page=N+1
    next_page = current_page + 1
    for a in soup.find_all("a", href=True):
        if not isinstance(a, Tag):
            continue
        href = str(a["href"])
        if f"page={next_page}" in href or "nächste" in a.get_text().lower():
            return href if href.startswith("http") else _BASE_URL + href
    return None


async def _fetch_raw_text(client: httpx.AsyncClient, url: str) -> str | None:
    """Fetcht die Volltext-Beschreibung von einer Detail-Seite."""
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Bekannte Selektoren für Stellenbeschreibungs-Container
        for selector in [
            ".stellenbeschreibung",
            ".job-description",
            ".description",
            "article",
            "main",
        ]:
            container = soup.select_one(selector)
            if container and isinstance(container, Tag):
                text = container.get_text(separator=" ")
                cleaned = " ".join(text.split())
                if len(cleaned) > 100:
                    return cleaned

        # Fallback: gesamter Body-Text
        body = soup.find("body")
        if body and isinstance(body, Tag):
            text = body.get_text(separator=" ")
            return " ".join(text.split())

    except Exception as exc:  # noqa: BLE001
        logger.debug("[jobboerse] Detail-Fehler %s: %s", url, exc)

    return None


class JobboerseScraper(BaseScraper):
    """Jobbörse.de SSR-Scraper.

    Scrapt Suchergebnisseiten mit httpx + BeautifulSoup.
    Fetcht Detail-Seiten für Volltext.
    Speichert Debug-HTML unter data/jobboerse_debug.html wenn keine Jobs gefunden.
    """

    source_name = "jobboerse"
    source_type = "portal"

    async def fetch_jobs(self) -> list[ScrapedJob]:
        """Fetcht Jobs für alle konfigurierten Standorte."""
        max_days = settings.scrape_posted_within_days or 7
        locations = [loc for loc in settings.scrape_locations if loc.lower() != "remote"]

        jobs: list[ScrapedJob] = []
        seen_urls: set[str] = set()

        async with httpx.AsyncClient(
            headers=_HEADERS, timeout=30.0, follow_redirects=True
        ) as client:
            for i, location in enumerate(locations):
                if i > 0:
                    await asyncio.sleep(3.0)

                loc_jobs = await self._scrape_location(client, location, max_days, seen_urls)
                jobs.extend(loc_jobs)
                logger.debug("[jobboerse] %s: %d Jobs", location, len(loc_jobs))

        logger.info("[jobboerse] Gesamt: %d Jobs", len(jobs))
        return jobs

    async def _scrape_location(
        self,
        client: httpx.AsyncClient,
        location: str,
        max_days: int,
        seen_urls: set[str],
    ) -> list[ScrapedJob]:
        """Scrapt alle Seiten für einen Standort."""
        jobs: list[ScrapedJob] = []
        page = 1
        debug_saved = False

        while True:
            params: dict[str, str | int] = {
                "was": "",
                "wo": location,
                "zeitraum": max_days,
                "page": page,
            }

            try:
                resp = await client.get(_BASE_URL + _SEARCH_PATH, params=params)
                resp.raise_for_status()
                html_content = resp.text
            except Exception as exc:  # noqa: BLE001
                logger.warning("[jobboerse] HTTP-Fehler (%s, S.%d): %s", location, page, exc)
                break

            soup = BeautifulSoup(html_content, "html.parser")
            containers = _find_listing_containers(soup)

            if not containers:
                if not debug_saved:
                    _DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)
                    _DEBUG_PATH.write_text(html_content, encoding="utf-8")
                    logger.warning(
                        "[jobboerse] Keine Listings gefunden (%s) — Debug-HTML: %s",
                        location,
                        _DEBUG_PATH,
                    )
                    debug_saved = True
                break

            page_jobs = 0
            for container in containers:
                parsed = _parse_listing(container)
                if parsed is None:
                    continue

                title, url, company, loc_raw = parsed
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                source_job_id = _extract_job_id(url)

                # Detail-Seite für Volltext
                raw_text = await _fetch_raw_text(client, url)
                await asyncio.sleep(2.0)

                jobs.append(
                    ScrapedJob(
                        title=title,
                        company_name=company or "Unbekannt",
                        location_raw=loc_raw or location,
                        url=url,
                        source_job_id=source_job_id,
                        raw_text=raw_text,
                        sector=None,
                    )
                )
                page_jobs += 1

            logger.debug("[jobboerse] %s Seite %d: %d Jobs", location, page, page_jobs)

            if page_jobs == 0 and not debug_saved:
                _DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)
                _DEBUG_PATH.write_text(html_content, encoding="utf-8")
                logger.warning(
                    "[jobboerse] 0 Jobs geparst (%s S.%d) — Debug-HTML: %s",
                    location,
                    page,
                    _DEBUG_PATH,
                )
                debug_saved = True

            # Nächste Seite?
            next_url = _find_next_page_url(soup, page)
            if not next_url or page_jobs == 0:
                break

            page += 1
            await asyncio.sleep(2.0)

        return jobs
