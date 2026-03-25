"""Backfill-Skript: Fetcht fehlende raw_text für Interamt-Jobs aus der DB."""

import argparse
import asyncio
import logging
from pathlib import Path

import aiosqlite
import httpx
from bs4 import BeautifulSoup

from app.db.models import now_iso

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_DETAIL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_DETAIL_CONCURRENCY = 5
_DETAIL_SLEEP = 1.0


async def _fetch_raw_text(client: httpx.AsyncClient, url: str) -> str | None:
    """Fetcht und extrahiert raw_text von einer Detail-Seite."""
    try:
        resp = await client.get(url, timeout=20.0)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Versuche die Selektoren in Reihenfolge
        selectors = [
            ".ia-e-stellenangebot__beschreibung",
            ".ia-e-detail",
            ".ia-e-content",
            "main",
            "article",
        ]

        for selector in selectors:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(separator=" ", strip=True)
                cleaned = " ".join(text.split())
                if len(cleaned) > 100:
                    return cleaned

        # Fallback: body
        body = soup.find("body")
        if body:
            text = body.get_text(separator=" ", strip=True)
            cleaned = " ".join(text.split())
            if len(cleaned) > 100:
                return cleaned

        return None
    except Exception as exc:  # noqa: BLE001
        logger.debug("Detail-Fehler %s: %s", url, exc)
        return None


async def _fetch_with_sem(
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    job_id: int,
    url: str,
    db: aiosqlite.Connection,
) -> bool:
    """Fetcht einen Job-Volltext mit Semaphore."""
    async with sem:
        raw_text = await _fetch_raw_text(client, url)
        if raw_text:
            await db.execute(
                "UPDATE jobs SET raw_text = ?, updated_at = ? WHERE id = ?",
                (raw_text, now_iso(), job_id),
            )
            await db.commit()
        await asyncio.sleep(_DETAIL_SLEEP)
        return raw_text is not None


async def backfill(db_path: Path, limit: int | None = None) -> None:
    """Backfill-Logik."""
    if not db_path.exists():
        logger.error("DB nicht gefunden: %s", db_path)
        raise SystemExit(1)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        logger.info("Verbunden mit: %s", db_path)

        # Lade alle Interamt-Jobs ohne raw_text
        query = """
        SELECT DISTINCT j.id, j.title, js.url
        FROM jobs j
        JOIN job_sources js ON js.job_id = j.id
        WHERE js.source_name = 'interamt'
          AND (j.raw_text IS NULL OR j.raw_text = '')
          AND j.is_active = 1
        ORDER BY j.first_seen_at DESC
        """
        if limit:
            query += f" LIMIT {limit}"

        rows = await db.execute(query)
        jobs = await rows.fetchall()

        if not jobs:
            logger.info("Keine Jobs zum Backfill gefunden")
            return

        total = len(jobs)
        logger.info(
            "Fetche raw_text für %d Jobs (Parallelität: %d) ...",
            total,
            _DETAIL_CONCURRENCY,
        )
        print()

        async with httpx.AsyncClient(
            headers=_DETAIL_HEADERS, timeout=20.0, follow_redirects=True
        ) as client:
            sem = asyncio.Semaphore(_DETAIL_CONCURRENCY)
            tasks = [_fetch_with_sem(sem, client, job["id"], job["url"], db) for job in jobs]

            completed = 0
            success = 0
            for coro in asyncio.as_completed(tasks):
                result = await coro
                completed += 1
                if result:
                    success += 1
                if completed % 50 == 0 or completed == total:
                    logger.info(
                        "raw_text: %d / %d (erfolg: %d)",
                        completed,
                        total,
                        success,
                    )

        logger.info("")
        logger.info("✅ Backfill abgeschlossen: %d / %d erfolg", success, total)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill: fehlende raw_text für Interamt-Jobs fetchen"
    )
    parser.add_argument("--db-path", type=Path, default=Path("./data/jobs.db"))
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max. Anzahl Jobs zum Backfill (default: alle)",
    )
    args = parser.parse_args()
    await backfill(args.db_path, args.limit)


if __name__ == "__main__":
    asyncio.run(main())
