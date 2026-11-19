"""Tests for iamai.stroke_burst_analyzer — burst pattern analysis."""

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from iamai.stroke_burst_analyzer import (
    BurstReport,
    analyse_bursts,
    analyse_strokes_file,
    _burstiness_index,
    _compute_gaps,
    _detect_bursts,
    _detect_silences,
    _extract_timestamps,
    _regularity_score,
    DEFAULT_BURST_THRESHOLD,
    DEFAULT_SILENCE_THRESHOLD,
    DEFAULT_IDEAL_CADENCE,
)


# ── helpers ────────────────────────────────────────────────────────────

def _stroke(at_iso: str, seq: int = 1, kind: str = "thought") -> dict:
    return {"seq": seq, "at": at_iso, "kind": kind, "text": "sample stroke"}


def _stroke_ts(ts: float, seq: int = 1) -> dict:
    return {"seq": seq, "ts": ts, "kind": "note", "text": "ts stroke"}


def _make_strokes_iso(intervals_sec: list[float], start: str = "2026-01-01T00:00:00+00:00") -> list[dict]:
    """Build a list of strokes with given intervals (seconds) between them."""
    base = datetime.fromisoformat(start)
    strokes = [_stroke(base.isoformat(), seq=0)]
    current = base
    for i, gap in enumerate(intervals_sec, 1):
        current = current + timedelta(seconds=gap)
        strokes.append(_stroke(current.isoformat(), seq=i))
    return strokes


def _make_strokes_ts(intervals_sec: list[float], start: float = 1000.0) -> list[dict]:
    """Build strokes using numeric timestamps."""
    strokes = [_stroke_ts(start, seq=0)]
    current = start
    for i, gap in enumerate(intervals_sec, 1):
        current += gap
        strokes.append(_stroke_ts(current, seq=i))
    return strokes


def _write_jsonl(strokes: list, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for s in strokes:
            fh.write(json.dumps(s) + "\n")


# ── _extract_timestamps ──────────────────────────────────────────────

class TestExtractTimestamps:
    def test_iso_format(self):
        strokes = [_stroke("2026-01-01T00:00:00+00:00"), _stroke("2026-01-01T00:01:00+00:00")]
        ts = _extract_timestamps(strokes)
        assert len(ts) == 2
        assert ts[1] - ts[0] == pytest.approx(60.0, abs=1)

    def test_numeric_ts(self):
        strokes = [_stroke_ts(1000.0), _stroke_ts(1015.0)]
        ts = _extract_timestamps(strokes)
        assert ts == [1000.0, 1015.0]

    def test_mixed_prefers_ts(self):
        strokes = [{"seq": 1, "ts": 500.0, "at": "2026-01-01T00:00:00+00:00"}]
        ts = _extract_timestamps(strokes)
        assert ts == [500.0]

    def test_unparseable_skipped(self):
        strokes = [{"seq": 1, "at": "not-a-date"}, _stroke_ts(100.0)]
        ts = _extract_timestamps(strokes)
        assert ts == [100.0]

    def test_sorted_output(self):
        strokes = [_stroke_ts(300.0), _stroke_ts(100.0), _stroke_ts(200.0)]
        ts = _extract_timestamps(strokes)
        assert ts == [100.0, 200.0, 300.0]

    def test_empty(self):
        assert _extract_timestamps([]) == []

    def test_z_suffix(self):
        strokes = [_stroke("2026-06-15T12:00:00Z")]
        ts = _extract_timestamps(strokes)
        assert len(ts) == 1


# ── _compute_gaps ────────────────────────────────────────────────────

class TestComputeGaps:
    def test_basic(self):
        assert _compute_gaps([10, 25, 40]) == [15, 15]

    def test_single(self):
        assert _compute_gaps([100]) == []

    def test_empty(self):
        assert _compute_gaps([]) == []

    def test_zero_gap_included(self):
        assert _compute_gaps([10, 10, 20]) == [0, 10]

    def test_negative_gap_skipped(self):
        # shouldn't happen with sorted input, but defensive
        assert _compute_gaps([10, 5, 20]) == [15]


# ── _detect_bursts ───────────────────────────────────────────────────

class TestDetectBursts:
    def test_all_within_threshold(self):
        gaps = [5, 5, 5, 5]
        bursts = _detect_bursts(gaps, threshold=10)
        assert bursts == [5]  # one big burst of 5 strokes

    def test_all_above_threshold(self):
        gaps = [30, 30, 30]
        bursts = _detect_bursts(gaps, threshold=10)
        assert bursts == [1, 1, 1, 1]  # four isolated strokes

    def test_mixed(self):
        gaps = [5, 5, 60, 3, 3, 60, 8]
        bursts = _detect_bursts(gaps, threshold=10)
        assert bursts == [3, 3, 2]  # two bursts of 3, one burst of 2

    def test_empty_gaps(self):
        assert _detect_bursts([], threshold=10) == []

    def test_single_gap_burst(self):
        assert _detect_bursts([5], threshold=10) == [2]

    def test_single_gap_isolated(self):
        assert _detect_bursts([50], threshold=10) == [1, 1]

    def test_boundary_at_threshold(self):
        # gap == threshold is NOT in a burst (burst = gap < threshold)
        gaps = [10, 10, 10]
        bursts = _detect_bursts(gaps, threshold=10)
        assert bursts == [1, 1, 1, 1]


# ── _detect_silences ─────────────────────────────────────────────────

class TestDetectSilences:
    def test_basic(self):
        gaps = [5, 200, 10, 300, 15]
        silences = _detect_silences(gaps, threshold=120)
        assert silences == [200, 300]

    def test_none(self):
        gaps = [5, 10, 15]
        assert _detect_silences(gaps, threshold=120) == []

    def test_all(self):
        gaps = [200, 300]
        assert _detect_silences(gaps, threshold=120) == [200, 300]

    def test_boundary(self):
        # gap == threshold is NOT a silence (silence = gap > threshold)
        gaps = [120]
        assert _detect_silences(gaps, threshold=120) == []


# ── _burstiness_index ────────────────────────────────────────────────

class TestBurstinessIndex:
    def test_zero_cv(self):
        assert _burstiness_index(0) == 0.0

    def test_negative_cv(self):
        assert _burstiness_index(-1) == 0.0

    def test_increasing(self):
        vals = [_burstiness_index(cv) for cv in [0.1, 0.5, 1.0, 2.0, 5.0]]
        assert all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))

    def test_bounded(self):
        for cv in [0, 0.01, 0.5, 1, 10, 100]:
            bi = _burstiness_index(cv)
            assert 0.0 <= bi <= 1.0

    def test_high_cv_near_one(self):
        assert _burstiness_index(100) > 0.99


