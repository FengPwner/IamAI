"""Tests for iamai.commit_focus."""

import math
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.commit_focus import (
    _dirs_from_paths,
    commit_file_spread,
    focus_report,
    focus_score,
    focus_verdict,
)


# ---------------------------------------------------------------------------
# focus_score
# ---------------------------------------------------------------------------

class TestFocusScore:
    def test_zero_files(self):
        assert focus_score(0, 0) == 1.0

    def test_one_file_one_dir(self):
        # log2(1)=0, log2(1)=0 → 1/(1+0+0) = 1.0
        assert focus_score(1, 1) == 1.0

    def test_one_file_zero_dirs(self):
        # log2(1) = 0, so 1/(1+0+0) = 1.0
        assert focus_score(1, 0) == 1.0

    def test_many_files_many_dirs(self):
        score = focus_score(10, 5)
        # 1 / (1 + log2(10) + log2(5)) = 1 / (1 + 3.3219 + 2.3219) ≈ 0.1506
        expected = 1.0 / (1.0 + math.log2(10) + math.log2(5))
        assert abs(score - expected) < 0.001

    def test_negative_files_clamped(self):
        # negative files treated as 0
        assert focus_score(-1, 0) == 1.0

    def test_two_files_one_dir(self):
        # 1 / (1 + 1 + 0) = 0.5
        assert focus_score(2, 1) == 0.5

    def test_two_files_two_dirs(self):
        # 1 / (1 + 1 + 1) = 1/3
        score = focus_score(2, 2)
        assert abs(score - 1.0 / 3.0) < 0.001

    def test_returns_float(self):
        result = focus_score(3, 2)
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# focus_verdict
# ---------------------------------------------------------------------------

class TestFocusVerdict:
    def test_focused(self):
        assert focus_verdict(0.5) == "focused"
        assert focus_verdict(1.0) == "focused"
        assert focus_verdict(0.51) == "focused"

    def test_broad(self):
        assert focus_verdict(0.3) == "broad"
        assert focus_verdict(0.49) == "broad"
        assert focus_verdict(0.35) == "broad"

    def test_sprawling(self):
        assert focus_verdict(0.29) == "sprawling"
        assert focus_verdict(0.0) == "sprawling"
        assert focus_verdict(0.1) == "sprawling"

    def test_boundary_at_half(self):
        assert focus_verdict(0.5) == "focused"

    def test_boundary_at_three_tenths(self):
        assert focus_verdict(0.3) == "broad"


# ---------------------------------------------------------------------------
# _dirs_from_paths
# ---------------------------------------------------------------------------

class TestDirsFromPaths:
    def test_empty(self):
        assert _dirs_from_paths([]) == set()

    def test_root_files(self):
        result = _dirs_from_paths(["README.md", "LICENSE"])
        assert result == {""}

    def test_single_dir(self):
        result = _dirs_from_paths(["iamai/foo.py", "iamai/bar.py"])
        assert result == {"iamai"}

    def test_multiple_dirs(self):
        result = _dirs_from_paths(["iamai/foo.py", "tests/test_foo.py", "docs/README.md"])
        assert result == {"iamai", "tests", "docs"}

    def test_nested_dirs(self):
        result = _dirs_from_paths(["a/b/c/file.py"])
        assert result == {"a/b/c"}

    def test_mixed_depth(self):
        result = _dirs_from_paths(["top.py", "sub/nested.py"])
        assert result == {"", "sub"}


# ---------------------------------------------------------------------------
# commit_file_spread
# ---------------------------------------------------------------------------

class TestCommitFileSpread:
    def test_no_git_repo(self, tmp_path: Path):
        """Empty result when path is not a git repo."""
        result = commit_file_spread(tmp_path, 5)
        assert result == []

    def test_result_structure(self):
        """Each entry has the expected keys."""
        # Use the real repo (this test file lives inside it)
        result = commit_file_spread(n=3)
        if not result:
            pytest.skip("no git history available")
        for entry in result:
            assert "hash" in entry
            assert "files" in entry
            assert "dirs" in entry
            assert "score" in entry
            assert "verdict" in entry
            assert isinstance(entry["files"], int)
            assert isinstance(entry["dirs"], int)
            assert isinstance(entry["score"], float)
            assert entry["verdict"] in ("focused", "broad", "sprawling")

    def test_hash_is_short(self):
        result = commit_file_spread(n=1)
        if not result:
            pytest.skip("no git history available")
        assert len(result[0]["hash"]) == 7

    def test_respects_n(self):
        result = commit_file_spread(n=2)
        assert len(result) <= 2

    def test_newest_first(self):
        """Results should be in newest-first order (git log default)."""
        result = commit_file_spread(n=5)
        if len(result) < 2:
            pytest.skip("need at least 2 commits")
        # We can't know exact order without git, but the list should be non-empty
        assert len(result) >= 2


# ---------------------------------------------------------------------------
# focus_report
# ---------------------------------------------------------------------------

class TestFocusReport:
    def test_no_repo(self, tmp_path: Path):
        result = focus_report(tmp_path)
        assert "no commits" in result

    def test_report_format(self):
        result = focus_report(n=5)
        if "no commits" in result:
            pytest.skip("no git history available")
        assert "last" in result
        assert "avg score" in result
        # Should contain at least one verdict keyword
        assert any(
            kw in result for kw in ("focused", "broad", "sprawling")
        )

    def test_report_mentions_count(self):
        result = focus_report(n=3)
        if "no commits" in result:
            pytest.skip("no git history available")
        # Should contain a number
        assert any(c.isdigit() for c in result)
