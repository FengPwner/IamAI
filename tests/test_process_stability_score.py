"""Tests for iamai.process_stability_score — writer process stability scoring.

Covers: StabilityReport properties, score_uptime, score_cadence,
score_stall_distance, score_restarts, grade, get_cadence_cv,
get_stall_distance_seconds, stability_report composite, edge cases,
boundary conditions.
"""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.process_stability_score import (
    CADENCE_CV_THRESHOLD,
    GRADE_SHAKY,
    GRADE_STABLE,
    MAX_PER_SIGNAL,
    RESTART_PENALTY,
    STALL_HOURS_FOR_FULL,
    UPTIME_HOURS_FOR_FULL,
    StabilityReport,
    _parse_iso,
    get_cadence_cv,
    get_stall_distance_seconds,
    grade,
    score_cadence,
    score_restarts,
    score_stall_distance,
    score_uptime,
    stability_report,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_history(timestamps: list[str]) -> list[dict]:
    """Build a minimal history list from a list of ISO timestamps."""
    return [{"at": ts, "kind": "note", "path": "notes/test.md", "seq": i}
            for i, ts in enumerate(timestamps)]


def _iso(epoch: float) -> str:
    """Convert a Unix epoch to an ISO timestamp string."""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# score_uptime
# ---------------------------------------------------------------------------

class TestScoreUptime:
    def test_zero_uptime(self):
        assert score_uptime(0) == 0.0

    def test_full_uptime(self):
        full = UPTIME_HOURS_FOR_FULL * 3600
        assert score_uptime(full) == MAX_PER_SIGNAL

    def test_half_uptime(self):
        half = UPTIME_HOURS_FOR_FULL * 3600 / 2
        expected = MAX_PER_SIGNAL / 2
        assert abs(score_uptime(half) - expected) < 0.1

    def test_over_full_caps(self):
        way_over = UPTIME_HOURS_FOR_FULL * 3600 * 10
        assert score_uptime(way_over) == MAX_PER_SIGNAL

    def test_one_hour(self):
        one_hour = 3600
        expected = 1.0 * (MAX_PER_SIGNAL / UPTIME_HOURS_FOR_FULL)
        assert abs(score_uptime(one_hour) - expected) < 0.1


# ---------------------------------------------------------------------------
# score_cadence
# ---------------------------------------------------------------------------

class TestScoreCadence:
    def test_perfect_cadence(self):
        assert score_cadence(0.0) == MAX_PER_SIGNAL

    def test_worst_cadence(self):
        assert score_cadence(CADENCE_CV_THRESHOLD) == 0.0

    def test_half_cadence(self):
        cv = CADENCE_CV_THRESHOLD / 2
        expected = MAX_PER_SIGNAL / 2
        assert abs(score_cadence(cv) - expected) < 0.1

    def test_over_threshold_caps(self):
        assert score_cadence(CADENCE_CV_THRESHOLD * 2) == 0.0

    def test_negative_cv_treated_as_zero(self):
        assert score_cadence(-0.5) == MAX_PER_SIGNAL


# ---------------------------------------------------------------------------
# score_stall_distance
# ---------------------------------------------------------------------------

class TestScoreStallDistance:
    def test_zero_distance(self):
        assert score_stall_distance(0) == 0.0

    def test_full_distance(self):
        full = STALL_HOURS_FOR_FULL * 3600
        assert score_stall_distance(full) == MAX_PER_SIGNAL

    def test_half_distance(self):
        half = STALL_HOURS_FOR_FULL * 3600 / 2
        expected = MAX_PER_SIGNAL / 2
        assert abs(score_stall_distance(half) - expected) < 0.1

    def test_over_full_caps(self):
        assert score_stall_distance(STALL_HOURS_FOR_FULL * 3600 * 3) == MAX_PER_SIGNAL


# ---------------------------------------------------------------------------
# score_restarts
# ---------------------------------------------------------------------------

class TestScoreRestarts:
    def test_no_restarts(self):
        assert score_restarts(0) == MAX_PER_SIGNAL

    def test_one_restart(self):
        assert score_restarts(1) == MAX_PER_SIGNAL - RESTART_PENALTY

    def test_max_restarts_zeroes(self):
        # 4 restarts * 8 = 32 > 25 → capped at 0
        assert score_restarts(4) == 0.0

    def test_three_restarts(self):
        expected = max(0, MAX_PER_SIGNAL - 3 * RESTART_PENALTY)
        assert score_restarts(3) == expected


# ---------------------------------------------------------------------------
# grade
# ---------------------------------------------------------------------------

class TestGrade:
    def test_stable(self):
        assert grade(75) == "stable"
        assert grade(100) == "stable"

    def test_shaky(self):
        assert grade(40) == "shaky"
        assert grade(74.9) == "shaky"

    def test_fragile(self):
        assert grade(0) == "fragile"
        assert grade(39.9) == "fragile"

    def test_boundary_stable(self):
        assert grade(GRADE_STABLE) == "stable"

    def test_boundary_shaky(self):
        assert grade(GRADE_SHAKY) == "shaky"


# ---------------------------------------------------------------------------
# get_cadence_cv
# ---------------------------------------------------------------------------

class TestGetCadenceCV:
    def test_perfectly_regular(self):
        now = 1000000.0
        ts = [_iso(now - 60), _iso(now - 45), _iso(now - 30), _iso(now - 15)]
        history = _make_history(ts)
        cv = get_cadence_cv(history, now=now, window_seconds=120)
        # all intervals are 15s → cv ≈ 0
        assert cv < 0.01

    def test_highly_irregular(self):
        now = 1000000.0
        # intervals: 1, 50, 1 → high cv
        ts = [_iso(now - 52), _iso(now - 51), _iso(now - 1), _iso(now)]
        history = _make_history(ts)
        cv = get_cadence_cv(history, now=now, window_seconds=120)
        assert cv > 0.5

    def test_too_few_strokes(self):
        now = 1000000.0
        history = _make_history([_iso(now - 10), _iso(now)])
        cv = get_cadence_cv(history, now=now, window_seconds=120)
        assert cv == 1.0  # default worst

    def test_empty_history(self):
        cv = get_cadence_cv([], now=1000000.0)
        assert cv == 1.0

    def test_window_excludes_old_strokes(self):
        now = 1000000.0
        # old strokes outside window, then regular recent ones
        old = [_iso(now - 7200), _iso(now - 7185), _iso(now - 7170)]
        recent = [_iso(now - 45), _iso(now - 30), _iso(now - 15)]
        history = _make_history(old + recent)
        cv = get_cadence_cv(history, now=now, window_seconds=120)
        # only recent strokes matter → regular → low cv
        assert cv < 0.1

    def test_all_same_timestamp(self):
        now = 1000000.0
        ts = [_iso(now)] * 5
        history = _make_history(ts)
        cv = get_cadence_cv(history, now=now, window_seconds=120)
        # zero intervals → worst
        assert cv == 1.0


# ---------------------------------------------------------------------------
# get_stall_distance_seconds
# ---------------------------------------------------------------------------

class TestGetStallDistanceSeconds:
    def test_no_stall(self):
        now = 1000000.0
        # regular 15s intervals
        ts = [_iso(now - 60 + i * 15) for i in range(5)]
        history = _make_history(ts)
        dist = get_stall_distance_seconds(history, now=now)
        # no stall found → distance = now - first stroke
        assert abs(dist - 60) < 1

    def test_stall_in_middle(self):
        now = 1000000.0
        # stroke at t-300, then gap of 60s (stall), then stroke at t-240
        # then regular strokes
        ts = [
            _iso(now - 300),
            _iso(now - 240),  # this ends the stall
            _iso(now - 225),
            _iso(now - 210),
        ]
        history = _make_history(ts)
        dist = get_stall_distance_seconds(history, now=now, cadence_seconds=15)
        # last stall ended at now - 240 → distance = 240
        assert abs(dist - 240) < 1

    def test_stall_at_end(self):
        now = 1000000.0
        # regular strokes then a big gap before the last one
        ts = [
            _iso(now - 100),
            _iso(now - 85),
            _iso(now - 70),
            _iso(now - 10),  # big gap from -70 to -10 = 60s stall
        ]
        history = _make_history(ts)
        dist = get_stall_distance_seconds(history, now=now, cadence_seconds=15)
        # stall ended at now - 10 → distance = 10
        assert abs(dist - 10) < 1

    def test_empty_history(self):
        assert get_stall_distance_seconds([], now=1000000.0) == 0.0

    def test_single_stroke(self):
        now = 1000000.0
        history = _make_history([_iso(now - 500)])
        dist = get_stall_distance_seconds(history, now=now)
        assert abs(dist - 500) < 1


# ---------------------------------------------------------------------------
# _parse_iso
# ---------------------------------------------------------------------------

class TestParseISO:
    def test_utc_offset(self):
        result = _parse_iso("2026-10-23T04:00:00+00:00")
        assert result is not None
        assert result > 0

    def test_z_suffix(self):
        result = _parse_iso("2026-10-23T04:00:00Z")
        assert result is not None

    def test_empty_string(self):
        assert _parse_iso("") is None

    def test_invalid(self):
        assert _parse_iso("not-a-date") is None


# ---------------------------------------------------------------------------
# stability_report composite
# ---------------------------------------------------------------------------

class TestStabilityReport:
    def test_freshly_started(self):
        """A just-started process with no history → fragile."""
        now = 1000000.0
        report = stability_report(
            writer_id="nonexistent",
            now=now,
            history=[],
        )
        assert report.grade == "fragile"
        assert report.score < GRADE_SHAKY

    def test_stable_process(self):
        """Long-running, regular output, no stalls → stable."""
        now = 1000000.0
        # 12 hours of uptime, regular 15s cadence for 2 hours
        ts = [_iso(now - 7200 + i * 15) for i in range(480)]
        history = _make_history(ts)

        with patch(
            "iamai.process_stability_score.get_uptime_seconds",
            return_value=12 * 3600,
        ):
            with patch(
                "iamai.process_stability_score.get_restart_count_24h",
                return_value=0,
            ):
                report = stability_report(
                    writer_id="test",
                    now=now,
                    history=history,
                )
        assert report.grade == "stable"
        assert report.score >= GRADE_STABLE

    def test_summary_format(self):
        now = 1000000.0
        report = StabilityReport(
            score=65.0,
            grade="shaky",
            uptime_seconds=7200,
            uptime_score=18.0,
            cadence_cv=0.3,
            cadence_score=17.5,
            stall_distance_seconds=3600,
            stall_score=10.0,
            restart_count_24h=2,
            restart_score=9.0,
        )
        s = report.summary()
        assert "shaky" in s
        assert "65/100" in s
        assert "2 restarts" in s

    def test_all_zero_history(self):
        """Empty history should yield fragile."""
        report = stability_report(
            writer_id="test",
            now=1000000.0,
            history=[],
        )
        assert report.grade == "fragile"
        assert report.cadence_cv == 1.0


# ---------------------------------------------------------------------------
# StabilityReport dataclass
# ---------------------------------------------------------------------------

class TestStabilityReportDataclass:
    def test_frozen(self):
        report = StabilityReport(
            score=50.0, grade="shaky",
            uptime_seconds=100, uptime_score=10,
            cadence_cv=0.5, cadence_score=12.5,
            stall_distance_seconds=200, stall_score=5,
            restart_count_24h=1, restart_score=17,
        )
        with pytest.raises(AttributeError):
            report.score = 99

    def test_fields(self):
        report = StabilityReport(
            score=80.0, grade="stable",
            uptime_seconds=36000, uptime_score=25,
            cadence_cv=0.1, cadence_score=22.5,
            stall_distance_seconds=18000, stall_score=25,
            restart_count_24h=0, restart_score=25,
        )
        assert report.score == 80.0
        assert report.grade == "stable"
        assert report.uptime_seconds == 36000
        assert report.restart_count_24h == 0
