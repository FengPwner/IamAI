"""tests for iamai.commit_churn — detect rewrite vs additive patterns.

covers:
  1. _file_overlap edge cases
  2. _rewrite_ratio boundary values
  3. _per_commit_churn calculation
  4. churn_index empty, single, multi-commit
  5. band classification thresholds
  6. integration: healthy additive workflow
  7. integration: stalled rewrite workflow
"""

from __future__ import annotations

import pytest

from iamai.commit_churn import (
    _band,
    _file_overlap,
    _per_commit_churn,
    _rewrite_ratio,
    churn_index,
)


# ---------------------------------------------------------------------------
# _file_overlap
# ---------------------------------------------------------------------------

class TestFileOverlap:
    def test_empty_current_returns_zero(self):
        assert _file_overlap(set(), {"a.py", "b.py"}) == 0.0

    def test_empty_previous_returns_zero(self):
        assert _file_overlap({"a.py"}, set()) == 0.0

    def test_both_empty_returns_zero(self):
        assert _file_overlap(set(), set()) == 0.0

    def test_full_overlap(self):
        files = {"a.py", "b.py", "c.py"}
        assert _file_overlap(files, files) == 1.0

    def test_partial_overlap(self):
        current = {"a.py", "b.py", "c.py"}
        previous = {"a.py", "d.py"}
        # overlap = {a.py}, fraction = 1/3
        assert abs(_file_overlap(current, previous) - 1 / 3) < 0.001

    def test_no_overlap(self):
        current = {"a.py", "b.py"}
        previous = {"c.py", "d.py"}
        assert _file_overlap(current, previous) == 0.0

    def test_single_file_overlap(self):
        current = {"a.py"}
        previous = {"a.py"}
        assert _file_overlap(current, previous) == 1.0


# ---------------------------------------------------------------------------
# _rewrite_ratio
# ---------------------------------------------------------------------------

class TestRewriteRatio:
    def test_pure_addition(self):
        # 100 lines added, 0 deleted → 0.0
        assert _rewrite_ratio(100, 0) == 0.0

    def test_pure_rewrite(self):
        # equal additions and deletions → 1.0
        assert _rewrite_ratio(50, 50) == 1.0

    def test_pure_deletion(self):
        # 0 added, 100 deleted → 0.0 (min(0,100)/max(0,100,1))
        assert _rewrite_ratio(0, 100) == 0.0

    def test_mostly_addition(self):
        # 90 added, 10 deleted → 10/90 ≈ 0.111
        assert abs(_rewrite_ratio(90, 10) - 10 / 90) < 0.001

    def test_mostly_deletion(self):
        # 10 added, 90 deleted → 10/90 ≈ 0.111
        assert abs(_rewrite_ratio(10, 90) - 10 / 90) < 0.001

    def test_both_zero_uses_floor_of_one(self):
        # max(0, 0, 1) = 1, min(0, 0) = 0 → 0.0
        assert _rewrite_ratio(0, 0) == 0.0

    def test_one_line_each(self):
        # 1 added, 1 deleted → 1/1 = 1.0
        assert _rewrite_ratio(1, 1) == 1.0


# ---------------------------------------------------------------------------
# _per_commit_churn
# ---------------------------------------------------------------------------

