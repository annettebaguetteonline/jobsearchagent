"""Unit-Tests für app.location.resolver.AddressResolver."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pytest_httpx import HTTPXMock

from app.db.models import Company
from app.location.geocoding import NominatimClient
from app.location.models import GeocodingResult
from app.location.resolver import AddressResolver, _extract_german_address

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

COMPANY_FOUND = Company(
    id=1,
    name="Test GmbH",
    name_normalized="test gmbh",
    address_street="Musterstraße 1",
    address_city="Berlin",
    address_zip="10115",
    lat=52.532,
    lng=13.383,
    address_status="found",
    address_source="impressum",
    created_at="2026-01-01T00:00:00",
    updated_at="2026-01-01T00:00:00",
)

COMPANY_UNKNOWN = Company(
    id=2,
    name="Neu GmbH",
    name_normalized="neu gmbh",
    address_status="unknown",
    created_at="2026-01-01T00:00:00",
    updated_at="2026-01-01T00:00:00",
)

GEO_RESULT = GeocodingResult(
    lat=52.520,
    lng=13.405,
    display_name="Berlin, 10115, Deutschland",
    source="nominatim",
)

IMPRESSUM_HTML = """
<html><body>
<h1>Impressum</h1>
<p>Example GmbH</p>
<p>Hauptstraße 42</p>
<p>10115 Berlin</p>
</body></html>
"""

IMPRESSUM_HTML_NO_STREET = """
<html><body>
<h1>Impressum</h1>
<p>Example GmbH</p>
<p>10115 Berlin</p>
</body></html>
"""

NO_ADDRESS_HTML = """
<html><body>
<h1>Willkommen</h1>
<p>Dies ist eine Webseite ohne Adressinformationen.</p>
</body></html>
"""


@pytest.fixture()
def mock_geocoder() -> AsyncMock:
    geocoder = AsyncMock(spec=NominatimClient)
    geocoder.geocode.return_value = GEO_RESULT
    return geocoder


@pytest.fixture()
def mock_db() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def resolver(mock_geocoder: AsyncMock, httpx_mock: HTTPXMock) -> AddressResolver:
    http = httpx.AsyncClient()
    return AddressResolver(geocoder=mock_geocoder, http_client=http)


# ---------------------------------------------------------------------------
# Stufe 1: DB-Lookup
# ---------------------------------------------------------------------------


class TestStage1DbLookup:
    async def test_stage1_already_resolved(
        self, resolver: AddressResolver, mock_db: AsyncMock
    ) -> None:
        """Company hat address_status='found' -> sofort CompanyAddress zurück."""
        with patch("app.location.resolver.get_company", return_value=COMPANY_FOUND):
            result = await resolver._stage1_db_lookup(mock_db, 1)
        assert result is not None
        assert result.source == "db"
        assert result.status == "found"
        assert result.street == "Musterstraße 1"
        assert result.city == "Berlin"

    async def test_stage1_not_resolved_continues(
        self, resolver: AddressResolver, mock_db: AsyncMock
    ) -> None:
        """Company hat address_status='unknown' -> None (weiter zu Stufe 2)."""
        with patch("app.location.resolver.get_company", return_value=COMPANY_UNKNOWN):
            result = await resolver._stage1_db_lookup(mock_db, 2)
        assert result is None


# ---------------------------------------------------------------------------
# Stufe 2: Impressum-Scraping
# ---------------------------------------------------------------------------


class TestStage2ImpressumScraping:
    async def test_stage2_impressum_found(
        self,
        resolver: AddressResolver,
        mock_db: AsyncMock,
        mock_geocoder: AsyncMock,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Mock HTTP für /impressum -> Adresse extrahiert."""
        httpx_mock.add_response(
            url="https://example.com/impressum",
            text=IMPRESSUM_HTML,
        )

        with patch("app.location.resolver.update_company_address") as mock_update:
            result = await resolver._stage2_impressum_scraping(
                mock_db, 1, "https://example.com/jobs/123"
            )

        assert result is not None
        assert result.source == "impressum"
        assert result.status == "found"
        assert result.zip_code == "10115"
        assert result.city == "Berlin"
        mock_update.assert_awaited_once()
        mock_geocoder.geocode.assert_awaited_once()

    async def test_stage2_no_impressum(
        self,
        resolver: AddressResolver,
        mock_db: AsyncMock,
        httpx_mock: HTTPXMock,
    ) -> None:
        """/impressum, /imprint, /about/impressum alle 404 -> None."""
        httpx_mock.add_response(url="https://example.com/impressum", status_code=404)
        httpx_mock.add_response(url="https://example.com/imprint", status_code=404)
        httpx_mock.add_response(url="https://example.com/about/impressum", status_code=404)

        result = await resolver._stage2_impressum_scraping(
            mock_db, 1, "https://example.com/jobs/123"
        )
        assert result is None


