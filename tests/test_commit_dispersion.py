"""Tests for iamai.commit_dispersion."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.commit_dispersion import (
    _entropy,
    _median,
    _parse_numstat,
    _top_dirs,
    commit_dispersion,
    dispersion_report,
)


# ---------------------------------------------------------------------------
# _top_dirs
# ---------------------------------------------------------------------------

class TestTopDirs:
    def test_single_dir(self):
        assert _top_dirs(["iamai/foo.py", "iamai/bar.py"]) == {"iamai"}

    def test_multiple_dirs(self):
        result = _top_dirs(["iamai/foo.py", "tests/test_foo.py", "README.md"])
        assert result == {"iamai", "tests", "(root)"}

    def test_root_files(self):
        assert _top_dirs(["README.md", "LICENSE"]) == {"(root)"}

    def test_empty(self):
        assert _top_dirs([]) == set()

    def test_nested_counts_top_only(self):
        result = _top_dirs(["a/b/c/d.py", "a/x/y.py"])
        assert result == {"a"}


# ---------------------------------------------------------------------------
# _entropy
# ---------------------------------------------------------------------------

class TestEntropy:
    def test_uniform_high_entropy(self):
        # All equal → max entropy → 1.0
        assert _entropy([10, 10, 10, 10]) == pytest.approx(1.0, abs=0.01)

    def test_single_value_zero_entropy(self):
        assert _entropy([42]) == 0.0

    def test_empty_zero_entropy(self):
        assert _entropy([]) == 0.0

    def test_zero_sum(self):
        assert _entropy([0, 0, 0]) == 0.0

    def test_skewed_low_entropy(self):
        # One dominates → low entropy
        result = _entropy([100, 1, 1, 1])
        assert 0.0 < result < 0.5

    def test_two_equal(self):
        assert _entropy([5, 5]) == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# _median
# ---------------------------------------------------------------------------

class TestMedian:
    def test_odd(self):
        assert _median([1, 3, 5]) == 3

    def test_even(self):
        assert _median([1, 2, 3, 4]) == 2  # (2+3)//2 = 2

    def test_single(self):
        assert _median([7]) == 7

    def test_empty(self):
        assert _median([]) == 0

    def test_unsorted(self):
        assert _median([5, 1, 3]) == 3

    def test_duplicates(self):
        assert _median([2, 2, 2, 5, 5]) == 2


# ---------------------------------------------------------------------------
# _parse_numstat
# ---------------------------------------------------------------------------

FAKE_NUMSTAT = """\
COMMIT:abc1234
5\t2\tiamai/foo.py
3\t0\ttests/test_foo.py

COMMIT:def5678
10\t8\tiamai/bar.py
2\t1\tiamai/baz.py
1\t0\tREADME.md

