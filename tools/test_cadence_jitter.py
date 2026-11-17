#!/usr/bin/env python3
"""Tests for cadence_jitter.py — stroke-interval variance analysis.

Covers:
    - Interval computation from timestamps
    - Jitter metric calculation (ratio, stddev, outliers)
    - Status classification (smooth / rough / erratic)
    - Edge cases (insufficient data, empty file, malformed lines)
    - CLI argument parsing and exit codes
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

# Allow importing tools/ modules
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cadence_jitter import (
    JitterResult,
    SMOOTH,
    ROUGH,
    ERRATIC,
    parse_stroke_times,
    compute_intervals,
    compute_jitter,
    analyze_jitter,
    format_human,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_strokes(times: list[datetime]) -> str:
    """Create strokes.jsonl content from a list of timestamps."""
    lines = []
    for i, t in enumerate(times):
        stroke = {
            "seq": i + 1,
            "at": t.isoformat(),
            "kind": "thought",
            "text": f"test stroke {i + 1}",
        }
        lines.append(json.dumps(stroke))
    return "\n".join(lines) + "\n"


def _regular_times(base: datetime, interval: float, count: int) -> list[datetime]:
    """Generate `count` timestamps spaced exactly `interval` seconds apart."""
    return [base + timedelta(seconds=i * interval) for i in range(count)]


def _jittery_times(base: datetime, count: int, seed: int = 42) -> list[datetime]:
    """Generate timestamps with pseudo-random jitter."""
    import random
    rng = random.Random(seed)
    times = [base]
    for _ in range(count - 1):
        # Normal distribution around 15s with stddev 5s
        gap = max(1.0, rng.gauss(15, 5))
        times.append(times[-1] + timedelta(seconds=gap))
    return times


def _write_tmp_strokes(content: str) -> Path:
    """Write stroke content to a temp file and return the path."""
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return Path(path)


# ---------------------------------------------------------------------------
# Tests: compute_intervals
# ---------------------------------------------------------------------------


class TestComputeIntervals:
    def test_empty_list(self):
        assert compute_intervals([]) == []

    def test_single_timestamp(self):
        t = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        assert compute_intervals(t) == []

    def test_two_timestamps(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = [base, base + timedelta(seconds=15)]
        intervals = compute_intervals(times)
        assert len(intervals) == 1
        assert intervals[0] == 15.0

    def test_regular_intervals(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = _regular_times(base, 15.0, 5)
        intervals = compute_intervals(times)
        assert len(intervals) == 4
        assert all(abs(i - 15.0) < 0.001 for i in intervals)

    def test_irregular_intervals(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = [
            base,
            base + timedelta(seconds=10),
            base + timedelta(seconds=30),  # 20s gap
            base + timedelta(seconds=35),  # 5s gap
        ]
        intervals = compute_intervals(times)
        assert intervals == [10.0, 20.0, 5.0]

    def test_subsecond_precision(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = [base, base + timedelta(seconds=15.7)]
        intervals = compute_intervals(times)
        assert abs(intervals[0] - 15.7) < 0.001


# ---------------------------------------------------------------------------
# Tests: compute_jitter
# ---------------------------------------------------------------------------


class TestComputeJitter:
    def test_perfectly_regular(self):
        intervals = [15.0, 15.0, 15.0, 15.0]
        result = compute_jitter(intervals, 15)
        assert result is not None
        assert result.jitter_ratio == 0.0
        assert result.stddev_interval == 0.0
        assert result.max_gap == 15.0
        assert result.min_gap == 15.0
        assert result.gap_spread == 0.0
        assert result.outlier_count == 0

    def test_high_jitter(self):
        # Mix of very short and very long intervals
        intervals = [5.0, 25.0, 5.0, 25.0, 5.0, 25.0]
        result = compute_jitter(intervals, 15)
        assert result is not None
        # stddev of [5,25,5,25,5,25] = 10, mean = 15, ratio = 10/15 ≈ 0.667
        assert result.jitter_ratio > 0.5
        assert result.gap_spread == 20.0

    def test_insufficient_intervals(self):
        assert compute_jitter([], 15) is None
        assert compute_jitter([15.0], 15) is None

    def test_minimum_valid(self):
        intervals = [14.0, 16.0]
        result = compute_jitter(intervals, 15)
        assert result is not None
        assert result.mean_interval == 15.0
        assert result.stddev_interval == 1.0

    def test_cadence_drift(self):
        intervals = [20.0, 20.0, 20.0]
        result = compute_jitter(intervals, 15)
        assert result is not None
        assert result.cadence_drift == 5.0

    def test_negative_drift(self):
        intervals = [10.0, 10.0, 10.0]
        result = compute_jitter(intervals, 15)
        assert result is not None
        assert result.cadence_drift == -5.0

    def test_outlier_detection(self):
        # 9 normal intervals + 1 extreme outlier
        intervals = [15.0] * 9 + [100.0]
        result = compute_jitter(intervals, 15)
        assert result is not None
        assert result.outlier_count >= 1

    def test_stroke_and_interval_count(self):
        intervals = [15.0, 15.0, 15.0]
        result = compute_jitter(intervals, 15)
        assert result is not None
        assert result.interval_count == 3
        assert result.stroke_count == 4


# ---------------------------------------------------------------------------
# Tests: analyze_jitter (full pipeline)
# ---------------------------------------------------------------------------


class TestAnalyzeJitter:
    def test_regular_strokes(self):
        base = datetime(2026, 11, 17, tzinfo=timezone.utc)
        times = _regular_times(base, 15.0, 20)
        content = _make_strokes(times)
        path = _write_tmp_strokes(content)
        try:
            result = analyze_jitter(strokes_file=path, tail=20, expected_cadence=15)
            assert result.status == SMOOTH
            assert result.jitter_ratio < 0.1
        finally:
            path.unlink()

    def test_jittery_strokes(self):
        base = datetime(2026, 11, 17, tzinfo=timezone.utc)
        times = _jittery_times(base, 50, seed=42)
        content = _make_strokes(times)
        path = _write_tmp_strokes(content)
        try:
            result = analyze_jitter(
                strokes_file=path, tail=50, expected_cadence=15, threshold=0.25
            )
            # With stddev=5 on mean=15, ratio should be ~0.27-0.33
            assert result.status in (ROUGH, ERRATIC)
        finally:
            path.unlink()

    def test_insufficient_data_empty_file(self):
        path = _write_tmp_strokes("")
        try:
            result = analyze_jitter(strokes_file=path)
            assert result.status == "insufficient_data"
            assert result.stroke_count == 0
        finally:
            path.unlink()

    def test_insufficient_data_two_strokes(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = _regular_times(base, 15.0, 2)
        content = _make_strokes(times)
        path = _write_tmp_strokes(content)
        try:
            result = analyze_jitter(strokes_file=path)
            assert result.status == "insufficient_data"
        finally:
            path.unlink()

    def test_nonexistent_file(self):
        result = analyze_jitter(strokes_file=Path("/nonexistent/strokes.jsonl"))
        assert result.status == "insufficient_data"

    def test_malformed_lines_skipped(self):
        lines = [
            '{"seq": 1, "at": "2026-01-01T00:00:00+00:00", "kind": "thought", "text": "a"}',
            "THIS IS NOT JSON",
            '{"seq": 2, "at": "2026-01-01T00:00:15+00:00", "kind": "thought", "text": "b"}',
            "",
            '{"seq": 3, "at": "2026-01-01T00:00:30+00:00", "kind": "thought", "text": "c"}',
            '{"missing_at": true}',
            '{"seq": 4, "at": "2026-01-01T00:00:45+00:00", "kind": "thought", "text": "d"}',
        ]
        content = "\n".join(lines) + "\n"
        path = _write_tmp_strokes(content)
        try:
            result = analyze_jitter(strokes_file=path, expected_cadence=15)
            # 4 valid strokes = 3 intervals = enough for analysis
            assert result.status in (SMOOTH, ROUGH, ERRATIC)
            assert result.stroke_count == 4
        finally:
            path.unlink()

    def test_tail_limits_analysis_window(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = _regular_times(base, 15.0, 200)
        content = _make_strokes(times)
        path = _write_tmp_strokes(content)
        try:
            result = analyze_jitter(strokes_file=path, tail=10, expected_cadence=15)
            assert result.stroke_count == 10
        finally:
            path.unlink()

    def test_custom_threshold(self):
        base = datetime(2026, 11, 17, tzinfo=timezone.utc)
        times = _jittery_times(base, 30, seed=99)
        content = _make_strokes(times)
        path = _write_tmp_strokes(content)
        try:
            # Very high threshold — should be smooth even with jitter
            result_high = analyze_jitter(
                strokes_file=path, tail=30, expected_cadence=15, threshold=5.0
            )
            assert result_high.status in (SMOOTH, ROUGH)

            # Very low threshold — should be erratic
            result_low = analyze_jitter(
                strokes_file=path, tail=30, expected_cadence=15, threshold=0.01
            )
            assert result_low.status == ERRATIC
        finally:
            path.unlink()


# ---------------------------------------------------------------------------
# Tests: parse_stroke_times
# ---------------------------------------------------------------------------


class TestParseStrokeTimes:
    def test_valid_file(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = _regular_times(base, 15.0, 5)
        content = _make_strokes(times)
        path = _write_tmp_strokes(content)
        try:
            parsed = parse_stroke_times(path, tail=10)
            assert len(parsed) == 5
        finally:
            path.unlink()

    def test_nonexistent(self):
        result = parse_stroke_times(Path("/no/such/file.jsonl"))
        assert result == []

    def test_tail_respects_limit(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = _regular_times(base, 15.0, 20)
        content = _make_strokes(times)
        path = _write_tmp_strokes(content)
        try:
            parsed = parse_stroke_times(path, tail=5)
            assert len(parsed) == 5
        finally:
            path.unlink()

    def test_z_suffix_handling(self):
        content = (
            '{"seq": 1, "at": "2026-01-01T00:00:00Z", "kind": "thought", "text": "z"}\n'
            '{"seq": 2, "at": "2026-01-01T00:00:15Z", "kind": "thought", "text": "z2"}\n'
        )
        path = _write_tmp_strokes(content)
        try:
            parsed = parse_stroke_times(path)
            assert len(parsed) == 2
        finally:
            path.unlink()

    def test_sorted_output(self):
        # Strokes written out of order
        content = (
            '{"seq": 3, "at": "2026-01-01T00:00:30+00:00", "kind": "thought", "text": "c"}\n'
            '{"seq": 1, "at": "2026-01-01T00:00:00+00:00", "kind": "thought", "text": "a"}\n'
            '{"seq": 2, "at": "2026-01-01T00:00:15+00:00", "kind": "thought", "text": "b"}\n'
        )
        path = _write_tmp_strokes(content)
        try:
            parsed = parse_stroke_times(path)
            assert len(parsed) == 3
            assert parsed[0] < parsed[1] < parsed[2]
        finally:
            path.unlink()


# ---------------------------------------------------------------------------
# Tests: format_human
# ---------------------------------------------------------------------------


class TestFormatHuman:
    def test_insufficient_data_message(self):
        result = JitterResult(
            status="insufficient_data",
            jitter_ratio=0.0,
            mean_interval=0.0,
            stddev_interval=0.0,
            max_gap=0.0,
            min_gap=0.0,
            gap_spread=0.0,
            outlier_count=0,
            stroke_count=1,
            interval_count=0,
            expected_cadence=15,
            cadence_drift=0.0,
        )
        text = format_human(result)
        assert "insufficient data" in text
        assert "1 strokes" in text

    def test_normal_output_contains_key_fields(self):
        result = JitterResult(
            status=SMOOTH,
            jitter_ratio=0.05,
            mean_interval=15.2,
            stddev_interval=0.76,
            max_gap=16.5,
            min_gap=14.1,
            gap_spread=2.4,
            outlier_count=0,
            stroke_count=100,
            interval_count=99,
            expected_cadence=15,
            cadence_drift=0.2,
        )
        text = format_human(result)
        assert "smooth" in text
        assert "jitter_ratio" in text
        assert "mean_interval" in text
        assert "outliers" in text


# ---------------------------------------------------------------------------
# Tests: CLI
# ---------------------------------------------------------------------------


class TestCLI:
    def test_json_output(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = _regular_times(base, 15.0, 10)
        content = _make_strokes(times)
        path = _write_tmp_strokes(content)
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parent / "cadence_jitter.py"),
                    "--strokes-file",
                    str(path),
                    "--json",
                    "--tail",
                    "10",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            data = json.loads(result.stdout)
            assert data["status"] == SMOOTH
            assert data["stroke_count"] == 10
        finally:
            path.unlink()

    def test_insufficient_data_exit_code(self):
        path = _write_tmp_strokes("")
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parent / "cadence_jitter.py"),
                    "--strokes-file",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert result.returncode == 2
        finally:
            path.unlink()

    def test_smooth_exit_code(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        times = _regular_times(base, 15.0, 10)
        content = _make_strokes(times)
        path = _write_tmp_strokes(content)
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).parent / "cadence_jitter.py"),
                    "--strokes-file",
                    str(path),
                    "--tail",
                    "10",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert result.returncode == 0
        finally:
            path.unlink()
