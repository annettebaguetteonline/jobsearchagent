"""4-Stufen Firmenadress-Auflösung.

Stufe 1: DB-Lookup (Firma schon aufgelöst?)
Stufe 2: Impressum-Scraping von der Job-URL
Stufe 3: Web-Suche nach Firmen-Impressum (DuckDuckGo)
Stufe 4: Nominatim Geocoding aus location_raw
"""

import logging
import re
from urllib.parse import urlparse

import aiosqlite
import httpx
from bs4 import BeautifulSoup

from app.db.queries import (
    get_company,
    mark_company_address_failed,
    update_company_address,
)
from app.location.geocoding import NominatimClient
from app.location.models import CompanyAddress

logger = logging.getLogger(__name__)


class AddressResolver:
    """Löst Firmenadressen über eine 4-Stufen-Pipeline auf."""

    def __init__(
        self,
        geocoder: NominatimClient,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._geocoder = geocoder
        self._http_client = http_client
        self._owns_client = http_client is None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self._http_client

    async def resolve(
        self,
        db: aiosqlite.Connection,
        company_id: int,
        company_name: str,
        location_raw: str | None = None,
        source_url: str | None = None,
    ) -> CompanyAddress | None:
        """Versuche die Firmenadresse über alle 4 Stufen aufzulösen."""

        # Stufe 1: DB-Lookup
        result = await self._stage1_db_lookup(db, company_id)
        if result is not None:
            return result

        # Stufe 2: Impressum-Scraping
        if source_url:
            result = await self._stage2_impressum_scraping(db, company_id, source_url)
            if result is not None:
                return result

        # Stufe 3: Web-Suche
        result = await self._stage3_web_search(db, company_id, company_name)
        if result is not None:
            return result

        # Stufe 4: Nominatim Geocoding
        if location_raw:
            result = await self._stage4_nominatim(db, company_id, location_raw)
            if result is not None:
                return result

        # Alle Stufen fehlgeschlagen
        await mark_company_address_failed(db, company_id)
        logger.info(
            "Adressauflösung fehlgeschlagen für Company %d (%s)",
            company_id,
            company_name,
        )
        return None

    async def _stage1_db_lookup(
        self, db: aiosqlite.Connection, company_id: int
    ) -> CompanyAddress | None:
        """Prüfe ob die Firma schon eine aufgelöste Adresse hat."""
        company = await get_company(db, company_id)
        if company is None:
            return None
        if company.address_status != "found":
            return None

        return CompanyAddress(
            street=company.address_street,
            city=company.address_city,
            zip_code=company.address_zip,
            lat=company.lat,
            lng=company.lng,
            source="db",
            status="found",
        )

    async def _stage2_impressum_scraping(
        self,
        db: aiosqlite.Connection,
        company_id: int,
        source_url: str,
    ) -> CompanyAddress | None:
        """Versuche die Adresse aus dem Impressum der Job-Seite zu extrahieren."""
        client = await self._ensure_client()

        try:
            parsed = urlparse(source_url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"

            for path in ["/impressum", "/imprint", "/about/impressum"]:
                try:
                    resp = await client.get(
                        f"{base_url}{path}",
                        follow_redirects=True,
                        timeout=10.0,
                    )
                    if resp.status_code == 200:
                        address = _extract_german_address(resp.text)
                        if address is not None:
                            street, zip_code, city = address
                            geo = await self._geocoder.geocode(
                                f"{street}, {zip_code} {city}" if street else f"{zip_code} {city}"
                            )
                            await update_company_address(
                                db,
                                company_id,
                                street=street,
                                city=city,
                                zip_code=zip_code,
                                lat=geo.lat if geo else None,
                                lng=geo.lng if geo else None,
                                source="impressum",
                            )
                            return CompanyAddress(
                                street=street,
                                city=city,
                                zip_code=zip_code,
                                lat=geo.lat if geo else None,
                                lng=geo.lng if geo else None,
                                source="impressum",
                                status="found",
                            )
                except httpx.HTTPError:
                    continue
        except Exception as exc:
            logger.debug("Impressum-Scraping fehlgeschlagen: %s", exc)

        return None

    async def _stage3_web_search(
        self,
        db: aiosqlite.Connection,
        company_id: int,
        company_name: str,
    ) -> CompanyAddress | None:
        """Suche das Impressum der Firma via DuckDuckGo."""
        try:
            from duckduckgo_search import DDGS

            with DDGS() as ddgs:
                results = ddgs.text(
                    f"{company_name} Impressum Adresse",
                    max_results=3,
                    region="de-de",
                )

            if not results:
                return None

            client = await self._ensure_client()
            for result in results:
                url = result.get("href") or result.get("link", "")
                if not url:
                    continue
                try:
                    resp = await client.get(url, follow_redirects=True, timeout=10.0)
                    if resp.status_code != 200:
                        continue
                    address = _extract_german_address(resp.text)
                    if address is not None:
                        street, zip_code, city = address
                        geo = await self._geocoder.geocode(
                            f"{street}, {zip_code} {city}" if street else f"{zip_code} {city}"
                        )
                        await update_company_address(
                            db,
                            company_id,
                            street=street,
                            city=city,
                            zip_code=zip_code,
                            lat=geo.lat if geo else None,
                            lng=geo.lng if geo else None,
                            source="searxng",
                        )
                        return CompanyAddress(
                            street=street,
                            city=city,
                            zip_code=zip_code,
                            lat=geo.lat if geo else None,
                            lng=geo.lng if geo else None,
                            source="searxng",
                            status="found",
                        )
                except httpx.HTTPError:
                    continue

        except Exception as exc:
            logger.warning("Web-Suche fehlgeschlagen: %s", exc)

        return None

    async def _stage4_nominatim(
        self,
        db: aiosqlite.Connection,
        company_id: int,
        location_raw: str,
    ) -> CompanyAddress | None:
        """Geocode location_raw direkt — gibt lat/lng aber keine Straßenadresse."""
        geo = await self._geocoder.geocode(location_raw)
        if geo is None:
            return None

        # Versuche Stadt/PLZ aus display_name zu extrahieren
        parts = [p.strip() for p in geo.display_name.split(",")]
        city = parts[0] if parts else None
        zip_code = None
        for part in parts:
            if re.match(r"^\d{5}$", part.strip()):
                zip_code = part.strip()
                break

        await update_company_address(
            db,
            company_id,
            street=None,
            city=city,
            zip_code=zip_code,
            lat=geo.lat,
            lng=geo.lng,
            source="nominatim",
        )
        return CompanyAddress(
            street=None,
            city=city,
            zip_code=zip_code,
            lat=geo.lat,
            lng=geo.lng,
            source="nominatim",
            status="found",
        )

    async def close(self) -> None:
        """Schließe den HTTP-Client falls wir ihn selbst erstellt haben."""
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None


def _extract_german_address(
    html: str,
) -> tuple[str | None, str | None, str | None] | None:
    """Extrahiere deutsche Adresse (Straße, PLZ, Ort) aus HTML.

    Returns:
        (street, zip_code, city) oder None wenn nichts gefunden.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")

    # Muster: PLZ + Ort (5 Ziffern + Wort)
    plz_city_match = re.search(
        r"(\d{5})\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[a-zäöüß]+)*(?:\s+am\s+\w+)?)",
        text,
    )
    if plz_city_match is None:
        return None

    zip_code = plz_city_match.group(1)
    city = plz_city_match.group(2).strip()

    # Suche Straße in der Nähe (1-3 Zeilen davor)
    lines = text.split("\n")
    plz_line_idx = None
    for i, line in enumerate(lines):
        if zip_code in line and city in line:
            plz_line_idx = i
            break

    street = None
    if plz_line_idx is not None:
        search_range = lines[max(0, plz_line_idx - 3) : plz_line_idx + 1]
        for line in search_range:
            street_match = re.search(
                r"([A-ZÄÖÜ][a-zäöüß]+"
                r"(?:straße|str\.|weg|platz|allee|gasse|ring|damm|ufer)"
                r"\s*\d+\s*[a-zA-Z]?)",
                line,
            )
            if street_match:
                street = street_match.group(1).strip()
                break

    return (street, zip_code, city)
