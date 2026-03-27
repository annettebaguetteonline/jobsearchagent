"""Unit-Tests für den Ollama-Client."""

import json
from unittest.mock import AsyncMock

import pytest

from app.evaluator.ollama_client import (
    OllamaClient,
    OllamaModelNotFoundError,
    OllamaUnavailableError,
)


@pytest.mark.asyncio
async def test_chat_json_success() -> None:
    """Erfolgreiche JSON-Antwort wird korrekt geparst."""
    client = OllamaClient(host="http://localhost:11434")
    mock_response = {"message": {"content": json.dumps({"pass": True, "reason": "Relevant"})}}
    client._chat_client.chat = AsyncMock(return_value=mock_response)

    result = await client.chat_json(
        model="mistral-nemo:12b",
        system="Du bist ein Job-Evaluator.",
        user="Bewerte diesen Job: Python Developer",
    )
    assert result == {"pass": True, "reason": "Relevant"}


@pytest.mark.asyncio
async def test_chat_json_markdown_fallback() -> None:
    """JSON in Markdown-Codeblock wird extrahiert."""
    client = OllamaClient(host="http://localhost:11434")
    raw = '```json\n{"pass": false, "reason": "Praktikum"}\n```'
    mock_response = {"message": {"content": raw}}
    client._chat_client.chat = AsyncMock(return_value=mock_response)

    result = await client.chat_json(
        model="mistral-nemo:12b",
        system="test",
        user="test",
    )
    assert result["pass"] is False
    assert result["reason"] == "Praktikum"


@pytest.mark.asyncio
async def test_chat_json_brace_fallback() -> None:
    """JSON mit umgebendem Text wird extrahiert."""
    client = OllamaClient(host="http://localhost:11434")
    raw = 'Here is my analysis: {"pass": true, "reason": "Good fit"} end.'
    mock_response = {"message": {"content": raw}}
    client._chat_client.chat = AsyncMock(return_value=mock_response)

    result = await client.chat_json(
        model="mistral-nemo:12b",
        system="test",
        user="test",
    )
    assert result["pass"] is True


@pytest.mark.asyncio
async def test_chat_json_connection_error_retries() -> None:
    """ConnectionError führt zu Retry, dann OllamaUnavailableError."""
    client = OllamaClient(host="http://localhost:11434")
    client._chat_client.chat = AsyncMock(side_effect=ConnectionError("refused"))

    with pytest.raises(OllamaUnavailableError, match="nicht erreichbar"):
        await client.chat_json(
            model="mistral-nemo:12b",
            system="test",
            user="test",
        )
    # 2 Versuche (MAX_RETRIES = 2)
    assert client._chat_client.chat.call_count == 2


@pytest.mark.asyncio
async def test_chat_json_model_not_found() -> None:
    """ResponseError mit 'model not found' → OllamaModelNotFoundError."""
    from ollama import ResponseError

    client = OllamaClient(host="http://localhost:11434")
    client._chat_client.chat = AsyncMock(side_effect=ResponseError("model 'xyz' not found"))

    with pytest.raises(OllamaModelNotFoundError, match="xyz"):
        await client.chat_json(
            model="xyz",
            system="test",
            user="test",
        )


@pytest.mark.asyncio
async def test_embed_single_batch() -> None:
    """Embedding mit weniger als 32 Texten wird in einem Aufruf verarbeitet."""
    client = OllamaClient(host="http://localhost:11434")
    mock_embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    client._embed_client.embed = AsyncMock(return_value={"embeddings": mock_embeddings})

    result = await client.embed(
        model="nomic-embed-text",
        texts=["Hello world", "Test text"],
    )
    assert len(result) == 2
    assert result[0] == [0.1, 0.2, 0.3]
    client._embed_client.embed.assert_called_once()


@pytest.mark.asyncio
async def test_embed_multi_batch() -> None:
    """Mehr als 32 Texte werden in mehrere Batches aufgeteilt."""
    client = OllamaClient(host="http://localhost:11434")
    # 40 Texte → 2 Batches (32 + 8)
    texts = [f"text_{i}" for i in range(40)]
    batch1_embeds = [[float(i)] for i in range(32)]
    batch2_embeds = [[float(i)] for i in range(32, 40)]

    client._embed_client.embed = AsyncMock(
        side_effect=[
            {"embeddings": batch1_embeds},
            {"embeddings": batch2_embeds},
        ]
    )

    result = await client.embed(model="nomic-embed-text", texts=texts)
    assert len(result) == 40
    assert client._embed_client.embed.call_count == 2


@pytest.mark.asyncio
async def test_embed_empty_list() -> None:
    """Leere Textliste gibt leere Ergebnisliste zurück."""
    client = OllamaClient(host="http://localhost:11434")
    result = await client.embed(model="nomic-embed-text", texts=[])
    assert result == []
