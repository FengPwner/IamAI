#!/usr/bin/env python3
"""Tests for tools/repo_reflex.py — repo self-healing reflex scorer."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from repo_reflex import (
    ReflexMetric,
    ReflexReport,
    grade,
    exit_code_for_grade,
    score_stroke_recovery,
    score_backlog_clearance,
    score_restart_latency,
    score_cadence_return,
    _clamp,
    _intervals_from_timestamps,
    assess,
    as_text,
    as_json,
)
from datetime import datetime, timezone, timedelta


# ── _clamp ────────────────────────────────────────────────────────────


class TestClamp:
    def test_within_range(self):
        assert _clamp(12.5) == 12.5

    def test_below_zero(self):
        assert _clamp(-5.0) == 0.0

    def test_above_max(self):
        assert _clamp(30.0) == 25.0

    def test_custom_range(self):
        assert _clamp(50.0, 0.0, 100.0) == 50.0
        assert _clamp(-1.0, 0.0, 100.0) == 0.0
        assert _clamp(150.0, 0.0, 100.0) == 100.0


# ── score_stroke_recovery ─────────────────────────────────────────────


class TestScoreStrokeRecovery:
    def test_no_gaps_perfect(self):
        m = score_stroke_recovery([])
        assert m.value == 25.0
        assert "no stalls" in m.detail

    def test_no_stall_events(self):
        """All gaps are within 2× cadence → no stalls."""
        gaps = [30.0, 45.0, 50.0, 60.0]
        m = score_stroke_recovery(gaps, cadence_s=60.0)
        assert m.value == 25.0

    def test_small_stall(self):
        """A 200s stall with 60s cadence (threshold 120s)."""
        gaps = [200.0]
        m = score_stroke_recovery(gaps, cadence_s=60.0)
        assert m.value > 20  # 200/1800 ≈ 0.11 → ~22.2

    def test_large_stall(self):
        """A 1800s stall → score 0."""
        gaps = [1800.0]
        m = score_stroke_recovery(gaps, cadence_s=60.0)
        assert m.value == 0.0

    def test_median_of_multiple(self):
        """Multiple stalls: median used."""
        gaps = [300.0, 600.0, 900.0]
        m = score_stroke_recovery(gaps, cadence_s=60.0)
        # median is 600 → 25 * (1 - 600/1800) = 25 * 0.667 ≈ 16.67
        assert 15 < m.value < 18

    def test_detail_includes_event_count(self):
        gaps = [300.0, 600.0]
        m = score_stroke_recovery(gaps, cadence_s=60.0)
        assert "2 events" in m.detail


# ── score_backlog_clearance ───────────────────────────────────────────


class TestScoreBacklogClearance:
    def test_no_events(self):
        m = score_backlog_clearance([])
        assert m.value == 25.0
        assert "no backlog" in m.detail

    def test_fast_clearance(self):
        """60s clearance → nearly full score."""
        m = score_backlog_clearance([60.0])
        # 25 * (1 - 60/1800) = 25 * 0.967 ≈ 24.17
        assert m.value > 23

    def test_slow_clearance(self):
        """1800s clearance → 0."""
        m = score_backlog_clearance([1800.0])
        assert m.value == 0.0

    def test_medium_clearance(self):
        """900s → 12.5."""
        m = score_backlog_clearance([900.0])
        assert m.value == 12.5

    def test_multiple_events_uses_median(self):
        m = score_backlog_clearance([100.0, 500.0, 1200.0])
        # median 500 → 25 * (1 - 500/1800) ≈ 18.06
        assert 17 < m.value < 19


# ── score_restart_latency ─────────────────────────────────────────────


class TestScoreRestartLatency:
    def test_no_restarts(self):
        m = score_restart_latency([])
        assert m.value == 25.0
        assert "no restarts" in m.detail

    def test_instant_restart(self):
        """Near-zero latency → full score."""
        m = score_restart_latency([1.0])
        assert m.value > 24

    def test_300s_restart(self):
        """300s → 12.5."""
        m = score_restart_latency([300.0])
        assert m.value == 12.5

    def test_over_600s(self):
        """600s+ → 0."""
        m = score_restart_latency([600.0])
        assert m.value == 0.0

    def test_multiple_median(self):
        m = score_restart_latency([100.0, 200.0, 400.0])
        # median 200 → 25 * (1 - 200/600) ≈ 16.67
        assert 15 < m.value < 18


# ── score_cadence_return ──────────────────────────────────────────────


class TestScoreCadenceReturn:
    def test_too_few_intervals(self):
        m = score_cadence_return([600.0])
        assert m.value == 25.0
        assert "too few" in m.detail

    def test_perfect_cadence(self):
        """All intervals at target → full score."""
        intervals = [600.0] * 10
        m = score_cadence_return(intervals, target_s=600.0)
        assert m.value == 25.0

    def test_drift_then_recovery(self):
        """One big drift followed by quick recovery."""
        intervals = [600.0, 600.0, 1500.0, 600.0, 600.0]
        m = score_cadence_return(intervals, target_s=600.0)
        # Drift at index 2, recovered at index 3 → 1 cycle recovery
        assert m.value > 20

    def test_persistent_drift(self):
        """Drift that never recovers → score based on mean deviation."""
        intervals = [1500.0, 1500.0, 1500.0]
        m = score_cadence_return(intervals, target_s=600.0)
        # deviation = 150% each → mean 1.5 → score = 25*(1-1.5) = clamped to 0
        assert m.value == 0.0

    def test_moderate_drift(self):
        """Some drift within bounds."""
        intervals = [600.0, 750.0, 650.0, 600.0]
        m = score_cadence_return(intervals, target_s=600.0)
        # No deviation >50%, so no recovery_times → mean deviation path
        assert m.value > 15


# ── grade ─────────────────────────────────────────────────────────────


class TestGrade:
    def test_sharp(self):
        assert grade(100.0) == "sharp"
        assert grade(80.0) == "sharp"

    def test_responsive(self):
        assert grade(79.9) == "responsive"
        assert grade(50.0) == "responsive"

    def test_sluggish(self):
        assert grade(49.9) == "sluggish"
        assert grade(20.0) == "sluggish"

    def test_numb(self):
        assert grade(19.9) == "numb"
        assert grade(0.0) == "numb"


class TestExitCode:
    def test_sharp_zero(self):
        assert exit_code_for_grade("sharp") == 0

    def test_responsive_zero(self):
        assert exit_code_for_grade("responsive") == 0

    def test_sluggish_one(self):
        assert exit_code_for_grade("sluggish") == 1

    def test_numb_two(self):
        assert exit_code_for_grade("numb") == 2

    def test_unknown_three(self):
        assert exit_code_for_grade("???") == 3


# ── _intervals_from_timestamps ────────────────────────────────────────


class TestIntervalsFromTimestamps:
    def test_empty(self):
        assert _intervals_from_timestamps([]) == []

    def test_single(self):
        now = datetime.now(timezone.utc)
        assert _intervals_from_timestamps([now]) == []

    def test_two_timestamps(self):
        t0 = datetime(2026, 10, 24, 0, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 10, 24, 0, 10, 0, tzinfo=timezone.utc)
        intervals = _intervals_from_timestamps([t0, t1])
        assert len(intervals) == 1
        assert intervals[0] == 600.0

    def test_unsorted_input(self):
        """Should sort internally."""
        t0 = datetime(2026, 10, 24, 0, 10, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 10, 24, 0, 0, 0, tzinfo=timezone.utc)
        intervals = _intervals_from_timestamps([t0, t1])
        assert intervals[0] == 600.0

    def test_three_timestamps(self):
        base = datetime(2026, 10, 24, 0, 0, 0, tzinfo=timezone.utc)
        ts = [base, base + timedelta(minutes=10), base + timedelta(minutes=25)]
        intervals = _intervals_from_timestamps(ts)
        assert len(intervals) == 2
        assert intervals[0] == 600.0
        assert intervals[1] == 900.0


# ── assess (integration) ─────────────────────────────────────────────


class TestAssess:
    def test_returns_report(self):
        report = assess(n_commits=10)
        assert isinstance(report, ReflexReport)
        assert report.grade in ("sharp", "responsive", "sluggish", "numb")
        assert 0 <= report.total <= 100
        assert len(report.metrics) == 4

    def test_metric_names(self):
        report = assess(n_commits=10)
        names = [m.name for m in report.metrics]
        assert "stroke_recovery" in names
        assert "backlog_clearance" in names
        assert "restart_latency" in names
        assert "cadence_return" in names

    def test_zero_commits(self):
        report = assess(n_commits=0)
        assert report.scanned_commits == 0
        # With no data, defaults should produce reasonable scores.
        assert report.total >= 0


# ── formatting ────────────────────────────────────────────────────────


class TestFormatting:
    def test_as_text_contains_grade(self):
        report = ReflexReport(
            metrics=[ReflexMetric("test", 20.0, "detail")],
            total=80.0,
            grade="sharp",
            scanned_commits=50,
            checked_at="2026-10-24T00:00:00",
        )
        text = as_text(report)
        assert "SHARP" in text
        assert "80.0" in text
        assert "test" in text

    def test_as_json_valid(self):
        report = ReflexReport(
            metrics=[ReflexMetric("test", 20.0, "detail")],
            total=80.0,
            grade="sharp",
            scanned_commits=50,
            checked_at="2026-10-24T00:00:00",
        )
        import json
        data = json.loads(as_json(report))
        assert data["grade"] == "sharp"
        assert data["total"] == 80.0
        assert len(data["metrics"]) == 1

    def test_bar_visual(self):
        report = ReflexReport(
            metrics=[ReflexMetric("test", 25.0, "full")],
            total=25.0,
            grade="sharp",
            scanned_commits=10,
            checked_at="now",
        )
        text = as_text(report)
        assert "█" in text
