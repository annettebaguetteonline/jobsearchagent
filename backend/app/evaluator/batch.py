"""Anthropic Batch API Integration für kosteneffiziente Stage-2-Massenverarbeitung.

Workflow:
1. Jobs sammeln, Prompts via Stage2Evaluator.build_prompt() generieren
2. Batch via messages.batches.create() einreichen
3. Status via messages.batches.retrieve() pollen (exp. Backoff)
4. Ergebnisse streamen und einzeln parsen
5. DB aktualisieren (evaluations + evaluation_batches)

Batch API ist 50% günstiger als Einzel-Calls.
"""

import asyncio
import json
import logging
import time
import types

import aiosqlite
import anthropic
from pydantic import BaseModel

from app.db.models import Company, Job, now_iso
from app.evaluator.stage2 import Stage2Evaluator, Stage2Result, _parse_stage2_response, build_prompt

logger = logging.getLogger(__name__)


# ─── Modelle ─────────────────────────────────────────────────────────────────


class BatchJobInput(BaseModel):
    """Ein einzelner Job-Request für den Batch."""

    custom_id: str  # f"job_{job_id}_user_{user_id}"
    system_prompt: str
    user_prompt: str


class BatchStatus(BaseModel):
    """Status eines laufenden Batches."""

    batch_id: str
    status: str  # 'in_progress'|'ended'|'canceling'|'canceled'|'expired'
    completed: int
    total: int
    error_count: int


class BatchFlowResult(BaseModel):
    """Ergebnis des gesamten Batch-Workflows."""

    batch_id: str
    submitted: int
    completed: int
    errors: int
    duration_ms: int


# ─── Polling-Konfiguration ──────────────────────────────────────────────────

# Exponentielles Backoff: 10s, 20s, 30s, 60s, 60s, 60s, ...
POLL_INTERVALS_SECONDS: list[int] = [10, 20, 30, 60]
MAX_POLL_SECONDS: int = 7200  # 2 Stunden Timeout


# ─── BatchEvaluator ─────────────────────────────────────────────────────────


