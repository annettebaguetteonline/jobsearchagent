"""Unit-Tests für den BatchEvaluator.

Alle Anthropic API-Calls werden gemockt.
"""

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.evaluator.batch import (
    POLL_INTERVALS_SECONDS,
    BatchEvaluator,
    BatchFlowResult,
    BatchJobInput,
    BatchStatus,
)
from app.evaluator.stage2 import Stage2Evaluator


def _make_mock_stage2() -> MagicMock:
    """Mock Stage2Evaluator."""
    return MagicMock(spec=Stage2Evaluator)


def _make_batch_input(
    job_id: int = 1,
    user_id: str = "test-user",
) -> BatchJobInput:
    """Erstelle einen BatchJobInput."""
    return BatchJobInput(
        custom_id=f"job_{job_id}_user_{user_id}",
        system_prompt="Du bist ein Job-Analyst.",
        user_prompt="Bewerte diesen Job: Python Developer",
    )


class _AsyncResultStream:
    """Mock für AsyncJSONLDecoder — async iterable über Batch-Ergebnisse."""

    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[Any]:
        for item in self._items:
            yield item


# ─── submit_batch Tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_batch_success() -> None:
    """Batch wird erfolgreich eingereicht."""
    mock_stage2 = _make_mock_stage2()

    evaluator = BatchEvaluator(
        anthropic_key="test-key",
        stage2=mock_stage2,
        model="claude-haiku-4-5",
    )

    mock_batch = MagicMock()
    mock_batch.id = "batch_abc123"
    evaluator._client = AsyncMock()
    evaluator._client.messages.batches.create = AsyncMock(return_value=mock_batch)

    inputs = [_make_batch_input(job_id=1), _make_batch_input(job_id=2)]
    batch_id = await evaluator.submit_batch(inputs)

    assert batch_id == "batch_abc123"
    evaluator._client.messages.batches.create.assert_called_once()
    call_kwargs = evaluator._client.messages.batches.create.call_args
    requests = call_kwargs.kwargs.get("requests") or call_kwargs[1].get("requests")
    assert len(requests) == 2
    assert requests[0]["custom_id"] == "job_1_user_test-user"
    assert requests[0]["params"]["model"] == "claude-haiku-4-5"


@pytest.mark.asyncio
async def test_submit_batch_empty_raises() -> None:
    """Leerer Batch wirft ValueError."""
    mock_stage2 = _make_mock_stage2()
    evaluator = BatchEvaluator(
        anthropic_key="test-key",
        stage2=mock_stage2,
    )

    with pytest.raises(ValueError, match="nicht leer"):
        await evaluator.submit_batch([])


# ─── poll_batch Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_poll_batch_in_progress() -> None:
    """Laufender Batch zeigt korrekten Status."""
    mock_stage2 = _make_mock_stage2()
    evaluator = BatchEvaluator(anthropic_key="test-key", stage2=mock_stage2)

    mock_batch = MagicMock()
    mock_batch.id = "batch_abc123"
    mock_batch.processing_status = "in_progress"
    mock_batch.request_counts = MagicMock()
    mock_batch.request_counts.processing = 30
    mock_batch.request_counts.succeeded = 15
    mock_batch.request_counts.errored = 2
    mock_batch.request_counts.canceled = 0
    mock_batch.request_counts.expired = 0

    evaluator._client = AsyncMock()
    evaluator._client.messages.batches.retrieve = AsyncMock(return_value=mock_batch)

    status = await evaluator.poll_batch("batch_abc123")

    assert status.batch_id == "batch_abc123"
    assert status.status == "in_progress"
    assert status.completed == 15
    assert status.total == 47
    assert status.error_count == 2


@pytest.mark.asyncio
async def test_poll_batch_ended() -> None:
    """Abgeschlossener Batch zeigt ended-Status."""
    mock_stage2 = _make_mock_stage2()
    evaluator = BatchEvaluator(anthropic_key="test-key", stage2=mock_stage2)

    mock_batch = MagicMock()
    mock_batch.id = "batch_abc123"
    mock_batch.processing_status = "ended"
    mock_batch.request_counts = MagicMock()
    mock_batch.request_counts.processing = 0
    mock_batch.request_counts.succeeded = 48
    mock_batch.request_counts.errored = 2
    mock_batch.request_counts.canceled = 0
    mock_batch.request_counts.expired = 0

    evaluator._client = AsyncMock()
    evaluator._client.messages.batches.retrieve = AsyncMock(return_value=mock_batch)

    status = await evaluator.poll_batch("batch_abc123")

    assert status.status == "ended"
    assert status.completed == 48
    assert status.error_count == 2


