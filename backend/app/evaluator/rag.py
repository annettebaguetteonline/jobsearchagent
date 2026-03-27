"""RAG-Pipeline: ChromaDB-Vektordatenbank mit Ollama-Embeddings.

Indexiert Bewerberdokumente als Chunks und stellt eine Query-Schnittstelle
fuer die Stage-2-Evaluierung bereit.

ChromaDB laeuft embedded (kein separater Server).
Embeddings via nomic-embed-text ueber OllamaClient.
"""

import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Protocol

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from pydantic import BaseModel


class _EmbedCapable(Protocol):
    async def embed(self, model: str, texts: list[str]) -> Embeddings: ...


logger = logging.getLogger(__name__)


# --- Modelle ----------------------------------------------------------------


class RAGChunk(BaseModel):
    """Ein abgerufener Chunk mit Relevanz-Score."""

    text: str
    source_doc: str
    doc_type: str
    chunk_id: str
    relevance_score: float
    metadata: dict[str, str]


class IndexResult(BaseModel):
    """Ergebnis einer Indexierungsoperation."""

    chunks_created: int
    documents_processed: int
    embedding_time_ms: int


# --- Ollama Embedding Function fuer ChromaDB --------------------------------


class OllamaEmbeddingFunction(EmbeddingFunction[Documents]):
    """Wrapper um OllamaClient.embed() fuer ChromaDB.

    ChromaDB ruft __call__ synchron auf, daher verwenden wir
    asyncio.run() als Bridge. In der Praxis wird die Pipeline
    ohnehin in einem async-Kontext betrieben.
    """

    def __init__(self, client: _EmbedCapable, model: str = "nomic-embed-text") -> None:
        self._client = client
        self._model = model

    def __call__(self, input: Documents) -> Embeddings:
        """Berechne Embeddings fuer eine Liste von Texten.

        Wird von ChromaDB synchron aufgerufen.
        """
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            # Wir sind bereits in einem async-Kontext
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    self._client.embed(model=self._model, texts=list(input)),
                )
                return future.result()
        else:
            return asyncio.run(self._client.embed(model=self._model, texts=list(input)))


# --- Chunking-Logik ---------------------------------------------------------


def _chunk_by_sections(text: str, max_tokens: int = 400) -> list[str]:
    """Splitte Text an Markdown-Headern oder Doppel-Leerzeilen.

    Fuer CVs und strukturierte Dokumente.
    """
    # Split an ## Headers oder doppelten Leerzeilen
    sections = re.split(r"\n(?=##\s)|(?:\n\s*\n\s*\n)", text)
    chunks: list[str] = []

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # Grobe Token-Schaetzung: ~4 Zeichen pro Token
        estimated_tokens = len(section) // 4
        if estimated_tokens <= max_tokens:
            chunks.append(section)
        else:
            # Zu lang -> bei Absaetzen splitten
            paragraphs = section.split("\n\n")
            current_chunk = ""
            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue
                if len(current_chunk + "\n\n" + para) // 4 > max_tokens and current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = para
                else:
                    current_chunk = current_chunk + "\n\n" + para if current_chunk else para
            if current_chunk.strip():
                chunks.append(current_chunk.strip())

    return chunks if chunks else [text.strip()] if text.strip() else []


def _chunk_projects(text: str) -> list[str]:
    """Ein Chunk pro Projekt. Projekte werden an Nummerierung oder ## getrennt."""
    # Versuche Projekt-Trennung
    projects = re.split(r"\n(?=(?:##\s|Projekt\s*\d|[-*]\s+Projekt))", text)
    chunks = [p.strip() for p in projects if p.strip()]
    return chunks if chunks else [text.strip()] if text.strip() else []


def _chunk_short(text: str) -> list[str]:
    """Kurze Dokumente (Zeugnisse, Zertifikate) als einzelner Chunk."""
    if not text.strip():
        return []
    return [text.strip()]


