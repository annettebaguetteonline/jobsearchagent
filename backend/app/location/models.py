"""Pydantic-Modelle und Scoring-Logik für die Location-Pipeline."""

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Datenmodelle
# ---------------------------------------------------------------------------


class GeocodingResult(BaseModel):
    """Ergebnis einer Geocoding-Abfrage."""

    lat: float
    lng: float
    display_name: str
    source: str  # 'nominatim' | 'db_lookup'


class TransitResult(BaseModel):
    """Ergebnis einer Transit-API-Abfrage."""

    origin_hash: str
    company_id: int
    transit_minutes: int
    mode: str  # 'public_transit' | 'car'
    api_used: str  # 'db_rest' | 'transport_rest' | 'osrm'
    cached: bool = False


class LocationScore(BaseModel):
    """Berechneter Location-Score für eine Stelle."""

    score: float  # 0.0 - 1.0
    effective_minutes: int  # transit_minutes * work_model_weight
    transit_minutes_public: int | None = None
    transit_minutes_car: int | None = None
    work_model: str  # 'remote' | 'hybrid' | 'onsite' | 'unknown'
    work_model_weight: float
    hybrid_days: int | None = None
    is_remote: bool


class CompanyAddress(BaseModel):
    """Aufgelöste Firmenadresse."""

    street: str | None = None
    city: str | None = None
    zip_code: str | None = None
    lat: float | None = None
    lng: float | None = None
    source: str  # 'db' | 'impressum' | 'searxng' | 'nominatim'
    status: str  # 'found' | 'failed'


# ---------------------------------------------------------------------------
# Scoring-Konstanten und Funktionen
# ---------------------------------------------------------------------------

WORK_MODEL_WEIGHTS: dict[str, float] = {
    "remote": 0.0,
    "hybrid_1": 0.2,
    "hybrid_2_3": 0.5,
    "hybrid_4_5": 0.8,
    "onsite": 1.0,
    "unknown": 0.6,
}


def get_work_model_weight(work_model: str | None, hybrid_days: int | None = None) -> float:
    """Bestimme das Gewicht basierend auf Work-Model und Hybrid-Tagen."""
    if work_model == "remote":
        return WORK_MODEL_WEIGHTS["remote"]
    if work_model == "hybrid" and hybrid_days is not None:
        if hybrid_days <= 1:
            return WORK_MODEL_WEIGHTS["hybrid_1"]
        if hybrid_days <= 3:
            return WORK_MODEL_WEIGHTS["hybrid_2_3"]
        return WORK_MODEL_WEIGHTS["hybrid_4_5"]
    if work_model == "hybrid":
        return WORK_MODEL_WEIGHTS["hybrid_2_3"]  # Default Hybrid
    if work_model == "onsite":
        return WORK_MODEL_WEIGHTS["onsite"]
    return WORK_MODEL_WEIGHTS["unknown"]


def compute_location_score(
    transit_minutes_public: int | None,
    transit_minutes_car: int | None,
    work_model: str | None,
    hybrid_days: int | None = None,
    max_commute_min: int = 60,
) -> LocationScore:
    """Berechne den Location-Score.

    Formel aus dem Design-Dokument:
    effective = transit_min * weight
    score = 1.0 - (effective / max_min) * 0.3     wenn effective <= max_min
    score = max(0.0, 0.7 - (effective - max_min) / 60 * 0.5)  sonst
    """
    weight = get_work_model_weight(work_model, hybrid_days)
    is_remote = weight == 0.0

    if is_remote:
        return LocationScore(
            score=1.0,
            effective_minutes=0,
            transit_minutes_public=transit_minutes_public,
            transit_minutes_car=transit_minutes_car,
            work_model=work_model or "unknown",
            work_model_weight=weight,
            hybrid_days=hybrid_days,
            is_remote=True,
        )

    # Nutze den kürzeren der beiden Wege
    transit_min = (
        min(t for t in [transit_minutes_public, transit_minutes_car] if t is not None)
        if any(t is not None for t in [transit_minutes_public, transit_minutes_car])
        else None
    )

    if transit_min is None:
        # Keine Transitdaten → konservativer Score
        return LocationScore(
            score=0.5,
            effective_minutes=0,
            transit_minutes_public=transit_minutes_public,
            transit_minutes_car=transit_minutes_car,
            work_model=work_model or "unknown",
            work_model_weight=weight,
            hybrid_days=hybrid_days,
            is_remote=False,
        )

    effective = int(transit_min * weight)

    if effective <= max_commute_min:
        score = 1.0 - (effective / max_commute_min) * 0.3
    else:
        score = max(0.0, 0.7 - (effective - max_commute_min) / 60 * 0.5)

    return LocationScore(
        score=round(score, 3),
        effective_minutes=effective,
        transit_minutes_public=transit_minutes_public,
        transit_minutes_car=transit_minutes_car,
        work_model=work_model or "unknown",
        work_model_weight=weight,
        hybrid_days=hybrid_days,
        is_remote=False,
    )
