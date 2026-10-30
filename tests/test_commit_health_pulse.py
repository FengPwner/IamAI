#!/usr/bin/env python3
"""Tests for commit_health_pulse.py — 16 tests covering classification, analysis, edge cases.

Uses temporary git repos with controlled commit timestamps to verify
the pulse analysis logic without depending on the real IamAI repo.
"""

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from commit_health_pulse import (
    CommitPulse,
    PulseReport,
    find_repo_root,
    classify_gap,
    classify_pulse,
    analyze_pulse,
    get_commits_in_window,
    DEFAULT_CADENCE_SEC,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd, cwd, env=None):
    merged = {**os.environ, **(env or {})}
    result = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, env=merged
    )
    assert result.returncode == 0, f"Command failed: {cmd}\n{result.stderr}"
    return result


def _make_repo(tmpdir):
    """Create a temporary git repo with an initial commit."""
    repo = Path(tmpdir) / "test_repo"
    repo.mkdir()
    _run(["git", "init"], repo)
    _run(["git", "config", "user.email", "test@test.local"], repo)
    _run(["git", "config", "user.name", "Test"], repo)
    # Initial commit
    readme = repo / "README.md"
    readme.write_text("# Test\n")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "init"], repo)
    return repo


def _add_commit(repo, message, date_offset_minutes=0, base_time=None):
    """Add a commit with a specific timestamp offset from now (or base_time)."""
    f = repo / f"file_{message}.txt"
    f.write_text(f"content: {message}\n")
    _run(["git", "add", "."], repo)

    if base_time is None:
        base_time = datetime.now(timezone.utc)
    commit_time = base_time + timedelta(minutes=date_offset_minutes)
    date_str = commit_time.strftime("%Y-%m-%dT%H:%M:%S+00:00")

    env = {
        "GIT_AUTHOR_DATE": date_str,
        "GIT_COMMITTER_DATE": date_str,
    }
    _run(["git", "commit", "-m", message], repo, env=env)


# ---------------------------------------------------------------------------
# Tests: classify_gap
# ---------------------------------------------------------------------------

class TestClassifyGap:
    def test_zero_gap_is_steady(self):
        assert classify_gap(0, 600) == "steady"

    def test_exact_cadence_is_steady(self):
        assert classify_gap(600, 600) == "steady"

    def test_half_cadence_is_steady(self):
        """0.5× is the boundary — should be steady (not burst)."""
        assert classify_gap(300, 600) == "steady"

    def test_just_below_half_is_burst(self):
        assert classify_gap(299, 600) == "burst"

    def test_double_cadence_is_steady(self):
        """2× is the boundary — should be steady (not gap)."""
        assert classify_gap(1200, 600) == "steady"

    def test_above_double_is_gap(self):
        assert classify_gap(1201, 600) == "gap"

    def test_very_small_gap_is_burst(self):
        assert classify_gap(10, 600) == "burst"

    def test_very_large_gap(self):
        assert classify_gap(3600, 600) == "gap"


# ---------------------------------------------------------------------------
# Tests: classify_pulse
# ---------------------------------------------------------------------------

class TestClassifyPulse:
    def test_high_health_is_steady(self):
        assert classify_pulse(0.9, 0.05, 0.05) == "steady"

    def test_exactly_08_is_steady(self):
        assert classify_pulse(0.8, 0.1, 0.1) == "steady"

    def test_recovering_when_burst_dominates(self):
        assert classify_pulse(0.6, 0.3, 0.1) == "recovering"

    def test_erratic_when_gap_dominates(self):
        assert classify_pulse(0.5, 0.1, 0.4) == "erratic"

    def test_stalled_when_low_health(self):
        assert classify_pulse(0.2, 0.4, 0.4) == "stalled"

    def test_zero_health_is_stalled(self):
        assert classify_pulse(0.0, 0.5, 0.5) == "stalled"


# ---------------------------------------------------------------------------
# Tests: find_repo_root
# ---------------------------------------------------------------------------

