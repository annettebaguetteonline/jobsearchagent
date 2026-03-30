"""API-Endpoints für Unternehmen: Detail und Suche."""

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.db.database import get_db
from app.db.queries import get_company

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Response-Modelle ────────────────────────────────────────────────────────


class CompanyResponse(BaseModel):
    id: int
    name: str
    name_normalized: str
    name_aliases: list[str] | None
    address_street: str | None
    address_city: str | None
    address_zip: str | None
    lat: float | None
    lng: float | None
    address_status: str
    address_source: str | None
    remote_policy: str
    careers_url: str | None
    ats_system: str | None


class CompanySearchItem(BaseModel):
    id: int
    name: str
    address_city: str | None


class CompanySearchResponse(BaseModel):
    total: int
    companies: list[CompanySearchItem]


# ─── Hilfsfunktionen ────────────────────────────────────────────────────────


def _company_to_response(row: dict) -> CompanyResponse:  # type: ignore[type-arg]
    """Wandelt ein Company-dict in eine API-Response."""
    import json

    aliases = None
    if row.get("name_aliases"):
        try:
            aliases = json.loads(row["name_aliases"])
        except (json.JSONDecodeError, TypeError):
            aliases = None

    return CompanyResponse(
        id=row["id"],
        name=row["name"],
        name_normalized=row["name_normalized"],
        name_aliases=aliases,
        address_street=row.get("address_street"),
        address_city=row.get("address_city"),
        address_zip=row.get("address_zip"),
        lat=row.get("lat"),
        lng=row.get("lng"),
        address_status=row.get("address_status", "unknown"),
        address_source=row.get("address_source"),
        remote_policy=row.get("remote_policy", "unknown"),
        careers_url=row.get("careers_url"),
        ats_system=row.get("ats_system"),
    )


# ─── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/{company_id}")
async def get_company_detail(company_id: int) -> CompanyResponse:
    """Einzelnes Unternehmen mit allen Details."""
    async for db in get_db():
        company = await get_company(db, company_id)
        if company is None:
            raise HTTPException(status_code=404, detail=f"Unternehmen {company_id} nicht gefunden")
        return _company_to_response(company.model_dump())
    raise RuntimeError("Keine Datenbankverbindung verfügbar")


@router.get("")
async def search_companies(
    search: str = Query(default="", min_length=0),
    limit: int = Query(default=20, le=100),
) -> CompanySearchResponse:
    """Unternehmen nach Name suchen (für Autocomplete)."""
    async for db in get_db():
        if search:
            cursor = await db.execute(
                """
                SELECT id, name, address_city FROM companies
                WHERE name LIKE ? OR name_normalized LIKE ?
                ORDER BY name LIMIT ?
                """,
                (f"%{search}%", f"%{search.lower()}%", limit),
            )
        else:
            cursor = await db.execute(
                "SELECT id, name, address_city FROM companies ORDER BY name LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()

        count_cursor = await db.execute("SELECT COUNT(*) as cnt FROM companies")
        count_row = await count_cursor.fetchone()
        total = count_row["cnt"] if count_row else 0

        items = [
            CompanySearchItem(id=r["id"], name=r["name"], address_city=r["address_city"])
            for r in rows
        ]
        return CompanySearchResponse(total=total, companies=items)
    raise RuntimeError("Keine Datenbankverbindung verfügbar")
