"""test_resurrection_detector.py — 42 tests for resurrection detection.

covers:
- timestamp parsing (Z suffix, offset formats, edge cases)
- gap computation (normal, empty, single-stroke)
- stall detection (threshold boundary, multiple stalls)
- backfill burst detection (qualifying, too small, too spread)
- full resurrection detection pipeline
- stroke tagging (correct annotation, no mutation of input)
- summary generation
- edge cases (out-of-order, identical timestamps, missing fields)
"""

import json
import pytest
from datetime import datetime, timezone, timedelta

from tools.resurrection_detector import (
    parse_timestamp,
    compute_gaps,
    detect_stalls,
    detect_backfill_burst,
    detect_resurrections,
    tag_strokes,
    summarize_resurrections,
)


# --- timestamp parsing ---

class TestParseTimestamp:
    def test_z_suffix(self):
        dt = parse_timestamp("2026-11-20T15:00:00Z")
        assert dt.tzinfo is not None
        assert dt.year == 2026
        assert dt.month == 11
        assert dt.day == 20

    def test_offset_suffix(self):
        dt = parse_timestamp("2026-11-20T15:00:00+08:00")
        assert dt.tzinfo is not None
        assert dt.utcoffset() == timedelta(hours=8)

    def test_whitespace_stripped(self):
        dt = parse_timestamp("  2026-11-20T15:00:00Z  ")
        assert dt.year == 2026

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_timestamp("not-a-timestamp")

    def test_fractional_seconds(self):
        dt = parse_timestamp("2026-11-20T15:00:00.123456Z")
        assert dt.microsecond == 123456


# --- gap computation ---

class TestComputeGaps:
    def test_normal_gaps(self):
        strokes = [
            {"at": "2026-11-20T15:00:00Z"},
            {"at": "2026-11-20T15:05:00Z"},
            {"at": "2026-11-20T15:15:00Z"},
        ]
        gaps = compute_gaps(strokes)
        assert len(gaps) == 2
        assert gaps[0]["gap_sec"] == 300.0
        assert gaps[1]["gap_sec"] == 600.0

    def test_single_stroke(self):
        gaps = compute_gaps([{"at": "2026-11-20T15:00:00Z"}])
        assert gaps == []

    def test_empty_list(self):
        gaps = compute_gaps([])
        assert gaps == []

    def test_identical_timestamps(self):
        strokes = [
            {"at": "2026-11-20T15:00:00Z"},
            {"at": "2026-11-20T15:00:00Z"},
        ]
        gaps = compute_gaps(strokes)
        assert gaps[0]["gap_sec"] == 0.0

    def test_gap_indices(self):
        strokes = [
            {"at": "2026-11-20T15:00:00Z"},
            {"at": "2026-11-20T15:10:00Z"},
        ]
        gaps = compute_gaps(strokes)
        assert gaps[0]["index"] == 1


# --- stall detection ---

class TestDetectStalls:
    def test_above_threshold(self):
        gaps = [{"gap_sec": 600.0, "index": 1, "gap_start": None, "gap_end": None}]
        stalls = detect_stalls(gaps, stall_threshold_sec=300.0)
        assert len(stalls) == 1

    def test_below_threshold(self):
        gaps = [{"gap_sec": 100.0, "index": 1, "gap_start": None, "gap_end": None}]
        stalls = detect_stalls(gaps, stall_threshold_sec=300.0)
        assert len(stalls) == 0

    def test_exact_threshold(self):
        gaps = [{"gap_sec": 300.0, "index": 1, "gap_start": None, "gap_end": None}]
        stalls = detect_stalls(gaps, stall_threshold_sec=300.0)
        assert len(stalls) == 1

    def test_multiple_stalls(self):
        gaps = [
            {"gap_sec": 400.0, "index": 1},
            {"gap_sec": 50.0, "index": 2},
            {"gap_sec": 500.0, "index": 3},
        ]
        stalls = detect_stalls(gaps, stall_threshold_sec=300.0)
        assert len(stalls) == 2


# --- backfill burst detection ---

