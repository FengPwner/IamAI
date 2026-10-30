"""Tests for iamai.stall_classifier — classifying silence gaps by cause.

Each test constructs a minimal stroke sequence with known gaps and
verifies the classifier assigns the correct category. The strokes are
synthetic — no file I/O needed.
"""

import pytest

from iamai.stall_classifier import (
    NETWORK_BLIP,
    PUSH_DIVERGENCE,
    RECYCLE,
    UNKNOWN,
    Stall,
    StallReport,
    classify_strokes,
    summarize,
    _classify_gap,
)


def _stroke(seq: int, at: str) -> dict:
    return {"seq": seq, "at": at}


# --- _classify_gap (unit) ---


class TestClassifyGap:
    def test_short_continuous_gap_is_network_blip(self):
        assert _classify_gap(20.0, seq_continuous=True) == NETWORK_BLIP

    def test_moderate_continuous_gap_is_recycle(self):
        assert _classify_gap(90.0, seq_continuous=True) == RECYCLE

    def test_long_gap_is_push_divergence(self):
        assert _classify_gap(600.0, seq_continuous=False) == PUSH_DIVERGENCE

    def test_very_long_gap_is_unknown(self):
        assert _classify_gap(7200.0, seq_continuous=False) == UNKNOWN

    def test_boundary_network_max(self):
        assert _classify_gap(45.0, seq_continuous=True) == NETWORK_BLIP

    def test_boundary_recycle_max(self):
        assert _classify_gap(120.0, seq_continuous=True) == RECYCLE

    def test_boundary_divergence_min(self):
        assert _classify_gap(120.0, seq_continuous=False) == PUSH_DIVERGENCE

    def test_short_discontinuous_is_unknown(self):
        # short gap but seq numbers skipped — doesn't fit blip or recycle
        assert _classify_gap(20.0, seq_continuous=False) == UNKNOWN


# --- classify_strokes (integration) ---


class TestClassifyStrokes:
    def test_no_strokes(self):
        report = classify_strokes([])
        assert report.stall_count == 0
        assert report.stroke_count == 0

    def test_single_stroke(self):
        report = classify_strokes([_stroke(1, "2026-10-30T12:00:00+00:00")])
        assert report.stall_count == 0
        assert report.stroke_count == 1

    def test_continuous_no_gap(self):
        strokes = [
            _stroke(1, "2026-10-30T12:00:00+00:00"),
            _stroke(2, "2026-10-30T12:00:15+00:00"),
            _stroke(3, "2026-10-30T12:00:30+00:00"),
        ]
        report = classify_strokes(strokes)
        assert report.stall_count == 0

    def test_detects_network_blip(self):
        # 30s gap with continuous seq → network blip
        strokes = [
            _stroke(100, "2026-10-30T12:00:00+00:00"),
            _stroke(101, "2026-10-30T12:00:30+00:00"),
        ]
        report = classify_strokes(strokes)
        assert report.stall_count == 1
        assert report.stalls[0].category == NETWORK_BLIP
        assert report.stalls[0].seq_continuous is True

    def test_detects_recycle(self):
        # 60s gap with continuous seq → recycle
        strokes = [
            _stroke(200, "2026-10-30T12:00:00+00:00"),
            _stroke(201, "2026-10-30T12:01:00+00:00"),
        ]
        report = classify_strokes(strokes)
        assert report.stall_count == 1
        assert report.stalls[0].category == RECYCLE

    def test_detects_push_divergence(self):
        # 10 min gap with seq skip → push divergence
        strokes = [
            _stroke(300, "2026-10-30T12:00:00+00:00"),
            _stroke(305, "2026-10-30T12:10:00+00:00"),
        ]
        report = classify_strokes(strokes)
        assert report.stall_count == 1
        assert report.stalls[0].category == PUSH_DIVERGENCE
        assert report.stalls[0].seq_continuous is False

    def test_detects_unknown_long_gap(self):
        # 2 hour gap → unknown
        strokes = [
            _stroke(400, "2026-10-30T12:00:00+00:00"),
            _stroke(410, "2026-10-30T14:00:00+00:00"),
        ]
        report = classify_strokes(strokes)
        assert report.stall_count == 1
        assert report.stalls[0].category == UNKNOWN

    def test_multiple_stalls(self):
        strokes = [
            _stroke(1, "2026-10-30T12:00:00+00:00"),
            _stroke(2, "2026-10-30T12:00:35+00:00"),   # 35s blip
            _stroke(3, "2026-10-30T12:01:35+00:00"),   # 60s recycle
            _stroke(8, "2026-10-30T12:11:35+00:00"),   # 10min divergence
        ]
        report = classify_strokes(strokes)
        assert report.stall_count == 3
        cats = [s.category for s in report.stalls]
        assert NETWORK_BLIP in cats
        assert RECYCLE in cats
        assert PUSH_DIVERGENCE in cats

    def test_custom_gap_threshold(self):
        strokes = [
            _stroke(1, "2026-10-30T12:00:00+00:00"),
            _stroke(2, "2026-10-30T12:00:10+00:00"),  # 10s — below default
        ]
        # default threshold (30s) → no stall
        assert classify_strokes(strokes).stall_count == 0
        # lower threshold → detects it
        report = classify_strokes(strokes, gap_threshold=5.0)
        assert report.stall_count == 1

    def test_malformed_timestamps_skipped(self):
        strokes = [
            _stroke(1, "2026-10-30T12:00:00+00:00"),
            _stroke(2, "not-a-date"),
            _stroke(3, "2026-10-30T12:05:00+00:00"),
        ]
        report = classify_strokes(strokes)
        # the gap between stroke 1 and 3 is 5 min, but stroke 2 has bad ts
        # so only the gap from 1→bad and bad→3 are checked; bad→3 is skipped
        # stroke 1→2 has bad ts so skipped; 2→3 has bad ts so skipped
        # Actually: 1→2 (bad ts, skip), 2→3 (bad ts, skip) → 0 stalls
        assert report.stall_count == 0

    def test_total_gap_seconds_accumulates(self):
        strokes = [
            _stroke(1, "2026-10-30T12:00:00+00:00"),
            _stroke(2, "2026-10-30T12:01:00+00:00"),   # 60s
            _stroke(3, "2026-10-30T12:03:00+00:00"),   # 120s
        ]
        report = classify_strokes(strokes)
        assert report.total_gap_seconds == 180.0


