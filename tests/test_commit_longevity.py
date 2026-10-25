"""Tests for iamai.commit_longevity — file change durability measurement.

Covers:
  - empty / no-commits edge case
  - single-commit edge case (no longevity measurable)
  - basic lifetime calculation (first-seen to last-seen)
  - median and max longevity correctness
  - churn file detection (>50% commit appearance)
  - verdict thresholds at boundary values
  - longevity_report formatting
  - file that appears once (excluded from lifetimes)
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from iamai.commit_longevity import (
    commit_longevity,
    longevity_report,
    _parse_log,
    DURABLE_THRESHOLD,
    TRANSIENT_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_repo(tmp: Path) -> None:
    """Create a fresh git repo with an initial commit."""
    subprocess.run(["git", "init"], cwd=tmp, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        cwd=tmp, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp, check=True, capture_output=True,
    )
    (tmp / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=tmp, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp, check=True, capture_output=True,
    )


def _commit(tmp: Path, filename: str, content: str, message: str,
            epoch: int | None = None) -> None:
    """Write a file and commit it, optionally with a fake timestamp."""
    (tmp / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=tmp, check=True, capture_output=True)
    env = {}
    if epoch is not None:
        env = {
            "GIT_AUTHOR_DATE": f"{epoch} +0000",
            "GIT_COMMITTER_DATE": f"{epoch} +0000",
        }
    import os
    merged = {**os.environ, **env}
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=tmp, check=True, capture_output=True,
        env=merged,
    )


# ---------------------------------------------------------------------------
# Tests: _parse_log
# ---------------------------------------------------------------------------

class TestParseLog:
    def test_parses_commits_and_files(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _commit(tmp_path, "a.py", "v1", "add a")
        _commit(tmp_path, "b.py", "v1", "add b")
        commits = _parse_log(tmp_path, count=10)
        assert len(commits) >= 2  # at least init + a + b
        # Newest first
        assert commits[0]["sha"] != ""
        assert commits[0]["timestamp"] > 0

    def test_returns_empty_on_non_repo(self, tmp_path: Path) -> None:
        commits = _parse_log(tmp_path, count=10)
        assert commits == []


# ---------------------------------------------------------------------------
# Tests: commit_longevity
# ---------------------------------------------------------------------------

class TestCommitLongevity:
    def test_no_commits_returns_churning(self, tmp_path: Path) -> None:
        result = commit_longevity(tmp_path, count=10)
        assert result["verdict"] == "churning"
        assert result["median_longevity_s"] == 0

    def test_single_file_appears_once_excluded(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _commit(tmp_path, "once.py", "v1", "only once")
        result = commit_longevity(tmp_path, count=10)
        # "once.py" appears in exactly 1 commit → excluded from lifetimes
        assert "once.py" not in result["file_lifetimes"]

    def test_basic_lifetime(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        base = 1700000000
        _commit(tmp_path, "a.py", "v1", "first", epoch=base)
        _commit(tmp_path, "b.py", "v1", "second", epoch=base + 600)
        _commit(tmp_path, "a.py", "v2", "rewrite a", epoch=base + 1800)
        result = commit_longevity(tmp_path, count=10)
        # a.py: first at base, last at base+1800 → 1800s
        assert "a.py" in result["file_lifetimes"]
        assert result["file_lifetimes"]["a.py"] == 1800

    def test_median_and_max(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        base = 1700000000
        _commit(tmp_path, "a.py", "v1", "c1", epoch=base)
        _commit(tmp_path, "b.py", "v1", "c2", epoch=base + 300)
        _commit(tmp_path, "a.py", "v2", "c3", epoch=base + 1200)
        _commit(tmp_path, "b.py", "v2", "c4", epoch=base + 3600)
        result = commit_longevity(tmp_path, count=10)
        # a.py: 1200s, b.py: 3300s → median ~2250, max 3300
        assert result["max_longevity_s"] == 3300
        assert result["median_longevity_s"] == 2250

    def test_churn_files_detected(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        base = 1700000000
        # a.py appears in 4 of 5 commits (80%) → churn
        for i in range(5):
            _commit(tmp_path, "a.py", f"v{i}", f"rewrite a {i}",
                    epoch=base + i * 60)
        # b.py appears in 1 of 5 → not churn
        _commit(tmp_path, "b.py", "v1", "add b", epoch=base + 300)
        result = commit_longevity(tmp_path, count=10)
        assert "a.py" in result["churn_files"]
        assert "b.py" not in result["churn_files"]


# ---------------------------------------------------------------------------
# Tests: verdict classification
# ---------------------------------------------------------------------------

class TestVerdict:
    def test_durable_when_median_above_threshold(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        base = 1700000000
        _commit(tmp_path, "a.py", "v1", "c1", epoch=base)
        _commit(tmp_path, "b.py", "v1", "c2", epoch=base + 100)
        # Both rewritten after 7200s (> DURABLE_THRESHOLD=3600)
        _commit(tmp_path, "a.py", "v2", "c3", epoch=base + 7200)
        _commit(tmp_path, "b.py", "v2", "c4", epoch=base + 7300)
        result = commit_longevity(tmp_path, count=10)
        assert result["verdict"] == "durable"

    def test_transient_between_thresholds(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        base = 1700000000
        _commit(tmp_path, "a.py", "v1", "c1", epoch=base)
        _commit(tmp_path, "b.py", "v1", "c2", epoch=base + 100)
        # Both rewritten after 1800s (between TRANSIENT=600 and DURABLE=3600)
        _commit(tmp_path, "a.py", "v2", "c3", epoch=base + 1800)
        _commit(tmp_path, "b.py", "v2", "c4", epoch=base + 1900)
        result = commit_longevity(tmp_path, count=10)
        assert result["verdict"] == "transient"

    def test_churning_when_below_transient(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        base = 1700000000
        _commit(tmp_path, "a.py", "v1", "c1", epoch=base)
        _commit(tmp_path, "b.py", "v1", "c2", epoch=base + 10)
        # Both rewritten after 120s (< TRANSIENT_THRESHOLD=600)
        _commit(tmp_path, "a.py", "v2", "c3", epoch=base + 120)
        _commit(tmp_path, "b.py", "v2", "c4", epoch=base + 130)
        result = commit_longevity(tmp_path, count=10)
        assert result["verdict"] == "churning"


# ---------------------------------------------------------------------------
# Tests: longevity_report
# ---------------------------------------------------------------------------

class TestLongevityReport:
    def test_report_format_durable(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        base = 1700000000
        _commit(tmp_path, "a.py", "v1", "c1", epoch=base)
        _commit(tmp_path, "a.py", "v2", "c2", epoch=base + 7200)
        _commit(tmp_path, "b.py", "v1", "c3", epoch=base + 100)
        _commit(tmp_path, "b.py", "v2", "c4", epoch=base + 7300)
        report = longevity_report(tmp_path, count=10)
        assert "durable" in report
        assert "commits" in report

    def test_report_format_churning(self, tmp_path: Path) -> None:
        report = longevity_report(tmp_path, count=10)
        assert "churning" in report

    def test_report_includes_churn_count(self, tmp_path: Path) -> None:
        report = longevity_report(tmp_path, count=10)
        # Should contain "0 churning files" for an empty/nonexistent repo
        assert "churning file" in report


# ---------------------------------------------------------------------------
# Tests: boundary and edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_count_larger_than_history(self, tmp_path: Path) -> None:
        """Requesting more commits than exist should not crash."""
        _init_repo(tmp_path)
        result = commit_longevity(tmp_path, count=9999)
        assert result["commits"] >= 1  # at least init

    def test_file_modified_in_every_commit(self, tmp_path: Path) -> None:
        """A file touched in all commits has longevity = full window span."""
        _init_repo(tmp_path)
        base = 1700000000
        for i in range(6):
            _commit(tmp_path, "always.py", f"v{i}", f"edit {i}",
                    epoch=base + i * 300)
        result = commit_longevity(tmp_path, count=10)
        # always.py: first at base, last at base+1500 → 1500s
        assert result["file_lifetimes"]["always.py"] == 1500
        # Appears in 6 commits out of 7 (6 + init) → 85.7% → churn
        assert "always.py" in result["churn_files"]

    def test_multiple_files_mixed_longevity(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        base = 1700000000
        # Short-lived file (300s)
        _commit(tmp_path, "short.py", "v1", "c1", epoch=base)
        _commit(tmp_path, "short.py", "v2", "c2", epoch=base + 300)
        # Long-lived file (5000s)
        _commit(tmp_path, "long.py", "v1", "c3", epoch=base + 100)
        _commit(tmp_path, "long.py", "v2", "c4", epoch=base + 5100)
        result = commit_longevity(tmp_path, count=10)
        assert result["file_lifetimes"]["short.py"] == 300
        assert result["file_lifetimes"]["long.py"] == 5000
        assert result["max_longevity_s"] == 5000
        # median of [300, 5000] = 2650
        assert result["median_longevity_s"] == 2650
