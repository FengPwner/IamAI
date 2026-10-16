"""Tests for iamai.caretaker_patience — patience budget for caretaker escalation.

These tests verify:
- patience_budget returns correct structure and types
- Reliability calculation from visit/stall ratios
- Patience budget clamping and boundary conditions
- Edge cases: no visits, all stalls, perfect reliability
- patience_report produces human-readable output
"""

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from iamai.caretaker_patience import (
    DEFAULT_MAX_BUDGET,
    DEFAULT_WINDOW_HOURS,
    _count_visits_in_window,
    _parse_strokes_since,
    patience_budget,
    patience_report,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_repo(tmp_path):
    """Create a minimal repo structure."""
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    # Initialize a git repo so subprocess calls don't crash.
    subprocess.run(
        ["git", "init"],
        cwd=str(tmp_path),
        capture_output=True,
        timeout=10,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        cwd=str(tmp_path),
        capture_output=True,
        timeout=10,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path),
        capture_output=True,
        timeout=10,
    )
    return tmp_path


@pytest.fixture
def live_repo():
    """The actual IamAI repository."""
    return REPO_ROOT


# ---------------------------------------------------------------------------
# _count_visits_in_window
# ---------------------------------------------------------------------------


class TestCountVisitsInWindow:
    def test_no_commits_returns_zero(self, fake_repo):
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _count_visits_in_window(fake_repo, since)
        assert result["visits"] == 0
        assert result["stalls"] == 0

    def test_counts_regular_commits(self, fake_repo):
        # Make a few commits.
        (fake_repo / "test.txt").write_text("hello\n")
        subprocess.run(["git", "add", "."], cwd=str(fake_repo), capture_output=True, timeout=10)
        subprocess.run(
            ["git", "commit", "-m", "regular commit"],
            cwd=str(fake_repo),
            capture_output=True,
            timeout=10,
        )
        (fake_repo / "test2.txt").write_text("world\n")
        subprocess.run(["git", "add", "."], cwd=str(fake_repo), capture_output=True, timeout=10)
        subprocess.run(
            ["git", "commit", "-m", "stall recovery fix"],
            cwd=str(fake_repo),
            capture_output=True,
            timeout=10,
        )
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _count_visits_in_window(fake_repo, since)
        assert result["visits"] == 2
        assert result["stalls"] == 1  # "stall" in commit message

    def test_empty_repo(self, tmp_path):
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _count_visits_in_window(tmp_path, since)
        assert result["visits"] == 0


# ---------------------------------------------------------------------------
# _parse_strokes_since
# ---------------------------------------------------------------------------


class TestParseStrokesSince:
    def test_no_strokes_file(self, tmp_path):
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        assert _parse_strokes_since(tmp_path, since) == 0

    def test_counts_recent_strokes(self, fake_repo):
        now = datetime.now(timezone.utc)
        strokes = [
            {"seq": 1, "at": (now - timedelta(minutes=30)).isoformat(), "kind": "note"},
            {"seq": 2, "at": (now - timedelta(minutes=15)).isoformat(), "kind": "devlog"},
            {"seq": 3, "at": (now - timedelta(hours=2)).isoformat(), "kind": "thought"},
        ]
        strokes_path = fake_repo / "data" / "strokes.jsonl"
        with open(strokes_path, "w") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")

        since = now - timedelta(hours=1)
        count = _parse_strokes_since(fake_repo, since)
        assert count == 2  # Only the first two are within the window

    def test_malformed_lines_skipped(self, fake_repo):
        strokes_path = fake_repo / "data" / "strokes.jsonl"
        now = datetime.now(timezone.utc)
        with open(strokes_path, "w") as f:
            f.write("not json\n")
            f.write(json.dumps({"seq": 1, "at": now.isoformat(), "kind": "note"}) + "\n")
            f.write("\n")

        since = now - timedelta(hours=1)
        count = _parse_strokes_since(fake_repo, since)
        assert count == 1


# ---------------------------------------------------------------------------
# patience_budget
# ---------------------------------------------------------------------------


