"""Tests for iamai/repo_reliability.py — silence detection, statistics, trend."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.repo_reliability import (  # noqa: E402
    ReliabilityReport,
    SilencePeriod,
    analyze,
    compute_trend,
    find_silences,
    format_text,
)


# ---------------------------------------------------------------------------
# find_silences
# ---------------------------------------------------------------------------

class TestFindSilences:
    def test_empty(self):
        assert find_silences([]) == []

    def test_single_commit(self):
        assert find_silences([1_000_000.0]) == []

    def test_no_gaps(self):
        ts = [100.0, 200.0, 300.0, 400.0]
        assert find_silences(ts, threshold=1800) == []

    def test_one_silence(self):
        ts = [100.0, 200.0, 4000.0, 4100.0]
        silences = find_silences(ts, threshold=1800)
        assert len(silences) == 1
        assert silences[0].before == 200.0
        assert silences[0].after == 4000.0
        assert silences[0].duration == 3800.0

    def test_multiple_silences(self):
        ts = [0.0, 100.0, 5000.0, 5100.0, 10000.0, 10100.0]
        silences = find_silences(ts, threshold=1800)
        assert len(silences) == 2
        assert silences[0].duration == 4900.0
        assert silences[1].duration == 4900.0

    def test_exact_threshold(self):
        ts = [0.0, 3600.0]
        silences = find_silences(ts, threshold=3600)
        assert len(silences) == 1
        assert silences[0].duration == 3600.0

    def test_below_threshold(self):
        ts = [0.0, 3599.0]
        assert find_silences(ts, threshold=3600) == []

    def test_custom_threshold(self):
        ts = [0.0, 100.0, 200.0, 500.0, 600.0]
        silences = find_silences(ts, threshold=150)
        assert len(silences) == 1
        assert silences[0].duration == 300.0


# ---------------------------------------------------------------------------
# compute_trend
# ---------------------------------------------------------------------------

class TestComputeTrend:
    def test_insufficient_data(self):
        assert compute_trend([]) == "insufficient"
        assert compute_trend([SilencePeriod(0, 100, 100)]) == "insufficient"
        assert compute_trend([
            SilencePeriod(0, 100, 100),
            SilencePeriod(200, 300, 100),
            SilencePeriod(400, 500, 100),
        ]) == "insufficient"

    def test_stable(self):
        silences = [
            SilencePeriod(0, 1000, 1000),
            SilencePeriod(2000, 3000, 1000),
            SilencePeriod(4000, 5000, 1000),
            SilencePeriod(6000, 7000, 1000),
        ]
        assert compute_trend(silences) == "stable"

    def test_improving(self):
        silences = [
            SilencePeriod(0, 5000, 5000),
            SilencePeriod(10000, 15000, 5000),
            SilencePeriod(20000, 21000, 1000),
            SilencePeriod(25000, 25500, 500),
        ]
        assert compute_trend(silences) == "improving"

    def test_degrading(self):
        silences = [
            SilencePeriod(0, 500, 500),
            SilencePeriod(1000, 1500, 500),
            SilencePeriod(3000, 6000, 3000),
            SilencePeriod(10000, 15000, 5000),
        ]
        assert compute_trend(silences) == "degrading"


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_insufficient_data_empty(self):
        report = analyze([])
        assert report.total_commits == 0
        assert report.trend == "insufficient"
        assert not report.healthy
        assert "insufficient" in report.message

    def test_insufficient_data_single(self):
        report = analyze([1000.0])
        assert report.total_commits == 1
        assert report.trend == "insufficient"

    def test_no_silences(self):
        ts = [0.0, 60.0, 120.0, 180.0, 240.0]
        report = analyze(ts, threshold=3600)
        assert report.total_silences == 0
        assert report.healthy
        assert "no silences" in report.message
        assert report.mtbs is None

    def test_with_silences_healthy(self):
        # Stable silences: all roughly the same duration
        ts = [0.0, 100.0, 5000.0, 5100.0, 10000.0, 10100.0, 15000.0, 15100.0]
        report = analyze(ts, threshold=1800)
        assert report.total_silences == 3
        assert report.healthy  # stable trend
        assert report.mean_silence == pytest.approx(4900.0)
        assert report.max_silence == pytest.approx(4900.0)
        assert report.mtbs is not None

    def test_degrading_not_healthy(self):
        silences = [
            0.0, 100.0,       # gap 100
            200.0, 700.0,     # gap 500
            1000.0, 3000.0,   # gap 2000
            4000.0, 9000.0,   # gap 5000
        ]
        report = analyze(silences, threshold=250)
        assert report.total_silences >= 2
        assert report.trend == "degrading"
        assert not report.healthy

    def test_improving_is_healthy(self):
        silences = [
            0.0, 5000.0,      # gap 5000
            6000.0, 11000.0,  # gap 5000
            12000.0, 12500.0, # gap 500
            13000.0, 13100.0, # gap 100
        ]
        report = analyze(silences, threshold=250)
        assert report.trend == "improving"
        assert report.healthy


# ---------------------------------------------------------------------------
# ReliabilityReport dataclass
# ---------------------------------------------------------------------------

class TestReliabilityReport:
    def test_frozen(self):
        report = analyze([0.0, 100.0])
        with pytest.raises(AttributeError):
            report.healthy = False

    def test_as_dict(self):
        report = analyze([0.0, 100.0, 5000.0, 5100.0], threshold=1800)
        d = report.as_dict()
        assert "total_commits" in d
        assert "mean_silence" in d
        assert "trend" in d
        assert d["total_commits"] == 4

    def test_as_dict_no_silences(self):
        report = analyze([0.0, 100.0], threshold=3600)
        d = report.as_dict()
        assert d["total_silences"] == 0
        assert d["mean_silence"] == 0.0
        assert d["mtbs"] is None


# ---------------------------------------------------------------------------
# SilencePeriod dataclass
# ---------------------------------------------------------------------------

class TestSilencePeriod:
    def test_frozen(self):
        sp = SilencePeriod(0.0, 100.0, 100.0)
        with pytest.raises(AttributeError):
            sp.duration = 200.0

    def test_as_dict(self):
        sp = SilencePeriod(1000.0, 2000.0, 1000.0)
        d = sp.as_dict()
        assert d["before"] == 1000.0
        assert d["after"] == 2000.0
        assert d["duration"] == 1000.0


# ---------------------------------------------------------------------------
# format_text
# ---------------------------------------------------------------------------

class TestFormatText:
    def test_insufficient(self):
        report = analyze([])
        assert format_text(report) == "insufficient data"

    def test_clean(self):
        report = analyze([0.0, 100.0, 200.0], threshold=3600)
        text = format_text(report)
        assert "clean" in text
        assert "3 commits" in text

    def test_with_silences(self):
        report = analyze([0.0, 100.0, 5000.0, 5100.0], threshold=1800)
        text = format_text(report)
        assert "1 silences" in text
        assert "trend" in text
