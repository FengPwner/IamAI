#!/usr/bin/env python3
"""Tests for overnight_coverage_map.py"""

import json
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from overnight_coverage_map import (
    parse_iso,
    load_strokes,
    detect_gaps,
    aggregate_hourly,
    compute_coverage,
    render_heatmap,
    build_map,
)


# ---------------------------------------------------------------------------
# parse_iso
# ---------------------------------------------------------------------------

class TestParseIso:
    def test_z_suffix(self):
        dt = parse_iso("2026-11-04T03:00:00Z")
        assert dt is not None
        assert dt.hour == 3
        assert dt.tzinfo == timezone.utc

    def test_offset(self):
        dt = parse_iso("2026-11-04T11:00:00+08:00")
        assert dt is not None
        assert dt.hour == 11

    def test_naive_assumed_utc(self):
        dt = parse_iso("2026-11-04T03:00:00")
        assert dt is not None
        assert dt.tzinfo == timezone.utc

    def test_empty(self):
        assert parse_iso("") is None
        assert parse_iso(None) is None

    def test_invalid(self):
        assert parse_iso("not-a-date") is None
        assert parse_iso("2026-13-45") is None

    def test_whitespace(self):
        dt = parse_iso("  2026-11-04T03:00:00Z  ")
        assert dt is not None
        assert dt.hour == 3


# ---------------------------------------------------------------------------
# load_strokes
# ---------------------------------------------------------------------------

