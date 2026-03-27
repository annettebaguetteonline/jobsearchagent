"""Stage 2 Evaluierung: Claude Tiefanalyse einer einzelnen Stelle.

Zwei Strategien:
- structured_core: Kompaktes Kernprofil (~400 Tokens) + Job-Details
- rag_hybrid: Kernprofil + Top-5 RAG-Chunks (~4300 Tokens) + Job-Details

Dimensionen (konfigurierbare Gewichte):
- Skills-Match (35%): Primary/Secondary Overlap
- Erfahrungslevel (25%): Senior/Lead Requirement Fit
- Branche/Domäne (20%): Known vs. New Industry
- Standort/Remote (15%): ÖPNV-Score Integration
- Karrierepotenzial (5%): Growth, Tech Future
"""

import json
import logging
import time

import anthropic
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ─── Modelle ─────────────────────────────────────────────────────────────────


class FeedbackExample(BaseModel):
    """Ein Feedback-Beispiel für Few-Shot Learning."""

    job_title: str
    company: str
    model_score: float
    user_decision: str
    reasoning: str | None = None


class Stage2Result(BaseModel):
    """Ergebnis der Stage-2-Tiefanalyse."""

    score: float  # 1.0-10.0
    score_breakdown: dict[str, float]  # {skills, level, domain, location, potential}
    recommendation: str  # 'APPLY'|'MAYBE'|'SKIP'
    match_reasons: list[str]
    missing_skills: list[str]
    salary_estimate: str | None = None
    summary: str
    application_tips: list[str]
    model: str
    tokens_used: int
    duration_ms: int
    strategy: str


# ─── Gewichte ────────────────────────────────────────────────────────────────

DEFAULT_WEIGHTS: dict[str, float] = {
    "skills": 0.35,
    "level": 0.25,
    "domain": 0.20,
    "location": 0.15,
    "potential": 0.05,
}


# ─── Prompt-Konstruktion ────────────────────────────────────────────────────


SYSTEM_PROMPT = (
    "Du bist ein erfahrener Karriereberater und Job-Analyst. "
    "Deine Aufgabe ist die Tiefanalyse einer Stellenanzeige "
    "für einen spezifischen Bewerber.\n\n"
    "Bewerte die Stelle entlang dieser 5 Dimensionen "
    "(Gewichte in Klammern):\n\n"
    "1. **Skills-Match** ({skills_weight:.0%}): "
    "Übereinstimmung der Primary/Secondary Skills. "
    "Fehlende Kernkompetenzen stark abwerten.\n"
    "2. **Erfahrungslevel** ({level_weight:.0%}): "
    "Passt das geforderte Level "
    "(Junior/Senior/Lead/etc.) zum Bewerber?\n"
    "3. **Branche/Domäne** ({domain_weight:.0%}): "
    "Bekannte vs. neue Branche. "
    "Transferierbare Erfahrung berücksichtigen.\n"
    "4. **Standort/Remote** ({location_weight:.0%}): "
    "Pendelbewertung (ÖPNV-Score wenn verfügbar). "
    "Remote = Bonus.\n"
    "5. **Karrierepotenzial** ({potential_weight:.0%}): "
    "Wachstumschancen, Zukunftstechnologien, "
    "Aufstiegsmöglichkeiten.\n\n"
    "## Scoring\n\n"
    "- Jede Dimension: 1.0 bis 10.0\n"
    "- Gesamtscore: Gewichteter Durchschnitt\n"
    "- Empfehlung basierend auf Gesamtscore:\n"
    "  - >= 7.0: APPLY (aktiv bewerben)\n"
    "  - 5.0-6.9: MAYBE (bei Interesse genauer ansehen)\n"
    "  - < 5.0: SKIP (nicht passend)\n\n"
    "## Output-Format\n\n"
    "Antworte IMMER als valides JSON:\n\n"
    "```json\n"
    "{{\n"
    '  "score": 7.5,\n'
    '  "score_breakdown": {{\n'
    '    "skills": 8.0,\n'
    '    "level": 7.0,\n'
    '    "domain": 7.5,\n'
    '    "location": 8.0,\n'
    '    "potential": 6.0\n'
    "  }},\n"
    '  "recommendation": "APPLY",\n'
    '  "match_reasons": '
    '["Python/FastAPI Kernkompetenz passt perfekt", "..."],\n'
    '  "missing_skills": ["Kubernetes", "..."],\n'
    '  "salary_estimate": '
    '"65.000-80.000 EUR/Jahr (Schätzung)",\n'
    '  "summary": '
    '"Gut passende Senior-Backend-Stelle...",\n'
    '  "application_tips": '
    '["Kubernetes-Erfahrung hervorheben", "..."]\n'
    "}}\n"
    "```\n\n"
    "{feedback_section}"
)


