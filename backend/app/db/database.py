"""Datenbankverbindung und Migrations-Initialisierung."""

import logging
from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite

from app.core.config import settings

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def get_db(db_path: Path | None = None) -> AsyncIterator[aiosqlite.Connection]:
    """Async-Kontextmanager für eine SQLite-Verbindung.

    In Production wird settings.db_path verwendet.
    Tests übergeben den tmp_db-Pfad explizit.
    """
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        yield db


async def init_db(db_path: Path | None = None) -> None:
    """Führt alle ausstehenden Migrationen aus.

    Legt eine _migrations-Tabelle an und merkt sich welche .sql-Dateien
    bereits angewandt wurden – idempotent.
    """
    async for db in get_db(db_path):
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS _migrations (
                filename  TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.commit()

        sql_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
        for sql_file in sql_files:
            row = await db.execute_fetchall(
                "SELECT 1 FROM _migrations WHERE filename = ?", (sql_file.name,)
            )
            if row:
                continue

            logger.info("Applying migration: %s", sql_file.name)
            sql = sql_file.read_text(encoding="utf-8")
            await db.executescript(sql)
            await db.execute("INSERT INTO _migrations (filename) VALUES (?)", (sql_file.name,))
            await db.commit()
            logger.info("Migration applied: %s", sql_file.name)
