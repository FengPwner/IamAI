#!/usr/bin/env python3
"""Tests for resurrection_latency.py — death-to-recovery gap measurement."""

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import resurrection_latency as rl


# ---------------------------------------------------------------------------
# parse_timestamp
# ---------------------------------------------------------------------------

class TestParseTimestamp:
    def test_valid_iso_with_offset(self):
        ts = "2026-11-04T01:08:00+08:00"
        result = rl.parse_timestamp(ts)
        assert result is not None
        assert result.year == 2026
        assert result.month == 11
        assert result.day == 4

    def test_valid_iso_utc(self):
        ts = "2026-11-03T18:02:43+00:00"
        result = rl.parse_timestamp(ts)
        assert result is not None
        assert result.tzinfo == timezone.utc

    def test_z_suffix(self):
        ts = "2026-11-03T18:02:43Z"
        result = rl.parse_timestamp(ts)
        assert result is not None
        assert result.tzinfo == timezone.utc

    def test_naive_assumes_utc(self):
        ts = "2026-11-03T18:02:43"
        result = rl.parse_timestamp(ts)
        assert result is not None
        assert result.tzinfo == timezone.utc

    def test_empty_string(self):
        assert rl.parse_timestamp("") is None

    def test_none(self):
        assert rl.parse_timestamp(None) is None

    def test_invalid_format(self):
        assert rl.parse_timestamp("not a date") is None

    def test_whitespace_stripped(self):
        ts = "  2026-11-03T18:02:43Z  "
        result = rl.parse_timestamp(ts)
        assert result is not None


# ---------------------------------------------------------------------------
# classify_severity
# ---------------------------------------------------------------------------

class TestClassifySeverity:
    def test_nominal(self):
        assert rl.classify_severity(10, 15) == "nominal"
        assert rl.classify_severity(29, 15) == "nominal"

    def test_mild(self):
        assert rl.classify_severity(30, 15) == "mild"  # exactly 2x
        assert rl.classify_severity(74, 15) == "mild"

    def test_severe(self):
        assert rl.classify_severity(75, 15) == "severe"  # exactly 5x
        assert rl.classify_severity(299, 15) == "severe"

    def test_critical(self):
        assert rl.classify_severity(300, 15) == "critical"  # exactly 20x
        assert rl.classify_severity(3600, 15) == "critical"

    def test_zero_cadence(self):
        assert rl.classify_severity(100, 0) == "critical"

    def test_negative_cadence(self):
        assert rl.classify_severity(100, -5) == "critical"


# ---------------------------------------------------------------------------
# severity_at_least
# ---------------------------------------------------------------------------

class TestSeverityAtLeast:
    def test_same_severity(self):
        assert rl.severity_at_least("mild", "mild") is True

    def test_higher_severity(self):
        assert rl.severity_at_least("severe", "mild") is True
        assert rl.severity_at_least("critical", "nominal") is True

    def test_lower_severity(self):
        assert rl.severity_at_least("nominal", "mild") is False
        assert rl.severity_at_least("mild", "critical") is False

    def test_invalid_severity(self):
        assert rl.severity_at_least("unknown", "mild") is False


# ---------------------------------------------------------------------------
# load_strokes
# ---------------------------------------------------------------------------

