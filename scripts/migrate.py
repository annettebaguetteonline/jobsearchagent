"""Migrations-CLI: python scripts/migrate.py upgrade

Führt alle ausstehenden SQL-Migrationen aus.
Muss vom Repo-Root aus aufgerufen werden.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Backend-Package aus dem Repo-Root erreichbar machen
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.db.database import _MIGRATIONS_DIR, get_db, init_db  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def _show_status() -> None:
    """Zeigt welche Migrationen bereits angewandt wurden."""
    async for db in get_db():
        try:
            rows = await db.execute_fetchall(
                "SELECT filename, applied_at FROM _migrations ORDER BY filename"
            )
            if rows:
                print("Angewandte Migrationen:")
                for row in rows:
                    print(f"  ✓ {row['filename']}  ({row['applied_at']})")
            else:
                print("Keine Migrationen angewandt.")
        except Exception:  # noqa: BLE001
            print("_migrations-Tabelle existiert noch nicht.")

        pending = [
            f.name
            for f in sorted(_MIGRATIONS_DIR.glob("*.sql"))
            if not any(r["filename"] == f.name for r in rows)
        ]
        if pending:
            print("Ausstehende Migrationen:")
            for name in pending:
                print(f"  ○ {name}")


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "upgrade"

    if command == "upgrade":
        asyncio.run(init_db())
        print("Migrationen abgeschlossen.")
    elif command == "status":
        asyncio.run(_show_status())
    else:
        print(f"Unbekannter Befehl: {command}")
        print("Verwendung: python scripts/migrate.py [upgrade|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()