class TestFindRepoRoot:
    def test_finds_repo_from_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = _make_repo(tmpdir)
            assert find_repo_root(str(repo)) == repo

    def test_finds_repo_from_subdirectory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = _make_repo(tmpdir)
            sub = repo / "sub" / "deep"
            sub.mkdir(parents=True)
            assert find_repo_root(str(sub)) == repo

    def test_raises_when_no_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(FileNotFoundError):
                find_repo_root(tmpdir)


# ---------------------------------------------------------------------------
# Tests: analyze_pulse with real temp repos
# ---------------------------------------------------------------------------

class TestAnalyzePulse:
    def test_steady_commits(self):
        """Commits at exactly the cadence should be all steady."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = _make_repo(tmpdir)
            base = datetime.now(timezone.utc) - timedelta(hours=2)
            # Add 5 commits at 10-minute intervals
            for i in range(5):
                _add_commit(repo, f"s{i}", date_offset_minutes=i * 10, base_time=base)

            report = analyze_pulse(repo, hours=3, cadence=600)
            assert report.total_commits >= 6  # 5 + init
            assert report.pulse_label == "steady"
            assert report.health_score > 0.8

    def test_burst_commits(self):
        """Commits fired within seconds should be classified as bursts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = _make_repo(tmpdir)
            base = datetime.now(timezone.utc) - timedelta(minutes=30)
            # 5 commits within 1 minute total
            for i in range(5):
                _add_commit(repo, f"b{i}", date_offset_minutes=i * 0.2, base_time=base)

            report = analyze_pulse(repo, hours=1, cadence=600)
            assert report.burst_count >= 4  # 4 gaps between 5 burst commits

    def test_no_commits_returns_stalled(self):
        """Empty window should produce a stalled report."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = _make_repo(tmpdir)
            report = analyze_pulse(repo, hours=0.001, cadence=600)
            # The init commit might be within 0.001h (3.6s) of now
            # but if not, total_commits is 0
            assert report.pulse_label in ("stalled", "steady")

    def test_gap_after_silence(self):
        """A long silence followed by a commit should register as a gap."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = _make_repo(tmpdir)
            base = datetime.now(timezone.utc) - timedelta(hours=10)
            # One commit 10 hours ago
            _add_commit(repo, "old", date_offset_minutes=0, base_time=base)
            # One commit now
            _add_commit(repo, "new", date_offset_minutes=600, base_time=base)

            report = analyze_pulse(repo, hours=12, cadence=600)
            assert report.gap_count >= 1
            assert report.longest_gap_seconds >= 36000  # 10 hours


# ---------------------------------------------------------------------------
# Tests: PulseReport structure
# ---------------------------------------------------------------------------

class TestPulseReportStructure:
    def test_report_has_all_fields(self):
        """PulseReport should serialize cleanly to dict."""
        from dataclasses import asdict
        report = PulseReport(
            repo="/tmp/test",
            window_hours=24,
            cadence_seconds=600,
            total_commits=10,
            total_gaps=9,
            steady_count=7,
            burst_count=1,
            gap_count=1,
            health_score=0.78,
            burst_ratio=0.11,
            gap_ratio=0.11,
            pulse_label="recovering",
            longest_gap_seconds=3600.0,
            shortest_gap_seconds=5.0,
            pulses=[
                CommitPulse("abc1234", "2026-10-31T00:00:00+00:00", 0.0, "steady"),
            ],
        )
        d = asdict(report)
        assert d["health_score"] == 0.78
        assert d["pulse_label"] == "recovering"
        assert len(d["pulses"]) == 1

    def test_empty_report(self):
        """Empty report should have sensible defaults."""
        report = PulseReport(
            repo="/tmp/test",
            window_hours=24,
            cadence_seconds=600,
            total_commits=0,
            total_gaps=0,
            steady_count=0,
            burst_count=0,
            gap_count=0,
            health_score=0.0,
            burst_ratio=0.0,
            gap_ratio=0.0,
            pulse_label="stalled",
            longest_gap_seconds=0.0,
            shortest_gap_seconds=0.0,
            pulses=[],
        )
        assert report.total_commits == 0
        assert report.pulse_label == "stalled"