class TestDetectBackfillBurst:
    def _make_strokes(self, base_ts, intervals_sec):
        """helper: create strokes at given intervals from base."""
        strokes = []
        current = base_ts
        for interval in [0] + intervals_sec:
            current = current + timedelta(seconds=interval)
            strokes.append({"at": current.isoformat()})
        return strokes

    def test_qualifying_burst(self):
        base = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)
        # 5 strokes, 10s apart
        strokes = self._make_strokes(base, [10, 10, 10, 10])
        burst = detect_backfill_burst(strokes, 0, burst_window_sec=60.0, min_burst_size=3)
        assert burst is not None
        assert burst["count"] == 5

    def test_too_small(self):
        base = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)
        strokes = self._make_strokes(base, [10])
        burst = detect_backfill_burst(strokes, 0, burst_window_sec=60.0, min_burst_size=3)
        assert burst is None

    def test_too_spread(self):
        base = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)
        # gaps of 120s exceed 60s burst window
        strokes = self._make_strokes(base, [120, 120, 120])
        burst = detect_backfill_burst(strokes, 0, burst_window_sec=60.0, min_burst_size=3)
        assert burst is None

    def test_partial_burst(self):
        base = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)
        # first 4 strokes tight, then a big gap
        strokes = self._make_strokes(base, [10, 10, 10, 200, 10])
        burst = detect_backfill_burst(strokes, 0, burst_window_sec=60.0, min_burst_size=3)
        assert burst is not None
        assert burst["count"] == 4

    def test_index_out_of_range(self):
        strokes = [{"at": "2026-11-20T15:00:00Z"}]
        burst = detect_backfill_burst(strokes, 5)
        assert burst is None

    def test_burst_span(self):
        base = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)
        strokes = self._make_strokes(base, [10, 10, 10, 10])
        burst = detect_backfill_burst(strokes, 0, burst_window_sec=60.0, min_burst_size=3)
        assert burst["span_sec"] == 40.0


# --- full resurrection detection ---

class TestDetectResurrections:
    def test_stall_then_burst(self):
        base = datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc)
        strokes = [
            {"at": base.isoformat()},
            # 10 minute gap (stall)
            {"at": (base + timedelta(minutes=10)).isoformat()},
            # burst: 4 strokes 5s apart
            {"at": (base + timedelta(minutes=10, seconds=5)).isoformat()},
            {"at": (base + timedelta(minutes=10, seconds=10)).isoformat()},
            {"at": (base + timedelta(minutes=10, seconds=15)).isoformat()},
        ]
        events = detect_resurrections(strokes, stall_threshold_sec=300.0)
        assert len(events) == 1
        assert events[0]["burst_count"] == 4
        assert events[0]["stall_gap_sec"] == 600.0

    def test_stall_without_burst(self):
        base = datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc)
        strokes = [
            {"at": base.isoformat()},
            # 10 minute gap
            {"at": (base + timedelta(minutes=10)).isoformat()},
            # then normal cadence (5 min apart)
            {"at": (base + timedelta(minutes=15)).isoformat()},
        ]
        events = detect_resurrections(strokes, stall_threshold_sec=300.0)
        assert len(events) == 0

    def test_no_stall(self):
        base = datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc)
        strokes = [
            {"at": base.isoformat()},
            {"at": (base + timedelta(seconds=15)).isoformat()},
            {"at": (base + timedelta(seconds=30)).isoformat()},
            {"at": (base + timedelta(seconds=45)).isoformat()},
        ]
        events = detect_resurrections(strokes, stall_threshold_sec=300.0)
        assert len(events) == 0

    def test_empty_strokes(self):
        events = detect_resurrections([])
        assert events == []

    def test_single_stroke(self):
        events = detect_resurrections([{"at": "2026-11-20T15:00:00Z"}])
        assert events == []

    def test_multiple_resurrections(self):
        base = datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc)
        strokes = [
            {"at": base.isoformat()},
            # stall 1: 10 min gap
            {"at": (base + timedelta(minutes=10)).isoformat()},
            # burst 1
            {"at": (base + timedelta(minutes=10, seconds=5)).isoformat()},
            {"at": (base + timedelta(minutes=10, seconds=10)).isoformat()},
            # normal gap
            {"at": (base + timedelta(minutes=15)).isoformat()},
            # stall 2: 10 min gap
            {"at": (base + timedelta(minutes=25)).isoformat()},
            # burst 2
            {"at": (base + timedelta(minutes=25, seconds=5)).isoformat()},
            {"at": (base + timedelta(minutes=25, seconds=10)).isoformat()},
        ]
        events = detect_resurrections(strokes, stall_threshold_sec=300.0)
        assert len(events) == 2


# --- stroke tagging ---

