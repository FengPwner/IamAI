"""Tests for iamai.stall_diurnal_analysis.

Covers:
  - timestamp parsing (both 'at' and 't' fields)
  - stall midpoint hour calculation
  - histogram building (including empty input)
  - uniformity score (uniform, skewed, empty)
  - peak hour detection
  - verdict classification
  - summary formatting
  - full analyse pipeline
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iamai.stall_diurnal_analysis import (
    GMT8,
    analyse,
    diurnal_summary,
    diurnal_verdict,
    hour_histogram,
    parse_timestamps,
    peak_hours,
    stall_midpoint_hours,
    uniformity_score,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _ts(iso: str) -> datetime:
    """Shortcut: parse an ISO string into an aware datetime."""
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@pytest.fixture
def sample_timestamps():
    """Five timestamps with one large gap (3h) in the early morning."""
    base = datetime(2026, 10, 20, 22, 0, tzinfo=timezone.utc)
    return [
        base,                          # 22:00 UTC = 06:00+8 next day
        base + timedelta(minutes=5),   # 22:05
        base + timedelta(minutes=10),  # 22:10
        base + timedelta(hours=3, minutes=10),  # 01:10 UTC = gap of 3h
        base + timedelta(hours=3, minutes=15),  # 01:15
    ]


@pytest.fixture
def uniform_timestamps():
    """Stalls spread evenly across all 24 hours."""
    base = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
    timestamps = [base]
    for h in range(24):
        # normal stroke
        timestamps.append(timestamps[-1] + timedelta(minutes=5))
        # 10-minute gap (stall) → midpoint falls in hour h (UTC)
        timestamps.append(timestamps[-1] + timedelta(minutes=10))
    return timestamps


# ---------------------------------------------------------------------------
# parse_timestamps
# ---------------------------------------------------------------------------

class TestParseTimestamps:
    def test_basic_parsing(self):
        records = [
            {"seq": 1, "at": "2026-10-20T10:00:00+00:00"},
            {"seq": 2, "at": "2026-10-20T10:05:00+00:00"},
        ]
        result = parse_timestamps(records)
        assert len(result) == 2
        assert result[0] < result[1]

    def test_t_field_fallback(self):
        """Stroke 4007 uses 't' instead of 'at' (visit 261 data note)."""
        records = [{"seq": 4007, "t": "2026-10-18T12:00:00+00:00"}]
        result = parse_timestamps(records)
        assert len(result) == 1
        assert result[0].hour == 12

    def test_naive_gets_utc(self):
        records = [{"at": "2026-10-20T10:00:00"}]
        result = parse_timestamps(records)
        assert result[0].tzinfo == timezone.utc

    def test_missing_timestamp_skipped(self):
        records = [{"seq": 1, "text": "no timestamp"}, {"seq": 2, "at": "2026-10-20T10:00:00+00:00"}]
        result = parse_timestamps(records)
        assert len(result) == 1

    def test_sorted_output(self):
        records = [
            {"at": "2026-10-20T12:00:00+00:00"},
            {"at": "2026-10-20T08:00:00+00:00"},
            {"at": "2026-10-20T10:00:00+00:00"},
        ]
        result = parse_timestamps(records)
        assert result[0].hour == 8
        assert result[2].hour == 12

    def test_empty_records(self):
        assert parse_timestamps([]) == []


# ---------------------------------------------------------------------------
# stall_midpoint_hours
# ---------------------------------------------------------------------------

class TestStallMidpointHours:
    def test_detects_gap(self, sample_timestamps):
        hours = stall_midpoint_hours(sample_timestamps, threshold_seconds=300)
        # 3h gap between index 2 and 3; midpoint at 23:40 UTC = 07:40+8
        assert len(hours) == 1
        assert hours[0] == 7  # GMT+8

    def test_no_stalls(self):
        base = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
        ts = [base + timedelta(minutes=i * 5) for i in range(10)]
        hours = stall_midpoint_hours(ts, threshold_seconds=600)
        assert hours == []

    def test_multiple_stalls(self):
        base = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
        ts = [
            base,
            base + timedelta(hours=1),   # 1h gap
            base + timedelta(hours=1, minutes=5),
            base + timedelta(hours=3),   # ~2h gap
            base + timedelta(hours=3, minutes=5),
        ]
        hours = stall_midpoint_hours(ts, threshold_seconds=600)
        assert len(hours) == 2

    def test_threshold_boundary(self):
        base = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
        ts = [base, base + timedelta(seconds=300)]
        # exactly at threshold — should NOT be a stall (gap must exceed)
        assert stall_midpoint_hours(ts, threshold_seconds=300) == []
        # just under — should be a stall
        assert len(stall_midpoint_hours(ts, threshold_seconds=299)) == 1

    def test_timezone_conversion(self):
        """Ensure midpoint hour is in GMT+8, not UTC."""
        # gap from 16:00 UTC to 19:00 UTC = 00:00+8 to 03:00+8
        # midpoint at 17:30 UTC = 01:30+8 → hour 1
        base = datetime(2026, 10, 20, 16, 0, tzinfo=timezone.utc)
        ts = [base, base + timedelta(hours=3)]
        hours = stall_midpoint_hours(ts, threshold_seconds=60)
        assert hours == [1]


# ---------------------------------------------------------------------------
# hour_histogram
# ---------------------------------------------------------------------------

class TestHourHistogram:
    def test_basic(self):
        hist = hour_histogram([7, 7, 14, 22])
        assert hist[7] == 2
        assert hist[14] == 1
        assert hist[22] == 1
        assert hist[0] == 0

    def test_empty(self):
        hist = hour_histogram([])
        assert sum(hist.values()) == 0
        assert len(hist) == 24

    def test_all_24_keys(self):
        hist = hour_histogram([0, 12, 23])
        assert set(hist.keys()) == set(range(24))


# ---------------------------------------------------------------------------
# uniformity_score
# ---------------------------------------------------------------------------

class TestUniformityScore:
    def test_perfectly_uniform(self):
        hist = {h: 10 for h in range(24)}
        assert uniformity_score(hist) == 0.0

    def test_all_in_one_bin(self):
        hist = {h: 0 for h in range(24)}
        hist[3] = 240
        score = uniformity_score(hist)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_empty_histogram(self):
        hist = {h: 0 for h in range(24)}
        assert uniformity_score(hist) == 0.0

    def test_moderate_skew(self):
        hist = {h: 5 for h in range(24)}
        hist[4] = 20  # bump one hour
        score = uniformity_score(hist)
        assert 0.0 < score < 1.0

    def test_returns_float(self):
        hist = hour_histogram([1, 2, 3])
        assert isinstance(uniformity_score(hist), float)


# ---------------------------------------------------------------------------
# peak_hours
# ---------------------------------------------------------------------------

class TestPeakHours:
    def test_detects_peaks(self):
        hist = {h: 5 for h in range(24)}
        hist[3] = 30
        hist[14] = 25
        peaks = peak_hours(hist, multiplier=1.5)
        assert 3 in peaks
        assert 14 in peaks

    def test_no_peaks(self):
        hist = {h: 10 for h in range(24)}
        assert peak_hours(hist) == []

    def test_empty(self):
        assert peak_hours({}) == []

    def test_sorted_by_count(self):
        hist = {h: 5 for h in range(24)}
        hist[2] = 40
        hist[8] = 30
        peaks = peak_hours(hist, multiplier=1.5)
        assert peaks[0] == 2  # highest first
        assert peaks[1] == 8

    def test_custom_multiplier(self):
        hist = {h: 10 for h in range(24)}
        hist[5] = 16
        # at 1.5x, threshold = 15 → 16 qualifies
        assert 5 in peak_hours(hist, multiplier=1.5)
        # at 2.0x, threshold = 20 → 16 does not qualify
        assert 5 not in peak_hours(hist, multiplier=2.0)


# ---------------------------------------------------------------------------
# diurnal_verdict
# ---------------------------------------------------------------------------

class TestDiurnalVerdict:
    def test_strong_diurnal(self):
        hist = {h: 2 for h in range(24)}
        hist[3] = 50
        hist[4] = 40
        assert diurnal_verdict(hist) == "strong_diurnal"

    def test_weak_diurnal(self):
        hist = {h: 5 for h in range(24)}
        hist[7] = 30
        assert diurnal_verdict(hist) == "weak_diurnal"

    def test_uniform(self):
        hist = {h: 10 for h in range(24)}
        assert diurnal_verdict(hist) == "uniform"

    def test_empty(self):
        hist = hour_histogram([])
        assert diurnal_verdict(hist) == "uniform"


# ---------------------------------------------------------------------------
# diurnal_summary
# ---------------------------------------------------------------------------

class TestDiurnalSummary:
    def test_contains_verdict(self):
        hist = {h: 5 for h in range(24)}
        verdict = diurnal_verdict(hist)
        summary = diurnal_summary(hist, verdict)
        assert verdict in summary

    def test_contains_peak_hours(self):
        hist = {h: 2 for h in range(24)}
        hist[3] = 50
        verdict = diurnal_verdict(hist)
        summary = diurnal_summary(hist, verdict)
        assert "03:00" in summary

    def test_returns_string(self):
        hist = hour_histogram([10, 10, 10])
        verdict = diurnal_verdict(hist)
        assert isinstance(diurnal_summary(hist, verdict), str)

    def test_no_peaks_shows_none(self):
        hist = {h: 10 for h in range(24)}
        summary = diurnal_summary(hist, "uniform")
        assert "none" in summary


# ---------------------------------------------------------------------------
# analyse (integration)
# ---------------------------------------------------------------------------

class TestAnalyse:
    def test_with_records(self):
        base = "2026-10-20T10:00:00+00:00"
        records = [
            {"seq": 1, "at": base},
            {"seq": 2, "at": "2026-10-20T10:05:00+00:00"},
            {"seq": 3, "at": "2026-10-20T10:10:00+00:00"},
            {"seq": 4, "at": "2026-10-20T13:10:00+00:00"},  # 3h gap
            {"seq": 5, "at": "2026-10-20T13:15:00+00:00"},
        ]
        result = analyse(records=records, threshold_seconds=300)
        assert result["total_strokes"] == 5
        assert result["stall_count"] == 1
        assert "verdict" in result
        assert "histogram" in result
        assert isinstance(result["uniformity_score"], float)

    def test_empty_records(self):
        result = analyse(records=[], threshold_seconds=300)
        assert result["total_strokes"] == 0
        assert result["stall_count"] == 0
        assert result["verdict"] == "uniform"

    def test_with_t_field(self):
        records = [
            {"seq": 1, "t": "2026-10-20T10:00:00+00:00"},
            {"seq": 2, "t": "2026-10-20T13:00:00+00:00"},
        ]
        result = analyse(records=records, threshold_seconds=60)
        assert result["total_strokes"] == 2
        assert result["stall_count"] == 1