FEEDBACK_SECTION_TEMPLATE = (
    "## Kalibrierung "
    "(bisherige Entscheidungen des Bewerbers)\n\n"
    "Hier sind Beispiele bisheriger Bewertungen und "
    "wie der Bewerber entschieden hat. "
    "Passe dein Scoring entsprechend an:\n\n"
    "{examples}"
)


USER_PROMPT_STRUCTURED = """## Bewerberprofil (Kernprofil)

```json
{profile_json}
```

## Stellenanzeige

**Titel:** {title}
**Unternehmen:** {company_name}
**Standort:** {location}
**Work-Model:** {work_model}
**Gehalt:** {salary}
**Branche:** {sector}

{location_score_block}

### Stellentext

{raw_text}"""


RAG_CHUNKS_BLOCK = """## Relevante Auszüge aus den Bewerbungsunterlagen

{chunks_text}"""


def _format_profile_json(profile: object) -> str:
    """Formatiere das Kernprofil als kompaktes JSON (~400 Tokens)."""
    data: dict[str, object] = {}

    if hasattr(profile, "skills"):
        skills = profile.skills
        data["skills"] = {
            "primary": getattr(skills, "primary", []),
            "secondary": getattr(skills, "secondary", []),
            "domains": getattr(skills, "domains", []),
        }

    if hasattr(profile, "experience"):
        exp = profile.experience
        data["experience"] = {
            "total_years": getattr(exp, "total_years", None),
            "levels_held": getattr(exp, "levels_held", []),
            "industries": getattr(exp, "industries", []),
        }

    if hasattr(profile, "preferences"):
        prefs = profile.preferences
        data["preferences"] = {
            "locations": getattr(prefs, "locations", []),
            "min_level": getattr(prefs, "min_level", None),
            "avoid": getattr(prefs, "avoid", []),
        }

    if hasattr(profile, "certifications"):
        data["certifications"] = profile.certifications

    if hasattr(profile, "narrative_profile"):
        data["narrative"] = profile.narrative_profile

    return json.dumps(data, ensure_ascii=False, indent=2)


def _format_feedback_examples(examples: list[FeedbackExample]) -> str:
    """Formatiere Feedback-Beispiele für Few-Shot-Kalibrierung."""
    if not examples:
        return ""

    lines: list[str] = []
    for ex in examples:
        line = (
            f"- **{ex.job_title}** bei {ex.company}: "
            f"Score {ex.model_score:.1f} → Bewerber: {ex.user_decision}"
        )
        if ex.reasoning:
            line += f" ({ex.reasoning})"
        lines.append(line)

    return FEEDBACK_SECTION_TEMPLATE.format(examples="\n".join(lines))


def _format_location_score_block(location_score: object | None) -> str:
    """Formatiere den Location-Score-Block für den Prompt."""
    if location_score is None:
        return ""

    score = getattr(location_score, "score", None)
    effective = getattr(location_score, "effective_minutes", None)
    transit_pub = getattr(location_score, "transit_minutes_public", None)
    transit_car = getattr(location_score, "transit_minutes_car", None)
    is_remote = getattr(location_score, "is_remote", False)

    if is_remote:
        return "**Location-Score:** 1.0 (Remote)"

    parts = [f"**Location-Score:** {score:.2f}" if score is not None else ""]
    if effective is not None:
        parts.append(f"Effektive Pendelzeit: {effective} min")
    if transit_pub is not None:
        parts.append(f"ÖPNV: {transit_pub} min")
    if transit_car is not None:
        parts.append(f"Auto: {transit_car} min")

    return " | ".join(p for p in parts if p)


def _format_rag_chunks(rag_chunks: list[object]) -> str:
    """Formatiere RAG-Chunks für den Prompt."""
    if not rag_chunks:
        return ""

    chunk_texts: list[str] = []
    for i, chunk in enumerate(rag_chunks, 1):
        source = getattr(chunk, "source_doc", "unbekannt")
        doc_type = getattr(chunk, "doc_type", "unbekannt")
        text = getattr(chunk, "text", "")
        relevance = getattr(chunk, "relevance_score", 0.0)

        chunk_texts.append(
            f"### Chunk {i} (Quelle: {source}, Typ: {doc_type}, "
            f"Relevanz: {relevance:.2f})\n\n{text}"
        )

    return RAG_CHUNKS_BLOCK.format(chunks_text="\n\n---\n\n".join(chunk_texts))