def _make_chunk_id(source_doc: str, chunk_index: int) -> str:
    """Generiere eine deterministische Chunk-ID."""
    raw = f"{source_doc}:{chunk_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def chunk_document(
    doc: object,
    max_tokens: int = 400,
) -> list[dict[str, str]]:
    """Chunke ein ParsedDocument typabhaengig.

    Args:
        doc: ParsedDocument (aus AP-04) mit path, filename, doc_type, text.
        max_tokens: Maximale Tokenzahl pro Chunk.

    Returns:
        Liste von Dicts mit {text, source_doc, doc_type, chunk_id, chunk_index}.
    """
    doc_type: str = getattr(doc, "doc_type", "sonstiges")
    text: str = getattr(doc, "text", "")
    source: str = getattr(doc, "filename", getattr(doc, "path", "unknown"))

    if doc_type == "cv":
        raw_chunks = _chunk_by_sections(text, max_tokens=max_tokens)
    elif doc_type == "projekt":
        raw_chunks = _chunk_projects(text)
    elif doc_type in ("zeugnis", "zertifikat"):
        raw_chunks = _chunk_short(text)
    else:
        raw_chunks = _chunk_by_sections(text, max_tokens=max_tokens)

    results: list[dict[str, str]] = []
    for i, chunk_text in enumerate(raw_chunks):
        results.append(
            {
                "text": chunk_text,
                "source_doc": source,
                "doc_type": doc_type,
                "chunk_id": _make_chunk_id(source, i),
                "chunk_index": str(i),
            }
        )

    return results


# --- RAG Pipeline -----------------------------------------------------------


