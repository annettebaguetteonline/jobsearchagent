"""Stage 1a: Deterministischer Keyword-Filter.

Schnelle Vorfilterung ohne LLM-Aufruf. Prüft title und raw_text
gegen konfigurierte Ausschlusskeywords mit Word-Boundary-Matching.

Beispiel-Keywords: Praktikum, Werkstudent, Ausbildung, Minijob, Teilzeit

Design:
- Word-Boundary-Matching (\\b) vermeidet Substring-False-Positives
  (z.B. "Praktikum" matcht, aber "Praktikumserfahrung" nicht fälschlicherweise
  bei einem Keyword "Praktikum" — \\b würde hier aber matchen; bei Bedarf
  die Keyword-Liste feingranularer gestalten)
- Pre-compiled Regex-Patterns für Performance
- Leere Keyword-Liste = alles passiert
- None raw_text wird toleriert (nur title geprüft)
"""

import json
import logging
import re
import time
import unicodedata

from pydantic import BaseModel

from app.db.models import Job
from app.evaluator.models import ExtractedFields, JobSkillExtracted, Stage1bResult

logger = logging.getLogger(__name__)


# ─── Ergebnis-Modell ────────────────────────────────────────────────────────


class Stage1aResult(BaseModel):
    """Ergebnis des deterministischen Keyword-Filters."""

    passed: bool
    reason: str | None = None
    stage: str = "1a"
    model: str = "deterministic"
    duration_ms: int = 0


# ─── Hilfsfunktionen ────────────────────────────────────────────────────────


def _normalize_text(text: str) -> str:
    """Normalisiere Text für Keyword-Matching.

    - Unicode NFC-Normalisierung (Umlaute konsistent)
    - Whitespace kollabieren
    - Kleinschreibung (wird über re.IGNORECASE gehandhabt, hier für
      konsistentes Logging)
    """
    # NFC: ä wird zu ä (nicht a + combining umlaut)
    text = unicodedata.normalize("NFC", text)
    # Mehrfache Whitespace-Zeichen zu einem Leerzeichen
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ─── Filter-Klasse ──────────────────────────────────────────────────────────


class Stage1aFilter:
    """Deterministischer Keyword-Ausschlussfilter.

    Prüft Job-Titel und raw_text gegen eine Liste von Ausschlusskeywords.
    Verwendet Word-Boundary-Matching mit pre-compiled Regex-Patterns.
    """

    def __init__(self, exclude_keywords: list[str]) -> None:
        """Initialisiere den Filter mit Ausschlusskeywords.

        Args:
            exclude_keywords: Liste von Keywords die zum Ausschluss führen.
                              Leere Liste = kein Ausschluss, alles passiert.
        """
        self._keywords = exclude_keywords
        self._patterns: list[tuple[str, re.Pattern[str]]] = []

        for keyword in exclude_keywords:
            if not keyword.strip():
                continue
            # Word-Boundary-Pattern: \b<keyword>\b
            # re.IGNORECASE für case-insensitive Matching
            try:
                pattern = re.compile(
                    r"\b" + re.escape(keyword.strip()) + r"\b",
                    re.IGNORECASE,
                )
                self._patterns.append((keyword.strip(), pattern))
            except re.error:
                logger.warning("Ungültiges Keyword-Pattern übersprungen: %r", keyword)

    def check(self, job: Job) -> Stage1aResult:
        """Prüfe einen Job gegen die Ausschlusskeywords.

        Prüfreihenfolge:
        1. Titel (schneller, kürzer)
        2. raw_text (falls vorhanden)

        Args:
            job: Der zu prüfende Job

        Returns:
            Stage1aResult mit passed=True (weitermachen) oder
            passed=False (ausschließen) und Begründung.
        """
        start = time.monotonic()

        # Keine Keywords konfiguriert → alles passiert
        if not self._patterns:
            duration_ms = int((time.monotonic() - start) * 1000)
            return Stage1aResult(passed=True, duration_ms=duration_ms)

        # 1. Titel prüfen
        title = _normalize_text(job.title)
        for keyword, pattern in self._patterns:
            if pattern.search(title):
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.debug(
                    "Job %d: Stage 1a SKIP — Keyword '%s' im Titel '%s'",
                    job.id,
                    keyword,
                    job.title,
                )
                return Stage1aResult(
                    passed=False,
                    reason=f"exclude_keyword: {keyword}",
                    duration_ms=duration_ms,
                )

        # 2. raw_text prüfen (falls vorhanden)
        if job.raw_text is not None:
            raw_text = _normalize_text(job.raw_text)
            for keyword, pattern in self._patterns:
                if pattern.search(raw_text):
                    duration_ms = int((time.monotonic() - start) * 1000)
                    logger.debug(
                        "Job %d: Stage 1a SKIP — Keyword '%s' im raw_text",
                        job.id,
                        keyword,
                    )
                    return Stage1aResult(
                        passed=False,
                        reason=f"exclude_keyword: {keyword}",
                        duration_ms=duration_ms,
                    )

        # Alle Checks bestanden
        duration_ms = int((time.monotonic() - start) * 1000)
        return Stage1aResult(passed=True, duration_ms=duration_ms)


