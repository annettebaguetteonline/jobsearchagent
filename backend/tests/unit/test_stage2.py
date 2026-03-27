"""Unit-Tests für Stage 2 Evaluator.

Prompt-Konstruktion und Response-Parsing werden ohne API-Calls getestet.
"""

import json
from unittest.mock import MagicMock

from app.evaluator.stage2 import (
    FeedbackExample,
    _format_feedback_examples,
    _format_location_score_block,
    _format_profile_json,
    _format_rag_chunks,
    _parse_stage2_response,
    build_prompt,
)


def _make_job(**overrides: object) -> MagicMock:
    """Hilfsfunktion: Mock-Job."""
    job = MagicMock()
    job.id = overrides.get("id", 1)
    job.title = overrides.get("title", "Senior Python Developer")
    job.company_id = overrides.get("company_id", 10)
    job.location_raw = overrides.get("location_raw", "Frankfurt am Main")
    job.work_model = overrides.get("work_model", "hybrid")
    job.salary_raw = overrides.get("salary_raw", "65.000-80.000 EUR")
    job.sector = overrides.get("sector", "private")
    job.raw_text = overrides.get(
        "raw_text",
        "Wir suchen einen Senior Python Developer mit FastAPI und PostgreSQL.",
    )
    return job


def _make_company(name: str = "TechCorp GmbH") -> MagicMock:
    """Hilfsfunktion: Mock-Company."""
    company = MagicMock()
    company.name = name
    return company


def _make_profile() -> MagicMock:
    """Hilfsfunktion: Mock-Kernprofil."""
    profile = MagicMock()
    profile.skills = MagicMock()
    profile.skills.primary = ["Python", "FastAPI", "PostgreSQL"]
    profile.skills.secondary = ["Docker", "AWS", "Redis"]
    profile.skills.domains = ["Backend", "Data Engineering"]
    profile.experience = MagicMock()
    profile.experience.total_years = 8
    profile.experience.levels_held = ["Senior", "Lead"]
    profile.experience.industries = ["FinTech", "E-Commerce"]
    profile.preferences = MagicMock()
    profile.preferences.locations = ["Frankfurt", "Remote"]
    profile.preferences.min_level = "Senior"
    profile.preferences.avoid = ["SAP"]
    profile.certifications = ["AWS Solutions Architect"]
    profile.narrative_profile = "Erfahrener Backend-Entwickler."
    return profile


def _make_location_score(
    score: float = 0.85,
    effective_minutes: int = 25,
    transit_minutes_public: int = 35,
    transit_minutes_car: int = 20,
    is_remote: bool = False,
) -> MagicMock:
    """Hilfsfunktion: Mock-LocationScore."""
    ls = MagicMock()
    ls.score = score
    ls.effective_minutes = effective_minutes
    ls.transit_minutes_public = transit_minutes_public
    ls.transit_minutes_car = transit_minutes_car
    ls.is_remote = is_remote
    return ls


def _make_rag_chunk(
    text: str = "Python, FastAPI Erfahrung seit 2019",
    source_doc: str = "lebenslauf.pdf",
    doc_type: str = "cv",
    relevance_score: float = 0.85,
) -> MagicMock:
    """Hilfsfunktion: Mock-RAGChunk."""
    chunk = MagicMock()
    chunk.text = text
    chunk.source_doc = source_doc
    chunk.doc_type = doc_type
    chunk.relevance_score = relevance_score
    return chunk


# ─── Prompt-Building Tests ──────────────────────────────────────────────────


def test_build_prompt_structured_core() -> None:
    """structured_core Strategie: System + User Prompt ohne RAG-Chunks."""
    system, user = build_prompt(
        job=_make_job(),
        company=_make_company(),
        profile=_make_profile(),
        strategy="structured_core",
    )

    assert "Skills-Match" in system
    assert "35%" in system
    assert "Senior Python Developer" in user
    assert "TechCorp GmbH" in user
    assert "Python" in user  # Profil-JSON
    assert "Relevante Auszüge" not in user  # Kein RAG-Block


