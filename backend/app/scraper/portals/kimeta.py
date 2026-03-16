"""Kimeta.de SSR-Scraper (Next.js / __PPA__-Dekodierung).

Meta-Aggregator mit ~2,5 Mio. Stellen aus hunderten Quellen.

Kimeta nutzt Next.js. Die Seiten-Daten sind als Unicode-Codepoint-Array im `__NEXT_DATA__`-Script
unter `props.pageProps.__PPA__` eingebettet.

URL-Format: https://www.kimeta.de/search?pf=<FILTER>&loc={city}&r={radius}&page={page}

Paginierung: `page`-Query-Parameter (0-basiert), Stop wenn `canPageMore == false`.
Datumsfilter: Client-seitig über `lastChange`/`firstFound`-Feld im jobOffer-Objekt.
Max. Seiten: 15 pro Suchanfrage (Kimeta-Limit).

Mehrstufige Suche pro Standort:
1. Seite 0 der Basis-Suche: Jobs + Filter-pf-Werte aus HTML (<a class="pos">) extrahieren.
2. &cat=position-Fetch: vollständige Positions-Keyword-Liste.
3. Basis-Suche ab Seite 1 weiterführen.
4. &cat=contract-Fetch: Vertragsarten-pf-Werte.
5. Sub-Suchen pro pf-Wert (positions, areas, Vertragsarten).

Volltext-Abruf: Für Jobs mit kimeta.de/iframe/-URL wird die Detail-Seite zusätzlich
gefetcht und der Text als raw_text gespeichert.

Debug: Basis-PPA → data/kimeta_debug_ppa.json
"""

import asyncio
import json
import logging
import re
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, Tag

from app.core.config import settings
from app.scraper.base import BaseScraper, ScrapedJob

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.kimeta.de/search"
_DEBUG_HTML_PATH = Path("data/kimeta_debug.html")
_DEBUG_PPA_PATH = Path("data/kimeta_debug_ppa.json")
_MAX_PAGES = 50  # Sicherheitsnetz; tatsächlicher Stop via canPageMore

_PAGE_SLEEP = 2.0  # zwischen Seiten innerhalb einer Suchanfrage
_SUBSEARCH_SLEEP = 3.0  # zwischen Suchanfragen / Kategorie-Fetches
_LOCATION_SLEEP = 3.0  # zwischen Standorten
_MAX_SUBSEARCHES = 150  # Sicherheitsnetz: max. Sub-Suchen pro Standort
_FULLTEXT_SLEEP = 0.5  # zwischen Detail-Seiten-Fetches für Volltext

_IFRAME_PREFIX = "https://www.kimeta.de/iframe/"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.google.de/",
}


