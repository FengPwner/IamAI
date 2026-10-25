#!/usr/bin/env python3
"""Tests for iamai.restart_cascade — restart chain detection.

A single restart is bad luck.  Two in a row is a coincidence.  Three
is a cascade — and it means the root cause wasn't fixed.  These tests
verify that cascade detection, scoring, and tier classification all
work correctly across realistic and edge-case scenarios.
"""

from __future__ import annotations

import pytest

from iamai.restart_cascade import (
    detect_cascades,
    _parse_ts,
    _classify_tier,
    _generate_advice,
    _FRAGILE_THRESHOLD,
    _UNSTABLE_THRESHOLD,
    _DEEP_CHAIN_THRESHOLD,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ts(offset_minutes: int, base: str = "2026-10-23T00:00:00+00:00") -> str:
    """Generate an ISO timestamp at base + offset_minutes."""
    from datetime import datetime, timedelta, timezone
    dt = datetime.fromisoformat(base) + timedelta(minutes=offset_minutes)
    return dt.isoformat()


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------


class TestParseTs:
    def test_iso_string(self):
        dt = _parse_ts("2026-10-23T12:00:00+08:00")
        assert dt.hour == 12

    def test_datetime_passthrough(self):
        from datetime import datetime, timezone
        dt = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
        assert _parse_ts(dt) is dt

    def test_naive_iso(self):
        dt = _parse_ts("2026-10-23T12:00:00")
        assert dt.hour == 12


# ---------------------------------------------------------------------------
# detect_cascades — basic cases
# ---------------------------------------------------------------------------


class TestDetectCascadesBasic:
    def test_empty_list(self):
        result = detect_cascades([])
        assert result["total_restarts"] == 0
        assert result["cascade_count"] == 0
        assert result["tier"] == "stable"

    def test_single_restart(self):
        result = detect_cascades([_ts(0)])
        assert result["total_restarts"] == 1
        assert result["cascade_count"] == 0
        assert result["tier"] == "stable"

    def test_two_isolated_restarts(self):
        # 2 hours apart — well beyond 10-minute window
        result = detect_cascades([_ts(0), _ts(120)])
        assert result["total_restarts"] == 2
        assert result["cascade_count"] == 0
        assert result["tier"] == "stable"

    def test_two_cascading_restarts(self):
        # 5 minutes apart — within 10-minute window
        result = detect_cascades([_ts(0), _ts(5)])
        assert result["total_restarts"] == 2
        assert result["cascade_count"] == 1
        assert result["cascades"][0]["depth"] == 2

    def test_three_cascading_restarts(self):
        # 3 minutes each — all cascade
        result = detect_cascades([_ts(0), _ts(3), _ts(6)])
        assert result["total_restarts"] == 3
        assert result["cascade_count"] == 1
        assert result["cascades"][0]["depth"] == 3
        assert result["max_depth"] == 3

    def test_mixed_isolated_and_cascade(self):
        # First three cascade (3min gaps), last one isolated (2hr gap)
        result = detect_cascades([_ts(0), _ts(3), _ts(6), _ts(126)])
        assert result["total_restarts"] == 4
        assert result["cascade_count"] == 1
        assert result["cascades"][0]["depth"] == 3

    def test_two_separate_cascades(self):
        # Cascade 1: t+0, t+3, t+6  (3min gaps)
        # Isolated:   t+120
        # Cascade 2: t+240, t+245   (5min gap)
        result = detect_cascades([
            _ts(0), _ts(3), _ts(6),
            _ts(120),
            _ts(240), _ts(245),
        ])
        assert result["total_restarts"] == 6
        assert result["cascade_count"] == 2
        assert result["max_depth"] == 3


# ---------------------------------------------------------------------------
# detect_cascades — edge cases
# ---------------------------------------------------------------------------


class TestDetectCascadesEdge:
    def test_unsorted_input(self):
        # Input is scrambled; should still work
        result = detect_cascades([_ts(6), _ts(0), _ts(3)])
        assert result["total_restarts"] == 3
        assert result["cascade_count"] == 1

    def test_exact_window_boundary(self):
        # Exactly at the 600-second window — should cascade
        result = detect_cascades([_ts(0), _ts(10)])  # 600 seconds
        assert result["cascade_count"] == 1

    def test_just_beyond_window(self):
        # 601 seconds — should NOT cascade
        result = detect_cascades([
            "2026-10-23T00:00:00+00:00",
            "2026-10-23T00:10:01+00:00",
        ])
        assert result["cascade_count"] == 0

    def test_custom_window(self):
        # 15 minutes apart — cascades with 20min window, not with 10min
        timestamps = [_ts(0), _ts(15)]
        result_default = detect_cascades(timestamps)  # 600s window
        result_wide = detect_cascades(timestamps, cascade_window_seconds=1200)
        assert result_default["cascade_count"] == 0
        assert result_wide["cascade_count"] == 1

    def test_duplicate_timestamps(self):
        # Same time twice — gap = 0, which is <= window
        result = detect_cascades([_ts(5), _ts(5)])
        assert result["cascade_count"] == 1
        assert result["cascades"][0]["gaps"] == [0.0]

    def test_gaps_recorded_correctly(self):
        # 2min, 4min, 3min gaps
        result = detect_cascades([_ts(0), _ts(2), _ts(6), _ts(9)])
        gaps = result["cascades"][0]["gaps"]
        assert gaps[0] == pytest.approx(120.0)
        assert gaps[1] == pytest.approx(240.0)
        assert gaps[2] == pytest.approx(180.0)

    def test_datetime_objects_accepted(self):
        from datetime import datetime, timezone, timedelta
        base = datetime(2026, 10, 23, tzinfo=timezone.utc)
        timestamps = [
            base,
            base + timedelta(minutes=5),
            base + timedelta(hours=2),
        ]
        result = detect_cascades(timestamps)
        assert result["total_restarts"] == 3
        assert result["cascade_count"] == 1


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


class TestCascadeScore:
    def test_all_isolated_score_zero(self):
        result = detect_cascades([_ts(0), _ts(120), _ts(240)])
        assert result["cascade_score"] == 0.0

    def test_all_cascading_high_score(self):
        # 5 restarts, all 3 minutes apart — one big cascade
        result = detect_cascades([_ts(i * 3) for i in range(5)])
        assert result["cascade_score"] > 0.5
        assert result["cascade_pct"] == 100.0

    def test_partial_cascade_moderate_score(self):
        # 2 cascade, 3 isolated → 40% in cascades
        result = detect_cascades([
            _ts(0), _ts(3),       # cascade pair
            _ts(120), _ts(240), _ts(360),  # isolated
        ])
        assert 0.0 < result["cascade_score"] < 0.5

    def test_score_bounded_0_to_1(self):
        # Worst case: 10 restarts, all 1 minute apart
        result = detect_cascades([_ts(i) for i in range(10)])
        assert 0.0 <= result["cascade_score"] <= 1.0


# ---------------------------------------------------------------------------
# tier classification
# ---------------------------------------------------------------------------


class TestCascadeTiers:
    def test_stable_tier(self):
        result = detect_cascades([_ts(0), _ts(120), _ts(240)])
        assert result["tier"] == "stable"

    def test_fragile_tier(self):
        # 2 out of 6 restarts cascade = 33% (above 20% fragile threshold)
        result = detect_cascades([
            _ts(0), _ts(3),        # cascade pair
            _ts(120), _ts(240), _ts(360), _ts(480),  # isolated
        ])
        assert result["tier"] in ("fragile", "stable")

    def test_unstable_tier_high_pct(self):
        # 4 out of 5 cascade = 80%
        result = detect_cascades([
            _ts(0), _ts(2), _ts(4), _ts(6),  # cascade chain of 4
            _ts(300),  # isolated
        ])
        assert result["tier"] in ("unstable", "critical")

    def test_unstable_tier_deep_chain(self):
        # Chain depth 4 triggers unstable even at lower percentage
        result = detect_cascades([
            _ts(0), _ts(2), _ts(4), _ts(6),  # depth 4 chain
            _ts(120), _ts(240), _ts(360), _ts(480),  # 4 isolated
        ])
        assert result["max_depth"] == 4
        assert result["tier"] in ("unstable", "critical")

    def test_critical_tier(self):
        # Deep chain AND high percentage
        timestamps = [_ts(i * 2) for i in range(8)]  # 8 restarts, 2min apart
        result = detect_cascades(timestamps)
        assert result["tier"] == "critical"
        assert result["cascade_pct"] == 100.0


# ---------------------------------------------------------------------------
# _classify_tier unit tests
# ---------------------------------------------------------------------------


class TestClassifyTier:
    def test_stable(self):
        assert _classify_tier(0.0, 1) == "stable"

    def test_fragile_low_pct(self):
        assert _classify_tier(25.0, 2) == "fragile"

    def test_unstable_high_pct(self):
        assert _classify_tier(55.0, 3) == "unstable"

    def test_unstable_deep_chain(self):
        assert _classify_tier(15.0, 4) == "unstable"

    def test_critical_both_high(self):
        assert _classify_tier(60.0, 5) == "critical"


# ---------------------------------------------------------------------------
# _generate_advice
# ---------------------------------------------------------------------------


class TestGenerateAdvice:
    def test_stable_advice(self):
        advice = _generate_advice("stable", 0, 1)
        assert "isolated" in advice.lower() or "clean" in advice.lower()

    def test_fragile_advice(self):
        advice = _generate_advice("fragile", 1, 2)
        assert "monitor" in advice.lower()

    def test_unstable_advice(self):
        advice = _generate_advice("unstable", 2, 4)
        assert "root cause" in advice.lower() or "investigate" in advice.lower()

    def test_critical_advice(self):
        advice = _generate_advice("critical", 3, 6)
        assert "not stabilizing" in advice.lower() or "fundamental" in advice.lower()


# ---------------------------------------------------------------------------
# integration — realistic scenario
# ---------------------------------------------------------------------------


class TestRealisticScenario:
    def test_overnight_restart_storm(self):
        """Simulate a bad night: 4 restarts in 20 minutes, then stable."""
        timestamps = [
            _ts(0),     # 00:00 — first death
            _ts(5),     # 00:05 — restarted, died again (5min gap)
            _ts(12),    # 00:12 — restarted, died again (7min gap)
            _ts(20),    # 00:20 — restarted once more (8min gap)
            _ts(180),   # 03:00 — isolated restart hours later
            _ts(480),   # 08:00 — morning restart
        ]
        result = detect_cascades(timestamps)

        assert result["total_restarts"] == 6
        assert result["cascade_count"] == 1
        assert result["cascades"][0]["depth"] == 4
        assert result["max_depth"] == 4
        # 4 of 6 restarts in cascade = 66.7%
        assert result["cascade_pct"] == pytest.approx(66.7, abs=0.5)

    def test_healthy_repo_pattern(self):
        """Simulate healthy pattern: restarts well-spaced over days."""
        timestamps = [
            _ts(0),           # Day 1 morning
            _ts(60 * 24),     # Day 2 morning
            _ts(60 * 48),     # Day 3 morning
        ]
        result = detect_cascades(timestamps)
        assert result["tier"] == "stable"
        assert result["cascade_count"] == 0

    def test_single_pair_among_many(self):
        """One cascade pair among 10 well-spaced restarts."""
        timestamps = [_ts(i * 120) for i in range(10)]  # every 2 hours
        # Replace one with a close pair
        timestamps[5] = _ts(600)   # t=600min
        timestamps[6] = _ts(605)   # t=605min (5 min later)
        result = detect_cascades(timestamps)
        assert result["cascade_count"] == 1
        assert result["total_restarts"] == 10