# ─── retrieve_results Tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retrieve_results_success() -> None:
    """Erfolgreiche Ergebnisse werden korrekt geparst."""
    mock_stage2 = _make_mock_stage2()
    evaluator = BatchEvaluator(anthropic_key="test-key", stage2=mock_stage2)

    mock_result = MagicMock()
    mock_result.custom_id = "job_1_user_test-user"
    mock_result.result.type = "succeeded"
    mock_result.result.message.content = [
        MagicMock(
            text=json.dumps(
                {
                    "score": 7.5,
                    "score_breakdown": {
                        "skills": 8.0,
                        "level": 7.0,
                        "domain": 7.5,
                        "location": 8.0,
                        "potential": 6.0,
                    },
                    "recommendation": "APPLY",
                    "match_reasons": ["Python passt"],
                    "missing_skills": ["Kubernetes"],
                    "summary": "Gute Stelle",
                    "application_tips": ["Kubernetes lernen"],
                }
            )
        )
    ]
    mock_result.result.message.usage = MagicMock()
    mock_result.result.message.usage.input_tokens = 1000
    mock_result.result.message.usage.output_tokens = 500

    evaluator._client = AsyncMock()
    evaluator._client.messages.batches.results = AsyncMock(
        return_value=_AsyncResultStream([mock_result]),
    )

    results = await evaluator.retrieve_results("batch_abc123")

    assert len(results) == 1
    custom_id, stage2_result = results[0]
    assert custom_id == "job_1_user_test-user"
    assert stage2_result is not None
    assert stage2_result.score == 7.5
    assert stage2_result.recommendation == "APPLY"


@pytest.mark.asyncio
async def test_retrieve_results_with_error() -> None:
    """Fehlerhafte Einzelergebnisse ergeben None."""
    mock_stage2 = _make_mock_stage2()
    evaluator = BatchEvaluator(anthropic_key="test-key", stage2=mock_stage2)

    mock_result = MagicMock()
    mock_result.custom_id = "job_2_user_test-user"
    mock_result.result.type = "errored"
    mock_result.result.error = "Rate limit exceeded"

    evaluator._client = AsyncMock()
    evaluator._client.messages.batches.results = AsyncMock(
        return_value=_AsyncResultStream([mock_result]),
    )

    results = await evaluator.retrieve_results("batch_abc123")

    assert len(results) == 1
    assert results[0][1] is None


@pytest.mark.asyncio
async def test_retrieve_results_canceled() -> None:
    """Stornierte Ergebnisse ergeben None."""
    mock_stage2 = _make_mock_stage2()
    evaluator = BatchEvaluator(anthropic_key="test-key", stage2=mock_stage2)

    mock_result = MagicMock()
    mock_result.custom_id = "job_3_user_test-user"
    mock_result.result.type = "canceled"

    evaluator._client = AsyncMock()
    evaluator._client.messages.batches.results = AsyncMock(
        return_value=_AsyncResultStream([mock_result]),
    )

    results = await evaluator.retrieve_results("batch_abc123")
    assert len(results) == 1
    assert results[0][1] is None


@pytest.mark.asyncio
async def test_retrieve_results_mixed() -> None:
    """Gemischte Ergebnisse (Erfolg + Fehler) werden korrekt verarbeitet."""
    mock_stage2 = _make_mock_stage2()
    evaluator = BatchEvaluator(anthropic_key="test-key", stage2=mock_stage2)

    success_result = MagicMock()
    success_result.custom_id = "job_1_user_test-user"
    success_result.result.type = "succeeded"
    success_result.result.message.content = [
        MagicMock(
            text=json.dumps(
                {
                    "score": 8.0,
                    "score_breakdown": {
                        "skills": 8.0,
                        "level": 8.0,
                        "domain": 8.0,
                        "location": 8.0,
                        "potential": 8.0,
                    },
                    "recommendation": "APPLY",
                    "match_reasons": ["Perfekt"],
                    "missing_skills": [],
                    "summary": "Top Match",
                    "application_tips": [],
                }
            )
        )
    ]
    success_result.result.message.usage = MagicMock()
    success_result.result.message.usage.input_tokens = 500
    success_result.result.message.usage.output_tokens = 300

    error_result = MagicMock()
    error_result.custom_id = "job_2_user_test-user"
    error_result.result.type = "errored"
    error_result.result.error = "Internal error"

    evaluator._client = AsyncMock()
    evaluator._client.messages.batches.results = AsyncMock(
        return_value=_AsyncResultStream([success_result, error_result]),
    )

    results = await evaluator.retrieve_results("batch_abc123")

    assert len(results) == 2
    assert results[0][1] is not None
    assert results[0][1].score == 8.0
    assert results[1][1] is None