class TestTagStrokes:
    def test_tags_applied(self):
        base = datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc)
        strokes = [
            {"at": base.isoformat(), "seq": 1},
            {"at": (base + timedelta(minutes=10)).isoformat(), "seq": 2},
            {"at": (base + timedelta(minutes=10, seconds=5)).isoformat(), "seq": 3},
            {"at": (base + timedelta(minutes=10, seconds=10)).isoformat(), "seq": 4},
        ]
        events = detect_resurrections(strokes, stall_threshold_sec=300.0)
        tagged = tag_strokes(strokes, events)
        # stroke 0: no tag (before stall)
        assert "resurrection_tag" not in tagged[0]
        # strokes 1,2,3: tagged as burst
        assert "resurrection_tag" in tagged[1]
        assert tagged[1]["resurrection_tag"]["position_in_burst"] == 0
        assert tagged[2]["resurrection_tag"]["position_in_burst"] == 1
        assert tagged[3]["resurrection_tag"]["position_in_burst"] == 2

    def test_no_mutation(self):
        strokes = [
            {"at": "2026-11-20T15:00:00Z", "seq": 1},
            {"at": "2026-11-20T15:10:00Z", "seq": 2},
        ]
        events = []
        tagged = tag_strokes(strokes, events)
        # original should not be modified
        assert "resurrection_tag" not in strokes[0]
        # tagged is a new list
        assert tagged is not strokes

    def test_custom_tag_field(self):
        strokes = [
            {"at": "2026-11-20T15:00:00Z"},
            {"at": "2026-11-20T15:10:00Z"},
        ]
        events = [{
            "burst_start_index": 0,
            "burst_end_index": 1,
            "stall_gap_sec": 600,
        }]
        tagged = tag_strokes(strokes, events, tag_field="my_tag")
        assert "my_tag" in tagged[0]
        assert "resurrection_tag" not in tagged[0]

    def test_empty_events(self):
        strokes = [{"at": "2026-11-20T15:00:00Z"}]
        tagged = tag_strokes(strokes, [])
        assert "resurrection_tag" not in tagged[0]


# --- summary generation ---

class TestSummarizeResurrections:
    def test_no_events(self):
        result = summarize_resurrections([])
        assert "no resurrection events" in result

    def test_single_event(self):
        events = [{
            "stall_gap_sec": 600.0,
            "burst_count": 5,
            "burst_span_sec": 20.0,
        }]
        result = summarize_resurrections(events)
        assert "1 resurrection event" in result
        assert "600s" in result
        assert "5 strokes" in result

    def test_multiple_events(self):
        events = [
            {"stall_gap_sec": 300.0, "burst_count": 3, "burst_span_sec": 10.0},
            {"stall_gap_sec": 900.0, "burst_count": 7, "burst_span_sec": 30.0},
        ]
        result = summarize_resurrections(events)
        assert "2 resurrection event" in result
        assert "[0]" in result
        assert "[1]" in result

    def test_minutes_conversion(self):
        events = [{"stall_gap_sec": 600.0, "burst_count": 3, "burst_span_sec": 10.0}]
        result = summarize_resurrections(events)
        assert "10.0min" in result


# --- edge cases ---

class TestEdgeCases:
    def test_out_of_order_timestamps(self):
        """strokes not sorted by time — gaps may be negative."""
        strokes = [
            {"at": "2026-11-20T15:10:00Z"},
            {"at": "2026-11-20T15:00:00Z"},  # earlier than previous
        ]
        gaps = compute_gaps(strokes)
        assert gaps[0]["gap_sec"] == -600.0
        # negative gaps should not trigger stalls
        stalls = detect_stalls(gaps, stall_threshold_sec=300.0)
        assert len(stalls) == 0

    def test_burst_at_end_of_list(self):
        """stall near the end with a burst that hits the last stroke."""
        base = datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc)
        strokes = [
            {"at": base.isoformat()},
            {"at": (base + timedelta(minutes=10)).isoformat()},
            {"at": (base + timedelta(minutes=10, seconds=5)).isoformat()},
            {"at": (base + timedelta(minutes=10, seconds=10)).isoformat()},
        ]
        events = detect_resurrections(strokes, stall_threshold_sec=300.0)
        assert len(events) == 1
        assert events[0]["burst_end_index"] == 3

    def test_tag_strokes_beyond_bounds(self):
        """event references indices beyond stroke list length."""
        strokes = [{"at": "2026-11-20T15:00:00Z"}]
        events = [{
            "burst_start_index": 0,
            "burst_end_index": 10,  # way beyond
            "stall_gap_sec": 600,
        }]
        # should not crash
        tagged = tag_strokes(strokes, events)
        assert len(tagged) == 1
        assert "resurrection_tag" in tagged[0]

    def test_zero_threshold(self):
        """threshold of 0 means every gap is a stall."""
        gaps = [{"gap_sec": 0.1, "index": 1}]
        stalls = detect_stalls(gaps, stall_threshold_sec=0.0)
        assert len(stalls) == 1

    def test_very_large_gap(self):
        """multi-day gap should be detected."""
        base = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
        strokes = [
            {"at": base.isoformat()},
            {"at": (base + timedelta(days=7)).isoformat()},
            {"at": (base + timedelta(days=7, seconds=5)).isoformat()},
            {"at": (base + timedelta(days=7, seconds=10)).isoformat()},
        ]
        events = detect_resurrections(strokes, stall_threshold_sec=300.0)
        assert len(events) == 1
        assert events[0]["stall_gap_sec"] == 7 * 86400.0