class BatchEvaluator:
    """Verwaltet Anthropic Batch API Lifecycle.

    Nutzt Stage2Evaluator.build_prompt() für Prompt-Generierung
    und _parse_stage2_response() für Response-Parsing.
    """

    def __init__(
        self,
        anthropic_key: str,
        stage2: Stage2Evaluator,
        model: str = "claude-haiku-4-5",
    ) -> None:
        """Initialisiere den BatchEvaluator.

        Args:
            anthropic_key: Anthropic API Key.
            stage2: Stage2Evaluator-Instanz (für build_prompt).
            model: Claude-Modellname für Batch-Requests.
        """
        self._client = anthropic.AsyncAnthropic(api_key=anthropic_key)
        self._stage2 = stage2
        self._model = model

    async def submit_batch(self, inputs: list[BatchJobInput]) -> str:
        """Reiche einen Batch bei der Anthropic API ein.

        Args:
            inputs: Liste von BatchJobInput mit Prompts.

        Returns:
            batch_id der eingereichten Batch.

        Raises:
            ValueError: Bei leerem Batch.
            anthropic.APIError: Bei API-Fehlern.
        """
        if not inputs:
            raise ValueError("Batch darf nicht leer sein")

        requests: list[anthropic.types.messages.batch_create_params.Request] = [
            {
                "custom_id": inp.custom_id,
                "params": {
                    "model": self._model,
                    "max_tokens": 2000,
                    "system": inp.system_prompt,
                    "messages": [{"role": "user", "content": inp.user_prompt}],
                },
            }
            for inp in inputs
        ]

        batch = await self._client.messages.batches.create(requests=requests)

        logger.info(
            "Batch eingereicht: %s — %d Requests — Modell: %s",
            batch.id,
            len(inputs),
            self._model,
        )
        return batch.id

    async def poll_batch(self, batch_id: str) -> BatchStatus:
        """Hole den aktuellen Status eines Batches.

        Args:
            batch_id: ID des Batches.

        Returns:
            BatchStatus mit aktuellem Stand.
        """
        batch = await self._client.messages.batches.retrieve(batch_id)

        counts = batch.request_counts
        completed = counts.succeeded
        total = (
            counts.processing + counts.succeeded + counts.errored + counts.canceled + counts.expired
        )
        error_count = counts.errored + counts.canceled + counts.expired

        return BatchStatus(
            batch_id=batch.id,
            status=batch.processing_status,
            completed=completed,
            total=total,
            error_count=error_count,
        )

    async def retrieve_results(
        self,
        batch_id: str,
    ) -> list[tuple[str, Stage2Result | None]]:
        """Streame und parse die Ergebnisse eines abgeschlossenen Batches.

        Args:
            batch_id: ID des abgeschlossenen Batches.

        Returns:
            Liste von (custom_id, Stage2Result | None) Tupeln.
            None bei Fehlern für einzelne Requests.
        """
        results: list[tuple[str, Stage2Result | None]] = []

        result_stream = await self._client.messages.batches.results(batch_id)
        async for result in result_stream:
            custom_id = result.custom_id

            if result.result.type == "errored":
                logger.warning(
                    "Batch-Ergebnis Fehler für %s: %s",
                    custom_id,
                    result.result.error,
                )
                results.append((custom_id, None))
                continue

            if result.result.type in ("canceled", "expired"):
                logger.warning(
                    "Batch-Ergebnis %s für %s",
                    result.result.type,
                    custom_id,
                )
                results.append((custom_id, None))
                continue

            # Erfolgreiches Ergebnis (type == "succeeded")
            try:
                message = result.result.message  # type: ignore[union-attr]
                response_text = ""
                for block in message.content:
                    if hasattr(block, "text"):
                        response_text += block.text

                tokens_used = message.usage.input_tokens + message.usage.output_tokens

                parsed = _parse_stage2_response(
                    raw_text=response_text,
                    model=self._model,
                    tokens_used=tokens_used,
                    duration_ms=0,  # Batch hat keine Einzelzeiten
                    strategy="batch",
                )
                results.append((custom_id, parsed))

            except Exception as exc:
                logger.error(
                    "Fehler beim Parsen des Batch-Ergebnisses für %s: %s",
                    custom_id,
                    exc,
                )
                results.append((custom_id, None))

        logger.info(
            "Batch %s: %d Ergebnisse abgerufen (%d Fehler)",
            batch_id,
            len(results),
            sum(1 for _, r in results if r is None),
        )
        return results

    async def _poll_until_complete(self, batch_id: str) -> BatchStatus:
        """Polle den Batch-Status mit exponentiellem Backoff bis Abschluss.

        Raises:
            TimeoutError: Nach MAX_POLL_SECONDS (2 Stunden).
        """
        start_time = time.monotonic()
        poll_index = 0

        while True:
            status = await self.poll_batch(batch_id)
            logger.info(
                "Batch %s: Status=%s, %d/%d abgeschlossen, %d Fehler",
                batch_id,
                status.status,
                status.completed,
                status.total,
                status.error_count,
            )

            if status.status == "ended":
                return status

            if status.status in ("canceled", "expired"):
                logger.error("Batch %s: Status=%s — abgebrochen", batch_id, status.status)
                return status

            # Timeout prüfen
            elapsed = time.monotonic() - start_time
            if elapsed >= MAX_POLL_SECONDS:
                raise TimeoutError(
                    f"Batch {batch_id} nach {int(elapsed)}s nicht abgeschlossen. "
                    f"Status: {status.status}, {status.completed}/{status.total}"
                )

            # Exponentielles Backoff
            if poll_index < len(POLL_INTERVALS_SECONDS):
                wait = POLL_INTERVALS_SECONDS[poll_index]
            else:
                wait = POLL_INTERVALS_SECONDS[-1]  # 60s max
            poll_index += 1

            logger.debug("Nächster Poll in %ds...", wait)
            await asyncio.sleep(wait)

    async def process_batch_flow(
        self,
        db: aiosqlite.Connection,
        user_id: str,
        strategy: str = "structured_core",
        limit: int = 50,
    ) -> BatchFlowResult:
        """Vollständiger Batch-Workflow: Vorbereitung → Submit → Poll → Ergebnisse → DB.

        Args:
            db: Datenbankverbindung.
            user_id: User-UUID.
            strategy: Evaluierungs-Strategie.
            limit: Maximale Anzahl Jobs pro Batch.

        Returns:
            BatchFlowResult mit Zusammenfassung.
        """
        start_ms = time.monotonic_ns() // 1_000_000

        # 1. Jobs laden die Stage 2 benötigen
        rows = list(
            await db.execute_fetchall(
                """SELECT j.* FROM jobs j
                   JOIN evaluations e ON e.job_id = j.id AND e.user_id = ?
                   WHERE e.stage1_pass = 1
                     AND e.stage2_score IS NULL
                   LIMIT ?""",
                (user_id, limit),
            )
        )

        if not rows:
            elapsed = int(time.monotonic_ns() // 1_000_000 - start_ms)
            logger.info("Keine Jobs für Stage-2-Batch gefunden")
            return BatchFlowResult(
                batch_id="",
                submitted=0,
                completed=0,
                errors=0,
                duration_ms=elapsed,
            )

        # 2. User-Profil und Kernprofil laden
        user_rows = list(await db.execute_fetchall("SELECT * FROM users WHERE id = ?", (user_id,)))
        if not user_rows:
            raise ValueError(f"User {user_id} nicht gefunden")

        profile_json_str = user_rows[0]["profile_json"]
        if not profile_json_str:
            raise ValueError(f"User {user_id} hat kein Profil")

        # Kernprofil als Namespace laden (wird von build_prompt duck-typed verwendet)
        profile_data = json.loads(profile_json_str)
        profile = types.SimpleNamespace(**profile_data)

        # 3. Prompts bauen
        batch_inputs: list[BatchJobInput] = []
        for row in rows:
            job = Job.model_validate(dict(row))

            # Company laden (optional)
            company: Company | None = None
            if job.company_id is not None:
                company_rows = list(
                    await db.execute_fetchall(
                        "SELECT * FROM companies WHERE id = ?", (job.company_id,)
                    )
                )
                if company_rows:
                    company = Company.model_validate(dict(company_rows[0]))

            system_prompt, user_prompt = build_prompt(
                job=job,
                company=company,
                profile=profile,
                strategy=strategy,
            )

            custom_id = f"job_{job.id}_user_{user_id}"
            batch_inputs.append(
                BatchJobInput(
                    custom_id=custom_id,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
            )

        # 4. Batch einreichen
        batch_id = await self.submit_batch(batch_inputs)

        # 5. evaluation_batches Eintrag erstellen
        ts = now_iso()
        await db.execute(
            """INSERT INTO evaluation_batches
               (user_id, batch_api_id, strategy, status, job_count, submitted_at)
               VALUES (?, ?, ?, 'submitted', ?, ?)""",
            (user_id, batch_id, strategy, len(batch_inputs), ts),
        )
        await db.commit()

        # 6. Polling bis Abschluss
        try:
            await self._poll_until_complete(batch_id)
        except TimeoutError as exc:
            await db.execute(
                """UPDATE evaluation_batches
                   SET status = 'timeout', error_log = ?
                   WHERE batch_api_id = ?""",
                (str(exc), batch_id),
            )
            await db.commit()
            elapsed = int(time.monotonic_ns() // 1_000_000 - start_ms)
            return BatchFlowResult(
                batch_id=batch_id,
                submitted=len(batch_inputs),
                completed=0,
                errors=len(batch_inputs),
                duration_ms=elapsed,
            )

        # 7. Ergebnisse abrufen und in DB schreiben
        results = await self.retrieve_results(batch_id)
        completed_count = 0
        error_count = 0

        for custom_id, stage2_result in results:
            # custom_id Format: "job_{job_id}_user_{user_id}"
            parts = custom_id.split("_")
            try:
                job_id = int(parts[1])
            except (IndexError, ValueError):
                logger.error("Ungültige custom_id: %s", custom_id)
                error_count += 1
                continue

            if stage2_result is None:
                error_count += 1
                continue

            # Evaluation in DB aktualisieren
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
                    stage2_result.score,
                    json.dumps(stage2_result.score_breakdown),
                    stage2_result.recommendation,
                    json.dumps(stage2_result.match_reasons),
                    json.dumps(stage2_result.missing_skills),
                    stage2_result.salary_estimate,
                    stage2_result.summary,
                    json.dumps(stage2_result.application_tips),
                    stage2_result.model,
                    stage2_result.tokens_used,
                    stage2_result.duration_ms,
                    job_id,
                    user_id,
                ),
            )
            completed_count += 1

        # 8. evaluation_batches aktualisieren
        await db.execute(
            """UPDATE evaluation_batches SET
                   status = 'completed',
                   completed_count = ?,
                   error_count = ?,
                   completed_at = ?
               WHERE batch_api_id = ?""",
            (completed_count, error_count, now_iso(), batch_id),
        )
        await db.commit()

        elapsed = int(time.monotonic_ns() // 1_000_000 - start_ms)

        logger.info(
            "Batch-Flow abgeschlossen: %s — %d/%d erfolgreich, %d Fehler — %d ms",
            batch_id,
            completed_count,
            len(batch_inputs),
            error_count,
            elapsed,
        )

        return BatchFlowResult(
            batch_id=batch_id,
            submitted=len(batch_inputs),
            completed=completed_count,
            errors=error_count,
            duration_ms=elapsed,
        )
