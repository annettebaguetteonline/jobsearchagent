"""Diagnose-Skript: Analysiert raw_text-Abdeckung nach Zeit."""

import argparse
import asyncio
import logging
from pathlib import Path

import aiosqlite

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def diagnose(db_path: Path) -> None:
    """Führe Diagnose-Queries aus."""
    if not db_path.exists():
        logger.error("DB nicht gefunden: %s", db_path)
        raise SystemExit(1)

    async with aiosqlite.connect(db_path) as db:
        logger.info("Verbunden mit: %s", db_path)
        db.row_factory = aiosqlite.Row

        # ─── Abfrage 1: Coverage nach Woche ─────────────────────────────────
        logger.info("")
        logger.info("─ raw_text ABDECKUNG NACH WOCHE ─")
        rows = await db.execute(
            """
            SELECT
                strftime('%Y-W%W', j.first_seen_at) AS woche,
                COUNT(*) AS total,
                SUM(
                    CASE
                        WHEN j.raw_text IS NOT NULL AND j.raw_text != ''
                        THEN 1 ELSE 0
                    END
                ) AS mit_text,
                ROUND(
                    100.0 * SUM(
                        CASE
                            WHEN j.raw_text IS NOT NULL AND j.raw_text != ''
                            THEN 1 ELSE 0
                        END
                    ) / COUNT(*), 1
                ) AS coverage_pct
            FROM jobs j
            JOIN job_sources js ON js.job_id = j.id
            WHERE js.source_name = 'interamt'
            GROUP BY woche
            ORDER BY woche DESC
            LIMIT 12
            """
        )
        data = await rows.fetchall()
        if data:
            print()
            print(f"{'Woche':<12} {'Total':>8} {'Mit Text':>10} {'Abdeckung':>12}")
            print("─" * 48)
            for row in data:
                print(
                    f"{row['woche']:<12} {row['total']:>8,} "
                    f"{row['mit_text']:>10,} {row['coverage_pct']:>11.1f}%"
                )
        else:
            print("(keine Interamt-Jobs gefunden)")
        print()

        # ─── Abfrage 2: Status-Verteilung ───────────────────────────────────
        logger.info("─ raw_text STATUS-VERTEILUNG ─")
        rows = await db.execute(
            """
            SELECT
                CASE
                    WHEN raw_text IS NULL THEN 'NULL'
                    WHEN raw_text = '' THEN 'leer'
                    WHEN LENGTH(raw_text) < 50 THEN 'sehr_kurz (<50)'
                    ELSE 'ok'
                END AS status,
                COUNT(*) AS anzahl
            FROM jobs j
            JOIN job_sources js ON js.job_id = j.id
            WHERE js.source_name = 'interamt'
            GROUP BY 1
            ORDER BY 2 DESC
            """
        )
        data = await rows.fetchall()
        total = sum(row["anzahl"] for row in data) if data else 0
        if data:
            print()
            print(f"{'Status':<20} {'Anzahl':>10} {'Anteil':>10}")
            print("─" * 45)
            for row in data:
                pct = (row["anzahl"] / total * 100) if total > 0 else 0
                print(f"{row['status']:<20} {row['anzahl']:>10,} {pct:>9.1f}%")
            print("─" * 45)
            print(f"{'GESAMT':<20} {total:>10,}")
        else:
            print("(keine Interamt-Jobs gefunden)")
        print()

        # ─── Zusammenfassung ─────────────────────────────────────────────────
        cursor = await db.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(
                    CASE
                        WHEN raw_text IS NOT NULL AND raw_text != ''
                        THEN 1 ELSE 0
                    END
                ) AS mit_text,
                SUM(
                    CASE
                        WHEN raw_text IS NULL OR raw_text = ''
                        THEN 1 ELSE 0
                    END
                ) AS ohne_text
            FROM jobs j
            JOIN job_sources js ON js.job_id = j.id
            WHERE js.source_name = 'interamt'
            """
        )
        row = await cursor.fetchone()
        if row:
            total = row["total"] or 0
            mit_text = row["mit_text"] or 0
            ohne_text = row["ohne_text"] or 0
            coverage = (mit_text / total * 100) if total > 0 else 0
            logger.info("ZUSAMMENFASSUNG für Interamt:")
            logger.info(
                "  Gesamt: %d | Mit Text: %d | Ohne Text: %d | Coverage: %.1f%%",
                total,
                mit_text,
                ohne_text,
                coverage,
            )
            if coverage < 50:
                logger.warning("  ⚠️  Weniger als 50%% raw_text vorhanden!")
            logger.info("  💡 Tipp: backfill_raw_text.py ausführen um fehlende Texte zu fetchen")
        print()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose: raw_text-Abdeckung analysieren")
    parser.add_argument("--db-path", type=Path, default=Path("./data/jobs.db"))
    args = parser.parse_args()
    await diagnose(args.db_path)


if __name__ == "__main__":
    asyncio.run(main())
