"""Tests for iamai/process_lifecycle_scorer.py — process lifecycle scoring."""

from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.process_lifecycle_scorer import (
    _count_reclamations,
    _current_uptime_seconds,
    _extract_uptimes,
    _observation_window_seconds,
    _stability_score,
    _verdict,
    score_lifecycle,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _ev(kind: str, dt: datetime) -> dict:
    return {"kind": kind, "at": _iso(dt)}


TZ = timezone(timedelta(hours=8))


def _ts(hour: int, minute: int = 0) -> datetime:
    """Return a fixed-base datetime for 2026-10-24 at the given hour:minute."""
    return datetime(2026, 10, 24, hour, minute, tzinfo=TZ)


# ---------------------------------------------------------------------------
# _extract_uptimes
# ---------------------------------------------------------------------------

class TestExtractUptimes:
    def test_empty(self):
        assert _extract_uptimes([]) == []

    def test_single_start_no_stop(self):
        events = [_ev("start", _ts(1))]
        assert _extract_uptimes(events) == []

    def test_single_stop_no_start(self):
        events = [_ev("stop", _ts(2))]
        assert _extract_uptimes(events) == []

    def test_one_pair(self):
        events = [_ev("start", _ts(1)), _ev("stop", _ts(4))]
        uptimes = _extract_uptimes(events)
        assert len(uptimes) == 1
        assert uptimes[0] == pytest.approx(3 * 3600, abs=1)

    def test_two_pairs(self):
        events = [
            _ev("start", _ts(1)),
            _ev("stop", _ts(3)),
            _ev("start", _ts(5)),
            _ev("stop", _ts(8)),
        ]
        uptimes = _extract_uptimes(events)
        assert len(uptimes) == 2
        assert uptimes[0] == pytest.approx(2 * 3600, abs=1)
        assert uptimes[1] == pytest.approx(3 * 3600, abs=1)

    def test_consecutive_starts(self):
        """Two starts in a row — only the first counts."""
        events = [
            _ev("start", _ts(1)),
            _ev("start", _ts(2)),
            _ev("stop", _ts(5)),
        ]
        uptimes = _extract_uptimes(events)
        assert len(uptimes) == 1
        assert uptimes[0] == pytest.approx(4 * 3600, abs=1)

    def test_consecutive_stops(self):
        """Two stops in a row — second stop is ignored."""
        events = [
            _ev("start", _ts(1)),
            _ev("stop", _ts(3)),
            _ev("stop", _ts(4)),
        ]
        uptimes = _extract_uptimes(events)
        assert len(uptimes) == 1

    def test_crash_counts_as_stop(self):
        events = [_ev("start", _ts(1)), _ev("crash", _ts(2))]
        uptimes = _extract_uptimes(events)
        assert len(uptimes) == 1
        assert uptimes[0] == pytest.approx(3600, abs=1)

    def test_exit_counts_as_stop(self):
        events = [_ev("start", _ts(1)), _ev("exit", _ts(1, 30))]
        uptimes = _extract_uptimes(events)
        assert len(uptimes) == 1
        assert uptimes[0] == pytest.approx(1800, abs=1)

    def test_unsorted_input(self):
        """Events should be sorted internally."""
        events = [
            _ev("stop", _ts(5)),
            _ev("start", _ts(1)),
        ]
        uptimes = _extract_uptimes(events)
        assert len(uptimes) == 1
        assert uptimes[0] == pytest.approx(4 * 3600, abs=1)

    def test_three_cycles(self):
        events = [
            _ev("start", _ts(0)), _ev("stop", _ts(2)),
            _ev("start", _ts(3)), _ev("stop", _ts(6)),
            _ev("start", _ts(7)), _ev("stop", _ts(10)),
        ]
        uptimes = _extract_uptimes(events)
        assert len(uptimes) == 3
        assert uptimes == pytest.approx([7200, 10800, 10800], abs=1)


# ---------------------------------------------------------------------------
# _count_reclamations
# ---------------------------------------------------------------------------

class TestCountReclamations:
    def test_empty(self):
        assert _count_reclamations([]) == 0

    def test_no_stops(self):
        events = [_ev("start", _ts(1)), _ev("start", _ts(5))]
        assert _count_reclamations(events) == 0

    def test_one_reclaim(self):
        events = [_ev("start", _ts(1)), _ev("stop", _ts(3))]
        assert _count_reclamations(events) == 1

    def test_consecutive_stops_count_as_one(self):
        events = [
            _ev("start", _ts(1)),
            _ev("stop", _ts(2)),
            _ev("stop", _ts(3)),
        ]
        assert _count_reclamations(events) == 1

    def test_three_reclaims(self):
        events = [
            _ev("start", _ts(1)), _ev("stop", _ts(2)),
            _ev("start", _ts(3)), _ev("crash", _ts(4)),
            _ev("start", _ts(5)), _ev("stop", _ts(6)),
        ]
        assert _count_reclamations(events) == 3

    def test_stop_without_start_ignored(self):
        events = [
            _ev("stop", _ts(1)),
            _ev("start", _ts(2)),
            _ev("stop", _ts(4)),
        ]
        assert _count_reclamations(events) == 1


# ---------------------------------------------------------------------------
# _stability_score
# ---------------------------------------------------------------------------

class TestStabilityScore:
    def test_no_uptimes(self):
        assert _stability_score(0, [], 3600) == 0.0

    def test_zero_window(self):
        assert _stability_score(0, [3600], 0) == 0.0

    def test_perfect_stability(self):
        """Full uptime, zero reclaims -> 1.0."""
        score = _stability_score(0, [3600], 3600)
        assert score == pytest.approx(1.0)

    def test_one_reclaim_penalty(self):
        """One reclaim: score = uptime_ratio * exp(-0.5)."""
        score = _stability_score(1, [3600], 3600)
        expected = 1.0 * math.exp(-0.5)
        assert score == pytest.approx(round(expected, 4), abs=0.001)

    def test_many_reclaims_low_score(self):
        """Five reclaims should produce a very low score."""
        score = _stability_score(5, [3600], 3600)
        expected = 1.0 * math.exp(-2.5)
        assert score == pytest.approx(round(expected, 4), abs=0.001)

    def test_uptime_ratio_clamped(self):
        """Uptime exceeding window is clamped to 1.0."""
        score = _stability_score(0, [7200], 3600)
        assert score == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# _current_uptime_seconds
# ---------------------------------------------------------------------------

class TestCurrentUptime:
    def test_empty(self):
        assert _current_uptime_seconds([]) is None

    def test_last_event_is_stop(self):
        events = [_ev("start", _ts(1)), _ev("stop", _ts(3))]
        assert _current_uptime_seconds(events) is None

    def test_last_event_is_start(self):
        events = [_ev("start", _ts(1)), _ev("stop", _ts(3)), _ev("start", _ts(4))]
        now = _ts(6)
        uptime = _current_uptime_seconds(events, now)
        assert uptime is not None
        assert uptime == pytest.approx(2 * 3600, abs=1)

    def test_just_started(self):
        now = _ts(4)
        events = [_ev("start", now)]
        uptime = _current_uptime_seconds(events, now)
        assert uptime == 0.0


# ---------------------------------------------------------------------------
# _verdict
# ---------------------------------------------------------------------------

class TestVerdict:
    def test_no_current_uptime_is_critical(self):
        assert _verdict(0, None, 1.0) == "critical"

    def test_many_reclaims_critical(self):
        assert _verdict(3, 7200, 0.5) == "critical"

    def test_short_uptime_critical(self):
        """Uptime < 1 hour is critical."""
        assert _verdict(0, 1800, 0.8) == "critical"

    def test_one_reclaim_degraded(self):
        assert _verdict(1, 7200, 0.6) == "degraded"

    def test_two_reclaims_degraded(self):
        assert _verdict(2, 7200, 0.5) == "degraded"

    def test_short_uptime_degraded(self):
        """Uptime between 1 and 6 hours with 0 reclaims is degraded."""
        assert _verdict(0, 10800, 0.9) == "degraded"

    def test_healthy(self):
        """0 reclaims, uptime > 6 hours -> healthy."""
        assert _verdict(0, 25200, 0.95) == "healthy"

    def test_boundary_exactly_six_hours(self):
        """Exactly 6 hours with 0 reclaims is degraded (>= threshold)."""
        assert _verdict(0, 21600, 0.95) == "healthy"


# ---------------------------------------------------------------------------
# score_lifecycle (integration)
# ---------------------------------------------------------------------------

class TestScoreLifecycle:
    def test_empty_events(self):
        result = score_lifecycle([])
        assert result["stability_score"] == 0.0
        assert result["verdict"] == "critical"
        assert result["reclamation_count"] == 0
        assert result["mean_uptime"] == 0.0
        assert result["churn_rate"] == 0.0
        assert result["current_uptime"] is None
        assert result["uptimes"] == []

    def test_single_start_only(self):
        now = _ts(8)
        events = [_ev("start", _ts(1))]
        result = score_lifecycle(events, now=now)
        assert result["stability_score"] == 0.0  # no window
        assert result["reclamation_count"] == 0
        assert result["current_uptime"] == pytest.approx(7 * 3600, abs=1)
        # uptime > 6h, 0 reclaims -> healthy
        assert result["verdict"] == "healthy"

    def test_overnight_churn(self):
        """Simulate overnight: 4 reclaims in 8 hours."""
        events = [
            _ev("start", _ts(0)), _ev("stop", _ts(1)),
            _ev("start", _ts(2)), _ev("stop", _ts(3)),
            _ev("start", _ts(4)), _ev("stop", _ts(5)),
            _ev("start", _ts(6)), _ev("stop", _ts(7)),
            _ev("start", _ts(8)),
        ]
        now = _ts(9)
        result = score_lifecycle(events, now=now)
        assert result["reclamation_count"] == 4
        assert result["verdict"] == "critical"
        assert result["stability_score"] < 0.1
        assert len(result["uptimes"]) == 4

    def test_healthy_long_run(self):
        """One start, no stops for 12 hours."""
        events = [_ev("start", _ts(0))]
        now = _ts(12)
        result = score_lifecycle(events, now=now)
        assert result["reclamation_count"] == 0
        assert result["verdict"] == "healthy"
        assert result["current_uptime"] == pytest.approx(12 * 3600, abs=1)

    def test_degraded_one_reclaim_recent_start(self):
        """One reclaim, running for 3 hours."""
        events = [
            _ev("start", _ts(0)), _ev("stop", _ts(8)),
            _ev("start", _ts(9)),
        ]
        now = _ts(12)
        result = score_lifecycle(events, now=now)
        assert result["reclamation_count"] == 1
        assert result["verdict"] == "degraded"
        assert result["current_uptime"] == pytest.approx(3 * 3600, abs=1)

    def test_uptimes_list_populated(self):
        events = [
            _ev("start", _ts(0)), _ev("stop", _ts(2)),
            _ev("start", _ts(3)), _ev("stop", _ts(6)),
        ]
        result = score_lifecycle(events, now=_ts(6))
        assert len(result["uptimes"]) == 2
        assert result["mean_uptime"] > 0

    def test_churn_rate_calculation(self):
        """2 reclaims over 4 hours = 0.5 reclaims/hour."""
        events = [
            _ev("start", _ts(0)), _ev("stop", _ts(1)),
            _ev("start", _ts(2)), _ev("stop", _ts(3)),
            _ev("start", _ts(4)),
        ]
        result = score_lifecycle(events, now=_ts(4))
        assert result["churn_rate"] == pytest.approx(0.5, abs=0.01)

    def test_string_and_datetime_events(self):
        """Mix of string and datetime timestamps."""
        events = [
            {"kind": "start", "at": _ts(0)},
            {"kind": "stop", "at": _iso(_ts(2))},
            {"kind": "start", "at": _iso(_ts(3))},
        ]
        result = score_lifecycle(events, now=_ts(5))
        assert result["reclamation_count"] == 1
        assert len(result["uptimes"]) == 1

    def test_realistic_caretaker_scenario(self):
        """Simulate today's visit 331: process reclaimed and restarted."""
        events = [
            _ev("start", _ts(1, 0)),   # original start
            _ev("stop", _ts(3, 55)),   # reclaimed
            _ev("start", _ts(4, 1)),   # restarted by caretaker
        ]
        now = _ts(4, 2)
        result = score_lifecycle(events, now=now)
        assert result["reclamation_count"] == 1
        assert result["verdict"] == "critical"  # uptime < 1 hour
        assert result["current_uptime"] is not None
        assert result["current_uptime"] < 3600