# --- StallReport properties ---


class TestStallReport:
    def test_category_counts(self):
        report = StallReport(stalls=[
            Stall(1, 2, 30, "", NETWORK_BLIP, True),
            Stall(2, 3, 60, "", RECYCLE, True),
            Stall(3, 4, 35, "", NETWORK_BLIP, True),
        ])
        assert report.category_counts == {NETWORK_BLIP: 2, RECYCLE: 1}

    def test_longest_stall(self):
        report = StallReport(stalls=[
            Stall(1, 2, 30, "", NETWORK_BLIP, True),
            Stall(5, 10, 600, "", PUSH_DIVERGENCE, False),
            Stall(10, 11, 90, "", RECYCLE, True),
        ])
        assert report.longest_stall.gap_seconds == 600

    def test_empty_report_longest_is_none(self):
        report = StallReport()
        assert report.longest_stall is None

    def test_uptime_fraction(self):
        report = StallReport(
            stalls=[Stall(1, 2, 60, "", RECYCLE, True)],
            total_gap_seconds=60,
            stroke_count=100,
        )
        # total_span ≈ 60 + 100*15 = 1560
        # uptime ≈ 1 - 60/1560 ≈ 0.9615
        assert 0.96 < report.uptime_fraction < 0.97

    def test_uptime_fraction_no_strokes(self):
        report = StallReport(stroke_count=0)
        assert report.uptime_fraction == 1.0


# --- summarize ---


class TestSummarize:
    def test_no_stalls(self):
        report = StallReport(stroke_count=50)
        assert "no stalls" in summarize(report)

    def test_with_stalls(self):
        report = StallReport(
            stalls=[
                Stall(1, 2, 30, "", NETWORK_BLIP, True),
                Stall(5, 10, 600, "", PUSH_DIVERGENCE, False),
            ],
            total_gap_seconds=630,
            stroke_count=200,
        )
        s = summarize(report)
        assert "2 stalls" in s
        assert "200 strokes" in s
        assert "longest: 600s" in s


# --- Stall dataclass ---


class TestStall:
    def test_seq_gap(self):
        s = Stall(10, 15, 300, "", PUSH_DIVERGENCE, False)
        assert s.seq_gap == 5

    def test_to_dict(self):
        s = Stall(1, 2, 30.5, "2026-10-30T12:00:30Z", NETWORK_BLIP, True)
        d = s.to_dict()
        assert d["seq_before"] == 1
        assert d["seq_after"] == 2
        assert d["gap_seconds"] == 30.5
        assert d["category"] == NETWORK_BLIP
        assert d["seq_continuous"] is True
