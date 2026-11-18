#!/usr/bin/env python3
"""Tests for stroke_burst_detector.py — burst and drought pattern detection."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_burst_detector import (
    BurstEvent,
    BurstReport,
    DroughtEvent,
    _compute_regularity,
    _extract_timestamps,
    _parse_ts,
    analyze,
    detect_bursts,
    detect_droughts,
    inter_stroke_gaps,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 11, 19, 0, 0, 0, tzinfo=timezone.utc)


def _ts(offset_seconds: float) -> str:
    """Return an ISO-8601 timestamp offset from a fixed base."""
    dt = _BASE + timedelta(seconds=offset_seconds)
    return dt.isoformat()


def _stroke(offset: float, seq: int = 0) -> dict:
    return {"seq": seq, "at": _ts(offset), "kind": "thought", "text": "x"}


def _strokes_from_offsets(offsets: list, seqs: list = None) -> list:
    if seqs is None:
        seqs = list(range(len(offsets)))
    return [_stroke(o, s) for o, s in zip(offsets, seqs)]


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------

class TestParseTs:
    def test_iso_with_timezone(self):
        dt = _parse_ts("2026-11-19T00:00:00+00:00")
        assert dt.year == 2026
        assert dt.tzinfo is not None

    def test_iso_with_z(self):
        dt = _parse_ts("2026-11-19T00:00:00Z")
        assert dt.tzinfo is not None

    def test_iso_no_timezone(self):
        dt = _parse_ts("2026-11-19T00:00:00")
        assert dt.year == 2026


# ---------------------------------------------------------------------------
# _extract_timestamps
# ---------------------------------------------------------------------------

class TestExtractTimestamps:
    def test_sorted_output(self):
        strokes = [
            _stroke(100, 1),
            _stroke(0, 0),
            _stroke(50, 2),
        ]
        ts = _extract_timestamps(strokes)
        assert len(ts) == 3
        assert ts[0] < ts[1] < ts[2]

    def test_empty(self):
        assert _extract_timestamps([]) == []

    def test_missing_at_key(self):
        strokes = [{"seq": 1, "text": "no at"}]
        ts = _extract_timestamps(strokes)
        assert ts == []


# ---------------------------------------------------------------------------
# inter_stroke_gaps
# ---------------------------------------------------------------------------

class TestInterStrokeGaps:
    def test_uniform_gaps(self):
        strokes = _strokes_from_offsets([0, 15, 30, 45])
        gaps = inter_stroke_gaps(strokes)
        assert gaps == [15.0, 15.0, 15.0]

    def test_single_stroke(self):
        gaps = inter_stroke_gaps([_stroke(0)])
        assert gaps == []

    def test_empty(self):
        assert inter_stroke_gaps([]) == []

    def test_two_strokes(self):
        strokes = _strokes_from_offsets([0, 60])
        gaps = inter_stroke_gaps(strokes)
        assert gaps == [60.0]

    def test_unsorted_input(self):
        """Timestamps should be sorted internally."""
        strokes = [_stroke(30, 2), _stroke(0, 0), _stroke(15, 1)]
        gaps = inter_stroke_gaps(strokes)
        assert gaps == [15.0, 15.0]

    def test_negative_gap_clamped(self):
        """Duplicate timestamps should yield 0.0, not negative."""
        strokes = _strokes_from_offsets([0, 0, 10])
        gaps = inter_stroke_gaps(strokes)
        assert gaps[0] == 0.0
        assert gaps[1] == 10.0


# ---------------------------------------------------------------------------
# detect_bursts
# ---------------------------------------------------------------------------

class TestDetectBursts:
    def test_no_bursts(self):
        gaps = [15.0, 15.0, 15.0, 15.0]
        events = detect_bursts(gaps, threshold=3.75)
        assert events == []

    def test_single_burst(self):
        # 5 gaps of 1.0s (well below threshold of 10)
        gaps = [15.0, 1.0, 1.0, 1.0, 1.0, 15.0]
        events = detect_bursts(gaps, threshold=5.0)
        assert len(events) == 1
        assert events[0].count == 5  # 4 short gaps + 1
        assert events[0].span_seconds == pytest.approx(4.0)

    def test_burst_too_short(self):
        """A single short gap is not a burst (need ≥2 consecutive)."""
        gaps = [15.0, 1.0, 15.0]
        events = detect_bursts(gaps, threshold=5.0)
        assert events == []

    def test_trailing_burst(self):
        gaps = [15.0, 1.0, 1.0, 1.0]
        events = detect_bursts(gaps, threshold=5.0)
        assert len(events) == 1
        assert events[0].count == 4

    def test_leading_burst(self):
        gaps = [1.0, 1.0, 1.0, 15.0]
        events = detect_bursts(gaps, threshold=5.0)
        assert len(events) == 1
        assert events[0].start_seq == 0

    def test_empty_gaps(self):
        assert detect_bursts([], threshold=5.0) == []

    def test_zero_threshold(self):
        gaps = [1.0, 1.0, 1.0]
        assert detect_bursts(gaps, threshold=0) == []

    def test_seq_offset(self):
        gaps = [15.0, 1.0, 1.0, 1.0, 15.0]
        events = detect_bursts(gaps, threshold=5.0, seq_start=100)
        assert events[0].start_seq == 101

    def test_multiple_bursts(self):
        gaps = [1.0, 1.0, 15.0, 1.0, 1.0, 1.0, 15.0]
        events = detect_bursts(gaps, threshold=5.0)
        assert len(events) == 2


# ---------------------------------------------------------------------------
# detect_droughts
# ---------------------------------------------------------------------------

class TestDetectDroughts:
    def test_no_droughts(self):
        gaps = [15.0, 15.0, 15.0]
        events = detect_droughts(gaps, threshold=45.0)
        assert events == []

    def test_single_drought(self):
        gaps = [15.0, 300.0, 15.0]
        events = detect_droughts(gaps, threshold=45.0)
        assert len(events) == 1
        assert events[0].gap_seconds == 300.0
        assert events[0].after_seq == 1

    def test_multiple_droughts(self):
        gaps = [15.0, 100.0, 15.0, 200.0]
        events = detect_droughts(gaps, threshold=45.0)
        assert len(events) == 2
        assert events[0].gap_seconds == 100.0
        assert events[1].gap_seconds == 200.0

    def test_empty_gaps(self):
        assert detect_droughts([], threshold=45.0) == []

    def test_zero_threshold(self):
        assert detect_droughts([1.0], threshold=0) == []

    def test_exact_threshold_not_drought(self):
        gaps = [45.0]
        events = detect_droughts(gaps, threshold=45.0)
        assert events == []  # must be strictly above


# ---------------------------------------------------------------------------
# _compute_regularity
# ---------------------------------------------------------------------------

class TestComputeRegularity:
    def test_perfect(self):
        assert _compute_regularity(0.0) == 1.0

    def test_chaotic(self):
        assert _compute_regularity(1.0) == 0.0

    def test_beyond_one(self):
        assert _compute_regularity(5.0) == 0.0

    def test_midrange(self):
        assert _compute_regularity(0.5) == 0.5

    def test_negative_clamped(self):
        assert _compute_regularity(-0.1) == 1.0


# ---------------------------------------------------------------------------
# analyze (integration)
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_empty_strokes(self):
        report = analyze([])
        assert report.mean_gap == 0.0
        assert report.regularity_score == 0.0
        assert report.burst_events == []
        assert report.drought_events == []

    def test_single_stroke(self):
        report = analyze([_stroke(0, 0)])
        assert report.mean_gap == 0.0
        assert len(report.inter_stroke_gaps) == 0

    def test_clockwork_stream(self):
        """Perfectly periodic strokes should score high regularity."""
        strokes = _strokes_from_offsets(
            [i * 15.0 for i in range(100)]
        )
        report = analyze(strokes)
        assert report.mean_gap == 15.0
        assert report.gap_stddev == 0.0
        assert report.cv == 0.0
        assert report.regularity_score == 1.0
        assert report.burst_events == []
        assert report.drought_events == []

    def test_bursty_stream(self):
        """Bursts followed by droughts."""
        offsets = []
        t = 0.0
        for _ in range(10):
            # burst of 5 strokes in 5 seconds
            for j in range(5):
                offsets.append(t + j * 1.0)
            t += 5.0
            # drought of 300 seconds
            t += 300.0
        strokes = _strokes_from_offsets(offsets)
        report = analyze(strokes)

        assert report.regularity_score < 0.5
        assert len(report.burst_events) > 0
        assert len(report.drought_events) > 0
        assert report.burstiness > 0.0
        assert report.drought_fraction > 0.0

    def test_to_dict(self):
        strokes = _strokes_from_offsets([0, 15, 30, 45])
        report = analyze(strokes)
        d = report.to_dict()
        assert "n_gaps" in d
        assert "mean_gap_s" in d
        assert "regularity_score" in d
        assert d["n_gaps"] == 3
        assert d["mean_gap_s"] == 15.0

    def test_custom_thresholds(self):
        offsets = [0, 10, 20, 30, 100, 110, 120]
        strokes = _strokes_from_offsets(offsets)
        # Very generous burst threshold
        report = analyze(strokes, burst_fraction=0.8)
        # mean_gap ≈ 20, burst_threshold ≈ 16, so 10s gaps are bursts
        assert len(report.burst_events) > 0

    def test_drought_fraction_bounded(self):
        offsets = [0, 10, 1000, 1010]
        strokes = _strokes_from_offsets(offsets)
        report = analyze(strokes)
        assert 0.0 <= report.drought_fraction <= 1.0

    def test_burstiness_bounded(self):
        offsets = [0, 1, 2, 3, 4]
        strokes = _strokes_from_offsets(offsets)
        report = analyze(strokes)
        assert 0.0 <= report.burstiness <= 1.0

    def test_two_strokes_only(self):
        strokes = _strokes_from_offsets([0, 15])
        report = analyze(strokes)
        assert report.mean_gap == 15.0
        assert report.gap_stddev == 0.0  # single gap, no variance

    def test_mixed_gaps_realistic(self):
        """Simulate a realistic writer pattern: mostly 15s with jitter."""
        import random
        random.seed(42)
        offsets = [0.0]
        for i in range(200):
            gap = 15.0 + random.gauss(0, 3.0)
            offsets.append(offsets[-1] + max(0.5, gap))
        strokes = _strokes_from_offsets(offsets)
        report = analyze(strokes)

        assert report.mean_gap == pytest.approx(15.0, abs=1.0)
        assert report.regularity_score > 0.5
        assert report.cv < 0.5


# ---------------------------------------------------------------------------
# BurstReport dataclass
# ---------------------------------------------------------------------------

class TestBurstReport:
    def test_defaults(self):
        r = BurstReport()
        assert r.inter_stroke_gaps == []
        assert r.burst_events == []
        assert r.drought_events == []

    def test_to_dict_rounding(self):
        r = BurstReport(
            inter_stroke_gaps=[1.123456],
            mean_gap=1.123456,
            cv=0.987654,
            regularity_score=0.012346,
        )
        d = r.to_dict()
        assert d["mean_gap_s"] == 1.12
        assert d["cv"] == 0.9877
        assert d["regularity_score"] == 0.0123


# ---------------------------------------------------------------------------
# BurstEvent / DroughtEvent dataclasses
# ---------------------------------------------------------------------------

class TestEvents:
    def test_burst_event_fields(self):
        e = BurstEvent(start_seq=10, count=5, span_seconds=4.0)
        assert e.start_seq == 10
        assert e.count == 5
        assert e.span_seconds == 4.0

    def test_drought_event_fields(self):
        e = DroughtEvent(after_seq=42, gap_seconds=600.0)
        assert e.after_seq == 42
        assert e.gap_seconds == 600.0
