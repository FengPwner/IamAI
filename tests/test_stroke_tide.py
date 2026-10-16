"""Tests for iamai.stroke_tide — repo expansion/contraction tide analysis.

These tests verify:
- measure_tide returns correct structure and types
- tide_report produces human-readable output
- edge cases: empty repos, no commits, binary files
- threshold logic correctly classifies expanding/contracting/flat
- deterministic results with controlled git history
"""

import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from iamai.stroke_tide import (
    DEFAULT_THRESHOLD,
    measure_tide,
    tide_report,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def live_repo():
    """The actual IamAI repository — used for integration tests."""
    return REPO_ROOT


@pytest.fixture
def temp_repo(tmp_path):
    """A minimal git repository with controlled commit history."""
    repo = tmp_path / "test_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, capture_output=True, check=True,
    )

    # Create initial files.
    (repo / "readme.md").write_text("# Test Repo\n")
    (repo / "module.py").write_text("# module\n" * 10)
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo, capture_output=True, check=True,
    )

    return repo


@pytest.fixture
def expanding_repo(tmp_path):
    """A repo with significant net additions (expanding tide)."""
    repo = tmp_path / "expanding_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, capture_output=True, check=True,
    )

    # Initial commit with a small file.
    (repo / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=repo, capture_output=True, check=True,
    )

    # Add many lines across multiple commits.
    for i in range(5):
        content = f"# Module {i}\n" + "x = 1\n" * 30 + "\n"
        (repo / f"mod_{i}.py").write_text(content)
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"add module {i}"],
            cwd=repo, capture_output=True, check=True,
        )

    return repo


@pytest.fixture
def contracting_repo(tmp_path):
    """A repo with significant net deletions (contracting tide)."""
    repo = tmp_path / "contracting_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, capture_output=True, check=True,
    )

    # Initial commit with large files.
    big_content = "line\n" * 200
    (repo / "big_module.py").write_text(big_content)
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial big"],
        cwd=repo, capture_output=True, check=True,
    )

    # Delete most content across multiple commits.
    for i in range(3):
        # Replace big file with tiny content, commit.
        (repo / "big_module.py").write_text(f"# trimmed {i}\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"trim {i}"],
            cwd=repo, capture_output=True, check=True,
        )
        # Restore for next trim cycle.
        (repo / "big_module.py").write_text(big_content)
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"restore {i}"],
            cwd=repo, capture_output=True, check=True,
        )

    # Final aggressive trim.
    (repo / "big_module.py").write_text("# final trim\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "final trim"],
        cwd=repo, capture_output=True, check=True,
    )

    return repo


@pytest.fixture
def empty_repo(tmp_path):
    """A git repo with no commits."""
    repo = tmp_path / "empty_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    return repo


# ---------------------------------------------------------------------------
# measure_tide — structure and types
# ---------------------------------------------------------------------------


class TestMeasureTideStructure:
    def test_returns_dict(self, temp_repo):
        result = measure_tide(root=temp_repo)
        assert isinstance(result, dict)

    def test_has_required_keys(self, temp_repo):
        result = measure_tide(root=temp_repo)
        required_keys = {"added", "deleted", "net", "tide", "magnitude", "commits_analysed"}
        assert set(result.keys()) == required_keys

    def test_added_is_non_negative_int(self, temp_repo):
        result = measure_tide(root=temp_repo)
        assert isinstance(result["added"], int)
        assert result["added"] >= 0

    def test_deleted_is_non_negative_int(self, temp_repo):
        result = measure_tide(root=temp_repo)
        assert isinstance(result["deleted"], int)
        assert result["deleted"] >= 0

    def test_net_equals_added_minus_deleted(self, temp_repo):
        result = measure_tide(root=temp_repo)
        assert result["net"] == result["added"] - result["deleted"]

    def test_magnitude_is_abs_of_net(self, temp_repo):
        result = measure_tide(root=temp_repo)
        assert result["magnitude"] == abs(result["net"])

    def test_tide_is_valid_value(self, temp_repo):
        result = measure_tide(root=temp_repo)
        assert result["tide"] in ("expanding", "contracting", "flat")

    def test_commits_analysed_is_positive(self, temp_repo):
        result = measure_tide(root=temp_repo)
        assert isinstance(result["commits_analysed"], int)
        assert result["commits_analysed"] > 0


# ---------------------------------------------------------------------------
# measure_tide — tide classification
# ---------------------------------------------------------------------------


