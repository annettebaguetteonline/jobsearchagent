"""Unit-Tests für den Dokument-Parser."""

from pathlib import Path

import pytest

from app.evaluator.document_parser import (
    DocumentParser,
)


@pytest.fixture
def parser() -> DocumentParser:
    return DocumentParser()


@pytest.fixture
def fixtures_dir(tmp_path: Path) -> Path:
    """Erstelle Fixture-Dateien für Tests."""
    # TXT-Datei
    txt_file = tmp_path / "lebenslauf_max.txt"
    txt_file.write_text(
        "Max Mustermann\nPython Developer\n\nErfahrung:\n- 5 Jahre Python\n- 3 Jahre Django",
        encoding="utf-8",
    )

    # LaTeX-Datei
    tex_file = tmp_path / "cv_template.tex"
    tex_file.write_text(
        r"""\documentclass{article}
\begin{document}
\section{Berufserfahrung}
\textbf{Python Developer} bei \emph{TestCo GmbH}
Zeitraum: 2020--2025
\subsection{Aufgaben}
Backend-Entwicklung mit Django und FastAPI.
\end{document}
""",
        encoding="utf-8",
    )

    # Bild-Datei (leer, nur für Typ-Erkennung)
    img_file = tmp_path / "arbeitszeugnis_firma.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n")  # Minimaler PNG-Header

    # Markdown-Datei
    md_file = tmp_path / "projekt_portfolio.md"
    md_file.write_text(
        "# Mein Portfolio\n\n## Projekt Alpha\nBeschreibung des Projekts.",
        encoding="utf-8",
    )

    # Unterordner mit Datei
    sub_dir = tmp_path / "zertifikate"
    sub_dir.mkdir()
    cert_file = sub_dir / "zertifikat_aws.txt"
    cert_file.write_text("AWS Solutions Architect Associate\nBestanden: 2024", encoding="utf-8")

    # Nicht unterstützte Datei
    unsupported = tmp_path / "notes.xlsx"
    unsupported.write_bytes(b"fake xlsx content")

    return tmp_path


async def test_parse_txt_file(parser: DocumentParser, fixtures_dir: Path) -> None:
    doc = await parser.parse_file(fixtures_dir / "lebenslauf_max.txt")
    assert doc.doc_type == "cv"
    assert doc.parse_method == "plain"
    assert "Python Developer" in doc.text
    assert doc.filename == "lebenslauf_max.txt"


async def test_parse_latex_file(parser: DocumentParser, fixtures_dir: Path) -> None:
    doc = await parser.parse_file(fixtures_dir / "cv_template.tex")
    assert doc.doc_type == "cv"
    assert doc.parse_method == "latex_strip"
    assert "Python Developer" in doc.text
    assert "TestCo GmbH" in doc.text
    assert "Backend-Entwicklung" in doc.text
    # LaTeX-Kommandos sollten entfernt sein
    assert "\\textbf" not in doc.text
    assert "\\begin" not in doc.text


async def test_parse_image_returns_vision_pending(
    parser: DocumentParser, fixtures_dir: Path
) -> None:
    doc = await parser.parse_file(fixtures_dir / "arbeitszeugnis_firma.png")
    assert doc.doc_type == "zeugnis"
    assert doc.parse_method == "vision_pending"
    assert doc.text == ""


def test_classify_doc_type_cv(parser: DocumentParser) -> None:
    assert parser._classify_doc_type("lebenslauf_max.pdf") == "cv"
    assert parser._classify_doc_type("CV_2025.docx") == "cv"
    assert parser._classify_doc_type("resume-john.txt") == "cv"
    assert parser._classify_doc_type("curriculum_vitae.pdf") == "cv"


def test_classify_doc_type_zeugnis(parser: DocumentParser) -> None:
    assert parser._classify_doc_type("arbeitszeugnis_testco.pdf") == "zeugnis"
    assert parser._classify_doc_type("Zwischenzeugnis_2024.pdf") == "zeugnis"
    assert parser._classify_doc_type("reference_letter.docx") == "zeugnis"


def test_classify_doc_type_sonstiges(parser: DocumentParser) -> None:
    assert parser._classify_doc_type("random_document.pdf") == "sonstiges"
    assert parser._classify_doc_type("notes.txt") == "sonstiges"


async def test_scan_folder(parser: DocumentParser, fixtures_dir: Path) -> None:
    docs = await parser.scan_folder(fixtures_dir)
    # lebenslauf_max.txt, cv_template.tex, arbeitszeugnis_firma.png,
    # projekt_portfolio.md, zertifikate/zertifikat_aws.txt
    assert len(docs) == 5
    doc_types = {d.doc_type for d in docs}
    assert "cv" in doc_types
    assert "zeugnis" in doc_types
    assert "zertifikat" in doc_types
    assert "projekt" in doc_types


async def test_scan_folder_skips_unsupported(parser: DocumentParser, fixtures_dir: Path) -> None:
    docs = await parser.scan_folder(fixtures_dir)
    filenames = {d.filename for d in docs}
    assert "notes.xlsx" not in filenames


async def test_parse_file_not_found(parser: DocumentParser, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        await parser.parse_file(tmp_path / "nonexistent.pdf")


async def test_parse_unsupported_format(parser: DocumentParser, tmp_path: Path) -> None:
    xlsx_file = tmp_path / "test.xlsx"
    xlsx_file.write_bytes(b"fake")
    with pytest.raises(ValueError, match="Nicht unterstütztes Format"):
        await parser.parse_file(xlsx_file)
