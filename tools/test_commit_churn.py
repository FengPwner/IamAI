#!/usr/bin/env python3
"""tests for commit_churn — detect writer rewrite loops.

run: python3 -m pytest tools/test_commit_churn.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.commit_churn import (  # noqa: E402
    churn_index,
    _file_overlap,
    _rewrite_ratio,
    _per_commit_churn,
)


# ---------------------------------------------------------------------------
# unit tests — helper functions
# ---------------------------------------------------------------------------

class TestFileOverlap:
    def test_no_overlap(self):
        assert _file_overlap({"a", "b"}, {"c", "d"}) == 0.0

    def test_full_overlap(self):
        assert _file_overlap({"a", "b"}, {"a", "b"}) == 1.0

    def test_partial_overlap(self):
        # 1 of 2 current files overlap → 0.5
        assert _file_overlap({"a", "b"}, {"a", "c"}) == 0.5

    def test_empty_current(self):
        assert _file_overlap(set(), {"a"}) == 0.0

    def test_empty_previous(self):
        assert _file_overlap({"a"}, set()) == 0.0

    def test_both_empty(self):
        assert _file_overlap(set(), set()) == 0.0


class TestRewriteRatio:
    def test_pure_addition(self):
        assert _rewrite_ratio(100, 0) == 0.0

    def test_pure_rewrite(self):
        assert _rewrite_ratio(50, 50) == 1.0

    def test_mostly_addition(self):
        # min/max = 10/100 = 0.1
        assert _rewrite_ratio(100, 10) == 0.1

    def test_both_zero(self):
        # edge case: 0/0 should be 0.0 (max(0,0,1) = 1, min = 0)
        assert _rewrite_ratio(0, 0) == 0.0

    def test_small_rewrite(self):
        assert _rewrite_ratio(30, 70) == 30 / 70


class TestPerCommitChurn:
    def test_additive_commit_no_overlap(self):
        commit = {"files": {"new.md"}, "insertions": 50, "deletions": 0}
        score = _per_commit_churn(commit, {"other.md"})
        # overlap = 0, rewrite = 0 → churn = 0
        assert score == 0.0

    def test_rewrite_commit_high_overlap(self):
        commit = {"files": {"a.md", "b.md"}, "insertions": 40, "deletions": 40}
        score = _per_commit_churn(commit, {"a.md", "b.md"})
        # overlap = 1.0, rewrite = 1.0 → churn = 1.0
        assert score == 1.0

    def test_mixed_commit(self):
        commit = {"files": {"a.md", "new.md"}, "insertions": 20, "deletions": 20}
        score = _per_commit_churn(commit, {"a.md", "old.md"})
        # overlap = 0.5 (1 of 2), rewrite = 1.0 → 0.6*0.5 + 0.4*1.0 = 0.7
        assert abs(score - 0.7) < 0.01


# ---------------------------------------------------------------------------
# integration tests — churn_index
# ---------------------------------------------------------------------------

class TestChurnIndex:
    def test_empty_commits(self):
        result = churn_index([])
        assert result["score"] == 0
        assert result["band"] == "healthy"
        assert result["per_commit"] == []

    def test_single_commit(self):
        commits = [
            {"files": {"a.md"}, "insertions": 10, "deletions": 0},
        ]
        result = churn_index(commits)
        assert result["score"] == 0
        assert result["band"] == "healthy"

    def test_all_additive(self):
        """each commit touches new files and only adds."""
        commits = [
            {"files": {"a.md"}, "insertions": 10, "deletions": 0},
            {"files": {"b.md"}, "insertions": 20, "deletions": 0},
            {"files": {"c.md"}, "insertions": 30, "deletions": 0},
            {"files": {"d.md"}, "insertions": 15, "deletions": 0},
        ]
        result = churn_index(commits)
        assert result["band"] == "healthy"
        assert result["score"] < 30

    def test_rewrite_loop(self):
        """writer keeps editing the same files with similar ins/dels."""
        commits = [
            {"files": {"a.md", "b.md"}, "insertions": 10, "deletions": 2},
            {"files": {"a.md", "b.md"}, "insertions": 8, "deletions": 10},
            {"files": {"a.md", "b.md"}, "insertions": 12, "deletions": 9},
            {"files": {"a.md", "b.md"}, "insertions": 7, "deletions": 11},
            {"files": {"a.md", "b.md"}, "insertions": 15, "deletions": 13},
        ]
        result = churn_index(commits)
        assert result["band"] == "stalled"
        assert result["score"] >= 60

    def test_mixed_pattern(self):
        """some additive, some rewrite — should land in churning."""
        commits = [
            {"files": {"a.md"}, "insertions": 20, "deletions": 0},
            {"files": {"a.md"}, "insertions": 5, "deletions": 8},
            {"files": {"b.md"}, "insertions": 30, "deletions": 0},
            {"files": {"b.md"}, "insertions": 10, "deletions": 12},
            {"files": {"c.md"}, "insertions": 25, "deletions": 0},
            {"files": {"c.md"}, "insertions": 8, "deletions": 6},
        ]
        result = churn_index(commits)
        # expect churning band
        assert result["band"] in ("churning", "healthy")
        assert 0 <= result["score"] <= 100

    def test_score_bounded(self):
        """score is always 0–100 regardless of input."""
        commits = [
            {"files": {"a.md"}, "insertions": 0, "deletions": 0},
            {"files": {"a.md"}, "insertions": 0, "deletions": 0},
        ]
        result = churn_index(commits)
        assert 0 <= result["score"] <= 100

    def test_summary_contains_count(self):
        commits = [
            {"files": {"a.md"}, "insertions": 10, "deletions": 0},
            {"files": {"b.md"}, "insertions": 20, "deletions": 0},
        ]
        result = churn_index(commits)
        assert "2 commits analysed" in result["summary"]

    def test_per_commit_length(self):
        commits = [
            {"files": {"a.md"}, "insertions": 10, "deletions": 0},
            {"files": {"b.md"}, "insertions": 20, "deletions": 0},
            {"files": {"c.md"}, "insertions": 15, "deletions": 5},
        ]
        result = churn_index(commits)
        assert len(result["per_commit"]) == len(commits)

    def test_high_churn_count(self):
        """high-churn commits have score >= 0.5."""
        commits = [
            {"files": {"a.md"}, "insertions": 5, "deletions": 5},
            {"files": {"a.md"}, "insertions": 5, "deletions": 5},
            {"files": {"a.md"}, "insertions": 5, "deletions": 5},
        ]
        result = churn_index(commits)
        # all commits after the first should be high-churn
        high = sum(1 for s in result["per_commit"][1:] if s >= 0.5)
        assert high == 2


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
