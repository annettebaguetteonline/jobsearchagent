"""Feedback-Seed-Loader für den Kaltstart der Evaluierungs-Pipeline.

Lädt manuell erstellte Feedback-Einträge aus einer YAML-Datei in die DB.
Idempotent: bereits vorhandene Seeds werden übersprungen.
"""

import logging
from pathlib import Path
from typing import Any

import aiosqlite
import yaml

from app.db.models import FeedbackCreate, now_iso
from app.db.queries import get_seed_feedback, insert_feedback

logger = logging.getLogger(__name__)

_DEFAULT_SEED_FILE = Path(__file__).resolve().parents[3] / "data" / "feedback_seed.yaml"


def _load_yaml(seed_file: Path) -> list[dict[str, Any]]:
    """Lese und validiere die YAML-Seed-Datei.

    Returns:
        Liste der Seed-Einträge als Dicts.

    Raises:
        FileNotFoundError: Seed-Datei existiert nicht.
        ValueError: YAML-Struktur ungültig.
    """
    if not seed_file.exists():
        raise FileNotFoundError(f"Seed-Datei nicht gefunden: {seed_file}")

    with open(seed_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "seeds" not in data:
        raise ValueError(f"YAML muss einen 'seeds'-Schlüssel enthalten: {seed_file}")

    seeds = data["seeds"]
    if not isinstance(seeds, list) or len(seeds) == 0:
        raise ValueError(f"'seeds' muss eine nicht-leere Liste sein: {seed_file}")

    # Pflichtfelder prüfen
    required = {"job_title", "company", "decision", "reasoning"}
    for i, seed in enumerate(seeds):
        missing = required - set(seed.keys())
        if missing:
            raise ValueError(f"Seed #{i + 1} fehlt: {missing}")

    return seeds


async def load_seed_feedback(
    db: aiosqlite.Connection,
    user_id: str,
    seed_file: Path = _DEFAULT_SEED_FILE,
) -> int:
    """Lade Seed-Feedback aus YAML in die Datenbank.

    Idempotent: bereits vorhandene Seeds werden übersprungen.
    Prüft die Anzahl bestehender is_seed=1 Einträge für den User.

    Args:
        db: Datenbankverbindung.
        user_id: User-ID für die Seeds.
        seed_file: Pfad zur YAML-Datei.

    Returns:
        Anzahl neu eingefügter Seeds.
    """
    seeds = _load_yaml(seed_file)

    # Idempotenz-Check: bereits vorhandene Seeds zählen
    existing = await get_seed_feedback(db, user_id)
    if len(existing) >= len(seeds):
        logger.info(
            "Seeds bereits vorhanden (%d/%d) für user=%s — übersprungen",
            len(existing),
            len(seeds),
            user_id,
        )
        return 0

    # Bestehende Seed-Titel sammeln für Duplikat-Erkennung
    existing_titles: set[str] = set()
    for fb in existing:
        if fb.reasoning:
            # Reasoning enthält Informationen zum Matching
            existing_titles.add(fb.reasoning)

    inserted = 0
    ts = now_iso()

    # Temporarily disable FK checks (seeds use negative pseudo job IDs)
    await db.execute("PRAGMA foreign_keys=OFF")

    try:
        for seed in seeds:
            reasoning = str(seed["reasoning"])
            if reasoning in existing_titles:
                logger.debug("Seed übersprungen (existiert): %s", seed["job_title"])
                continue

            # Pseudo-Job-ID generieren: negative IDs für Seeds (kollidieren nicht mit echten Jobs)
            pseudo_job_id = -(inserted + len(existing) + 1)

            model_score_val: float | None = None
            if seed.get("model_score") is not None:
                model_score_val = float(seed["model_score"])

            score_delta_val: float | None = None
            if seed.get("score_delta") is not None:
                score_delta_val = float(seed["score_delta"])

            feedback_entry: FeedbackCreate = FeedbackCreate(
                job_id=pseudo_job_id,
                user_id=user_id,
                decision=str(seed["decision"]).upper(),
                reasoning=reasoning,
                model_score=model_score_val,
                model_recommendation=None,
                score_delta=score_delta_val,
                job_snapshot=None,
                model_reasoning_snapshot=None,
                decided_at=ts,
                feedback_version=1,
                is_seed=True,
            )
            await insert_feedback(db, feedback_entry)
            inserted += 1
            logger.debug("Seed eingefügt: %s — %s", seed["job_title"], seed["decision"])
    finally:
        # Re-enable FK checks
        await db.execute("PRAGMA foreign_keys=ON")

    logger.info(
        "Seed-Feedback geladen: %d neu, %d bereits vorhanden für user=%s",
        inserted,
        len(existing),
        user_id,
    )
    return inserted
