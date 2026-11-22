"""tests for iamai.commit_churn — commit churn index.

visit 789: close the last test gap in core metrics.  commit_churn
was the only module in iamai/ still without dedicated tests after
the visit-788 sweep.

test areas:
    1. _file_overlap  — empty sets, full overlap, partial, disjoint
    2. _rewrite_ratio — pure add, pure rewrite, asymmetric, zeros
    3. _per_commit_churn — weighted blend, edge inputs
    4. churn_index — bands, empty input, single commit, many commits
    5. _band — threshold boundaries
    6. CLI integration — exit codes, --json flag, --count flag
    7. edge cases — malformed dicts, negative values, large inputs
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.commit_churn import (
    _band,
    _file_overlap,
    _per_commit_churn,
    _rewrite_ratio,
    churn_index,
)


# ---------------------------------------------------------------------------
# 1. _file_overlap
# ---------------------------------------------------------------------------

class TestFileOverlap:
    def test_both_empty(self):
        assert _file_overlap(set(), set()) == 0.0

    def test_current_empty(self):
        assert _file_overlap(set(), {"a.md", "b.md"}) == 0.0

    def test_previous_empty(self):
        assert _file_overlap({"a.md"}, set()) == 0.0

    def test_full_overlap(self):
        assert _file_overlap({"a.md", "b.md"}, {"a.md", "b.md"}) == 1.0

    def test_half_overlap(self):
        result = _file_overlap({"a.md", "b.md"}, {"a.md", "c.md"})
        assert result == pytest.approx(0.5)

    def test_disjoint(self):
        assert _file_overlap({"a.md"}, {"b.md"}) == 0.0

    def test_subset(self):
        result = _file_overlap({"a.md"}, {"a.md", "b.md", "c.md"})
        assert result == 1.0

    def test_superset(self):
        result = _file_overlap({"a.md", "b.md", "c.md"}, {"a.md"})
        assert result == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# 2. _rewrite_ratio
# ---------------------------------------------------------------------------

class TestRewriteRatio:
    def test_pure_add(self):
        assert _rewrite_ratio(100, 0) == 0.0

    def test_pure_delete(self):
        assert _rewrite_ratio(0, 100) == 0.0

    def test_pure_rewrite(self):
        assert _rewrite_ratio(50, 50) == 1.0

    def test_mostly_add(self):
        result = _rewrite_ratio(90, 10)
        assert result == pytest.approx(10 / 90)

    def test_mostly_delete(self):
        result = _rewrite_ratio(10, 90)
        assert result == pytest.approx(10 / 90)

    def test_both_zero(self):
        # max(0, 0, 1) = 1 → min(0, 0)/1 = 0.0
        assert _rewrite_ratio(0, 0) == 0.0

    def test_both_one(self):
        assert _rewrite_ratio(1, 1) == 1.0

    def test_asymmetric_large(self):
        result = _rewrite_ratio(1000, 500)
        assert result == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 3. _per_commit_churn
# ---------------------------------------------------------------------------

class TestPerCommitChurn:
    def test_no_overlap_pure_add(self):
        commit = {"files": {"new.md"}, "insertions": 10, "deletions": 0}
        score = _per_commit_churn(commit, {"other.md"})
        assert score == 0.0

    def test_full_overlap_pure_rewrite(self):
        commit = {"files": {"a.md"}, "insertions": 50, "deletions": 50}
        score = _per_commit_churn(commit, {"a.md"})
        # 0.6 * 1.0 + 0.4 * 1.0 = 1.0
        assert score == pytest.approx(1.0)

    def test_half_overlap_mixed(self):
        commit = {"files": {"a.md", "b.md"}, "insertions": 80, "deletions": 20}
        prev = {"a.md", "c.md"}
        # overlap: 1/2 = 0.5, rewrite: 20/80 = 0.25
        expected = 0.6 * 0.5 + 0.4 * 0.25
        assert _per_commit_churn(commit, prev) == pytest.approx(expected)

    def test_empty_commit_files(self):
        commit = {"files": set(), "insertions": 0, "deletions": 0}
        score = _per_commit_churn(commit, {"a.md"})
        assert score == 0.0

    def test_missing_keys_default(self):
        # get() with defaults → files=[], ins=0, del=0
        score = _per_commit_churn({}, {"a.md"})
        assert score == 0.0

    def test_weighted_blend(self):
        commit = {"files": {"x.md"}, "insertions": 30, "deletions": 70}
        prev = {"x.md"}
        # overlap: 1.0, rewrite: 30/70 ≈ 0.4286
        expected = 0.6 * 1.0 + 0.4 * (30 / 70)
        assert _per_commit_churn(commit, prev) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 4. churn_index
# ---------------------------------------------------------------------------

class TestChurnIndex:
    def test_empty_commits(self):
        result = churn_index([])
        assert result["score"] == 0
        assert result["band"] == "healthy"
        assert result["per_commit"] == []
        assert "no commits" in result["summary"]

    def test_single_commit(self):
        commits = [
            {"files": {"a.md"}, "insertions": 10, "deletions": 0},
        ]
        result = churn_index(commits)
        # single commit → effective = scores (no skip)
        assert 0 <= result["score"] <= 100
        assert len(result["per_commit"]) == 1

    def test_two_additive_commits_no_overlap(self):
        commits = [
            {"files": {"a.md"}, "insertions": 10, "deletions": 0},
            {"files": {"b.md"}, "insertions": 20, "deletions": 0},
        ]
        result = churn_index(commits)
        # second commit: overlap 0, rewrite 0 → score 0
        assert result["score"] == 0
        assert result["band"] == "healthy"

    def test_heavy_churn(self):
        commits = [
            {"files": {"a.md"}, "insertions": 50, "deletions": 50},
            {"files": {"a.md"}, "insertions": 50, "deletions": 50},
            {"files": {"a.md"}, "insertions": 50, "deletions": 50},
        ]
        result = churn_index(commits)
        # all commits: overlap 1.0, rewrite 1.0 → 1.0 each
        # effective = scores[1:] = [1.0, 1.0] → mean 1.0 → score 100
        assert result["score"] == 100
        assert result["band"] == "stalled"

    def test_mixed_pattern(self):
        commits = [
            {"files": {"a.md"}, "insertions": 100, "deletions": 0},
            {"files": {"b.md"}, "insertions": 50, "deletions": 50},
            {"files": {"c.md"}, "insertions": 80, "deletions": 5},
        ]
        result = churn_index(commits)
        assert 0 <= result["score"] <= 100
        assert len(result["per_commit"]) == 3

    def test_score_clamped_to_100(self):
        # contrived: per-commit churn could theoretically exceed 1.0
        # due to rounding, ensure score is clamped
        commits = [
            {"files": {"a.md"}, "insertions": 10, "deletions": 10},
            {"files": {"a.md"}, "insertions": 10, "deletions": 10},
        ]
        result = churn_index(commits)
        assert result["score"] <= 100

    def test_band_healthy(self):
        commits = [
            {"files": {"a.md"}, "insertions": 100, "deletions": 0},
            {"files": {"b.md"}, "insertions": 100, "deletions": 0},
        ]
        result = churn_index(commits)
        assert result["band"] == "healthy"

    def test_summary_contains_stats(self):
        commits = [
            {"files": {"a.md"}, "insertions": 10, "deletions": 0},
            {"files": {"b.md"}, "insertions": 20, "deletions": 5},
        ]
        result = churn_index(commits)
        assert "2 commits analysed" in result["summary"]
        assert "mean churn" in result["summary"]
        assert "high-churn commits" in result["summary"]

    def test_per_commit_length(self):
        commits = [
            {"files": {f"f{i}.md"}, "insertions": i, "deletions": 0}
            for i in range(10)
        ]
        result = churn_index(commits)
        assert len(result["per_commit"]) == 10

    def test_many_low_churn_commits(self):
        commits = [
            {"files": {f"file{i}.md"}, "insertions": 100, "deletions": 0}
            for i in range(50)
        ]
        result = churn_index(commits)
        assert result["score"] == 0
        assert result["band"] == "healthy"


# ---------------------------------------------------------------------------
# 5. _band
# ---------------------------------------------------------------------------

class TestBand:
    def test_zero(self):
        assert _band(0) == "healthy"

    def test_boundary_29(self):
        assert _band(29) == "healthy"

    def test_boundary_30(self):
        assert _band(30) == "churning"

    def test_boundary_59(self):
        assert _band(59) == "churning"

    def test_boundary_60(self):
        assert _band(60) == "stalled"

    def test_hundred(self):
        assert _band(100) == "stalled"


# ---------------------------------------------------------------------------
# 6. CLI integration
# ---------------------------------------------------------------------------

class TestCLI:
    """test the commit_churn_index.py CLI wrapper."""

    CLI = str(REPO / "tools" / "commit_churn_index.py")

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, self.CLI, *args],
            capture_output=True, text=True, cwd=REPO,
            timeout=30,
        )

    def test_default_output(self):
        r = self._run("--count", "5")
        # exit code 0, 1, or 2 are all valid
        assert r.returncode in (0, 1, 2)
        assert "commit churn index" in r.stdout
        assert "commits analysed" in r.stdout

    def test_json_output(self):
        r = self._run("--count", "5", "--json")
        assert r.returncode in (0, 1, 2)
        data = json.loads(r.stdout)
        assert "score" in data
        assert "band" in data
        assert data["band"] in ("healthy", "churning", "stalled")

    def test_count_flag(self):
        r = self._run("--count", "3", "--json")
        data = json.loads(r.stdout)
        # per_commit should have at most 3 entries
        assert len(data["per_commit"]) <= 3

    def test_exit_code_matches_band(self):
        r = self._run("--count", "5", "--json")
        data = json.loads(r.stdout)
        expected = {"healthy": 0, "churning": 1, "stalled": 2}
        assert r.returncode == expected[data["band"]]


# ---------------------------------------------------------------------------
# 7. edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_negative_insertions(self):
        # negative values shouldn't crash; rewrite_ratio handles via min/max
        commit = {"files": {"a.md"}, "insertions": -5, "deletions": 10}
        score = _per_commit_churn(commit, {"a.md"})
        assert isinstance(score, float)

    def test_negative_deletions(self):
        commit = {"files": {"a.md"}, "insertions": 10, "deletions": -5}
        score = _per_commit_churn(commit, {"a.md"})
        assert isinstance(score, float)

    def test_very_large_numbers(self):
        commit = {"files": {"a.md"}, "insertions": 10**9, "deletions": 10**9}
        score = _per_commit_churn(commit, {"a.md"})
        assert score == pytest.approx(1.0)

    def test_files_as_list_instead_of_set(self):
        # commit["files"] might be a list from JSON deserialization
        commit = {"files": ["a.md", "b.md"], "insertions": 10, "deletions": 0}
        score = _per_commit_churn(commit, {"a.md", "b.md"})
        # set(["a.md", "b.md"]) works fine
        assert score == pytest.approx(0.6 * 1.0 + 0.4 * 0.0)

    def test_churn_index_json_serializable(self):
        commits = [
            {"files": {"a.md"}, "insertions": 10, "deletions": 5},
            {"files": {"a.md"}, "insertions": 8, "deletions": 12},
        ]
        result = churn_index(commits)
        # should be JSON-serializable
        serialized = json.dumps(result)
        parsed = json.loads(serialized)
        assert parsed["score"] == result["score"]

    def test_identical_consecutive_commits(self):
        commit = {"files": {"a.md", "b.md"}, "insertions": 20, "deletions": 20}
        commits = [commit] * 10
        result = churn_index(commits)
        # all overlap=1.0, rewrite=1.0 → score should be 100
        assert result["score"] == 100
        assert result["band"] == "stalled"

    def test_alternating_pattern(self):
        commits = [
            {"files": {"a.md"}, "insertions": 100, "deletions": 0},
            {"files": {"a.md"}, "insertions": 0, "deletions": 100},
            {"files": {"a.md"}, "insertions": 100, "deletions": 0},
            {"files": {"a.md"}, "insertions": 0, "deletions": 100},
        ]
        result = churn_index(commits)
        # overlap always 1.0, rewrite always 0/100 → 0.0 ratio
        # score = 0.6 * 1.0 + 0.4 * 0.0 = 0.6 → 60
        assert result["band"] in ("churning", "stalled")
