"""Tests for iamai.caretaker_briefing — caretaker arrival status summary."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest

from iamai.caretaker_briefing import (
    Briefing,
    _count_commits_since,
    _count_uncommitted,
    _git,
    _longest_gap_from_state,
    _process_alive,
    _push_lag,
    brief,
)


# ---------------------------------------------------------------------------
# Briefing dataclass
# ---------------------------------------------------------------------------

class TestBriefingDataclass:
    def test_defaults(self):
        b = Briefing()
        assert b.strokes_since_visit == 0
        assert b.commits_since_visit == 0
        assert b.writer_alive is False
        assert b.batch_alive is False
        assert b.uncommitted_files == 0
        assert b.push_lag == 0
        assert b.stall_detected is False
        assert b.warnings == []
        assert b.duration_seconds == 0.0
        assert b.cadence_seconds == 15.0

    def test_healthy_when_all_good(self):
        b = Briefing(writer_alive=True, batch_alive=True)
        assert b.healthy is True

    def test_unhealthy_writer_down(self):
        b = Briefing(writer_alive=False, batch_alive=True)
        assert b.healthy is False

    def test_unhealthy_batch_down(self):
        b = Briefing(writer_alive=True, batch_alive=False)
        assert b.healthy is False

    def test_unhealthy_uncommitted(self):
        b = Briefing(writer_alive=True, batch_alive=True, uncommitted_files=3)
        assert b.healthy is False

    def test_unhealthy_stall(self):
        b = Briefing(writer_alive=True, batch_alive=True, stall_detected=True)
        assert b.healthy is False

    def test_unhealthy_push_lag(self):
        b = Briefing(writer_alive=True, batch_alive=True, push_lag=5)
        assert b.healthy is False


# ---------------------------------------------------------------------------
# Briefing.summary()
# ---------------------------------------------------------------------------

class TestBriefingSummary:
    def test_healthy_summary(self):
        b = Briefing(
            writer_alive=True,
            batch_alive=True,
            strokes_since_visit=10,
            commits_since_visit=2,
        )
        s = b.summary()
        assert "writer up" in s
        assert "batch up" in s
        assert "10 strokes" in s
        assert "2 commits" in s
        assert "tree clean" in s
        assert "push current" in s
        assert "[HEALTHY]" in s

    def test_writer_down_summary(self):
        b = Briefing(writer_alive=False, batch_alive=True)
        s = b.summary()
        assert "writer DOWN" in s
        assert "[NEEDS ATTENTION]" in s

    def test_stall_in_summary(self):
        b = Briefing(
            writer_alive=True,
            batch_alive=True,
            stall_detected=True,
            longest_gap_seconds=120.0,
            cadence_seconds=15.0,
        )
        s = b.summary()
        assert "STALL" in s
        assert "120s" in s
        assert ">30s threshold" in s

    def test_uncommitted_in_summary(self):
        b = Briefing(
            writer_alive=True,
            batch_alive=True,
            uncommitted_files=5,
        )
        s = b.summary()
        assert "5 uncommitted files" in s

    def test_push_lag_in_summary(self):
        b = Briefing(
            writer_alive=True,
            batch_alive=True,
            push_lag=3,
        )
        s = b.summary()
        assert "3 commits ahead" in s

    def test_warnings_in_summary(self):
        b = Briefing(
            writer_alive=True,
            batch_alive=True,
            warnings=["push lag 5 — risk of divergent history"],
        )
        s = b.summary()
        assert "WARNING:" in s
        assert "divergent history" in s


# ---------------------------------------------------------------------------
# _count_commits_since
# ---------------------------------------------------------------------------

class TestCountCommitsSince:
    def test_with_valid_since(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        fake = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="7\n", stderr=""
        )
        with patch("iamai.caretaker_briefing._git", return_value=fake):
            assert _count_commits_since(repo, "abc1234") == 7

    def test_fallback_to_total(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        fail = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="fatal"
        )
        ok = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="42\n", stderr=""
        )
        with patch("iamai.caretaker_briefing._git", side_effect=[fail, ok]):
            assert _count_commits_since(repo, "bad_ref") == 42

    def test_none_since_uses_total(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        ok = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="100\n", stderr=""
        )
        with patch("iamai.caretaker_briefing._git", return_value=ok):
            assert _count_commits_since(repo, None) == 100

    def test_both_fail_returns_zero(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        fail = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="err"
        )
        with patch("iamai.caretaker_briefing._git", side_effect=[fail, fail]):
            assert _count_commits_since(repo, "abc") == 0


# ---------------------------------------------------------------------------
# _count_uncommitted
# ---------------------------------------------------------------------------

class TestCountUncommitted:
    def test_clean_tree(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        clean = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with patch("iamai.caretaker_briefing._git", return_value=clean):
            assert _count_uncommitted(repo) == 0

    def test_dirty_tree(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        dirty = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=" M file1.py\n M file2.py\nA  file3.py\n",
            stderr="",
        )
        with patch("iamai.caretaker_briefing._git", return_value=dirty):
            assert _count_uncommitted(repo) == 3

    def test_git_failure_returns_zero(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        fail = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="err"
        )
        with patch("iamai.caretaker_briefing._git", return_value=fail):
            assert _count_uncommitted(repo) == 0


# ---------------------------------------------------------------------------
# _push_lag
# ---------------------------------------------------------------------------

class TestPushLag:
    def test_no_lag(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        ok = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="0\n", stderr=""
        )
        with patch("iamai.caretaker_briefing._git", return_value=ok):
            assert _push_lag(repo) == 0

    def test_ahead(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        ok = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="4\n", stderr=""
        )
        with patch("iamai.caretaker_briefing._git", return_value=ok):
            assert _push_lag(repo) == 4

    def test_no_remote_returns_zero(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        fail = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="no upstream"
        )
        with patch("iamai.caretaker_briefing._git", return_value=fail):
            assert _push_lag(repo) == 0


# ---------------------------------------------------------------------------
# _process_alive
# ---------------------------------------------------------------------------

class TestProcessAlive:
    def test_alive(self):
        ok = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1234\n", stderr=""
        )
        with patch("subprocess.run", return_value=ok):
            assert _process_alive("", "writer_loop.*qwen") is True

    def test_dead(self):
        fail = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=""
        )
        with patch("subprocess.run", return_value=fail):
            assert _process_alive("", "writer_loop.*qwen") is False

    def test_timeout_returns_false(self):
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="pgrep", timeout=5),
        ):
            assert _process_alive("", "anything") is False

    def test_pgrep_missing_returns_false(self):
        with patch(
            "subprocess.run",
            side_effect=FileNotFoundError,
        ):
            assert _process_alive("", "anything") is False


# ---------------------------------------------------------------------------
# _longest_gap_from_state
# ---------------------------------------------------------------------------

class TestLongestGapFromState:
    def test_no_state_file(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        assert _longest_gap_from_state(repo, "qwen") == 0.0

    def test_empty_history(self, tmp_path):
        repo = tmp_path / "repo"
        data_dir = repo / "data"
        data_dir.mkdir(parents=True)
        state = data_dir / "writer_state.qwen.json"
        state.write_text(json.dumps({"history": []}))
        assert _longest_gap_from_state(repo, "qwen") == 0.0

    def test_single_entry(self, tmp_path):
        repo = tmp_path / "repo"
        data_dir = repo / "data"
        data_dir.mkdir(parents=True)
        state = data_dir / "writer_state.qwen.json"
        state.write_text(json.dumps({"history": [{"timestamp": 1000}]}))
        assert _longest_gap_from_state(repo, "qwen") == 0.0

    def test_two_entries_small_gap(self, tmp_path):
        repo = tmp_path / "repo"
        data_dir = repo / "data"
        data_dir.mkdir(parents=True)
        state = data_dir / "writer_state.qwen.json"
        state.write_text(json.dumps({
            "history": [
                {"timestamp": 1000},
                {"timestamp": 1015},
            ]
        }))
        assert _longest_gap_from_state(repo, "qwen") == 15.0

    def test_multiple_entries_finds_max(self, tmp_path):
        repo = tmp_path / "repo"
        data_dir = repo / "data"
        data_dir.mkdir(parents=True)
        state = data_dir / "writer_state.qwen.json"
        state.write_text(json.dumps({
            "history": [
                {"timestamp": 1000},
                {"timestamp": 1015},
                {"timestamp": 1030},
                {"timestamp": 1300},  # big gap here: 270s
                {"timestamp": 1315},
            ]
        }))
        assert _longest_gap_from_state(repo, "qwen") == 270.0

    def test_corrupt_json(self, tmp_path):
        repo = tmp_path / "repo"
        data_dir = repo / "data"
        data_dir.mkdir(parents=True)
        state = data_dir / "writer_state.qwen.json"
        state.write_text("not valid json {{{")
        assert _longest_gap_from_state(repo, "qwen") == 0.0

    def test_missing_timestamps(self, tmp_path):
        repo = tmp_path / "repo"
        data_dir = repo / "data"
        data_dir.mkdir(parents=True)
        state = data_dir / "writer_state.qwen.json"
        state.write_text(json.dumps({
            "history": [{"stroke": "a"}, {"stroke": "b"}]
        }))
        assert _longest_gap_from_state(repo, "qwen") == 0.0


# ---------------------------------------------------------------------------
# brief() — integration (fully mocked git)
# ---------------------------------------------------------------------------

class TestBriefIntegration:
    def _mock_git(self, return_values: dict):
        """Create a _git mock that dispatches on args."""
        def side_effect(repo, *args):
            # distinguish push_lag (origin/main..HEAD) from commit count
            if args and args[0] == "rev-list":
                if "origin/main..HEAD" in args:
                    return return_values.get(
                        "push_lag",
                        subprocess.CompletedProcess(args=[], returncode=0, stdout="0\n", stderr=""),
                    )
                return return_values.get(
                    "rev-list",
                    subprocess.CompletedProcess(args=[], returncode=0, stdout="0\n", stderr=""),
                )
            key = args[0] if args else "status"
            return return_values.get(
                key,
                subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            )
        return side_effect

    def test_healthy_repo(self, tmp_path):
        repo = tmp_path / "repo"
        data_dir = repo / "data"
        data_dir.mkdir(parents=True)
        state = data_dir / "writer_state.qwen.json"
        state.write_text(json.dumps({
            "history": [{"timestamp": 1000}, {"timestamp": 1015}]
        }))

        git_responses = {
            "rev-list": subprocess.CompletedProcess(
                args=[], returncode=0, stdout="5\n", stderr=""
            ),
            "status": subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            ),
        }

        pgrep_ok = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1178\n", stderr=""
        )

        with (
            patch("iamai.caretaker_briefing._git", side_effect=self._mock_git(git_responses)),
            patch("subprocess.run", return_value=pgrep_ok),
        ):
            b = brief(repo_path=repo, since_commit="abc123", writer_id="qwen")

        assert b.commits_since_visit == 5
        assert b.uncommitted_files == 0
        assert b.writer_alive is True
        assert b.batch_alive is True
        assert b.longest_gap_seconds == 15.0
        assert b.stall_detected is False
        assert b.healthy is True

    def test_stalled_writer(self, tmp_path):
        repo = tmp_path / "repo"
        data_dir = repo / "data"
        data_dir.mkdir(parents=True)
        state = data_dir / "writer_state.qwen.json"
        state.write_text(json.dumps({
            "history": [
                {"timestamp": 1000},
                {"timestamp": 1015},
                {"timestamp": 1500},  # 485s gap → stall
            ]
        }))

        git_responses = {
            "rev-list": subprocess.CompletedProcess(
                args=[], returncode=0, stdout="0\n", stderr=""
            ),
            "status": subprocess.CompletedProcess(
                args=[], returncode=0, stdout=" M notes/foo.md\n", stderr=""
            ),
        }

        pgrep_fail = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=""
        )

        with (
            patch("iamai.caretaker_briefing._git", side_effect=self._mock_git(git_responses)),
            patch("subprocess.run", return_value=pgrep_fail),
        ):
            b = brief(repo_path=repo, since_commit="abc123", writer_id="qwen")

        assert b.writer_alive is False
        assert b.batch_alive is False
        assert b.uncommitted_files == 1
        assert b.longest_gap_seconds == 485.0
        assert b.stall_detected is True
        assert b.healthy is False
        assert any("writer process not found" in w for w in b.warnings)

    def test_push_lag_warning(self, tmp_path):
        repo = tmp_path / "repo"
        data_dir = repo / "data"
        data_dir.mkdir(parents=True)
        state = data_dir / "writer_state.qwen.json"
        state.write_text(json.dumps({"history": []}))

        call_count = {"n": 0}

        def git_side_effect(repo_path, *args):
            key = args[0] if args else "status"
            call_count["n"] += 1
            if key == "rev-list":
                # first call: commits since, second call: push lag
                if call_count["n"] <= 1:
                    return subprocess.CompletedProcess(
                        args=[], returncode=0, stdout="10\n", stderr=""
                    )
                else:
                    return subprocess.CompletedProcess(
                        args=[], returncode=0, stdout="5\n", stderr=""
                    )
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )

        pgrep_ok = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="100\n", stderr=""
        )

        with (
            patch("iamai.caretaker_briefing._git", side_effect=git_side_effect),
            patch("subprocess.run", return_value=pgrep_ok),
        ):
            b = brief(repo_path=repo, since_commit="abc123", writer_id="qwen")

        assert b.push_lag == 5
        assert any("push lag 5" in w for w in b.warnings)

    def test_duration_is_tracked(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        data_dir = repo / "data"
        data_dir.mkdir()
        state = data_dir / "writer_state.qwen.json"
        state.write_text(json.dumps({"history": []}))

        ok = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="0\n", stderr=""
        )
        fail = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=""
        )

        with (
            patch("iamai.caretaker_briefing._git", return_value=ok),
            patch("subprocess.run", return_value=fail),
        ):
            b = brief(repo_path=repo)

        assert b.duration_seconds >= 0.0
        assert b.duration_seconds < 5.0

    def test_custom_cadence(self, tmp_path):
        repo = tmp_path / "repo"
        data_dir = repo / "data"
        data_dir.mkdir(parents=True)
        state = data_dir / "writer_state.qwen.json"
        state.write_text(json.dumps({
            "history": [
                {"timestamp": 1000},
                {"timestamp": 1050},  # 50s gap
            ]
        }))

        ok = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="0\n", stderr=""
        )
        fail = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=""
        )

        with (
            patch("iamai.caretaker_briefing._git", return_value=ok),
            patch("subprocess.run", return_value=fail),
        ):
            # cadence=60 → threshold=120 → 50s gap is NOT a stall
            b = brief(repo_path=repo, writer_id="qwen", cadence=60.0)

        assert b.cadence_seconds == 60.0
        assert b.stall_detected is False

        # Now with cadence=15 → threshold=30 → 50s IS a stall
        with (
            patch("iamai.caretaker_briefing._git", return_value=ok),
            patch("subprocess.run", return_value=fail),
        ):
            b2 = brief(repo_path=repo, writer_id="qwen", cadence=15.0)

        assert b2.stall_detected is True
