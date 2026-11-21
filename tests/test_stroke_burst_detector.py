#!/usr/bin/env python3
"""Tests for stroke_burst_detector.py — 30 tests covering all paths."""

import json
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from stroke_burst_detector import (
    load_strokes,
    detect_bursts,
    classify_verdict,
    build_report,
    Burst,
    BurstReport,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ts(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def _make_strokes(times: list[datetime], path: Path) -> Path:
    """Write a minimal strokes.jsonl from a list of timestamps."""
    with open(path, "w") as f:
        for i, t in enumerate(times):
            record = {"seq": i, "at": t.isoformat(), "kind": "thought", "text": f"stroke {i}"}
            f.write(json.dumps(record) + "\n")
    return path


def _regular_times(base: datetime, count: int, interval_s: float) -> list[datetime]:
    return [base + timedelta(seconds=i * interval_s) for i in range(count)]


def _burst_times(base: datetime, count: int, interval_s: float) -> list[datetime]:
    return [base + timedelta(seconds=i * interval_s) for i in range(count)]


# ---------------------------------------------------------------------------
# load_strokes
# ---------------------------------------------------------------------------

class TestLoadStrokes:
    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        assert load_strokes(p) == []

    def test_missing_file(self, tmp_path):
        p = tmp_path / "nonexistent.jsonl"
        assert load_strokes(p) == []

    def test_valid_strokes(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = _regular_times(base, 5, 15.0)
        _make_strokes(times, p)
        loaded = load_strokes(p)
        assert len(loaded) == 5

    def test_malformed_lines_skipped(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with open(p, "w") as f:
            f.write("not json\n")
            f.write(json.dumps({"seq": 0, "at": base.isoformat(), "kind": "thought", "text": "ok"}) + "\n")
            f.write("{bad json\n")
        loaded = load_strokes(p)
        assert len(loaded) == 1

    def test_sorted_output(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = [base + timedelta(seconds=30), base, base + timedelta(seconds=15)]
        _make_strokes(times, p)
        loaded = load_strokes(p)
        assert loaded[0] <= loaded[1] <= loaded[2]


# ---------------------------------------------------------------------------
# detect_bursts
# ---------------------------------------------------------------------------

class TestDetectBursts:
    def test_no_bursts_regular_cadence(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = _regular_times(base, 20, 15.0)
        bursts = detect_bursts(times, target_cadence_s=15, threshold_pct=50.0)
        assert bursts == []

    def test_single_burst_detected(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        regular = _regular_times(base, 5, 15.0)
        # gap > threshold so the regular tail isn't absorbed into the burst
        burst_start = regular[-1] + timedelta(seconds=15)
        burst = _burst_times(burst_start, 5, 2.0)
        times = regular + burst
        bursts = detect_bursts(times, target_cadence_s=15, threshold_pct=50.0)
        assert len(bursts) == 1
        assert bursts[0].stroke_count == 5

    def test_severe_burst_classification(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = _burst_times(base, 6, 1.0)
        bursts = detect_bursts(times, target_cadence_s=15, threshold_pct=50.0)
        assert len(bursts) == 1
        assert bursts[0].severity == "severe"

    def test_mild_burst_classification(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = _burst_times(base, 5, 6.0)
        bursts = detect_bursts(times, target_cadence_s=15, threshold_pct=50.0)
        assert len(bursts) == 1
        assert bursts[0].severity == "mild"

    def test_too_short_run_ignored(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        regular = _regular_times(base, 5, 15.0)
        # gap > threshold so the regular tail isn't absorbed
        burst = _burst_times(regular[-1] + timedelta(seconds=15), 2, 2.0)
        times = regular + burst
        bursts = detect_bursts(times, target_cadence_s=15, threshold_pct=50.0, min_burst_size=3)
        assert bursts == []

    def test_custom_threshold(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = _burst_times(base, 5, 10.0)
        bursts_50 = detect_bursts(times, target_cadence_s=15, threshold_pct=50.0)
        bursts_80 = detect_bursts(times, target_cadence_s=15, threshold_pct=80.0)
        assert len(bursts_50) == 0
        assert len(bursts_80) == 1

    def test_multiple_bursts(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        seg1 = _regular_times(base, 5, 15.0)
        burst1 = _burst_times(seg1[-1] + timedelta(seconds=15), 4, 2.0)
        gap = _regular_times(burst1[-1] + timedelta(seconds=30), 5, 15.0)
        burst2 = _burst_times(gap[-1] + timedelta(seconds=15), 4, 1.0)
        times = seg1 + burst1 + gap + burst2
        bursts = detect_bursts(times, target_cadence_s=15, threshold_pct=50.0)
        assert len(bursts) == 2

    def test_empty_input(self):
        assert detect_bursts([]) == []

    def test_single_stroke(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert detect_bursts([base]) == []

    def test_mean_interval_calculation(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = [base, base + timedelta(seconds=3), base + timedelta(seconds=6), base + timedelta(seconds=9)]
        bursts = detect_bursts(times, target_cadence_s=15, threshold_pct=50.0, min_burst_size=3)
        assert len(bursts) == 1
        assert bursts[0].mean_interval_s == 3.0

    def test_trailing_burst_captured(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        regular = _regular_times(base, 3, 15.0)
        burst = _burst_times(regular[-1] + timedelta(seconds=15), 5, 2.0)
        times = regular + burst
        bursts = detect_bursts(times, target_cadence_s=15, threshold_pct=50.0)
        assert len(bursts) == 1
        assert bursts[0].stroke_count == 5


# ---------------------------------------------------------------------------
# classify_verdict
# ---------------------------------------------------------------------------

class TestClassifyVerdict:
    def test_clean(self):
        assert classify_verdict([]) == "clean"

    def test_mild(self):
        bursts = [Burst("a", "b", 5, 6.0, "mild")]
        assert classify_verdict(bursts) == "mild"

    def test_bursting_with_severe(self):
        bursts = [
            Burst("a", "b", 5, 6.0, "mild"),
            Burst("c", "d", 10, 1.0, "severe"),
        ]
        assert classify_verdict(bursts) == "bursting"

    def test_all_mild_stays_mild(self):
        bursts = [Burst("a", "b", 5, 6.0, "mild") for _ in range(3)]
        assert classify_verdict(bursts) == "mild"


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------

class TestBuildReport:
    def test_report_structure(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = _regular_times(base, 20, 15.0)
        bursts = detect_bursts(times)
        report = build_report(times, bursts, 15, 50.0)
        assert isinstance(report, BurstReport)
        assert report.total_strokes == 20
        assert report.verdict == "clean"

    def test_burst_rate_calculation(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = _regular_times(base, 100, 15.0)
        bursts = [Burst("a", "b", 5, 2.0, "severe")]
        report = build_report(times, bursts, 15, 50.0)
        assert report.burst_rate_per_1000 == 10.0

    def test_worst_burst_selection(self):
        bursts = [
            Burst("a", "b", 5, 5.0, "mild"),
            Burst("c", "d", 8, 1.0, "severe"),
            Burst("e", "f", 4, 3.0, "mild"),
        ]
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = _regular_times(base, 50, 15.0)
        report = build_report(times, bursts, 15, 50.0)
        assert report.worst_burst.mean_interval_s == 1.0

    def test_empty_bursts_no_worst(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = _regular_times(base, 10, 15.0)
        report = build_report(times, [], 15, 50.0)
        assert report.worst_burst is None
        assert report.total_bursts == 0

    def test_zero_strokes(self):
        report = build_report([], [], 15, 50.0)
        assert report.burst_rate_per_1000 == 0.0
        assert report.verdict == "clean"


# ---------------------------------------------------------------------------
# integration: end-to-end via temp file
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_end_to_end_with_burst(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        regular = _regular_times(base, 10, 15.0)
        burst = _burst_times(regular[-1] + timedelta(seconds=15), 6, 1.5)
        more = _regular_times(burst[-1] + timedelta(seconds=30), 10, 15.0)
        _make_strokes(regular + burst + more, p)
        timestamps = load_strokes(p)
        bursts = detect_bursts(timestamps, target_cadence_s=15, threshold_pct=50.0)
        report = build_report(timestamps, bursts, 15, 50.0)
        assert report.total_strokes == 26
        assert report.total_bursts == 1
        assert report.verdict == "bursting"

    def test_end_to_end_clean(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = _regular_times(base, 30, 15.0)
        _make_strokes(times, p)
        timestamps = load_strokes(p)
        bursts = detect_bursts(timestamps, target_cadence_s=15, threshold_pct=50.0)
        report = build_report(timestamps, bursts, 15, 50.0)
        assert report.total_bursts == 0
        assert report.verdict == "clean"


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_exact_threshold_boundary(self):
        """Intervals exactly at the threshold should NOT be flagged."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # 50% of 15 = 7.5s threshold; use exactly 7.5s intervals
        times = _burst_times(base, 5, 7.5)
        bursts = detect_bursts(times, target_cadence_s=15, threshold_pct=50.0)
        assert bursts == []

    def test_just_below_threshold(self):
        """Intervals just below the threshold should be flagged."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = _burst_times(base, 5, 7.4)
        bursts = detect_bursts(times, target_cadence_s=15, threshold_pct=50.0)
        assert len(bursts) == 1

    def test_large_gap_between_strokes(self):
        """Very large gaps should never be flagged as bursts."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = [base + timedelta(hours=i) for i in range(10)]
        bursts = detect_bursts(times, target_cadence_s=15, threshold_pct=50.0)
        assert bursts == []
