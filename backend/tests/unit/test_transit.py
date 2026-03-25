"""Unit-Tests für app.location.transit."""

import re
from datetime import UTC, datetime

import httpx
import pytest
from pytest_httpx import HTTPXMock

from app.location.models import TransitResult
from app.location.transit import (
    CarRoutingClient,
    PublicTransitClient,
    _next_weekday,
    hash_home_address,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

LOCATIONS_RESPONSE = [{"name": "Frankfurt", "location": {"latitude": 50.11, "longitude": 8.68}}]

JOURNEYS_RESPONSE = {
    "journeys": [
        {
            "legs": [
                {
                    "departure": "2026-03-17T08:00:00+00:00",
                    "arrival": "2026-03-17T08:45:00+00:00",
                }
            ]
        }
    ]
}

OSRM_RESPONSE = {"code": "Ok", "routes": [{"duration": 2700.0, "distance": 50000}]}


@pytest.fixture()
def transit_client(httpx_mock: HTTPXMock) -> PublicTransitClient:
    http = httpx.AsyncClient()
    return PublicTransitClient(client=http, rate_limit_seconds=0)


@pytest.fixture()
def car_client(httpx_mock: HTTPXMock) -> CarRoutingClient:
    http = httpx.AsyncClient()
    return CarRoutingClient(client=http, rate_limit_seconds=0)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestHashHomeAddress:
    def test_deterministic(self) -> None:
        assert hash_home_address("Musterstr. 1, 60311 Frankfurt") == hash_home_address(
            "Musterstr. 1, 60311 Frankfurt"
        )

    def test_is_sha256(self) -> None:
        result = hash_home_address("some address")
        assert len(result) == 64
        assert re.fullmatch(r"[0-9a-f]{64}", result)


class TestNextWeekday:
    def test_future(self) -> None:
        result = _next_weekday("tuesday", "08:00")
        dt = datetime.fromisoformat(result.replace("Z", "+00:00"))
        assert dt > datetime.now(UTC)

    def test_format(self) -> None:
        result = _next_weekday("monday", "09:30")
        # Must end with Z (UTC)
        assert result.endswith("Z")
        dt = datetime.fromisoformat(result.replace("Z", "+00:00"))
        assert dt.hour == 9
        assert dt.minute == 30
        assert dt.second == 0
        assert dt.weekday() == 0  # Monday


# ---------------------------------------------------------------------------
# PublicTransitClient
# ---------------------------------------------------------------------------


class TestPublicTransitClient:
    async def test_success(
        self, transit_client: PublicTransitClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(json=LOCATIONS_RESPONSE)
        httpx_mock.add_response(json=JOURNEYS_RESPONSE)

        result = await transit_client.compute_transit_time(
            origin_address="Musterstr. 1, Frankfurt",
            dest_lat=52.52,
            dest_lng=13.41,
            origin_hash="abc123",
            company_id=42,
        )
        assert isinstance(result, TransitResult)
        assert result.transit_minutes == 45
        assert result.mode == "public_transit"
        assert result.api_used == "db_rest"
        assert result.company_id == 42
        assert result.origin_hash == "abc123"

    async def test_no_locations(
        self, transit_client: PublicTransitClient, httpx_mock: HTTPXMock
    ) -> None:
        # DB REST: empty locations → None; transport.rest fallback also empty
        httpx_mock.add_response(json=[])
        httpx_mock.add_response(json=[])

        result = await transit_client.compute_transit_time(
            origin_address="Unbekannte Str. 99",
            dest_lat=52.52,
            dest_lng=13.41,
            origin_hash="abc",
            company_id=1,
        )
        assert result is None

    async def test_no_journeys(
        self, transit_client: PublicTransitClient, httpx_mock: HTTPXMock
    ) -> None:
        # DB REST: locations OK, journeys empty → fallback
        httpx_mock.add_response(json=LOCATIONS_RESPONSE)
        httpx_mock.add_response(json={"journeys": []})
        # transport.rest fallback: also no journeys
        httpx_mock.add_response(json=LOCATIONS_RESPONSE)
        httpx_mock.add_response(json={"journeys": []})

        result = await transit_client.compute_transit_time(
            origin_address="Frankfurt",
            dest_lat=52.52,
            dest_lng=13.41,
            origin_hash="abc",
            company_id=1,
        )
        assert result is None

    async def test_fallback_to_transport_rest(
        self, transit_client: PublicTransitClient, httpx_mock: HTTPXMock
    ) -> None:
        # DB REST /locations fails
        httpx_mock.add_response(status_code=500)
        # transport.rest succeeds
        httpx_mock.add_response(json=LOCATIONS_RESPONSE)
        httpx_mock.add_response(json=JOURNEYS_RESPONSE)

        result = await transit_client.compute_transit_time(
            origin_address="Frankfurt",
            dest_lat=52.52,
            dest_lng=13.41,
            origin_hash="abc",
            company_id=1,
        )
        assert result is not None
        assert result.api_used == "transport_rest"
        assert result.transit_minutes == 45

    async def test_both_fail(
        self, transit_client: PublicTransitClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(status_code=500)
        httpx_mock.add_response(status_code=500)

        result = await transit_client.compute_transit_time(
            origin_address="Frankfurt",
            dest_lat=52.52,
            dest_lng=13.41,
            origin_hash="abc",
            company_id=1,
        )
        assert result is None

    async def test_picks_shortest_journey(
        self, transit_client: PublicTransitClient, httpx_mock: HTTPXMock
    ) -> None:
        journeys_multi = {
            "journeys": [
                {
                    "legs": [
                        {
                            "departure": "2026-03-17T08:00:00+00:00",
                            "arrival": "2026-03-17T09:30:00+00:00",
                        }
                    ]
                },
                {
                    "legs": [
                        {
                            "departure": "2026-03-17T08:00:00+00:00",
                            "arrival": "2026-03-17T08:40:00+00:00",
                        }
                    ]
                },
                {
                    "legs": [
                        {
                            "departure": "2026-03-17T08:00:00+00:00",
                            "arrival": "2026-03-17T09:00:00+00:00",
                        }
                    ]
                },
            ]
        }
        httpx_mock.add_response(json=LOCATIONS_RESPONSE)
        httpx_mock.add_response(json=journeys_multi)

        result = await transit_client.compute_transit_time(
            origin_address="Frankfurt",
            dest_lat=52.52,
            dest_lng=13.41,
            origin_hash="abc",
            company_id=1,
        )
        assert result is not None
        assert result.transit_minutes == 40  # shortest of 90, 40, 60


# ---------------------------------------------------------------------------
# CarRoutingClient
# ---------------------------------------------------------------------------


class TestCarRoutingClient:
    async def test_success(self, car_client: CarRoutingClient, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(json=OSRM_RESPONSE)

        result = await car_client.compute_driving_time(
            origin_lat=50.11,
            origin_lng=8.68,
            dest_lat=52.52,
            dest_lng=13.41,
            origin_hash="abc",
            company_id=7,
        )
        assert isinstance(result, TransitResult)
        assert result.transit_minutes == 45  # 2700s / 60
        assert result.mode == "car"
        assert result.api_used == "osrm"
        assert result.company_id == 7

    async def test_error_code(self, car_client: CarRoutingClient, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(json={"code": "NoRoute", "message": "No route found"})
        result = await car_client.compute_driving_time(
            origin_lat=50.11,
            origin_lng=8.68,
            dest_lat=52.52,
            dest_lng=13.41,
            origin_hash="abc",
            company_id=1,
        )
        assert result is None

    async def test_http_error(self, car_client: CarRoutingClient, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(status_code=500)
        result = await car_client.compute_driving_time(
            origin_lat=50.11,
            origin_lng=8.68,
            dest_lat=52.52,
            dest_lng=13.41,
            origin_hash="abc",
            company_id=1,
        )
        assert result is None

    async def test_lng_lat_order_in_url(
        self, car_client: CarRoutingClient, httpx_mock: HTTPXMock
    ) -> None:
        """OSRM erwartet lng,lat — nicht lat,lng."""
        httpx_mock.add_response(json=OSRM_RESPONSE)
        await car_client.compute_driving_time(
            origin_lat=50.11,
            origin_lng=8.68,
            dest_lat=52.52,
            dest_lng=13.41,
            origin_hash="abc",
            company_id=1,
        )
        request = httpx_mock.get_requests()[0]
        # URL should contain "8.68,50.11;13.41,52.52" (lng first)
        assert "8.68,50.11" in str(request.url)
        assert "13.41,52.52" in str(request.url)
