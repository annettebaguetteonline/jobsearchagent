"""API-Endpoints für Evaluierungs-Pipeline, Feedback und Profilverwaltung."""

import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from pydantic import BaseModel

from app.db.database import get_db
from app.db.models import (
    Evaluation,
    FeedbackCreate,
    now_iso,
)
from app.db.queries import (
    get_evaluation,
    get_user,
    insert_feedback,
    mark_needs_reevaluation,
    update_user_profile,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Request/Response-Modelle ────────────────────────────────────────────────


class RunStage1Request(BaseModel):
    user_id: str
    limit: int = 100


class Stage1RunResponse(BaseModel):
    processed: int
    passed: int
    skipped: int
    errors: int


class RunStage2Request(BaseModel):
    user_id: str
    limit: int = 50
    strategy: str = "structured_core"


class BatchStatus(BaseModel):
    batch_id: str
    status: str
    completed: int
    total: int
    error_count: int


class EvaluationResponse(BaseModel):
    id: int
    job_id: int
    user_id: str
    stage1_pass: bool | None
    stage1_reason: str | None
    stage2_score: float | None
    stage2_recommendation: str | None
    stage2_match_reasons: list[str] | None
    stage2_missing_skills: list[str] | None
    stage2_salary_estimate: str | None
    stage2_summary: str | None
    stage2_application_tips: list[str] | None
    location_score: float | None
    location_effective_minutes: int | None
    needs_reevaluation: bool
    evaluated_at: str


class EvaluationResultsResponse(BaseModel):
    total: int
    results: list[EvaluationResponse]


class EvaluationStats(BaseModel):
    total_jobs: int
    evaluated: int
    stage1_passed: int
    stage1_skipped: int
    stage2_completed: int
    avg_score: float | None
    recommendations: dict[str, int]


class FeedbackRequest(BaseModel):
    job_id: int
    user_id: str
    decision: str
    reasoning: str | None = None


class ProfileExtractRequest(BaseModel):
    user_id: str


class PreferencePatternItem(BaseModel):
    type: str
    key: str
    value: str | None
    confidence: float | None
    sample_count: int | None


class FeedbackStats(BaseModel):
    total: int
    by_decision: dict[str, int]
    preference_patterns: list[PreferencePatternItem]


# ─── Hilfsfunktionen ────────────────────────────────────────────────────────


def _eval_to_response(ev: Evaluation) -> EvaluationResponse:
    """Wandelt ein Evaluation-Objekt in eine API-Response um."""
    return EvaluationResponse(
        id=ev.id,
        job_id=ev.job_id,
        user_id=ev.user_id,
        stage1_pass=ev.stage1_pass,
        stage1_reason=ev.stage1_reason,
        stage2_score=ev.stage2_score,
        stage2_recommendation=ev.stage2_recommendation,
        stage2_match_reasons=(
            json.loads(ev.stage2_match_reasons) if ev.stage2_match_reasons else None
        ),
        stage2_missing_skills=(
            json.loads(ev.stage2_missing_skills) if ev.stage2_missing_skills else None
        ),
        stage2_salary_estimate=ev.stage2_salary_estimate,
        stage2_summary=ev.stage2_summary,
        stage2_application_tips=(
            json.loads(ev.stage2_application_tips) if ev.stage2_application_tips else None
        ),
        location_score=ev.location_score,
        location_effective_minutes=ev.location_effective_minutes,
        needs_reevaluation=ev.needs_reevaluation,
        evaluated_at=ev.evaluated_at,
    )


async def _run_stage2_task(user_id: str, strategy: str, limit: int) -> None:
    """Background-Task für Stage-2-Batch-Verarbeitung."""
    from app.evaluator.pipeline import EvaluationPipeline

    pipeline = EvaluationPipeline()
    try:
        async for db in get_db():
            result = await pipeline.process_batch_stage2(
                db, user_id, strategy=strategy, limit=limit
            )
            logger.info(
                "Stage-2 abgeschlossen: batch_id=%s, completed=%d, errors=%d",
                result.batch_id,
                result.completed,
                result.errors,
            )
    except Exception:
        logger.exception("Fehler bei Stage-2 Background-Task für user=%s", user_id)
    finally:
        await pipeline.close()


async def _extract_profile_task(user_id: str) -> None:
    """Background-Task für Profil-Extraktion."""
    import hashlib

    from app.core.config import settings
    from app.evaluator.document_parser import DocumentParser
    from app.evaluator.profile_extractor import ProfileExtractor

    extractor = ProfileExtractor(anthropic_key=settings.anthropic_api_key)
    parser = DocumentParser()
    try:
        async for db in get_db():
            user = await get_user(db, user_id)
            if user is None:
                logger.error("User %s nicht gefunden für Profil-Extraktion", user_id)
                return

            # Dokumente aus User-Ordner laden
            folder = Path(user.folder) if user.folder else Path(f"data/users/{user_id}")
            documents = []
            if folder.exists():
                for f in folder.iterdir():
                    if f.is_file():
                        try:
                            documents.append(await parser.parse_file(f))
                        except Exception:
                            logger.warning("Datei konnte nicht geparst werden: %s", f)

            # Profil extrahieren und speichern
            profile = await extractor.extract_profile(documents)
            profile_json = profile.model_dump_json()
            version = hashlib.sha256(profile_json.encode()).hexdigest()[:16]
            await update_user_profile(db, user_id, profile_json, version)
            await mark_needs_reevaluation(db, user_id)
            logger.info("Profil extrahiert für user=%s, version=%s", user_id, version)
    except Exception:
        logger.exception("Fehler bei Profil-Extraktion für user=%s", user_id)


# ─── Stage 1 ────────────────────────────────────────────────────────────────


@router.post("/run-stage1")
async def run_stage1(request: RunStage1Request) -> Stage1RunResponse:
    """Stage-1-Evaluierung (1a + 1b) für alle noch nicht evaluierten Jobs.

    Läuft synchron — verarbeitet bis zu `limit` Jobs und gibt Zusammenfassung zurück.
    """
    from app.evaluator.pipeline import EvaluationPipeline

    pipeline = EvaluationPipeline()
    try:
        async for db in get_db():
            result = await pipeline.process_batch_stage1(db, request.user_id, limit=request.limit)
            return Stage1RunResponse(
                processed=result.processed,
                passed=result.passed,
                skipped=result.skipped_1a + result.skipped_1b,
                errors=result.errors,
            )
        raise RuntimeError("Keine Datenbankverbindung verfügbar")
    finally:
        await pipeline.close()


# ─── Stage 2 ────────────────────────────────────────────────────────────────


@router.post("/run-stage2")
async def run_stage2(request: RunStage2Request, bg: BackgroundTasks) -> dict[str, str]:
    """Stage-2-Evaluierung als Background-Task starten.

    Nutzt die Anthropic Batch API für kosteneffiziente Verarbeitung.
    """
    bg.add_task(_run_stage2_task, request.user_id, request.strategy, request.limit)
    return {"status": "started", "user_id": request.user_id}


# ─── Batch-Status ───────────────────────────────────────────────────────────


@router.get("/batch/{batch_id}")
async def get_batch_status(batch_id: str) -> BatchStatus:
    """Status eines Stage-2-Batch-Laufs abfragen."""
    async for db in get_db():
        cursor = await db.execute(
            """
            SELECT batch_api_id, status, job_count, completed_count, error_count
            FROM evaluation_batches
            WHERE batch_api_id = ?
            """,
            (batch_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Batch nicht gefunden")
        return BatchStatus(
            batch_id=row["batch_api_id"],
            status=row["status"],
            completed=row["completed_count"],
            total=row["job_count"],
            error_count=row["error_count"],
        )
    raise RuntimeError("Keine Datenbankverbindung verfügbar")


# ─── Ergebnisse ─────────────────────────────────────────────────────────────


@router.get("/results")
async def get_results(
    user_id: str,
    min_score: float | None = None,
    recommendation: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> EvaluationResultsResponse:
    """Paginierte, filterbare Liste aller Evaluierungsergebnisse."""
    async for db in get_db():
        # Dynamische WHERE-Klausel aufbauen
        conditions = ["user_id = ?"]
        params: list[str | float | int] = [user_id]

        if min_score is not None:
            conditions.append("stage2_score >= ?")
            params.append(min_score)

        if recommendation is not None:
            conditions.append("stage2_recommendation = ?")
            params.append(recommendation)

        where_clause = " AND ".join(conditions)

        # Total Count — where_clause besteht ausschließlich aus hartcodierten Spalten-
        # namen und Platzhaltern (?), nie aus User-Input → kein SQL-Injection-Risiko
        count_sql = f"SELECT COUNT(*) as cnt FROM evaluations WHERE {where_clause}"  # noqa: S608
        count_cursor = await db.execute(count_sql, tuple(params))
        count_row = await count_cursor.fetchone()
        total = count_row["cnt"] if count_row else 0

        # Paginierte Ergebnisse
        params.extend([limit, offset])
        results_sql = f"""
            SELECT * FROM evaluations
            WHERE {where_clause}
            ORDER BY stage2_score DESC NULLS LAST, evaluated_at DESC
            LIMIT ? OFFSET ?
            """  # noqa: S608
        cursor = await db.execute(results_sql, tuple(params))
        rows = await cursor.fetchall()

        from app.db.queries import _row_to_evaluation

        results = [_eval_to_response(_row_to_evaluation(dict(row))) for row in rows]

        return EvaluationResultsResponse(total=total, results=results)

    raise RuntimeError("Keine Datenbankverbindung verfügbar")


# ─── Statistiken ────────────────────────────────────────────────────────────


@router.get("/stats")
async def get_stats(user_id: str) -> EvaluationStats:
    """Aggregierte Statistiken der Evaluierungs-Pipeline für einen User."""
    async for db in get_db():
        # Grundzählung
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM jobs WHERE is_active = 1",
        )
        row = await cursor.fetchone()
        total_jobs = row["cnt"] if row else 0

        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM evaluations WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        evaluated = row["cnt"] if row else 0

        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM evaluations WHERE user_id = ? AND stage1_pass = 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        stage1_passed = row["cnt"] if row else 0

        cursor = await db.execute(
            """
            SELECT COUNT(*) as cnt FROM evaluations
            WHERE user_id = ? AND (stage1_pass = 0 OR stage1_pass IS NULL)
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        stage1_skipped = row["cnt"] if row else 0

        cursor = await db.execute(
            """
            SELECT COUNT(*) as cnt FROM evaluations
            WHERE user_id = ? AND stage2_score IS NOT NULL
            """,
            (user_id,),
        )
        row = await cursor.fetchone()
        stage2_completed = row["cnt"] if row else 0

        cursor = await db.execute(
            "SELECT AVG(stage2_score) as avg_s FROM evaluations"
            " WHERE user_id = ? AND stage2_score IS NOT NULL",
            (user_id,),
        )
        row = await cursor.fetchone()
        avg_score = round(row["avg_s"], 2) if row and row["avg_s"] is not None else None

        cursor = await db.execute(
            """
            SELECT stage2_recommendation, COUNT(*) as cnt
            FROM evaluations
            WHERE user_id = ? AND stage2_recommendation IS NOT NULL
            GROUP BY stage2_recommendation
            """,
            (user_id,),
        )
        rec_rows = await cursor.fetchall()
        recommendations = {row["stage2_recommendation"]: row["cnt"] for row in rec_rows}

        return EvaluationStats(
            total_jobs=total_jobs,
            evaluated=evaluated,
            stage1_passed=stage1_passed,
            stage1_skipped=stage1_skipped,
            stage2_completed=stage2_completed,
            avg_score=avg_score,
            recommendations=recommendations,
        )
    raise RuntimeError("Keine Datenbankverbindung verfügbar")


# ─── Feedback ───────────────────────────────────────────────────────────────


@router.get("/feedback-stats")
async def get_feedback_stats(user_id: str) -> FeedbackStats:
    """Feedback-Statistiken für einen User: Gesamtanzahl, Verteilung und Präferenzmuster."""
    async for db in get_db():
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM feedback WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        total = row["cnt"] if row else 0

        cursor = await db.execute(
            """
            SELECT decision, COUNT(*) as cnt
            FROM feedback
            WHERE user_id = ?
            GROUP BY decision
            """,
            (user_id,),
        )
        dec_rows = await cursor.fetchall()
        by_decision = {r["decision"]: r["cnt"] for r in dec_rows}

        cursor = await db.execute(
            """
            SELECT pattern_type, pattern_key, pattern_value, confidence, sample_count
            FROM preference_patterns
            WHERE user_id = ? AND is_active = 1
            ORDER BY confidence DESC
            LIMIT 10
            """,
            (user_id,),
        )
        pat_rows = await cursor.fetchall()
        patterns = [
            PreferencePatternItem(
                type=r["pattern_type"],
                key=r["pattern_key"],
                value=r["pattern_value"],
                confidence=r["confidence"],
                sample_count=r["sample_count"],
            )
            for r in pat_rows
        ]

        return FeedbackStats(total=total, by_decision=by_decision, preference_patterns=patterns)
    raise RuntimeError("Keine Datenbankverbindung verfügbar")


@router.post("/feedback")
async def submit_feedback(request: FeedbackRequest) -> dict[str, int | float | None]:
    """Feedback zu einer Evaluierung erfassen.

    Berechnet score_delta aus der bestehenden Evaluierung.
    """
    async for db in get_db():
        # score_delta berechnen falls Evaluierung existiert
        score_delta: float | None = None
        ev = await get_evaluation(db, request.job_id, request.user_id)
        if ev and ev.stage2_score is not None:
            decision_scores = {"APPLY": 9.0, "MAYBE": 6.0, "SKIP": 3.0, "IGNORE": 1.0}
            user_score = decision_scores.get(request.decision.upper(), 5.0)
            score_delta = round(user_score - ev.stage2_score, 2)

        fb = FeedbackCreate(
            job_id=request.job_id,
            user_id=request.user_id,
            decision=request.decision.upper(),
            reasoning=request.reasoning,
            model_score=ev.stage2_score if ev else None,
            model_recommendation=ev.stage2_recommendation if ev else None,
            score_delta=score_delta,
            decided_at=now_iso(),
        )
        fb_id = await insert_feedback(db, fb)

        return {"id": fb_id, "score_delta": score_delta}

    raise RuntimeError("Keine Datenbankverbindung verfügbar")


# ─── Profil ─────────────────────────────────────────────────────────────────


@router.post("/profile/extract")
async def extract_profile(request: ProfileExtractRequest, bg: BackgroundTasks) -> dict[str, str]:
    """Kernprofil-Extraktion als Background-Task starten."""
    bg.add_task(_extract_profile_task, request.user_id)
    return {"status": "started", "user_id": request.user_id}


@router.get("/profile/{user_id}")
async def get_profile(user_id: str) -> dict[str, object]:
    """Gespeichertes Kernprofil eines Users zurückgeben."""
    async for db in get_db():
        user = await get_user(db, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User nicht gefunden")
        if user.profile_json is None:
            raise HTTPException(
                status_code=404,
                detail="Kein Profil vorhanden. Bitte zuerst /profile/extract aufrufen.",
            )
        result: dict[str, object] = json.loads(user.profile_json)
        return result
    raise RuntimeError("Keine Datenbankverbindung verfügbar")


@router.post("/profile/upload")
async def upload_profile_document(user_id: str, file: UploadFile) -> dict[str, str]:
    """Lebenslauf oder Zeugnis hochladen und im User-Verzeichnis speichern."""
    async for db in get_db():
        user = await get_user(db, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User nicht gefunden")

        folder = Path(user.folder) if user.folder else Path(f"data/users/{user_id}")
        folder.mkdir(parents=True, exist_ok=True)

        filename = file.filename or f"upload_{uuid.uuid4().hex[:8]}"
        save_path = folder / filename

        content = await file.read()
        save_path.write_bytes(content)

        logger.info("Dokument gespeichert: %s → %s", filename, save_path)
        return {"filename": filename, "saved_to": str(save_path)}

    raise RuntimeError("Keine Datenbankverbindung verfügbar")
