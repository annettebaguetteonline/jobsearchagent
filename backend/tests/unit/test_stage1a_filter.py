"""Unit-Tests für den Stage-1a Keyword-Filter."""

from app.db.models import Job, now_iso
from app.evaluator.stage1 import Stage1aFilter, _normalize_text


def _make_job(
    title: str = "Python Developer",
    raw_text: str | None = "We are looking for a Python developer.",
    job_id: int = 1,
) -> Job:
    """Hilfsfunktion: Job-Objekt für Tests erstellen."""
    ts = now_iso()
    return Job(
        id=job_id,
        canonical_id=f"test-{job_id}",
        title=title,
        first_seen_at=ts,
        last_seen_at=ts,
        raw_text=raw_text,
        created_at=ts,
        updated_at=ts,
    )


def test_empty_keywords_passes_all() -> None:
    """Leere Keyword-Liste → alles passiert."""
    f = Stage1aFilter(exclude_keywords=[])
    result = f.check(_make_job())
    assert result.passed is True
    assert result.reason is None
    assert result.stage == "1a"
    assert result.model == "deterministic"


def test_title_match_excludes() -> None:
    """Keyword im Titel → SKIP."""
    f = Stage1aFilter(exclude_keywords=["Praktikum"])
    result = f.check(_make_job(title="Praktikum Softwareentwicklung"))
    assert result.passed is False
    assert result.reason == "exclude_keyword: Praktikum"


def test_raw_text_match_excludes() -> None:
    """Keyword im raw_text → SKIP."""
    f = Stage1aFilter(exclude_keywords=["Werkstudent"])
    result = f.check(
        _make_job(
            title="Junior Developer",
            raw_text="Wir suchen einen Werkstudent (m/w/d) für unser Team.",
        )
    )
    assert result.passed is False
    assert result.reason == "exclude_keyword: Werkstudent"


def test_word_boundary_prevents_substring_match() -> None:
    """Substring ohne Word-Boundary matcht nicht."""
    # "Praktikumserfahrung" enthält "Praktikum" als Substring,
    # aber \b matcht an der Wortgrenze → MATCHT trotzdem.
    # Testen wir stattdessen einen echten Substring-Fall:
    f = Stage1aFilter(exclude_keywords=["rat"])
    result = f.check(_make_job(title="Strategieberater"))
    # "rat" hat keine Word-Boundary in "Strategieberater" → PASS
    assert result.passed is True


def test_case_insensitive() -> None:
    """Case-insensitive Matching."""
    f = Stage1aFilter(exclude_keywords=["praktikum"])
    result = f.check(_make_job(title="PRAKTIKUM Software"))
    assert result.passed is False
    f2 = Stage1aFilter(exclude_keywords=["WERKSTUDENT"])
    result2 = f2.check(_make_job(title="werkstudent (m/w/d)"))
    assert result2.passed is False


def test_umlauts_handled() -> None:
    """Deutsche Umlaute korrekt gematcht."""
    f = Stage1aFilter(exclude_keywords=["Bürokauffrau"])
    result = f.check(_make_job(title="Bürokauffrau (m/w/d)"))
    assert result.passed is False
    # Auch im raw_text
    result2 = f.check(
        _make_job(
            title="Kaufmännische Stelle",
            raw_text="Wir suchen eine Bürokauffrau für unser Team.",
        )
    )
    assert result2.passed is False


def test_none_raw_text_only_checks_title() -> None:
    """raw_text=None → nur Titel geprüft."""
    f = Stage1aFilter(exclude_keywords=["Praktikum"])
    # Keyword nicht im Titel → PASS (raw_text=None wird toleriert)
    result = f.check(_make_job(title="Python Developer", raw_text=None))
    assert result.passed is True
    # Keyword im Titel → SKIP (auch ohne raw_text)
    result2 = f.check(_make_job(title="Praktikum Python", raw_text=None))
    assert result2.passed is False


def test_multiple_keywords() -> None:
    """Mehrere Keywords, erster Treffer gewinnt."""
    f = Stage1aFilter(exclude_keywords=["Praktikum", "Werkstudent", "Minijob"])
    result = f.check(_make_job(title="Werkstudent Backend"))
    assert result.passed is False
    assert result.reason == "exclude_keyword: Werkstudent"
    # Kein Match → PASS
    result2 = f.check(_make_job(title="Senior Python Developer"))
    assert result2.passed is True


def test_title_checked_before_raw_text() -> None:
    """Titel wird vor raw_text geprüft."""
    f = Stage1aFilter(exclude_keywords=["Praktikum", "Werkstudent"])
    result = f.check(
        _make_job(
            title="Praktikum Development",
            raw_text="Werkstudent gesucht",
        )
    )
    # Titel-Match wird zuerst gefunden
    assert result.reason == "exclude_keyword: Praktikum"


def test_normalize_text_whitespace() -> None:
    """Whitespace-Normalisierung."""
    assert _normalize_text("  hello   world  ") == "hello world"
    assert _normalize_text("line1\n\nline2\ttab") == "line1 line2 tab"
