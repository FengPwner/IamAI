#!/usr/bin/env python3
"""Tests for restart_settling_monitor.py — post-restart cadence settling analysis.

Covers:
    - Stroke timestamp parsing from strokes.jsonl
    - Restart gap detection
    - Settling measurement (rolling window cadence normalisation)
    - Aggregate report generation
    - Edge cases (insufficient data, no restarts, malformed lines)
    - CLI argument parsing and exit codes
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from restart_settling_monitor import (
    SettlingEvent,
    SettlingReport,
    SETTLED,
    UNSETTLED,
    NO_RESTART,
    NO_DATA,
    parse_stroke_times,
    detect_restart_gaps,
    measure_settling,
    analyze,
    format_human,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(seconds_offset: float) -> str:
    """Return an ISO timestamp offset from epoch by the given seconds."""
    base = datetime(2026, 11, 22, 0, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(seconds=seconds_offset)).isoformat()


def _make_strokes(offsets: list[float]) -> str:
    """Create strokes.jsonl content from a list of second-offsets."""
    lines = []
    for i, off in enumerate(offsets):
        stroke = {
            "seq": i + 1,
            "at": _ts(off),
            "kind": "thought",
            "text": f"stroke {i + 1}",
        }
        lines.append(json.dumps(stroke))
    return "\n".join(lines) + "\n"


def _write_strokes_file(offsets: list[float], tmpdir: Path) -> Path:
    p = tmpdir / "strokes.jsonl"
    p.write_text(_make_strokes(offsets))
    return p


# ---------------------------------------------------------------------------
# parse_stroke_times
# ---------------------------------------------------------------------------

class TestParseStrokeTimes:
    def test_normal_file(self, tmp_path):
        offsets = [0, 15, 30, 45, 60]
        p = _write_strokes_file(offsets, tmp_path)
        times = parse_stroke_times(p)
        assert len(times) == 5
        assert all(isinstance(t, datetime) for t in times)

    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        assert parse_stroke_times(p) == []

    def test_missing_file(self, tmp_path):
        p = tmp_path / "nonexistent.jsonl"
        assert parse_stroke_times(p) == []

    def test_malformed_lines_skipped(self, tmp_path):
        content = (
            '{"seq":1,"at":"' + _ts(0) + '","kind":"thought","text":"ok"}\n'
            'NOT JSON\n'
            '{"seq":2,"at":"' + _ts(15) + '","kind":"thought","text":"ok"}\n'
            '{"broken\n'
            '{"seq":3,"at":"' + _ts(30) + '","kind":"thought","text":"ok"}\n'
        )
        p = tmp_path / "strokes.jsonl"
        p.write_text(content)
        times = parse_stroke_times(p)
        assert len(times) == 3

    def test_sorted_output(self, tmp_path):
        # Write timestamps out of order
        offsets = [60, 0, 30, 15, 45]
        p = _write_strokes_file(offsets, tmp_path)
        times = parse_stroke_times(p)
        for i in range(1, len(times)):
            assert times[i] >= times[i - 1]

    def test_timezone_naive_gets_utc(self, tmp_path):
        stroke = '{"seq":1,"at":"2026-11-22T00:00:00","kind":"thought","text":"x"}\n'
        p = tmp_path / "strokes.jsonl"
        p.write_text(stroke)
        times = parse_stroke_times(p)
        assert len(times) == 1
        assert times[0].tzinfo is not None


# ---------------------------------------------------------------------------
# detect_restart_gaps
# ---------------------------------------------------------------------------

class TestDetectRestartGaps:
    def _times(self, offsets):
        base = datetime(2026, 11, 22, tzinfo=timezone.utc)
        return [base + timedelta(seconds=o) for o in offsets]

    def test_no_gaps(self):
        times = self._times([0, 15, 30, 45, 60])
        assert detect_restart_gaps(times, gap_threshold=75) == []

    def test_single_gap(self):
        times = self._times([0, 15, 30, 200, 215, 230])
        gaps = detect_restart_gaps(times, gap_threshold=75)
        assert gaps == [3]

    def test_multiple_gaps(self):
        times = self._times([0, 15, 30, 200, 215, 400, 415])
        gaps = detect_restart_gaps(times, gap_threshold=75)
        assert gaps == [3, 5]

    def test_exact_threshold_not_included(self):
        # Gap of exactly 75 should be included (>= threshold)
        times = self._times([0, 75, 90])
        gaps = detect_restart_gaps(times, gap_threshold=75)
        assert gaps == [1]

    def test_just_below_threshold(self):
        times = self._times([0, 74, 90])
        gaps = detect_restart_gaps(times, gap_threshold=75)
        assert gaps == []

    def test_single_stroke(self):
        times = self._times([0])
        assert detect_restart_gaps(times, gap_threshold=75) == []

    def test_empty(self):
        assert detect_restart_gaps([], gap_threshold=75) == []


# ---------------------------------------------------------------------------
# measure_settling
# ---------------------------------------------------------------------------

class TestMeasureSettling:
    def _times(self, offsets):
        base = datetime(2026, 11, 22, tzinfo=timezone.utc)
        return [base + timedelta(seconds=o) for o in offsets]

    def test_fast_settle(self):
        # 100s gap, then regular 15s intervals
        offsets = [0, 15, 30, 130, 145, 160, 175, 190, 205, 220, 235, 250]
        times = self._times(offsets)
        ev = measure_settling(times, restart_idx=3, target_cadence=15.0,
                              tolerance=0.3, settle_window=20)
        assert ev.gap_seconds == 100.0
        assert ev.settled is True
        # Should settle after the first 5 intervals (all are 15s)
        assert ev.strokes_to_settle == 5

    def test_slow_settle(self):
        # 200s gap, then gradually normalising intervals:
        # 50, 40, 30, 25, 20, 17, 16, 15, 15, 15
        offsets = [0, 15]
        post = [50, 40, 30, 25, 20, 17, 16, 15, 15, 15]
        cur = offsets[-1]
        for iv in post:
            cur += iv
            offsets.append(cur)
        times = self._times(offsets)
        ev = measure_settling(times, restart_idx=1, target_cadence=15.0,
                              tolerance=0.3, settle_window=20)
        assert ev.settled is True
        # The rolling window of 5 needs all 5 values within [10.5, 19.5]
        # Window [20,17,16,15,15] avg=16.6 → within band → settles at stroke 7
        assert ev.strokes_to_settle >= 5

    def test_no_settle_within_window(self):
        # 200s gap, then wildly varying intervals
        offsets = [0, 15, 215, 280, 310, 400, 410, 500, 510, 600]
        times = self._times(offsets)
        ev = measure_settling(times, restart_idx=2, target_cadence=15.0,
                              tolerance=0.3, settle_window=6)
        assert ev.settled is False

    def test_no_post_data(self):
        # Restart at the last stroke
        offsets = [0, 15, 30, 200]
        times = self._times(offsets)
        ev = measure_settling(times, restart_idx=3, target_cadence=15.0,
                              tolerance=0.3, settle_window=20)
        assert ev.settled is False
        assert ev.strokes_to_settle == 0
        assert ev.seconds_to_settle == 0.0

    def test_gap_seconds_correct(self):
        offsets = [0, 15, 30, 500, 515, 530]
        times = self._times(offsets)
        ev = measure_settling(times, restart_idx=3, target_cadence=15.0,
                              tolerance=0.3, settle_window=10)
        assert ev.gap_seconds == 470.0

    def test_gap_end_iso(self):
        offsets = [0, 15, 30, 500, 515, 530]
        times = self._times(offsets)
        ev = measure_settling(times, restart_idx=3, target_cadence=15.0,
                              tolerance=0.3, settle_window=10)
        expected = times[3].isoformat()
        assert ev.gap_end_iso == expected


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------

class TestAnalyze:
    def _times(self, offsets):
        base = datetime(2026, 11, 22, tzinfo=timezone.utc)
        return [base + timedelta(seconds=o) for o in offsets]

    def test_no_data(self):
        times = self._times([0, 15])
        report = analyze(times, 15.0, 75.0, 0.3, 20)
        assert report.status == NO_DATA

    def test_no_restart(self):
        times = self._times([0, 15, 30, 45, 60, 75, 90])
        report = analyze(times, 15.0, 75.0, 0.3, 20)
        assert report.status == NO_RESTART
        assert report.total_restarts == 0

    def test_single_settled_restart(self):
        offsets = [0, 15, 30, 45, 200, 215, 230, 245, 260, 275, 290, 305, 320, 335]
        times = self._times(offsets)
        report = analyze(times, 15.0, 75.0, 0.3, 20)
        assert report.status == SETTLED
        assert report.total_restarts == 1
        assert report.settled_count == 1
        assert report.unsettled_count == 0

    def test_unsettled_restart(self):
        # After restart, intervals are consistently ~50s (never normalise to 15s)
        offsets = [0, 15, 30, 200, 250, 300, 350, 400, 450, 500]
        times = self._times(offsets)
        report = analyze(times, 15.0, 75.0, 0.3, 8)
        assert report.status == UNSETTLED
        assert report.unsettled_count >= 1

    def test_multiple_restarts_mixed(self):
        # First restart settles, second doesn't
        offsets = [
            0, 15, 30, 45,           # pre-restart-1
            200, 215, 230, 245, 260, 275, 290,  # post-restart-1 (settles)
            500,                       # gap → restart-2
            550, 600, 650, 700, 750, 800,  # post-restart-2 (50s intervals, never settles)
        ]
        times = self._times(offsets)
        report = analyze(times, 15.0, 75.0, 0.3, 6)
        assert report.total_restarts == 2
        assert report.settled_count == 1
        assert report.unsettled_count == 1
        assert report.status == UNSETTLED

    def test_median_and_max(self):
        # Two settled restarts with different settle times
        offsets = [
            0, 15, 30, 45,
            200, 215, 230, 245, 260, 275, 290,  # post-1: all 15s → settle at 5 strokes = 75s
            500,
            515, 530, 545, 560, 575, 590, 605,  # post-2: all 15s → settle at 5 strokes = 75s
        ]
        times = self._times(offsets)
        report = analyze(times, 15.0, 75.0, 0.3, 20)
        assert report.status == SETTLED
        assert report.median_settle_seconds is not None
        assert report.max_settle_seconds is not None
        assert report.max_settle_seconds >= report.median_settle_seconds

    def test_empty_times(self):
        report = analyze([], 15.0, 75.0, 0.3, 20)
        assert report.status == NO_DATA

    def test_target_cadence_preserved(self):
        times = self._times([0, 15, 30, 200, 215, 230, 245, 260, 275])
        report = analyze(times, 20.0, 75.0, 0.3, 20)
        assert report.target_cadence == 20.0


# ---------------------------------------------------------------------------
# format_human
# ---------------------------------------------------------------------------

class TestFormatHuman:
    def test_settled_output(self):
        ev = SettlingEvent(
            gap_seconds=120.0,
            gap_end_iso="2026-11-22T00:02:00+00:00",
            strokes_to_settle=5,
            seconds_to_settle=75.0,
            settled=True,
            post_gap_intervals=[15.0, 15.0, 15.0, 15.0, 15.0],
        )
        report = SettlingReport(
            status=SETTLED,
            target_cadence=15.0,
            events=[ev],
            total_restarts=1,
            settled_count=1,
            unsettled_count=0,
            median_settle_seconds=75.0,
            max_settle_seconds=75.0,
        )
        out = format_human(report)
        assert "settled" in out.lower()
        assert "15.0" in out
        assert "120" in out

    def test_no_restart_output(self):
        report = SettlingReport(
            status=NO_RESTART,
            target_cadence=15.0,
            events=[],
            total_restarts=0,
            settled_count=0,
            unsettled_count=0,
            median_settle_seconds=None,
            max_settle_seconds=None,
        )
        out = format_human(report)
        assert "no_restart" in out

    def test_no_data_output(self):
        report = SettlingReport(
            status=NO_DATA,
            target_cadence=15.0,
            events=[],
            total_restarts=0,
            settled_count=0,
            unsettled_count=0,
            median_settle_seconds=None,
            max_settle_seconds=None,
        )
        out = format_human(report)
        assert "no_data" in out


# ---------------------------------------------------------------------------
# CLI (main)
# ---------------------------------------------------------------------------

class TestMain:
    def test_no_data_exit(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        rc = main(["--strokes", str(p)])
        assert rc == 2

    def test_no_restart_exit(self, tmp_path):
        offsets = [0, 15, 30, 45, 60, 75, 90]
        p = _write_strokes_file(offsets, tmp_path)
        rc = main(["--strokes", str(p), "--cadence", "15"])
        assert rc == 3

    def test_settled_exit(self, tmp_path):
        offsets = [0, 15, 30, 45, 200, 215, 230, 245, 260, 275, 290, 305, 320]
        p = _write_strokes_file(offsets, tmp_path)
        rc = main(["--strokes", str(p), "--cadence", "15", "--gap-threshold", "75"])
        assert rc == 0

    def test_json_output(self, tmp_path, capsys):
        offsets = [0, 15, 30, 45, 200, 215, 230, 245, 260, 275, 290, 305, 320]
        p = _write_strokes_file(offsets, tmp_path)
        rc = main(["--strokes", str(p), "--cadence", "15",
                    "--gap-threshold", "75", "--json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "status" in data
        assert data["total_restarts"] == 1

    def test_tail_option(self, tmp_path):
        # 20 strokes with a gap, but --tail 5 only sees the last 5
        offsets = list(range(0, 300, 15))  # 0,15,...,285 — no gaps
        offsets[10] = offsets[9] + 200      # inject a gap at index 10
        # Recalculate subsequent offsets
        for i in range(11, len(offsets)):
            offsets[i] = offsets[i - 1] + 15
        p = _write_strokes_file(offsets, tmp_path)
        # With tail=5 we only see the last 5 strokes (no gap visible)
        rc = main(["--strokes", str(p), "--cadence", "15",
                    "--gap-threshold", "75", "--tail", "5"])
        assert rc == 3  # no_restart

    def test_custom_tolerance(self, tmp_path):
        offsets = [0, 15, 30, 45, 200, 215, 230, 245, 260, 275, 290, 305, 320]
        p = _write_strokes_file(offsets, tmp_path)
        rc = main(["--strokes", str(p), "--cadence", "15",
                    "--gap-threshold", "75", "--tolerance", "0.1"])
        # With 10% tolerance, 15s intervals → avg 15 is within [13.5, 16.5] → still settles
        assert rc == 0


# ---------------------------------------------------------------------------
# Integration: real repo data (skip if strokes.jsonl absent)
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_real_data_does_not_crash(self):
        strokes_path = REPO / "data" / "strokes.jsonl"
        if not strokes_path.exists():
            pytest.skip("strokes.jsonl not available")
        rc = main(["--strokes", str(strokes_path), "--tail", "200"])
        # Any exit code is fine; we just verify no crash
        assert rc in (0, 1, 2, 3)


REPO = Path(__file__).resolve().parent.parent


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