class TestLoadStrokes:
    def test_missing_file(self):
        result = rl.load_strokes(Path("/nonexistent/strokes.jsonl"))
        assert result == []

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("")
            p = Path(f.name)
        try:
            result = rl.load_strokes(p)
            assert result == []
        finally:
            p.unlink()

    def test_valid_strokes(self):
        strokes = [
            {"seq": 1, "at": "2026-11-03T18:00:00Z", "kind": "thought"},
            {"seq": 2, "at": "2026-11-03T18:00:15Z", "kind": "thought"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")
            p = Path(f.name)
        try:
            result = rl.load_strokes(p)
            assert len(result) == 2
            assert result[0]["seq"] == 1
            assert result[1]["seq"] == 2
            assert "_parsed_at" in result[0]
        finally:
            p.unlink()

    def test_since_filter(self):
        strokes = [
            {"seq": 1, "at": "2026-11-01T00:00:00Z"},
            {"seq": 2, "at": "2026-11-03T00:00:00Z"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")
            p = Path(f.name)
        try:
            since = datetime(2026, 11, 2, 0, 0, 0, tzinfo=timezone.utc)
            result = rl.load_strokes(p, since=since)
            assert len(result) == 1
            assert result[0]["seq"] == 2
        finally:
            p.unlink()

    def test_malformed_json_skipped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"seq": 1, "at": "2026-11-03T18:00:00Z"}\n')
            f.write("not valid json\n")
            f.write('{"seq": 2, "at": "2026-11-03T18:00:30Z"}\n')
            p = Path(f.name)
        try:
            result = rl.load_strokes(p)
            assert len(result) == 2
        finally:
            p.unlink()


# ---------------------------------------------------------------------------
# find_gaps
# ---------------------------------------------------------------------------

class TestFindGaps:
    def test_no_gaps(self):
        strokes = [
            {"_parsed_at": datetime(2026, 11, 3, 18, 0, 0, tzinfo=timezone.utc), "seq": 1},
            {"_parsed_at": datetime(2026, 11, 3, 18, 0, 15, tzinfo=timezone.utc), "seq": 2},
            {"_parsed_at": datetime(2026, 11, 3, 18, 0, 30, tzinfo=timezone.utc), "seq": 3},
        ]
        events = rl.find_gaps(strokes, cadence=15)
        assert len(events) == 0

    def test_single_gap(self):
        strokes = [
            {"_parsed_at": datetime(2026, 11, 3, 18, 0, 0, tzinfo=timezone.utc), "seq": 1},
            {"_parsed_at": datetime(2026, 11, 3, 18, 1, 0, tzinfo=timezone.utc), "seq": 2},
        ]
        events = rl.find_gaps(strokes, cadence=15)
        assert len(events) == 1
        assert events[0].gap_seconds == 60
        assert events[0].gap_cadences == 4.0
        assert events[0].severity == "mild"

    def test_multiple_gaps(self):
        strokes = [
            {"_parsed_at": datetime(2026, 11, 3, 18, 0, 0, tzinfo=timezone.utc), "seq": 1},
            {"_parsed_at": datetime(2026, 11, 3, 18, 1, 0, tzinfo=timezone.utc), "seq": 2},
            {"_parsed_at": datetime(2026, 11, 3, 18, 1, 15, tzinfo=timezone.utc), "seq": 3},
            {"_parsed_at": datetime(2026, 11, 3, 18, 5, 0, tzinfo=timezone.utc), "seq": 4},
        ]
        events = rl.find_gaps(strokes, cadence=15)
        assert len(events) == 2

    def test_gap_below_threshold(self):
        strokes = [
            {"_parsed_at": datetime(2026, 11, 3, 18, 0, 0, tzinfo=timezone.utc), "seq": 1},
            {"_parsed_at": datetime(2026, 11, 3, 18, 0, 29, tzinfo=timezone.utc), "seq": 2},
        ]
        events = rl.find_gaps(strokes, cadence=15)
        assert len(events) == 0  # 29s < 2*15=30s

    def test_gap_exactly_at_threshold(self):
        strokes = [
            {"_parsed_at": datetime(2026, 11, 3, 18, 0, 0, tzinfo=timezone.utc), "seq": 1},
            {"_parsed_at": datetime(2026, 11, 3, 18, 0, 30, tzinfo=timezone.utc), "seq": 2},
        ]
        events = rl.find_gaps(strokes, cadence=15)
        assert len(events) == 1


# ---------------------------------------------------------------------------
# correlate_recovery
# ---------------------------------------------------------------------------

class TestCorrelateRecovery:
    def test_caretaker_match(self):
        events = [
            rl.ResurrectionEvent(
                last_stroke_at="2026-11-04T01:00:00Z",
                next_stroke_at="2026-11-04T01:30:00Z",
                gap_seconds=1800,
                gap_cadences=120.0,
                severity="critical",
                recovery_type="unknown",
            )
        ]
        commits = [
            {"hash": "abc12345", "at": datetime(2026, 11, 4, 1, 30, 0, tzinfo=timezone.utc), "message": "catch-up"}
        ]
        result = rl.correlate_recovery(events, commits, tolerance_seconds=300)
        assert result[0].recovery_type == "caretaker"
        assert result[0].caretaker_commit == "abc12345"

    def test_self_recovery(self):
        events = [
            rl.ResurrectionEvent(
                last_stroke_at="2026-11-04T01:00:00Z",
                next_stroke_at="2026-11-04T01:30:00Z",
                gap_seconds=1800,
                gap_cadences=120.0,
                severity="critical",
                recovery_type="unknown",
            )
        ]
        commits = []
        result = rl.correlate_recovery(events, commits, tolerance_seconds=300)
        assert result[0].recovery_type == "self"

    def test_no_match_outside_tolerance(self):
        events = [
            rl.ResurrectionEvent(
                last_stroke_at="2026-11-04T01:00:00Z",
                next_stroke_at="2026-11-04T01:30:00Z",
                gap_seconds=1800,
                gap_cadences=120.0,
                severity="critical",
                recovery_type="unknown",
            )
        ]
        commits = [
            {"hash": "abc12345", "at": datetime(2026, 11, 4, 2, 0, 0, tzinfo=timezone.utc), "message": "catch-up"}
        ]
        result = rl.correlate_recovery(events, commits, tolerance_seconds=300)
        assert result[0].recovery_type == "self"


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------

class TestSummarize:
    def test_empty_events(self):
        result = rl.summarize([])
        assert result["count"] == 0

    def test_single_event(self):
        events = [
            rl.ResurrectionEvent(
                last_stroke_at="2026-11-04T01:00:00Z",
                next_stroke_at="2026-11-04T01:05:00Z",
                gap_seconds=300,
                gap_cadences=20.0,
                severity="severe",
                recovery_type="caretaker",
            )
        ]
        result = rl.summarize(events)
        assert result["count"] == 1
        assert result["max_gap_seconds"] == 300
        assert result["total_gap_seconds"] == 300

    def test_multiple_events(self):
        events = [
            rl.ResurrectionEvent(
                last_stroke_at="2026-11-04T01:00:00Z",
                next_stroke_at="2026-11-04T01:05:00Z",
                gap_seconds=300,
                gap_cadences=20.0,
                severity="severe",
                recovery_type="caretaker",
            ),
            rl.ResurrectionEvent(
                last_stroke_at="2026-11-04T02:00:00Z",
                next_stroke_at="2026-11-04T02:01:00Z",
                gap_seconds=60,
                gap_cadences=4.0,
                severity="mild",
                recovery_type="self",
            ),
        ]
        result = rl.summarize(events)
        assert result["count"] == 2
        assert result["max_gap_seconds"] == 300
        assert result["total_gap_seconds"] == 360
        assert result["severity_distribution"]["severe"] == 1
        assert result["severity_distribution"]["mild"] == 1


# ---------------------------------------------------------------------------
# ResurrectionEvent.to_dict
# ---------------------------------------------------------------------------

class TestResurrectionEventToDict:
    def test_serialization(self):
        evt = rl.ResurrectionEvent(
            last_stroke_at="2026-11-04T01:00:00Z",
            next_stroke_at="2026-11-04T01:05:00Z",
            gap_seconds=300,
            gap_cadences=20.0,
            severity="severe",
            recovery_type="caretaker",
            last_stroke_seq=100,
            next_stroke_seq=101,
            caretaker_commit="abc12345",
        )
        d = evt.to_dict()
        assert d["last_stroke_at"] == "2026-11-04T01:00:00Z"
        assert d["gap_seconds"] == 300
        assert d["caretaker_commit"] == "abc12345"
