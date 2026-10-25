#!/usr/bin/env python3
"""Tests for iamai/repo_heartbeat.py — composite repo liveness check."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.repo_heartbeat import (
    HeartbeatReport,
    HeartbeatVerdict,
    SignalResult,
    assess,
    check_commit_freshness,
    check_process_liveness,
    check_stroke_freshness,
)


# ---------------------------------------------------------------------------
# check_commit_freshness
# ---------------------------------------------------------------------------


class TestCheckCommitFreshness:
    def test_ok_when_commit_is_recent(self, tmp_path: Path) -> None:
        # Pretend the repo root has a git log that returns a time 60s ago.
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(seconds=60)).isoformat()
        with patch("subprocess.check_output", return_value=recent + "\n"):
            result = check_commit_freshness(tmp_path, max_gap=120)
        assert result.ok is True
        assert result.name == "commit_freshness"
        assert result.age_seconds is not None
        assert result.age_seconds < 120

    def test_fail_when_commit_is_old(self, tmp_path: Path) -> None:
        now = datetime.now(timezone.utc)
        old = (now - timedelta(seconds=3600)).isoformat()
        with patch("subprocess.check_output", return_value=old + "\n"):
            result = check_commit_freshness(tmp_path, max_gap=120)
        assert result.ok is False
        assert result.age_seconds is not None
        assert result.age_seconds > 120

    def test_fail_on_git_error(self, tmp_path: Path) -> None:
        import subprocess

        with patch(
            "subprocess.check_output",
            side_effect=subprocess.CalledProcessError(1, "git"),
        ):
            result = check_commit_freshness(tmp_path)
        assert result.ok is False
        assert "could not read" in result.detail


# ---------------------------------------------------------------------------
# check_stroke_freshness
# ---------------------------------------------------------------------------


class TestCheckStrokeFreshness:
    def test_ok_when_stroke_is_recent(self, tmp_path: Path) -> None:
        now = datetime.now(timezone.utc)
        recent_at = (now - timedelta(seconds=30)).isoformat()
        strokes = tmp_path / "data"
        strokes.mkdir()
        (strokes / "strokes.jsonl").write_text(
            json.dumps({"seq": 1, "at": recent_at, "kind": "note", "text": "hi"}) + "\n",
            encoding="utf-8",
        )
        result = check_stroke_freshness(tmp_path, max_gap=120)
        assert result.ok is True
        assert result.age_seconds is not None
        assert result.age_seconds < 120

    def test_fail_when_stroke_is_old(self, tmp_path: Path) -> None:
        now = datetime.now(timezone.utc)
        old_at = (now - timedelta(seconds=900)).isoformat()
        strokes = tmp_path / "data"
        strokes.mkdir()
        (strokes / "strokes.jsonl").write_text(
            json.dumps({"seq": 1, "at": old_at, "kind": "note", "text": "stale"}) + "\n",
            encoding="utf-8",
        )
        result = check_stroke_freshness(tmp_path, max_gap=120)
        assert result.ok is False

    def test_fail_when_file_missing(self, tmp_path: Path) -> None:
        result = check_stroke_freshness(tmp_path)
        assert result.ok is False
        assert "missing" in result.detail

    def test_fail_when_file_empty(self, tmp_path: Path) -> None:
        strokes = tmp_path / "data"
        strokes.mkdir()
        (strokes / "strokes.jsonl").write_text("", encoding="utf-8")
        result = check_stroke_freshness(tmp_path)
        assert result.ok is False
        assert "empty" in result.detail

    def test_reads_last_line_only(self, tmp_path: Path) -> None:
        now = datetime.now(timezone.utc)
        old_at = (now - timedelta(seconds=9999)).isoformat()
        recent_at = (now - timedelta(seconds=10)).isoformat()
        strokes = tmp_path / "data"
        strokes.mkdir()
        lines = (
            json.dumps({"seq": 1, "at": old_at, "kind": "note", "text": "old"})
            + "\n"
            + json.dumps({"seq": 2, "at": recent_at, "kind": "note", "text": "new"})
            + "\n"
        )
        (strokes / "strokes.jsonl").write_text(lines, encoding="utf-8")
        result = check_stroke_freshness(tmp_path, max_gap=120)
        assert result.ok is True


# ---------------------------------------------------------------------------
# check_process_liveness
# ---------------------------------------------------------------------------


class TestCheckProcessLiveness:
    def test_ok_when_both_alive(self, tmp_path: Path) -> None:
        # Create fake PID files with our own PID (which is obviously alive).
        my_pid = str(os.getpid())
        (tmp_path / "iamai-writer-qwen.pid").write_text(my_pid, encoding="utf-8")
        (tmp_path / "iamai-batch-qwen.pid").write_text(my_pid, encoding="utf-8")
        result = check_process_liveness(
            Path("."), pid_dir=str(tmp_path), writer_name="qwen"
        )
        assert result.ok is True
        assert "2/2" in result.detail

    def test_fail_when_one_stale(self, tmp_path: Path) -> None:
        my_pid = str(os.getpid())
        (tmp_path / "iamai-writer-qwen.pid").write_text(my_pid, encoding="utf-8")
        # Use a PID that almost certainly doesn't exist.
        (tmp_path / "iamai-batch-qwen.pid").write_text("999999999", encoding="utf-8")
        result = check_process_liveness(
            Path("."), pid_dir=str(tmp_path), writer_name="qwen"
        )
        assert result.ok is False
        assert "1/2" in result.detail

    def test_fail_when_no_pid_files(self, tmp_path: Path) -> None:
        result = check_process_liveness(
            Path("."), pid_dir=str(tmp_path), writer_name="qwen"
        )
        assert result.ok is False
        assert "0/2" in result.detail

    def test_handles_corrupt_pid_file(self, tmp_path: Path) -> None:
        (tmp_path / "iamai-writer-qwen.pid").write_text("not-a-number", encoding="utf-8")
        (tmp_path / "iamai-batch-qwen.pid").write_text("999999999", encoding="utf-8")
        result = check_process_liveness(
            Path("."), pid_dir=str(tmp_path), writer_name="qwen"
        )
        assert result.ok is False


# ---------------------------------------------------------------------------
# assess (aggregate)
# ---------------------------------------------------------------------------


class TestAssess:
    def test_healthy_when_all_pass(self, tmp_path: Path) -> None:
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(seconds=60)).isoformat()
        # Set up strokes file.
        data = tmp_path / "data"
        data.mkdir()
        (data / "strokes.jsonl").write_text(
            json.dumps({"seq": 1, "at": recent, "kind": "note", "text": "ok"}) + "\n",
            encoding="utf-8",
        )
        # Set up PID files with a live PID.
        my_pid = str(os.getpid())
        (tmp_path / "iamai-writer-qwen.pid").write_text(my_pid, encoding="utf-8")
        (tmp_path / "iamai-batch-qwen.pid").write_text(my_pid, encoding="utf-8")
        # Initialise a bare git repo with one recent commit.
        _init_git_repo(tmp_path, commit_age_seconds=30)

        report = assess(
            repo_root=tmp_path,
            max_commit_gap=1200,
            max_stroke_gap=600,
            pid_dir=str(tmp_path),
        )
        assert report.verdict == HeartbeatVerdict.HEALTHY
        assert len(report.signals) == 3
        assert all(s.ok for s in report.signals)

    def test_degraded_when_one_fails(self, tmp_path: Path) -> None:
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(seconds=60)).isoformat()
        data = tmp_path / "data"
        data.mkdir()
        (data / "strokes.jsonl").write_text(
            json.dumps({"seq": 1, "at": recent, "kind": "note", "text": "ok"}) + "\n",
            encoding="utf-8",
        )
        # No PID files → process_liveness fails; commit and stroke pass.
        _init_git_repo(tmp_path, commit_age_seconds=30)

        report = assess(
            repo_root=tmp_path,
            max_commit_gap=1200,
            max_stroke_gap=600,
            pid_dir=str(tmp_path),
        )
        assert report.verdict == HeartbeatVerdict.DEGRADED

    def test_dead_when_two_fail(self, tmp_path: Path) -> None:
        # No strokes file, no PID files → two failures.
        _init_git_repo(tmp_path, commit_age_seconds=30)

        report = assess(
            repo_root=tmp_path,
            max_commit_gap=1200,
            max_stroke_gap=600,
            pid_dir=str(tmp_path),
        )
        assert report.verdict == HeartbeatVerdict.DEAD

    def test_to_dict_serialises(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path, commit_age_seconds=30)
        report = assess(repo_root=tmp_path, pid_dir=str(tmp_path))
        d = report.to_dict()
        assert "verdict" in d
        assert "signals" in d
        assert isinstance(d["signals"], list)
        assert d["verdict"] in ("healthy", "degraded", "dead")


# ---------------------------------------------------------------------------
# HeartbeatReport dataclass
# ---------------------------------------------------------------------------


class TestHeartbeatReport:
    def test_default_fields(self) -> None:
        r = HeartbeatReport(verdict=HeartbeatVerdict.HEALTHY)
        assert r.signals == []
        assert r.checked_at == ""

    def test_to_dict_empty(self) -> None:
        r = HeartbeatReport(verdict=HeartbeatVerdict.DEAD, checked_at="now")
        d = r.to_dict()
        assert d["verdict"] == "dead"
        assert d["checked_at"] == "now"
        assert d["signals"] == []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import subprocess


def _init_git_repo(path: Path, commit_age_seconds: int = 30) -> None:
    """Create a minimal git repo with one commit aged *commit_age_seconds*."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test"],
        cwd=str(path), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path), check=True, capture_output=True,
    )
    dummy = path / "README.md"
    dummy.write_text("# test\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(path), check=True, capture_output=True,
    )
    if commit_age_seconds > 0:
        # Backdate the commit using GIT_COMMITTER_DATE and --amend.
        import email.utils
        past = datetime.now(timezone.utc) - timedelta(seconds=commit_age_seconds)
        date_str = past.strftime("%Y-%m-%dT%H:%M:%S%z")
        env = {
            **dict(__import__("os").environ),
            "GIT_COMMITTER_DATE": date_str,
            "GIT_AUTHOR_DATE": date_str,
        }
        subprocess.run(
            ["git", "commit", "--amend", "--no-edit", "--date", date_str],
            cwd=str(path), check=True, capture_output=True, env=env,
        )


# Need os for getpid in process liveness tests.
import os