# ─── Stage 1b: LLM-Vorfilter ────────────────────────────────────────────────


# JSON-Schema für die Ollama-Antwort
STAGE1B_RESPONSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "pass": {"type": "boolean"},
        "reason": {"type": "string"},
        "extracted": {
            "type": "object",
            "properties": {
                "salary_min": {"type": ["integer", "null"]},
                "salary_max": {"type": ["integer", "null"]},
                "work_model": {
                    "type": ["string", "null"],
                    "enum": ["remote", "hybrid", "onsite", None],
                },
                "skills": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "skill": {"type": "string"},
                            "type": {
                                "type": "string",
                                "enum": ["required", "nice_to_have", "mentioned"],
                            },
                            "confidence": {"type": "number"},
                        },
                        "required": ["skill", "type", "confidence"],
                    },
                },
            },
        },
    },
    "required": ["pass", "reason"],
}


STAGE1B_SYSTEM_PROMPT = """Du bist ein Job-Vorfilter für eine Jobsuche. \
Deine Aufgabe hat zwei Teile:

1) FILTER: Entscheide ob der Job zum Bewerberprofil passt (PASS/SKIP).
   - Sei LIBERAL: Lieber einen unpassenden Job durchlassen als einen passenden ablehnen.
   - SKIP nur bei offensichtlichen Ausschlusskriterien:
     * Völlig andere Fachrichtung (z.B. Pflege-Job für IT-Bewerber)
     * Explizit gefordertes Erfahrungslevel weit unter dem Bewerber (z.B. Praktikum)
     * Standort komplett unvereinbar (wenn Bewerber Präferenz hat)
   - Im Zweifel: PASS.

2) EXTRAKTION: Extrahiere fehlende Felder aus dem Stellentext, falls vorhanden.
   - salary_min/salary_max: Jahresgehalt in EUR (nur wenn explizit genannt)
   - work_model: 'remote', 'hybrid' oder 'onsite' (nur wenn klar erkennbar)
   - skills: Liste der genannten Skills mit Typ und Konfidenz

Antworte IMMER als valides JSON nach dem vorgegebenen Schema.

## Bewerberprofil

{profile_block}"""


STAGE1B_USER_PROMPT_TEMPLATE = """## Stellenanzeige

**Titel:** {title}
**Unternehmen:** {company}
**Standort:** {location}
**Work-Model:** {work_model}
**Gehalt:** {salary}

{extraction_hint}

### Stellentext (gekürzt)

{raw_text}

---

Antworte als JSON: {{"pass": bool, "reason": "...", "extracted": {{...}}}}"""


def _build_profile_block(profile: object) -> str:
    """Baue den Profil-Block für den System-Prompt."""
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

    if hasattr(profile, "narrative_profile"):
        data["narrative"] = profile.narrative_profile

    return json.dumps(data, ensure_ascii=False, indent=2)


def _build_extraction_hint(job: Job) -> str:
    """Baue den Extraktions-Hinweis: nur für NULL-Felder bitten."""
    missing: list[str] = []
    if job.salary_min is None and job.salary_max is None:
        missing.append("Gehalt (salary_min, salary_max in EUR/Jahr)")
    if job.work_model is None:
        missing.append("Work-Model (remote/hybrid/onsite)")
    missing.append("Skills (immer extrahieren)")

    if not missing:
        return "**Extraktion:** Nur Skills extrahieren."

    items = ", ".join(missing)
    return f"**Bitte extrahiere folgende fehlende Felder:** {items}"