def test_build_prompt_rag_hybrid() -> None:
    """rag_hybrid Strategie: Prompt enthält RAG-Chunks."""
    chunks = [
        _make_rag_chunk(text="5 Jahre Python/FastAPI Backend-Entwicklung"),
        _make_rag_chunk(
            text="AWS Solutions Architect Zertifizierung 2023",
            doc_type="zertifikat",
        ),
    ]

    system, user = build_prompt(
        job=_make_job(),
        company=_make_company(),
        profile=_make_profile(),
        strategy="rag_hybrid",
        rag_chunks=chunks,
    )

    assert "Relevante Auszüge" in user
    assert "5 Jahre Python/FastAPI" in user
    assert "AWS Solutions Architect" in user


def test_build_prompt_with_feedback_examples() -> None:
    """Feedback-Beispiele erscheinen im System-Prompt."""
    examples = [
        FeedbackExample(
            job_title="Backend Dev",
            company="TestCorp",
            model_score=7.5,
            user_decision="APPLY",
            reasoning="Gute Skills-Match",
        ),
        FeedbackExample(
            job_title="SAP Berater",
            company="ConsultCo",
            model_score=4.0,
            user_decision="SKIP",
        ),
    ]

    system, user = build_prompt(
        job=_make_job(),
        company=_make_company(),
        profile=_make_profile(),
        strategy="structured_core",
        feedback_examples=examples,
    )

    assert "Kalibrierung" in system
    assert "Backend Dev" in system
    assert "APPLY" in system
    assert "SAP Berater" in system


def test_build_prompt_with_location_score() -> None:
    """Location-Score wird im User-Prompt angezeigt."""
    system, user = build_prompt(
        job=_make_job(),
        company=_make_company(),
        profile=_make_profile(),
        strategy="structured_core",
        location_score=_make_location_score(score=0.85, effective_minutes=25),
    )

    assert "0.85" in user
    assert "25 min" in user


def test_build_prompt_with_remote_location_score() -> None:
    """Remote Location-Score wird korrekt angezeigt."""
    system, user = build_prompt(
        job=_make_job(work_model="remote"),
        company=_make_company(),
        profile=_make_profile(),
        strategy="structured_core",
        location_score=_make_location_score(score=1.0, is_remote=True),
    )

    assert "1.0 (Remote)" in user


def test_build_prompt_custom_weights() -> None:
    """Benutzerdefinierte Gewichte werden im System-Prompt angezeigt."""
    custom_weights = {
        "skills": 0.50,
        "level": 0.20,
        "domain": 0.15,
        "location": 0.10,
        "potential": 0.05,
    }

    system, user = build_prompt(
        job=_make_job(),
        company=_make_company(),
        profile=_make_profile(),
        strategy="structured_core",
        weights=custom_weights,
    )

    assert "50%" in system


def test_build_prompt_no_company() -> None:
    """Ohne Company-Objekt: 'Unbekannt' wird angezeigt."""
    system, user = build_prompt(
        job=_make_job(),
        company=None,
        profile=_make_profile(),
        strategy="structured_core",
    )

    assert "Unbekannt" in user


# ─── Response Parsing Tests ─────────────────────────────────────────────────


def test_parse_valid_json_response() -> None:
    """Gültiges JSON wird korrekt geparsed."""
    raw = json.dumps(
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
            "match_reasons": ["Python passt perfekt"],
            "missing_skills": ["Kubernetes"],
            "salary_estimate": "65.000-80.000 EUR/Jahr",
            "summary": "Sehr gute Stelle für Backend-Entwickler.",
            "application_tips": ["Kubernetes-Erfahrung hervorheben"],
        }
    )

    result = _parse_stage2_response(raw, "claude-haiku-4-5", 1500, 3000, "structured_core")

    assert result.score == 7.5
    assert result.recommendation == "APPLY"
    assert result.score_breakdown["skills"] == 8.0
    assert "Python passt perfekt" in result.match_reasons
    assert "Kubernetes" in result.missing_skills
    assert result.model == "claude-haiku-4-5"
    assert result.tokens_used == 1500
    assert result.strategy == "structured_core"


