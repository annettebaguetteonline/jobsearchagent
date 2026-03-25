"""Unit-Tests für app.location.models."""

import pytest

from app.location.models import (
    compute_location_score,
    get_work_model_weight,
)

# ---------------------------------------------------------------------------
# get_work_model_weight
# ---------------------------------------------------------------------------


class TestGetWorkModelWeight:
    def test_remote(self) -> None:
        assert get_work_model_weight("remote", None) == 0.0

    def test_hybrid_1_day(self) -> None:
        assert get_work_model_weight("hybrid", 1) == 0.2

    def test_hybrid_3_days(self) -> None:
        assert get_work_model_weight("hybrid", 3) == 0.5

    def test_hybrid_5_days(self) -> None:
        assert get_work_model_weight("hybrid", 5) == 0.8

    def test_hybrid_default_no_days(self) -> None:
        assert get_work_model_weight("hybrid", None) == 0.5

    def test_onsite(self) -> None:
        assert get_work_model_weight("onsite", None) == 1.0

    def test_none_work_model(self) -> None:
        assert get_work_model_weight(None, None) == 0.6

    def test_unknown_work_model(self) -> None:
        assert get_work_model_weight("unknown", None) == 0.6

    def test_hybrid_2_days_boundary(self) -> None:
        assert get_work_model_weight("hybrid", 2) == 0.5

    def test_hybrid_4_days_boundary(self) -> None:
        assert get_work_model_weight("hybrid", 4) == 0.8


# ---------------------------------------------------------------------------
# compute_location_score
# ---------------------------------------------------------------------------


class TestComputeLocationScore:
    def test_remote_always_1_0(self) -> None:
        result = compute_location_score(
            transit_minutes_public=30,
            transit_minutes_car=20,
            work_model="remote",
            hybrid_days=None,
        )
        assert result.score == 1.0
        assert result.effective_minutes == 0
        assert result.is_remote is True

    def test_short_onsite_commute(self) -> None:
        result = compute_location_score(
            transit_minutes_public=30,
            transit_minutes_car=20,
            work_model="onsite",
            hybrid_days=None,
        )
        assert result.effective_minutes == 20
        # score = 1.0 - (20/60)*0.3 = 1.0 - 0.1 = 0.9
        assert result.score == pytest.approx(0.9, abs=0.01)
        assert result.is_remote is False

    def test_long_onsite_commute(self) -> None:
        result = compute_location_score(
            transit_minutes_public=90,
            transit_minutes_car=70,
            work_model="onsite",
            hybrid_days=None,
        )
        assert result.effective_minutes == 70
        # effective > max_min: score = max(0, 0.7 - (70-60)/60*0.5) = max(0, 0.7 - 0.083) ≈ 0.617
        assert result.score < 0.7
        assert result.score > 0.0

    def test_hybrid_reduces_effective_minutes(self) -> None:
        result = compute_location_score(
            transit_minutes_public=60,
            transit_minutes_car=40,
            work_model="hybrid",
            hybrid_days=2,
        )
        # weight = 0.5 for hybrid_2_3, effective = 40 * 0.5 = 20
        assert result.effective_minutes == 20
        # score = 1.0 - (20/60)*0.3 = 0.9
        assert result.score == pytest.approx(0.9, abs=0.01)

    def test_no_transit_data(self) -> None:
        result = compute_location_score(
            transit_minutes_public=None,
            transit_minutes_car=None,
            work_model="onsite",
            hybrid_days=None,
        )
        assert result.score == 0.5
        assert result.effective_minutes == 0
        assert result.is_remote is False

    def test_both_transit_modes_uses_shorter(self) -> None:
        result = compute_location_score(
            transit_minutes_public=60,
            transit_minutes_car=30,
            work_model="onsite",
            hybrid_days=None,
        )
        # Should use car (30), not public (60)
        assert result.effective_minutes == 30
        # score = 1.0 - (30/60)*0.3 = 1.0 - 0.15 = 0.85
        assert result.score == pytest.approx(0.85, abs=0.01)

    def test_only_public_transit(self) -> None:
        result = compute_location_score(
            transit_minutes_public=45,
            transit_minutes_car=None,
            work_model="onsite",
            hybrid_days=None,
        )
        assert result.effective_minutes == 45
        assert result.transit_minutes_public == 45

    def test_only_car_transit(self) -> None:
        result = compute_location_score(
            transit_minutes_public=None,
            transit_minutes_car=50,
            work_model="onsite",
            hybrid_days=None,
        )
        assert result.effective_minutes == 50
        assert result.transit_minutes_car == 50

    def test_unknown_work_model_default_weight(self) -> None:
        result = compute_location_score(
            transit_minutes_public=40,
            transit_minutes_car=None,
            work_model="unknown",
            hybrid_days=None,
        )
        # weight = 0.6 for unknown, effective = 40 * 0.6 = 24
        assert result.effective_minutes == 24
        assert result.work_model_weight == 0.6

    def test_custom_max_commute_min(self) -> None:
        result = compute_location_score(
            transit_minutes_public=50,
            transit_minutes_car=None,
            work_model="onsite",
            hybrid_days=None,
            max_commute_min=30,
        )
        # effective = 50 > 30, score = max(0, 0.7 - (50-30)/60*0.5)
        # = max(0, 0.7 - 0.167) ≈ 0.533
        assert result.score == pytest.approx(0.533, abs=0.01)

    def test_score_never_below_zero(self) -> None:
        result = compute_location_score(
            transit_minutes_public=300,
            transit_minutes_car=None,
            work_model="onsite",
            hybrid_days=None,
            max_commute_min=60,
        )
        # effective = 300, score = max(0, 0.7 - (300-60)/60*0.5) = max(0, -3.3) = 0
        assert result.score == 0.0

    def test_hybrid_1_day_weight(self) -> None:
        result = compute_location_score(
            transit_minutes_public=40,
            transit_minutes_car=None,
            work_model="hybrid",
            hybrid_days=1,
        )
        # weight = 0.2, effective = 40 * 0.2 = 8
        assert result.effective_minutes == 8
        assert result.work_model_weight == 0.2

    def test_transit_minutes_stored_in_result(self) -> None:
        result = compute_location_score(
            transit_minutes_public=45,
            transit_minutes_car=35,
            work_model="onsite",
            hybrid_days=None,
        )
        assert result.transit_minutes_public == 45
        assert result.transit_minutes_car == 35

    def test_work_model_stored_in_result(self) -> None:
        result = compute_location_score(
            transit_minutes_public=30,
            transit_minutes_car=None,
            work_model="hybrid",
            hybrid_days=2,
        )
        assert result.work_model == "hybrid"
        assert result.hybrid_days == 2
