"""API-Endpoints für Klärungsbedarf: Liste, Resolve, URL-Update."""

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.database import get_db
from app.db.models import now_iso

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Response-Modelle ────────────────────────────────────────────────────────


class ClarificationItem(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    issue_type: str
    priority: str
    severity: str
    attempts: list[dict[str, object]] | None
    last_attempt_at: str | None
    resolved: bool
    created_at: str
    # Angereicherte Felder (aus JOINs)
    entity_title: str | None = None
    entity_company: str | None = None
    entity_score: float | None = None


class ClarificationListResponse(BaseModel):
    total: int
    urgent: list[ClarificationItem]
    normal: list[ClarificationItem]


class ResolveRequest(BaseModel):
    resolved_by: str = "manual"
    resolution_note: str | None = None


class UpdateUrlRequest(BaseModel):
    url: str


# ─── Hilfsfunktionen ────────────────────────────────────────────────────────


def _row_to_item(row: dict[str, Any]) -> ClarificationItem:
    """Wandelt eine DB-Zeile in ein ClarificationItem."""
    attempts = None
    if row.get("attempts"):
        try:
            attempts = json.loads(row["attempts"])
        except (json.JSONDecodeError, TypeError):
            pass

    return ClarificationItem(
        id=row["id"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        issue_type=row["issue_type"],
        priority=row["priority"],
        severity=row["severity"],
        attempts=attempts,
        last_attempt_at=row.get("last_attempt_at"),
        resolved=bool(row["resolved"]),
        created_at=row["created_at"],
        entity_title=row.get("entity_title"),
        entity_company=row.get("entity_company"),
        entity_score=row.get("entity_score"),
    )


# ─── Endpoints ──────────────────────────────────────────────────────────────


@router.get("")
async def list_clarifications(
    user_id: str | None = None,
    include_resolved: bool = False,
) -> ClarificationListResponse:
    """Offene Klärungsbedarfe, unterteilt in urgent (rot) und normal (gelb).

    Angereichert mit Job-Titel, Company-Name und Score per JOIN.
    """
    from app.db.queries import get_default_user_id

    async for db in get_db():
        uid = user_id
        if uid is None:
            uid = await get_default_user_id(db)

        resolved_filter = "" if include_resolved else "AND cq.resolved = 0"

        sql = f"""
            SELECT cq.*,
                   j.title as entity_title,
                   c.name as entity_company,
                   e.stage2_score as entity_score
            FROM clarification_queue cq
            LEFT JOIN jobs j ON cq.entity_type = 'job' AND cq.entity_id = j.id
            LEFT JOIN companies c ON (
                (cq.entity_type = 'company' AND cq.entity_id = c.id)
                OR (cq.entity_type = 'job' AND j.company_id = c.id)
            )
            LEFT JOIN evaluations e ON cq.entity_type = 'job' AND cq.entity_id = e.job_id
                AND e.user_id = ?
            WHERE 1=1 {resolved_filter}
            ORDER BY
                CASE cq.severity WHEN 'red' THEN 0 ELSE 1 END,
                e.stage2_score DESC NULLS LAST,
                cq.created_at DESC
        """  # noqa: S608
        cursor = await db.execute(sql, (uid,))
        rows = await cursor.fetchall()

        urgent = []
        normal = []
        for row in rows:
            item = _row_to_item(dict(row))
            if item.severity == "red":
                urgent.append(item)
            else:
                normal.append(item)

        return ClarificationListResponse(
            total=len(urgent) + len(normal),
            urgent=urgent,
            normal=normal,
        )
    raise RuntimeError("Keine Datenbankverbindung verfügbar")


@router.patch("/{item_id}/resolve")
async def resolve_clarification(item_id: int, request: ResolveRequest) -> dict[str, str | int]:
    """Klärungsbedarf als gelöst markieren."""
    async for db in get_db():
        cursor = await db.execute("SELECT id FROM clarification_queue WHERE id = ?", (item_id,))
        if await cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail=f"Eintrag {item_id} nicht gefunden")

        await db.execute(
            """
            UPDATE clarification_queue
            SET resolved = 1, resolved_at = ?, resolved_by = ?, resolution_note = ?
            WHERE id = ?
            """,
            (now_iso(), request.resolved_by, request.resolution_note, item_id),
        )
        await db.commit()
        return {"id": item_id, "status": "resolved"}
    raise RuntimeError("Keine Datenbankverbindung verfügbar")


@router.post("/{item_id}/update-url")
async def update_entity_url(item_id: int, request: UpdateUrlRequest) -> dict[str, str | int]:
    """URL für ein Unternehmen manuell setzen (bei website_unknown).

    Aktualisiert die careers_url des Unternehmens und markiert den
    Klärungsbedarf als gelöst.
    """
    async for db in get_db():
        cursor = await db.execute("SELECT * FROM clarification_queue WHERE id = ?", (item_id,))
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Eintrag {item_id} nicht gefunden")

        row_dict: dict[str, Any] = dict(row)
        if row_dict["entity_type"] == "company":
            await db.execute(
                "UPDATE companies SET careers_url = ?, updated_at = ? WHERE id = ?",
                (request.url, now_iso(), row_dict["entity_id"]),
            )
        elif row_dict["entity_type"] == "job":
            # Job → zugehöriges Unternehmen aktualisieren
            j_cursor = await db.execute(
                "SELECT company_id FROM jobs WHERE id = ?", (row_dict["entity_id"],)
            )
            j_row = await j_cursor.fetchone()
            if j_row and j_row["company_id"]:
                await db.execute(
                    "UPDATE companies SET careers_url = ?, updated_at = ? WHERE id = ?",
                    (request.url, now_iso(), j_row["company_id"]),
                )

        # Klärungsbedarf als gelöst markieren
        await db.execute(
            """
            UPDATE clarification_queue
            SET resolved = 1, resolved_at = ?, resolved_by = 'manual',
                resolution_note = ?
            WHERE id = ?
            """,
            (now_iso(), f"URL gesetzt: {request.url}", item_id),
        )
        await db.commit()
        return {"id": item_id, "url": request.url, "status": "resolved"}
    raise RuntimeError("Keine Datenbankverbindung verfügbar")
