"""service.bund.de RSS-Scraper (Typ A – Strukturiert).

Bundesweiter Öffentlicher Dienst. Einzel-RSS-Feed, kein Keyword-/Ortsfilter.
Die Evaluation-Pipeline entscheidet über Relevanz.

Feed-URL:
  https://www.service.bund.de/Content/Globals/Functions/RSSFeed/RSSGenerator_Stellen.xml

Item-Struktur (CDATA in <description>):
  Arbeitgeber: <strong>Landesbetrieb Landwirtschaft Hessen (LLH)</strong>
  Ort:         <strong>34117 Kassel</strong>
  Bewerbungsfrist: <strong>03.04.2026 23:59</strong>
"""

import logging
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from app.core.config import settings
from app.scraper.base import BaseScraper, ScrapedJob

logger = logging.getLogger(__name__)

_RSS_URL = "https://www.service.bund.de/Content/Globals/Functions/RSSFeed/RSSGenerator_Stellen.xml"

# CDATA-Extraktions-Pattern
_RE_ARBEITGEBER = re.compile(r"Arbeitgeber:\s*<strong>(.*?)</strong>", re.IGNORECASE)
_RE_ORT = re.compile(r"Ort:\s*<strong>(.*?)</strong>", re.IGNORECASE)
_RE_FRIST = re.compile(r"Bewerbungsfrist:\s*<strong>(.*?)</strong>", re.IGNORECASE)

# Job-ID aus GUID-URL: letztes Segment vor .html (z.B. "...INPCOX-Titel--1234567.html")
_RE_JOB_ID = re.compile(r"-(\d+)\.html$", re.IGNORECASE)


def _parse_deadline(raw: str) -> str | None:
    """Konvertiert 'DD.MM.YYYY HH:MM' → ISO-8601 UTC-String.

    Beispiel: '03.04.2026 23:59' → '2026-04-03T23:59:00Z'
    Fehlende oder nicht parsbare Werte → None.
    """
    raw = raw.strip()
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            dt = datetime.strptime(raw, fmt)  # noqa: DTZ007
            return dt.replace(tzinfo=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        except ValueError:
            continue
    logger.debug("Konnte Bewerbungsfrist nicht parsen: %r", raw)
    return None


def _is_recent(pub_date_str: str | None, max_days: int) -> bool:
    """Gibt True zurück wenn das Posting nicht älter als max_days Tage ist."""
    if not pub_date_str or max_days <= 0:
        return True
    try:
        pub_dt = parsedate_to_datetime(pub_date_str)
        now = datetime.now(tz=UTC)
        return (now - pub_dt).days <= max_days
    except Exception:  # noqa: BLE001
        return True  # Im Zweifel behalten


def _extract_source_job_id(guid_url: str) -> str | None:
    """Extrahiert die numerische Job-ID aus der GUID-URL.

    Beispiel: '.../INPCOX-Sachbearbeiter--1234567.html' → '1234567'
    """
    match = _RE_JOB_ID.search(guid_url)
    return match.group(1) if match else None


def _parse_rss_item(item: ET.Element) -> ScrapedJob | None:
    """Extrahiert einen ScrapedJob aus einem RSS <item>-Element.

    service.bund.de-RSS-Felder:
      <title>   Stellentitel
      <guid>    Saubere URL (kein #track-Suffix)
      <link>    URL mit #track=feed-jobs → ignorieren, GUID nutzen
      <pubDate> RFC-2822-Datum
      <description> HTML/CDATA mit Arbeitgeber, Ort, Bewerbungsfrist
    """
    title_el = item.find("title")
    guid_el = item.find("guid")
    desc_el = item.find("description")

    if title_el is None or guid_el is None:
        return None

    title = (title_el.text or "").strip()
    url = (guid_el.text or "").strip()
    description = desc_el.text or "" if desc_el is not None else ""

    if not title or not url:
        return None

    # CDATA-Felder extrahieren
    arbeitgeber_match = _RE_ARBEITGEBER.search(description)
    ort_match = _RE_ORT.search(description)
    frist_match = _RE_FRIST.search(description)

    company_name = arbeitgeber_match.group(1).strip() if arbeitgeber_match else "Unbekannt"
    location_raw = ort_match.group(1).strip() if ort_match else None
    deadline = _parse_deadline(frist_match.group(1)) if frist_match else None
    source_job_id = _extract_source_job_id(url)

    return ScrapedJob(
        title=title,
        company_name=company_name,
        location_raw=location_raw,
        url=url,
        deadline=deadline,
        raw_text=description or None,
        source_job_id=source_job_id,
        sector="public",
    )


class ServiceBundScraper(BaseScraper):
    """service.bund.de RSS-Scraper (Typ A).

    Einzel-Feed, kein Keyword-/Ortsfilter — alle Bundesstellen werden gescrapt.
    Die Evaluation-Pipeline entscheidet über Relevanz und Pendelbarkeit.
    """

    source_name = "service_bund"
    source_type = "portal"

    async def fetch_jobs(self) -> list[ScrapedJob]:
        """Fetcht den RSS-Feed und gibt alle aktuellen Stellen zurück."""
        logger.debug("Fetching service.bund.de RSS: %s", _RSS_URL)

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(_RSS_URL)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("HTTP-Fehler bei service.bund.de: %s", exc)
            return []

        jobs = self._parse_feed(response.text)
        logger.info("[service_bund] %d Jobs aus Feed", len(jobs))
        return jobs

    def _parse_feed(self, xml_content: str) -> list[ScrapedJob]:
        """Parst RSS-XML und filtert nach Alter."""
        jobs: list[ScrapedJob] = []
        max_days = settings.scrape_posted_within_days

        try:
            root = ET.fromstring(xml_content)  # noqa: S314
        except ET.ParseError as exc:
            logger.warning("RSS-Parse-Fehler (service.bund.de): %s", exc)
            return []

        seen_urls: set[str] = set()
        for item in root.findall(".//item"):
            pub_date_el = item.find("pubDate")
            pub_date = pub_date_el.text if pub_date_el is not None else None

            if not _is_recent(pub_date, max_days):
                logger.debug("Übersprungen (zu alt): %s", pub_date)
                continue

            scraped = _parse_rss_item(item)
            if scraped is None:
                continue

            if scraped.url in seen_urls:
                continue
            seen_urls.add(scraped.url)

            jobs.append(scraped)

        return jobs
