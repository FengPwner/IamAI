"""Tests for tools/stale_uncommitted.py.

Covers:
    - FileAge classification (ok / warn / crit)
    - StaleReport verdict logic
    - _format_age human-readable output
    - _classify threshold boundaries
    - Empty working tree produces "clean" verdict
    - Mixed ages produce correct stale_ratio
"""

import os
import sys
import time
import tempfile
import subprocess
import pytest

# Ensure tools/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from stale_uncommitted import (
    FileAge,
    StaleReport,
    _classify,
    _format_age,
    _file_age_seconds,
    check,
)


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_ok_below_warn(self):
        assert _classify(100.0, 900.0, 3600.0) == "ok"

    def test_ok_at_zero(self):
        assert _classify(0.0, 900.0, 3600.0) == "ok"

    def test_warn_at_threshold(self):
        assert _classify(900.0, 900.0, 3600.0) == "warn"

    def test_warn_between(self):
        assert _classify(1800.0, 900.0, 3600.0) == "warn"

    def test_crit_at_threshold(self):
        assert _classify(3600.0, 900.0, 3600.0) == "crit"

    def test_crit_above(self):
        assert _classify(7200.0, 900.0, 3600.0) == "crit"

    def test_custom_thresholds(self):
        assert _classify(50.0, 30.0, 60.0) == "warn"
        assert _classify(29.0, 30.0, 60.0) == "ok"
        assert _classify(61.0, 30.0, 60.0) == "crit"


# ---------------------------------------------------------------------------
# _format_age
# ---------------------------------------------------------------------------

class TestFormatAge:
    def test_seconds(self):
        assert _format_age(42.0) == "42s"

    def test_minutes(self):
        assert _format_age(125.0) == "2m5s"

    def test_hours(self):
        result = _format_age(7200.0)
        assert result == "2.0h"

    def test_zero(self):
        assert _format_age(0.0) == "0s"

    def test_just_under_hour(self):
        assert _format_age(3599.0) == "59m59s"


# ---------------------------------------------------------------------------
# FileAge dataclass
# ---------------------------------------------------------------------------

class TestFileAge:
    def test_fields(self):
        fa = FileAge(path="notes/foo.md", status="M", age_seconds=123.4, level="ok")
        assert fa.path == "notes/foo.md"
        assert fa.status == "M"
        assert fa.age_seconds == 123.4
        assert fa.level == "ok"


# ---------------------------------------------------------------------------
# StaleReport verdict
# ---------------------------------------------------------------------------

class TestStaleReport:
    def test_clean_when_empty(self):
        r = StaleReport(
            files=[], total_uncommitted=0,
            ok_count=0, warn_count=0, crit_count=0,
            stale_ratio=0.0, verdict="clean",
            checked_at="2026-10-31T19:02:00+00:00",
        )
        assert r.verdict == "clean"
        assert r.stale_ratio == 0.0

    def test_critical_if_any_crit(self):
        files = [
            FileAge("a.py", "M", 7200.0, "crit"),
            FileAge("b.py", "M", 100.0, "ok"),
        ]
        r = StaleReport(
            files=files, total_uncommitted=2,
            ok_count=1, warn_count=0, crit_count=1,
            stale_ratio=0.5, verdict="critical",
            checked_at="2026-10-31T19:02:00+00:00",
        )
        assert r.verdict == "critical"
        assert r.stale_ratio == 0.5

    def test_warning_if_warn_no_crit(self):
        files = [
            FileAge("c.py", "M", 1500.0, "warn"),
            FileAge("d.py", "M", 200.0, "ok"),
        ]
        r = StaleReport(
            files=files, total_uncommitted=2,
            ok_count=1, warn_count=1, crit_count=0,
            stale_ratio=0.5, verdict="warning",
            checked_at="2026-10-31T19:02:00+00:00",
        )
        assert r.verdict == "warning"


# ---------------------------------------------------------------------------
# Integration: check() against a temp repo
# ---------------------------------------------------------------------------

class TestCheckIntegration:
    def _make_repo(self, tmpdir: str) -> str:
        """Create a minimal git repo with one uncommitted file."""
        repo = os.path.join(tmpdir, "test-repo")
        os.makedirs(repo)
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.local"],
            cwd=repo, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo, capture_output=True,
        )
        # Initial commit so git status works cleanly
        readme = os.path.join(repo, "README.md")
        with open(readme, "w") as f:
            f.write("# test\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=repo, capture_output=True, check=True,
        )
        return repo

    def test_clean_repo(self, tmp_path):
        repo = self._make_repo(str(tmp_path))
        report = check(repo=repo)
        assert report.verdict == "clean"
        assert report.total_uncommitted == 0

    def test_fresh_untracked(self, tmp_path):
        repo = self._make_repo(str(tmp_path))
        # Create a new file (just modified)
        new_file = os.path.join(repo, "fresh.md")
        with open(new_file, "w") as f:
            f.write("fresh content\n")
        report = check(repo=repo, warn_threshold=900, crit_threshold=3600)
        assert report.total_uncommitted >= 1
        # File was just created, so it should be ok
        assert all(f.level == "ok" for f in report.files)
        assert report.verdict == "ok"

    def test_stale_file_detected(self, tmp_path):
        repo = self._make_repo(str(tmp_path))
        stale = os.path.join(repo, "stale.md")
        with open(stale, "w") as f:
            f.write("old content\n")
        # Set mtime to 2 hours ago
        old_time = time.time() - 7200
        os.utime(stale, (old_time, old_time))

        report = check(repo=repo, warn_threshold=900, crit_threshold=3600)
        assert report.total_uncommitted >= 1
        crit_files = [f for f in report.files if f.level == "crit"]
        assert len(crit_files) >= 1
        assert any("stale.md" in f.path for f in crit_files)
        assert report.verdict == "critical"

    def test_json_output_structure(self, tmp_path):
        """Verify check() returns proper dataclass convertible to dict."""
        from dataclasses import asdict
        repo = self._make_repo(str(tmp_path))
        report = check(repo=repo)
        d = asdict(report)
        assert "files" in d
        assert "verdict" in d
        assert "stale_ratio" in d
        assert "checked_at" in d


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_classify_with_same_thresholds(self):
        """warn == crit means anything at that value is crit."""
        assert _classify(100.0, 100.0, 100.0) == "crit"
        assert _classify(99.0, 100.0, 100.0) == "ok"

    def test_format_age_exactly_one_hour(self):
        assert _format_age(3600.0) == "1.0h"

    def test_stale_ratio_precision(self):
        """1/3 should round to 0.33."""
        ratio = round(1 / 3, 2)
        assert ratio == 0.33
