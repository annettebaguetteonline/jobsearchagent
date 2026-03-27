"""Unit-Tests fuer die RAG-Pipeline.

Verwendet in-memory ChromaDB und gemockte Ollama-Embeddings.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.evaluator.rag import (
    RAGChunk,
    RAGPipeline,
    _chunk_by_sections,
    _chunk_projects,
    _chunk_short,
    _make_chunk_id,
    chunk_document,
)


def _make_parsed_doc(
    text: str = "Test content",
    doc_type: str = "cv",
    filename: str = "lebenslauf.pdf",
    path: str = "/docs/lebenslauf.pdf",
) -> MagicMock:
    """Erstelle ein Mock-ParsedDocument."""
    doc = MagicMock()
    doc.text = text
    doc.doc_type = doc_type
    doc.filename = filename
    doc.path = path
    doc.page_count = 1
    doc.parse_method = "pdfplumber"
    return doc


def _make_mock_ollama() -> AsyncMock:
    """Erstelle einen Mock OllamaClient mit deterministischen Embeddings."""
    client = AsyncMock()

    async def mock_embed(model: str, texts: list[str]) -> list[list[float]]:
        """Generiere deterministische Fake-Embeddings (384 Dimensionen)."""
        embeddings: list[list[float]] = []
        for _i, text in enumerate(texts):
            # Einfaches Embedding basierend auf Textlaenge und Index
            base = (hash(text) % 1000) / 1000.0
            embedding = [base + (j * 0.001) for j in range(384)]
            embeddings.append(embedding)
        return embeddings

    client.embed = AsyncMock(side_effect=mock_embed)
    return client


# --- Chunking-Tests ---------------------------------------------------------


def test_chunk_by_sections_markdown_headers() -> None:
    """Text mit ## Headers wird an Headers gesplittet."""
    text = """## Berufserfahrung
Senior Developer bei TechCorp (2020-2024)

## Ausbildung
Master Informatik, TU Darmstadt"""

    chunks = _chunk_by_sections(text)
    assert len(chunks) == 2
    assert "Berufserfahrung" in chunks[0]
    assert "Ausbildung" in chunks[1]


def test_chunk_by_sections_long_section() -> None:
    """Zu lange Sektionen werden an Absaetzen gesplittet."""
    # Erstelle einen sehr langen Text (~2000 Tokens = ~8000 Zeichen)
    long_text = "\n\n".join([f"Absatz {i}: " + "x" * 500 for i in range(20)])
    chunks = _chunk_by_sections(long_text, max_tokens=400)
    assert len(chunks) > 1
    for chunk in chunks:
        # Grobe Pruefung: kein Chunk sollte viel laenger als max_tokens sein
        assert len(chunk) // 4 < 600  # etwas Spielraum


def test_chunk_by_sections_empty_text() -> None:
    """Leerer Text ergibt keine Chunks."""
    assert _chunk_by_sections("") == []
    assert _chunk_by_sections("   ") == []


def test_chunk_projects_multiple() -> None:
    """Projekte werden einzeln gechunked."""
    text = """## Projekt 1: E-Commerce Platform
Entwicklung einer Microservice-Architektur.

## Projekt 2: Data Pipeline
ETL-Pipeline fuer 10M Records/Tag."""

    chunks = _chunk_projects(text)
    assert len(chunks) == 2
    assert "E-Commerce" in chunks[0]
    assert "Data Pipeline" in chunks[1]


def test_chunk_short_single() -> None:
    """Kurze Dokumente ergeben einen einzelnen Chunk."""
    text = "AWS Solutions Architect Professional, erworben 2023."
    chunks = _chunk_short(text)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_short_empty() -> None:
    """Leerer Text ergibt keine Chunks."""
    assert _chunk_short("") == []


def test_chunk_document_cv_type() -> None:
    """CV-Dokument wird nach Sektionen gechunked."""
    doc = _make_parsed_doc(
        text="## Skills\nPython, FastAPI\n\n## Erfahrung\n5 Jahre Backend",
        doc_type="cv",
    )
    chunks = chunk_document(doc)
    assert len(chunks) >= 2
    assert all(c["doc_type"] == "cv" for c in chunks)
    assert all(c["source_doc"] == "lebenslauf.pdf" for c in chunks)


def test_chunk_document_zertifikat_type() -> None:
    """Zertifikat wird als einzelner Chunk behandelt."""
    doc = _make_parsed_doc(
        text="AWS Solutions Architect Professional 2023",
        doc_type="zertifikat",
        filename="aws_cert.pdf",
    )
    chunks = chunk_document(doc)
    assert len(chunks) == 1
    assert chunks[0]["doc_type"] == "zertifikat"


def test_make_chunk_id_deterministic() -> None:
    """Chunk-IDs sind deterministisch."""
    id1 = _make_chunk_id("doc.pdf", 0)
    id2 = _make_chunk_id("doc.pdf", 0)
    id3 = _make_chunk_id("doc.pdf", 1)
    assert id1 == id2
    assert id1 != id3


