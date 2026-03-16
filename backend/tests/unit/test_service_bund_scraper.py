"""Unit-Tests für den service.bund.de RSS-Scraper."""

from pathlib import Path

from app.scraper.portals.service_bund import (
    ServiceBundScraper,
    _extract_source_job_id,
    _is_recent,
    _parse_deadline,
    _parse_rss_item,
)

# ─── Fixtures ─────────────────────────────────────────────────────────────────

_FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "service_bund_rss_sample.xml"

_CDATA_FULL = (
    "Arbeitgeber: <strong>Testbehörde GmbH</strong><br />"
    "Ort: <strong>34117 Kassel</strong><br />"
    "Bewerbungsfrist: <strong>03.04.2026 23:59</strong><br />"
)

_CDATA_NO_FRIST = (
    "Arbeitgeber: <strong>Bundesamt für Testen</strong><br />"
    "Ort: <strong>53113 Bonn</strong><br />"
    "Veröffentlichungsende: <strong>30.04.2026 23:59</strong>"
)


# ─── _parse_deadline ──────────────────────────────────────────────────────────


def test_parse_deadline_full_format() -> None:
    """'DD.MM.YYYY HH:MM' wird korrekt nach ISO-8601 UTC konvertiert."""
    result = _parse_deadline("03.04.2026 23:59")
    assert result == "2026-04-03T23:59:00Z"


def test_parse_deadline_date_only() -> None:
    """'DD.MM.YYYY' (ohne Uhrzeit) wird ebenfalls akzeptiert."""
    result = _parse_deadline("15.04.2026")
    assert result == "2026-04-15T00:00:00Z"


def test_parse_deadline_invalid_returns_none() -> None:
    """Ungültige Formate → None."""
    assert _parse_deadline("invalid-date") is None
    assert _parse_deadline("") is None


def test_parse_deadline_strips_whitespace() -> None:
    """Führende/nachfolgende Leerzeichen werden toleriert."""
    result = _parse_deadline("  03.04.2026 23:59  ")
    assert result == "2026-04-03T23:59:00Z"


# ─── _extract_source_job_id ───────────────────────────────────────────────────


def test_extract_source_job_id_numeric_suffix() -> None:
    """Numerische ID am Ende der GUID-URL wird extrahiert."""
    url = "https://www.service.bund.de/INPCOX/content/Sachbearbeiter-Personal-1111111.html"
    assert _extract_source_job_id(url) == "1111111"


def test_extract_source_job_id_double_dash() -> None:
    """IDs mit doppeltem Bindestrich-Prefix werden korrekt extrahiert."""
    url = "https://www.service.bund.de/INPCOX/content/IT-Admin--2222222.html"
    assert _extract_source_job_id(url) == "2222222"


def test_extract_source_job_id_no_id_returns_none() -> None:
    """URL ohne numerischen Suffix → None."""
    url = "https://www.service.bund.de/stellenangebote.html"
    assert _extract_source_job_id(url) is None


# ─── _is_recent ───────────────────────────────────────────────────────────────


def test_is_recent_none_date_always_true() -> None:
    """Kein Datum → immer behalten."""
    assert _is_recent(None, 30) is True


def test_is_recent_zero_max_days_always_true() -> None:
    """max_days=0 → kein Filter."""
    assert _is_recent("Mon, 01 Jan 2024 08:00:00 +0000", 0) is True


def test_is_recent_old_date_filtered() -> None:
    """Sehr altes Datum → herausgefiltert."""
    assert _is_recent("Mon, 01 Jan 2024 08:00:00 +0000", 30) is False


def test_is_recent_invalid_date_kept() -> None:
    """Nicht parsbare Daten → behalten (Fehlertoleranz)."""
    assert _is_recent("kein-datum", 30) is True


# ─── _parse_rss_item ──────────────────────────────────────────────────────────


def _make_item_xml(
    title: str,
    guid: str,
    link: str,
    description: str,
    pub_date: str = "Thu, 12 Mar 2026 14:00:00 +0100",
) -> str:
    return (
        "<item>"
        f"<title>{title}</title>"
        f"<link>{link}</link>"
        f"<guid>{guid}</guid>"
        f"<pubDate>{pub_date}</pubDate>"
        f"<description><![CDATA[{description}]]></description>"
        "</item>"
    )


def _parse_xml_item(xml_str: str):  # type: ignore[return]
    import xml.etree.ElementTree as ET

    return _parse_rss_item(ET.fromstring(xml_str))  # noqa: S314


def test_parse_rss_item_full_cdata() -> None:
    """Vollständiges CDATA: alle Felder korrekt extrahiert."""
    xml = _make_item_xml(
        title="Sachbearbeiterin Personal (w/m/d)",
        guid="https://www.service.bund.de/INPCOX/content/Sachbearbeiter-1111111.html",
        link="https://www.service.bund.de/INPCOX/content/Sachbearbeiter-1111111.html#track=feed-jobs",
        description=_CDATA_FULL,
    )
    job = _parse_xml_item(xml)
    assert job is not None
    assert job.title == "Sachbearbeiterin Personal (w/m/d)"
    assert job.company_name == "Testbehörde GmbH"
    assert job.location_raw == "34117 Kassel"
    assert job.deadline == "2026-04-03T23:59:00Z"
    assert job.sector == "public"
    assert job.source_job_id == "1111111"


