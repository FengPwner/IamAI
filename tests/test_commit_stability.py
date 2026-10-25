"""Tests for iamai.commit_stability."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.commit_stability import (
    _commit_timestamps,
    _intervals,
    _mean,
    _std,
    commit_stability,
    stability_report,
)


# ---------------------------------------------------------------------------
# _commit_timestamps
# ---------------------------------------------------------------------------

class TestCommitTimestamps:
    def test_parses_output(self, tmp_path: Path):
        out = "1697529600\n1697529000\n1697528400\n"
        with patch("subprocess.check_output", return_value=out.encode()):
            ts = _commit_timestamps(tmp_path, count=3)
        assert ts == [1697529600.0, 1697529000.0, 1697528400.0]

    def test_empty_on_failure(self, tmp_path: Path):
        def fail(*a, **kw):
            raise subprocess.CalledProcessError(128, "git")

        with patch("subprocess.check_output", side_effect=fail):
            ts = _commit_timestamps(tmp_path)
        assert ts == []

    def test_empty_on_blank(self, tmp_path: Path):
        with patch("subprocess.check_output", return_value=b""):
            ts = _commit_timestamps(tmp_path)
        assert ts == []

    def test_skips_non_numeric(self, tmp_path: Path):
        out = "1697529600\nnot-a-number\n1697529000\n"
        with patch("subprocess.check_output", return_value=out.encode()):
            ts = _commit_timestamps(tmp_path, count=2)
        assert ts == [1697529600.0, 1697529000.0]


# ---------------------------------------------------------------------------
# _intervals
# ---------------------------------------------------------------------------

class TestIntervals:
    def test_newest_first(self):
        ts = [1000.0, 700.0, 400.0, 100.0]
        assert _intervals(ts) == [300.0, 300.0, 300.0]

    def test_single_timestamp(self):
        assert _intervals([1000.0]) == []

    def test_empty(self):
        assert _intervals([]) == []

    def test_two_timestamps(self):
        assert _intervals([1000.0, 500.0]) == [500.0]

    def test_irregular_gaps(self):
        ts = [1000.0, 900.0, 600.0, 100.0]
        assert _intervals(ts) == [100.0, 300.0, 500.0]


# ---------------------------------------------------------------------------
# _mean / _std
# ---------------------------------------------------------------------------

class TestMean:
    def test_simple(self):
        assert _mean([2, 4, 6]) == pytest.approx(4.0)

    def test_empty(self):
        assert _mean([]) == 0.0

    def test_single(self):
        assert _mean([7.0]) == pytest.approx(7.0)


class TestStd:
    def test_uniform(self):
        assert _std([5, 5, 5], 5.0) == pytest.approx(0.0)

    def test_known(self):
        # std of [1, 2, 3, 4] with sample variance: sqrt(5/3) ≈ 1.291
        mu = _mean([1, 2, 3, 4])
        assert _std([1, 2, 3, 4], mu) == pytest.approx(1.291, abs=0.01)

    def test_single_value(self):
        assert _std([42], 42.0) == 0.0

    def test_empty(self):
        assert _std([], 0.0) == 0.0


# ---------------------------------------------------------------------------
# commit_stability
# ---------------------------------------------------------------------------

class TestCommitStability:
    def test_perfectly_regular(self, tmp_path: Path):
        """All intervals equal → cv=0, stability=1, steady."""
        ts = "\n".join(str(int(1697529600 - i * 600)) for i in range(10))
        with patch("subprocess.check_output", return_value=ts.encode()):
            info = commit_stability(tmp_path, count=10)
        assert info["cv"] == 0.0
        assert info["stability"] == 1.0
        assert info["verdict"] == "steady"
        assert info["commits_inspected"] == 10

    def test_erratic(self, tmp_path: Path):
        """Highly variable intervals → high cv, erratic."""
        # Alternating 60s and 1800s gaps → very high cv
        base = 1697529600
        offsets = [0]
        for i in range(1, 12):
            offsets.append(offsets[-1] + (60 if i % 2 == 0 else 1800))
        ts = "\n".join(str(base - o) for o in offsets)
        with patch("subprocess.check_output", return_value=ts.encode()):
            info = commit_stability(tmp_path, count=12)
        assert info["cv"] > 0.7
        assert info["verdict"] == "erratic"
        assert info["stability"] < 0.3

    def test_wobbly(self, tmp_path: Path):
        """Moderately variable intervals → wobbly."""
        base = 1697529600
        # Gaps: 200, 800, 200, 800, ... → cv ≈ 0.64
        offsets = [0]
        for i in range(1, 9):
            offsets.append(offsets[-1] + (200 if i % 2 == 1 else 800))
        ts = "\n".join(str(base - o) for o in offsets)
        with patch("subprocess.check_output", return_value=ts.encode()):
            info = commit_stability(tmp_path, count=9)
        assert 0.3 < info["cv"] <= 0.7, f"cv was {info['cv']}"
        assert info["verdict"] == "wobbly"

    def test_insufficient_data(self, tmp_path: Path):
        with patch("subprocess.check_output", return_value=b"1697529600\n"):
            info = commit_stability(tmp_path, count=1)
        assert info["verdict"] == "unknown"
        assert info["stability"] == 0.0

    def test_mean_interval(self, tmp_path: Path):
        ts = "1697529600\n1697529000\n1697528400\n"
        with patch("subprocess.check_output", return_value=ts.encode()):
            info = commit_stability(tmp_path, count=3)
        assert info["mean_interval"] == pytest.approx(600.0)

    def test_jitter_positive(self, tmp_path: Path):
        ts = "1697529600\n1697529000\n1697528100\n1697527800\n"
        with patch("subprocess.check_output", return_value=ts.encode()):
            info = commit_stability(tmp_path, count=4)
        assert info["jitter"] > 0.0

    def test_intervals_list(self, tmp_path: Path):
        ts = "1697529600\n1697529000\n1697528400\n"
        with patch("subprocess.check_output", return_value=ts.encode()):
            info = commit_stability(tmp_path, count=3)
        assert info["intervals"] == [600.0, 600.0]


# ---------------------------------------------------------------------------
# stability_report
# ---------------------------------------------------------------------------

class TestStabilityReport:
    def test_returns_string(self, tmp_path: Path):
        ts = "1697529600\n1697529000\n1697528400\n"
        with patch("subprocess.check_output", return_value=ts.encode()):
            report = stability_report(tmp_path, count=3)
        assert "steady" in report or "wobbly" in report or "erratic" in report

    def test_insufficient_message(self, tmp_path: Path):
        with patch("subprocess.check_output", return_value=b""):
            report = stability_report(tmp_path)
        assert "insufficient" in report

    def test_includes_count(self, tmp_path: Path):
        ts = "\n".join(str(int(1697529600 - i * 600)) for i in range(5))
        with patch("subprocess.check_output", return_value=ts.encode()):
            report = stability_report(tmp_path, count=5)
        assert "5 commits" in report

    def test_includes_cv(self, tmp_path: Path):
        ts = "\n".join(str(int(1697529600 - i * 600)) for i in range(5))
        with patch("subprocess.check_output", return_value=ts.encode()):
            report = stability_report(tmp_path, count=5)
        assert "cv " in report
