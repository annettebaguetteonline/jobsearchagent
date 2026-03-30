"""API-Endpoints für Stellenangebote: Liste, Detail, Status-Update."""

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.db.database import get_db
from app.db.queries import (
    get_default_user_id,
    get_job_with_details,
    get_jobs_paginated,
    update_job_status,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Response-Modelle ────────────────────────────────────────────────────────


class JobListItem(BaseModel):
    id: int
    canonical_id: str
    title: str
    company_name: str | None
    company_city: str | None
    company_remote_policy: str | None
    company_careers_url: str | None
    location_raw: str | None
    work_model: str | None
    salary_raw: str | None
    deadline: str | None
    first_seen_at: str
    status: str
    stage2_score: float | None
    stage2_recommendation: str | None
    stage1_pass: bool | None
    location_score: float | None
    location_effective_minutes: int | None


class JobListResponse(BaseModel):
    total: int
    jobs: list[JobListItem]


class JobSourceResponse(BaseModel):
    id: int
    url: str
    source_name: str
    source_type: str
    is_canonical: bool


class JobSkillResponse(BaseModel):
    skill: str
    skill_type: str | None
    confidence: float | None


class EvaluationDetailResponse(BaseModel):
    id: int
    stage1_pass: bool | None
    stage1_reason: str | None
    stage2_score: float | None
    stage2_score_breakdown: dict[str, float] | None
    stage2_recommendation: str | None
    stage2_match_reasons: list[str] | None
    stage2_missing_skills: list[str] | None
    stage2_salary_estimate: str | None
    stage2_summary: str | None
    stage2_application_tips: list[str] | None
    location_score: float | None
    location_effective_minutes: int | None
    eval_strategy: str | None
    evaluated_at: str


class FeedbackDetailResponse(BaseModel):
    id: int
    decision: str
    reasoning: str | None
    score_delta: float | None
    decided_at: str


class CompanyDetailResponse(BaseModel):
    name: str | None
    name_normalized: str | None
    address_street: str | None
    address_city: str | None
    address_zip: str | None
    lat: float | None
    lng: float | None
    address_status: str | None
    remote_policy: str | None
    careers_url: str | None
    ats_system: str | None


class JobDetailResponse(BaseModel):
    id: int
    canonical_id: str
    title: str
    location_raw: str | None
    location_status: str
    work_model: str | None
    salary_raw: str | None
    salary_min: int | None
    salary_max: int | None
    deadline: str | None
    first_seen_at: str
    last_seen_at: str
    status: str
    raw_text: str | None
    sector: str | None
    company: CompanyDetailResponse | None
    evaluation: EvaluationDetailResponse | None
    sources: list[JobSourceResponse]
    feedback: list[FeedbackDetailResponse]
    skills: list[JobSkillResponse]


class StatusUpdateRequest(BaseModel):
    status: str


# ─── Hilfsfunktionen ────────────────────────────────────────────────────────


def _parse_json_field_list(value: str | None) -> None | list[str]:
    """Parsed ein JSON-String aus der DB. Gibt None bei None/Fehler zurück."""
    if value is None:
        return None
    try:
        result = json.loads(value)
        if not isinstance(result, list):
            raise TypeError("Retrieved value is not of type list")
        return result
    except (json.JSONDecodeError, TypeError):
        return None


def _parse_json_field_dict(value: str | None) -> None | dict[str, Any]:
    """Parsed ein JSON-String aus der DB. Gibt None bei None/Fehler zurück."""
    if value is None:
        return None
    try:
        result = json.loads(value)
        if not isinstance(result, dict):
            raise TypeError("Retrieved value is not of type dict")
        return result
    except (json.JSONDecodeError, TypeError):
        return None


def _row_to_list_item(row: dict[str, Any]) -> JobListItem:
    """Wandelt eine DB-Zeile (mit JOINs) in ein JobListItem."""
    return JobListItem(
        id=row["id"],
        canonical_id=row["canonical_id"],
        title=row["title"],
        company_name=row.get("company_name"),
        company_city=row.get("company_city"),
        company_remote_policy=row.get("company_remote_policy"),
        company_careers_url=row.get("company_careers_url"),
        location_raw=row.get("location_raw"),
        work_model=row.get("work_model"),
        salary_raw=row.get("salary_raw"),
        deadline=row.get("deadline"),
        first_seen_at=row["first_seen_at"],
        status=row["status"],
        stage2_score=row.get("stage2_score"),
        stage2_recommendation=row.get("stage2_recommendation"),
        stage1_pass=bool(row["stage1_pass"]) if row.get("stage1_pass") is not None else None,
        location_score=row.get("location_score"),
        location_effective_minutes=row.get("location_effective_minutes"),
    )


def _build_detail_response(data: dict[str, Any]) -> JobDetailResponse:
    """Baut die Detail-Response aus dem Query-Ergebnis zusammen."""
    # Company
    company = None
    if data.get("company_name") is not None:
        company = CompanyDetailResponse(
            name=data.get("company_name"),
            name_normalized=data.get("company_name_normalized"),
            address_street=data.get("address_street"),
            address_city=data.get("address_city"),
            address_zip=data.get("address_zip"),
            lat=data.get("company_lat"),
            lng=data.get("company_lng"),
            address_status=data.get("address_status"),
            remote_policy=data.get("remote_policy"),
            careers_url=data.get("careers_url"),
            ats_system=data.get("ats_system"),
        )

    # Evaluation
    evaluation = None
    ev = data.get("evaluation")
    if ev is not None:
        evaluation = EvaluationDetailResponse(
            id=ev["id"],
            stage1_pass=bool(ev["stage1_pass"]) if ev.get("stage1_pass") is not None else None,
            stage1_reason=ev.get("stage1_reason"),
            stage2_score=ev.get("stage2_score"),
            stage2_score_breakdown=_parse_json_field_dict(ev.get("stage2_score_breakdown")),
            stage2_recommendation=ev.get("stage2_recommendation"),
            stage2_match_reasons=_parse_json_field_list(ev.get("stage2_match_reasons")),
            stage2_missing_skills=_parse_json_field_list(ev.get("stage2_missing_skills")),
            stage2_salary_estimate=ev.get("stage2_salary_estimate"),
            stage2_summary=ev.get("stage2_summary"),
            stage2_application_tips=_parse_json_field_list(ev.get("stage2_application_tips")),
            location_score=ev.get("location_score"),
            location_effective_minutes=ev.get("location_effective_minutes"),
            eval_strategy=ev.get("eval_strategy"),
            evaluated_at=ev["evaluated_at"],
        )

    # Sources
    sources = [
        JobSourceResponse(
            id=s["id"],
            url=s["url"],
            source_name=s["source_name"],
            source_type=s["source_type"],
            is_canonical=bool(s["is_canonical"]),
        )
        for s in data.get("sources", [])
    ]

    # Feedback
    feedback = [
        FeedbackDetailResponse(
            id=f["id"],
            decision=f["decision"],
            reasoning=f.get("reasoning"),
            score_delta=f.get("score_delta"),
            decided_at=f["decided_at"],
        )
        for f in data.get("feedback", [])
    ]

    # Skills
    skills = [
        JobSkillResponse(
            skill=sk["skill"],
            skill_type=sk.get("skill_type"),
            confidence=sk.get("confidence"),
        )
        for sk in data.get("skills", [])
    ]

    return JobDetailResponse(
        id=data["id"],
        canonical_id=data["canonical_id"],
        title=data["title"],
        location_raw=data.get("location_raw"),
        location_status=data.get("location_status", "unknown"),
        work_model=data.get("work_model"),
        salary_raw=data.get("salary_raw"),
        salary_min=data.get("salary_min"),
        salary_max=data.get("salary_max"),
        deadline=data.get("deadline"),
        first_seen_at=data["first_seen_at"],
        last_seen_at=data["last_seen_at"],
        status=data["status"],
        raw_text=data.get("raw_text"),
        sector=data.get("sector"),
        company=company,
        evaluation=evaluation,
        sources=sources,
        feedback=feedback,
        skills=skills,
    )


# ─── Endpoints ──────────────────────────────────────────────────────────────


@router.get("")
async def list_jobs(
    user_id: str | None = None,
    status: str | None = None,
    min_score: float | None = None,
    work_model: str | None = None,
    source: str | None = None,
    search: str | None = None,
    has_deadline: bool | None = None,
    sort_by: str = "date",
    sort_dir: str = "desc",
    limit: int = Query(default=50, le=200),
    offset: int = 0,
) -> JobListResponse:
    """Paginierte, filterbare Job-Liste mit Evaluierungs-Daten."""
    async for db in get_db():
        uid = user_id or await get_default_user_id(db)
        total, rows = await get_jobs_paginated(
            db,
            user_id=uid,
            status=status,
            min_score=min_score,
            work_model=work_model,
            source=source,
            search=search,
            has_deadline=has_deadline,
            sort_by=sort_by,
            sort_dir=sort_dir,
            limit=limit,
            offset=offset,
        )
        jobs = [_row_to_list_item(row) for row in rows]
        return JobListResponse(total=total, jobs=jobs)
    raise RuntimeError("Keine Datenbankverbindung verfügbar")


@router.get("/{job_id}")
async def get_job(job_id: int, user_id: str | None = None) -> JobDetailResponse:
    """Vollständige Job-Details mit Evaluation, Sources, Feedback und Skills."""
    async for db in get_db():
        uid = user_id or await get_default_user_id(db)
        data = await get_job_with_details(db, job_id, uid)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} nicht gefunden")
        return _build_detail_response(data)
    raise RuntimeError("Keine Datenbankverbindung verfügbar")


@router.patch("/{job_id}/status")
async def patch_job_status(job_id: int, request: StatusUpdateRequest) -> dict[str, str | int]:
    """Status eines Jobs aktualisieren (z.B. 'new' → 'reviewed')."""
    async for db in get_db():
        try:
            updated = await update_job_status(db, job_id, request.status)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not updated:
            raise HTTPException(status_code=404, detail=f"Job {job_id} nicht gefunden")
        return {"job_id": job_id, "status": request.status}
    raise RuntimeError("Keine Datenbankverbindung verfügbar")
