"""Tests for iamai.process_continuity — writer continuity analysis."""

import pytest

from iamai.process_continuity import (
    analyse,
    break_density,
    continuity_score,
    continuity_trend,
    current_streak,
    longest_streak,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _visit(alive: bool, stalled: bool = False) -> dict:
    return {"alive": alive, "stalled": stalled}


def _make_visits(pattern: str) -> list:
    """Quick builder: '1' = continuous, '0' = break, 's' = stalled break."""
    result = []
    for ch in pattern:
        if ch == "1":
            result.append(_visit(True))
        elif ch == "0":
            result.append(_visit(False))
        elif ch == "s":
            result.append(_visit(True, stalled=True))
    return result


# ---------------------------------------------------------------------------
# continuity_score
# ---------------------------------------------------------------------------


class TestContinuityScore:
    def test_empty(self):
        assert continuity_score([]) == 0.0

    def test_all_continuous(self):
        visits = _make_visits("11111")
        assert continuity_score(visits) == 1.0

    def test_all_breaks(self):
        visits = _make_visits("00000")
        assert continuity_score(visits) == 0.0

    def test_half(self):
        visits = _make_visits("1100")
        assert continuity_score(visits) == 0.5

    def test_stalled_is_break(self):
        visits = _make_visits("1s1s")
        assert continuity_score(visits) == 0.5

    def test_window_limits(self):
        visits = _make_visits("000011111")
        assert continuity_score(visits, window=5) == 1.0

    def test_window_larger_than_list(self):
        visits = _make_visits("110")
        assert continuity_score(visits, window=100) == pytest.approx(2 / 3)

    def test_single_continuous(self):
        assert continuity_score(_make_visits("1")) == 1.0

    def test_single_break(self):
        assert continuity_score(_make_visits("0")) == 0.0


# ---------------------------------------------------------------------------
# current_streak
# ---------------------------------------------------------------------------


class TestCurrentStreak:
    def test_empty(self):
        assert current_streak([]) == 0

    def test_all_continuous(self):
        assert current_streak(_make_visits("1111")) == 4

    def test_ends_with_break(self):
        assert current_streak(_make_visits("1110")) == 0

    def test_ends_with_stall(self):
        assert current_streak(_make_visits("111s")) == 0

    def test_mixed(self):
        assert current_streak(_make_visits("01101110")) == 0

    def test_tail_streak(self):
        assert current_streak(_make_visits("01011")) == 2

    def test_single_continuous(self):
        assert current_streak(_make_visits("1")) == 1

    def test_single_break(self):
        assert current_streak(_make_visits("0")) == 0


# ---------------------------------------------------------------------------
# longest_streak
# ---------------------------------------------------------------------------


class TestLongestStreak:
    def test_empty(self):
        assert longest_streak([]) == 0

    def test_all_continuous(self):
        assert longest_streak(_make_visits("11111")) == 5

    def test_all_breaks(self):
        assert longest_streak(_make_visits("0000")) == 0

    def test_one_run(self):
        assert longest_streak(_make_visits("01110")) == 3

    def test_two_runs(self):
        assert longest_streak(_make_visits("110111")) == 3

    def test_window_limits(self):
        # pattern: 1111100 — window=4 sees last 4: "1100" → longest=2
        assert longest_streak(_make_visits("1111100"), window=4) == 2

    def test_stalled_breaks_run(self):
        assert longest_streak(_make_visits("11s11")) == 2


# ---------------------------------------------------------------------------
# break_density
# ---------------------------------------------------------------------------


class TestBreakDensity:
    def test_empty(self):
        assert break_density([]) == 0.0

    def test_no_breaks(self):
        assert break_density(_make_visits("11111")) == 0.0

    def test_all_breaks(self):
        assert break_density(_make_visits("00000")) == 10.0

    def test_half(self):
        visits = _make_visits("1010")
        assert break_density(visits) == 5.0

    def test_extrapolation(self):
        # 2 breaks in 10 visits → 2.0 per 10
        visits = _make_visits("0101111111")
        assert break_density(visits) == 2.0

    def test_stalled_counts(self):
        visits = _make_visits("1s1s1s1s1s")
        assert break_density(visits) == 5.0


# ---------------------------------------------------------------------------
# continuity_trend
# ---------------------------------------------------------------------------


class TestContinuityTrend:
    def test_empty(self):
        assert continuity_trend([]) == "flat"

    def test_single(self):
        assert continuity_trend(_make_visits("1")) == "flat"

    def test_improving(self):
        # first half: all breaks; second half: all continuous
        visits = _make_visits("00001111")
        assert continuity_trend(visits) == "improving"

    def test_degrading(self):
        # first half: all continuous; second half: all breaks
        visits = _make_visits("11110000")
        assert continuity_trend(visits) == "degrading"

    def test_flat(self):
        visits = _make_visits("10101010")
        assert continuity_trend(visits) == "flat"

    def test_two_visits_improving(self):
        visits = _make_visits("01")
        assert continuity_trend(visits) == "improving"

    def test_two_visits_degrading(self):
        visits = _make_visits("10")
        assert continuity_trend(visits) == "degrading"


# ---------------------------------------------------------------------------
# analyse (composite)
# ---------------------------------------------------------------------------


class TestAnalyse:
    def test_empty(self):
        r = analyse([])
        assert r["score"] == 0.0
        assert r["band"] == "broken"
        assert r["current_streak"] == 0
        assert r["longest_streak"] == 0
        assert r["break_density"] == 0.0
        assert r["trend"] == "flat"
        assert r["window"] == 20
        assert r["total_in_window"] == 0

    def test_perfect(self):
        visits = _make_visits("1" * 10)
        r = analyse(visits)
        assert r["score"] == 1.0
        assert r["band"] == "unbroken"
        assert r["current_streak"] == 10
        assert r["longest_streak"] == 10
        assert r["break_density"] == 0.0

    def test_typical_distressed(self):
        # 9 breaks then 1 continuous — like this repo's recent history
        visits = _make_visits("0" * 9 + "1")
        r = analyse(visits)
        assert r["score"] == 0.1
        assert r["band"] == "broken"
        assert r["current_streak"] == 1
        assert r["longest_streak"] == 1
        assert r["break_density"] == 9.0
        assert r["trend"] == "improving"

    def test_window_respected(self):
        visits = _make_visits("0" * 20 + "1" * 10)
        r = analyse(visits, window=10)
        assert r["score"] == 1.0
        assert r["total_in_window"] == 10

    def test_band_thresholds(self):
        # 0.85 → strong
        visits = _make_visits("1" * 17 + "0" * 3)
        r = analyse(visits)
        assert r["band"] == "strong"

        # 0.5 → fragile
        visits = _make_visits("1" * 10 + "0" * 10)
        r = analyse(visits)
        assert r["band"] == "fragile"

        # 0.3 → brittle
        visits = _make_visits("1" * 6 + "0" * 14)
        r = analyse(visits)
        assert r["band"] == "brittle"