# ── _regularity_score ────────────────────────────────────────────────

class TestRegularityScore:
    def test_perfect_cadence(self):
        gaps = [15, 15, 15, 15]
        assert _regularity_score(gaps, ideal_cadence=15) == 1.0

    def test_all_outside(self):
        gaps = [200, 300, 400]
        assert _regularity_score(gaps, ideal_cadence=15) == 0.0

    def test_half_within(self):
        gaps = [15, 200, 14, 300]
        score = _regularity_score(gaps, ideal_cadence=15)
        assert score == pytest.approx(0.5, abs=0.01)

    def test_empty(self):
        assert _regularity_score([], ideal_cadence=15) == 0.0

    def test_boundary_values(self):
        # exactly at 50% and 150% of ideal
        gaps = [7.5, 22.5]
        score = _regularity_score(gaps, ideal_cadence=15)
        assert score == 1.0  # boundaries are inclusive


# ── analyse_bursts (integration) ─────────────────────────────────────

class TestAnalyseBursts:
    def test_empty_input(self):
        report = analyse_bursts([])
        assert report.total_strokes == 0
        assert report.burstiness_index == 0.0
        assert report.classify() == "insufficient_data"

    def test_single_stroke(self):
        strokes = [_stroke_ts(1000.0)]
        report = analyse_bursts(strokes)
        assert report.total_strokes == 1
        assert report.classify() == "insufficient_data"

    def test_steady_cadence(self):
        """15-second intervals → steady, low burstiness."""
        strokes = _make_strokes_ts([15] * 20)
        report = analyse_bursts(strokes)
        assert report.total_strokes == 21
        assert report.total_gaps == 20
        assert report.mean_gap == pytest.approx(15.0, abs=0.1)
        assert report.cv == pytest.approx(0.0, abs=0.01)
        assert report.burstiness_index < 0.30
        assert report.regularity_score == pytest.approx(1.0, abs=0.01)
        assert report.classify() == "steady"

    def test_burst_then_silence(self):
        """5 rapid strokes, then a 5-minute silence, then 5 more."""
        intervals = [3, 3, 3, 3, 300, 3, 3, 3, 3]
        strokes = _make_strokes_ts(intervals)
        report = analyse_bursts(
            strokes,
            burst_threshold=20,
            silence_threshold=120,
        )
        assert report.burst_count >= 1
        assert report.silence_count >= 1
        assert report.longest_silence == pytest.approx(300, abs=1)
        assert report.largest_burst >= 4

    def test_severe_bursts(self):
        """Highly variable gaps → high burstiness."""
        intervals = [1, 1, 1, 1, 500, 1, 1, 800, 2, 1]
        strokes = _make_strokes_ts(intervals)
        report = analyse_bursts(strokes)
        assert report.burstiness_index > 0.60
        assert report.classify() == "severe_bursts"

    def test_moderate_bursts(self):
        """Some variability but not extreme."""
        intervals = [10, 20, 30, 15, 25, 20, 10, 30, 15, 20]
        strokes = _make_strokes_ts(intervals)
        report = analyse_bursts(strokes)
        assert report.total_strokes == 11
        # cv should be moderate
        assert 0.1 < report.cv < 1.0

    def test_iso_timestamps(self):
        """Works with ISO-8601 at field."""
        strokes = _make_strokes_iso([15, 15, 15, 15])
        report = analyse_bursts(strokes)
        assert report.total_strokes == 5
        assert report.mean_gap == pytest.approx(15.0, abs=1.0)

    def test_to_dict(self):
        strokes = _make_strokes_ts([15] * 5)
        report = analyse_bursts(strokes)
        d = report.to_dict()
        assert "total_strokes" in d
        assert "burstiness_index" in d
        assert "classification" in d
        assert d["classification"] == "steady"
        assert isinstance(d["burst_sizes"], list)