class TestPerCommitChurn:
    def test_no_overlap_pure_add(self):
        commit = {"files": {"new.py"}, "insertions": 50, "deletions": 0}
        prev_files = {"old.py"}
        # overlap=0, rewrite=0 → 0.6*0 + 0.4*0 = 0.0
        assert _per_commit_churn(commit, prev_files) == 0.0

    def test_full_overlap_pure_rewrite(self):
        files = {"a.py", "b.py"}
        commit = {"files": files, "insertions": 50, "deletions": 50}
        # overlap=1.0, rewrite=1.0 → 0.6*1 + 0.4*1 = 1.0
        assert _per_commit_churn(commit, files) == 1.0

    def test_partial_overlap_mixed(self):
        commit = {"files": {"a.py", "b.py"}, "insertions": 20, "deletions": 10}
        prev_files = {"a.py", "c.py"}
        # overlap = 1/2 = 0.5, rewrite = 10/20 = 0.5
        # 0.6*0.5 + 0.4*0.5 = 0.3 + 0.2 = 0.5
        assert abs(_per_commit_churn(commit, prev_files) - 0.5) < 0.001

    def test_missing_files_key(self):
        commit = {"insertions": 10, "deletions": 5}
        prev_files = {"a.py"}
        # files defaults to empty set → overlap=0
        # rewrite = 5/10 = 0.5
        # 0.6*0 + 0.4*0.5 = 0.2
        assert abs(_per_commit_churn(commit, prev_files) - 0.2) < 0.001

    def test_missing_insertions_deletions(self):
        commit = {"files": {"a.py"}}
        prev_files = {"a.py"}
        # overlap=1.0, rewrite=0/1=0.0 (both default to 0)
        # 0.6*1 + 0.4*0 = 0.6
        assert abs(_per_commit_churn(commit, prev_files) - 0.6) < 0.001


# ---------------------------------------------------------------------------
# churn_index — empty and single
# ---------------------------------------------------------------------------

class TestChurnIndexEdgeCases:
    def test_empty_commits(self):
        result = churn_index([])
        assert result["score"] == 0
        assert result["band"] == "healthy"
        assert result["per_commit"] == []
        assert "no commits" in result["summary"]

    def test_single_commit(self):
        commits = [
            {"files": {"a.py"}, "insertions": 10, "deletions": 0},
        ]
        result = churn_index(commits)
        # single commit: effective = scores (no previous to skip for comparison,
        # but the code skips first only if len > 1)
        assert result["score"] == 0  # first commit has no prev, overlap=0, rewrite=0
        assert result["band"] == "healthy"

    def test_two_commits_no_overlap(self):
        commits = [
            {"files": {"a.py"}, "insertions": 10, "deletions": 0},
            {"files": {"b.py"}, "insertions": 20, "deletions": 0},
        ]
        result = churn_index(commits)
        # second commit: overlap=0 (different files), rewrite=0 (pure add)
        assert result["score"] == 0
        assert result["band"] == "healthy"


# ---------------------------------------------------------------------------
# churn_index — healthy workflow
# ---------------------------------------------------------------------------

class TestChurnIndexHealthy:
    def test_additive_distinct_files(self):
        commits = [
            {"files": {"a.py"}, "insertions": 50, "deletions": 0},
            {"files": {"b.py"}, "insertions": 30, "deletions": 0},
            {"files": {"c.py"}, "insertions": 40, "deletions": 5},
            {"files": {"d.py"}, "insertions": 20, "deletions": 0},
        ]
        result = churn_index(commits)
        assert result["band"] == "healthy"
        assert result["score"] < 30

    def test_mostly_additive_some_overlap(self):
        commits = [
            {"files": {"a.py", "b.py"}, "insertions": 50, "deletions": 0},
            {"files": {"c.py", "d.py"}, "insertions": 40, "deletions": 2},
            {"files": {"a.py", "e.py"}, "insertions": 30, "deletions": 3},
        ]
        result = churn_index(commits)
        assert result["band"] == "healthy"


# ---------------------------------------------------------------------------
# churn_index — stalled workflow
# ---------------------------------------------------------------------------

class TestChurnIndexStalled:
    def test_rewrite_loop(self):
        # same files, high ins and high dels — classic rewrite loop
        commits = [
            {"files": {"a.py", "b.py"}, "insertions": 50, "deletions": 50},
            {"files": {"a.py", "b.py"}, "insertions": 48, "deletions": 52},
            {"files": {"a.py", "b.py"}, "insertions": 51, "deletions": 49},
            {"files": {"a.py", "b.py"}, "insertions": 50, "deletions": 50},
        ]
        result = churn_index(commits)
        assert result["band"] == "stalled"
        assert result["score"] >= 60

    def test_churning_moderate_overlap(self):
        commits = [
            {"files": {"a.py", "b.py", "c.py"}, "insertions": 30, "deletions": 20},
            {"files": {"a.py", "b.py"}, "insertions": 25, "deletions": 25},
            {"files": {"a.py", "b.py", "d.py"}, "insertions": 30, "deletions": 15},
        ]
        result = churn_index(commits)
        # moderate overlap + moderate rewrite → should be churning or stalled
        assert result["score"] >= 30