def build_prompt(
    job: object,
    company: object | None,
    profile: object,
    strategy: str,
    rag_chunks: list[object] | None = None,
    location_score: object | None = None,
    feedback_examples: list[FeedbackExample] | None = None,
    weights: dict[str, float] | None = None,
) -> tuple[str, str]:
    """Baue System- und User-Prompt für die Stage-2-Evaluierung.

    Diese Funktion ist als reine Funktion (pure function) testbar,
    ohne API-Calls.

    Args:
        job: Job-Objekt.
        company: Company-Objekt (optional).
        profile: Kernprofil-Objekt (aus AP-05).
        strategy: 'structured_core' oder 'rag_hybrid'.
        rag_chunks: Liste von RAGChunk-Objekten (nur für rag_hybrid).
        location_score: LocationScore-Objekt (optional).
        feedback_examples: Feedback-Beispiele für Few-Shot (optional).
        weights: Dimensions-Gewichte (optional, Default: DEFAULT_WEIGHTS).

    Returns:
        Tuple (system_prompt, user_prompt).
    """
    w = weights or DEFAULT_WEIGHTS

    # Feedback-Sektion
    feedback_section = ""
    if feedback_examples:
        feedback_section = _format_feedback_examples(feedback_examples)

    # System-Prompt
    system_prompt = SYSTEM_PROMPT.format(
        skills_weight=w.get("skills", 0.35),
        level_weight=w.get("level", 0.25),
        domain_weight=w.get("domain", 0.20),
        location_weight=w.get("location", 0.15),
        potential_weight=w.get("potential", 0.05),
        feedback_section=feedback_section,
    )

    # User-Prompt: Profil-JSON
    profile_json = _format_profile_json(profile)

    # Job-Details
    title = getattr(job, "title", "Unbekannt")
    company_name = getattr(company, "name", "Unbekannt") if company else "Unbekannt"
    location = getattr(job, "location_raw", None) or "Nicht angegeben"
    work_model = getattr(job, "work_model", None) or "Nicht angegeben"
    salary = getattr(job, "salary_raw", None) or "Nicht angegeben"
    sector = getattr(job, "sector", None) or "Nicht angegeben"
    raw_text = getattr(job, "raw_text", None) or "Kein Stellentext verfügbar."

    # Location-Score Block
    location_score_block = _format_location_score_block(location_score)

    # User-Prompt
    user_prompt = USER_PROMPT_STRUCTURED.format(
        profile_json=profile_json,
        title=title,
        company_name=company_name,
        location=location,
        work_model=work_model,
        salary=salary,
        sector=sector,
        location_score_block=location_score_block,
        raw_text=raw_text,
    )

    # RAG-Chunks hinzufügen (nur für rag_hybrid)
    if strategy == "rag_hybrid" and rag_chunks:
        rag_block = _format_rag_chunks(rag_chunks)
        user_prompt = rag_block + "\n\n" + user_prompt

    return system_prompt, user_prompt


# ─── Response Parsing ────────────────────────────────────────────────────────


def _parse_stage2_response(
    raw_text: str,
    model: str,
    tokens_used: int,
    duration_ms: int,
    strategy: str,
) -> Stage2Result:
    """Parse die Claude-Antwort in ein Stage2Result.

    Versucht JSON aus der Antwort zu extrahieren, auch wenn es
    in Markdown-Codeblocks eingebettet ist.
    """
    # Versuche JSON zu extrahieren
    json_str = raw_text.strip()

    # Entferne eventuelle Markdown-Codeblocks
    if "```json" in json_str:
        start = json_str.index("```json") + 7
        end = json_str.index("```", start)
        json_str = json_str[start:end].strip()
    elif "```" in json_str:
        start = json_str.index("```") + 3
        end = json_str.index("```", start)
        json_str = json_str[start:end].strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.error("Stage2 JSON-Parse-Fehler: %s\nAntwort: %s", exc, raw_text[:500])
        # Fallback: minimales Ergebnis
        return Stage2Result(
            score=5.0,
            score_breakdown={
                "skills": 5.0,
                "level": 5.0,
                "domain": 5.0,
                "location": 5.0,
                "potential": 5.0,
            },
            recommendation="MAYBE",
            match_reasons=["JSON-Parse-Fehler — manuelle Prüfung empfohlen"],
            missing_skills=[],
            salary_estimate=None,
            summary="Automatische Analyse fehlgeschlagen. Bitte manuell prüfen.",
            application_tips=[],
            model=model,
            tokens_used=tokens_used,
            duration_ms=duration_ms,
            strategy=strategy,
        )

    # Score validieren und begrenzen
    score = max(1.0, min(10.0, float(data.get("score", 5.0))))

    # Score-Breakdown validieren
    breakdown = data.get("score_breakdown", {})
    validated_breakdown: dict[str, float] = {}
    for key in ("skills", "level", "domain", "location", "potential"):
        val = breakdown.get(key, 5.0)
        validated_breakdown[key] = max(1.0, min(10.0, float(val)))

    # Recommendation validieren
    recommendation = str(data.get("recommendation", "MAYBE")).upper()
    if recommendation not in ("APPLY", "MAYBE", "SKIP"):
        recommendation = "MAYBE"

    return Stage2Result(
        score=round(score, 1),
        score_breakdown=validated_breakdown,
        recommendation=recommendation,
        match_reasons=list(data.get("match_reasons", [])),
        missing_skills=list(data.get("missing_skills", [])),
        salary_estimate=data.get("salary_estimate"),
        summary=str(data.get("summary", "")),
        application_tips=list(data.get("application_tips", [])),
        model=model,
        tokens_used=tokens_used,
        duration_ms=duration_ms,
        strategy=strategy,
    )


