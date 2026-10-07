"""Tests for iamai.repo_pulse."""

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.repo_pulse import (
    _classify_commit,
    _classify_git,
    _git_pending,
    _last_commit_age,
    pulse,
    pulse_report,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path, strokes: list[dict] | None = None) -> Path:
    """Create a fake repo with data/strokes.jsonl and a git init."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    if strokes is not None:
        with open(data_dir / "strokes.jsonl", "w", encoding="utf-8") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")
    # init git
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init", "--allow-empty"], cwd=tmp_path, capture_output=True)
    return tmp_path


def _stroke(seconds_ago: float, kind: str = "thought") -> dict:
    ts = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return {"seq": 1, "at": ts.isoformat(), "kind": kind, "text": "test"}


# ---------------------------------------------------------------------------
# _classify_git
# ---------------------------------------------------------------------------

class TestClassifyGit:
    def test_clean(self):
        assert _classify_git(0) == "clean"
        assert _classify_git(2) == "clean"

    def test_dirty(self):
        assert _classify_git(5) == "dirty"

    def test_backlog(self):
        assert _classify_git(10) == "backlog"

    def test_unknown(self):
        assert _classify_git(-1) == "unknown"

    def test_boundary_warn(self):
        assert _classify_git(3) == "clean"  # PENDING_WARN inclusive
        assert _classify_git(4) == "dirty"

    def test_boundary_bad(self):
        # _PENDING_BAD = 8, so 8 <= 8 → "dirty"
        assert _classify_git(8) == "dirty"
        assert _classify_git(9) == "backlog"


# ---------------------------------------------------------------------------
# _classify_commit
# ---------------------------------------------------------------------------

class TestClassifyCommit:
    def test_recent(self):
        assert _classify_commit(60) == "recent"
        assert _classify_commit(0) == "recent"

    def test_aging(self):
        assert _classify_commit(3600) == "aging"

    def test_stale(self):
        assert _classify_commit(10000) == "stale"

    def test_none(self):
        assert _classify_commit(float("inf")) == "none"

    def test_boundary_warn(self):
        assert _classify_commit(1800) == "aging"  # exactly at threshold

    def test_boundary_bad(self):
        assert _classify_commit(7200) == "stale"  # exactly at threshold


# ---------------------------------------------------------------------------
# _git_pending
# ---------------------------------------------------------------------------

class TestGitPending:
    def test_clean_repo(self, tmp_path):
        repo = _make_repo(tmp_path)
        assert _git_pending(repo) == 0

    def test_dirty_repo(self, tmp_path):
        repo = _make_repo(tmp_path)
        (repo / "new_file.txt").write_text("hello")
        assert _git_pending(repo) == 1

    def test_not_a_repo(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert _git_pending(empty) == -1


# ---------------------------------------------------------------------------
# _last_commit_age
# ---------------------------------------------------------------------------

class TestLastCommitAge:
    def test_recent_commit(self, tmp_path):
        repo = _make_repo(tmp_path)
        now = datetime.now(timezone.utc)
        age = _last_commit_age(repo, now)
        # commit was just made, age should be very small
        assert age < 30

    def test_not_a_repo(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        now = datetime.now(timezone.utc)
        assert _last_commit_age(empty, now) == float("inf")


# ---------------------------------------------------------------------------
# pulse (composite)
# ---------------------------------------------------------------------------

class TestPulse:
    def test_healthy_repo(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[_stroke(10)])
        now = datetime.now(timezone.utc)
        info = pulse(repo, cadence_seconds=15, now=now)
        assert info["verdict"] == "alive"
        assert info["score"] >= 2.5
        assert info["signals"]["freshness"] == "fresh"

    def test_no_strokes_file(self, tmp_path):
        repo = _make_repo(tmp_path)
        now = datetime.now(timezone.utc)
        info = pulse(repo, cadence_seconds=15, now=now)
        # no strokes → freshness is "dead", but git is clean and commit recent
        assert info["signals"]["freshness"] == "dead"
        assert info["verdict"] in ("limping", "stalled")

    def test_dirty_tree_degrades(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[_stroke(10)])
        # create 10 untracked files to push past PENDING_BAD
        for i in range(10):
            (repo / f"file_{i}.txt").write_text(f"content {i}")
        now = datetime.now(timezone.utc)
        info = pulse(repo, cadence_seconds=15, now=now)
        assert info["signals"]["git"] == "backlog"

    def test_stale_strokes_degrade(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[_stroke(600)])  # 10 min ago
        now = datetime.now(timezone.utc)
        info = pulse(repo, cadence_seconds=15, now=now)
        assert info["signals"]["freshness"] in ("stale", "dead")

    def test_custom_cadence(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[_stroke(120)])
        now = datetime.now(timezone.utc)
        # with default cadence (15s), 120s ago = stale
        info_default = pulse(repo, cadence_seconds=15, now=now)
        assert info_default["signals"]["freshness"] == "stale"
        # with cadence=120s, 120s ago = fresh (< 2× = 240s)
        info_wide = pulse(repo, cadence_seconds=120, now=now)
        assert info_wide["signals"]["freshness"] == "fresh"

    def test_score_range(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[_stroke(10)])
        now = datetime.now(timezone.utc)
        info = pulse(repo, now=now)
        assert 0 <= info["score"] <= 3

    def test_details_populated(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[_stroke(10)])
        now = datetime.now(timezone.utc)
        info = pulse(repo, now=now)
        assert "pending_files" in info["details"]
        assert "commit_age_seconds" in info["details"]
        assert "stroke_age_seconds" in info["details"]
        assert "cadence_seconds" in info["details"]


# ---------------------------------------------------------------------------
# pulse_report
# ---------------------------------------------------------------------------

class TestPulseReport:
    def test_healthy_report(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[_stroke(10)])
        now = datetime.now(timezone.utc)
        report = pulse_report(repo, cadence_seconds=15, now=now)
        assert "alive" in report
        assert "fresh strokes" in report
        assert "clean tree" in report

    def test_report_format(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[_stroke(10)])
        now = datetime.now(timezone.utc)
        report = pulse_report(repo, now=now)
        # should have verdict — signal1, signal2, signal3
        assert " — " in report
        assert ", " in report

    def test_no_strokes_report(self, tmp_path):
        repo = _make_repo(tmp_path)
        now = datetime.now(timezone.utc)
        report = pulse_report(repo, now=now)
        assert "no strokes" in report
