"""Tests for iamai.commit_silence.

Covers: classification logic, silence measurement, pending count,
stroke-since-commit counting, writer-active detection, full status
dict assembly, report formatting, and edge cases.
"""

import json
import os
import subprocess
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.commit_silence import (
    DEFAULT_INTERVAL,
    NORMAL_RATIO,
    STALE_RATIO,
    STRETCHING_RATIO,
    WRITER_GRACE,
    _classify,
    _last_commit_time,
    _pending_count,
    _recent_strokes,
    _writer_active,
    silence_report,
    silence_status,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def tmp_repo(tmp_path):
    """Create a minimal git repo with one commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.check_call(["git", "init", str(repo)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.check_call(
        ["git", "config", "user.email", "test@test.local"],
        cwd=str(repo), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    subprocess.check_call(
        ["git", "config", "user.name", "Test"],
        cwd=str(repo), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    (repo / "README.md").write_text("# test\n")
    # create data dir and strokes file, include in initial commit
    (repo / "data").mkdir()
    (repo / "data" / "strokes.jsonl").write_text("")
    subprocess.check_call(
        ["git", "add", "README.md", "data/strokes.jsonl"],
        cwd=str(repo), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    subprocess.check_call(
        ["git", "commit", "-m", "initial", "--date=2026-10-19T01:00:00+00:00"],
        cwd=str(repo), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return repo


@pytest.fixture
def strokes_file(tmp_path):
    """Return a path to a strokes.jsonl file with sample data."""
    sf = tmp_path / "strokes.jsonl"
    entries = [
        {"seq": 1, "at": "2026-10-19T01:00:00+00:00", "kind": "thought", "text": "alpha"},
        {"seq": 2, "at": "2026-10-19T01:00:15+00:00", "kind": "thought", "text": "beta"},
        {"seq": 3, "at": "2026-10-19T01:00:30+00:00", "kind": "thought", "text": "gamma"},
        {"seq": 4, "at": "2026-10-19T01:00:45+00:00", "kind": "thought", "text": "delta"},
        {"seq": 5, "at": "2026-10-19T01:01:00+00:00", "kind": "thought", "text": "epsilon"},
    ]
    with open(sf, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return sf


# ------------------------------------------------------------------
# _classify
# ------------------------------------------------------------------


class TestClassify:
    def test_normal(self):
        assert _classify(300, 600) == "normal"

    def test_normal_boundary(self):
        # exactly at NORMAL_RATIO boundary → stretching
        boundary = 600 * NORMAL_RATIO
        assert _classify(boundary, 600) == "stretching"

    def test_stretching(self):
        assert _classify(1200, 600) == "stretching"

    def test_stretching_boundary(self):
        boundary = 600 * STRETCHING_RATIO
        assert _classify(boundary, 600) == "stale"

    def test_stale(self):
        assert _classify(2400, 600) == "stale"

    def test_stale_boundary(self):
        boundary = 600 * STALE_RATIO
        assert _classify(boundary, 600) == "dead"

    def test_dead(self):
        assert _classify(7200, 600) == "dead"

    def test_zero_silence(self):
        assert _classify(0, 600) == "normal"

    def test_negative_silence(self):
        # clock skew: silence clamped to 0
        assert _classify(-100, 600) == "normal"

    def test_zero_interval(self):
        assert _classify(100, 0) == "dead"

    def test_very_large_silence(self):
        assert _classify(999999, 600) == "dead"


# ------------------------------------------------------------------
# _last_commit_time
# ------------------------------------------------------------------


class TestLastCommitTime:
    def test_returns_datetime(self, tmp_repo):
        result = _last_commit_time(tmp_repo)
        assert isinstance(result, datetime)

    def test_correct_time(self, tmp_repo):
        result = _last_commit_time(tmp_repo)
        assert result.year == 2026
        assert result.month == 10
        assert result.day == 19

    def test_no_repo(self, tmp_path):
        fake = tmp_path / "nonexistent"
        assert _last_commit_time(fake) is None

    def test_empty_repo(self, tmp_path):
        """Repo exists but has no commits."""
        repo = tmp_path / "empty"
        repo.mkdir()
        subprocess.check_call(["git", "init", str(repo)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert _last_commit_time(repo) is None


# ------------------------------------------------------------------
# _pending_count
# ------------------------------------------------------------------


class TestPendingCount:
    def test_clean_tree(self, tmp_repo):
        assert _pending_count(tmp_repo) == 0

    def test_modified_file(self, tmp_repo):
        (tmp_repo / "README.md").write_text("# modified\n")
        assert _pending_count(tmp_repo) == 1

    def test_new_untracked(self, tmp_repo):
        """Untracked files show in porcelain but are counted."""
        (tmp_repo / "new_file.txt").write_text("hello")
        # porcelain includes untracked with ??
        count = _pending_count(tmp_repo)
        assert count >= 1

    def test_multiple_changes(self, tmp_repo):
        (tmp_repo / "README.md").write_text("# modified\n")
        (tmp_repo / "file2.txt").write_text("new")
        subprocess.check_call(["git", "add", "file2.txt"], cwd=str(tmp_repo), stdout=subprocess.DEVNULL)
        assert _pending_count(tmp_repo) == 2

    def test_no_repo(self, tmp_path):
        assert _pending_count(tmp_path / "nope") == 0


# ------------------------------------------------------------------
# _recent_strokes
# ------------------------------------------------------------------


class TestRecentStrokes:
    def test_reads_all(self, strokes_file):
        result = _recent_strokes(strokes_file)
        assert len(result) == 5

    def test_limit(self, strokes_file):
        result = _recent_strokes(strokes_file, limit=3)
        assert len(result) == 3

    def test_since_filter(self, strokes_file):
        cutoff = datetime(2026, 10, 19, 1, 0, 30, tzinfo=timezone.utc)
        result = _recent_strokes(strokes_file, since=cutoff)
        # entries at :45 and 1:00 → 2 strokes after cutoff
        assert len(result) == 2

    def test_nonexistent_file(self, tmp_path):
        assert _recent_strokes(tmp_path / "missing.jsonl") == []

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        assert _recent_strokes(f) == []

    def test_malformed_lines(self, tmp_path):
        f = tmp_path / "bad.jsonl"
        f.write_text("not json\n{also bad\n")
        assert _recent_strokes(f) == []

    def test_mixed_valid_invalid(self, tmp_path):
        f = tmp_path / "mixed.jsonl"
        f.write_text(
            '{"seq":1,"at":"2026-10-19T01:00:00+00:00","kind":"t","text":"ok"}\n'
            "garbage line\n"
            '{"seq":2,"at":"2026-10-19T01:00:15+00:00","kind":"t","text":"ok2"}\n'
        )
        result = _recent_strokes(f)
        assert len(result) == 2


# ------------------------------------------------------------------
# _writer_active
# ------------------------------------------------------------------


class TestWriterActive:
    def test_active_when_recent(self, strokes_file):
        now = datetime(2026, 10, 19, 1, 1, 30, tzinfo=timezone.utc)
        assert _writer_active(strokes_file, now, grace_seconds=60) is True

    def test_idle_when_stale(self, strokes_file):
        now = datetime(2026, 10, 19, 2, 0, 0, tzinfo=timezone.utc)
        assert _writer_active(strokes_file, now, grace_seconds=60) is False

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        now = datetime(2026, 10, 19, 1, 0, 0, tzinfo=timezone.utc)
        assert _writer_active(f, now) is False

    def test_missing_file(self, tmp_path):
        now = datetime(2026, 10, 19, 1, 0, 0, tzinfo=timezone.utc)
        assert _writer_active(tmp_path / "nope.jsonl", now) is False


# ------------------------------------------------------------------
# silence_status (integration)
# ------------------------------------------------------------------


class TestSilenceStatus:
    def test_returns_dict(self, tmp_repo):
        now = datetime(2026, 10, 19, 1, 5, 0, tzinfo=timezone.utc)
        result = silence_status(tmp_repo, interval=600, now=now)
        assert isinstance(result, dict)

    def test_normal_after_recent_commit(self, tmp_repo):
        now = datetime(2026, 10, 19, 1, 5, 0, tzinfo=timezone.utc)
        result = silence_status(tmp_repo, interval=600, now=now)
        assert result["verdict"] == "normal"
        assert result["silence_seconds"] == pytest.approx(300, abs=5)

    def test_stretching(self, tmp_repo):
        now = datetime(2026, 10, 19, 1, 20, 0, tzinfo=timezone.utc)
        result = silence_status(tmp_repo, interval=600, now=now)
        assert result["verdict"] == "stretching"

    def test_stale(self, tmp_repo):
        now = datetime(2026, 10, 19, 1, 35, 0, tzinfo=timezone.utc)
        result = silence_status(tmp_repo, interval=600, now=now)
        assert result["verdict"] == "stale"

    def test_dead(self, tmp_repo):
        now = datetime(2026, 10, 19, 3, 0, 0, tzinfo=timezone.utc)
        result = silence_status(tmp_repo, interval=600, now=now)
        assert result["verdict"] == "dead"

    def test_pending_changes(self, tmp_repo):
        (tmp_repo / "README.md").write_text("# mod\n")
        now = datetime(2026, 10, 19, 1, 5, 0, tzinfo=timezone.utc)
        result = silence_status(tmp_repo, interval=600, now=now)
        assert result["pending_changes"] >= 1

    def test_clean_tree(self, tmp_repo):
        now = datetime(2026, 10, 19, 1, 5, 0, tzinfo=timezone.utc)
        result = silence_status(tmp_repo, interval=600, now=now)
        assert result["pending_changes"] == 0

    def test_writer_active_with_strokes(self, tmp_repo):
        sf = tmp_repo / "data" / "strokes.jsonl"
        sf.write_text(
            '{"seq":1,"at":"2026-10-19T01:04:30+00:00","kind":"t","text":"hi"}\n'
        )
        now = datetime(2026, 10, 19, 1, 5, 0, tzinfo=timezone.utc)
        result = silence_status(tmp_repo, interval=600, now=now, writer_grace=60)
        assert result["writer_active"] is True

    def test_writer_idle_without_strokes(self, tmp_repo):
        now = datetime(2026, 10, 19, 1, 5, 0, tzinfo=timezone.utc)
        result = silence_status(tmp_repo, interval=600, now=now)
        assert result["writer_active"] is False

    def test_strokes_since_commit(self, tmp_repo):
        sf = tmp_repo / "data" / "strokes.jsonl"
        # commit was at 01:00:00 — strokes after that should count
        entries = [
            {"seq": 1, "at": "2026-10-19T00:59:00+00:00", "kind": "t", "text": "before"},
            {"seq": 2, "at": "2026-10-19T01:00:15+00:00", "kind": "t", "text": "after1"},
            {"seq": 3, "at": "2026-10-19T01:00:30+00:00", "kind": "t", "text": "after2"},
        ]
        with open(sf, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        now = datetime(2026, 10, 19, 1, 5, 0, tzinfo=timezone.utc)
        result = silence_status(tmp_repo, interval=600, now=now)
        assert result["strokes_since_commit"] == 2

    def test_no_commits_returns_dead(self, tmp_path):
        repo = tmp_path / "empty_repo"
        repo.mkdir()
        subprocess.check_call(["git", "init", str(repo)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (repo / "data").mkdir()
        (repo / "data" / "strokes.jsonl").write_text("")
        now = datetime(2026, 10, 19, 1, 0, 0, tzinfo=timezone.utc)
        result = silence_status(repo, interval=600, now=now)
        assert result["verdict"] == "dead"
        assert result["last_commit"] is None

    def test_interval_ratio(self, tmp_repo):
        now = datetime(2026, 10, 19, 1, 15, 0, tzinfo=timezone.utc)
        result = silence_status(tmp_repo, interval=600, now=now)
        # 900s / 600 = 1.5
        assert result["interval_ratio"] == pytest.approx(1.5, abs=0.05)

    def test_last_commit_iso(self, tmp_repo):
        now = datetime(2026, 10, 19, 1, 5, 0, tzinfo=timezone.utc)
        result = silence_status(tmp_repo, interval=600, now=now)
        assert result["last_commit"] is not None
        # should be parseable ISO format
        parsed = datetime.fromisoformat(result["last_commit"])
        assert parsed.year == 2026


# ------------------------------------------------------------------
# silence_report (formatting)
# ------------------------------------------------------------------


class TestSilenceReport:
    def test_normal_clean(self, tmp_repo):
        now = datetime(2026, 10, 19, 1, 5, 0, tzinfo=timezone.utc)
        report = silence_report(tmp_repo, interval=600, now=now)
        assert "normal" in report
        assert "tree clean" in report

    def test_stretching_with_pending(self, tmp_repo):
        (tmp_repo / "README.md").write_text("# mod\n")
        now = datetime(2026, 10, 19, 1, 20, 0, tzinfo=timezone.utc)
        report = silence_report(tmp_repo, interval=600, now=now)
        assert "stretching" in report
        assert "pending" in report

    def test_dead_no_commits(self, tmp_path):
        repo = tmp_path / "empty_repo"
        repo.mkdir()
        subprocess.check_call(["git", "init", str(repo)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (repo / "data").mkdir()
        (repo / "data" / "strokes.jsonl").write_text("")
        now = datetime(2026, 10, 19, 1, 0, 0, tzinfo=timezone.utc)
        report = silence_report(repo, interval=600, now=now)
        assert "dead" in report
        assert "no commits" in report

    def test_writer_active_flag(self, tmp_repo):
        sf = tmp_repo / "data" / "strokes.jsonl"
        sf.write_text(
            '{"seq":1,"at":"2026-10-19T01:04:30+00:00","kind":"t","text":"hi"}\n'
        )
        now = datetime(2026, 10, 19, 1, 5, 0, tzinfo=timezone.utc)
        report = silence_report(tmp_repo, interval=600, now=now, writer_grace=60)
        assert "writer active" in report

    def test_writer_idle_flag(self, tmp_repo):
        now = datetime(2026, 10, 19, 1, 5, 0, tzinfo=timezone.utc)
        report = silence_report(tmp_repo, interval=600, now=now)
        assert "writer idle" in report

    def test_uncommitted_strokes_shown(self, tmp_repo):
        sf = tmp_repo / "data" / "strokes.jsonl"
        entries = [
            {"seq": 1, "at": "2026-10-19T01:00:15+00:00", "kind": "t", "text": "a"},
            {"seq": 2, "at": "2026-10-19T01:00:30+00:00", "kind": "t", "text": "b"},
        ]
        with open(sf, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        now = datetime(2026, 10, 19, 1, 5, 0, tzinfo=timezone.utc)
        report = silence_report(tmp_repo, interval=600, now=now)
        assert "2 strokes uncommitted" in report

    def test_interval_ratio_in_report(self, tmp_repo):
        now = datetime(2026, 10, 19, 1, 20, 0, tzinfo=timezone.utc)
        report = silence_report(tmp_repo, interval=600, now=now)
        assert "× interval" in report


# ------------------------------------------------------------------
# Edge cases & robustness
# ------------------------------------------------------------------


class TestEdgeCases:
    def test_large_strokes_file(self, tmp_path):
        """Module handles files with many strokes efficiently."""
        sf = tmp_path / "big.jsonl"
        with open(sf, "w") as f:
            for i in range(500):
                entry = {
                    "seq": i,
                    "at": f"2026-10-19T01:{i // 60:02d}:{i % 60:02d}+00:00",
                    "kind": "t",
                    "text": f"stroke {i}",
                }
                f.write(json.dumps(entry) + "\n")
        result = _recent_strokes(sf, limit=50)
        assert len(result) == 50

    def test_strokes_with_timezone_offsets(self, tmp_path):
        """Handles various ISO timezone formats."""
        sf = tmp_path / "tz.jsonl"
        entries = [
            {"seq": 1, "at": "2026-10-19T01:00:00+00:00", "kind": "t", "text": "utc"},
            {"seq": 2, "at": "2026-10-19T09:00:00+08:00", "kind": "t", "text": "cst"},
        ]
        with open(sf, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        result = _recent_strokes(sf)
        assert len(result) == 2

    def test_status_keys_complete(self, tmp_repo):
        """All expected keys present in the status dict."""
        now = datetime(2026, 10, 19, 1, 5, 0, tzinfo=timezone.utc)
        result = silence_status(tmp_repo, interval=600, now=now)
        expected_keys = {
            "verdict",
            "silence_seconds",
            "interval_ratio",
            "pending_changes",
            "writer_active",
            "strokes_since_commit",
            "last_commit",
        }
        assert set(result.keys()) == expected_keys

    def test_custom_interval(self, tmp_repo):
        """Works with non-default intervals."""
        now = datetime(2026, 10, 19, 1, 5, 0, tzinfo=timezone.utc)
        result = silence_status(tmp_repo, interval=300, now=now)
        # 300s silence with 300s interval = ratio 1.0 → normal
        assert result["verdict"] == "normal"

    def test_custom_writer_grace(self, tmp_repo):
        sf = tmp_repo / "data" / "strokes.jsonl"
        sf.write_text(
            '{"seq":1,"at":"2026-10-19T01:03:00+00:00","kind":"t","text":"x"}\n'
        )
        now = datetime(2026, 10, 19, 1, 5, 0, tzinfo=timezone.utc)
        # 2 minutes since last stroke: active with 180s grace, idle with 60s
        active = silence_status(tmp_repo, interval=600, now=now, writer_grace=180)
        idle = silence_status(tmp_repo, interval=600, now=now, writer_grace=60)
        assert active["writer_active"] is True
        assert idle["writer_active"] is False
