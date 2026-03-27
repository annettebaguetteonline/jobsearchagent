"""Pydantic-Modelle für die Evaluierungs-Pipeline (Stage 1b + Stage 2)."""

from pydantic import BaseModel


class JobSkillExtracted(BaseModel):
    """Ein aus dem Stellentext extrahierter Skill."""

    skill: str
    skill_type: str  # 'required'|'nice_to_have'|'mentioned'
    confidence: float


class ExtractedFields(BaseModel):
    """Fehlende Felder die Stage 1b aus dem Stellentext extrahiert."""

    salary_min: int | None = None
    salary_max: int | None = None
    work_model: str | None = None  # 'remote'|'hybrid'|'onsite'
    skills: list[JobSkillExtracted] | None = None


class Stage1bResult(BaseModel):
    """Ergebnis des LLM-Vorfilters (Stage 1b)."""

    passed: bool
    reason: str | None = None
    stage: str = "1b"
    model: str
    duration_ms: int
    extracted_fields: ExtractedFields | None = None
