"""API-Endpoints für die Location-Pipeline."""

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.database import get_db
from app.location.pipeline import LocationPipeline

logger = logging.getLogger(__name__)
router = APIRouter()


class BatchResult(BaseModel):
    processed: int
    results: list[dict[str, float | int | str | None]]


class LocationStats(BaseModel):
    jobs_total: int
    jobs_resolved: int
    jobs_unknown: int
    jobs_failed: int
    companies_total: int
    companies_with_address: int
    companies_without_address: int
    transit_cache_entries: int


@router.post("/resolve-batch")
async def resolve_batch(limit: int = 50) -> BatchResult:
    """Batch-Auflösung von Location-Scores.

    Verarbeitet bis zu `limit` Jobs ohne Location-Score.
    """
    pipeline = LocationPipeline()
    try:
        async for db in get_db():
            results = await pipeline.process_batch(db, limit=limit)
            return BatchResult(
                processed=len(results),
                results=[
                    {
                        "job_id": job_id,
                        "score": score.score,
                        "effective_minutes": score.effective_minutes,
                        "transit_public": score.transit_minutes_public,
                        "transit_car": score.transit_minutes_car,
                        "work_model": score.work_model,
                        "is_remote": score.is_remote,
                    }
                    for job_id, score in results
                ],
            )
        raise RuntimeError("No database connection available")
    finally:
        await pipeline.close()


@router.get("/stats")
async def location_stats() -> LocationStats:
    """Statistiken der Location-Pipeline."""
    async for db in get_db():
        # Jobs nach location_status
        cursor = await db.execute(
            "SELECT location_status, COUNT(*) as cnt FROM jobs GROUP BY location_status"
        )
        job_stats = {row["location_status"]: row["cnt"] async for row in cursor}

        # Companies nach address_status
        cursor = await db.execute(
            "SELECT address_status, COUNT(*) as cnt FROM companies GROUP BY address_status"
        )
        company_stats = {row["address_status"]: row["cnt"] async for row in cursor}

        # Transit-Cache
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM transit_cache")
        cache_row = await cursor.fetchone()

        return LocationStats(
            jobs_total=sum(job_stats.values()),
            jobs_resolved=job_stats.get("resolved", 0),
            jobs_unknown=job_stats.get("unknown", 0),
            jobs_failed=job_stats.get("failed", 0),
            companies_total=sum(company_stats.values()),
            companies_with_address=company_stats.get("found", 0),
            companies_without_address=company_stats.get("unknown", 0),
            transit_cache_entries=cache_row["cnt"] if cache_row else 0,
        )
    raise RuntimeError("No database connection available")
