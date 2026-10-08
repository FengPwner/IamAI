"""Tests for iamai.commit_burst_detector — burst detection from commit gaps."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.commit_burst_detector import (  # noqa: E402
    Burst,
    DEFAULT_BURST_THRESHOLD,
    DEFAULT_PANIC_MEAN_GAP,
    burst_summary,
    burst_verdict,
    detect_bursts,
)


# ---------------------------------------------------------------------------
# Burst dataclass
# ---------------------------------------------------------------------------


class TestBurst:
    """Unit tests for the Burst dataclass."""

    def test_length_from_gaps(self):
        b = Burst(start_index=0, gaps=(10, 8, 12))
        assert b.length == 4  # gaps + 1

    def test_duration(self):
        b = Burst(start_index=0, gaps=(10, 8, 12))
        assert b.duration == 30

    def test_mean_gap(self):
        b = Burst(start_index=0, gaps=(10, 8, 12))
        assert b.mean_gap == 10.0

    def test_single_gap(self):
        b = Burst(start_index=0, gaps=(5,))
        assert b.length == 2
        assert b.duration == 5
        assert b.mean_gap == 5.0

    def test_frozen(self):
        b = Burst(start_index=0, gaps=(10,))
        with pytest.raises(AttributeError):
            b.start_index = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# detect_bursts
# ---------------------------------------------------------------------------


class TestDetectBursts:
    """Tests for the detect_bursts function."""

    def test_empty_gaps(self):
        assert detect_bursts([]) == []

    def test_single_gap(self):
        # A single gap is not enough for a burst (need ≥ 2 gaps in a run)
        assert detect_bursts([5]) == []

    def test_no_bursts_all_slow(self):
        gaps = [60, 120, 90, 45, 200]
        assert detect_bursts(gaps, burst_threshold=30) == []

    def test_one_burst(self):
        gaps = [60, 10, 8, 12, 60]
        bursts = detect_bursts(gaps, burst_threshold=15)
        assert len(bursts) == 1
        assert bursts[0].start_index == 1
        assert bursts[0].gaps == (10, 8, 12)
        assert bursts[0].length == 4

    def test_two_bursts(self):
        gaps = [10, 8, 60, 60, 5, 7, 9]
        bursts = detect_bursts(gaps, burst_threshold=15)
        assert len(bursts) == 2
        assert bursts[0].start_index == 0
        assert bursts[1].start_index == 4

    def test_all_rapid(self):
        gaps = [5, 3, 7, 4, 6]
        bursts = detect_bursts(gaps, burst_threshold=10)
        assert len(bursts) == 1
        assert bursts[0].length == 6

    def test_threshold_boundary(self):
        gaps = [30, 30, 30]
        bursts = detect_bursts(gaps, burst_threshold=30)
        assert len(bursts) == 1
        assert bursts[0].gaps == (30, 30, 30)

    def test_just_above_threshold(self):
        gaps = [31, 31, 31]
        bursts = detect_bursts(gaps, burst_threshold=30)
        assert bursts == []

    def test_trailing_burst(self):
        gaps = [120, 60, 5, 3, 7]
        bursts = detect_bursts(gaps, burst_threshold=10)
        assert len(bursts) == 1
        assert bursts[0].start_index == 2

    def test_leading_burst(self):
        gaps = [5, 3, 7, 120, 60]
        bursts = detect_bursts(gaps, burst_threshold=10)
        assert len(bursts) == 1
        assert bursts[0].start_index == 0

    def test_isolated_rapid_gap_not_burst(self):
        # A single rapid gap surrounded by slow ones is not a burst (need ≥ 2)
        gaps = [60, 5, 60]
        assert detect_bursts(gaps, burst_threshold=10) == []


# ---------------------------------------------------------------------------
# burst_verdict
# ---------------------------------------------------------------------------


class TestBurstVerdict:
    """Tests for the burst_verdict classifier."""

    def test_quiet(self):
        assert burst_verdict([]) == "quiet"

    def test_steady_one_short_burst(self):
        bursts = [Burst(start_index=0, gaps=(10, 8))]
        assert burst_verdict(bursts) == "steady"

    def test_steady_two_short_bursts(self):
        bursts = [
            Burst(start_index=0, gaps=(10, 8)),
            Burst(start_index=5, gaps=(12, 9)),
        ]
        assert burst_verdict(bursts) == "steady"

    def test_surging_three_bursts(self):
        bursts = [
            Burst(start_index=0, gaps=(10, 8)),
            Burst(start_index=5, gaps=(12, 9)),
            Burst(start_index=10, gaps=(7, 6)),
        ]
        assert burst_verdict(bursts) == "surging"

    def test_surging_long_burst(self):
        bursts = [Burst(start_index=0, gaps=(10, 8, 12, 9, 11))]
        assert burst_verdict(bursts, long_burst=5) == "surging"

    def test_panic_takes_priority(self):
        bursts = [
            Burst(start_index=0, gaps=(2, 1, 3)),  # mean_gap = 2.0 < 5
            Burst(start_index=5, gaps=(10, 8)),
        ]
        assert burst_verdict(bursts) == "panic"

    def test_panic_exactly_at_threshold(self):
        # mean_gap == 5.0 is NOT < 5.0, so not panic
        bursts = [Burst(start_index=0, gaps=(5, 5))]
        assert burst_verdict(bursts, panic_mean_gap=5.0) == "steady"

    def test_panic_below_threshold(self):
        bursts = [Burst(start_index=0, gaps=(4, 5))]
        # mean_gap = 4.5 < 5.0
        assert burst_verdict(bursts, panic_mean_gap=5.0) == "panic"


# ---------------------------------------------------------------------------
# burst_summary
# ---------------------------------------------------------------------------


class TestBurstSummary:
    """Tests for the burst_summary convenience function."""

    def test_empty(self):
        result = burst_summary([])
        assert result["count"] == 0
        assert result["verdict"] == "quiet"
        assert result["longest"] == 0
        assert result["total_burst_commits"] == 0

    def test_with_bursts(self):
        gaps = [60, 10, 8, 12, 60, 5, 3, 7]
        result = burst_summary(gaps, burst_threshold=15)
        assert result["count"] == 2
        assert result["verdict"] == "steady"
        assert result["longest"] == 4  # first burst has 3 gaps → 4 commits
        assert result["total_burst_commits"] == 4 + 4  # 4 + 4

    def test_panic_scenario(self):
        gaps = [60, 1, 2, 1, 3, 60]
        result = burst_summary(gaps, burst_threshold=10)
        assert result["verdict"] == "panic"
        assert result["count"] == 1

    def test_all_slow(self):
        gaps = [120, 90, 60, 45]
        result = burst_summary(gaps, burst_threshold=30)
        assert result["verdict"] == "quiet"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Boundary and regression tests."""

    def test_zero_gaps(self):
        gaps = [0, 0, 0]
        bursts = detect_bursts(gaps, burst_threshold=10)
        assert len(bursts) == 1
        assert bursts[0].mean_gap == 0.0

    def test_negative_gaps_treated_as_rapid(self):
        # Clock skew could produce negative gaps
        gaps = [-1, -2, -3]
        bursts = detect_bursts(gaps, burst_threshold=10)
        assert len(bursts) == 1

    def test_large_threshold(self):
        gaps = [100, 200, 300]
        bursts = detect_bursts(gaps, burst_threshold=500)
        assert len(bursts) == 1
        assert bursts[0].length == 4

    def test_float_gaps(self):
        gaps = [10.5, 8.3, 12.7, 60.0, 5.1, 3.9]
        bursts = detect_bursts(gaps, burst_threshold=15)
        assert len(bursts) == 2

    def test_default_threshold(self):
        assert DEFAULT_BURST_THRESHOLD == 30

    def test_default_panic_mean_gap(self):
        assert DEFAULT_PANIC_MEAN_GAP == 5.0
