"""Location-Pipeline Orchestrator.

Verarbeitet Jobs in folgendem Ablauf:
1. location_raw parsen
2. Remote-Check → Score 1.0, fertig
3. Work-Model aus raw_text erkennen (falls NULL)
4. Firmenadresse auflösen (4 Stufen)
5. Heimatadresse geocoden (einmalig, gecacht)
6. Transit-Zeiten berechnen (ÖPNV + Auto)
7. Transit-Cache prüfen/füllen
8. Location-Score berechnen
9. DB aktualisieren
"""

import logging

import aiosqlite

from app.core.config import settings
from app.db.models import Job
from app.db.queries import (
    get_company,
    get_jobs_needing_location_score,
    get_transit_cached,
    update_job_location_status,
    upsert_transit_cache,
)
from app.location.geocoding import NominatimClient
from app.location.models import LocationScore, compute_location_score
from app.location.parser import (
    detect_work_model_from_text,
    extract_hybrid_days,
    parse_location_raw,
)
from app.location.resolver import AddressResolver
from app.location.transit import (
    CarRoutingClient,
    PublicTransitClient,
    hash_home_address,
)

logger = logging.getLogger(__name__)


class LocationPipeline:
    """Orchestriert die vollständige Location-Auflösung und -Bewertung."""

    def __init__(self) -> None:
        self._geocoder = NominatimClient()
        self._resolver = AddressResolver(geocoder=self._geocoder)
        self._public_transit = PublicTransitClient()
        self._car_routing = CarRoutingClient()
        self._home_coords: tuple[float, float] | None = None

    async def _get_home_coords(self) -> tuple[float, float] | None:
        """Geocode die Heimatadresse (einmalig, im Speicher gecacht)."""
        if self._home_coords is not None:
            return self._home_coords

        result = await self._geocoder.geocode(settings.home_address)
        if result is None:
            logger.error(
                "Heimatadresse konnte nicht geocoded werden: %s",
                settings.home_address,
            )
            return None

        self._home_coords = (result.lat, result.lng)
        logger.info(
            "Heimatadresse geocoded: %s → %.4f, %.4f",
            settings.home_address,
            result.lat,
            result.lng,
        )
        return self._home_coords

    async def process_job(
        self,
        db: aiosqlite.Connection,
        job: Job,
    ) -> LocationScore:
        """Verarbeite einen einzelnen Job durch die Location-Pipeline.

        Ablauf:
        1. Parse location_raw
        2. Bestimme work_model (aus Job oder raw_text)
        3. Remote? → Score 1.0, fertig
        4. Löse Firmenadresse auf
        5. Berechne Transit-Zeiten (ÖPNV + Auto)
        6. Berechne Score
        7. Aktualisiere DB
        """
        origin_hash = hash_home_address(settings.home_address)
        max_commute = settings.max_commute_min

        # 1. Parse location_raw
        parsed = parse_location_raw(job.location_raw or "")

        # 2. Work-Model bestimmen
        work_model = job.work_model
        hybrid_days = None

        if work_model is None and job.raw_text:
            work_model = detect_work_model_from_text(job.raw_text)
            hybrid_days = extract_hybrid_days(job.raw_text)
        elif work_model == "hybrid" and job.raw_text:
            hybrid_days = extract_hybrid_days(job.raw_text)

        # 3. Remote-Check
        if parsed.is_remote or work_model == "remote":
            score = compute_location_score(
                transit_minutes_public=None,
                transit_minutes_car=None,
                work_model="remote",
                hybrid_days=None,
                max_commute_min=max_commute,
            )
            await update_job_location_status(db, job.id, "resolved")
            return score

        # 4. Firmenadresse auflösen
        company_address = None
        if job.company_id is not None:
            # Hole die kanonische Source-URL für Impressum-Scraping
            cursor = await db.execute(
                """SELECT url FROM job_sources
                   WHERE job_id = ? AND is_canonical = 1
                   LIMIT 1""",
                (job.id,),
            )
            row = await cursor.fetchone()
            source_url = row["url"] if row else None

            company = await get_company(db, job.company_id)
            company_name = company.name if company else "Unknown"

            company_address = await self._resolver.resolve(
                db=db,
                company_id=job.company_id,
                company_name=company_name,
                location_raw=job.location_raw,
                source_url=source_url,
            )

        # 5. Transit-Zeiten berechnen
        transit_public: int | None = None
        transit_car: int | None = None

        if company_address and company_address.lat and company_address.lng:
            # 5a. Cache prüfen (ÖPNV)
            if job.company_id is not None:
                cached = await get_transit_cached(db, job.company_id, origin_hash)
                if cached is not None:
                    transit_public = cached
                    logger.debug("Transit-Cache Hit für Company %d", job.company_id)

            # 5b. ÖPNV berechnen (falls kein Cache)
            if transit_public is None:
                public_result = await self._public_transit.compute_transit_time(
                    origin_address=settings.home_address,
                    dest_lat=company_address.lat,
                    dest_lng=company_address.lng,
                    origin_hash=origin_hash,
                    company_id=job.company_id or 0,
                    departure_time=settings.transit_departure_time,
                    departure_weekday=settings.transit_departure_weekday,
                )
                if public_result is not None:
                    transit_public = public_result.transit_minutes
                    if job.company_id is not None:
                        await upsert_transit_cache(
                            db,
                            job.company_id,
                            origin_hash,
                            public_result.transit_minutes,
                            public_result.api_used,
                            ttl_days=settings.transit_cache_ttl_days,
                        )

            # 5c. Auto-Fahrzeit berechnen
            home_coords = await self._get_home_coords()
            if home_coords is not None:
                car_result = await self._car_routing.compute_driving_time(
                    origin_lat=home_coords[0],
                    origin_lng=home_coords[1],
                    dest_lat=company_address.lat,
                    dest_lng=company_address.lng,
                    origin_hash=origin_hash,
                    company_id=job.company_id or 0,
                )
                if car_result is not None:
                    transit_car = car_result.transit_minutes

        # 6. Score berechnen
        score = compute_location_score(
            transit_minutes_public=transit_public,
            transit_minutes_car=transit_car,
            work_model=work_model,
            hybrid_days=hybrid_days,
            max_commute_min=max_commute,
        )

        # 7. DB aktualisieren
        status = "resolved" if (transit_public or transit_car) else "failed"
        await update_job_location_status(db, job.id, status)

        logger.info(
            "Job %d: score=%.2f, ÖPNV=%s min, Auto=%s min, model=%s",
            job.id,
            score.score,
            transit_public,
            transit_car,
            work_model,
        )
        return score

    async def process_batch(
        self,
        db: aiosqlite.Connection,
        limit: int = 50,
    ) -> list[tuple[int, LocationScore]]:
        """Verarbeite einen Batch von Jobs.

        Returns:
            Liste von (job_id, LocationScore) Tupeln.
        """
        jobs = await get_jobs_needing_location_score(db, limit)
        logger.info("Location-Pipeline: %d Jobs zu verarbeiten", len(jobs))

        results: list[tuple[int, LocationScore]] = []
        for i, job in enumerate(jobs, 1):
            try:
                score = await self.process_job(db, job)
                results.append((job.id, score))
                logger.info("  [%d/%d] Job %d → Score %.2f", i, len(jobs), job.id, score.score)
            except Exception:
                logger.exception("Fehler bei Job %d", job.id)
                await update_job_location_status(db, job.id, "failed")

        logger.info(
            "Location-Pipeline fertig: %d/%d erfolgreich",
            len(results),
            len(jobs),
        )
        return results

    async def close(self) -> None:
        """Ressourcen freigeben."""
        await self._geocoder.close()
        await self._public_transit.close()
        await self._car_routing.close()