# ---------------------------------------------------------------------------
# _band
# ---------------------------------------------------------------------------

class TestBand:
    def test_healthy_range(self):
        assert _band(0) == "healthy"
        assert _band(15) == "healthy"
        assert _band(29) == "healthy"

    def test_healthy_boundary(self):
        assert _band(29) == "healthy"
        assert _band(30) == "churning"

    def test_churning_range(self):
        assert _band(30) == "churning"
        assert _band(45) == "churning"
        assert _band(59) == "churning"

    def test_churning_boundary(self):
        assert _band(59) == "churning"
        assert _band(60) == "stalled"

    def test_stalled_range(self):
        assert _band(60) == "stalled"
        assert _band(80) == "stalled"
        assert _band(100) == "stalled"

    def test_all_boundaries(self):
        boundaries = [
            (0, "healthy"),
            (29, "healthy"),
            (30, "churning"),
            (59, "churning"),
            (60, "stalled"),
            (100, "stalled"),
        ]
        for score, expected in boundaries:
            assert _band(score) == expected, f"score={score} should be {expected}"


# ---------------------------------------------------------------------------
# churn_index — summary and per_commit
# ---------------------------------------------------------------------------

class TestChurnIndexOutput:
    def test_summary_format(self):
        commits = [
            {"files": {"a.py"}, "insertions": 10, "deletions": 0},
            {"files": {"b.py"}, "insertions": 20, "deletions": 0},
            {"files": {"a.py"}, "insertions": 15, "deletions": 10},
        ]
        result = churn_index(commits)
        assert "3 commits analysed" in result["summary"]
        assert "mean churn" in result["summary"]

    def test_per_commit_length_matches_input(self):
        commits = [
            {"files": {"a.py"}, "insertions": 10, "deletions": 0},
            {"files": {"b.py"}, "insertions": 20, "deletions": 5},
            {"files": {"c.py"}, "insertions": 30, "deletions": 0},
        ]
        result = churn_index(commits)
        assert len(result["per_commit"]) == len(commits)

    def test_score_clamped_to_0_100(self):
        # even with pathological input, score should be 0–100
        commits = [
            {"files": {"a.py"}, "insertions": 100, "deletions": 100},
            {"files": {"a.py"}, "insertions": 100, "deletions": 100},
        ]
        result = churn_index(commits)
        assert 0 <= result["score"] <= 100

    def test_high_churn_count_in_summary(self):
        commits = [
            {"files": {"a.py"}, "insertions": 50, "deletions": 50},
            {"files": {"a.py"}, "insertions": 48, "deletions": 52},
            {"files": {"a.py"}, "insertions": 50, "deletions": 50},
        ]
        result = churn_index(commits)
        assert "high-churn commits" in result["summary"]


# ---------------------------------------------------------------------------
# integration: realistic scenarios
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_healthy_growth_pattern(self):
        """simulate a writer adding new files with minimal rewrites."""
        commits = []
        for i in range(20):
            commits.append({
                "files": {f"note_{i}.md", "index.md"},
                "insertions": 25,
                "deletions": 2,
            })
        result = churn_index(commits)
        # index.md overlap every time but only partial; rewrite_ratio low
        assert result["band"] in ("healthy", "churning")

    def test_stalled_rewrite_cycle(self):
        """simulate a writer stuck in a rewrite loop."""
        commits = []
        for i in range(15):
            commits.append({
                "files": {"core.py", "utils.py", "config.py"},
                "insertions": 40 + (i % 5),
                "deletions": 38 + (i % 7),
            })
        result = churn_index(commits)
        assert result["band"] == "stalled"
        assert result["score"] >= 60