# ─── Stage 2 Evaluator ──────────────────────────────────────────────────────


class Stage2Evaluator:
    """Tiefanalyse einer Stelle via Claude Haiku.

    Nutzt die Anthropic SDK direkt (kein OllamaClient).
    """

    def __init__(
        self,
        anthropic_key: str,
        rag: object | None = None,
        model: str = "claude-haiku-4-5",
    ) -> None:
        """Initialisiere den Stage-2-Evaluator.

        Args:
            anthropic_key: Anthropic API Key.
            rag: RAGPipeline-Instanz (optional, für rag_hybrid Strategie).
            model: Claude-Modellname.
        """
        self._client = anthropic.AsyncAnthropic(api_key=anthropic_key)
        self._rag = rag
        self._model = model

    async def evaluate_single(
        self,
        job: object,
        company: object | None,
        profile: object,
        strategy: str = "structured_core",
        location_score: object | None = None,
        feedback_examples: list[FeedbackExample] | None = None,
        weights: dict[str, float] | None = None,
        user_id: str | None = None,
    ) -> Stage2Result:
        """Evaluiere eine einzelne Stelle.

        Args:
            job: Job-Objekt.
            company: Company-Objekt (optional).
            profile: Kernprofil-Objekt (aus AP-05).
            strategy: 'structured_core' oder 'rag_hybrid'.
            location_score: LocationScore (optional).
            feedback_examples: Feedback für Few-Shot Kalibrierung.
            weights: Dimensions-Gewichte (optional).
            user_id: User-UUID (für RAG-Query, nur bei rag_hybrid).

        Returns:
            Stage2Result mit vollständiger Analyse.
        """
        start_ms = time.monotonic_ns() // 1_000_000

        # RAG-Chunks laden (nur bei rag_hybrid)
        rag_chunks: list[object] = []
        if strategy == "rag_hybrid" and self._rag is not None and user_id is not None:
            raw_text = getattr(job, "raw_text", "") or ""
            rag_chunks = await self._rag.query(  # type: ignore[attr-defined]
                user_id=user_id,
                job_text=raw_text,
                top_k=5,
            )

        # Prompt bauen
        system_prompt, user_prompt = build_prompt(
            job=job,
            company=company,
            profile=profile,
            strategy=strategy,
            rag_chunks=rag_chunks,
            location_score=location_score,
            feedback_examples=feedback_examples,
            weights=weights,
        )

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=2000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.APIError as exc:
            elapsed_ms = int(time.monotonic_ns() // 1_000_000 - start_ms)
            logger.error("Stage2 API-Fehler für Job: %s", exc)
            return Stage2Result(
                score=5.0,
                score_breakdown={
                    "skills": 5.0,
                    "level": 5.0,
                    "domain": 5.0,
                    "location": 5.0,
                    "potential": 5.0,
                },
                recommendation="MAYBE",
                match_reasons=["API-Fehler — manuelle Prüfung empfohlen"],
                missing_skills=[],
                salary_estimate=None,
                summary=f"API-Fehler: {exc}",
                application_tips=[],
                model=self._model,
                tokens_used=0,
                duration_ms=elapsed_ms,
                strategy=strategy,
            )

        elapsed_ms = int(time.monotonic_ns() // 1_000_000 - start_ms)

        # Tokens zählen
        tokens_used = response.usage.input_tokens + response.usage.output_tokens

        # Response-Text extrahieren
        response_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                response_text += block.text

        result = _parse_stage2_response(
            raw_text=response_text,
            model=self._model,
            tokens_used=tokens_used,
            duration_ms=elapsed_ms,
            strategy=strategy,
        )

        logger.info(
            "Stage2: Score %.1f (%s) — %s — %d Tokens — %d ms",
            result.score,
            result.recommendation,
            strategy,
            tokens_used,
            elapsed_ms,
        )

        return result
