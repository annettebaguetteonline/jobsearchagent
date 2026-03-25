"""Unit-Tests für app.location.parser."""

from app.location.parser import (
    ParsedLocation,
    detect_work_model_from_text,
    extract_hybrid_days,
    parse_location_raw,
)

# ---------------------------------------------------------------------------
# parse_location_raw
# ---------------------------------------------------------------------------


class TestParseLocationRaw:
    def test_plz_city(self) -> None:
        result = parse_location_raw("34117 Kassel")
        assert result.pattern_type == "plz_city"
        assert result.postal_code == "34117"
        assert result.city == "Kassel"
        assert result.is_remote is False

    def test_plz_city_multiword(self) -> None:
        result = parse_location_raw("60311 Frankfurt am Main")
        assert result.pattern_type == "plz_city"
        assert result.postal_code == "60311"
        assert result.city == "Frankfurt am Main"

    def test_city_only(self) -> None:
        result = parse_location_raw("Frankfurt am Main")
        assert result.pattern_type == "city_only"
        assert result.city == "Frankfurt am Main"
        assert result.postal_code is None

    def test_remote_keyword(self) -> None:
        result = parse_location_raw("Remote")
        assert result.pattern_type == "remote"
        assert result.is_remote is True

    def test_homeoffice(self) -> None:
        result = parse_location_raw("Homeoffice")
        assert result.pattern_type == "remote"
        assert result.is_remote is True

    def test_deutschlandweit(self) -> None:
        result = parse_location_raw("deutschlandweit")
        assert result.pattern_type == "remote"
        assert result.is_remote is True

    def test_bundesweit(self) -> None:
        result = parse_location_raw("bundesweit")
        assert result.pattern_type == "remote"
        assert result.is_remote is True

    def test_region_bundesland(self) -> None:
        result = parse_location_raw("Hessen")
        assert result.pattern_type == "region"
        assert result.region == "Hessen"
        assert result.city is None

    def test_region_case_insensitive(self) -> None:
        result = parse_location_raw("bayern")
        assert result.pattern_type == "region"
        assert result.region == "Bayern"

    def test_plz_city_with_region_comma(self) -> None:
        result = parse_location_raw("60311 Frankfurt am Main, Hessen")
        assert result.pattern_type == "plz_city"
        assert result.postal_code == "60311"
        assert result.city == "Frankfurt am Main"
        assert result.region == "Hessen"

    def test_city_with_region_comma(self) -> None:
        result = parse_location_raw("Frankfurt am Main, Hessen")
        assert result.pattern_type == "city_only"
        assert result.city == "Frankfurt am Main"
        assert result.region == "Hessen"

    def test_empty_string(self) -> None:
        result = parse_location_raw("")
        assert result.pattern_type == "unparseable"
        assert result.raw == ""

    def test_none_input(self) -> None:
        result = parse_location_raw(None)
        assert result.pattern_type == "unparseable"
        assert result.raw == ""

    def test_whitespace_only(self) -> None:
        result = parse_location_raw("   ")
        assert result.pattern_type == "unparseable"

    def test_home_office_with_space(self) -> None:
        result = parse_location_raw("Home Office")
        assert result.pattern_type == "remote"
        assert result.is_remote is True

    def test_all_bundeslaender_recognized(self) -> None:
        bundeslaender = [
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
        for bl in bundeslaender:
            result = parse_location_raw(bl)
            assert result.pattern_type == "region", f"{bl} should be region"
            assert result.region == bl

    def test_unparseable_has_digits(self) -> None:
        result = parse_location_raw("Raum 123 irgendwo")
        assert result.pattern_type == "unparseable"

    def test_preserves_raw(self) -> None:
        raw = "34117 Kassel"
        result = parse_location_raw(raw)
        assert result.raw == raw

    def test_returns_pydantic_model(self) -> None:
        result = parse_location_raw("München")
        assert isinstance(result, ParsedLocation)


# ---------------------------------------------------------------------------
# detect_work_model_from_text
# ---------------------------------------------------------------------------


class TestDetectWorkModelFromText:
    def test_remote(self) -> None:
        assert detect_work_model_from_text("Arbeiten Sie 100% remote von überall") == "remote"

    def test_hybrid_overrides_remote(self) -> None:
        # "teilweise remote" → hybrid, nicht remote
        assert detect_work_model_from_text("teilweise remote möglich") == "hybrid"

    def test_hybrid_days(self) -> None:
        result = detect_work_model_from_text("2-3 Tage pro Woche im Büro, Rest Homeoffice")
        assert result == "hybrid"

    def test_onsite(self) -> None:
        assert detect_work_model_from_text("Präsenz am Standort erforderlich") == "onsite"

    def test_no_match(self) -> None:
        assert detect_work_model_from_text("Wir bieten eine spannende Position") is None

    def test_none_input(self) -> None:
        assert detect_work_model_from_text(None) is None

    def test_empty_string(self) -> None:
        assert detect_work_model_from_text("") is None

    def test_homeoffice_is_remote(self) -> None:
        assert detect_work_model_from_text("Vollständige Homeoffice-Stelle") == "remote"

    def test_teilweise_homeoffice_is_hybrid(self) -> None:
        assert detect_work_model_from_text("teilweise homeoffice möglich") == "hybrid"

    def test_vor_ort_is_onsite(self) -> None:
        assert detect_work_model_from_text("Arbeit vor Ort in Berlin") == "onsite"

    def test_in_unserem_buero_is_onsite(self) -> None:
        assert detect_work_model_from_text("Arbeit in unserem Büro in Hamburg") == "onsite"

    def test_case_insensitive(self) -> None:
        assert detect_work_model_from_text("REMOTE ARBEIT") == "remote"
        assert detect_work_model_from_text("HYBRID Modell") == "hybrid"


# ---------------------------------------------------------------------------
# extract_hybrid_days
# ---------------------------------------------------------------------------


class TestExtractHybridDays:
    def test_range_pro_woche(self) -> None:
        result = extract_hybrid_days("2-3 Tage pro Woche vor Ort")
        assert result == 2  # (2+3)//2

    def test_range_wochentlich(self) -> None:
        result = extract_hybrid_days("3-4 Tage wöchentlich im Büro")
        assert result == 3  # (3+4)//2

    def test_single_tage(self) -> None:
        result = extract_hybrid_days("2 Tage pro Woche Homeoffice erlaubt")
        assert result == 2

    def test_single_im_buero(self) -> None:
        result = extract_hybrid_days("3 Tage im Büro erwartet")
        assert result == 3

    def test_x_woche(self) -> None:
        result = extract_hybrid_days("2x/Woche im Büro")
        assert result == 2

    def test_no_match(self) -> None:
        assert extract_hybrid_days("Kein Hybrid-Hinweis in diesem Text") is None

    def test_none_input(self) -> None:
        assert extract_hybrid_days(None) is None

    def test_empty_string(self) -> None:
        assert extract_hybrid_days("") is None

    def test_em_dash_range(self) -> None:
        # En-Dash statt Bindestrich
        result = extract_hybrid_days("2–3 Tage pro Woche")
        assert result == 2
