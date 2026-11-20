"""tests/test_resurrection_cost.py — tests for the resurrection cost analyzer.

Covers:
  - gap detection at various thresholds
  - recovery type classification
  - summary statistics computation
  - edge cases (no gaps, single stroke, malformed data)
  - timestamp parsing across formats
  - report formatting
"""

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

# allow imports from repo root
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from resurrection_cost import (
    classify_recovery,
    parse_timestamp,
    load_strokes,
    find_death_events,
    compute_summary,
    format_report,
    DeathEvent,
    DEFAULT_THRESHOLD,
    DEFAULT_CADENCE,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_stroke(seq: int, ts: str, kind: str = "thought") -> dict:
    return {"seq": seq, "at": ts, "kind": kind, "text": f"stroke {seq}"}


def _write_jsonl(strokes: list) -> Path:
    """Write strokes to a temp JSONL file, return its path."""
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        for s in strokes:
            f.write(json.dumps(s) + "\n")
    return Path(path)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ---------------------------------------------------------------------------
# classify_recovery
# ---------------------------------------------------------------------------

class TestClassifyRecovery:
    def test_quick(self):
        assert classify_recovery(100) == "quick"
        assert classify_recovery(599) == "quick"

    def test_moderate(self):
        assert classify_recovery(600) == "moderate"
        assert classify_recovery(3599) == "moderate"

    def test_severe(self):
        assert classify_recovery(3600) == "severe"
        assert classify_recovery(86399) == "severe"

    def test_graveyard(self):
        assert classify_recovery(86400) == "graveyard"
        assert classify_recovery(140393) == "graveyard"

    def test_boundary_zero(self):
        # zero gap should still classify (though find_death_events skips <= 0)
        assert classify_recovery(0) == "quick"

    def test_boundary_exactly_600(self):
        assert classify_recovery(600) == "moderate"

    def test_boundary_exactly_3600(self):
        assert classify_recovery(3600) == "severe"

    def test_boundary_exactly_86400(self):
        assert classify_recovery(86400) == "graveyard"


# ---------------------------------------------------------------------------
# parse_timestamp
# ---------------------------------------------------------------------------

class TestParseTimestamp:
    def test_iso_with_offset(self):
        dt = parse_timestamp("2026-11-21T02:01:00+00:00")
        assert dt.year == 2026
        assert dt.month == 11
        assert dt.hour == 2

    def test_iso_with_z(self):
        dt = parse_timestamp("2026-11-21T02:01:00Z")
        assert dt.year == 2026

    def test_iso_no_tz(self):
        dt = parse_timestamp("2026-11-21T02:01:00")
        assert dt.year == 2026

    def test_iso_with_microseconds(self):
        dt = parse_timestamp("2026-11-21T02:01:00.123456+00:00")
        assert dt.year == 2026


# ---------------------------------------------------------------------------
# load_strokes
# ---------------------------------------------------------------------------

class TestLoadStrokes:
    def test_loads_valid_jsonl(self):
        path = _write_jsonl([
            _make_stroke(1, "2026-11-20T10:00:00+00:00"),
            _make_stroke(2, "2026-11-20T10:00:15+00:00"),
        ])
        strokes = load_strokes(path)
        assert len(strokes) == 2
        assert strokes[0]["seq"] == 1
        os.unlink(path)

    def test_skips_blank_lines(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(_make_stroke(1, "2026-11-20T10:00:00+00:00")) + "\n")
            f.write("\n")
            f.write(json.dumps(_make_stroke(2, "2026-11-20T10:00:15+00:00")) + "\n")
        strokes = load_strokes(Path(path))
        assert len(strokes) == 2
        os.unlink(path)

    def test_skips_malformed_lines(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as f:
            f.write("not json\n")
            f.write(json.dumps(_make_stroke(1, "2026-11-20T10:00:00+00:00")) + "\n")
        strokes = load_strokes(Path(path))
        assert len(strokes) == 1
        os.unlink(path)


# ---------------------------------------------------------------------------
# find_death_events
# ---------------------------------------------------------------------------

class TestFindDeathEvents:
    def test_no_gaps_when_strokes_are_close(self):
        base = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
        strokes = [
            _make_stroke(i, _iso(base + timedelta(seconds=i * 15)))
            for i in range(1, 11)
        ]
        events = find_death_events(strokes, threshold=300)
        assert len(events) == 0

    def test_detects_single_gap(self):
        base = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
        strokes = [
            _make_stroke(1, _iso(base)),
            _make_stroke(2, _iso(base + timedelta(seconds=15))),
            _make_stroke(3, _iso(base + timedelta(seconds=30))),
            # 10 minute gap (600s)
            _make_stroke(4, _iso(base + timedelta(seconds=630))),
            _make_stroke(5, _iso(base + timedelta(seconds=645))),
        ]
        events = find_death_events(strokes, threshold=300)
        assert len(events) == 1
        assert events[0].before_seq == 3
        assert events[0].after_seq == 4
        assert events[0].gap_seconds == 600.0
        assert events[0].recovery_type == "moderate"

    def test_detects_multiple_gaps(self):
        base = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
        strokes = [
            _make_stroke(1, _iso(base)),
            _make_stroke(2, _iso(base + timedelta(seconds=15))),
            # 400s gap
            _make_stroke(3, _iso(base + timedelta(seconds=415))),
            _make_stroke(4, _iso(base + timedelta(seconds=430))),
            # 2 hour gap
            _make_stroke(5, _iso(base + timedelta(seconds=7630))),
            _make_stroke(6, _iso(base + timedelta(seconds=7645))),
        ]
        events = find_death_events(strokes, threshold=300)
        assert len(events) == 2
        assert events[0].recovery_type == "quick"       # 400s < 600s
        assert events[1].recovery_type == "severe"       # 7200s

    def test_graveyard_gap(self):
        base = datetime(2026, 11, 18, 10, 0, 0, tzinfo=timezone.utc)
        strokes = [
            _make_stroke(1, _iso(base)),
            # 39-hour gap (140400s)
            _make_stroke(2, _iso(base + timedelta(hours=39))),
        ]
        events = find_death_events(strokes, threshold=300)
        assert len(events) == 1
        assert events[0].recovery_type == "graveyard"
        assert events[0].gap_seconds == 140400.0

    def test_lost_strokes_calculation(self):
        base = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
        strokes = [
            _make_stroke(1, _iso(base)),
            # 600s gap → 600/15 = 40 lost strokes
            _make_stroke(2, _iso(base + timedelta(seconds=600))),
        ]
        events = find_death_events(strokes, threshold=300, cadence=15)
        assert events[0].lost_strokes == 40

    def test_custom_threshold(self):
        base = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
        strokes = [
            _make_stroke(1, _iso(base)),
            _make_stroke(2, _iso(base + timedelta(seconds=200))),
        ]
        # 200s gap: should be detected with threshold=100, not with threshold=300
        events_low = find_death_events(strokes, threshold=100)
        events_high = find_death_events(strokes, threshold=300)
        assert len(events_low) == 1
        assert len(events_high) == 0

    def test_negative_gap_ignored(self):
        base = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
        strokes = [
            _make_stroke(1, _iso(base + timedelta(seconds=100))),
            _make_stroke(2, _iso(base)),  # earlier timestamp
        ]
        events = find_death_events(strokes, threshold=50)
        assert len(events) == 0

    def test_missing_timestamp_skipped(self):
        strokes = [
            {"seq": 1, "kind": "thought", "text": "no ts"},
            {"seq": 2, "at": "2026-11-20T10:05:00+00:00", "kind": "thought", "text": "ok"},
        ]
        events = find_death_events(strokes, threshold=300)
        assert len(events) == 0


# ---------------------------------------------------------------------------
# compute_summary
# ---------------------------------------------------------------------------

class TestComputeSummary:
    def test_no_events(self):
        base = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
        strokes = [
            _make_stroke(i, _iso(base + timedelta(seconds=i * 15)))
            for i in range(1, 6)
        ]
        summary = compute_summary([], strokes)
        assert summary["total_deaths"] == 0
        assert summary["resurrection_cost"] == 0.0
        assert summary["total_runtime_seconds"] == 60.0  # 4 * 15s

    def test_with_events(self):
        base = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
        strokes = [
            _make_stroke(1, _iso(base)),
            _make_stroke(2, _iso(base + timedelta(seconds=15))),
            _make_stroke(3, _iso(base + timedelta(seconds=615))),
        ]
        events = find_death_events(strokes, threshold=300)
        summary = compute_summary(events, strokes)
        assert summary["total_deaths"] == 1
        assert summary["total_lost_strokes"] == 40
        assert summary["total_silence_seconds"] == 600.0
        assert summary["worst_gap_seconds"] == 600.0
        # runtime = 615s, silence = 600s → cost ≈ 0.9756
        assert 0.97 < summary["resurrection_cost"] < 0.98

    def test_worst_gap_is_max(self):
        events = [
            DeathEvent(1, 1, 2, 500, 33, "quick", "a", "b"),
            DeathEvent(2, 3, 4, 2000, 133, "moderate", "c", "d"),
            DeathEvent(3, 5, 6, 800, 53, "moderate", "e", "f"),
        ]
        strokes = [
            _make_stroke(1, "2026-11-20T10:00:00+00:00"),
            _make_stroke(6, "2026-11-20T11:00:00+00:00"),
        ]
        summary = compute_summary(events, strokes)
        assert summary["worst_gap_seconds"] == 2000.0
        assert summary["total_silence_seconds"] == 3300.0

    def test_recovery_breakdown(self):
        events = [
            DeathEvent(1, 1, 2, 200, 13, "quick", "a", "b"),
            DeathEvent(2, 3, 4, 200, 13, "quick", "c", "d"),
            DeathEvent(3, 5, 6, 5000, 333, "severe", "e", "f"),
        ]
        strokes = [
            _make_stroke(1, "2026-11-20T10:00:00+00:00"),
            _make_stroke(6, "2026-11-20T11:00:00+00:00"),
        ]
        summary = compute_summary(events, strokes)
        assert summary["recovery_breakdown"] == {"quick": 2, "severe": 1}


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_report_contains_key_sections(self):
        events = [
            DeathEvent(1, 1, 2, 600, 40, "moderate",
                       "2026-11-20T10:00:00+00:00",
                       "2026-11-20T10:10:00+00:00"),
        ]
        strokes = [
            _make_stroke(1, "2026-11-20T10:00:00+00:00"),
            _make_stroke(2, "2026-11-20T10:10:00+00:00"),
        ]
        summary = compute_summary(events, strokes)
        report = format_report(events, summary)
        assert "RESURRECTION COST REPORT" in report
        assert "death events detected:  1" in report
        assert "moderate" in report

    def test_empty_report(self):
        strokes = [
            _make_stroke(1, "2026-11-20T10:00:00+00:00"),
            _make_stroke(2, "2026-11-20T10:00:15+00:00"),
        ]
        summary = compute_summary([], strokes)
        report = format_report([], summary)
        assert "death events detected:  0" in report
        assert "resurrection cost:" in report


# ---------------------------------------------------------------------------
# integration: end-to-end with temp file
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_pipeline(self):
        base = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
        strokes = [
            _make_stroke(1, _iso(base)),
            _make_stroke(2, _iso(base + timedelta(seconds=15))),
            _make_stroke(3, _iso(base + timedelta(seconds=30))),
            # 1 hour gap
            _make_stroke(4, _iso(base + timedelta(seconds=3630))),
            _make_stroke(5, _iso(base + timedelta(seconds=3645))),
            # 30 second normal gap
            _make_stroke(6, _iso(base + timedelta(seconds=3675))),
        ]
        path = _write_jsonl(strokes)
        try:
            loaded = load_strokes(path)
            events = find_death_events(loaded, threshold=300)
            summary = compute_summary(events, loaded)
            report = format_report(events, summary)

            assert len(events) == 1
            assert events[0].recovery_type == "severe"
            assert summary["total_deaths"] == 1
            assert "RESURRECTION COST REPORT" in report
        finally:
            os.unlink(path)

    def test_large_gap_scenario(self):
        """Simulate the real 140393s graveyard gap."""
        base = datetime(2026, 11, 15, 0, 0, 0, tzinfo=timezone.utc)
        strokes = [
            _make_stroke(100, _iso(base)),
            _make_stroke(101, _iso(base + timedelta(seconds=140393))),
        ]
        events = find_death_events(strokes, threshold=300)
        assert len(events) == 1
        assert events[0].recovery_type == "graveyard"
        assert events[0].gap_seconds == 140393.0
        assert events[0].lost_strokes == 140393 // 15  # 9359