# ---------------------------------------------------------------------------
# Stufe 3: Web-Suche
# ---------------------------------------------------------------------------


class TestStage3WebSearch:
    async def test_stage3_web_search_success(
        self,
        mock_geocoder: AsyncMock,
        mock_db: AsyncMock,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Mock DuckDuckGo + HTTP -> Adresse gefunden."""
        from unittest.mock import MagicMock

        http = httpx.AsyncClient()
        resolver = AddressResolver(geocoder=mock_geocoder, http_client=http)

        ddg_results = [{"href": "https://firma.de/impressum"}]

        httpx_mock.add_response(
            url="https://firma.de/impressum",
            text=IMPRESSUM_HTML,
        )

        mock_ddgs = MagicMock()
        mock_ddgs.text.return_value = ddg_results
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.location.resolver.update_company_address") as mock_update,
            patch("duckduckgo_search.DDGS", return_value=mock_ddgs),
        ):
            result = await resolver._stage3_web_search(mock_db, 1, "Firma GmbH")

        assert result is not None
        assert result.source == "searxng"
        assert result.status == "found"
        mock_update.assert_awaited_once()

    async def test_stage3_no_results(
        self,
        resolver: AddressResolver,
        mock_db: AsyncMock,
    ) -> None:
        """DuckDuckGo gibt [] -> None."""
        from unittest.mock import MagicMock

        mock_ddgs = MagicMock()
        mock_ddgs.text.return_value = []
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)

        with patch("duckduckgo_search.DDGS", return_value=mock_ddgs):
            result = await resolver._stage3_web_search(mock_db, 1, "Firma GmbH")

        assert result is None


# ---------------------------------------------------------------------------
# Stufe 4: Nominatim
# ---------------------------------------------------------------------------


class TestStage4Nominatim:
    async def test_stage4_nominatim_success(
        self,
        resolver: AddressResolver,
        mock_db: AsyncMock,
        mock_geocoder: AsyncMock,
    ) -> None:
        """Mock Geocoder -> lat/lng gespeichert."""
        with patch("app.location.resolver.update_company_address") as mock_update:
            result = await resolver._stage4_nominatim(mock_db, 1, "Berlin")

        assert result is not None
        assert result.source == "nominatim"
        assert result.lat == pytest.approx(52.520)
        assert result.lng == pytest.approx(13.405)
        mock_update.assert_awaited_once()

    async def test_stage4_nominatim_no_result(
        self,
        resolver: AddressResolver,
        mock_db: AsyncMock,
        mock_geocoder: AsyncMock,
    ) -> None:
        """Geocoder gibt None -> None."""
        mock_geocoder.geocode.return_value = None
        result = await resolver._stage4_nominatim(mock_db, 1, "Nirgendwo")
        assert result is None


# ---------------------------------------------------------------------------
# Full Pipeline
# ---------------------------------------------------------------------------


class TestFullPipeline:
    async def test_all_stages_fail_marks_failed(
        self,
        resolver: AddressResolver,
        mock_db: AsyncMock,
        mock_geocoder: AsyncMock,
    ) -> None:
        """Alle Stufen fehlgeschlagen -> mark_company_address_failed aufgerufen."""
        from unittest.mock import MagicMock

        mock_geocoder.geocode.return_value = None

        # Mock DDGS so stage 3 doesn't make real HTTP calls
        mock_ddgs = MagicMock()
        mock_ddgs.text.return_value = []
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.location.resolver.get_company", return_value=COMPANY_UNKNOWN),
            patch("app.location.resolver.mark_company_address_failed") as mock_fail,
            patch("duckduckgo_search.DDGS", return_value=mock_ddgs),
        ):
            result = await resolver.resolve(
                mock_db, 2, "Neu GmbH", location_raw=None, source_url=None
            )

        assert result is None
        mock_fail.assert_awaited_once_with(mock_db, 2)


# ---------------------------------------------------------------------------
# Adress-Extraktion
# ---------------------------------------------------------------------------


class TestExtractGermanAddress:
    def test_extract_full_address(self) -> None:
        """HTML mit Straße + PLZ + Ort -> korrekte Extraktion."""
        result = _extract_german_address(IMPRESSUM_HTML)
        assert result is not None
        street, zip_code, city = result
        assert street == "Hauptstraße 42"
        assert zip_code == "10115"
        assert city == "Berlin"

    def test_extract_no_street(self) -> None:
        """HTML nur mit PLZ + Ort -> street=None."""
        result = _extract_german_address(IMPRESSUM_HTML_NO_STREET)
        assert result is not None
        street, zip_code, city = result
        assert street is None
        assert zip_code == "10115"
        assert city == "Berlin"

    def test_extract_no_match(self) -> None:
        """HTML ohne Adresse -> None."""
        result = _extract_german_address(NO_ADDRESS_HTML)
        assert result is None
