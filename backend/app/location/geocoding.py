"""Nominatim Geocoding Client — kostenlos, kein API-Key nötig.

Nominatim Usage Policy:
- Max 1 Request/Sekunde
- Sinnvoller User-Agent erforderlich
- Keine Bulk-Geocoding (wir cachen in companies-Tabelle)
"""

import asyncio
import logging
import time

import httpx

from app.location.models import GeocodingResult

logger = logging.getLogger(__name__)


class NominatimClient:
    """Geocoding via OpenStreetMap Nominatim."""

    BASE_URL = "https://nominatim.openstreetmap.org/search"
    USER_AGENT = "JobSearchAgent/0.1 (private job search tool)"
    TIMEOUT = 10.0

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        rate_limit_seconds: float = 1.1,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._rate_limit = rate_limit_seconds
        self._last_request_at: float = 0.0

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.TIMEOUT,
                headers={"User-Agent": self.USER_AGENT},
            )
        return self._client

    async def _rate_limit_wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._rate_limit:
            await asyncio.sleep(self._rate_limit - elapsed)
        self._last_request_at = time.monotonic()

    async def geocode(self, query: str) -> GeocodingResult | None:
        """Geocode einen Freitext-String. Gibt None zurück wenn nichts gefunden."""
        client = await self._ensure_client()
        await self._rate_limit_wait()

        try:
            resp = await client.get(
                self.BASE_URL,
                params={
                    "q": query,
                    "format": "json",
                    "limit": "1",
                    "countrycodes": "de",
                },
            )
            resp.raise_for_status()
            results = resp.json()

            if not results:
                logger.debug("Nominatim: keine Ergebnisse für %r", query)
                return None

            hit = results[0]
            return GeocodingResult(
                lat=float(hit["lat"]),
                lng=float(hit["lon"]),
                display_name=hit["display_name"],
                source="nominatim",
            )
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.warning("Nominatim-Fehler für %r: %s", query, exc)
            return None

    async def geocode_structured(
        self,
        city: str,
        postal_code: str | None = None,
        country: str = "Germany",
    ) -> GeocodingResult | None:
        """Strukturierte Geocoding-Abfrage."""
        client = await self._ensure_client()
        await self._rate_limit_wait()

        params: dict[str, str] = {
            "city": city,
            "country": country,
            "format": "json",
            "limit": "1",
            "countrycodes": "de",
        }
        if postal_code:
            params["postalcode"] = postal_code

        try:
            resp = await client.get(self.BASE_URL, params=params)
            resp.raise_for_status()
            results = resp.json()

            if not results:
                return None

            hit = results[0]
            return GeocodingResult(
                lat=float(hit["lat"]),
                lng=float(hit["lon"]),
                display_name=hit["display_name"],
                source="nominatim",
            )
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.warning("Nominatim structured Fehler: %s", exc)
            return None

    async def close(self) -> None:
        """Schließe den HTTP-Client falls wir ihn selbst erstellt haben."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