# ─── _poll_until_complete Tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_poll_until_complete_immediate() -> None:
    """Batch ist sofort fertig → kein Warten."""
    mock_stage2 = _make_mock_stage2()
    evaluator = BatchEvaluator(anthropic_key="test-key", stage2=mock_stage2)

    final_status = BatchStatus(
        batch_id="batch_abc",
        status="ended",
        completed=50,
        total=50,
        error_count=0,
    )
    evaluator.poll_batch = AsyncMock(return_value=final_status)  # type: ignore[method-assign]

    result = await evaluator._poll_until_complete("batch_abc")
    assert result.status == "ended"
    assert evaluator.poll_batch.call_count == 1


@pytest.mark.asyncio
async def test_poll_until_complete_multiple_polls() -> None:
    """Batch braucht mehrere Polls bis Abschluss."""
    mock_stage2 = _make_mock_stage2()
    evaluator = BatchEvaluator(anthropic_key="test-key", stage2=mock_stage2)

    in_progress = BatchStatus(
        batch_id="batch_abc",
        status="in_progress",
        completed=10,
        total=50,
        error_count=0,
    )
    ended = BatchStatus(
        batch_id="batch_abc",
        status="ended",
        completed=50,
        total=50,
        error_count=0,
    )

    evaluator.poll_batch = AsyncMock(  # type: ignore[method-assign]
        side_effect=[in_progress, in_progress, ended],
    )

    with patch("app.evaluator.batch.asyncio.sleep", new_callable=AsyncMock):
        result = await evaluator._poll_until_complete("batch_abc")

    assert result.status == "ended"
    assert evaluator.poll_batch.call_count == 3


@pytest.mark.asyncio
async def test_poll_until_complete_canceled() -> None:
    """Stornierter Batch wird korrekt erkannt."""
    mock_stage2 = _make_mock_stage2()
    evaluator = BatchEvaluator(anthropic_key="test-key", stage2=mock_stage2)

    canceled = BatchStatus(
        batch_id="batch_abc",
        status="canceled",
        completed=10,
        total=50,
        error_count=0,
    )
    evaluator.poll_batch = AsyncMock(return_value=canceled)  # type: ignore[method-assign]

    result = await evaluator._poll_until_complete("batch_abc")
    assert result.status == "canceled"


@pytest.mark.asyncio
async def test_poll_until_complete_timeout() -> None:
    """Timeout nach MAX_POLL_SECONDS wirft TimeoutError."""
    mock_stage2 = _make_mock_stage2()
    evaluator = BatchEvaluator(anthropic_key="test-key", stage2=mock_stage2)

    in_progress = BatchStatus(
        batch_id="batch_abc",
        status="in_progress",
        completed=10,
        total=50,
        error_count=0,
    )
    evaluator.poll_batch = AsyncMock(return_value=in_progress)  # type: ignore[method-assign]

    # time.monotonic so mocken, dass Timeout sofort erreicht wird
    with (
        patch("app.evaluator.batch.time.monotonic", side_effect=[0.0, 8000.0]),
        patch("app.evaluator.batch.asyncio.sleep", new_callable=AsyncMock),
    ):
        with pytest.raises(TimeoutError, match="nicht abgeschlossen"):
            await evaluator._poll_until_complete("batch_abc")


# ─── BatchJobInput Modell ───────────────────────────────────────────────────


def test_batch_job_input_custom_id_format() -> None:
    """custom_id Format ist korrekt."""
    inp = _make_batch_input(job_id=42, user_id="abc-123")
    assert inp.custom_id == "job_42_user_abc-123"


def test_poll_intervals_increasing() -> None:
    """Poll-Intervalle sind monoton steigend."""
    for i in range(1, len(POLL_INTERVALS_SECONDS)):
        assert POLL_INTERVALS_SECONDS[i] >= POLL_INTERVALS_SECONDS[i - 1]


# ─── BatchStatus Modell ────────────────────────────────────────────────────


def test_batch_status_model() -> None:
    """BatchStatus kann korrekt erstellt werden."""
    status = BatchStatus(
        batch_id="batch_test",
        status="in_progress",
        completed=5,
        total=10,
        error_count=1,
    )
    assert status.batch_id == "batch_test"
    assert status.total == 10


def test_batch_flow_result_model() -> None:
    """BatchFlowResult kann korrekt erstellt werden."""
    result = BatchFlowResult(
        batch_id="batch_test",
        submitted=50,
        completed=48,
        errors=2,
        duration_ms=5000,
    )
    assert result.submitted == 50
    assert result.errors == 2
