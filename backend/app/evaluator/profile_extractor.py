"""Kernprofil-Extraktion aus User-Dokumenten via Claude API.

Ablauf:
1. Dokumente nach Typ gruppieren
2. Bilder via Claude Vision -> Text extrahieren
3. Arbeitszeugnisse einzeln decodieren (Zeugnissprache -> Staerken/Schwaechen)
4. Narrative Profilsynthese aus allen Zeugnisanalysen
5. Kernprofil aus CV + Zertifikate + Narrative extrahieren (ein Claude-Call)
6. SHA256-Hash als Profil-Version berechnen
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import anthropic
from anthropic.types import Message, TextBlock
from pydantic import BaseModel

from app.evaluator.document_parser import DocumentParser, ParsedDocument

logger = logging.getLogger(__name__)


def _extract_text(response: Message) -> str:
    """Extrahiere den Text aus dem ersten TextBlock einer Claude-Response."""
    for block in response.content:
        if isinstance(block, TextBlock):
            return block.text
    msg = "Kein TextBlock in der Claude-Response gefunden"
    raise ValueError(msg)


# --- Datenmodelle ------------------------------------------------------------


class SkillSet(BaseModel):
    """Skill-Kategorien des Kandidaten."""

    primary: list[str]  # Hauptskills (z.B. Python, Django, SQL)
    secondary: list[str]  # Nebenskills (z.B. Docker, Git, Jira)
    domains: list[str]  # Fachdomaenen (z.B. Fintech, E-Commerce, Public Sector)


class Experience(BaseModel):
    """Berufserfahrung des Kandidaten."""

    total_years: int
    levels_held: list[str]  # z.B. ['Junior', 'Mid-Level', 'Senior']
    industries: list[str]  # z.B. ['IT', 'Finanzwesen', 'Oeffentlicher Dienst']


class Preferences(BaseModel):
    """Praeferenzen des Kandidaten (aus Dokumenten abgeleitet)."""

    locations: list[str]  # Bevorzugte Standorte
    min_level: str  # Mindest-Level (z.B. 'Mid-Level', 'Senior')
    avoid: list[str]  # Bereiche/Themen die vermieden werden sollen


class Kernprofil(BaseModel):
    """Vollstaendiges extrahiertes Kernprofil."""

    skills: SkillSet
    experience: Experience
    preferences: Preferences
    narrative_profile: str  # Freitext-Zusammenfassung des Profils
    certifications: list[str]  # z.B. ['AWS SAA', 'ISTQB Foundation']
    projects_summary: list[str]  # Kurzbeschreibungen der wichtigsten Projekte


class ZeugnisAnalysis(BaseModel):
    """Analyse eines einzelnen Arbeitszeugnisses."""

    aufgaben: list[str]  # Beschriebene Aufgaben/Taetigkeiten
    staerken: list[str]  # Identifizierte Staerken (aus Zeugnissprache)
    niveau: int  # 1-5 (1=sehr gut, 5=mangelhaft)
    kontext: str  # Zusammenfassung des Kontexts (Rolle, Branche, Dauer)


# --- Prompts -----------------------------------------------------------------

ZEUGNIS_SYSTEM_PROMPT = """\
Du bist ein Experte fuer deutsche Arbeitszeugnisse und ihre codierte Sprache.
Analysiere das folgende Arbeitszeugnis und decodiere die Zeugnissprache.

Antworte ausschliesslich als JSON mit folgender Struktur:
{
    "aufgaben": ["Aufgabe 1", "Aufgabe 2"],
    "staerken": ["Staerke 1", "Staerke 2"],
    "niveau": 1-5,
    "kontext": "Kurzer Kontext (Rolle, Branche, ca. Dauer)"
}

Hinweise zur Zeugnissprache:
- "stets zu unserer vollsten Zufriedenheit" = Note 1 (sehr gut)
- "stets zu unserer vollen Zufriedenheit" = Note 2 (gut)
- "zu unserer vollen Zufriedenheit" = Note 3 (befriedigend)
- "zu unserer Zufriedenheit" = Note 4 (ausreichend)
- Fehlende Standardformulierungen = negativ (Auslassungsprinzip)
- "bemuehte sich" = mangelhaft
- "war stets puenktlich" = keine anderen Staerken zu nennen\
"""

NARRATIVE_SYSTEM_PROMPT = """\
Du erstellst ein zusammenfassendes Narrativ-Profil aus mehreren Zeugnisanalysen.
Fasse die berufliche Entwicklung, Kernkompetenzen und Staerken in einem
kohaerenten Absatz (5-8 Saetze) zusammen. Schreibe auf Deutsch.
Fokussiere auf: Karriereprogression, wiederkehrende Staerken, Fachgebiete.\
"""

PROFILE_SYSTEM_PROMPT = """\
Du extrahierst ein strukturiertes Kernprofil aus den Dokumenten eines Bewerbers.