COMMIT:ghi9012
1\t0\tnotes/hello.md
"""


class TestParseNumstat:
    def test_parses_three_commits(self, tmp_path: Path):
        with patch("subprocess.check_output", return_value=FAKE_NUMSTAT.encode()):
            result = _parse_numstat(tmp_path, count=3)
        assert len(result) == 3
        assert result[0]["sha"] == "abc1234"
        assert len(result[0]["files"]) == 2
        assert result[1]["sha"] == "def5678"
        assert len(result[1]["files"]) == 3
        assert result[2]["sha"] == "ghi9012"
        assert len(result[2]["files"]) == 1

    def test_empty_on_git_failure(self, tmp_path: Path):
        def fail(*a, **kw):
            raise subprocess.CalledProcessError(128, "git")

        with patch("subprocess.check_output", side_effect=fail):
            result = _parse_numstat(tmp_path)
        assert result == []

    def test_handles_empty_output(self, tmp_path: Path):
        with patch("subprocess.check_output", return_value=b""):
            result = _parse_numstat(tmp_path)
        assert result == []

    def test_handles_binary_files(self, tmp_path: Path):
        data = "COMMIT:aaa1111\n-\t-\tassets/image.png\n"
        with patch("subprocess.check_output", return_value=data.encode()):
            result = _parse_numstat(tmp_path, count=1)
        assert len(result) == 1
        assert result[0]["files"] == ["assets/image.png"]


# ---------------------------------------------------------------------------
# commit_dispersion
# ---------------------------------------------------------------------------

class TestCommitDispersion:
    def test_focused_commits(self, tmp_path: Path):
        """Each commit touches 1-2 files in 1 dir → focused."""
        data = (
            "COMMIT:aaa\n1\t0\tiamai/a.py\n\n"
            "COMMIT:bbb\n2\t0\tiamai/b.py\n\n"
            "COMMIT:ccc\n1\t0\ttests/t.py\n"
        )
        with patch("subprocess.check_output", return_value=data.encode()):
            info = commit_dispersion(tmp_path, count=3)
        assert info["focus"] == "focused"
        assert info["median_files"] == 1
        assert info["commits_inspected"] == 3

    def test_scattered_commits(self, tmp_path: Path):
        """Commits touching many files → scattered."""
        lines = ["COMMIT:big\n"]
        for i in range(15):
            lines.append(f"1\t0\tdir{i}/file.py\n")
        data = "\n".join(lines)
        with patch("subprocess.check_output", return_value=data.encode()):
            info = commit_dispersion(tmp_path, count=1)
        assert info["focus"] == "scattered"
        assert info["max_files"] == 15

    def test_moderate_commits(self, tmp_path: Path):
        """Commits touching 5-7 files → moderate."""
        lines = ["COMMIT:mod\n"]
        for i in range(6):
            lines.append(f"1\t0\tiamai/mod{i}.py\n")
        data = "\n".join(lines)
        with patch("subprocess.check_output", return_value=data.encode()):
            info = commit_dispersion(tmp_path, count=1)
        assert info["focus"] == "moderate"

    def test_no_commits(self, tmp_path: Path):
        with patch("subprocess.check_output", return_value=b""):
            info = commit_dispersion(tmp_path)
        assert info["focus"] == "unknown"
        assert info["commits_inspected"] == 0

    def test_dispersion_range(self, tmp_path: Path):
        data = (
            "COMMIT:a\n1\t0\tiamai/a.py\n\n"
            "COMMIT:b\n5\t0\tiamai/b.py\n\n"
            "COMMIT:c\n2\t0\ttests/c.py\n"
        )
        with patch("subprocess.check_output", return_value=data.encode()):
            info = commit_dispersion(tmp_path, count=3)
        assert 0.0 <= info["dispersion"] <= 1.0

    def test_dirs_per_commit(self, tmp_path: Path):
        data = (
            "COMMIT:multi\n"
            "1\t0\tiamai/a.py\n"
            "1\t0\ttests/test_a.py\n"
            "1\t0\tnotes/hello.md\n"
        )
        with patch("subprocess.check_output", return_value=data.encode()):
            info = commit_dispersion(tmp_path, count=1)
        assert info["dirs_per_commit"] == [3]
        assert info["median_dirs"] == 3


# ---------------------------------------------------------------------------
# dispersion_report
# ---------------------------------------------------------------------------

class TestDispersionReport:
    def test_returns_string(self, tmp_path: Path):
        data = "COMMIT:aaa\n1\t0\tiamai/a.py\n"
        with patch("subprocess.check_output", return_value=data.encode()):
            report = dispersion_report(tmp_path, count=1)
        assert "focused" in report or "moderate" in report or "scattered" in report

    def test_no_commits_message(self, tmp_path: Path):
        with patch("subprocess.check_output", return_value=b""):
            report = dispersion_report(tmp_path)
        assert report == "no commits found"

    def test_includes_count(self, tmp_path: Path):
        data = (
            "COMMIT:a\n1\t0\tiamai/a.py\n\n"
            "COMMIT:b\n2\t0\tiamai/b.py\n"
        )
        with patch("subprocess.check_output", return_value=data.encode()):
            report = dispersion_report(tmp_path, count=2)
        assert "2 commits" in report
