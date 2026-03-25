"""Unit-Tests für app.location.geocoding.NominatimClient."""

import time

import httpx
import pytest
from pytest_httpx import HTTPXMock

from app.location.geocoding import NominatimClient
from app.location.models import GeocodingResult

FRANKFURT_RESPONSE = [
    {
        "lat": "50.1109",
        "lon": "8.6821",
        "display_name": "Frankfurt am Main, Hessen, Deutschland",
    }
]


@pytest.fixture()
def client(httpx_mock: HTTPXMock) -> NominatimClient:
    """NominatimClient mit rate_limit=0 und injiziertem httpx-Client."""
    http = httpx.AsyncClient()
    return NominatimClient(client=http, rate_limit_seconds=0)


class TestGeocode:
    async def test_geocode_success(self, client: NominatimClient, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(json=FRANKFURT_RESPONSE)
        result = await client.geocode("Frankfurt am Main")
        assert isinstance(result, GeocodingResult)
        assert result.lat == pytest.approx(50.1109)
        assert result.lng == pytest.approx(8.6821)
        assert result.display_name == "Frankfurt am Main, Hessen, Deutschland"
        assert result.source == "nominatim"

    async def test_geocode_empty_results(
        self, client: NominatimClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(json=[])
        result = await client.geocode("Nichtexistierender Ort XYZ")
        assert result is None

    async def test_geocode_http_error(self, client: NominatimClient, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(status_code=500)
        result = await client.geocode("Berlin")
        assert result is None

    async def test_geocode_timeout(self, client: NominatimClient, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_exception(httpx.TimeoutException("timeout"))
        result = await client.geocode("München")
        assert result is None

    async def test_country_codes_de_always_set(
        self, client: NominatimClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(json=FRANKFURT_RESPONSE)
        await client.geocode("Frankfurt")
        request = httpx_mock.get_requests()[0]
        assert "countrycodes=de" in str(request.url)


class TestGeocodeStructured:
    async def test_geocode_structured_with_postal_code(
        self, client: NominatimClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(json=FRANKFURT_RESPONSE)
        result = await client.geocode_structured("Frankfurt am Main", postal_code="60311")
        assert result is not None
        request = httpx_mock.get_requests()[0]
        assert "postalcode=60311" in str(request.url)

    async def test_geocode_structured_without_postal_code(
        self, client: NominatimClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(json=FRANKFURT_RESPONSE)
        await client.geocode_structured("Frankfurt am Main")
        request = httpx_mock.get_requests()[0]
        assert "postalcode" not in str(request.url)

    async def test_geocode_structured_empty_results(
        self, client: NominatimClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(json=[])
        result = await client.geocode_structured("Unbekannt")
        assert result is None


class TestRateLimiting:
    async def test_rate_limiting(self, httpx_mock: HTTPXMock) -> None:
        """Zwei schnelle Aufrufe: zweiter muss auf Rate-Limit warten."""
        httpx_mock.add_response(json=FRANKFURT_RESPONSE)
        httpx_mock.add_response(json=FRANKFURT_RESPONSE)

        http = httpx.AsyncClient()
        rate_client = NominatimClient(client=http, rate_limit_seconds=0.2)

        start = time.monotonic()
        await rate_client.geocode("Berlin")
        await rate_client.geocode("München")
        elapsed = time.monotonic() - start

        assert elapsed >= 0.2
