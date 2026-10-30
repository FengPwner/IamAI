#!/usr/bin/env python3
"""Tests for writer_rhythm_score — rhythm health scoring logic."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from writer_rhythm_score import (
    compute_score,
    grade_to_exit,
    load_intervals,
)


# ---------------------------------------------------------------------------
# compute_score
# ---------------------------------------------------------------------------

class TestComputeScore:
    def test_empty_intervals_returns_stalled(self):
        result = compute_score([])
        assert result["score"] == 0
        assert result["grade"] == "stalled"
        assert result["sample_count"] == 0

    def test_perfect_cadence_scores_high(self):
        intervals = [900.0] * 50
        result = compute_score(intervals, expected_cadence=900.0)
        assert result["score"] >= 90
        assert result["grade"] == "healthy"
        assert result["pct_on_time"] == 100.0

    def test_slightly_irregular_still_healthy(self):
        intervals = [850.0, 920.0, 880.0, 950.0, 910.0] * 10
        result = compute_score(intervals, expected_cadence=900.0)
        assert result["score"] >= 70
        assert result["grade"] == "healthy"

    def test_degraded_with_long_gaps(self):
        # 30% of intervals at 10x cadence
        intervals = [900.0] * 15 + [9000.0] * 15 + [900.0] * 20
        result = compute_score(intervals, expected_cadence=900.0)
        assert result["grade"] == "degraded"
        assert 30 <= result["score"] < 70

    def test_stalled_with_massive_gap(self):
        intervals = [9000.0] * 50
        result = compute_score(intervals, expected_cadence=900.0)
        assert result["score"] < 30
        assert result["grade"] == "stalled"

    def test_single_interval(self):
        result = compute_score([900.0], expected_cadence=900.0)
        assert result["score"] == 100
        assert result["grade"] == "healthy"

    def test_score_bounded_0_to_100(self):
        intervals = [90000.0] * 50
        result = compute_score(intervals, expected_cadence=900.0)
        assert 0 <= result["score"] <= 100
        assert result["grade"] == "stalled"

    def test_custom_cadence(self):
        intervals = [60.0] * 30
        result = compute_score(intervals, expected_cadence=60.0)
        assert result["score"] >= 90
        assert result["grade"] == "healthy"

    def test_median_gap_computed(self):
        intervals = [100.0, 200.0, 300.0, 400.0, 500.0]
        result = compute_score(intervals, expected_cadence=300.0)
        assert result["median_gap"] == 300.0
        assert result["max_gap"] == 500.0

    def test_purity_on_time_pct(self):
        intervals = [900.0] * 25 + [2700.0] * 25
        result = compute_score(intervals, expected_cadence=900.0)
        assert result["pct_on_time"] == 50.0


# ---------------------------------------------------------------------------
# grade_to_exit
# ---------------------------------------------------------------------------

class TestGradeToExit:
    def test_healthy(self):
        assert grade_to_exit("healthy") == 0

    def test_degraded(self):
        assert grade_to_exit("degraded") == 1

    def test_stalled(self):
        assert grade_to_exit("stalled") == 2

    def test_unknown_defaults_to_2(self):
        assert grade_to_exit("unknown") == 2


# ---------------------------------------------------------------------------
# load_intervals
# ---------------------------------------------------------------------------

class TestLoadIntervals:
    def test_loads_from_jsonl(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        base = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        lines = []
        for i in range(10):
            ts = (base + timedelta(minutes=15 * i)).isoformat()
            lines.append(json.dumps({"seq": i, "at": ts, "kind": "thought"}))
        f.write_text("\n".join(lines))

        intervals = load_intervals(f, window=50)
        assert len(intervals) == 9
        for gap in intervals:
            assert 899 < gap < 901

    def test_missing_file_returns_empty(self, tmp_path):
        intervals = load_intervals(tmp_path / "nonexistent.jsonl")
        assert intervals == []

    def test_skips_invalid_lines(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        lines = [
            '{"seq": 1, "at": "2026-10-30T12:00:00+00:00", "kind": "t"}',
            'not valid json',
            '{"seq": 2, "at": "2026-10-30T12:15:00+00:00", "kind": "t"}',
        ]
        f.write_text("\n".join(lines))
        intervals = load_intervals(f, window=50)
        assert len(intervals) == 1
        assert 899 < intervals[0] < 901

    def test_window_limits_results(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        base = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
        lines = []
        for i in range(100):
            ts = (base + timedelta(minutes=15 * i)).isoformat()
            lines.append(json.dumps({"seq": i, "at": ts, "kind": "thought"}))
        f.write_text("\n".join(lines))

        intervals = load_intervals(f, window=10)
        assert len(intervals) == 10

    def test_skips_negative_gaps(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        lines = [
            '{"seq": 1, "at": "2026-10-30T12:00:00+00:00"}',
            '{"seq": 2, "at": "2026-10-30T11:00:00+00:00"}',
            '{"seq": 3, "at": "2026-10-30T12:30:00+00:00"}',
        ]
        f.write_text("\n".join(lines))
        intervals = load_intervals(f, window=50)
        assert all(g > 0 for g in intervals)


# ---------------------------------------------------------------------------
# Integration: run on actual strokes data
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_real_data_doesnt_crash(self):
        strokes = Path(__file__).resolve().parent.parent / "data" / "strokes.jsonl"
        if strokes.exists():
            intervals = load_intervals(strokes, window=20)
            result = compute_score(intervals)
            assert 0 <= result["score"] <= 100
            assert result["grade"] in ("healthy", "degraded", "stalled")