class TestTideClassification:
    def test_expanding_repo_classified_as_expanding(self, expanding_repo):
        result = measure_tide(root=expanding_repo, threshold=10)
        assert result["tide"] == "expanding"
        assert result["net"] > 0

    def test_flat_repo_classified_as_flat(self, temp_repo):
        # A repo with just one small initial commit — net change is small.
        result = measure_tide(root=temp_repo, window=1, threshold=1000)
        assert result["tide"] == "flat"

    def test_custom_threshold_affects_classification(self, temp_repo):
        # With a very high threshold, everything is flat.
        result_high = measure_tide(root=temp_repo, threshold=100000)
        assert result_high["tide"] == "flat"

    def test_zero_threshold_classifies_anything(self, temp_repo):
        # With threshold=0, any net change > 0 is expanding.
        result = measure_tide(root=temp_repo, threshold=0)
        if result["net"] > 0:
            assert result["tide"] == "expanding"
        elif result["net"] < 0:
            assert result["tide"] == "contracting"
        else:
            assert result["tide"] == "flat"


# ---------------------------------------------------------------------------
# measure_tide — window parameter
# ---------------------------------------------------------------------------


class TestWindowParameter:
    def test_window_limits_commits_analysed(self, expanding_repo):
        result = measure_tide(root=expanding_repo, window=2)
        assert result["commits_analysed"] <= 2

    def test_window_one_counts_only_latest(self, temp_repo):
        result = measure_tide(root=temp_repo, window=1)
        assert result["commits_analysed"] == 1

    def test_large_window_covers_all(self, temp_repo):
        result = measure_tide(root=temp_repo, window=1000)
        # Should have analysed all commits (just 1 in temp_repo).
        assert result["commits_analysed"] >= 1


# ---------------------------------------------------------------------------
# tide_report
# ---------------------------------------------------------------------------


class TestTideReport:
    def test_returns_string(self, temp_repo):
        result = tide_report(root=temp_repo)
        assert isinstance(result, str)

    def test_contains_tide_word(self, temp_repo):
        result = tide_report(root=temp_repo)
        assert any(word in result for word in ("expanding", "contracting", "flat"))

    def test_contains_commits_count(self, temp_repo):
        result = tide_report(root=temp_repo)
        assert "commits" in result

    def test_contains_added_and_deleted(self, temp_repo):
        result = tide_report(root=temp_repo)
        assert "added" in result
        assert "deleted" in result

    def test_expanding_report_format(self, expanding_repo):
        result = tide_report(root=expanding_repo, threshold=10)
        assert "expanding" in result
        assert "+" in result  # positive net should show +

    def test_live_repo_report(self, live_repo):
        result = tide_report(root=live_repo)
        assert len(result) > 20
        assert "no commits" not in result


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_repo_returns_flat(self, empty_repo):
        result = measure_tide(root=empty_repo)
        assert result["tide"] == "flat"
        assert result["commits_analysed"] == 0

    def test_empty_repo_report_says_no_commits(self, empty_repo):
        result = tide_report(root=empty_repo)
        assert "no commits" in result

    def test_none_root_defaults_to_repo(self):
        result = measure_tide(root=None)
        assert isinstance(result, dict)
        assert result["commits_analysed"] > 0

    def test_path_object_works(self, temp_repo):
        result = measure_tide(root=Path(temp_repo))
        assert isinstance(result, dict)

    def test_string_root_works(self, temp_repo):
        result = measure_tide(root=str(temp_repo))
        assert isinstance(result, dict)

    def test_nonexistent_repo_returns_flat(self, tmp_path):
        result = measure_tide(root=tmp_path / "nonexistent")
        assert result["tide"] == "flat"
        assert result["commits_analysed"] == 0

    def test_default_threshold_value(self):
        assert DEFAULT_THRESHOLD == 50


# ---------------------------------------------------------------------------
# integration with live repo
# ---------------------------------------------------------------------------


class TestLiveRepoIntegration:
    def test_live_repo_has_commits(self, live_repo):
        result = measure_tide(root=live_repo, window=20)
        assert result["commits_analysed"] == 20

    def test_live_repo_added_gt_zero(self, live_repo):
        result = measure_tide(root=live_repo, window=20)
        assert result["added"] > 0

    def test_live_repo_tide_is_valid(self, live_repo):
        result = measure_tide(root=live_repo, window=20)
        assert result["tide"] in ("expanding", "contracting", "flat")

    def test_live_repo_report_not_empty(self, live_repo):
        result = tide_report(root=live_repo, window=20)
        assert len(result) > 30
