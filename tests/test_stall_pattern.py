"""Tests for tools/stall_pattern.py — stall classification logic."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.stall_pattern import (
    classify_stalls,
    compute_gaps,
    find_stalls,
)


# ── compute_gaps ──────────────────────────────────────────────────

class TestComputeGaps:
    def test_empty(self):
        assert compute_gaps([]) == []

    def test_single(self):
        now = datetime.now(timezone.utc)
        assert compute_gaps([now]) == []

    def test_two_timestamps(self):
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 1, 1, 0, 5, 0, tzinfo=timezone.utc)
        gaps = compute_gaps([t1, t0])  # order shouldn't matter
        assert len(gaps) == 1
        assert gaps[0] == 300.0

    def test_unsorted_input(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts = [base + timedelta(minutes=m) for m in [10, 0, 5, 15]]
        gaps = compute_gaps(ts)
        assert gaps == [300.0, 300.0, 300.0]

    def test_chronological_output(self):
        """Gaps should always be positive (sorted input)."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts = [base + timedelta(minutes=i * 2) for i in range(10)]
        gaps = compute_gaps(ts)
        assert all(g > 0 for g in gaps)
        assert all(g == 120.0 for g in gaps)


# ── find_stalls ───────────────────────────────────────────────────

class TestFindStalls:
    def test_no_stalls(self):
        gaps = [15.0, 20.0, 18.0, 25.0]
        assert find_stalls(gaps, stall_gap=300.0) == []

    def test_one_stall(self):
        gaps = [15.0, 600.0, 20.0, 15.0]
        assert find_stalls(gaps, stall_gap=300.0) == [1]

    def test_multiple_stalls(self):
        gaps = [15.0, 500.0, 20.0, 400.0, 15.0, 350.0]
        indices = find_stalls(gaps, stall_gap=300.0)
        assert indices == [1, 3, 5]

    def test_exact_threshold(self):
        gaps = [300.0, 299.9, 300.1]
        indices = find_stalls(gaps, stall_gap=300.0)
        assert indices == [0, 2]

    def test_custom_threshold(self):
        gaps = [100.0, 200.0, 50.0]
        assert find_stalls(gaps, stall_gap=150.0) == [1]


# ── classify_stalls ───────────────────────────────────────────────

class TestClassifyStalls:
    def _make_gaps(self, n_normal: int, stall_every: int, total: int) -> list[float]:
        """Build a gap sequence with stalls inserted at regular intervals."""
        gaps = []
        for i in range(total):
            if (i + 1) % stall_every == 0:
                gaps.append(600.0)  # stall
            else:
                gaps.append(15.0)
        return gaps

    def test_too_few_stalls(self):
        result = classify_stalls([0, 5], [15.0] * 20)
        assert result["pattern"] == "random"
        assert result["confidence"] == 0.0
        assert result["stall_count"] == 2

    def test_regular_pattern(self):
        """Stalls at exactly every 10th commit → regular."""
        stall_indices = list(range(0, 50, 10))  # [0, 10, 20, 30, 40]
        gaps = [15.0] * 50
        result = classify_stalls(stall_indices, gaps)
        assert result["pattern"] == "regular"
        assert result["confidence"] > 0.5
        assert result["stall_count"] == 5

    def test_accelerating_pattern(self):
        """Stall gaps shrink from 15 → 5 over time."""
        # first half: gaps of 15, second half: gaps of 5
        stall_indices = [0, 15, 30, 35, 40, 45]
        gaps = [15.0] * 50
        result = classify_stalls(stall_indices, gaps)
        assert result["pattern"] == "accelerating"
        assert result["stall_count"] == 6

    def test_clustered_pattern(self):
        """Stalls arrive in tight pairs with long gaps between pairs."""
        # pairs: (0,1), (20,21), (40,41) → within-pair gap=1, between=19
        stall_indices = [0, 1, 20, 21, 40, 41]
        gaps = [15.0] * 50
        result = classify_stalls(stall_indices, gaps)
        # should detect clustering (3 out of 5 stall-gaps are ≤ 2)
        assert result["pattern"] == "clustered"
        assert result["stall_count"] == 6

    def test_random_pattern(self):
        """Irregular, non-accelerating, non-clustered → random."""
        stall_indices = [0, 7, 22, 28, 45]
        gaps = [15.0] * 50
        result = classify_stalls(stall_indices, gaps)
        assert result["pattern"] == "random"
        assert result["stall_count"] == 5

    def test_detail_is_nonempty_string(self):
        result = classify_stalls([0, 10, 20, 30], [15.0] * 40)
        assert isinstance(result["detail"], str)
        assert len(result["detail"]) > 0

    def test_mean_gap_positive_for_regular(self):
        stall_indices = list(range(0, 60, 12))
        gaps = [15.0] * 60
        result = classify_stalls(stall_indices, gaps)
        assert result["mean_gap"] == 12.0

    def test_empty_stall_list(self):
        result = classify_stalls([], [15.0] * 20)
        assert result["pattern"] == "random"
        assert result["stall_count"] == 0


# ── edge cases ────────────────────────────────────────────────────

class TestEdgeCases:
    def test_all_stalls(self):
        """Every commit gap is a stall — should still classify."""
        gaps = [600.0] * 10
        indices = find_stalls(gaps, 300.0)
        assert len(indices) == 10
        result = classify_stalls(indices, gaps)
        assert result["pattern"] in ("regular", "random", "clustered", "accelerating")

    def test_single_gap_entry(self):
        """One stall → too few to classify."""
        result = classify_stalls([3], [15.0, 600.0, 15.0, 15.0])
        assert result["stall_count"] == 1
        assert result["pattern"] == "random"
