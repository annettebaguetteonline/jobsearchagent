"""Evaluierungs-Pipeline Orchestrator.

Verarbeitet Jobs in folgendem Ablauf:
1. Kernprofil aus User laden
2. Stage 1a: Deterministischer Keyword-Ausschluss
3. Stage 1b: LLM-Vorfilter (Ollama) + Feldextraktion
4. Stage 2: Claude Tiefanalyse (Einzel oder Batch)

Folgt dem Pattern der LocationPipeline:
- process_job() für Einzelauswertung
- process_batch_stage1() für Stage-1-Massenverarbeitung
- process_batch_stage2() für Stage-2-Batch via Anthropic API
"""

import json
import logging
import time
import types

import aiosqlite
from pydantic import BaseModel

from app.core.config import settings
from app.db.models import Company, Job, User, now_iso
from app.evaluator.batch import BatchEvaluator, BatchFlowResult
from app.evaluator.models import ExtractedFields, Stage1bResult
from app.evaluator.stage2 import FeedbackExample, Stage2Evaluator, Stage2Result

logger = logging.getLogger(__name__)


# ─── Ergebnis-Modelle ────────────────────────────────────────────────────────


class EvaluationResult(BaseModel):
    """Ergebnis einer vollständigen Einzelauswertung."""

    job_id: int
    user_id: str
    stage1a_passed: bool
    stage1b_passed: bool | None = None
    stage2_result: Stage2Result | None = None
    extracted_fields: ExtractedFields | None = None
    total_ms: int


class Stage1BatchResult(BaseModel):
    """Ergebnis einer Stage-1-Massenverarbeitung."""

    processed: int
    passed: int
    skipped_1a: int
    skipped_1b: int
    errors: int
    extracted_fields_count: int


# ─── DB-Hilfsfunktionen ─────────────────────────────────────────────────────


async def _create_evaluation(
    db: aiosqlite.Connection,
    job_id: int,
    user_id: str,
    strategy: str | None = None,
) -> int:
    """Erstelle einen neuen Evaluierungs-Eintrag."""
    ts = now_iso()
    cursor = await db.execute(
        """INSERT INTO evaluations
           (job_id, user_id, eval_strategy, evaluated_at)
           VALUES (?, ?, ?, ?)""",
        (job_id, user_id, strategy, ts),
    )
    await db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def _update_evaluation_stage1(
    db: aiosqlite.Connection,
    job_id: int,
    user_id: str,
    passed: bool,
    reason: str | None,
    model: str,
    duration_ms: int,
) -> None:
    """Aktualisiere die Stage-1-Felder einer Evaluation."""
    await db.execute(
        """UPDATE evaluations SET
               stage1_pass = ?, stage1_reason = ?,
               stage1_model = ?, stage1_ms = ?
           WHERE job_id = ? AND user_id = ?""",
        (int(passed), reason, model, duration_ms, job_id, user_id),
    )
    await db.commit()


async def _update_evaluation_stage2(
    db: aiosqlite.Connection,
    job_id: int,
    user_id: str,
    result: Stage2Result,
) -> None:
    """Aktualisiere die Stage-2-Felder einer Evaluation."""
    await db.execute(
        """UPDATE evaluations SET
               stage2_score = ?,
               stage2_score_breakdown = ?,
               stage2_recommendation = ?,
               stage2_match_reasons = ?,
               stage2_missing_skills = ?,
               stage2_salary_estimate = ?,
               stage2_summary = ?,
               stage2_application_tips = ?,
               stage2_model = ?,
               stage2_tokens_used = ?,
               stage2_ms = ?
           WHERE job_id = ? AND user_id = ?""",
        (
            result.score,
            json.dumps(result.score_breakdown),
            result.recommendation,
            json.dumps(result.match_reasons),
            json.dumps(result.missing_skills),
            result.salary_estimate,
            result.summary,
            json.dumps(result.application_tips),
            result.model,
            result.tokens_used,
            result.duration_ms,
            job_id,
            user_id,
        ),
    )
    await db.commit()