def test_parse_rss_item_uses_guid_not_link() -> None:
    """URL wird aus <guid> genommen, nicht aus <link> (kein #track-Suffix)."""
    guid = "https://www.service.bund.de/INPCOX/content/Test-9999999.html"
    link = guid + "#track=feed-jobs"
    xml = _make_item_xml(
        title="Test Job",
        guid=guid,
        link=link,
        description=_CDATA_FULL,
    )
    job = _parse_xml_item(xml)
    assert job is not None
    assert job.url == guid
    assert "#track" not in job.url


def test_parse_rss_item_no_bewerbungsfrist() -> None:
    """Fehlende Bewerbungsfrist → deadline=None."""
    xml = _make_item_xml(
        title="Referentin Digitalisierung",
        guid="https://www.service.bund.de/INPCOX/content/Referent-3333333.html",
        link="https://www.service.bund.de/INPCOX/content/Referent-3333333.html#track=feed-jobs",
        description=_CDATA_NO_FRIST,
    )
    job = _parse_xml_item(xml)
    assert job is not None
    assert job.deadline is None
    assert job.company_name == "Bundesamt für Testen"
    assert job.location_raw == "53113 Bonn"


def test_parse_rss_item_missing_title_returns_none() -> None:
    """Fehlendes <title> → None."""
    import xml.etree.ElementTree as ET

    xml = "<item><guid>https://example.com/1.html</guid></item>"
    assert _parse_rss_item(ET.fromstring(xml)) is None  # noqa: S314


def test_parse_rss_item_sector_is_public() -> None:
    """Alle service.bund.de-Jobs haben sector='public'."""
    xml = _make_item_xml(
        title="Irgendein Job",
        guid="https://www.service.bund.de/INPCOX/content/Job-5555555.html",
        link="https://www.service.bund.de/INPCOX/content/Job-5555555.html",
        description=_CDATA_FULL,
    )
    job = _parse_xml_item(xml)
    assert job is not None
    assert job.sector == "public"


# ─── ServiceBundScraper._parse_feed ───────────────────────────────────────────


def test_parse_feed_with_fixture() -> None:
    """Fixture-XML: 3 Jobs eingelesen, 1 alter Job herausgefiltert."""
    scraper = ServiceBundScraper()
    xml_content = _FIXTURE_PATH.read_text(encoding="utf-8")

    # posted_within_days=0 → kein Datumsfilter (alle aktuellen Jobs)
    from unittest.mock import patch

    with patch("app.scraper.portals.service_bund.settings") as mock_settings:
        mock_settings.scrape_posted_within_days = 0
        jobs = scraper._parse_feed(xml_content)

    assert len(jobs) == 4  # alle 4 Items (kein Filter)


def test_parse_feed_date_filter() -> None:
    """Mit Datumsfilter (30 Tage) wird das alte Item (2024) herausgefiltert."""
    scraper = ServiceBundScraper()
    xml_content = _FIXTURE_PATH.read_text(encoding="utf-8")

    from unittest.mock import patch

    with patch("app.scraper.portals.service_bund.settings") as mock_settings:
        mock_settings.scrape_posted_within_days = 30
        jobs = scraper._parse_feed(xml_content)

    assert len(jobs) == 3  # 4 Items - 1 altes = 3


def test_parse_feed_invalid_xml_returns_empty() -> None:
    """Ungültiges XML → leere Liste, kein Fehler."""
    scraper = ServiceBundScraper()
    result = scraper._parse_feed("dies ist kein xml")
    assert result == []


def test_parse_feed_sector_all_public() -> None:
    """Alle Jobs aus dem Feed haben sector='public'."""
    scraper = ServiceBundScraper()
    xml_content = _FIXTURE_PATH.read_text(encoding="utf-8")

    from unittest.mock import patch

    with patch("app.scraper.portals.service_bund.settings") as mock_settings:
        mock_settings.scrape_posted_within_days = 0
        jobs = scraper._parse_feed(xml_content)

    assert all(j.sector == "public" for j in jobs)


def test_parse_feed_source_job_ids_extracted() -> None:
    """Alle Jobs aus dem Feed haben eine source_job_id."""
    scraper = ServiceBundScraper()
    xml_content = _FIXTURE_PATH.read_text(encoding="utf-8")

    from unittest.mock import patch

    with patch("app.scraper.portals.service_bund.settings") as mock_settings:
        mock_settings.scrape_posted_within_days = 0
        jobs = scraper._parse_feed(xml_content)

    assert all(j.source_job_id is not None for j in jobs)
    job_ids = {j.source_job_id for j in jobs}
    assert "1111111" in job_ids
    assert "2222222" in job_ids