class TestLoadStrokes:
    def test_missing_file(self):
        result = load_strokes("/nonexistent/path.jsonl")
        assert result == []

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("")
            path = f.name
        result = load_strokes(path)
        assert result == []
        Path(path).unlink()

    def test_valid_strokes(self):
        lines = [
            json.dumps({"seq": 1, "at": "2026-11-04T01:00:00Z", "kind": "thought", "text": "a"}),
            json.dumps({"seq": 2, "at": "2026-11-04T02:00:00Z", "kind": "thought", "text": "b"}),
            json.dumps({"seq": 3, "at": "2026-11-04T03:00:00Z", "kind": "thought", "text": "c"}),
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("\n".join(lines))
            path = f.name
        result = load_strokes(path)
        assert len(result) == 3
        assert result[0]["seq"] == 1
        assert result[2]["seq"] == 3
        Path(path).unlink()

    def test_malformed_lines_skipped(self):
        lines = [
            json.dumps({"seq": 1, "at": "2026-11-04T01:00:00Z", "kind": "thought", "text": "a"}),
            "not valid json {{{",
            json.dumps({"seq": 3, "at": "2026-11-04T03:00:00Z", "kind": "thought", "text": "c"}),
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("\n".join(lines))
            path = f.name
        result = load_strokes(path)
        assert len(result) == 2
        Path(path).unlink()

    def test_since_filter(self):
        lines = [
            json.dumps({"seq": 1, "at": "2026-11-01T01:00:00Z", "kind": "thought", "text": "old"}),
            json.dumps({"seq": 2, "at": "2026-11-03T01:00:00Z", "kind": "thought", "text": "new"}),
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("\n".join(lines))
            path = f.name
        since = datetime(2026, 11, 2, tzinfo=timezone.utc)
        result = load_strokes(path, since=since)
        assert len(result) == 1
        assert result[0]["seq"] == 2
        Path(path).unlink()

    def test_sorted_by_time(self):
        lines = [
            json.dumps({"seq": 3, "at": "2026-11-04T03:00:00Z", "kind": "thought", "text": "c"}),
            json.dumps({"seq": 1, "at": "2026-11-04T01:00:00Z", "kind": "thought", "text": "a"}),
            json.dumps({"seq": 2, "at": "2026-11-04T02:00:00Z", "kind": "thought", "text": "b"}),
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("\n".join(lines))
            path = f.name
        result = load_strokes(path)
        assert result[0]["seq"] == 1
        assert result[1]["seq"] == 2
        assert result[2]["seq"] == 3
        Path(path).unlink()


# ---------------------------------------------------------------------------
# detect_gaps
# ---------------------------------------------------------------------------

class TestDetectGaps:
    def _strokes(self, timestamps):
        return [{"_ts": parse_iso(t), "seq": i} for i, t in enumerate(timestamps)]

    def test_no_gaps(self):
        strokes = self._strokes([
            "2026-11-04T01:00:00Z",
            "2026-11-04T01:00:15Z",
            "2026-11-04T01:00:30Z",
        ])
        gaps = detect_gaps(strokes, cadence_seconds=15, min_gap_multiplier=2.0)
        assert len(gaps) == 0

    def test_single_gap(self):
        strokes = self._strokes([
            "2026-11-04T01:00:00Z",
            "2026-11-04T01:00:15Z",
            "2026-11-04T02:00:00Z",  # ~60 min gap
        ])
        gaps = detect_gaps(strokes, cadence_seconds=15, min_gap_multiplier=2.0)
        assert len(gaps) == 1
        assert gaps[0]["gap_seconds"] > 3500
        assert gaps[0]["hour"] == 1

    def test_multiple_gaps(self):
        strokes = self._strokes([
            "2026-11-04T01:00:00Z",
            "2026-11-04T02:00:00Z",  # 1h gap at hour 1
            "2026-11-04T02:00:15Z",
            "2026-11-04T05:00:00Z",  # 3h gap at hour 2
        ])
        gaps = detect_gaps(strokes, cadence_seconds=15, min_gap_multiplier=2.0)
        assert len(gaps) == 2
        assert gaps[0]["hour"] == 1
        assert gaps[1]["hour"] == 2

    def test_gap_at_threshold(self):
        """Gap exactly at threshold should be included."""
        strokes = self._strokes([
            "2026-11-04T01:00:00Z",
            "2026-11-04T01:00:30Z",  # exactly 2x cadence (15*2=30s)
        ])
        gaps = detect_gaps(strokes, cadence_seconds=15, min_gap_multiplier=2.0)
        assert len(gaps) == 1

    def test_below_threshold_excluded(self):
        strokes = self._strokes([
            "2026-11-04T01:00:00Z",
            "2026-11-04T01:00:29Z",  # 29s < 30s threshold
        ])
        gaps = detect_gaps(strokes, cadence_seconds=15, min_gap_multiplier=2.0)
        assert len(gaps) == 0

    def test_single_stroke(self):
        strokes = self._strokes(["2026-11-04T01:00:00Z"])
        gaps = detect_gaps(strokes, cadence_seconds=15)
        assert len(gaps) == 0

    def test_empty(self):
        gaps = detect_gaps([], cadence_seconds=15)
        assert len(gaps) == 0


# ---------------------------------------------------------------------------
# aggregate_hourly
# ---------------------------------------------------------------------------

class TestAggregateHourly:
    def test_empty_gaps(self):
        result = aggregate_hourly([])
        assert len(result) == 24
        for h in range(24):
            assert result[h]["count"] == 0
            assert result[h]["total_seconds"] == 0.0

    def test_single_gap(self):
        gaps = [{
            "last_ts": parse_iso("2026-11-04T03:10:00Z"),
            "next_ts": parse_iso("2026-11-04T04:10:00Z"),
            "gap_seconds": 3600.0,
            "hour": 3,
        }]
        result = aggregate_hourly(gaps)
        assert result[3]["count"] == 1
        assert result[3]["total_seconds"] == 3600.0
        assert result[3]["max_seconds"] == 3600.0
        assert result[3]["avg_seconds"] == 3600.0
        assert result[4]["count"] == 0

    def test_multiple_gaps_same_hour(self):
        gaps = [
            {"hour": 3, "gap_seconds": 1800.0, "last_ts": None, "next_ts": None},
            {"hour": 3, "gap_seconds": 3600.0, "last_ts": None, "next_ts": None},
        ]
        result = aggregate_hourly(gaps)
        assert result[3]["count"] == 2
        assert result[3]["total_seconds"] == 5400.0
        assert result[3]["max_seconds"] == 3600.0
        assert result[3]["avg_seconds"] == 2700.0

    def test_gaps_across_hours(self):
        gaps = [
            {"hour": 2, "gap_seconds": 600.0, "last_ts": None, "next_ts": None},
            {"hour": 14, "gap_seconds": 1200.0, "last_ts": None, "next_ts": None},
        ]
        result = aggregate_hourly(gaps)
        assert result[2]["count"] == 1
        assert result[14]["count"] == 1
        assert result[8]["count"] == 0


# ---------------------------------------------------------------------------
# compute_coverage
# ---------------------------------------------------------------------------

class TestComputeCoverage:
    def test_no_gaps_full_coverage(self):
        hourly = {h: {"count": 0, "total_seconds": 0.0, "max_seconds": 0.0, "avg_seconds": 0.0}
                  for h in range(24)}
        cov = compute_coverage(hourly)
        for h in range(24):
            assert cov[h] == 1.0

    def test_half_coverage(self):
        hourly = {h: {"count": 0, "total_seconds": 0.0, "max_seconds": 0.0, "avg_seconds": 0.0}
                  for h in range(24)}
        hourly[3] = {"count": 1, "total_seconds": 1800.0, "max_seconds": 1800.0, "avg_seconds": 1800.0}
        cov = compute_coverage(hourly)
        assert cov[3] == 0.5
        assert cov[0] == 1.0

    def test_clamped_to_zero(self):
        """Coverage should not go below 0 even if gap exceeds wall clock."""
        hourly = {h: {"count": 0, "total_seconds": 0.0, "max_seconds": 0.0, "avg_seconds": 0.0}
                  for h in range(24)}
        hourly[5] = {"count": 3, "total_seconds": 7200.0, "max_seconds": 3600.0, "avg_seconds": 2400.0}
        cov = compute_coverage(hourly)
        assert cov[5] == 0.0

    def test_custom_wall_seconds(self):
        hourly = {h: {"count": 0, "total_seconds": 0.0, "max_seconds": 0.0, "avg_seconds": 0.0}
                  for h in range(24)}
        hourly[10] = {"count": 1, "total_seconds": 500.0, "max_seconds": 500.0, "avg_seconds": 500.0}
        cov = compute_coverage(hourly, wall_seconds_per_hour=1000.0)
        assert cov[10] == 0.5


# ---------------------------------------------------------------------------
# render_heatmap
# ---------------------------------------------------------------------------

class TestRenderHeatmap:
    def test_basic_render(self):
        hourly = {h: {"count": 0, "total_seconds": 0.0, "max_seconds": 0.0, "avg_seconds": 0.0}
                  for h in range(24)}
        cov = {h: 1.0 for h in range(24)}
        output = render_heatmap(hourly, cov)
        assert "Hour" in output
        assert "100.0%" in output
        assert "█" in output

    def test_zero_coverage(self):
        hourly = {h: {"count": 0, "total_seconds": 0.0, "max_seconds": 0.0, "avg_seconds": 0.0}
                  for h in range(24)}
        cov = {h: 0.0 for h in range(24)}
        output = render_heatmap(hourly, cov)
        assert "0.0%" in output
        assert "░" * 20 in output

    def test_line_count(self):
        hourly = {h: {"count": 0, "total_seconds": 0.0, "max_seconds": 0.0, "avg_seconds": 0.0}
                  for h in range(24)}
        cov = {h: 1.0 for h in range(24)}
        output = render_heatmap(hourly, cov)
        # header + separator + 24 hour rows = 26 lines
        assert len(output.strip().split("\n")) == 26


# ---------------------------------------------------------------------------
# build_map (integration)
# ---------------------------------------------------------------------------

class TestBuildMap:
    def test_too_few_strokes(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"seq": 1, "at": "2026-11-04T01:00:00Z", "kind": "t", "text": "x"}))
            path = f.name
        result = build_map(strokes_path=path)
        assert result["strokes_loaded"] == 1
        assert result["gaps_detected"] == 0
        Path(path).unlink()

    def test_with_gaps(self):
        strokes = [
            {"seq": 1, "at": "2026-11-04T01:00:00Z", "kind": "thought", "text": "a"},
            {"seq": 2, "at": "2026-11-04T01:00:15Z", "kind": "thought", "text": "b"},
            {"seq": 3, "at": "2026-11-04T03:00:00Z", "kind": "thought", "text": "c"},  # 2h gap
            {"seq": 4, "at": "2026-11-04T03:00:15Z", "kind": "thought", "text": "d"},
            {"seq": 5, "at": "2026-11-04T06:00:00Z", "kind": "thought", "text": "e"},  # 3h gap
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")
            path = f.name
        result = build_map(strokes_path=path, cadence=15, min_gap_multiplier=2.0)
        assert result["strokes_loaded"] == 5
        assert result["gaps_detected"] == 2
        # worst hour should be 3 (3h gap) or 1 (2h gap)
        assert result["worst_hour"] in [1, 3]
        Path(path).unlink()

    def test_missing_file(self):
        result = build_map(strokes_path="/nonexistent/file.jsonl")
        assert result["strokes_loaded"] == 0


# ---------------------------------------------------------------------------
# Run with pytest
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