async def _save_extracted_fields(
    db: aiosqlite.Connection,
    job_id: int,
    fields: ExtractedFields,
) -> int:
    """Schreibe extrahierte Felder in die DB.

    Aktualisiert jobs-Tabelle (salary, work_model) und
    fügt Skills in job_skills ein.

    Returns:
        Anzahl der aktualisierten Felder.
    """
    updated = 0

    # Jobs-Tabelle: salary_min/max, work_model (nur wenn NULL)
    updates: list[str] = []
    params: list[object] = []

    if fields.salary_min is not None:
        updates.append("salary_min = COALESCE(salary_min, ?)")
        params.append(fields.salary_min)
        updated += 1

    if fields.salary_max is not None:
        updates.append("salary_max = COALESCE(salary_max, ?)")
        params.append(fields.salary_max)
        updated += 1

    if fields.work_model is not None:
        updates.append("work_model = COALESCE(work_model, ?)")
        params.append(fields.work_model)
        updated += 1

    if updates:
        updates.append("updated_at = ?")
        params.append(now_iso())
        params.append(job_id)
        sql = f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?"  # noqa: S608
        await db.execute(sql, params)

    # Skills in job_skills einfügen
    if fields.skills:
        for skill in fields.skills:
            await db.execute(
                """INSERT OR IGNORE INTO job_skills
                   (job_id, skill, skill_type, confidence)
                   VALUES (?, ?, ?, ?)""",
                (job_id, skill.skill, skill.skill_type, skill.confidence),
            )
            updated += 1

    await db.commit()
    return updated


async def _get_jobs_needing_evaluation(
    db: aiosqlite.Connection,
    user_id: str,
    limit: int = 100,
) -> list[Job]:
    """Hole aktive Jobs die noch nicht evaluiert wurden."""
    rows = list(
        await db.execute_fetchall(
            """SELECT j.* FROM jobs j
               WHERE j.is_active = 1
                 AND j.status NOT IN ('expired', 'ignored')
                 AND NOT EXISTS (
                     SELECT 1 FROM evaluations e
                     WHERE e.job_id = j.id AND e.user_id = ?
                 )
               LIMIT ?""",
            (user_id, limit),
        )
    )
    return [Job.model_validate(dict(row)) for row in rows]


async def _get_evaluation_exists(
    db: aiosqlite.Connection,
    job_id: int,
    user_id: str,
) -> bool:
    """Prüfe ob eine Evaluation für den Job/User existiert."""
    rows = list(
        await db.execute_fetchall(
            "SELECT 1 FROM evaluations WHERE job_id = ? AND user_id = ?",
            (job_id, user_id),
        )
    )
    return bool(rows)


# ─── Pipeline ───────────────────────────────────────────────────────────────