class RAGPipeline:
    """ChromaDB-basierte RAG-Pipeline fuer Bewerberdokumente.

    Indiziert Dokumente als Chunks mit Ollama-Embeddings und
    bietet Query-Zugriff fuer die Stage-2-Evaluierung.
    """

    def __init__(
        self,
        chroma_path: Path,
        ollama: _EmbedCapable,
        embed_model: str = "nomic-embed-text",
    ) -> None:
        """Initialisiere die RAG-Pipeline.

        Args:
            chroma_path: Pfad fuer persistente ChromaDB-Speicherung.
            ollama: OllamaClient-Instanz (aus AP-03).
            embed_model: Ollama-Modellname fuer Embeddings.
        """
        self._chroma_path = chroma_path
        self._ollama = ollama
        self._embed_model = embed_model
        self._embed_fn = OllamaEmbeddingFunction(client=ollama, model=embed_model)

        # ChromaDB Persistent Client
        self._chroma_client = chromadb.PersistentClient(
            path=str(chroma_path),
        )
        logger.info("ChromaDB initialisiert: %s", chroma_path)

    def _collection_name(self, user_id: str) -> str:
        """Generiere den Collection-Namen fuer einen User."""
        # ChromaDB erlaubt nur alphanumerische Zeichen, Unterstriche, Bindestriche
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", user_id)
        return f"user_{safe_id}_profile"

    def _get_collection(self, user_id: str) -> chromadb.Collection:
        """Hole oder erstelle die Collection fuer einen User."""
        return self._chroma_client.get_or_create_collection(
            name=self._collection_name(user_id),
            embedding_function=self._embed_fn,  # type: ignore[arg-type]
            metadata={"hnsw:space": "cosine"},
        )

    async def index_documents(
        self,
        user_id: str,
        documents: list[object],
    ) -> IndexResult:
        """Indexiere Bewerberdokumente fuer einen User.

        Args:
            user_id: User-UUID.
            documents: Liste von ParsedDocument-Objekten (aus AP-04).

        Returns:
            IndexResult mit Statistiken.
        """
        start_ms = time.monotonic_ns() // 1_000_000
        collection = self._get_collection(user_id)

        all_chunks: list[dict[str, str]] = []
        for doc in documents:
            doc_chunks = chunk_document(doc)
            all_chunks.extend(doc_chunks)

        if not all_chunks:
            elapsed = int(time.monotonic_ns() // 1_000_000 - start_ms)
            return IndexResult(
                chunks_created=0,
                documents_processed=len(documents),
                embedding_time_ms=elapsed,
            )

        # ChromaDB-Daten vorbereiten
        ids = [c["chunk_id"] for c in all_chunks]
        texts = [c["text"] for c in all_chunks]
        metadatas = [
            {
                "doc_type": c["doc_type"],
                "source_file": c["source_doc"],
                "chunk_index": c["chunk_index"],
            }
            for c in all_chunks
        ]

        # In ChromaDB upserten (idempotent)
        collection.upsert(
            ids=ids,
            documents=texts,
            metadatas=metadatas,  # type: ignore[arg-type]
        )

        elapsed = int(time.monotonic_ns() // 1_000_000 - start_ms)
        logger.info(
            "Indexiert: %d Chunks aus %d Dokumenten fuer User %s (%d ms)",
            len(all_chunks),
            len(documents),
            user_id,
            elapsed,
        )

        return IndexResult(
            chunks_created=len(all_chunks),
            documents_processed=len(documents),
            embedding_time_ms=elapsed,
        )

    async def query(
        self,
        user_id: str,
        job_text: str,
        top_k: int = 5,
    ) -> list[RAGChunk]:
        """Suche relevante Profil-Chunks fuer einen Stellentext.

        Args:
            user_id: User-UUID.
            job_text: Stellentext als Query.
            top_k: Anzahl der Top-Ergebnisse.

        Returns:
            Liste von RAGChunk-Objekten, sortiert nach Relevanz.
        """
        collection = self._get_collection(user_id)

        # Pruefe ob Collection Eintraege hat
        if collection.count() == 0:
            logger.warning("Keine Chunks fuer User %s — leere Collection", user_id)
            return []

        results = collection.query(
            query_texts=[job_text],
            n_results=min(top_k, collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        chunks: list[RAGChunk] = []
        if results["documents"] and results["documents"][0]:
            docs = results["documents"][0]
            metas = results["metadatas"][0] if results["metadatas"] else [{}] * len(docs)
            distances = results["distances"][0] if results["distances"] else [0.0] * len(docs)
            ids = results["ids"][0] if results["ids"] else [""] * len(docs)

            for doc_text, meta, dist, chunk_id in zip(docs, metas, distances, ids, strict=True):
                # ChromaDB Cosine-Distanz: 0 = identisch, 2 = entgegengesetzt
                # Konvertiere zu Similarity-Score: 1 - (distance / 2)
                relevance = max(0.0, 1.0 - dist / 2.0)

                meta_dict = dict(meta) if meta else {}
                chunks.append(
                    RAGChunk(
                        text=str(doc_text),
                        source_doc=str(meta_dict.get("source_file", "unknown")),
                        doc_type=str(meta_dict.get("doc_type", "unknown")),
                        chunk_id=str(chunk_id),
                        relevance_score=round(relevance, 4),
                        metadata={k: str(v) for k, v in meta_dict.items()},
                    )
                )

        logger.debug(
            "Query fuer User %s: %d Chunks gefunden",
            user_id,
            len(chunks),
        )
        return chunks

    async def reindex_user(
        self,
        user_id: str,
        documents: list[object],
    ) -> IndexResult:
        """Loesche alle Chunks eines Users und indexiere neu.

        Wird aufgerufen wenn sich das Profil aendert (neuer CV etc.).

        Args:
            user_id: User-UUID.
            documents: Neue ParsedDocument-Liste.

        Returns:
            IndexResult der Neuindexierung.
        """
        collection_name = self._collection_name(user_id)

        # Collection loeschen und neu erstellen
        try:
            self._chroma_client.delete_collection(collection_name)
            logger.info("Collection geloescht: %s", collection_name)
        except ValueError:
            # Collection existiert nicht — kein Problem
            pass

        return await self.index_documents(user_id, documents)

    def get_chunk_count(self, user_id: str) -> int:
        """Gibt die Anzahl der indexierten Chunks fuer einen User zurueck."""
        collection = self._get_collection(user_id)
        return collection.count()