class TestPatienceBudget:
    def test_returns_correct_keys(self, fake_repo):
        info = patience_budget(repo_root=fake_repo)
        expected_keys = {
            "budget", "reliability", "visits", "stalls",
            "healthy_visits", "max_budget", "window_hours",
        }
        assert set(info.keys()) == expected_keys

    def test_budget_within_max(self, fake_repo):
        info = patience_budget(repo_root=fake_repo, max_budget=6)
        assert 0 <= info["budget"] <= 6

    def test_default_parameters(self, fake_repo):
        info = patience_budget(repo_root=fake_repo)
        assert info["max_budget"] == DEFAULT_MAX_BUDGET
        assert info["window_hours"] == DEFAULT_WINDOW_HOURS

    def test_no_visits_gives_full_reliability(self, fake_repo):
        """With no commits in the window, reliability defaults to 1.0."""
        info = patience_budget(repo_root=fake_repo, window_hours=0.001)
        assert info["reliability"] == 1.0
        assert info["budget"] == DEFAULT_MAX_BUDGET

    def test_all_stalls_gives_zero_budget(self, fake_repo):
        """If every visit is a stall, patience should be 0."""
        # Make commits that all contain "stall".
        for i in range(3):
            (fake_repo / f"file{i}.txt").write_text(f"content {i}\n")
            subprocess.run(["git", "add", "."], cwd=str(fake_repo), capture_output=True, timeout=10)
            subprocess.run(
                ["git", "commit", "-m", f"stall recovery #{i}"],
                cwd=str(fake_repo),
                capture_output=True,
                timeout=10,
            )
        info = patience_budget(repo_root=fake_repo, window_hours=1)
        assert info["reliability"] == 0.0
        assert info["budget"] == 0

    def test_perfect_reliability(self, fake_repo):
        """All visits healthy → full budget."""
        for i in range(5):
            (fake_repo / f"ok{i}.txt").write_text(f"ok {i}\n")
            subprocess.run(["git", "add", "."], cwd=str(fake_repo), capture_output=True, timeout=10)
            subprocess.run(
                ["git", "commit", "-m", f"healthy visit {i}"],
                cwd=str(fake_repo),
                capture_output=True,
                timeout=10,
            )
        info = patience_budget(repo_root=fake_repo, window_hours=1)
        assert info["reliability"] == 1.0
        assert info["budget"] == DEFAULT_MAX_BUDGET

    def test_partial_reliability(self, fake_repo):
        """Mix of healthy and stall visits → proportional budget."""
        # 2 healthy + 1 stall = 0.667 reliability → budget = floor(0.667*6) = 4
        commits = [
            ("healthy visit A", "partial_a.txt"),
            ("healthy visit B", "partial_b.txt"),
            ("stall recovery", "partial_c.txt"),
        ]
        for msg, fname in commits:
            (fake_repo / fname).write_text(msg + "\n")
            subprocess.run(["git", "add", "."], cwd=str(fake_repo), capture_output=True, timeout=10)
            subprocess.run(
                ["git", "commit", "-m", msg],
                cwd=str(fake_repo),
                capture_output=True,
                timeout=10,
            )
        info = patience_budget(repo_root=fake_repo, window_hours=1)
        assert info["visits"] == 3
        assert info["stalls"] == 1
        assert info["healthy_visits"] == 2
        assert info["reliability"] == pytest.approx(2 / 3, abs=0.01)
        assert info["budget"] == 4  # floor(0.667 * 6)


# ---------------------------------------------------------------------------
# patience_report
# ---------------------------------------------------------------------------


class TestPatienceReport:
    def test_returns_string(self, fake_repo):
        report = patience_report(repo_root=fake_repo)
        assert isinstance(report, str)

    def test_contains_patience_prefix(self, fake_repo):
        report = patience_report(repo_root=fake_repo)
        assert report.startswith("patience ")

    def test_contains_reliability(self, fake_repo):
        report = patience_report(repo_root=fake_repo, window_hours=1)
        assert "reliability" in report

    def test_live_repo_does_not_crash(self, live_repo):
        """Integration test: running against the real repo should work."""
        report = patience_report(repo_root=live_repo)
        assert "patience" in report
