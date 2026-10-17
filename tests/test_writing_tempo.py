"""Tests for iamai.writing_tempo — stroke rhythm analysis."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from iamai.writing_tempo import (
    TempoReport,
    _parse_iso,
    _intervals,
    _percentile,
    _compute_score,
    tempo_report,
    verdict,
    tempo_summary,
    tempo_from_jsonl,
    find_stalls,
    DEFAULT_TARGET_INTERVAL,
    DEFAULT_STALL_THRESHOLD,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _stamps(n: int, interval: float = 30.0, start: str = "2026-10-17T00:00:00+00:00") -> list[str]:
    """Generate n evenly-spaced ISO timestamps."""
    base = datetime.fromisoformat(start.replace("Z", "+00:00"))
    return [
        (base + timedelta(seconds=i * interval)).isoformat()
        for i in range(n)
    ]


def _stamps_with_gaps(intervals: list[float], start: str = "2026-10-17T00:00:00+00:00") -> list[str]:
    """Generate timestamps from a list of intervals (seconds)."""
    base = datetime.fromisoformat(start.replace("Z", "+00:00"))
    result = [base.isoformat()]
    current = base
    for gap in intervals:
        current = current + timedelta(seconds=gap)
        result.append(current.isoformat())
    return result


def _make_jsonl(tmp_path: Path, stamps: list[str]) -> Path:
    """Write a minimal strokes JSONL file."""
    p = tmp_path / "strokes.jsonl"
    with open(p, "w", encoding="utf-8") as fh:
        for i, ts in enumerate(stamps):
            fh.write(json.dumps({"seq": i + 1, "at": ts, "kind": "thought", "text": f"stroke {i+1}"}) + "\n")
    return p


# ===========================================================================
# _parse_iso
# ===========================================================================


class TestParseIso:
    def test_standard_offset(self):
        dt = _parse_iso("2026-10-17T12:00:00+08:00")
        assert dt.hour == 12
        assert dt.utcoffset() == timedelta(hours=8)

    def test_z_suffix(self):
        dt = _parse_iso("2026-10-17T04:00:00Z")
        assert dt.hour == 4
        assert dt.utcoffset() == timedelta(0)

    def test_utc_offset_zero(self):
        dt = _parse_iso("2026-10-17T04:00:00+00:00")
        assert dt.utcoffset() == timedelta(0)


# ===========================================================================
# _intervals
# ===========================================================================


class TestIntervals:
    def test_basic(self):
        stamps = _stamps(4, interval=30.0)
        ivs = _intervals(stamps)
        assert len(ivs) == 3
        assert all(iv == 30.0 for iv in ivs)

    def test_single_stamp(self):
        assert _intervals(_stamps(1)) == []

    def test_empty(self):
        assert _intervals([]) == []

    def test_variable_gaps(self):
        stamps = _stamps_with_gaps([10, 20, 600])
        ivs = _intervals(stamps)
        assert ivs == [10.0, 20.0, 600.0]

    def test_order_preserved(self):
        stamps = _stamps_with_gaps([5, 15, 25, 35])
        ivs = _intervals(stamps)
        assert ivs == [5.0, 15.0, 25.0, 35.0]


# ===========================================================================
# _percentile
# ===========================================================================


class TestPercentile:
    def test_p50_equals_median(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert _percentile(data, 50) == 3.0

    def test_p10(self):
        data = list(range(1, 11))  # 1..10
        assert _percentile(data, 10) == pytest.approx(1.9)

    def test_p90(self):
        data = list(range(1, 11))
        assert _percentile(data, 90) == pytest.approx(9.1)

    def test_empty(self):
        assert _percentile([], 50) == 0.0

    def test_single_element(self):
        assert _percentile([42.0], 50) == 42.0
        assert _percentile([42.0], 10) == 42.0
        assert _percentile([42.0], 90) == 42.0


# ===========================================================================
# _compute_score
# ===========================================================================


class TestComputeScore:
    def test_perfect_cadence(self):
        """All intervals exactly at target → score 1.0."""
        ivs = [30.0] * 100
        assert _compute_score(ivs, 30.0, 300.0) == 1.0

    def test_empty_intervals(self):
        assert _compute_score([], 30.0, 300.0) == 0.0

    def test_single_stall_deduction(self):
        """One stall → score reduced by 0.05."""
        ivs = [30.0] * 99 + [600.0]
        score = _compute_score(ivs, 30.0, 300.0)
        # perfect would be 1.0 minus small variance/drift, minus 0.05 stall
        assert score < 0.96

    def test_many_stalls_capped(self):
        """20 stalls → stall penalty capped at 0.4."""
        ivs = [600.0] * 20
        score = _compute_score(ivs, 30.0, 300.0)
        # variance is 0 (all same), drift is huge, stalls capped at 0.4
        assert score >= 0.0

    def test_high_variance(self):
        """Wildly varying intervals → low score."""
        ivs = [5.0, 120.0, 10.0, 300.0, 15.0, 500.0] * 10
        score = _compute_score(ivs, 30.0, 300.0)
        assert score < 0.5

    def test_drift_penalty(self):
        """Mean far from target → drift deduction."""
        ivs = [90.0] * 100  # mean=90, target=30
        score = _compute_score(ivs, 30.0, 300.0)
        # drift = |90-30|/30 = 2.0, capped at 0.2
        assert score <= 0.8


# ===========================================================================
# tempo_report
# ===========================================================================


class TestTempoReport:
    def test_empty(self):
        r = tempo_report([])
        assert r.total_strokes == 0
        assert r.score == 1.0  # default, not enough data

    def test_single_stamp(self):
        r = tempo_report(_stamps(1))
        assert r.total_strokes == 1
        assert r.total_intervals == 0

    def test_perfect_cadence(self):
        stamps = _stamps(100, interval=30.0)
        r = tempo_report(stamps)
        assert r.total_strokes == 100
        assert r.total_intervals == 99
        assert r.mean_interval == 30.0
        assert r.median_interval == 30.0
        assert r.stdev_interval == 0.0
        assert r.stall_count == 0
        assert r.score == 1.0

    def test_with_stalls(self):
        intervals = [30.0] * 50 + [600.0] + [30.0] * 48
        stamps = _stamps_with_gaps(intervals)
        r = tempo_report(stamps)
        assert r.stall_count == 1
        assert len(r.stall_gaps) == 1
        assert r.stall_gaps[0] == 600.0

    def test_multiple_stalls(self):
        intervals = [30.0] * 10 + [400.0] + [30.0] * 10 + [500.0] + [30.0] * 10
        stamps = _stamps_with_gaps(intervals)
        r = tempo_report(stamps)
        assert r.stall_count == 2

    def test_recent_vs_baseline(self):
        """Recent intervals are slower than baseline → drift > 1."""
        baseline = [25.0] * 200
        recent = [45.0] * 50
        intervals = baseline + recent
        stamps = _stamps_with_gaps(intervals)
        r = tempo_report(stamps)
        assert r.recent_mean == 45.0
        assert r.baseline_mean == 25.0
        assert r.drift_ratio == pytest.approx(1.8)

    def test_percentiles(self):
        intervals = list(range(1, 101))  # 1..100
        stamps = _stamps_with_gaps([float(x) for x in intervals])
        r = tempo_report(stamps)
        assert r.p10_interval == pytest.approx(10.9, abs=0.5)
        assert r.p90_interval == pytest.approx(90.1, abs=0.5)

    def test_min_max(self):
        intervals = [5.0, 30.0, 60.0, 120.0]
        stamps = _stamps_with_gaps(intervals)
        r = tempo_report(stamps)
        assert r.min_interval == 5.0
        assert r.max_interval == 120.0

    def test_score_range(self):
        stamps = _stamps(100, interval=30.0)
        r = tempo_report(stamps)
        assert 0.0 <= r.score <= 1.0

    def test_is_stalling_property(self):
        intervals = [30.0] * 10 + [600.0]
        stamps = _stamps_with_gaps(intervals)
        r = tempo_report(stamps)
        assert r.is_stalling is True

    def test_is_dead_property(self):
        r = tempo_report([])
        assert r.is_dead is True


# ===========================================================================
# verdict
# ===========================================================================


class TestVerdict:
    def test_healthy(self):
        r = TempoReport(total_strokes=100, score=0.95, stall_count=0)
        assert verdict(r) == "healthy"

    def test_wobbling(self):
        r = TempoReport(total_strokes=100, score=0.5, stall_count=0)
        assert verdict(r) == "wobbling"

    def test_stalling(self):
        r = TempoReport(total_strokes=100, score=0.8, stall_count=3)
        assert verdict(r) == "stalling"

    def test_dead_too_few_strokes(self):
        r = TempoReport(total_strokes=1, score=0.9)
        assert verdict(r) == "dead"

    def test_dead_low_score(self):
        r = TempoReport(total_strokes=100, score=0.1, stall_count=0)
        assert verdict(r) == "dead"

    def test_stalling_overrides_wobbling(self):
        r = TempoReport(total_strokes=100, score=0.5, stall_count=1)
        assert verdict(r) == "stalling"

    def test_boundary_07_is_wobbling(self):
        r = TempoReport(total_strokes=100, score=0.69, stall_count=0)
        assert verdict(r) == "wobbling"

    def test_boundary_07_exact_is_healthy(self):
        r = TempoReport(total_strokes=100, score=0.7, stall_count=0)
        assert verdict(r) == "healthy"


# ===========================================================================
# tempo_summary
# ===========================================================================


class TestTempoSummary:
    def test_healthy_summary(self):
        r = TempoReport(
            total_strokes=100,
            mean_interval=30.5,
            median_interval=30.0,
            stall_count=0,
            score=0.95,
        )
        s = tempo_summary(r)
        assert "healthy" in s
        assert "100 strokes" in s
        assert "30.5s" in s
        assert "0 stall(s)" in s
        assert "0.95" in s

    def test_stalling_summary(self):
        r = TempoReport(
            total_strokes=50,
            mean_interval=45.0,
            median_interval=30.0,
            stall_count=2,
            score=0.75,
        )
        s = tempo_summary(r)
        assert "stalling" in s
        assert "2 stall(s)" in s


# ===========================================================================
# tempo_from_jsonl
# ===========================================================================


class TestTempoFromJsonl:
    def test_basic_read(self, tmp_path):
        stamps = _stamps(50, interval=30.0)
        p = _make_jsonl(tmp_path, stamps)
        r = tempo_from_jsonl(p)
        assert r.total_strokes == 50
        assert r.mean_interval == 30.0

    def test_missing_file(self, tmp_path):
        r = tempo_from_jsonl(tmp_path / "nonexistent.jsonl")
        assert r.total_strokes == 0

    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        r = tempo_from_jsonl(p)
        assert r.total_strokes == 0

    def test_malformed_lines(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            '{"seq": 1, "at": "2026-10-17T00:00:00+00:00", "kind": "thought"}',
            "not json at all",
            "",
            '{"seq": 2, "at": "2026-10-17T00:00:30+00:00", "kind": "thought"}',
            '{"seq": 3, "at": "2026-10-17T00:01:00+00:00", "kind": "thought"}',
        ]
        p.write_text("\n".join(lines))
        r = tempo_from_jsonl(p)
        assert r.total_strokes == 3

    def test_max_strokes(self, tmp_path):
        stamps = _stamps(200, interval=30.0)
        p = _make_jsonl(tmp_path, stamps)
        r = tempo_from_jsonl(p, max_strokes=50)
        assert r.total_strokes == 50

    def test_missing_at_field(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text('{"seq": 1, "kind": "thought"}\n')
        r = tempo_from_jsonl(p)
        assert r.total_strokes == 0

    def test_custom_target(self, tmp_path):
        stamps = _stamps(50, interval=60.0)
        p = _make_jsonl(tmp_path, stamps)
        # with default target=30, 60s intervals should score lower
        r_default = tempo_from_jsonl(p)
        r_custom = tempo_from_jsonl(p, target=60.0)
        assert r_custom.score > r_default.score


# ===========================================================================
# find_stalls
# ===========================================================================


class TestFindStalls:
    def test_no_stalls(self):
        stamps = _stamps(20, interval=30.0)
        assert find_stalls(stamps) == []

    def test_single_stall(self):
        intervals = [30.0] * 5 + [600.0] + [30.0] * 5
        stamps = _stamps_with_gaps(intervals)
        stalls = find_stalls(stamps)
        assert len(stalls) == 1
        assert stalls[0]["seconds"] == 600.0
        assert "from" in stalls[0]
        assert "to" in stalls[0]

    def test_multiple_stalls(self):
        intervals = [30.0, 400.0, 30.0, 500.0, 30.0]
        stamps = _stamps_with_gaps(intervals)
        stalls = find_stalls(stamps)
        assert len(stalls) == 2
        assert stalls[0]["seconds"] == 400.0
        assert stalls[1]["seconds"] == 500.0

    def test_custom_threshold(self):
        intervals = [30.0, 100.0, 30.0]
        stamps = _stamps_with_gaps(intervals)
        assert len(find_stalls(stamps, stall_threshold=300.0)) == 0
        assert len(find_stalls(stamps, stall_threshold=50.0)) == 1

    def test_empty_input(self):
        assert find_stalls([]) == []

    def test_single_stamp(self):
        assert find_stalls(_stamps(1)) == []

    def test_boundary_exact(self):
        """Interval exactly at threshold should NOT be a stall."""
        intervals = [300.0]
        stamps = _stamps_with_gaps(intervals)
        assert find_stalls(stamps, stall_threshold=300.0) == []

    def test_just_over_threshold(self):
        intervals = [300.1]
        stamps = _stamps_with_gaps(intervals)
        stalls = find_stalls(stamps, stall_threshold=300.0)
        assert len(stalls) == 1


# ===========================================================================
# integration
# ===========================================================================


class TestIntegration:
    def test_full_lifecycle(self, tmp_path):
        """Simulate: healthy writing → stall → recovery → check."""
        healthy = _stamps(50, interval=30.0)
        # 10-minute stall
        stall_start = datetime.fromisoformat(healthy[-1])
        stall_end = stall_start + timedelta(seconds=600)
        # resume writing
        recovery = [
            (stall_end + timedelta(seconds=i * 30)).isoformat()
            for i in range(50)
        ]
        all_stamps = healthy + recovery

        r = tempo_report(all_stamps)
        assert r.total_strokes == 100
        assert r.stall_count == 1
        assert verdict(r) == "stalling"
        assert r.score < 1.0
        assert r.score > 0.0

        # check find_stalls
        stalls = find_stalls(all_stamps)
        assert len(stalls) == 1
        assert stalls[0]["seconds"] == 600.0

    def test_jsonl_round_trip(self, tmp_path):
        stamps = _stamps(80, interval=28.0)
        p = _make_jsonl(tmp_path, stamps)
        r = tempo_from_jsonl(p, target=28.0)
        assert r.total_strokes == 80
        assert r.mean_interval == 28.0
        assert verdict(r) == "healthy"
        s = tempo_summary(r)
        assert "healthy" in s
