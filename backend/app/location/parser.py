"""Location Parser Utility.

Klassifiziert und parst `location_raw`-Strings aus den Scrapern.
Wird im Data Quality Report (Task 1.1) und in der Location Pipeline (Task 2.6) verwendet.
"""

import re

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------

_BUNDESLAENDER: list[str] = [
    "Baden-Württemberg",
    "Bayern",
    "Berlin",
    "Brandenburg",
    "Bremen",
    "Hamburg",
    "Hessen",
    "Mecklenburg-Vorpommern",
    "Niedersachsen",
    "Nordrhein-Westfalen",
    "Rheinland-Pfalz",
    "Saarland",
    "Sachsen",
    "Sachsen-Anhalt",
    "Schleswig-Holstein",
    "Thüringen",
]

_BUNDESLAENDER_LOWER: set[str] = {b.lower() for b in _BUNDESLAENDER}
_BUNDESLAENDER_MAP: dict[str, str] = {b.lower(): b for b in _BUNDESLAENDER}

_REMOTE_KEYWORDS: list[str] = [
    "100% remote",
    "vollständig remote",
    "deutschlandweit",
    "bundesweit",
    "homeoffice",
    "home office",
    "remote",
]

_HYBRID_KEYWORDS: list[str] = [
    "tage vor ort",
    "tage im büro",
    "2-3 tage",
    "teilweise homeoffice",
    "teilweise remote",
    "flexible arbeitsort",
    "hybrid",
]

_ONSITE_KEYWORDS: list[str] = [
    "in unserem büro",
    "am standort",
    "on-site",
    "präsenz",
    "vor ort",
]

_RE_PLZ_CITY = re.compile(r"^(\d{5})\s+(.+)$")
_RE_HYBRID_RANGE = re.compile(
    r"(\d)\s*[-–]\s*(\d)\s*Tage?\s*(pro\s+Woche|/\s*Woche|wöchentlich)",
    re.IGNORECASE,
)
_RE_HYBRID_SINGLE = re.compile(
    r"(\d)\s*Tage?\s*(pro\s+Woche|/\s*Woche|im\s+Büro)",
    re.IGNORECASE,
)
_RE_HYBRID_XWOCHE = re.compile(r"(\d)x\s*/?s*Woche", re.IGNORECASE)


class ParsedLocation(BaseModel):
    """Ergebnis des Parsens eines location_raw-Strings."""

    raw: str
    city: str | None = None
    postal_code: str | None = None
    region: str | None = None
    pattern_type: str  # 'plz_city' | 'city_only' | 'remote' | 'region' | 'unparseable'
    is_remote: bool = False


# ---------------------------------------------------------------------------
# Haupt-Parser
# ---------------------------------------------------------------------------


def parse_location_raw(raw: str | None) -> ParsedLocation:
    """Klassifiziere und parse einen location_raw-String.

    Reihenfolge der Prüfungen:
    1. None / leerer String → unparseable
    2. Remote-Keywords
    3. PLZ + Stadt-Muster
    4. Komma-getrennte Angaben
    5. Bundesland-Namen
    6. Einfacher Stadtname
    7. Fallback → unparseable
    """
    if not raw or not raw.strip():
        return ParsedLocation(raw="", pattern_type="unparseable")

    raw_stripped = raw.strip()
    lower = raw_stripped.lower()

    # 2. Remote-Keywords
    for keyword in _REMOTE_KEYWORDS:
        if keyword in lower:
            return ParsedLocation(raw=raw_stripped, pattern_type="remote", is_remote=True)

    # 3. PLZ + Stadt (optional mit Komma + Region: "60311 Frankfurt am Main, Hessen")
    match = _RE_PLZ_CITY.match(raw_stripped)
    if match:
        remainder = match.group(2).strip()
        city_part = remainder
        region_part: str | None = None
        if "," in remainder:
            city_candidate, region_candidate = remainder.split(",", 1)
            region_candidate = region_candidate.strip()
            if region_candidate.lower() in _BUNDESLAENDER_LOWER:
                city_part = city_candidate.strip()
                region_part = _BUNDESLAENDER_MAP[region_candidate.lower()]
        return ParsedLocation(
            raw=raw_stripped,
            postal_code=match.group(1),
            city=city_part,
            region=region_part,
            pattern_type="plz_city",
        )

    # 4. Komma-getrennt (z.B. "Frankfurt am Main, Hessen")
    if "," in raw_stripped:
        parts = raw_stripped.split(",", 1)
        left = parts[0].strip()
        right = parts[1].strip() if len(parts) > 1 else ""

        # PLZ in linkem Teil?
        plz_match = _RE_PLZ_CITY.match(left)
        if plz_match:
            region = right if right.lower() in _BUNDESLAENDER_LOWER else None
            return ParsedLocation(
                raw=raw_stripped,
                postal_code=plz_match.group(1),
                city=plz_match.group(2).strip(),
                region=region or (right if right else None),
                pattern_type="plz_city",
            )

        region = _BUNDESLAENDER_MAP.get(right.lower())
        return ParsedLocation(
            raw=raw_stripped,
            city=left,
            region=region or (right if right else None),
            pattern_type="city_only",
        )

    # 5. Bundesland-Name
    if lower in _BUNDESLAENDER_LOWER:
        return ParsedLocation(
            raw=raw_stripped,
            region=_BUNDESLAENDER_MAP[lower],
            pattern_type="region",
        )

    # 6. Einfacher Stadtname (keine Ziffern, kein Komma)
    if not any(c.isdigit() for c in raw_stripped):
        return ParsedLocation(raw=raw_stripped, city=raw_stripped.strip(), pattern_type="city_only")

    # 7. Fallback
    return ParsedLocation(raw=raw_stripped, pattern_type="unparseable")


# ---------------------------------------------------------------------------
# Work-Model-Erkennung
# ---------------------------------------------------------------------------


def detect_work_model_from_text(text: str | None) -> str | None:
    """Erkennt das Arbeitsmodell aus einem Volltext (raw_text).

    Reihenfolge: Hybrid zuerst (verhindert False-positive "remote" in "teilweise remote").
    """
    if not text:
        return None

    lower = text.lower()

    # Hybrid zuerst prüfen
    for keyword in _HYBRID_KEYWORDS:
        if keyword in lower:
            return "hybrid"

    for keyword in _REMOTE_KEYWORDS:
        if keyword in lower:
            return "remote"

    for keyword in _ONSITE_KEYWORDS:
        if keyword in lower:
            return "onsite"

    return None


# ---------------------------------------------------------------------------
# Hybrid-Tage-Extraktion
# ---------------------------------------------------------------------------


def extract_hybrid_days(text: str | None) -> int | None:
    """Extrahiert die Anzahl an Büro-Tagen pro Woche aus einem Text.

    Patterns (in Reihenfolge):
    1. "2-3 Tage pro Woche" → Durchschnitt (abgerundet)
    2. "2 Tage pro Woche / im Büro" → die Zahl
    3. "2x/Woche" → die Zahl
    """
    if not text:
        return None

    m = _RE_HYBRID_RANGE.search(text)
    if m:
        low = int(m.group(1))
        high = int(m.group(2))
        return (low + high) // 2

    m = _RE_HYBRID_SINGLE.search(text)
    if m:
        return int(m.group(1))

    m = _RE_HYBRID_XWOCHE.search(text)
    if m:
        return int(m.group(1))

    return None
