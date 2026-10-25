#!/usr/bin/env python3
"""Tests for iamai/gap_anatomy.py — dissect writer silence gaps.

Gaps are inevitable.  What matters is whether we understand them.
These tests ensure that gap discovery, severity classification,
recovery analysis, and reporting all behave correctly across the
full range of inputs.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from iamai.gap_anatomy import (
    classify_gap,
    classify_recovery,
    find_gaps,
    gap_report,
    gap_summary,
    _missed_strokes,
    _load_timestamps,
    _empty_gap,
    SEVERITY_TRIVIAL,
    SEVERITY_NOTABLE,
    SEVERITY_SIGNIFICANT,
    SEVERITY_SEVERE,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ts(offset_seconds: int, base: str = "2026-10-20T00:00:00+00:00") -> str:
    """ISO timestamp offset by N seconds from base."""
    base_dt = datetime.fromisoformat(base)
    return (base_dt + timedelta(seconds=offset_seconds)).isoformat()


def _write_strokes(tmp_path: Path, offsets: list[int]) -> Path:
    """Write a strokes.jsonl with strokes at given second offsets."""
    path = tmp_path / "strokes.jsonl"
    lines = []
    for i, off in enumerate(offsets, start=1):
        record = {
            "seq": i,
            "at": _ts(off),
            "kind": "thought",
            "text": f"stroke {i}",
        }
        lines.append(json.dumps(record))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# classify_gap
# ---------------------------------------------------------------------------


class TestClassifyGap:
    def test_trivial_at_lower_bound(self):
        # 2x cadence exactly → trivial
        assert classify_gap(30, 15) == "trivial"

    def test_trivial_just_below_notable(self):
        # 4.9x cadence → trivial
        assert classify_gap(73, 15) == "trivial"

    def test_notable_at_boundary(self):
        # 5x cadence → notable
        assert classify_gap(75, 15) == "notable"

    def test_notable_just_below_significant(self):
        # 19.9x cadence → notable
        assert classify_gap(298, 15) == "notable"

    def test_significant_at_boundary(self):
        # 20x cadence → significant
        assert classify_gap(300, 15) == "significant"

    def test_significant_just_below_severe(self):
        # 99x cadence → significant
        assert classify_gap(1485, 15) == "significant"

    def test_severe_at_boundary(self):
        # 100x cadence → severe
        assert classify_gap(1500, 15) == "severe"

    def test_severe_large_gap(self):
        # 4 hours with 15s cadence → severe
        assert classify_gap(14400, 15) == "severe"

    def test_zero_cadence_returns_severe(self):
        # Edge case: cadence=0 means something is very wrong
        assert classify_gap(100, 0) == "severe"

    def test_very_short_gap_is_trivial(self):
        assert classify_gap(31, 15) == "trivial"


# ---------------------------------------------------------------------------
# classify_recovery
# ---------------------------------------------------------------------------


class TestClassifyRecovery:
    def test_never_when_empty(self):
        assert classify_recovery([], 15) == "never"

    def test_instant_single_interval_within_tolerance(self):
        assert classify_recovery([20], 15) == "instant"

    def test_gradual_single_interval_beyond_tolerance(self):
        assert classify_recovery([45], 15) == "gradual"

    def test_instant_first_interval_good(self):
        # First interval is 25 (within 2x=30), rest don't matter
        assert classify_recovery([25, 15, 16, 14], 15) == "instant"

    def test_gradual_converging(self):
        # First interval bad (60s), then converging toward 15
        intervals = [60, 40, 25, 18, 16]
        result = classify_recovery(intervals, 15)
        assert result in ("gradual", "stuttering")

    def test_stuttering_high_variance(self):
        # Alternating fast/slow — high variance
        intervals = [60, 10, 55, 12, 50]
        result = classify_recovery(intervals, 15)
        assert result == "stuttering"

    def test_all_normal_intervals(self):
        intervals = [15, 16, 14, 15, 16]
        assert classify_recovery(intervals, 15) == "instant"


# ---------------------------------------------------------------------------
# _missed_strokes
# ---------------------------------------------------------------------------


class TestMissedStrokes:
    def test_basic(self):
        # 300s gap / 15s cadence = 20 expected, minus 1 = 19 missed
        assert _missed_strokes(300, 15) == 19

    def test_short_gap(self):
        # 30s / 15s = 2 expected, minus 1 = 1
        assert _missed_strokes(30, 15) == 1

    def test_zero_duration(self):
        assert _missed_strokes(0, 15) == 0

    def test_zero_cadence(self):
        assert _missed_strokes(300, 0) == 0

    def test_exact_one_cadence(self):
        # 15s / 15s = 1, minus 1 = 0
        assert _missed_strokes(15, 15) == 0


# ---------------------------------------------------------------------------
# _load_timestamps
# ---------------------------------------------------------------------------


class TestLoadTimestamps:
    def test_valid_file(self, tmp_path):
        path = _write_strokes(tmp_path, [0, 15, 30])
        ts = _load_timestamps(path)
        assert len(ts) == 3

    def test_missing_file(self, tmp_path):
        ts = _load_timestamps(tmp_path / "nonexistent.jsonl")
        assert ts == []

    def test_malformed_lines_skipped(self, tmp_path):
        path = tmp_path / "strokes.jsonl"
        path.write_text(
            '{"seq":1,"at":"2026-10-20T00:00:00+00:00","kind":"thought","text":"ok"}\n'
            'this is not json\n'
            '{"seq":2,"at":"2026-10-20T00:00:15+00:00","kind":"thought","text":"ok"}\n'
            '{"seq":3,"at":"","kind":"thought","text":"no ts"}\n',
            encoding="utf-8",
        )
        ts = _load_timestamps(path)
        assert len(ts) == 2

    def test_empty_file(self, tmp_path):
        path = tmp_path / "strokes.jsonl"
        path.write_text("", encoding="utf-8")
        ts = _load_timestamps(path)
        assert ts == []

    def test_naive_timestamps_get_utc(self, tmp_path):
        path = tmp_path / "strokes.jsonl"
        path.write_text(
            '{"seq":1,"at":"2026-10-20T00:00:00","kind":"thought","text":"naive"}\n',
            encoding="utf-8",
        )
        ts = _load_timestamps(path)
        assert len(ts) == 1
        assert ts[0].tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# find_gaps
# ---------------------------------------------------------------------------


class TestFindGaps:
    def test_no_gaps_in_regular_cadence(self, tmp_path):
        # Every stroke at exactly 15s intervals — no gaps
        path = _write_strokes(tmp_path, [0, 15, 30, 45, 60])
        gaps = find_gaps(path, cadence=15)
        assert gaps == []

    def test_single_notable_gap(self, tmp_path):
        # Normal, then 90s gap (6x cadence → notable), then normal
        path = _write_strokes(tmp_path, [0, 15, 30, 120, 135, 150])
        gaps = find_gaps(path, cadence=15)
        assert len(gaps) == 1
        assert gaps[0]["severity"] == "notable"
        assert gaps[0]["duration_seconds"] == 90.0

    def test_multiple_gaps(self, tmp_path):
        # Two gaps of different severity
        offsets = [
            0, 15, 30,        # normal
            120,              # 90s gap → notable
            135, 150,         # normal
            600,              # 450s gap → significant
            615, 630,         # normal
        ]
        path = _write_strokes(tmp_path, offsets)
        gaps = find_gaps(path, cadence=15)
        assert len(gaps) == 2
        assert gaps[0]["severity"] == "notable"
        assert gaps[1]["severity"] == "significant"

    def test_severe_gap(self, tmp_path):
        # 4-hour gap
        offsets = [0, 15, 14400, 14415]
        path = _write_strokes(tmp_path, offsets)
        gaps = find_gaps(path, cadence=15)
        assert len(gaps) == 1
        assert gaps[0]["severity"] == "severe"
        assert gaps[0]["missed_strokes"] > 900

    def test_min_multiplier_filter(self, tmp_path):
        # 40s gap with cadence 15 = 2.67x
        offsets = [0, 15, 55, 70]
        path = _write_strokes(tmp_path, offsets)

        # Default min_multiplier=2.0 → catches it
        gaps_default = find_gaps(path, cadence=15, min_multiplier=2.0)
        assert len(gaps_default) == 1

        # Higher threshold → filters it out
        gaps_high = find_gaps(path, cadence=15, min_multiplier=5.0)
        assert len(gaps_high) == 0

    def test_empty_file(self, tmp_path):
        path = tmp_path / "strokes.jsonl"
        path.write_text("", encoding="utf-8")
        gaps = find_gaps(path, cadence=15)
        assert gaps == []

    def test_single_stroke(self, tmp_path):
        path = _write_strokes(tmp_path, [0])
        gaps = find_gaps(path, cadence=15)
        assert gaps == []

    def test_recovery_analysis_with_post_gap_strokes(self, tmp_path):
        # Gap followed by enough strokes for recovery analysis
        offsets = [0, 15, 30, 120, 135, 150, 165, 180, 195]
        path = _write_strokes(tmp_path, offsets)
        gaps = find_gaps(path, cadence=15)
        assert len(gaps) == 1
        assert gaps[0]["recovery"] in (
            "instant", "gradual", "stuttering", "never"
        )

    def test_recovery_never_when_gap_at_end(self, tmp_path):
        # Gap is at the end — no post-gap strokes
        offsets = [0, 15, 30, 120]
        path = _write_strokes(tmp_path, offsets)
        gaps = find_gaps(path, cadence=15)
        assert len(gaps) == 1
        assert gaps[0]["recovery"] == "never"

    def test_gap_dict_has_all_keys(self, tmp_path):
        offsets = [0, 15, 120, 135]
        path = _write_strokes(tmp_path, offsets)
        gaps = find_gaps(path, cadence=15)
        assert len(gaps) == 1
        g = gaps[0]
        assert "start" in g
        assert "end" in g
        assert "duration_seconds" in g
        assert "severity" in g
        assert "missed_strokes" in g
        assert "recovery" in g


# ---------------------------------------------------------------------------
# gap_report
# ---------------------------------------------------------------------------


class TestGapReport:
    def test_basic_format(self):
        gap = {
            "start": "2026-10-20T03:00:00+00:00",
            "end": "2026-10-20T03:05:30+00:00",
            "duration_seconds": 330.0,
            "severity": "notable",
            "missed_strokes": 21,
            "recovery": "instant",
        }
        report = gap_report(gap)
        assert "notable" in report
        assert "330" in report
        assert "21" in report
        assert "instant" in report

    def test_severe_gap(self):
        gap = {
            "start": "2026-10-20T00:00:00+00:00",
            "end": "2026-10-20T04:00:00+00:00",
            "duration_seconds": 14400.0,
            "severity": "severe",
            "missed_strokes": 959,
            "recovery": "gradual",
        }
        report = gap_report(gap)
        assert "severe" in report
        assert "959" in report

    def test_trivial_gap(self):
        gap = {
            "start": "2026-10-20T12:00:00+00:00",
            "end": "2026-10-20T12:00:35+00:00",
            "duration_seconds": 35.0,
            "severity": "trivial",
            "missed_strokes": 1,
            "recovery": "instant",
        }
        report = gap_report(gap)
        assert "trivial" in report


# ---------------------------------------------------------------------------
# gap_summary
# ---------------------------------------------------------------------------


class TestGapSummary:
    def test_empty_list(self):
        assert gap_summary([]) == "no gaps found"

    def test_single_gap(self):
        gaps = [{
            "start": "2026-10-20T00:00:00+00:00",
            "end": "2026-10-20T00:01:30+00:00",
            "duration_seconds": 90.0,
            "severity": "notable",
            "missed_strokes": 5,
            "recovery": "instant",
        }]
        summary = gap_summary(gaps)
        assert "1 gaps" in summary
        assert "notable" in summary
        assert "5" in summary

    def test_mixed_severities(self):
        gaps = [
            {
                "start": "2026-10-20T00:00:00+00:00",
                "end": "2026-10-20T00:01:00+00:00",
                "duration_seconds": 60.0,
                "severity": "notable",
                "missed_strokes": 3,
                "recovery": "instant",
            },
            {
                "start": "2026-10-20T01:00:00+00:00",
                "end": "2026-10-20T01:00:30+00:00",
                "duration_seconds": 30.0,
                "severity": "trivial",
                "missed_strokes": 1,
                "recovery": "instant",
            },
            {
                "start": "2026-10-20T02:00:00+00:00",
                "end": "2026-10-20T06:00:00+00:00",
                "duration_seconds": 14400.0,
                "severity": "severe",
                "missed_strokes": 959,
                "recovery": "gradual",
            },
        ]
        summary = gap_summary(gaps)
        assert "3 gaps" in summary
        assert "trivial" in summary
        assert "notable" in summary
        assert "severe" in summary
        assert "963" in summary  # 3 + 1 + 959

    def test_only_zero_severity_tiers_omitted(self):
        # Only notable gaps — "trivial", "significant", "severe" should not appear
        gaps = [{
            "start": "2026-10-20T00:00:00+00:00",
            "end": "2026-10-20T00:01:30+00:00",
            "duration_seconds": 90.0,
            "severity": "notable",
            "missed_strokes": 5,
            "recovery": "instant",
        }]
        summary = gap_summary(gaps)
        assert "trivial" not in summary
        assert "significant" not in summary
        assert "severe" not in summary


# ---------------------------------------------------------------------------
# _empty_gap
# ---------------------------------------------------------------------------


class TestEmptyGap:
    def test_has_all_keys(self):
        g = _empty_gap()
        assert "start" in g
        assert "end" in g
        assert "duration_seconds" in g
        assert "severity" in g
        assert "missed_strokes" in g
        assert "recovery" in g

    def test_default_values(self):
        g = _empty_gap()
        assert g["severity"] == "trivial"
        assert g["missed_strokes"] == 0
        assert g["recovery"] == "instant"


# ---------------------------------------------------------------------------
# integration: end-to-end with realistic data
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_realistic_stroke_log(self, tmp_path):
        """Simulate a realistic stroke log with multiple gap types."""
        offsets = []
        t = 0
        # Normal cadence: 15s for 10 strokes
        for _ in range(10):
            offsets.append(t)
            t += 15

        # Trivial gap: 35s (commit boundary)
        t += 35
        offsets.append(t)

        # Back to normal
        for _ in range(5):
            t += 15
            offsets.append(t)

        # Notable gap: 120s
        t += 120
        offsets.append(t)

        # Gradual recovery (slightly irregular)
        t += 20
        offsets.append(t)
        t += 18
        offsets.append(t)
        t += 16
        offsets.append(t)
        t += 15
        offsets.append(t)

        # Normal
        for _ in range(5):
            t += 15
            offsets.append(t)

        path = _write_strokes(tmp_path, offsets)
        gaps = find_gaps(path, cadence=15)

        # Should find at least the notable gap
        assert len(gaps) >= 1
        notable_gaps = [g for g in gaps if g["severity"] == "notable"]
        assert len(notable_gaps) >= 1

        # Summary should be meaningful
        summary = gap_summary(gaps)
        assert "gaps" in summary
        assert "missed" in summary
