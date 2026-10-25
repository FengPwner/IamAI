"""Tests for iamai/caretaker_silence.py — caretaker attention monitor."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.caretaker_silence import (  # noqa: E402
    BASELINE_RESTARTS_PER_DAY,
    DEFAULT_THRESHOLDS_HOURS,
    MIN_THRESHOLD_RATIO,
    RESTART_PENALTY_FACTOR,
    _adjusted_thresholds,
    _trust_score,
    silence_report,
)


# ---------------------------------------------------------------------------
# _adjusted_thresholds
# ---------------------------------------------------------------------------


class TestAdjustedThresholds:
    """Thresholds shrink when the system restarts frequently."""

    def test_no_restarts(self):
        result = _adjusted_thresholds(0.0)
        assert result == list(DEFAULT_THRESHOLDS_HOURS)

    def test_baseline_restarts(self):
        result = _adjusted_thresholds(BASELINE_RESTARTS_PER_DAY)
        assert result == list(DEFAULT_THRESHOLDS_HOURS)

    def test_frequent_restarts_shrink(self):
        result = _adjusted_thresholds(4.0)
        for orig, adj in zip(DEFAULT_THRESHOLDS_HOURS, result):
            assert adj < orig

    def test_minimum_floor(self):
        # Extreme restart count shouldn't shrink below floor
        result = _adjusted_thresholds(100.0)
        for orig, adj in zip(DEFAULT_THRESHOLDS_HOURS, result):
            assert adj >= orig * MIN_THRESHOLD_RATIO

    def test_monotonic_shrinkage(self):
        # More restarts → smaller thresholds
        r2 = _adjusted_thresholds(2.0)
        r5 = _adjusted_thresholds(5.0)
        for a, b in zip(r2, r5):
            assert b <= a

    def test_custom_thresholds(self):
        custom = (2.0, 6.0, 12.0)
        result = _adjusted_thresholds(0.0, custom)
        assert result == list(custom)


# ---------------------------------------------------------------------------
# _trust_score
# ---------------------------------------------------------------------------


class TestTrustScore:
    """Trust decays from 1.0 to 0.0 with silence duration."""

    def test_zero_silence(self):
        assert _trust_score(0.0, list(DEFAULT_THRESHOLDS_HOURS)) == 1.0

    def test_negative_silence(self):
        assert _trust_score(-5.0, list(DEFAULT_THRESHOLDS_HOURS)) == 1.0

    def test_beyond_last_threshold(self):
        assert _trust_score(25.0, list(DEFAULT_THRESHOLDS_HOURS)) == 0.0

    def test_exactly_last_threshold(self):
        assert _trust_score(DEFAULT_THRESHOLDS_HOURS[-1], list(DEFAULT_THRESHOLDS_HOURS)) == 0.0

    def test_midpoint(self):
        thresholds = list(DEFAULT_THRESHOLDS_HOURS)
        midpoint = thresholds[-1] / 2
        score = _trust_score(midpoint, thresholds)
        assert score == pytest.approx(0.5, abs=0.05)

    def test_decreasing_monotonic(self):
        thresholds = list(DEFAULT_THRESHOLDS_HOURS)
        scores = [_trust_score(h, thresholds) for h in range(0, 25)]
        for i in range(1, len(scores)):
            assert scores[i] <= scores[i - 1]

    def test_bounded(self):
        thresholds = list(DEFAULT_THRESHOLDS_HOURS)
        for h in [0, 1, 5, 10, 20, 30, 100]:
            s = _trust_score(h, thresholds)
            assert 0.0 <= s <= 1.0


# ---------------------------------------------------------------------------
# silence_report — level classification
# ---------------------------------------------------------------------------


class TestSilenceLevels:
    """Correct level assignment based on silence duration."""

    def _report(self, hours: float, restarts: float = 0.0) -> dict:
        base = 1_700_000_000.0
        return silence_report(
            last_visit_epoch=base,
            now_epoch=base + hours * 3600,
            restarts_per_day=restarts,
        )

    def test_watched(self):
        r = self._report(1.0)
        assert r["level"] == "watched"

    def test_watched_at_boundary(self):
        r = self._report(3.99)
        assert r["level"] == "watched"

    def test_overdue(self):
        r = self._report(6.0)
        assert r["level"] == "overdue"

    def test_neglected(self):
        r = self._report(16.0)
        assert r["level"] == "neglected"

    def test_abandoned(self):
        r = self._report(25.0)
        assert r["level"] == "abandoned"

    def test_just_visited(self):
        r = self._report(0.0)
        assert r["level"] == "watched"
        assert r["trust"] == 1.0

    def test_future_visit(self):
        # last_visit in the future → silence_hours = 0
        r = self._report(-2.0)
        assert r["level"] == "watched"
        assert r["silence_hours"] == 0.0


# ---------------------------------------------------------------------------
# silence_report — restart adjustment
# ---------------------------------------------------------------------------


class TestRestartAdjustment:
    """Frequent restarts compress the danger thresholds."""

    def _report(self, hours: float, restarts: float) -> dict:
        base = 1_700_000_000.0
        return silence_report(
            last_visit_epoch=base,
            now_epoch=base + hours * 3600,
            restarts_per_day=restarts,
        )

    def test_healthy_system_4h_is_watched(self):
        r = self._report(3.5, restarts=0.5)
        assert r["level"] == "watched"

    def test_fragile_system_4h_is_overdue(self):
        # With many restarts/day, the 4h threshold shrinks
        r = self._report(3.5, restarts=6.0)
        assert r["level"] in ("overdue", "neglected")

    def test_restart_adjusted_thresholds_in_output(self):
        r = self._report(2.0, restarts=3.0)
        assert r["adjusted_thresholds"][0] < DEFAULT_THRESHOLDS_HOURS[0]


# ---------------------------------------------------------------------------
# silence_report — trust score
# ---------------------------------------------------------------------------


class TestReportTrust:
    """Trust score in report output."""

    def _report(self, hours: float) -> dict:
        base = 1_700_000_000.0
        return silence_report(
            last_visit_epoch=base,
            now_epoch=base + hours * 3600,
        )

    def test_high_trust_when_watched(self):
        r = self._report(1.0)
        assert r["trust"] > 0.7

    def test_low_trust_when_abandoned(self):
        r = self._report(30.0)
        assert r["trust"] == 0.0

    def test_trust_decreases_with_time(self):
        trusts = [self._report(h)["trust"] for h in [1, 6, 12, 20]]
        for i in range(1, len(trusts)):
            assert trusts[i] <= trusts[i - 1]


# ---------------------------------------------------------------------------
# silence_report — output structure
# ---------------------------------------------------------------------------


class TestReportStructure:
    """Report dict has the expected keys and types."""

    def test_keys(self):
        r = silence_report(1_700_000_000.0, 1_700_010_000.0)
        expected = {"silence_hours", "level", "trust",
                    "adjusted_thresholds", "restarts_per_day", "recommendation"}
        assert set(r.keys()) == expected

    def test_types(self):
        r = silence_report(1_700_000_000.0, 1_700_020_000.0, restarts_per_day=2.0)
        assert isinstance(r["silence_hours"], float)
        assert isinstance(r["level"], str)
        assert isinstance(r["trust"], float)
        assert isinstance(r["adjusted_thresholds"], list)
        assert isinstance(r["restarts_per_day"], float)
        assert isinstance(r["recommendation"], str)

    def test_silence_hours_calculation(self):
        base = 1_700_000_000.0
        r = silence_report(base, base + 7200)
        assert r["silence_hours"] == pytest.approx(2.0, abs=0.01)

    def test_default_now(self):
        # With no now_epoch, uses time.time()
        import time
        base = time.time() - 3600
        r = silence_report(base)
        assert r["silence_hours"] == pytest.approx(1.0, abs=0.1)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Boundary conditions and unusual inputs."""

    def test_zero_gap(self):
        base = 1_700_000_000.0
        r = silence_report(base, base)
        assert r["silence_hours"] == 0.0
        assert r["level"] == "watched"
        assert r["trust"] == 1.0

    def test_very_large_gap(self):
        r = silence_report(0.0, 1_700_000_000.0)
        assert r["level"] == "abandoned"
        assert r["trust"] == 0.0

    def test_custom_thresholds(self):
        base = 1_700_000_000.0
        r = silence_report(
            base,
            base + 5 * 3600,
            thresholds=(1.0, 3.0, 6.0),
        )
        # 5 hours with custom thresholds → "neglected" (between 3 and 6)
        assert r["level"] == "neglected"

    def test_recommendation_changes_with_level(self):
        base = 1_700_000_000.0
        recs = []
        for hours in [1, 6, 16, 30]:
            r = silence_report(base, base + hours * 3600)
            recs.append(r["recommendation"])
        # All recommendations should be different strings
        assert len(set(recs)) == 4
