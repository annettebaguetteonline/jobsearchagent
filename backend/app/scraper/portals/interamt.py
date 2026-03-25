"""Interamt Playwright-Scraper (Typ B).

Interamt ist das offizielle Stellenportal des Bundes für den öffentlichen Dienst.
Die API erfordert eine registrierte Partner-ID (nicht öffentlich).
Diese Implementierung nutzt Playwright zum Scrapen der Web-Oberfläche.

Portal-URL: https://interamt.de/koop/app/trefferliste

DOM-Struktur (verifiziert März 2026):
  Tabelle:    table.ia-e-table--searchresults
  Zeilen:     tr.ia-e-table__row  (Datenzeilen haben td[data-field])
  Felder:     td[data-field="Stellenbezeichnung"]   → Titel
              td[data-field="Behoerde"]              → Behörde
              td[data-field="PLZOrte"]               → PLZ + Ort
              td[data-field="StellenangebotId"] span → Job-ID (numerisch)
              td[data-field="Von"]                   → Eingestellt (DD.MM.YYYY)
              td[data-field="Bewerbungsfrist"]        → Frist
  Mehr laden: #id1  (Wicket AJAX "mehr laden"-Button)

Paginierung via "mehr laden" Button (kein URL-Parameter).
Job-URL: https://interamt.de/koop/app/stelle?id={job_id}
"""

import asyncio
import logging
import random
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, Tag
from playwright.async_api import ElementHandle, Page, async_playwright

from app.core.config import settings
from app.scraper.base import BaseScraper, ScrapedJob

logger = logging.getLogger(__name__)

_INTERAMT_BASE = "https://interamt.de"
_SEARCH_URL = "https://interamt.de/koop/app/trefferliste"
_JOB_URL_TEMPLATE = "https://interamt.de/koop/app/stelle?id={job_id}"
_DEBUG_FILE = Path("data/interamt_debug.html")
_DETAIL_SLEEP = 1.0  # Sekunden zwischen Detail-Requests
_DETAIL_CONCURRENCY = 5  # Parallele Detail-Requests
_DETAIL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
]

_USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
]

# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────


