"""Tests for iamai/cadence_jitter.py — timing irregularity measurement."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.cadence_jitter import (
    classify_jitter,
    extract_gaps,
    jitter_report,
    jitter_report_from_gaps,
    jitter_summary,
)


# ---------------------------------------------------------------------------
# classify_jitter
# ---------------------------------------------------------------------------

class TestClassifyJitter:
    def test_steady_low_cv(self):
        assert classify_jitter(0.0) == "steady"

    def test_steady_boundary(self):
        assert classify_jitter(0.09) == "steady"

    def test_regular_low_boundary(self):
        assert classify_jitter(0.10) == "regular"

    def test_regular_mid(self):
        assert classify_jitter(0.15) == "regular"

    def test_regular_high_boundary(self):
        assert classify_jitter(0.24) == "regular"

    def test_uneven_low_boundary(self):
        assert classify_jitter(0.25) == "uneven"

    def test_uneven_mid(self):
        assert classify_jitter(0.35) == "uneven"

    def test_uneven_high_boundary(self):
        assert classify_jitter(0.49) == "uneven"

    def test_erratic_low_boundary(self):
        assert classify_jitter(0.50) == "erratic"

    def test_erratic_high(self):
        assert classify_jitter(1.0) == "erratic"

    def test_negative_cv_clamped(self):
        assert classify_jitter(-0.5) == "steady"


# ---------------------------------------------------------------------------
# extract_gaps
# ---------------------------------------------------------------------------

class TestExtractGaps:
    def test_two_timestamps(self):
        gaps = extract_gaps([0.0, 15.0])
        assert gaps == [15.0]

    def test_three_timestamps(self):
        gaps = extract_gaps([0.0, 15.0, 30.0])
        assert gaps == [15.0, 15.0]

    def test_variable_gaps(self):
        gaps = extract_gaps([0.0, 10.0, 30.0, 45.0])
        assert gaps == [10.0, 20.0, 15.0]

    def test_single_timestamp(self):
        assert extract_gaps([0.0]) == []

    def test_empty_list(self):
        assert extract_gaps([]) == []

    def test_datetime_objects(self):
        ts = [
            datetime(2026, 10, 18, 0, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 10, 18, 0, 0, 15, tzinfo=timezone.utc),
            datetime(2026, 10, 18, 0, 0, 30, tzinfo=timezone.utc),
        ]
        gaps = extract_gaps(ts)
        assert len(gaps) == 2
        assert all(abs(g - 15.0) < 0.01 for g in gaps)

    def test_integer_timestamps(self):
        gaps = extract_gaps([100, 115, 130])
        assert gaps == [15.0, 15.0]


# ---------------------------------------------------------------------------
# jitter_report_from_gaps
# ---------------------------------------------------------------------------

class TestJitterReportFromGaps:
    def test_perfect_steady(self):
        r = jitter_report_from_gaps([15, 15, 15, 15])
        assert r["label"] == "steady"
        assert r["cv"] == 0.0
        assert r["mean_gap_s"] == 15.0
        assert r["std_gap_s"] == 0.0

    def test_erratic_alternating(self):
        # mean=15, std=5, CV=0.333 → uneven (not erratic; fix boundary)
        r = jitter_report_from_gaps([10, 20, 10, 20])
        assert r["label"] == "uneven"
        assert r["mean_gap_s"] == 15.0
        assert 0.25 <= r["cv"] < 0.50

    def test_truly_erratic(self):
        # Gaps with CV > 0.50: [5, 25, 5, 25]
        # mean=15, std=10, CV=0.667
        r = jitter_report_from_gaps([5, 25, 5, 25])
        assert r["label"] == "erratic"
        assert r["cv"] > 0.50

    def test_count(self):
        r = jitter_report_from_gaps([15, 15, 15])
        assert r["count"] == 3

    def test_max_and_min(self):
        r = jitter_report_from_gaps([10, 15, 20])
        assert r["max_gap_s"] == 20.0
        assert r["min_gap_s"] == 10.0

    def test_max_deviation(self):
        r = jitter_report_from_gaps([10, 15, 20])
        # mean = 15, max deviation = |10 - 15| = 5 or |20 - 15| = 5
        assert r["max_deviation_s"] == 5.0

    def test_single_gap(self):
        r = jitter_report_from_gaps([15])
        assert r["count"] == 1
        assert r["mean_gap_s"] == 15.0
        assert r["std_gap_s"] == 0.0
        assert r["label"] == "steady"

    def test_empty_gaps(self):
        r = jitter_report_from_gaps([])
        assert r["count"] == 0
        assert r["mean_gap_s"] == 0.0

    def test_uneven_gaps(self):
        # CV between 0.25 and 0.50 → uneven
        r = jitter_report_from_gaps([10, 12, 18, 20])
        mean = 15.0
        assert r["mean_gap_s"] == mean
        assert 0.25 <= r["cv"] < 0.50
        assert r["label"] == "uneven"

    def test_regular_gaps(self):
        # Small variance around 15: [13, 14, 16, 17]
        r = jitter_report_from_gaps([13, 14, 16, 17])
        assert r["mean_gap_s"] == 15.0
        assert r["label"] == "regular"

    def test_large_gaps(self):
        # mean=150, std=50, CV=0.333 → uneven
        r = jitter_report_from_gaps([100, 200, 100, 200])
        assert r["mean_gap_s"] == 150.0
        assert r["label"] == "uneven"

    def test_large_erratic_gaps(self):
        # mean=150, std=150, CV=1.0 → erratic
        r = jitter_report_from_gaps([0, 300, 0, 300])
        assert r["mean_gap_s"] == 150.0
        assert r["label"] == "erratic"


# ---------------------------------------------------------------------------
# jitter_report (from timestamps)
# ---------------------------------------------------------------------------

class TestJitterReport:
    def test_datetime_steady(self):
        ts = [
            datetime(2026, 10, 18, 0, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 10, 18, 0, 0, 15, tzinfo=timezone.utc),
            datetime(2026, 10, 18, 0, 0, 30, tzinfo=timezone.utc),
            datetime(2026, 10, 18, 0, 0, 45, tzinfo=timezone.utc),
        ]
        r = jitter_report(ts)
        assert r["label"] == "steady"
        assert r["count"] == 3
        assert r["mean_gap_s"] == 15.0

    def test_numeric_timestamps(self):
        r = jitter_report([0.0, 15.0, 30.0, 45.0])
        assert r["label"] == "steady"

    def test_two_timestamps(self):
        r = jitter_report([0.0, 15.0])
        assert r["count"] == 1
        assert r["mean_gap_s"] == 15.0


# ---------------------------------------------------------------------------
# jitter_summary
# ---------------------------------------------------------------------------

class TestJitterSummary:
    def test_steady_summary(self):
        s = jitter_summary([0.0, 15.0, 30.0, 45.0])
        assert "3 gaps" in s
        assert "mean 15.0s" in s
        assert "steady" in s

    def test_erratic_summary(self):
        # gaps: 5, 25, 5, 25 → mean=15, CV=0.667 → erratic
        s = jitter_summary([0.0, 5.0, 30.0, 35.0, 60.0])
        assert "erratic" in s

    def test_summary_format(self):
        s = jitter_summary([0.0, 15.0, 30.0])
        # Should match "N gaps: mean Xs, std Ys, CV Z.ZZ (label)"
        assert "gaps:" in s
        assert "mean" in s
        assert "std" in s
        assert "CV" in s
