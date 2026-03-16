"""Stellenmarkt.de RSS-Scraper.

15 kategorie-basierte RSS-Feeds, kein Auth.
Aktualisierung täglich. Volltext teilweise in <description>.
Kein Standort-/Keyword-Filter — nationale Feeds, LLM-Pipeline entscheidet.

Feed-Format: Standard RSS 2.0 XML.
pubDate: RFC 2822 (z.B. 'Mon, 01 Dec 2025 08:00:00 +0100').
"""

import asyncio
import html
import logging
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.scraper.base import BaseScraper, ScrapedJob

logger = logging.getLogger(__name__)

_FEEDS: dict[str, str] = {
    "consulting": "https://www.stellenmarkt.de/rss/smrssbf1.xml",
    "einkauf": "https://www.stellenmarkt.de/rss/smrssbf2.xml",
    "finanzen": "https://www.stellenmarkt.de/rss/smrssbf3.xml",
    "produktion": "https://www.stellenmarkt.de/rss/smrssbf4.xml",
    "ingenieure": "https://www.stellenmarkt.de/rss/smrssbf5.xml",
    "it": "https://www.stellenmarkt.de/rss/smrssbf6.xml",
    "bildung": "https://www.stellenmarkt.de/rss/smrssbf7.xml",
    "marketing": "https://www.stellenmarkt.de/rss/smrssbf8.xml",
    "medizin": "https://www.stellenmarkt.de/rss/smrssbf9.xml",
    "personal": "https://www.stellenmarkt.de/rss/smrssbf10.xml",
    "recht": "https://www.stellenmarkt.de/rss/smrssbf11.xml",
    "vertrieb": "https://www.stellenmarkt.de/rss/smrssbf12.xml",
    "sonstige": "https://www.stellenmarkt.de/rss/smrssbf13.xml",
    "verwaltung": "https://www.stellenmarkt.de/rss/smrssbf14.xml",
    "design": "https://www.stellenmarkt.de/rss/smrssbf15.xml",
}


def _pub_date_to_iso(pub_date_str: str) -> str | None:
    """Konvertiert RFC 2822 pubDate → ISO-8601 UTC."""
    try:
        dt = parsedate_to_datetime(pub_date_str)
        return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    except Exception:  # noqa: BLE001
        return None


def _is_recent(pub_date_str: str | None, max_days: int) -> bool:
    """Gibt True zurück wenn das Posting nicht älter als max_days Tage ist."""
    if not pub_date_str or max_days <= 0:
        return True
    try:
        pub_dt = parsedate_to_datetime(pub_date_str)
        return (datetime.now(tz=UTC) - pub_dt).days <= max_days
    except Exception:  # noqa: BLE001
        return True


def _strip_html(raw: str) -> str:
    """Entfernt HTML-Tags und normalisiert Whitespace."""
    text = BeautifulSoup(html.unescape(raw), "html.parser").get_text(separator=" ")
    return " ".join(text.split())


def _extract_source_job_id(url: str) -> str | None:
    """Extrahiert numerische ID aus URL (letztes Ziffernsegment)."""
    import re

    match = re.search(r"(\d+)", url.rstrip("/").split("/")[-1])
    return match.group(1) if match else None


def _parse_rss_item(item: ET.Element) -> ScrapedJob | None:
    """Extrahiert ScrapedJob aus RSS <item>."""
    title_el = item.find("title")
    link_el = item.find("link")
    desc_el = item.find("description")
    pub_el = item.find("pubDate")

    if title_el is None or link_el is None:
        return None

    title = (title_el.text or "").strip()
    url = (link_el.text or "").strip()
    if not title or not url:
        return None

    # Titel-Format: "Stellentitel - Firma GmbH" → aufteilen
    company_name = "Unbekannt"
    if " - " in title:
        parts = title.rsplit(" - ", 1)
        title = parts[0].strip()
        company_name = parts[1].strip()

    description = desc_el.text or "" if desc_el is not None else ""
    raw_text = _strip_html(description) if description else None

    pub_date = pub_el.text if pub_el is not None else None
    published_at = _pub_date_to_iso(pub_date) if pub_date else None
    source_job_id = _extract_source_job_id(url)

    return ScrapedJob(
        title=title,
        company_name=company_name,
        location_raw=None,  # Kein Orts-Feld im RSS
        url=url,
        published_at=published_at,
        raw_text=raw_text,
        source_job_id=source_job_id,
        sector=None,
    )


def _parse_feed(xml_content: str, category: str, max_days: int) -> list[ScrapedJob]:
    """Parst RSS-XML und filtert nach Alter."""
    jobs: list[ScrapedJob] = []
    try:
        root = ET.fromstring(xml_content)  # noqa: S314
    except ET.ParseError as exc:
        logger.warning("[stellenmarkt] Parse-Fehler (%s): %s", category, exc)
        return []

    for item in root.findall(".//item"):
        pub_el = item.find("pubDate")
        pub_date = pub_el.text if pub_el is not None else None
        if not _is_recent(pub_date, max_days):
            continue
        job = _parse_rss_item(item)
        if job is not None:
            jobs.append(job)

    return jobs


class StellenmarktScraper(BaseScraper):
    """Stellenmarkt.de RSS-Scraper.

    Fetcht alle 15 Kategorie-Feeds und filtert nach Alter.
    Kein Standortfilter — die Evaluation-Pipeline entscheidet über Relevanz.
    """

    source_name = "stellenmarkt"
    source_type = "aggregator"

    async def fetch_jobs(self) -> list[ScrapedJob]:
        """Fetcht alle RSS-Feeds und gibt gefilterte Jobs zurück."""
        max_days = settings.scrape_posted_within_days
        jobs: list[ScrapedJob] = []
        seen_urls: set[str] = set()

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for category, url in _FEEDS.items():
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[stellenmarkt] Feed-Fehler (%s): %s", category, exc)
                    await asyncio.sleep(1.0)
                    continue

                feed_jobs = _parse_feed(resp.text, category, max_days)
                new_count = 0
                for job in feed_jobs:
                    if job.url not in seen_urls:
                        seen_urls.add(job.url)
                        jobs.append(job)
                        new_count += 1

                logger.debug("[stellenmarkt] Feed %s: %d Jobs", category, new_count)
                await asyncio.sleep(0.5)

        logger.info("[stellenmarkt] Gesamt: %d Jobs aus %d Feeds", len(jobs), len(_FEEDS))
        return jobs
