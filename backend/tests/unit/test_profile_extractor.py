"""Unit-Tests fuer die Kernprofil-Extraktion."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from anthropic.types import TextBlock

from app.evaluator.document_parser import ParsedDocument
from app.evaluator.profile_extractor import (
    Experience,
    Kernprofil,
    Preferences,
    ProfileExtractor,
    SkillSet,
    ZeugnisAnalysis,
)


def _mock_response(text: str) -> MagicMock:
    """Erzeuge einen gemockten Claude-API-Response."""
    response = MagicMock()
    response.content = [TextBlock(type="text", text=text)]
    return response


@pytest.fixture()
def extractor() -> ProfileExtractor:
    return ProfileExtractor(anthropic_key="test-key")


async def test_decode_zeugnis(extractor: ProfileExtractor) -> None:
    mock_data = {
        "aufgaben": ["Backend-Entwicklung", "Code-Reviews"],
        "staerken": ["Selbstaendigkeit", "Teamfaehigkeit"],
        "niveau": 2,
        "kontext": "Senior Developer bei FinTech GmbH, 3 Jahre",
    }
    extractor._client.messages.create = AsyncMock(
        return_value=_mock_response(json.dumps(mock_data))
    )

    result = await extractor.decode_zeugnis(
        "Herr Mustermann war stets zu unserer vollen Zufriedenheit..."
    )
    assert isinstance(result, ZeugnisAnalysis)
    assert result.niveau == 2
    assert "Backend-Entwicklung" in result.aufgaben
    assert len(result.staerken) == 2


async def test_build_narrative(extractor: ProfileExtractor) -> None:
    extractor._client.messages.create = AsyncMock(
        return_value=_mock_response("Der Kandidat zeigt eine stetige berufliche Entwicklung...")
    )

    analyses = [
        ZeugnisAnalysis(
            aufgaben=["Entwicklung"],
            staerken=["Teamarbeit"],
            niveau=2,
            kontext="Developer bei Co A",
        ),
        ZeugnisAnalysis(
            aufgaben=["Architektur"],
            staerken=["Fuehrung"],
            niveau=1,
            kontext="Senior Dev bei Co B",
        ),
    ]
    result = await extractor.build_narrative(analyses)
    assert isinstance(result, str)
    assert len(result) > 0


async def test_extract_profile_with_cv_only(extractor: ProfileExtractor) -> None:
    profile_data = {
        "skills": {
            "primary": ["Python", "Django"],
            "secondary": ["Docker"],
            "domains": ["Web Development"],
        },
        "experience": {
            "total_years": 5,
            "levels_held": ["Junior", "Mid-Level"],
            "industries": ["IT"],
        },
        "preferences": {
            "locations": ["Frankfurt"],
            "min_level": "Mid-Level",
            "avoid": [],
        },
        "certifications": ["AWS SAA"],
        "projects_summary": ["E-Commerce Platform"],
    }
    extractor._client.messages.create = AsyncMock(
        return_value=_mock_response(json.dumps(profile_data))
    )

    docs = [
        ParsedDocument(
            path="/tmp/cv.pdf",
            filename="lebenslauf.pdf",
            doc_type="cv",
            text="Python Developer mit 5 Jahren Erfahrung...",
            parse_method="pymupdf",
        ),
    ]
    result = await extractor.extract_profile(docs)
    assert isinstance(result, Kernprofil)
    assert "Python" in result.skills.primary
    assert result.experience.total_years == 5


def test_compute_profile_version_deterministic() -> None:
    profile = Kernprofil(
        skills=SkillSet(primary=["Python"], secondary=[], domains=[]),
        experience=Experience(total_years=5, levels_held=["Mid"], industries=["IT"]),
        preferences=Preferences(locations=["FFM"], min_level="Mid", avoid=[]),
        narrative_profile="Test narrative",
        certifications=[],
        projects_summary=[],
    )
    v1 = ProfileExtractor._compute_profile_version(profile)
    v2 = ProfileExtractor._compute_profile_version(profile)
    assert v1 == v2
    assert len(v1) == 64  # SHA256 hex digest


def test_compute_profile_version_changes_on_diff() -> None:
    p1 = Kernprofil(
        skills=SkillSet(primary=["Python"], secondary=[], domains=[]),
        experience=Experience(total_years=5, levels_held=[], industries=[]),
        preferences=Preferences(locations=[], min_level="Mid", avoid=[]),
        narrative_profile="V1",
        certifications=[],
        projects_summary=[],
    )
    p2 = p1.model_copy(update={"narrative_profile": "V2"})
    assert ProfileExtractor._compute_profile_version(
        p1
    ) != ProfileExtractor._compute_profile_version(p2)


async def test_process_images_success(
    tmp_path: "Path",  # noqa: F821
    extractor: ProfileExtractor,
) -> None:
    img_path = tmp_path / "zeugnis_scan.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    extractor._client.messages.create = AsyncMock(
        return_value=_mock_response(
            "Arbeitszeugnis\nHerr Max Mustermann war als Developer taetig..."
        )
    )

    results = await extractor.process_images([img_path])
    assert len(results) == 1
    assert results[0].parse_method == "claude_vision"
    assert "Developer" in results[0].text


def test_zeugnis_analysis_model_validation() -> None:
    analysis = ZeugnisAnalysis(
        aufgaben=["Aufgabe 1"],
        staerken=["Staerke 1"],
        niveau=3,
        kontext="Kontext",
    )
    assert analysis.niveau == 3
    assert len(analysis.aufgaben) == 1
