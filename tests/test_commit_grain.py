"""Tests for iamai.commit_grain — commit granularity analysis."""

import os
import subprocess
import tempfile
import shutil

import pytest

from iamai.commit_grain import (
    CommitGrain,
    classify_commit,
    grain_report,
    BUCKETS,
)


# ---------------------------------------------------------------------------
# classify_commit
# ---------------------------------------------------------------------------

class TestClassifyCommit:
    def test_empty_zero(self):
        assert classify_commit(0) == "empty"

    def test_empty_negative(self):
        assert classify_commit(-1) == "empty"

    def test_atomic_one(self):
        assert classify_commit(1) == "atomic"

    def test_atomic_two(self):
        assert classify_commit(2) == "atomic"

    def test_normal_three(self):
        assert classify_commit(3) == "normal"

    def test_normal_ten(self):
        assert classify_commit(10) == "normal"

    def test_broad_eleven(self):
        assert classify_commit(11) == "broad"

    def test_broad_fifty(self):
        assert classify_commit(50) == "broad"

    def test_mega_fiftyone(self):
        assert classify_commit(51) == "mega"

    def test_mega_large(self):
        assert classify_commit(500) == "mega"


# ---------------------------------------------------------------------------
# CommitGrain — empty / edge cases
# ---------------------------------------------------------------------------

class TestCommitGrainEmpty:
    def test_empty_repo(self, tmp_path):
        """An empty git repo should return 0 for all metrics."""
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        cg = CommitGrain(str(tmp_path))
        assert cg.total_commits == 0
        assert cg.median_files == 0.0
        assert cg.mean_files == 0.0
        assert cg.consistency == 1.0
        assert cg.mega_pct == 0.0
        assert cg.trivial_pct == 0.0
        assert cg.grade == "excellent"

    def test_file_counts_empty(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        cg = CommitGrain(str(tmp_path))
        assert cg.file_counts == []

    def test_bucket_distribution_empty(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        cg = CommitGrain(str(tmp_path))
        dist = cg.bucket_distribution()
        assert all(v == 0 for v in dist.values())
        assert set(dist.keys()) == set(BUCKETS)

    def test_summary_keys(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        cg = CommitGrain(str(tmp_path))
        s = cg.summary()
        expected_keys = {
            "total_commits", "median_files", "mean_files", "consistency",
            "mega_pct", "trivial_pct", "atomic_pct", "grade", "buckets",
        }
        assert set(s.keys()) == expected_keys


# ---------------------------------------------------------------------------
# CommitGrain — with real commits
# ---------------------------------------------------------------------------

def _make_repo_with_commits(tmp_path, file_counts):
    """Create a git repo with commits touching specified file counts.

    file_counts is a list of ints; each int is the number of files
    that commit should touch.
    """
    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    subprocess.run(["git", "init", repo], capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        cwd=repo, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, capture_output=True,
    )

    file_counter = 0
    for i, n_files in enumerate(file_counts):
        for j in range(n_files):
            fname = os.path.join(repo, f"f_{file_counter:04d}.txt")
            with open(fname, "w") as f:
                f.write(f"content {file_counter}\n")
            file_counter += 1
        subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"commit {i}: {n_files} files",
             "--allow-empty"],
            cwd=repo, capture_output=True,
        )
    return repo


class TestCommitGrainWithCommits:
    def test_single_atomic_commit(self, tmp_path):
        repo = _make_repo_with_commits(tmp_path, [1])
        cg = CommitGrain(repo)
        assert cg.total_commits == 1
        assert cg.median_files == 1.0
        assert cg.mean_files == 1.0

    def test_uniform_commits(self, tmp_path):
        """All commits same size → consistency should be 1.0."""
        repo = _make_repo_with_commits(tmp_path, [5, 5, 5, 5, 5])
        cg = CommitGrain(repo)
        assert cg.consistency == pytest.approx(1.0, abs=0.01)
        assert cg.median_files == 5.0
        assert cg.mean_files == 5.0

    def test_mixed_commits(self, tmp_path):
        """Varying sizes → consistency < 1.0."""
        repo = _make_repo_with_commits(tmp_path, [3, 5, 7, 4, 6])
        cg = CommitGrain(repo)
        assert 0.0 < cg.consistency < 1.0
        assert cg.median_files == 5.0

    def test_mega_detection(self, tmp_path):
        repo = _make_repo_with_commits(tmp_path, [100, 1, 1, 1, 1])
        cg = CommitGrain(repo)
        assert cg.mega_pct == pytest.approx(20.0, abs=0.1)

    def test_trivial_detection(self, tmp_path):
        repo = _make_repo_with_commits(tmp_path, [1, 1, 1, 1, 5])
        cg = CommitGrain(repo)
        # 4 out of 5 commits are trivial (1 file each)
        assert cg.trivial_pct == pytest.approx(80.0, abs=0.1)

    def test_grade_excellent(self, tmp_path):
        """Uniform medium commits → excellent."""
        repo = _make_repo_with_commits(tmp_path, [5] * 20)
        cg = CommitGrain(repo)
        assert cg.grade == "excellent"

    def test_grade_degrades_with_mega(self, tmp_path):
        """Many mega commits should lower the grade."""
        repo = _make_repo_with_commits(tmp_path, [100] * 20)
        cg = CommitGrain(repo)
        assert cg.grade in ("coarse", "chaotic", "fair")

    def test_max_commits_limits(self, tmp_path):
        repo = _make_repo_with_commits(tmp_path, [3] * 30)
        cg = CommitGrain(repo, max_commits=10)
        assert cg.total_commits <= 10

    def test_file_counts_returns_list(self, tmp_path):
        repo = _make_repo_with_commits(tmp_path, [2, 7, 3])
        cg = CommitGrain(repo)
        fc = cg.file_counts
        assert isinstance(fc, list)
        assert len(fc) == 3
        assert all(isinstance(x, int) for x in fc)


# ---------------------------------------------------------------------------
# grain_report
# ---------------------------------------------------------------------------

class TestGrainReport:
    def test_report_format(self, tmp_path):
        repo = _make_repo_with_commits(tmp_path, [5, 5, 5])
        report = grain_report(repo)
        assert "commit grain:" in report
        assert "median" in report
        assert "consistency" in report
        assert "mega" in report
        assert "trivial" in report

    def test_report_empty_repo(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        report = grain_report(str(tmp_path))
        assert "excellent" in report

    def test_report_returns_string(self, tmp_path):
        repo = _make_repo_with_commits(tmp_path, [3, 8, 15])
        report = grain_report(repo)
        assert isinstance(report, str)
        assert len(report) > 10


# ---------------------------------------------------------------------------
# Buckets
# ---------------------------------------------------------------------------

class TestBuckets:
    def test_buckets_list(self):
        assert BUCKETS == ["empty", "atomic", "normal", "broad", "mega"]

    def test_all_buckets_covered(self):
        """Every non-negative integer should map to exactly one bucket."""
        for n in range(100):
            assert classify_commit(n) in BUCKETS
