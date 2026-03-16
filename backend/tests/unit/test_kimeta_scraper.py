"""Unit-Tests für den Kimeta Next.js-Scraper."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.scraper.portals.kimeta import (
    _extract_pf_from_html,
    _parse_job_from_ppa,
    _parse_published_at,
)

# ─── Fixtures ─────────────────────────────────────────────────────────────────

_FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "kimeta_position_filter.html"

_FIXTURE_HTML = _FIXTURE_PATH.read_text(encoding="utf-8")

# ─── _extract_pf_from_html ────────────────────────────────────────────────────


def test_extract_pf_from_html_positions() -> None:
    """Positions-pf-Werte werden korrekt aus dem HTML extrahiert."""
    result = _extract_pf_from_html(_FIXTURE_HTML)
    assert "position@Consultant (m/w/d)" in result
    assert "position@Senior Consultant (m/w/d)" in result


def test_extract_pf_from_html_area() -> None:
    """Tätigkeitsbereich-pf-Werte werden ebenfalls extrahiert."""
    result = _extract_pf_from_html(_FIXTURE_HTML)
    assert "tätigkeitsbereich@Software & IT" in result


def test_extract_pf_from_html_contracts() -> None:
    """Vertragsart-pf-Werte (beschäftigungsart@, zeitintensität@) werden extrahiert."""
    result = _extract_pf_from_html(_FIXTURE_HTML)
    assert "beschäftigungsart@Festanstellung" in result
    assert "beschäftigungsart@Ausbildung" in result
    assert "zeitintensität@Vollzeit" in result


def test_extract_pf_from_html_deduplication() -> None:
    """Doppelte hrefs werden nur einmal zurückgegeben."""
    result = _extract_pf_from_html(_FIXTURE_HTML)
    assert result.count("position@Consultant (m/w/d)") == 1


def test_extract_pf_from_html_ignores_non_pos_class() -> None:
    """Links ohne 'pos'-Klasse werden ignoriert."""
    result = _extract_pf_from_html(_FIXTURE_HTML)
    assert "something@value" not in result


def test_extract_pf_from_html_url_decoding() -> None:
    """URL-kodierte pf-Werte werden korrekt dekodiert."""
    html = (
        '<a rel="nofollow" class="jsx-123 pos" '
        'href="/search?pf=position%40Werkstudent%2Fin">Werkstudent</a>'
    )
    result = _extract_pf_from_html(html)
    assert result == ["position@Werkstudent/in"]


def test_extract_pf_from_html_empty() -> None:
    """HTML ohne pos-Elemente gibt leere Liste zurück."""
    assert _extract_pf_from_html("<html><body><p>kein Filter</p></body></html>") == []


def test_extract_pf_from_html_no_pf_param() -> None:
    """pos-Link ohne pf=-Parameter wird übersprungen."""
    html = '<a rel="nofollow" class="jsx-123 pos" href="/search?q=test">No pf</a>'
    assert _extract_pf_from_html(html) == []


def test_extract_pf_from_html_order_preserved() -> None:
    """Reihenfolge der extrahierten Werte entspricht der Reihenfolge im HTML."""
    result = _extract_pf_from_html(_FIXTURE_HTML)
    pos_consultant = result.index("position@Consultant (m/w/d)")
    pos_senior = result.index("position@Senior Consultant (m/w/d)")
    assert pos_consultant < pos_senior


# ─── _parse_published_at ──────────────────────────────────────────────────────


def test_parse_published_at_iso_with_z() -> None:
    """ISO-8601 mit Z-Suffix wird korrekt geparst."""
    published_at, age_days = _parse_published_at("2026-03-14T10:00:00Z")
    assert published_at == "2026-03-14T10:00:00Z"
    assert age_days is not None
    assert age_days >= 0


def test_parse_published_at_date_only() -> None:
    """Datumsstring ohne Uhrzeit wird akzeptiert."""
    published_at, age_days = _parse_published_at("2026-03-14")
    assert published_at is not None
    assert "2026-03-14" in published_at


def test_parse_published_at_invalid_returns_none() -> None:
    """Ungültiger Datumsstring gibt (None, None) zurück."""
    published_at, age_days = _parse_published_at("kein-datum")
    assert published_at is None
    assert age_days is None


# ─── _parse_job_from_ppa ──────────────────────────────────────────────────────

_TODAY_ISO = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
_YESTERDAY_ISO = (datetime.now(tz=UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
_OLD_ISO = (datetime.now(tz=UTC) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_job(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "Software Engineer (m/w/d)",
        "offerOriginalUrl": "https://example.com/job/123",
        "companyName": "Acme GmbH",
        "location": "Frankfurt am Main",
        "lastChange": _YESTERDAY_ISO,
        "documentId": "42",
        "teaser": "Wir suchen einen erfahrenen Software Engineer.",
    }
    base.update(overrides)
    return base


def test_parse_job_from_ppa_valid() -> None:
    """Vollständiges Job-Objekt wird korrekt zu ScrapedJob konvertiert."""
    job = _parse_job_from_ppa(_make_job(), max_days=7)
    assert job is not None
    assert job.title == "Software Engineer (m/w/d)"
    assert job.company_name == "Acme GmbH"
    assert job.url == "https://example.com/job/123"
    assert job.location_raw == "Frankfurt am Main"
    assert job.source_job_id == "42"
    assert job.raw_text == "Wir suchen einen erfahrenen Software Engineer."
    assert job.sector is None


def test_parse_job_from_ppa_prefers_original_url() -> None:
    """offerOriginalUrl wird gegenüber offerUrl bevorzugt."""
    job = _parse_job_from_ppa(
        _make_job(offerOriginalUrl="https://original.com/job", offerUrl="https://kimeta.de/job"),
        max_days=7,
    )
    assert job is not None
    assert job.url == "https://original.com/job"


def test_parse_job_from_ppa_falls_back_to_offer_url() -> None:
    """Wenn offerOriginalUrl fehlt, wird offerUrl genutzt."""
    data = _make_job()
    del data["offerOriginalUrl"]  # type: ignore[misc]
    data["offerUrl"] = "https://kimeta.de/job/fallback"
    job = _parse_job_from_ppa(data, max_days=7)
    assert job is not None
    assert job.url == "https://kimeta.de/job/fallback"


def test_parse_job_from_ppa_missing_title_returns_none() -> None:
    """Fehlendes title-Feld → None."""
    data = _make_job()
    del data["title"]  # type: ignore[misc]
    assert _parse_job_from_ppa(data, max_days=7) is None


def test_parse_job_from_ppa_missing_url_returns_none() -> None:
    """Fehlende URL → None."""
    data = _make_job()
    del data["offerOriginalUrl"]  # type: ignore[misc]
    assert _parse_job_from_ppa(data, max_days=7) is None


def test_parse_job_from_ppa_too_old_returns_none() -> None:
    """Job älter als max_days → None."""
    assert _parse_job_from_ppa(_make_job(lastChange=_OLD_ISO), max_days=7) is None


def test_parse_job_from_ppa_no_date_is_accepted() -> None:
    """Job ohne Datum wird nicht gefiltert (age_days=None)."""
    data = _make_job()
    del data["lastChange"]  # type: ignore[misc]
    assert _parse_job_from_ppa(data, max_days=7) is not None


def test_parse_job_from_ppa_uses_last_change_over_first_found() -> None:
    """lastChange wird gegenüber firstFound bevorzugt."""
    job = _parse_job_from_ppa(
        _make_job(lastChange=_YESTERDAY_ISO, firstFound=_OLD_ISO),
        max_days=7,
    )
    assert job is not None  # würde None sein wenn firstFound verwendet würde


def test_parse_job_from_ppa_unknown_company() -> None:
    """Fehlendes companyName → 'Unbekannt'."""
    data = _make_job()
    del data["companyName"]  # type: ignore[misc]
    job = _parse_job_from_ppa(data, max_days=7)
    assert job is not None
    assert job.company_name == "Unbekannt"


def test_parse_job_from_ppa_empty_teaser() -> None:
    """Leeres teaser-Feld → raw_text=None."""
    job = _parse_job_from_ppa(_make_job(teaser=""), max_days=7)
    assert job is not None
    assert job.raw_text is None