# ── analyse_strokes_file ─────────────────────────────────────────────

class TestAnalyseStrokesFile:
    def test_from_file(self, tmp_path):
        strokes = _make_strokes_ts([15] * 10)
        p = tmp_path / "strokes.jsonl"
        _write_jsonl(strokes, p)
        report = analyse_strokes_file(p)
        assert report.total_strokes == 11
        assert report.classify() == "steady"

    def test_missing_file(self, tmp_path):
        report = analyse_strokes_file(tmp_path / "nonexistent.jsonl")
        assert report.total_strokes == 0

    def test_malformed_lines(self, tmp_path):
        p = tmp_path / "bad.jsonl"
        p.write_text("not json\n{invalid\n" + json.dumps(_stroke_ts(1000)) + "\n")
        report = analyse_strokes_file(p)
        assert report.total_strokes == 1

    def test_custom_thresholds(self, tmp_path):
        strokes = _make_strokes_ts([5, 5, 5, 50, 5, 5])
        p = tmp_path / "s.jsonl"
        _write_jsonl(strokes, p)
        report = analyse_strokes_file(
            p,
            burst_threshold=10,
            silence_threshold=40,
            ideal_cadence=5,
        )
        assert report.silence_count >= 1
        assert report.burst_count >= 1


# ── classify edge cases ──────────────────────────────────────────────

class TestClassify:
    def test_steady(self):
        r = BurstReport(total_strokes=10, burstiness_index=0.1)
        assert r.classify() == "steady"

    def test_moderate(self):
        r = BurstReport(total_strokes=10, burstiness_index=0.45)
        assert r.classify() == "moderate_bursts"

    def test_severe(self):
        r = BurstReport(total_strokes=10, burstiness_index=0.80)
        assert r.classify() == "severe_bursts"

    def test_boundary_steady(self):
        r = BurstReport(total_strokes=10, burstiness_index=0.29)
        assert r.classify() == "steady"

    def test_boundary_moderate(self):
        r = BurstReport(total_strokes=10, burstiness_index=0.30)
        assert r.classify() == "moderate_bursts"

    def test_boundary_severe(self):
        r = BurstReport(total_strokes=10, burstiness_index=0.60)
        assert r.classify() == "severe_bursts"

    def test_insufficient(self):
        r = BurstReport(total_strokes=1)
        assert r.classify() == "insufficient_data"
