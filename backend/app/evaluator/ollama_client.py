"""Async Ollama-Client für Chat-Completions und Embeddings.

Kapselt die offizielle ollama-Library mit:
- JSON-Format-Erzwingung für strukturierte Antworten
- Retry-Logik bei Verbindungsfehlern
- Batch-Embedding (max 32 Texte pro Aufruf)
- Health-Check und Model-Management
"""

import json
import logging
import re
from typing import Any, Literal

import ollama as ollama_lib
from ollama import AsyncClient

logger = logging.getLogger(__name__)


class OllamaUnavailableError(Exception):
    """Ollama-Server ist nicht erreichbar."""


class OllamaModelNotFoundError(Exception):
    """Das angeforderte Modell ist nicht auf dem Ollama-Server verfügbar."""


class OllamaClient:
    """Async Client für Ollama Chat und Embeddings."""

    MAX_EMBED_BATCH = 32
    MAX_RETRIES = 2

    def __init__(
        self,
        host: str,
        timeout_chat: float = 120.0,
        timeout_embed: float = 30.0,
    ) -> None:
        self._host = host
        self._timeout_chat = timeout_chat
        self._timeout_embed = timeout_embed
        self._chat_client = AsyncClient(host=host, timeout=timeout_chat)
        self._embed_client = AsyncClient(host=host, timeout=timeout_embed)

    async def chat_json(
        self,
        model: str,
        system: str,
        user: str,
        response_schema: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Sende eine Chat-Anfrage und erzwinge JSON-Antwort.

        Args:
            model: Ollama-Modellname (z.B. 'mistral-nemo:12b')
            system: System-Prompt
            user: User-Nachricht
            response_schema: Optionales JSON-Schema für die Antwort

        Returns:
            Geparster JSON-Dict

        Raises:
            OllamaUnavailableError: Server nicht erreichbar
            OllamaModelNotFoundError: Modell nicht verfügbar
            ValueError: Antwort ist kein gültiges JSON
        """
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        format_param: Literal["json"] | dict[str, Any] = "json"
        if response_schema is not None:
            format_param = response_schema

        last_error: Exception | None = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = await self._chat_client.chat(
                    model=model,
                    messages=messages,
                    format=format_param,
                )
                raw_content = response["message"]["content"]
                return self._parse_json(raw_content)

            except ollama_lib.ResponseError as exc:
                if "model" in str(exc).lower() and "not found" in str(exc).lower():
                    raise OllamaModelNotFoundError(
                        f"Modell '{model}' nicht gefunden auf {self._host}"
                    ) from exc
                last_error = exc
                logger.warning(
                    "Ollama ResponseError (Versuch %d/%d): %s",
                    attempt,
                    self.MAX_RETRIES,
                    exc,
                )

            except (ConnectionError, OSError) as exc:
                last_error = exc
                logger.warning(
                    "Ollama Verbindungsfehler (Versuch %d/%d): %s",
                    attempt,
                    self.MAX_RETRIES,
                    exc,
                )
                if attempt == self.MAX_RETRIES:
                    raise OllamaUnavailableError(
                        f"Ollama nicht erreichbar unter {self._host} "
                        f"nach {self.MAX_RETRIES} Versuchen"
                    ) from exc

        # Sollte nur erreicht werden bei ResponseError im letzten Versuch
        raise OllamaUnavailableError(
            f"Ollama-Anfrage fehlgeschlagen nach {self.MAX_RETRIES} Versuchen"
        ) from last_error

    def _parse_json(self, raw: str) -> dict[str, object]:
        """Parse JSON aus der Ollama-Antwort mit Fallback-Extraktion.

        Manche Modelle wrappen JSON in Markdown-Codeblöcke oder fügen
        Text vor/nach dem JSON ein. Diese Methode extrahiert das JSON.
        """
        # Direktes Parsing
        try:
            result = json.loads(raw)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # Fallback: JSON aus Markdown-Codeblock extrahieren
        md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
        if md_match:
            try:
                result = json.loads(md_match.group(1))
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        # Fallback: Erstes {...} Objekt im Text finden
        brace_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if brace_match:
            try:
                result = json.loads(brace_match.group(0))
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Konnte kein JSON aus Ollama-Antwort extrahieren: {raw[:200]}")

    async def embed(
        self,
        model: str,
        texts: list[str],
    ) -> list[list[float]]:
        """Erzeuge Embeddings für eine Liste von Texten.

        Teilt große Listen automatisch in Batches von max 32 Texten auf.

        Args:
            model: Ollama-Embedding-Modell (z.B. 'nomic-embed-text')
            texts: Liste von Texten zum Embedding

        Returns:
            Liste von Embedding-Vektoren (gleiche Reihenfolge wie Eingabe)

        Raises:
            OllamaUnavailableError: Server nicht erreichbar
            OllamaModelNotFoundError: Modell nicht verfügbar
        """
        if not texts:
            return []

        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), self.MAX_EMBED_BATCH):
            batch = texts[i : i + self.MAX_EMBED_BATCH]
            try:
                response = await self._embed_client.embed(
                    model=model,
                    input=batch,
                )
                embeddings = response["embeddings"]
                all_embeddings.extend(embeddings)

            except ollama_lib.ResponseError as exc:
                if "model" in str(exc).lower() and "not found" in str(exc).lower():
                    raise OllamaModelNotFoundError(
                        f"Embedding-Modell '{model}' nicht gefunden auf {self._host}"
                    ) from exc
                raise OllamaUnavailableError(f"Ollama Embedding-Fehler: {exc}") from exc

            except (ConnectionError, OSError) as exc:
                raise OllamaUnavailableError(
                    f"Ollama nicht erreichbar für Embeddings: {exc}"
                ) from exc

        return all_embeddings

    async def check_health(self) -> bool:
        """Prüfe ob der Ollama-Server erreichbar ist.

        Ruft GET /api/tags auf (listet verfügbare Modelle).

        Returns:
            True wenn erreichbar, False sonst
        """
        try:
            client = AsyncClient(host=self._host, timeout=5.0)
            await client.list()
            return True
        except (ConnectionError, OSError, ollama_lib.ResponseError):
            return False

    async def ensure_models(self, models: list[str]) -> list[str]:
        """Stelle sicher dass alle benötigten Modelle verfügbar sind.

        Fehlende Modelle werden automatisch gepullt.

        Args:
            models: Liste der benötigten Modellnamen

        Returns:
            Liste der Modelle die gepullt werden mussten

        Raises:
            OllamaUnavailableError: Server nicht erreichbar
        """
        try:
            client = AsyncClient(host=self._host, timeout=5.0)
            response = await client.list()
            available = {m["name"] for m in response.get("models", [])}
        except (ConnectionError, OSError) as exc:
            raise OllamaUnavailableError(f"Ollama nicht erreichbar: {exc}") from exc

        pulled: list[str] = []
        for model in models:
            # Prüfe ob Modell schon vorhanden (mit und ohne Tag)
            if model in available:
                continue
            # Prüfe ohne :latest Tag
            model_base = model.split(":")[0]
            if any(a.startswith(model_base + ":") for a in available):
                continue

            logger.info("Pulling Ollama-Modell: %s ...", model)
            try:
                pull_client = AsyncClient(host=self._host, timeout=600.0)
                await pull_client.pull(model)
                pulled.append(model)
                logger.info("Modell %s erfolgreich gepullt", model)
            except ollama_lib.ResponseError as exc:
                raise OllamaModelNotFoundError(
                    f"Modell '{model}' konnte nicht gepullt werden: {exc}"
                ) from exc

        return pulled
