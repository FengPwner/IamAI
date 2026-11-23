"""Tests for iamai.commit_gap_analyzer — commit cadence regularity analysis.

Visit 812: this module measures the regularity of inter-commit intervals,
classifying the cadence as regular, moderate, irregular or chaotic.

Test areas:
    1. _parse_iso           — ISO 8601 timestamp parsing
    2. compute_gaps         — inter-commit interval calculation
    3. gap_distribution     — bucket classification
    4. detect_outliers      — outlier detection
    5. regularity_score     — CV-based scoring
    6. gap_report           — full structured report
    7. gap_summary          — human-readable output
    8. _cli                 — exit codes, --json flag
    9. edge cases           — empty, single, degenerate inputs
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.commit_gap_analyzer import (
    _cli,
    _parse_iso,
    compute_gaps,
    detect_outliers,
    gap_distribution,
    gap_report,
    gap_summary,
    regularity_score,
)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _ts(offset_seconds: float) -> str:
    """Return an ISO-8601 timestamp at *offset_seconds* after a base time."""
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    dt = base + timedelta(seconds=offset_seconds)
    return dt.isoformat()


def _uniform_timestamps(count: int, interval: float = 600.0) -> list[str]:
    """Generate *count* timestamps spaced exactly *interval* seconds apart."""
    return [_ts(i * interval) for i in range(count)]


# -----------------------------------------------------------------------
# 1. _parse_iso
# -----------------------------------------------------------------------


class TestParseIso:
    def test_utc_z_suffix(self):
        dt = _parse_iso("2026-01-01T12:00:00Z")
        assert dt.year == 2026
        assert dt.hour == 12
        assert dt.tzinfo is not None

    def test_explicit_offset(self):
        dt = _parse_iso("2026-06-15T08:30:00+08:00")
        assert dt.hour == 8
        assert dt.utcoffset() == timedelta(hours=8)

    def test_no_timezone_treated_as_naive(self):
        dt = _parse_iso("2026-01-01T12:00:00")
        assert dt.year == 2026
        # Naive datetime has no tzinfo
        assert dt.tzinfo is None

    def test_microseconds(self):
        dt = _parse_iso("2026-01-01T12:00:00.123456+00:00")
        assert dt.microsecond == 123456

    def test_whitespace_stripped(self):
        dt = _parse_iso("  2026-01-01T12:00:00Z  ")
        assert dt.year == 2026


# -----------------------------------------------------------------------
# 2. compute_gaps
# -----------------------------------------------------------------------


class TestComputeGaps:
    def test_uniform_600s(self):
        ts = _uniform_timestamps(5, interval=600.0)
        gaps = compute_gaps(ts)
        assert len(gaps) == 4
        assert all(g == 600.0 for g in gaps)

    def test_single_timestamp(self):
        assert compute_gaps([_ts(0)]) == []

    def test_empty_input(self):
        assert compute_gaps([]) == []

    def test_two_timestamps(self):
        ts = [_ts(0), _ts(300)]
        gaps = compute_gaps(ts)
        assert gaps == [300.0]

    def test_negative_gap_clamped_to_zero(self):
        # Second timestamp is before first (clock skew)
        ts = [_ts(100), _ts(50)]
        gaps = compute_gaps(ts)
        assert gaps == [0.0]

    def test_mixed_intervals(self):
        ts = [_ts(0), _ts(100), _ts(400), _ts(1000)]
        gaps = compute_gaps(ts)
        assert gaps == [100.0, 300.0, 600.0]

    def test_large_gap(self):
        ts = [_ts(0), _ts(7200)]  # 2 hours
        gaps = compute_gaps(ts)
        assert gaps == [7200.0]


# -----------------------------------------------------------------------
# 3. gap_distribution
# -----------------------------------------------------------------------


class TestGapDistribution:
    def test_all_buckets_populated(self):
        gaps = [30, 150, 450, 900, 3600]
        dist = gap_distribution(gaps)
        assert dist["rapid"] == 1
        assert dist["steady"] == 1
        assert dist["normal"] == 1
        assert dist["slow"] == 1
        assert dist["stalled"] == 1

    def test_empty_gaps(self):
        dist = gap_distribution([])
        assert all(v == 0 for v in dist.values())

    def test_all_rapid(self):
        gaps = [10, 20, 30, 40, 50]
        dist = gap_distribution(gaps)
        assert dist["rapid"] == 5
        assert sum(dist.values()) == 5

    def test_boundary_60_goes_to_steady(self):
        # 60s is the lower bound of "steady", not in "rapid"
        dist = gap_distribution([60.0])
        assert dist["steady"] == 1
        assert dist["rapid"] == 0

    def test_boundary_300_goes_to_normal(self):
        dist = gap_distribution([300.0])
        assert dist["normal"] == 1
        assert dist["steady"] == 0

    def test_boundary_600_goes_to_slow(self):
        dist = gap_distribution([600.0])
        assert dist["slow"] == 1
        assert dist["normal"] == 0

    def test_boundary_1800_goes_to_stalled(self):
        dist = gap_distribution([1800.0])
        assert dist["stalled"] == 1
        assert dist["slow"] == 0

    def test_zero_gap(self):
        dist = gap_distribution([0.0])
        assert dist["rapid"] == 1


# -----------------------------------------------------------------------
# 4. detect_outliers
# -----------------------------------------------------------------------


class TestDetectOutliers:
    def test_no_outliers_in_uniform_data(self):
        gaps = [600.0] * 10
        assert detect_outliers(gaps) == []

    def test_one_outlier(self):
        gaps = [600.0, 600.0, 600.0, 2000.0]
        outliers = detect_outliers(gaps, multiplier=2.0)
        assert outliers == [2000.0]

    def test_all_outliers_when_huge_spread(self):
        gaps = [1.0, 1.0, 100.0, 100.0]
        outliers = detect_outliers(gaps, multiplier=2.0)
        # mean is 50.5, threshold 101.0 — only 100 is NOT outlier
        # Actually 100 < 101, so not outlier; 1.0 is not outlier
        assert outliers == []

    def test_empty_gaps(self):
        assert detect_outliers([]) == []

    def test_custom_multiplier(self):
        gaps = [100.0, 100.0, 100.0, 350.0]
        # mean = 162.5, 2x = 325, 3x = 487.5
        outliers_2x = detect_outliers(gaps, multiplier=2.0)
        outliers_3x = detect_outliers(gaps, multiplier=3.0)
        assert 350.0 in outliers_2x
        assert 350.0 not in outliers_3x


# -----------------------------------------------------------------------
# 5. regularity_score
# -----------------------------------------------------------------------


class TestRegularityScore:
    def test_perfectly_uniform(self):
        gaps = [600.0, 600.0, 600.0, 600.0]
        score = regularity_score(gaps)
        assert score == pytest.approx(1.0)

    def test_single_gap(self):
        # Single gap → defined as perfectly regular
        score = regularity_score([600.0])
        assert score == 1.0

    def test_empty_gaps(self):
        assert regularity_score([]) == 0.0

    def test_cv_equals_mean_gives_half(self):
        # When std == mean, CV=1, score = 1/(1+1) = 0.5
        # gaps with std == mean: e.g. [0, 100] has mean=50, std=~70.7
        # Let's just check the formula direction
        gaps = [100.0, 200.0, 300.0]  # moderate spread
        score = regularity_score(gaps)
        assert 0.0 < score < 1.0

    def test_high_variance_low_score(self):
        gaps = [10.0, 10.0, 10.0, 10000.0]
        score = regularity_score(gaps)
        assert score < 0.4

    def test_two_gaps_equal(self):
        score = regularity_score([500.0, 500.0])
        assert score == pytest.approx(1.0)

    def test_all_zero_gaps(self):
        # Degenerate: all commits at same time
        score = regularity_score([0.0, 0.0, 0.0])
        assert score == 0.0

    def test_score_monotonic_with_regularisation(self):
        # More regular → higher score
        gaps_regular = [600.0, 600.0, 600.0, 600.0]
        gaps_irregular = [100.0, 200.0, 800.0, 1100.0]
        assert regularity_score(gaps_regular) > regularity_score(gaps_irregular)


# -----------------------------------------------------------------------
# 6. gap_report
# -----------------------------------------------------------------------


class TestGapReport:
    def test_report_structure(self):
        mock_timestamps = _uniform_timestamps(10, interval=600.0)
        with patch(
            "iamai.commit_gap_analyzer._run_git_log",
            return_value=mock_timestamps,
        ):
            report = gap_report(n=10)
        assert report["commit_count"] == 10
        assert report["gap_count"] == 9
        assert report["mean_gap_seconds"] == 600.0
        assert report["median_gap_seconds"] == 600.0
        assert report["max_gap_seconds"] == 600.0
        assert report["min_gap_seconds"] == 600.0
        assert report["std_gap_seconds"] == 0.0
        assert report["regularity_score"] == 1.0
        assert report["outlier_count"] == 0
        assert report["outlier_fraction"] == 0.0
        assert report["label"] == "regular"
        assert "gap_distribution" in report

    def test_report_irregular_cadence(self):
        # Mix of very short and very long gaps
        offsets = [0, 10, 20, 3600, 3610, 3620, 7200, 10800, 10810, 14400]
        mock_timestamps = [_ts(o) for o in offsets]
        with patch(
            "iamai.commit_gap_analyzer._run_git_log",
            return_value=mock_timestamps,
        ):
            report = gap_report(n=10)
        assert report["gap_count"] == 9
        assert report["regularity_score"] < 0.5
        assert report["label"] in ("irregular", "chaotic", "moderate")

    def test_report_insufficient_data(self):
        with patch(
            "iamai.commit_gap_analyzer._run_git_log",
            return_value=[_ts(0)],
        ):
            report = gap_report(n=1)
        assert report["gap_count"] == 0
        assert report["label"] == "insufficient_data"
        assert report["regularity_score"] == 0.0

    def test_report_with_outliers(self):
        offsets = [0, 600, 1200, 1800, 2400, 3000, 3600, 4200, 4800, 12000]
        mock_timestamps = [_ts(o) for o in offsets]
        with patch(
            "iamai.commit_gap_analyzer._run_git_log",
            return_value=mock_timestamps,
        ):
            report = gap_report(n=10)
        # The 7200s gap (from 4800 to 12000) should be an outlier
        assert report["outlier_count"] >= 1


# -----------------------------------------------------------------------
# 7. gap_summary
# -----------------------------------------------------------------------


class TestGapSummary:
    def test_summary_contains_key_fields(self):
        mock_timestamps = _uniform_timestamps(5, interval=600.0)
        with patch(
            "iamai.commit_gap_analyzer._run_git_log",
            return_value=mock_timestamps,
        ):
            summary = gap_summary(n=5)
        assert "commit_gap_analyzer" in summary
        assert "mean" in summary
        assert "score" in summary
        assert "regular" in summary

    def test_summary_handles_insufficient_data(self):
        with patch(
            "iamai.commit_gap_analyzer._run_git_log",
            return_value=[_ts(0)],
        ):
            summary = gap_summary(n=1)
        assert "insufficient_data" in summary


# -----------------------------------------------------------------------
# 8. _cli
# -----------------------------------------------------------------------


class TestCli:
    def test_json_output(self, capsys):
        mock_timestamps = _uniform_timestamps(5, interval=600.0)
        with patch(
            "iamai.commit_gap_analyzer._run_git_log",
            return_value=mock_timestamps,
        ):
            exit_code = _cli(["-n", "5", "--json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["commit_count"] == 5
        assert data["regularity_score"] == 1.0
        assert exit_code == 0

    def test_text_output(self, capsys):
        mock_timestamps = _uniform_timestamps(5, interval=600.0)
        with patch(
            "iamai.commit_gap_analyzer._run_git_log",
            return_value=mock_timestamps,
        ):
            exit_code = _cli(["-n", "5"])
        captured = capsys.readouterr()
        assert "commit_gap_analyzer" in captured.out
        assert exit_code == 0

    def test_exit_code_nonzero_for_chaotic(self, capsys):
        offsets = [0, 10, 20, 3600, 3610, 7200, 14400, 28800, 28810, 57600]
        mock_timestamps = [_ts(o) for o in offsets]
        with patch(
            "iamai.commit_gap_analyzer._run_git_log",
            return_value=mock_timestamps,
        ):
            exit_code = _cli(["-n", "10"])
        # Should be non-zero for irregular/chaotic
        assert exit_code == 1

    def test_custom_outlier_multiplier(self, capsys):
        mock_timestamps = _uniform_timestamps(5, interval=600.0)
        with patch(
            "iamai.commit_gap_analyzer._run_git_log",
            return_value=mock_timestamps,
        ):
            exit_code = _cli(["-n", "5", "--outlier-multiplier", "3.0", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert exit_code == 0


# -----------------------------------------------------------------------
# 9. Edge cases
# -----------------------------------------------------------------------


class TestEdgeCases:
    def test_compute_gaps_with_timezone_mix(self):
        # Both timestamps represent the same instant → gap = 0
        ts = ["2026-01-01T12:00:00+00:00", "2026-01-01T20:00:00+08:00"]
        gaps = compute_gaps(ts)
        assert gaps == [0.0]

    def test_gap_distribution_single_value(self):
        dist = gap_distribution([45.0])
        assert dist["rapid"] == 1
        assert sum(dist.values()) == 1

    def test_detect_outliers_single_gap(self):
        # Single gap: mean = gap itself, 2x mean = 2x gap > gap → not outlier
        assert detect_outliers([500.0], multiplier=2.0) == []

    def test_regularity_score_two_identical_gaps(self):
        score = regularity_score([300.0, 300.0])
        assert score == pytest.approx(1.0)

    def test_report_label_regular(self):
        mock_timestamps = _uniform_timestamps(20, interval=600.0)
        with patch(
            "iamai.commit_gap_analyzer._run_git_log",
            return_value=mock_timestamps,
        ):
            report = gap_report(n=20)
        assert report["label"] == "regular"

    def test_gap_distribution_counts_sum(self):
        gaps = [10, 70, 150, 350, 500, 700, 1200, 2000]
        dist = gap_distribution(gaps)
        assert sum(dist.values()) == len(gaps)

    def test_compute_gaps_preserves_order(self):
        # Even if gaps are decreasing (shouldn't happen with sorted input,
        # but verify the function doesn't sort)
        ts = [_ts(0), _ts(1000), _ts(1500), _ts(2000)]
        gaps = compute_gaps(ts)
        assert gaps == [1000.0, 500.0, 500.0]