def _decode_ppa(html_content: str) -> dict[str, object] | None:
    """Dekodiert den __PPA__-Codepoint-Array aus Next.js __NEXT_DATA__.

    Kimeta bettet Seitendaten als Unicode-Codepoint-Array ein.
    Dekodierung: ''.join(chr(v) for v in ppa)
    Gibt None zurück wenn kein __PPA__ gefunden oder Dekodierung fehlschlägt.
    """
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script or not isinstance(script, Tag):
            return None

        next_data = json.loads(script.string or "")
        ppa = next_data.get("props", {}).get("pageProps", {}).get("__PPA__")
        if not isinstance(ppa, list):
            return None

        decoded_str = "".join(chr(v) for v in ppa)
        page_data = json.loads(decoded_str)
        return page_data if isinstance(page_data, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("[kimeta] __PPA__-Dekodierung fehlgeschlagen: %s", exc)
        return None


def _save_debug_ppa(page_data: dict[str, object], path: Path = _DEBUG_PPA_PATH) -> None:
    """Speichert PPA-Struktur als Debug-JSON (überschreibt nicht wenn existiert)."""
    if path.exists():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(page_data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("[kimeta] __PPA__-Struktur gespeichert: %s", path)
    except Exception:  # noqa: BLE001, S110
        pass


def _parse_published_at(date_str: str) -> tuple[str | None, int | None]:
    """Parst ISO-8601-Datumsstring → (published_at, age_days)."""
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str[:19], fmt.rstrip("Z"))  # noqa: DTZ007
            dt_utc = dt.replace(tzinfo=UTC)
            published_at = dt_utc.isoformat(timespec="seconds").replace("+00:00", "Z")
            age_days = (datetime.now(tz=UTC) - dt_utc).days
            return published_at, age_days
        except ValueError:
            continue
    return None, None


def _parse_job_from_ppa(job: dict[str, object], max_days: int) -> ScrapedJob | None:
    """Konvertiert ein jobOffer-Objekt aus __PPA__ in ein ScrapedJob."""
    # Titel
    title = job.get("title")
    if not title or not isinstance(title, str):
        return None

    # URL — Original-URL bevorzugt (direkte Arbeitgeber-/Portal-Seite)
    url = job.get("offerOriginalUrl") or job.get("offerUrl")
    if not url or not isinstance(url, str):
        return None

    # Firma
    company_raw = job.get("companyName") or job.get("company")
    company_name = company_raw if isinstance(company_raw, str) else "Unbekannt"

    # Ort
    location_raw = job.get("location")
    location_str = location_raw if isinstance(location_raw, str) else None

    # Datum — lastChange bevorzugt (letzte Aktualisierung/Re-Post), Fallback firstFound
    published_at: str | None = None
    age_days: int | None = None

    for date_key in ("lastChange", "firstFound"):
        date_val = job.get(date_key)
        if isinstance(date_val, str) and date_val:
            published_at, age_days = _parse_published_at(date_val)
            if published_at:
                break

    if age_days is not None and age_days > max_days:
        return None

    # Source-ID
    doc_id = job.get("documentId")
    source_job_id = str(doc_id) if doc_id is not None else None

    # Beschreibung/Teaser
    teaser = job.get("teaser")
    raw_text = teaser if isinstance(teaser, str) and teaser else None

    return ScrapedJob(
        title=title,
        company_name=company_name,
        location_raw=location_str,
        url=url,
        source_job_id=source_job_id,
        published_at=published_at,
        raw_text=raw_text,
        sector=None,
    )


def _extract_jobs_from_page_data(
    page_data: dict[str, object],
    max_days: int,
    seen_urls: set[str],
) -> tuple[list[ScrapedJob], bool]:
    """Extrahiert Jobs aus dekodiertem __PPA__-Objekt.

    Gibt (jobs, has_more) zurück.
    has_more entspricht `canPageMore` im PPA-Objekt.
    """
    search_results = page_data.get("searchResults")
    job_list: list[object] = []
    if isinstance(search_results, dict):
        offers = search_results.get("jobOffers")
        if isinstance(offers, list):
            job_list = offers

    jobs: list[ScrapedJob] = []
    for job_obj in job_list:
        if not isinstance(job_obj, dict):
            continue
        job = _parse_job_from_ppa(job_obj, max_days)
        if job is None:
            continue
        if job.url in seen_urls:
            continue
        seen_urls.add(job.url)
        jobs.append(job)

    has_more = bool(page_data.get("canPageMore", False))
    return jobs, has_more


def _extract_pf_from_html(html_content: str) -> list[str]:
    """Extrahiert pf=-Werte aus <a rel="nofollow" class="... pos"> Elementen.

    Kimeta listet Filter-Optionen als <a class="jsx-... pos" rel="nofollow"> Links.
    Der href enthält den pf=-Parameter, z.B. pf=position%40Consultant%20(m%2Fw%2Fd).
    Funktioniert für Basis-Seite (Positionen/Bereiche) und &cat=contract (Vertragsarten).
    """
    soup = BeautifulSoup(html_content, "html.parser")
    pf_values: list[str] = []
    seen: set[str] = set()
    for a_tag in soup.find_all("a", rel="nofollow"):
        raw_classes = a_tag.get("class")
        classes: list[str] = raw_classes if isinstance(raw_classes, list) else []
        if "pos" not in classes:
            continue
        href = str(a_tag.get("href", ""))
        match = re.search(r"[?&]pf=([^&]+)", href)
        if match:
            pf_val = urllib.parse.unquote(match.group(1))
            if pf_val and pf_val not in seen:
                seen.add(pf_val)
                pf_values.append(pf_val)
    return pf_values


async def _fetch_raw_text(client: httpx.AsyncClient, url: str) -> str | None:
    """Fetcht Volltext von einer kimeta.de/iframe/-Detailseite.

    Nur für URLs mit _IFRAME_PREFIX aufrufen — externe URLs werden nicht unterstützt.
    Gibt None zurück bei HTTP-Fehlern oder wenn kein verwertbarer Text gefunden wird.
    """
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for selector in [".job-description", ".description", "article", "main"]:
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
        logger.debug("[kimeta] Volltext-Fehler %s: %s", url, exc)

    return None


class KimetaScraper(BaseScraper):
    """Kimeta.de Next.js-Scraper via __PPA__-Dekodierung.

    Nutzt den /search-Endpunkt mit loc=-Parameter.
    Fetcht Suchergebnisseiten und dekodiert den eingebetteten Next.js-Datenstrom.

    Mehrstufige Suche pro Standort:
    1. Seite 0 der Basis-Suche: Jobs + pf-Werte aus positions/areas extrahieren
    2. Basis-Suche ab Seite 1 weiterführen
    3. &cat=contract Request: Vertragsarten-pf-Werte per PPA-Scan ermitteln
    4. Sub-Suchen für alle pf-Werte (positions, areas, Vertragsarten)
    """

    source_name = "kimeta"
    source_type = "aggregator"
    known_job_ids: frozenset[str] = frozenset()

    async def fetch_jobs(self) -> list[ScrapedJob]:
        """Fetcht Jobs für alle konfigurierten Standorte."""
        max_days = settings.scrape_posted_within_days or 7
        locations = [loc for loc in settings.scrape_locations if loc.lower() != "remote"]

        jobs: list[ScrapedJob] = []

        async with httpx.AsyncClient(
            headers=_HEADERS, timeout=30.0, follow_redirects=True
        ) as client:
            for i, location in enumerate(locations):
                if i > 0:
                    await asyncio.sleep(_LOCATION_SLEEP)

                loc_jobs = await self._scrape_location(client, location, max_days)
                jobs.extend(loc_jobs)
                logger.debug("[kimeta] %s: %d Jobs", location, len(loc_jobs))

        logger.info("[kimeta] Gesamt: %d Jobs", len(jobs))
        return jobs

    async def _fetch_categories(
        self,
        client: httpx.AsyncClient,
        location: str,
        cat_type: str,
    ) -> list[str]:
        """Fetcht Kategorie-spezifische pf-Werte via &cat=<cat_type>.

        Extrahiert <a class="... pos" rel="nofollow"> Links aus dem HTML.
        """
        params: dict[str, str | int] = {
            "q": "",
            "loc": location,
            "r": settings.scrape_radius_km,
            "cat": cat_type,
        }
        try:
            resp = await client.get(_SEARCH_URL, params=params)
            resp.raise_for_status()
            html_content = resp.text
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[kimeta] Kategorie-Fetch fehlgeschlagen (%s, cat=%s): %s",
                location,
                cat_type,
                exc,
            )
            return []

        pf_values = _extract_pf_from_html(html_content)
        logger.debug("[kimeta] Kategorien %s/%s: %d gefunden", location, cat_type, len(pf_values))
        return pf_values

    async def _scrape_with_query(
        self,
        client: httpx.AsyncClient,
        location: str,
        max_days: int,
        seen_urls: set[str],
        pf: str = "",
        label: str = "",
        start_page: int = 0,
    ) -> list[ScrapedJob]:
        """Scrapt Seiten ab start_page für eine einzelne pf-Suchanfrage.

        seen_urls wird standort-weit geteilt → verhindert Duplikate über Subsuchen hinweg.
        """
        jobs: list[ScrapedJob] = []
        page = start_page

        while page <= _MAX_PAGES:
            params: dict[str, str | int] = {
                "q": "",
                "loc": location,
                "r": settings.scrape_radius_km,
                "page": page,
            }
            if pf:
                params["pf"] = pf

            try:
                resp = await client.get(_SEARCH_URL, params=params)
                resp.raise_for_status()
                html_content = resp.text
            except Exception as exc:  # noqa: BLE001
                logger.warning("[kimeta] HTTP-Fehler (%s/%s S.%d): %s", location, label, page, exc)
                break

            page_data = _decode_ppa(html_content)
            if page_data is None:
                logger.warning(
                    "[kimeta] __PPA__ nicht dekodierbar (%s/%s S.%d)", location, label, page
                )
                break

            page_jobs, has_more = _extract_jobs_from_page_data(page_data, max_days, seen_urls)

            # Volltext-Abruf für kimeta.de/iframe/-URLs
            for job in page_jobs:
                if job.url.startswith(_IFRAME_PREFIX) and not job.raw_text:
                    job.raw_text = await _fetch_raw_text(client, job.url)
                    await asyncio.sleep(_FULLTEXT_SLEEP)

            jobs.extend(page_jobs)
            logger.debug("[kimeta] %s/%s S.%d: %d Jobs", location, label, page, len(page_jobs))

            if not has_more:
                break

            page += 1
            await asyncio.sleep(_PAGE_SLEEP)

        return jobs

    async def _scrape_location(
        self,
        client: httpx.AsyncClient,
        location: str,
        max_days: int,
    ) -> list[ScrapedJob]:
        """Scrapt alle Subsuchen (Basis + Positionen + Tätigkeitsbereiche + Vertragsarten)."""
        all_jobs: list[ScrapedJob] = []
        seen_urls: set[str] = set()

        # --- Seite 0 manuell holen: Jobs + pf-Werte aus positions/areas ---
        params_p0: dict[str, str | int] = {
            "q": "",
            "loc": location,
            "r": settings.scrape_radius_km,
            "page": 0,
        }
        try:
            resp = await client.get(_SEARCH_URL, params=params_p0)
            resp.raise_for_status()
            html_p0 = resp.text
        except Exception as exc:  # noqa: BLE001
            logger.warning("[kimeta] Seite 0 fehlgeschlagen (%s): %s", location, exc)
            return []

        page_data_p0 = _decode_ppa(html_p0)
        if page_data_p0 is None:
            try:
                _DEBUG_HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
                _DEBUG_HTML_PATH.write_text(html_p0, encoding="utf-8")
                logger.warning(
                    "[kimeta] __PPA__ nicht dekodierbar (%s) — Debug-HTML: %s",
                    location,
                    _DEBUG_HTML_PATH,
                )
            except Exception:  # noqa: BLE001, S110
                pass
            return []

        _save_debug_ppa(page_data_p0)
        pf_seen: set[str] = set()
        pf_values: list[str] = []
        for v in _extract_pf_from_html(html_p0):
            if v not in pf_seen:
                pf_seen.add(v)
                pf_values.append(v)

        page0_jobs, has_more = _extract_jobs_from_page_data(page_data_p0, max_days, seen_urls)
        all_jobs.extend(page0_jobs)
        logger.debug(
            "[kimeta] %s/base S.0: %d Jobs, %d pf-Werte", location, len(page0_jobs), len(pf_values)
        )

        # --- Basis-Suche ab Seite 1 ---
        if has_more:
            more_base = await self._scrape_with_query(
                client, location, max_days, seen_urls, pf="", label="base", start_page=1
            )
            all_jobs.extend(more_base)

        # --- Positions-Keywords via &cat=position (kann mehr liefern als Basis-Seite) ---
        await asyncio.sleep(_SUBSEARCH_SLEEP)
        for v in await self._fetch_categories(client, location, "position"):
            if v not in pf_seen:
                pf_seen.add(v)
                pf_values.append(v)

        logger.info(
            "[kimeta] %s/base: %d Jobs, %d pf-Werte", location, len(all_jobs), len(pf_values)
        )

        # --- Vertragsarten via &cat=contract ---
        await asyncio.sleep(_SUBSEARCH_SLEEP)
        contracts_pf = await self._fetch_categories(client, location, "contract")
        logger.info("[kimeta] %s: %d Vertragsarten-pf gefunden", location, len(contracts_pf))

        # --- Sub-Suchen: positions + areas ---
        subsearch_count = 0
        for pf_val in pf_values:
            if subsearch_count >= _MAX_SUBSEARCHES:
                logger.warning(
                    "[kimeta] %s: Max. Subsuchen (%d) erreicht, abgebrochen",
                    location,
                    _MAX_SUBSEARCHES,
                )
                break
            await asyncio.sleep(_SUBSEARCH_SLEEP)
            sub_jobs = await self._scrape_with_query(
                client, location, max_days, seen_urls, pf=pf_val, label=pf_val[:25]
            )
            all_jobs.extend(sub_jobs)
            subsearch_count += 1
            logger.debug(
                "[kimeta] %s/%s: %d Jobs (%d gesamt)",
                location,
                pf_val[:20],
                len(sub_jobs),
                len(all_jobs),
            )

        # --- Sub-Suchen: Vertragsarten ---
        for pf_val in contracts_pf:
            if subsearch_count >= _MAX_SUBSEARCHES:
                logger.warning(
                    "[kimeta] %s: Max. Subsuchen (%d) erreicht, abgebrochen",
                    location,
                    _MAX_SUBSEARCHES,
                )
                break
            await asyncio.sleep(_SUBSEARCH_SLEEP)
            ct_jobs = await self._scrape_with_query(
                client, location, max_days, seen_urls, pf=pf_val, label=pf_val[:25]
            )
            all_jobs.extend(ct_jobs)
            subsearch_count += 1
            logger.debug(
                "[kimeta] %s/%s: %d Jobs (%d gesamt)",
                location,
                pf_val[:20],
                len(ct_jobs),
                len(all_jobs),
            )

        logger.info(
            "[kimeta] %s: %d Jobs gesamt (%d Subsuchen)",
            location,
            len(all_jobs),
            subsearch_count + 1,
        )
        return all_jobs