def _parse_llm_response(raw: dict[str, object], model: str) -> Stage1bResult:
    """Parse die LLM-Antwort in ein Stage1bResult."""
    passed = bool(raw.get("pass", True))  # Default: PASS (liberal)
    reason = str(raw.get("reason", "")) or None

    extracted_fields: ExtractedFields | None = None
    extracted_raw = raw.get("extracted")
    if isinstance(extracted_raw, dict):
        skills: list[JobSkillExtracted] | None = None
        raw_skills = extracted_raw.get("skills")
        if isinstance(raw_skills, list):
            skills = []
            for s in raw_skills:
                if isinstance(s, dict) and "skill" in s:
                    skills.append(
                        JobSkillExtracted(
                            skill=str(s["skill"]),
                            skill_type=str(s.get("type", "mentioned")),
                            confidence=float(s.get("confidence", 0.5)),
                        )
                    )

        work_model_raw = extracted_raw.get("work_model")
        work_model: str | None = None
        if isinstance(work_model_raw, str) and work_model_raw in (
            "remote",
            "hybrid",
            "onsite",
        ):
            work_model = work_model_raw

        salary_min: int | None = None
        salary_max: int | None = None
        if extracted_raw.get("salary_min") is not None:
            try:
                salary_min = int(extracted_raw["salary_min"])
            except (ValueError, TypeError):
                pass
        if extracted_raw.get("salary_max") is not None:
            try:
                salary_max = int(extracted_raw["salary_max"])
            except (ValueError, TypeError):
                pass

        extracted_fields = ExtractedFields(
            salary_min=salary_min,
            salary_max=salary_max,
            work_model=work_model,
            skills=skills if skills else None,
        )

    return Stage1bResult(
        passed=passed,
        reason=reason,
        model=model,
        duration_ms=0,  # wird vom Aufrufer gesetzt
        extracted_fields=extracted_fields,
    )


class Stage1bFilter:
    """LLM-basierter Vorfilter via Ollama.

    Verwendet einen einzigen LLM-Call pro Job für:
    1. Relevanz-Entscheidung (PASS/SKIP)
    2. Extraktion fehlender Felder (Gehalt, Work-Model, Skills)
    """

    def __init__(self, client: object, model: str = "mistral-nemo:12b") -> None:
        """Initialisiere den Stage1b-Filter.

        Args:
            client: OllamaClient-Instanz (aus AP-03).
            model: Ollama-Modellname für den Vorfilter.
        """
        self._client = client
        self._model = model

    async def check(
        self,
        job: Job,
        profile: object,
        raw_text_limit: int = 1500,
    ) -> Stage1bResult:
        """Prüfe einen Job gegen das Bewerberprofil via LLM.

        Args:
            job: Der zu prüfende Job.
            profile: Kernprofil-Objekt (aus AP-05).
            raw_text_limit: Maximale Zeichenanzahl für raw_text im Prompt.

        Returns:
            Stage1bResult mit Filter-Entscheidung und extrahierten Feldern.
        """
        start_ms = time.monotonic_ns() // 1_000_000

        # Prompts bauen
        profile_block = _build_profile_block(profile)
        system_prompt = STAGE1B_SYSTEM_PROMPT.format(profile_block=profile_block)

        raw_text = (job.raw_text or "")[:raw_text_limit]
        extraction_hint = _build_extraction_hint(job)

        user_prompt = STAGE1B_USER_PROMPT_TEMPLATE.format(
            title=job.title,
            company=f"ID {job.company_id}" if job.company_id else "Unbekannt",
            location=job.location_raw or "Nicht angegeben",
            work_model=job.work_model or "Nicht angegeben",
            salary=job.salary_raw or "Nicht angegeben",
            extraction_hint=extraction_hint,
            raw_text=raw_text if raw_text else "Kein Stellentext verfügbar.",
        )

        try:
            response = await self._client.chat_json(  # type: ignore[attr-defined]
                model=self._model,
                system=system_prompt,
                user=user_prompt,
                response_schema=STAGE1B_RESPONSE_SCHEMA,
            )
        except Exception as exc:
            elapsed_ms = int(time.monotonic_ns() // 1_000_000 - start_ms)
            logger.warning(
                "Stage1b LLM-Fehler für Job %d: %s — PASS als Fallback",
                job.id,
                exc,
            )
            return Stage1bResult(
                passed=True,  # Fehler = liberal durchlassen
                reason=f"LLM-Fehler: {exc}",
                model=self._model,
                duration_ms=elapsed_ms,
                extracted_fields=None,
            )

        elapsed_ms = int(time.monotonic_ns() // 1_000_000 - start_ms)

        result = _parse_llm_response(response, self._model)
        result.duration_ms = elapsed_ms

        logger.info(
            "Stage1b Job %d: %s (%s) — %d ms",
            job.id,
            "PASS" if result.passed else "SKIP",
            result.reason or "kein Grund",
            elapsed_ms,
        )

        return result