def _parse_german_date(date_str: str | None) -> str | None:
    """Konvertiert DD.MM.YYYY zu ISO-8601 UTC."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str.strip(), "%d.%m.%Y")  # noqa: DTZ007
        return dt.replace(tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def _browser_context_kwargs() -> dict[str, object]:
    """Browser-Context-Parameter."""
    return {
        "locale": "de-DE",
        "timezone_id": "Europe/Berlin",
        "viewport": random.choice(_VIEWPORTS),  # noqa: S311
        "user_agent": random.choice(_USER_AGENTS),  # noqa: S311
        "extra_http_headers": {"Accept-Language": "de-DE,de;q=0.9"},
    }


async def _get_field_text(row: ElementHandle, field: str) -> str:
    """Liest den Text einer td[data-field=...]-Zelle."""
    el = await row.query_selector(f"td[data-field='{field}']")
    if el is None:
        return ""
    text = await el.text_content()
    return (text or "").strip()


async def _parse_job_row(
    row: ElementHandle,
    seen_urls: set[str],
) -> ScrapedJob | None:
    """Extrahiert einen ScrapedJob aus einer Tabellenzeile."""
    # Job-ID aus der Span in der ID-Spalte
    id_el = await row.query_selector("td[data-field='StellenangebotId'] span")
    if id_el is None:
        return None
    job_id_text = (await id_el.text_content() or "").strip()
    if not re.match(r"^\d+$", job_id_text):
        return None  # Header-Zeile oder leer

    url = _JOB_URL_TEMPLATE.format(job_id=job_id_text)
    if url in seen_urls:
        return None
    seen_urls.add(url)

    title = await _get_field_text(row, "Stellenbezeichnung")
    if not title:
        return None

    company = await _get_field_text(row, "Behoerde")
    location_raw = await _get_field_text(row, "PLZOrte")
    published_at_str = await _get_field_text(row, "Von")
    deadline_str = await _get_field_text(row, "Bewerbungsfrist")

    published_at = _parse_german_date(published_at_str)
    deadline = _parse_german_date(deadline_str)

    return ScrapedJob(
        title=title,
        company_name=company or "Unbekannt",
        location_raw=location_raw or None,
        url=url,
        published_at=published_at,
        deadline=deadline,
        source_job_id=job_id_text,
        sector="Öffentlicher Dienst",
    )


async def _fetch_raw_text(client: httpx.AsyncClient, url: str) -> str | None:
    """Fetcht den Volltext einer Interamt-Detailseite via httpx."""
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for selector in [
            ".ia-e-stellenangebot__beschreibung",
            ".ia-e-detail",
            ".ia-e-content",
            "main",
            "article",
        ]:
            container = soup.select_one(selector)
            if container and isinstance(container, Tag):
                text = container.get_text(separator=" ")
                cleaned = " ".join(text.split())
                if len(cleaned) > 100:
                    return cleaned
        body = soup.find("body")
        if body and isinstance(body, Tag):
            text = body.get_text(separator=" ")
            return " ".join(text.split())
    except Exception as exc:  # noqa: BLE001
        logger.debug("[interamt] Detail-Fehler %s: %s", url, exc)
    return None


async def _fetch_with_sem(
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    job: ScrapedJob,
) -> None:
    """Fetcht einen Job-Volltext mit Semaphore für Parallelitätsbegrenzung."""
    async with sem:
        job.raw_text = await _fetch_raw_text(client, job.url)
        await asyncio.sleep(_DETAIL_SLEEP)


# ─── Scraper-Klasse ────────────────────────────────────────────────────────────


class InteramtScraper(BaseScraper):
    """Interamt Playwright-Scraper (Typ B).

    Lädt die Trefferliste und klickt wiederholt auf "mehr laden",
    bis alle Jobs geladen sind. 13.000+ Stellen verfügbar.
    """

    source_name = "interamt"
    source_type = "portal"

    async def fetch_jobs(self) -> list[ScrapedJob]:
        """Fetcht Jobs via Playwright (Listing) + httpx (Detail-Volltext)."""
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(**_browser_context_kwargs())  # type: ignore[arg-type]
            page = await context.new_page()

            all_jobs: list[ScrapedJob] = []
            seen_urls: set[str] = set()

            try:
                all_jobs = await self._scrape_all(page, seen_urls)
            finally:
                await context.close()
                await browser.close()

        # Phase 2: Detail-Seiten für Volltext via httpx (parallel)
        async with httpx.AsyncClient(
            headers=_DETAIL_HEADERS, timeout=20.0, follow_redirects=True
        ) as client:
            sem = asyncio.Semaphore(_DETAIL_CONCURRENCY)
            total = len(all_jobs)
            logger.info(
                "[interamt] Fetche Volltexte für %d Jobs (Parallelität: %d) ...",
                total,
                _DETAIL_CONCURRENCY,
            )
            tasks = [_fetch_with_sem(sem, client, job) for job in all_jobs]
            completed = 0
            for coro in asyncio.as_completed(tasks):
                await coro
                completed += 1
                if completed % 50 == 0 or completed == total:
                    logger.info("[interamt] Volltext: %d / %d", completed, total)

        logger.info("[interamt] Gesamt: %d Jobs", len(all_jobs))
        return all_jobs

    async def _scrape_all(self, page: Page, seen_urls: set[str]) -> list[ScrapedJob]:
        """Lädt Trefferliste und klickt "mehr laden" bis alle Jobs geladen."""
        jobs: list[ScrapedJob] = []

        logger.debug("[interamt] Lade: %s", _SEARCH_URL)
        try:
            await page.goto(_SEARCH_URL, wait_until="domcontentloaded", timeout=30_000)
            # Warte auf erste Job-Zeile
            await page.wait_for_selector(
                "tr.ia-e-table__row td[data-field='Stellenbezeichnung']",
                timeout=20_000,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[interamt] Seitenladefehler: %s", exc)
            try:
                html = await page.content()
                _DEBUG_FILE.parent.mkdir(parents=True, exist_ok=True)
                _DEBUG_FILE.write_text(html)
                logger.warning("[interamt] HTML-Dump: %s", _DEBUG_FILE)
            except Exception:  # noqa: BLE001, S110
                pass
            return jobs

        # Filtere ggf. auf Aktualität (scrape_posted_within_days)
        max_days = settings.scrape_posted_within_days

        load_more_rounds = 0
        while True:
            # Alle aktuell geladenen Zeilen auslesen
            rows = await page.query_selector_all("tr.ia-e-table__row")
            new_this_round = 0
            for row in rows:
                job = await _parse_job_row(row, seen_urls)
                if job is not None:
                    # Datumsfilter
                    if max_days > 0 and job.published_at:
                        try:
                            published = datetime.fromisoformat(
                                job.published_at.replace("Z", "+00:00")
                            )
                            age_days = (datetime.now(tz=UTC) - published).days
                            if age_days > max_days:
                                continue
                        except Exception:  # noqa: BLE001, S110
                            pass
                    jobs.append(job)
                    new_this_round += 1

            logger.debug("[interamt] Runde %d: %d Jobs total", load_more_rounds, len(jobs))

            # "Mehr laden" Button klicken — via JS um ia-e-backdrop zu umgehen
            has_more = await page.evaluate(
                "() => { const btn = document.getElementById('id1');"
                " if (!btn) return false; btn.click(); return true; }"
            )
            if not has_more:
                break  # Kein Button mehr → alle Jobs geladen

            await asyncio.sleep(random.uniform(2.0, 3.5))  # noqa: S311
            # Warte auf neue Zeilen (max 5 Sekunden, nicht 10)
            rows_loaded = False
            try:
                await page.wait_for_function(
                    f"document.querySelectorAll('tr.ia-e-table__row').length > {len(rows)}",
                    timeout=5_000,
                )
                rows_loaded = True
            except Exception as exc:  # noqa: BLE001
                # Keine neuen Zeilen nach kurzer Wartezeit
                logger.debug("[interamt] Keine neuen Zeilen nach Klick: %s", exc)

            if not rows_loaded:
                # Überprüfe nochmal ob Button noch existiert
                has_more = await page.evaluate(
                    "() => { const btn = document.getElementById('id1'); "
                    "return btn && !btn.disabled; }"
                )
                if not has_more:
                    break  # Button weg oder disabled → alle Jobs geladen

            load_more_rounds += 1

        return jobs