Antworte ausschliesslich als JSON mit folgender Struktur:
{
    "skills": {
        "primary": ["Skill 1", "Skill 2"],
        "secondary": ["Skill 3", "Skill 4"],
        "domains": ["Domain 1", "Domain 2"]
    },
    "experience": {
        "total_years": 5,
        "levels_held": ["Junior", "Mid-Level"],
        "industries": ["IT", "Finanzwesen"]
    },
    "preferences": {
        "locations": ["Frankfurt", "Remote"],
        "min_level": "Mid-Level",
        "avoid": []
    },
    "certifications": ["Zertifikat 1"],
    "projects_summary": ["Kurzbeschreibung Projekt 1"]
}

Regeln:
- "primary" Skills: Technologien/Tools die der Kandidat nachweislich beherrscht
- "secondary" Skills: Erwähnte aber nicht vertiefte Technologien
- "domains": Fachgebiete (nicht Technologien)
- "total_years": Gesamtberufserfahrung (auch wenn nicht explizit genannt, schaetze)
- "levels_held": Karrierestufen die gehalten wurden
- "avoid": Nur wenn explizit erwaehnt oder aus negativen Erfahrungen ableitbar
- "projects_summary": Maximal 5 wichtigste Projekte, je max 1 Satz\
"""


# --- Profil-Extraktor -------------------------------------------------------


class ProfileExtractor:
    """Extrahiert ein Kernprofil aus User-Dokumenten via Claude API."""

    def __init__(
        self,
        anthropic_key: str,
        model: str = "claude-sonnet-4-20250514",
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=anthropic_key)
        self._model = model

    async def extract_profile(
        self,
        documents: list[ParsedDocument],
    ) -> Kernprofil:
        """Extrahiere das Kernprofil aus einer Liste von Dokumenten.

        Ablauf:
        1. Dokumente nach Typ gruppieren
        2. Bilder via Claude Vision verarbeiten (vision_pending -> Text)
        3. Zeugnisse einzeln decodieren
        4. Narrativ aus Zeugnisanalysen bauen
        5. Kernprofil extrahieren (CV + Certs + Narrativ)
        """
        # 1. Bilder verarbeiten (vision_pending)
        image_docs = [d for d in documents if d.parse_method == "vision_pending"]
        if image_docs:
            image_paths = [Path(d.path) for d in image_docs]
            processed = await self.process_images(image_paths)
            # Ersetze vision_pending-Dokumente mit verarbeiteten
            processed_by_path = {p.path: p for p in processed}
            documents = [processed_by_path.get(doc.path, doc) for doc in documents]

        # 2. Zeugnisse decodieren
        zeugnis_docs = [d for d in documents if d.doc_type == "zeugnis" and d.text.strip()]
        analyses: list[ZeugnisAnalysis] = []
        for zdoc in zeugnis_docs:
            try:
                analysis = await self.decode_zeugnis(zdoc.text)
                analyses.append(analysis)
                logger.info(
                    "Zeugnis analysiert: %s -> Niveau %d",
                    zdoc.filename,
                    analysis.niveau,
                )
            except Exception:
                logger.exception("Fehler bei Zeugnisanalyse: %s", zdoc.filename)

        # 3. Narrativ bauen
        narrative = ""
        if analyses:
            narrative = await self.build_narrative(analyses)
            logger.info("Narrativ-Profil erstellt (%d Zeichen)", len(narrative))

        # 4. Kernprofil extrahieren
        profile_parts: list[str] = []

        cv_docs = [d for d in documents if d.doc_type == "cv" and d.text.strip()]
        if cv_docs:
            profile_parts.append("=== LEBENSLAUF ===")
            for cd in cv_docs:
                profile_parts.append(cd.text)

        cert_docs = [d for d in documents if d.doc_type == "zertifikat" and d.text.strip()]
        if cert_docs:
            profile_parts.append("\n=== ZERTIFIKATE ===")
            for cd in cert_docs:
                profile_parts.append(cd.text)

        project_docs = [d for d in documents if d.doc_type == "projekt" and d.text.strip()]
        if project_docs:
            profile_parts.append("\n=== PROJEKTE ===")
            for pd in project_docs:
                profile_parts.append(pd.text)

        other_docs = [d for d in documents if d.doc_type == "sonstiges" and d.text.strip()]
        if other_docs:
            profile_parts.append("\n=== SONSTIGE DOKUMENTE ===")
            for od in other_docs:
                profile_parts.append(od.text)

        if narrative:
            profile_parts.append("\n=== NARRATIVE ZUSAMMENFASSUNG (aus Arbeitszeugnissen) ===")
            profile_parts.append(narrative)

        user_message = "\n\n".join(profile_parts)

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=PROFILE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        response_text = _extract_text(response)
        profile_data = json.loads(response_text)

        kernprofil = Kernprofil(
            skills=SkillSet(**profile_data["skills"]),
            experience=Experience(**profile_data["experience"]),
            preferences=Preferences(**profile_data["preferences"]),
            narrative_profile=narrative or "Kein Narrativ verfuegbar (keine Zeugnisse).",
            certifications=profile_data.get("certifications", []),
            projects_summary=profile_data.get("projects_summary", []),
        )

        logger.info(
            "Kernprofil extrahiert: %d primary skills, %d years experience",
            len(kernprofil.skills.primary),
            kernprofil.experience.total_years,
        )

        return kernprofil

    async def decode_zeugnis(self, text: str) -> ZeugnisAnalysis:
        """Decodiere ein deutsches Arbeitszeugnis via Claude.

        Args:
            text: Rohtext des Arbeitszeugnisses

        Returns:
            Strukturierte Analyse mit Aufgaben, Staerken, Niveau, Kontext
        """
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=ZEUGNIS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
        )

        response_text = _extract_text(response)
        data = json.loads(response_text)

        return ZeugnisAnalysis(
            aufgaben=data["aufgaben"],
            staerken=data["staerken"],
            niveau=data["niveau"],
            kontext=data["kontext"],
        )

    async def build_narrative(self, analyses: list[ZeugnisAnalysis]) -> str:
        """Baue ein zusammenfassendes Narrativ-Profil aus mehreren Zeugnisanalysen.

        Args:
            analyses: Liste von ZeugnisAnalysis-Objekten

        Returns:
            Kohaerenter Absatz der die berufliche Entwicklung zusammenfasst
        """
        analyses_text_parts: list[str] = []
        for i, analysis in enumerate(analyses, 1):
            part = (
                f"Zeugnis {i} (Niveau {analysis.niveau}/5):\n"
                f"Kontext: {analysis.kontext}\n"
                f"Aufgaben: {', '.join(analysis.aufgaben)}\n"
                f"Staerken: {', '.join(analysis.staerken)}"
            )
            analyses_text_parts.append(part)

        user_message = "\n\n".join(analyses_text_parts)

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=NARRATIVE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        return _extract_text(response).strip()

    async def process_images(
        self,
        image_paths: list[Path],
    ) -> list[ParsedDocument]:
        """Verarbeite Bilddateien via Claude Vision.

        Sendet jedes Bild an Claude Vision API und extrahiert den Text-Inhalt.

        Args:
            image_paths: Liste von Pfaden zu Bilddateien

        Returns:
            Liste von ParsedDocument mit extrahiertem Text
        """
        import base64

        classifier = DocumentParser()
        results: list[ParsedDocument] = []

        for path in image_paths:
            if not path.exists():
                logger.warning("Bilddatei nicht gefunden: %s", path)
                continue

            image_data = path.read_bytes()
            b64_data = base64.b64encode(image_data).decode("utf-8")

            suffix = path.suffix.lower()
            media_type_map: dict[str, str] = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".tiff": "image/tiff",
                ".tif": "image/tiff",
            }
            media_type = media_type_map.get(suffix, "image/png")

            try:
                image_block: anthropic.types.ImageBlockParam = {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,  # type: ignore[typeddict-item]
                        "data": b64_data,
                    },
                }
                text_block: anthropic.types.TextBlockParam = {
                    "type": "text",
                    "text": (
                        "Extrahiere den vollstaendigen Text aus diesem "
                        "Dokument/Bild. Wenn es sich um ein deutsches "
                        "Arbeitszeugnis, Zertifikat oder einen Lebenslauf "
                        "handelt, gib den Text moeglichst vollstaendig "
                        "wieder. Antworte nur mit dem extrahierten Text, "
                        "ohne Kommentare oder Formatierung."
                    ),
                }
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=4096,
                    messages=[
                        {
                            "role": "user",
                            "content": [image_block, text_block],
                        },
                    ],
                )

                extracted_text = _extract_text(response).strip()
                doc_type = classifier._classify_doc_type(path.name)

                results.append(
                    ParsedDocument(
                        path=str(path),
                        filename=path.name,
                        doc_type=doc_type,
                        text=extracted_text,
                        page_count=1,
                        parse_method="claude_vision",
                    )
                )
                logger.info(
                    "Bild verarbeitet via Vision: %s -> %d Zeichen",
                    path.name,
                    len(extracted_text),
                )

            except Exception:
                logger.exception("Fehler bei Vision-Verarbeitung: %s", path.name)
                results.append(
                    ParsedDocument(
                        path=str(path),
                        filename=path.name,
                        doc_type="sonstiges",
                        text="",
                        page_count=None,
                        parse_method="vision_failed",
                    )
                )

        return results

    @staticmethod
    def _compute_profile_version(profile: Kernprofil) -> str:
        """Berechne einen SHA256-Hash des Kernprofils als Versions-Identifier.

        Wird verwendet um zu erkennen ob sich das Profil geaendert hat
        und ob Evaluierungen neu berechnet werden muessen.
        """
        profile_json = profile.model_dump_json(indent=None)
        return hashlib.sha256(profile_json.encode("utf-8")).hexdigest()