class EvaluationPipeline:
    """Orchestriert die vollständige Evaluierungs-Pipeline.

    Initialisiert alle Komponenten und steuert den Ablauf:
    Stage 1a → Stage 1b → Stage 2 (Einzel oder Batch).
    """

    def __init__(self) -> None:
        """Initialisiere alle Pipeline-Komponenten."""
        # Stage 1a: Deterministischer Filter
        from app.evaluator.stage1 import Stage1aFilter

        self._stage1a = Stage1aFilter(
            exclude_keywords=settings.eval_exclude_keywords
            if hasattr(settings, "eval_exclude_keywords")
            else [],
        )

        # Stage 1b: LLM-Vorfilter (Ollama)
        # OllamaClient initialisieren
        from app.evaluator.ollama_client import OllamaClient
        from app.evaluator.stage1 import Stage1bFilter

        self._ollama = OllamaClient(host=settings.ollama_host)
        self._stage1b = Stage1bFilter(
            client=self._ollama,
            model=settings.ollama_model_stage1,
        )

        # RAG-Pipeline
        from app.evaluator.rag import RAGPipeline

        self._rag = RAGPipeline(
            chroma_path=settings.chroma_path,
            ollama=self._ollama,  # type: ignore[arg-type]
            embed_model=settings.ollama_embed_model,
        )

        # Stage 2: Claude Tiefanalyse
        self._stage2 = Stage2Evaluator(
            anthropic_key=settings.anthropic_api_key,
            rag=self._rag,
        )

        # Batch Evaluator
        self._batch = BatchEvaluator(
            anthropic_key=settings.anthropic_api_key,
            stage2=self._stage2,
        )

        logger.info("EvaluationPipeline initialisiert")

    def _parse_profile(self, user: User) -> object:
        """Parse das Kernprofil aus dem User-Profil-JSON.

        Args:
            user: User-Objekt mit profile_json.

        Returns:
            Kernprofil-Objekt (duck-typed).

        Raises:
            ValueError: Wenn kein Profil vorhanden.
        """
        if not user.profile_json:
            raise ValueError(
                f"User {user.id} hat kein Profil. Bitte zuerst Dokumente verarbeiten (AP-04/05)."
            )

        profile_data = json.loads(user.profile_json)

        # Rekursiv SimpleNamespace erstellen für duck-typing
        def to_namespace(d: object) -> object:
            if isinstance(d, dict):
                return types.SimpleNamespace(**{k: to_namespace(v) for k, v in d.items()})
            if isinstance(d, list):
                return [to_namespace(item) for item in d]
            return d

        return to_namespace(profile_data)

    async def process_job(
        self,
        db: aiosqlite.Connection,
        job: Job,
        user: User,
        strategy: str = "structured_core",
    ) -> EvaluationResult:
        """Verarbeite einen einzelnen Job durch die gesamte Pipeline.

        Ablauf:
        1. Kernprofil aus User laden
        2. Stage 1a: Keyword-Ausschluss
        3. Stage 1b: LLM-Vorfilter + Feldextraktion
        4. Stage 2: Claude Tiefanalyse (Einzelauswertung)

        Args:
            db: Datenbankverbindung.
            job: Der zu evaluierende Job.
            user: Der User (mit Profil).
            strategy: Evaluierungs-Strategie ('structured_core'|'rag_hybrid').

        Returns:
            EvaluationResult mit allen Details.
        """
        start_ms = time.monotonic_ns() // 1_000_000

        # 1. Kernprofil laden
        profile = self._parse_profile(user)

        # 2. Evaluation in DB erstellen (falls nicht vorhanden)
        if not await _get_evaluation_exists(db, job.id, user.id):
            await _create_evaluation(db, job.id, user.id, strategy)

        # 3. Stage 1a: Deterministischer Keyword-Ausschluss
        stage1a_result = self._stage1a.check(job)

        if not stage1a_result.passed:
            await _update_evaluation_stage1(
                db,
                job.id,
                user.id,
                passed=False,
                reason=f"[1a] {stage1a_result.reason}",
                model=stage1a_result.model,
                duration_ms=stage1a_result.duration_ms,
            )
            elapsed = int(time.monotonic_ns() // 1_000_000 - start_ms)
            logger.info(
                "Job %d: Stage 1a SKIP — %s (%d ms)",
                job.id,
                stage1a_result.reason,
                elapsed,
            )
            return EvaluationResult(
                job_id=job.id,
                user_id=user.id,
                stage1a_passed=False,
                total_ms=elapsed,
            )

        # 4. Stage 1b: LLM-Vorfilter + Feldextraktion
        raw_text_limit = (
            settings.eval_stage1_raw_text_limit
            if hasattr(settings, "eval_stage1_raw_text_limit")
            else 1500
        )
        stage1b_result: Stage1bResult = await self._stage1b.check(
            job, profile, raw_text_limit=raw_text_limit
        )

        # 5. Extrahierte Felder in DB schreiben
        extracted_fields = stage1b_result.extracted_fields
        if extracted_fields is not None:
            await _save_extracted_fields(db, job.id, extracted_fields)

        if not stage1b_result.passed:
            await _update_evaluation_stage1(
                db,
                job.id,
                user.id,
                passed=False,
                reason=f"[1b] {stage1b_result.reason}",
                model=stage1b_result.model,
                duration_ms=stage1b_result.duration_ms,
            )
            elapsed = int(time.monotonic_ns() // 1_000_000 - start_ms)
            logger.info(
                "Job %d: Stage 1b SKIP — %s (%d ms)",
                job.id,
                stage1b_result.reason,
                elapsed,
            )
            return EvaluationResult(
                job_id=job.id,
                user_id=user.id,
                stage1a_passed=True,
                stage1b_passed=False,
                extracted_fields=extracted_fields,
                total_ms=elapsed,
            )

        # Stage 1b PASS
        await _update_evaluation_stage1(
            db,
            job.id,
            user.id,
            passed=True,
            reason=f"[1b] {stage1b_result.reason}",
            model=stage1b_result.model,
            duration_ms=stage1b_result.duration_ms,
        )

        # 6. Stage 2: Claude Tiefanalyse
        # Company laden
        company: Company | None = None
        if job.company_id is not None:
            company_rows = list(
                await db.execute_fetchall("SELECT * FROM companies WHERE id = ?", (job.company_id,))
            )
            if company_rows:
                company = Company.model_validate(dict(company_rows[0]))

        # Location-Score laden (falls vorhanden)
        location_score: object | None = None
        eval_rows = list(
            await db.execute_fetchall(
                """SELECT location_score, location_effective_minutes
                   FROM evaluations WHERE job_id = ? AND user_id = ?""",
                (job.id, user.id),
            )
        )
        if eval_rows and eval_rows[0]["location_score"] is not None:
            location_score = types.SimpleNamespace(
                score=eval_rows[0]["location_score"],
                effective_minutes=eval_rows[0]["location_effective_minutes"],
                is_remote=False,
            )

        # Feedback-Beispiele laden (letzte 5)
        feedback_examples: list[FeedbackExample] = []
        feedback_rows = list(
            await db.execute_fetchall(
                """SELECT f.decision, f.reasoning, f.model_score, f.model_recommendation,
                          j.title, c.name as company_name
                   FROM feedback f
                   JOIN jobs j ON j.id = f.job_id
                   LEFT JOIN companies c ON c.id = j.company_id
                   WHERE f.user_id = ? AND f.decision != 'SKIP'
                   ORDER BY f.decided_at DESC LIMIT 5""",
                (user.id,),
            )
        )
        for frow in feedback_rows:
            feedback_examples.append(
                FeedbackExample(
                    job_title=frow["title"],
                    company=frow["company_name"] or "Unbekannt",
                    model_score=float(frow["model_score"] or 5.0),
                    user_decision=frow["decision"],
                    reasoning=frow["reasoning"],
                )
            )

        stage2_result = await self._stage2.evaluate_single(
            job=job,
            company=company,
            profile=profile,
            strategy=strategy,
            location_score=location_score,
            feedback_examples=feedback_examples if feedback_examples else None,
            user_id=user.id,
        )

        # Stage 2 in DB speichern
        await _update_evaluation_stage2(db, job.id, user.id, stage2_result)

        elapsed = int(time.monotonic_ns() // 1_000_000 - start_ms)
        logger.info(
            "Job %d: Stage 2 Score=%.1f (%s) — %s — %d ms total",
            job.id,
            stage2_result.score,
            stage2_result.recommendation,
            strategy,
            elapsed,
        )

        return EvaluationResult(
            job_id=job.id,
            user_id=user.id,
            stage1a_passed=True,
            stage1b_passed=True,
            stage2_result=stage2_result,
            extracted_fields=extracted_fields,
            total_ms=elapsed,
        )

    async def process_batch_stage1(
        self,
        db: aiosqlite.Connection,
        user_id: str,
        limit: int = 100,
    ) -> Stage1BatchResult:
        """Verarbeite einen Batch von Jobs durch Stage 1a + 1b.

        Args:
            db: Datenbankverbindung.
            user_id: User-UUID.
            limit: Maximale Anzahl Jobs.

        Returns:
            Stage1BatchResult mit Zusammenfassung.
        """
        # User laden
        user_rows = list(await db.execute_fetchall("SELECT * FROM users WHERE id = ?", (user_id,)))
        if not user_rows:
            raise ValueError(f"User {user_id} nicht gefunden")
        user = User.model_validate(dict(user_rows[0]))

        profile = self._parse_profile(user)

        # Jobs laden
        jobs = await _get_jobs_needing_evaluation(db, user_id, limit)
        logger.info("Stage-1-Batch: %d Jobs zu verarbeiten", len(jobs))

        passed = 0
        skipped_1a = 0
        skipped_1b = 0
        errors = 0
        extracted_count = 0

        for i, job in enumerate(jobs, 1):
            try:
                # Evaluation erstellen
                await _create_evaluation(db, job.id, user_id)

                # Stage 1a
                stage1a_result = self._stage1a.check(job)
                if not stage1a_result.passed:
                    await _update_evaluation_stage1(
                        db,
                        job.id,
                        user_id,
                        passed=False,
                        reason=f"[1a] {stage1a_result.reason}",
                        model=stage1a_result.model,
                        duration_ms=stage1a_result.duration_ms,
                    )
                    skipped_1a += 1
                    continue

                # Stage 1b
                raw_text_limit = (
                    settings.eval_stage1_raw_text_limit
                    if hasattr(settings, "eval_stage1_raw_text_limit")
                    else 1500
                )
                stage1b_result = await self._stage1b.check(
                    job, profile, raw_text_limit=raw_text_limit
                )

                # Extrahierte Felder speichern
                if stage1b_result.extracted_fields is not None:
                    count = await _save_extracted_fields(
                        db, job.id, stage1b_result.extracted_fields
                    )
                    if count > 0:
                        extracted_count += 1

                if not stage1b_result.passed:
                    await _update_evaluation_stage1(
                        db,
                        job.id,
                        user_id,
                        passed=False,
                        reason=f"[1b] {stage1b_result.reason}",
                        model=stage1b_result.model,
                        duration_ms=stage1b_result.duration_ms,
                    )
                    skipped_1b += 1
                    continue

                # PASS
                await _update_evaluation_stage1(
                    db,
                    job.id,
                    user_id,
                    passed=True,
                    reason=f"[1b] {stage1b_result.reason}",
                    model=stage1b_result.model,
                    duration_ms=stage1b_result.duration_ms,
                )
                passed += 1

                if i % 10 == 0:
                    logger.info("  Stage-1-Batch: %d/%d verarbeitet", i, len(jobs))

            except Exception:
                logger.exception("Fehler bei Job %d", job.id)
                errors += 1

        logger.info(
            "Stage-1-Batch fertig: %d verarbeitet, %d PASS, %d 1a-SKIP, "
            "%d 1b-SKIP, %d Fehler, %d extrahierte Felder",
            len(jobs),
            passed,
            skipped_1a,
            skipped_1b,
            errors,
            extracted_count,
        )

        return Stage1BatchResult(
            processed=len(jobs),
            passed=passed,
            skipped_1a=skipped_1a,
            skipped_1b=skipped_1b,
            errors=errors,
            extracted_fields_count=extracted_count,
        )

    async def process_batch_stage2(
        self,
        db: aiosqlite.Connection,
        user_id: str,
        strategy: str = "structured_core",
        limit: int = 50,
    ) -> BatchFlowResult:
        """Verarbeite Stage-2 als Batch via Anthropic Batch API.

        Delegiert an BatchEvaluator.process_batch_flow().

        Args:
            db: Datenbankverbindung.
            user_id: User-UUID.
            strategy: Evaluierungs-Strategie.
            limit: Maximale Anzahl Jobs.

        Returns:
            BatchFlowResult.
        """
        return await self._batch.process_batch_flow(
            db=db,
            user_id=user_id,
            strategy=strategy,
            limit=limit,
        )

    async def close(self) -> None:
        """Ressourcen freigeben."""
        if hasattr(self._ollama, "close"):
            await self._ollama.close()
        logger.info("EvaluationPipeline geschlossen")