def test_parse_json_in_markdown_codeblock() -> None:
    """JSON in ```json Codeblock wird korrekt extrahiert."""
    raw = """Hier ist meine Analyse:

```json
{
    "score": 6.5,
    "score_breakdown": {
        "skills": 7.0,
        "level": 6.0,
        "domain": 6.5,
        "location": 7.0,
        "potential": 5.0
    },
    "recommendation": "MAYBE",
    "match_reasons": ["OK"],
    "missing_skills": [],
    "summary": "Mittel",
    "application_tips": []
}
```"""

    result = _parse_stage2_response(raw, "claude-haiku-4-5", 1000, 2000, "rag_hybrid")
    assert result.score == 6.5
    assert result.recommendation == "MAYBE"


def test_parse_invalid_json_returns_fallback() -> None:
    """Ungültiges JSON ergibt Fallback-Ergebnis (Score 5.0, MAYBE)."""
    raw = "Das ist kein JSON, sondern Freitext."

    result = _parse_stage2_response(raw, "claude-haiku-4-5", 500, 1000, "structured_core")
    assert result.score == 5.0
    assert result.recommendation == "MAYBE"
    assert "Parse-Fehler" in result.match_reasons[0]


def test_parse_score_clamped_to_range() -> None:
    """Score wird auf 1.0-10.0 begrenzt."""
    raw = json.dumps(
        {
            "score": 15.0,
            "score_breakdown": {
                "skills": 0.0,
                "level": 12.0,
                "domain": 5.0,
                "location": 5.0,
                "potential": 5.0,
            },
            "recommendation": "APPLY",
            "match_reasons": [],
            "missing_skills": [],
            "summary": "Test",
            "application_tips": [],
        }
    )

    result = _parse_stage2_response(raw, "test", 100, 100, "structured_core")
    assert result.score == 10.0
    assert result.score_breakdown["skills"] == 1.0  # 0.0 → 1.0
    assert result.score_breakdown["level"] == 10.0  # 12.0 → 10.0


def test_parse_invalid_recommendation_defaults_to_maybe() -> None:
    """Ungültige Recommendation wird zu MAYBE."""
    raw = json.dumps(
        {
            "score": 7.0,
            "score_breakdown": {
                "skills": 7.0,
                "level": 7.0,
                "domain": 7.0,
                "location": 7.0,
                "potential": 7.0,
            },
            "recommendation": "HMMMM",
            "match_reasons": [],
            "missing_skills": [],
            "summary": "Test",
            "application_tips": [],
        }
    )

    result = _parse_stage2_response(raw, "test", 100, 100, "structured_core")
    assert result.recommendation == "MAYBE"


# ─── Hilfsfunktionen Tests ──────────────────────────────────────────────────


def test_format_profile_json_contains_skills() -> None:
    """Profil-JSON enthält Skills, Erfahrung, Präferenzen."""
    profile = _make_profile()
    result = _format_profile_json(profile)
    data = json.loads(result)
    assert "Python" in data["skills"]["primary"]
    assert data["experience"]["total_years"] == 8
    assert "Frankfurt" in data["preferences"]["locations"]


def test_format_feedback_examples_empty() -> None:
    """Leere Feedback-Liste ergibt leeren String."""
    assert _format_feedback_examples([]) == ""


def test_format_location_score_none() -> None:
    """None Location-Score ergibt leeren String."""
    assert _format_location_score_block(None) == ""


def test_format_rag_chunks_empty() -> None:
    """Leere RAG-Chunks ergeben leeren String."""
    assert _format_rag_chunks([]) == ""
