"""Transit-Clients für Wegzeitberechnung.

ÖPNV: DB REST API v6 (Primary) + transport.rest v1 (Fallback)
Auto: OSRM (Open Source Routing Machine)
"""

import asyncio
import hashlib
import logging
import time
from datetime import UTC, datetime, timedelta

import httpx

from app.location.models import TransitResult

logger = logging.getLogger(__name__)


def hash_home_address(address: str) -> str:
    """SHA256-Hash der Heimatadresse für Privacy-konformes Caching."""
    return hashlib.sha256(address.encode("utf-8")).hexdigest()


def _next_weekday(weekday: str, time_str: str) -> str:
    """Berechne den nächsten ISO-8601 Timestamp für einen Wochentag + Uhrzeit.

    Args:
        weekday: Englischer Wochentagname ('monday', 'tuesday', ...)
        time_str: Uhrzeit im Format 'HH:MM'

    Returns:
        ISO-8601 UTC datetime string
    """
    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    target = weekdays[weekday.lower()]
    now = datetime.now(UTC)
    days_ahead = target - now.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    target_date = now + timedelta(days=days_ahead)
    hour, minute = time_str.split(":")
    target_dt = target_date.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    return target_dt.isoformat(timespec="seconds").replace("+00:00", "Z")


class PublicTransitClient:
    """ÖPNV-Wegzeitberechnung via deutsche Bahn REST APIs.

    Primary: https://v6.db.transport.rest (hafas-rest-api, community-betrieben)
    Fallback: https://v1.db.transport.rest (ältere Version)
    """

    DB_REST_URL = "https://v6.db.transport.rest"
    TRANSPORT_REST_URL = "https://v1.db.transport.rest"
    TIMEOUT = 15.0

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        rate_limit_seconds: float = 1.0,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._rate_limit = rate_limit_seconds
        self._last_request_at: float = 0.0

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.TIMEOUT)
        return self._client

    async def _rate_limit_wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._rate_limit:
            await asyncio.sleep(self._rate_limit - elapsed)
        self._last_request_at = time.monotonic()

    async def compute_transit_time(
        self,
        origin_address: str,
        dest_lat: float,
        dest_lng: float,
        origin_hash: str,
        company_id: int,
        departure_time: str = "08:00",
        departure_weekday: str = "tuesday",
    ) -> TransitResult | None:
        """Berechne ÖPNV-Fahrtzeit von origin zu destination.

        Ablauf:
        1. Origin-Adresse geocoden via /locations endpoint
        2. Journey-Anfrage mit Origin/Destination Koordinaten
        3. Kürzeste Reisezeit aus den Ergebnissen extrahieren
        4. Bei Fehler: Fallback auf transport.rest v1
        """
        result = await self._try_api(
            self.DB_REST_URL,
            origin_address,
            dest_lat,
            dest_lng,
            origin_hash,
            company_id,
            departure_time,
            departure_weekday,
            api_name="db_rest",
        )
        if result is not None:
            return result

        logger.info("DB REST fehlgeschlagen, versuche transport.rest Fallback")
        return await self._try_api(
            self.TRANSPORT_REST_URL,
            origin_address,
            dest_lat,
            dest_lng,
            origin_hash,
            company_id,
            departure_time,
            departure_weekday,
            api_name="transport_rest",
        )

    async def _try_api(
        self,
        base_url: str,
        origin_address: str,
        dest_lat: float,
        dest_lng: float,
        origin_hash: str,
        company_id: int,
        departure_time: str,
        departure_weekday: str,
        api_name: str,
    ) -> TransitResult | None:
        """Versuche eine Transit-Berechnung über eine spezifische API."""
        client = await self._ensure_client()

        # Schritt 1: Origin geocoden
        await self._rate_limit_wait()
        try:
            loc_resp = await client.get(
                f"{base_url}/locations",
                params={"query": origin_address, "results": "1"},
            )
            loc_resp.raise_for_status()
            locations = loc_resp.json()
            if not locations:
                logger.warning("Keine Location gefunden für %r", origin_address)
                return None

            origin = locations[0]
            origin_lat = origin["location"]["latitude"]
            origin_lng = origin["location"]["longitude"]
        except (httpx.HTTPError, KeyError) as exc:
            logger.warning("%s locations Fehler: %s", api_name, exc)
            return None

        # Schritt 2: Journey anfragen
        departure = _next_weekday(departure_weekday, departure_time)
        await self._rate_limit_wait()
        try:
            journey_resp = await client.get(
                f"{base_url}/journeys",
                params={
                    "from.latitude": str(origin_lat),
                    "from.longitude": str(origin_lng),
                    "to.latitude": str(dest_lat),
                    "to.longitude": str(dest_lng),
                    "departure": departure,
                    "results": "3",
                },
            )
            journey_resp.raise_for_status()
            data = journey_resp.json()
        except httpx.HTTPError as exc:
            logger.warning("%s journeys Fehler: %s", api_name, exc)
            return None

        # Schritt 3: Kürzeste Reisezeit extrahieren
        journeys = data.get("journeys", [])
        if not journeys:
            logger.warning("Keine Journeys gefunden via %s", api_name)
            return None

        min_minutes: int | None = None
        for journey in journeys:
            legs = journey.get("legs", [])
            if not legs:
                continue
            dep = datetime.fromisoformat(legs[0]["departure"].replace("Z", "+00:00"))
            arr = datetime.fromisoformat(legs[-1]["arrival"].replace("Z", "+00:00"))
            minutes = int((arr - dep).total_seconds() / 60)
            if min_minutes is None or minutes < min_minutes:
                min_minutes = minutes

        if min_minutes is None:
            return None

        return TransitResult(
            origin_hash=origin_hash,
            company_id=company_id,
            transit_minutes=min_minutes,
            mode="public_transit",
            api_used=api_name,
        )

    async def close(self) -> None:
        """Schließe den HTTP-Client falls wir ihn selbst erstellt haben."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


class CarRoutingClient:
    """Auto-Fahrzeitberechnung via OSRM (Open Source Routing Machine).

    OSRM Demo-Server: https://router.project-osrm.org
    Kostenlos, kein API-Key, aber nur für moderate Nutzung.
    """

    OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
    TIMEOUT = 10.0

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        rate_limit_seconds: float = 1.0,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._rate_limit = rate_limit_seconds
        self._last_request_at: float = 0.0

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.TIMEOUT)
        return self._client

    async def _rate_limit_wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._rate_limit:
            await asyncio.sleep(self._rate_limit - elapsed)
        self._last_request_at = time.monotonic()

    async def compute_driving_time(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        origin_hash: str,
        company_id: int,
    ) -> TransitResult | None:
        """Berechne Auto-Fahrzeit zwischen zwei Koordinaten.

        OSRM URL-Format:
        GET /route/v1/driving/{lng1},{lat1};{lng2},{lat2}?overview=false

        Achtung: OSRM nutzt lng,lat Reihenfolge (nicht lat,lng)!
        """
        client = await self._ensure_client()
        await self._rate_limit_wait()

        url = f"{self.OSRM_URL}/{origin_lng},{origin_lat};{dest_lng},{dest_lat}"
        try:
            resp = await client.get(url, params={"overview": "false"})
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != "Ok":
                logger.warning("OSRM Fehler: %s", data.get("message"))
                return None

            routes = data.get("routes", [])
            if not routes:
                return None

            # duration ist in Sekunden
            duration_seconds = routes[0]["duration"]
            minutes = int(duration_seconds / 60)

            return TransitResult(
                origin_hash=origin_hash,
                company_id=company_id,
                transit_minutes=minutes,
                mode="car",
                api_used="osrm",
            )
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.warning("OSRM Fehler: %s", exc)
            return None

    async def close(self) -> None:
        """Schließe den HTTP-Client falls wir ihn selbst erstellt haben."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