# --- Pipeline-Tests (in-memory ChromaDB) ------------------------------------


@pytest.mark.asyncio
async def test_index_and_query(tmp_path: Path) -> None:
    """Indexierung + Query-Roundtrip."""
    mock_ollama = _make_mock_ollama()
    pipeline = RAGPipeline(
        chroma_path=tmp_path / "chroma",
        ollama=mock_ollama,
        embed_model="nomic-embed-text",
    )

    doc = _make_parsed_doc(
        text="## Skills\nPython, FastAPI, PostgreSQL\n\n## Erfahrung\nSenior Backend Developer",
        doc_type="cv",
    )

    result = await pipeline.index_documents("user-1", [doc])
    assert result.documents_processed == 1
    assert result.chunks_created >= 1
    assert result.embedding_time_ms >= 0

    # Query
    chunks = await pipeline.query("user-1", "Python Backend Entwickler", top_k=3)
    assert len(chunks) >= 1
    assert all(isinstance(c, RAGChunk) for c in chunks)
    assert all(c.relevance_score >= 0.0 for c in chunks)
    assert all(c.doc_type == "cv" for c in chunks)


@pytest.mark.asyncio
async def test_query_empty_collection(tmp_path: Path) -> None:
    """Query auf leere Collection gibt leere Liste zurueck."""
    mock_ollama = _make_mock_ollama()
    pipeline = RAGPipeline(
        chroma_path=tmp_path / "chroma",
        ollama=mock_ollama,
    )

    chunks = await pipeline.query("nonexistent-user", "Python", top_k=5)
    assert chunks == []


@pytest.mark.asyncio
async def test_index_multiple_documents(tmp_path: Path) -> None:
    """Mehrere Dokumente verschiedener Typen indexieren."""
    mock_ollama = _make_mock_ollama()
    pipeline = RAGPipeline(
        chroma_path=tmp_path / "chroma",
        ollama=mock_ollama,
    )

    docs = [
        _make_parsed_doc(text="Python, FastAPI, Docker", doc_type="cv", filename="cv.pdf"),
        _make_parsed_doc(
            text="## Projekt 1: API Gateway\nMicroservice Routing",
            doc_type="projekt",
            filename="projekte.pdf",
        ),
        _make_parsed_doc(
            text="AWS Certified Solutions Architect 2023",
            doc_type="zertifikat",
            filename="aws.pdf",
        ),
    ]

    result = await pipeline.index_documents("user-2", docs)
    assert result.documents_processed == 3
    assert result.chunks_created >= 3

    # Chunk-Count pruefen
    count = pipeline.get_chunk_count("user-2")
    assert count == result.chunks_created


@pytest.mark.asyncio
async def test_reindex_user_clears_old_data(tmp_path: Path) -> None:
    """Reindexierung loescht alte Chunks und erstellt neue."""
    mock_ollama = _make_mock_ollama()
    pipeline = RAGPipeline(
        chroma_path=tmp_path / "chroma",
        ollama=mock_ollama,
    )

    # Erste Indexierung
    doc1 = _make_parsed_doc(text="Alte Skills: Java, Spring", doc_type="cv")
    await pipeline.index_documents("user-3", [doc1])
    old_count = pipeline.get_chunk_count("user-3")
    assert old_count >= 1

    # Reindexierung mit neuem Dokument
    doc2 = _make_parsed_doc(text="Neue Skills: Python, FastAPI", doc_type="cv")
    result = await pipeline.reindex_user("user-3", [doc2])
    new_count = pipeline.get_chunk_count("user-3")
    assert result.chunks_created >= 1
    assert new_count == result.chunks_created


@pytest.mark.asyncio
async def test_index_empty_documents(tmp_path: Path) -> None:
    """Leere Dokumentliste ergibt 0 Chunks."""
    mock_ollama = _make_mock_ollama()
    pipeline = RAGPipeline(
        chroma_path=tmp_path / "chroma",
        ollama=mock_ollama,
    )

    result = await pipeline.index_documents("user-4", [])
    assert result.chunks_created == 0
    assert result.documents_processed == 0


@pytest.mark.asyncio
async def test_query_returns_metadata(tmp_path: Path) -> None:
    """Query-Ergebnisse enthalten korrekte Metadaten."""
    mock_ollama = _make_mock_ollama()
    pipeline = RAGPipeline(
        chroma_path=tmp_path / "chroma",
        ollama=mock_ollama,
    )

    doc = _make_parsed_doc(
        text="Kubernetes, Terraform, CI/CD Erfahrung",
        doc_type="cv",
        filename="lebenslauf.pdf",
    )
    await pipeline.index_documents("user-5", [doc])

    chunks = await pipeline.query("user-5", "DevOps Skills", top_k=1)
    assert len(chunks) == 1
    assert chunks[0].source_doc == "lebenslauf.pdf"
    assert chunks[0].doc_type == "cv"
    assert "doc_type" in chunks[0].metadata
    assert "source_file" in chunks[0].metadata
