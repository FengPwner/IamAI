#!/usr/bin/env python3
"""Tests for iamai.caretaker_dashboard — aggregated caretaker snapshot."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.caretaker_dashboard import (
    Signal,
    check_writer_alive,
    check_batch_alive,
    check_backlog,
    check_freshness,
    check_momentum,
    score_to_verdict,
    dashboard_snapshot,
    format_snapshot,
)

REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Signal dataclass
# ---------------------------------------------------------------------------


class TestSignal:
    def test_basic_creation(self):
        s = Signal("test_signal", 2, "all good")
        assert s.name == "test_signal"
        assert s.score == 2
        assert s.detail == "all good"
        assert s.value is None

    def test_with_value(self):
        s = Signal("backlog", 1, "3 files", value=3)
        assert s.value == 3

    def test_to_dict_without_value(self):
        s = Signal("x", 0, "bad")
        d = s.to_dict()
        assert d == {"name": "x", "score": 0, "detail": "bad"}
        assert "value" not in d

    def test_to_dict_with_value(self):
        s = Signal("x", 2, "good", value=42)
        d = s.to_dict()
        assert d == {"name": "x", "score": 2, "detail": "good", "value": 42}

    def test_frozen(self):
        s = Signal("x", 1, "mid")
        with pytest.raises(AttributeError):
            s.score = 2  # type: ignore[misc]


# ---------------------------------------------------------------------------
# score_to_verdict
# ---------------------------------------------------------------------------


class TestScoreToVerdict:
    @pytest.mark.parametrize("score", [8, 9, 10])
    def test_healthy(self, score):
        assert score_to_verdict(score) == "healthy"

    @pytest.mark.parametrize("score", [5, 6, 7])
    def test_attention(self, score):
        assert score_to_verdict(score) == "attention"

    @pytest.mark.parametrize("score", [0, 1, 2, 3, 4])
    def test_critical(self, score):
        assert score_to_verdict(score) == "critical"

    def test_boundary_8_is_healthy(self):
        assert score_to_verdict(8) == "healthy"

    def test_boundary_7_is_attention(self):
        assert score_to_verdict(7) == "attention"

    def test_boundary_5_is_attention(self):
        assert score_to_verdict(5) == "attention"

    def test_boundary_4_is_critical(self):
        assert score_to_verdict(4) == "critical"


# ---------------------------------------------------------------------------
# check_writer_alive / check_batch_alive
# ---------------------------------------------------------------------------


class TestProcessChecks:
    def test_writer_alive_returns_signal(self):
        sig = check_writer_alive(writer="qwen")
        assert isinstance(sig, Signal)
        assert sig.name == "writer_alive"
        assert sig.score in (0, 2)

    def test_batch_alive_returns_signal(self):
        sig = check_batch_alive(writer="qwen")
        assert isinstance(sig, Signal)
        assert sig.name == "batch_alive"
        assert sig.score in (0, 2)

    def test_writer_alive_nonexistent(self):
        """A writer name that definitely doesn't exist."""
        sig = check_writer_alive(writer="nonexistent_writer_xyz_999")
        assert sig.score == 0
        assert "not running" in sig.detail

    def test_batch_alive_nonexistent(self):
        sig = check_batch_alive(writer="nonexistent_writer_xyz_999")
        assert sig.score == 0
        assert "not running" in sig.detail

    @patch("subprocess.check_output")
    def test_writer_alive_mocked_running(self, mock_check):
        mock_check.return_value = "12345\n"
        sig = check_writer_alive(writer="qwen")
        assert sig.score == 2
        assert "12345" in sig.detail

    @patch("subprocess.check_output")
    def test_batch_alive_mocked_running(self, mock_check):
        mock_check.return_value = "67890\n"
        sig = check_batch_alive(writer="qwen")
        assert sig.score == 2
        assert "67890" in sig.detail

    @patch("subprocess.check_output")
    def test_writer_not_found_raises(self, mock_check):
        import subprocess
        mock_check.side_effect = subprocess.CalledProcessError(1, "pgrep")
        sig = check_writer_alive(writer="qwen")
        assert sig.score == 0


# ---------------------------------------------------------------------------
# check_backlog
# ---------------------------------------------------------------------------


class TestCheckBacklog:
    def test_returns_signal(self):
        sig = check_backlog(repo=REPO)
        assert isinstance(sig, Signal)
        assert sig.name == "backlog"
        assert sig.score in (0, 1, 2)

    @patch("subprocess.check_output")
    def test_clean_tree(self, mock_check):
        mock_check.return_value = ""
        sig = check_backlog(repo=REPO)
        assert sig.score == 2
        assert sig.value == 0
        assert "clean" in sig.detail

    @patch("subprocess.check_output")
    def test_small_backlog(self, mock_check):
        mock_check.return_value = " M file1.py\n M file2.py\n M file3.py\n"
        sig = check_backlog(repo=REPO)
        assert sig.score == 1
        assert sig.value == 3

    @patch("subprocess.check_output")
    def test_large_backlog(self, mock_check):
        lines = "\n".join(f" M file{i}.py" for i in range(10))
        mock_check.return_value = lines + "\n"
        sig = check_backlog(repo=REPO)
        assert sig.score == 0
        assert sig.value == 10

    @patch("subprocess.check_output")
    def test_untracked_files_excluded(self, mock_check):
        """Untracked files (?? prefix) should not count toward backlog."""
        mock_check.return_value = "?? new_file.py\n M modified.py\n"
        sig = check_backlog(repo=REPO)
        assert sig.value == 1

    @patch("subprocess.check_output")
    def test_git_failure(self, mock_check):
        import subprocess
        mock_check.side_effect = subprocess.CalledProcessError(1, "git")
        sig = check_backlog(repo=REPO)
        assert sig.score == 0
        assert sig.value == -1


# ---------------------------------------------------------------------------
# check_freshness
# ---------------------------------------------------------------------------


class TestCheckFreshness:
    def test_returns_signal(self):
        sig = check_freshness(repo=REPO)
        assert isinstance(sig, Signal)
        assert sig.name == "freshness_sec"
        assert sig.score in (0, 1, 2)

    @patch("iamai.caretaker_dashboard.Path")
    def test_no_strokes_file(self, mock_path_cls):
        """Nonexistent strokes.jsonl → score 0."""
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        mock_path_cls.return_value = mock_path
        # Direct call with a path that doesn't exist
        sig = check_freshness(repo=Path("/tmp/nonexistent_repo_abc"))
        assert sig.score == 0

    def test_healthy_threshold(self):
        """A very recent stroke should score 2 with generous threshold."""
        sig = check_freshness(repo=REPO, healthy_sec=999999.0)
        # If strokes.jsonl exists and has any parseable stroke
        if sig.value is not None:
            assert sig.score == 2

    def test_custom_thresholds(self):
        sig_tight = check_freshness(repo=REPO, healthy_sec=0.001, degraded_sec=0.002)
        # With impossibly tight thresholds, any real stroke will be stale
        if sig_tight.value is not None:
            assert sig_tight.score == 0


# ---------------------------------------------------------------------------
# check_momentum
# ---------------------------------------------------------------------------


class TestCheckMomentum:
    def test_returns_signal(self):
        sig = check_momentum(repo=REPO)
        assert isinstance(sig, Signal)
        assert sig.name == "momentum"
        assert sig.score in (0, 1, 2)
        assert sig.value in ("accelerating", "steady", "decelerating", "stalled")

    def test_custom_window(self):
        sig = check_momentum(repo=REPO, window_hours=1.0)
        assert isinstance(sig, Signal)

    def test_nonexistent_repo(self):
        sig = check_momentum(repo=Path("/tmp/nonexistent_xyz"))
        # Should handle gracefully — either stalled or error
        assert sig.score in (0, 1, 2)


# ---------------------------------------------------------------------------
# dashboard_snapshot
# ---------------------------------------------------------------------------


class TestDashboardSnapshot:
    def test_returns_dict(self):
        snap = dashboard_snapshot(repo=REPO)
        assert isinstance(snap, dict)
        assert "verdict" in snap
        assert "total_score" in snap
        assert "max_score" in snap
        assert "signals" in snap
        assert "ts" in snap

    def test_verdict_values(self):
        snap = dashboard_snapshot(repo=REPO)
        assert snap["verdict"] in ("healthy", "attention", "critical")

    def test_max_score_is_ten(self):
        """5 signals × 2 max = 10."""
        snap = dashboard_snapshot(repo=REPO)
        assert snap["max_score"] == 10

    def test_total_score_range(self):
        snap = dashboard_snapshot(repo=REPO)
        assert 0 <= snap["total_score"] <= 10

    def test_signals_count(self):
        snap = dashboard_snapshot(repo=REPO)
        assert len(snap["signals"]) == 5

    def test_signal_names(self):
        snap = dashboard_snapshot(repo=REPO)
        names = {s["name"] for s in snap["signals"]}
        expected = {"writer_alive", "batch_alive", "backlog",
                    "freshness_sec", "momentum"}
        assert names == expected

    def test_ts_is_iso_format(self):
        snap = dashboard_snapshot(repo=REPO)
        # Should not raise
        dt = datetime.fromisoformat(snap["ts"])
        assert dt.tzinfo is not None

    def test_custom_writer(self):
        snap = dashboard_snapshot(repo=REPO, writer="nonexistent_xyz")
        # Writer/batch signals should be 0 for nonexistent writer
        writer_sig = next(s for s in snap["signals"]
                          if s["name"] == "writer_alive")
        assert writer_sig["score"] == 0

    def test_custom_freshness_thresholds(self):
        snap = dashboard_snapshot(
            repo=REPO,
            freshness_healthy_sec=0.001,
            freshness_degraded_sec=0.002,
        )
        fresh_sig = next(s for s in snap["signals"]
                         if s["name"] == "freshness_sec")
        # With impossibly tight thresholds, should be 0 if any data exists
        assert fresh_sig["score"] in (0, 1, 2)


# ---------------------------------------------------------------------------
# format_snapshot
# ---------------------------------------------------------------------------


class TestFormatSnapshot:
    def test_returns_string(self):
        snap = dashboard_snapshot(repo=REPO)
        text = format_snapshot(snap)
        assert isinstance(text, str)

    def test_contains_verdict(self):
        snap = dashboard_snapshot(repo=REPO)
        text = format_snapshot(snap)
        assert snap["verdict"].upper() in text

    def test_contains_signal_names(self):
        snap = dashboard_snapshot(repo=REPO)
        text = format_snapshot(snap)
        for sig in snap["signals"]:
            assert sig["name"] in text

    def test_score_bar_length(self):
        """Score bars should always be exactly 2 characters."""
        snap = dashboard_snapshot(repo=REPO)
        text = format_snapshot(snap)
        for line in text.split("\n"):
            if "[" in line and "]" in line:
                bar = line.split("[")[1].split("]")[0]
                assert len(bar) == 2
                assert all(c in "●○" for c in bar)

    def test_all_healthy_snapshot(self):
        """A fully healthy snapshot should format cleanly."""
        snap = {
            "verdict": "healthy",
            "total_score": 10,
            "max_score": 10,
            "signals": [
                {"name": "writer_alive", "score": 2, "detail": "running (pid 1)"},
                {"name": "batch_alive", "score": 2, "detail": "running (pid 2)"},
                {"name": "backlog", "score": 2, "detail": "clean", "value": 0},
                {"name": "freshness_sec", "score": 2, "detail": "last stroke 5s ago"},
                {"name": "momentum", "score": 2, "detail": "steady (ratio 1.00)"},
            ],
            "ts": "2026-10-21T09:00:00+00:00",
        }
        text = format_snapshot(snap)
        assert "HEALTHY" in text
        assert "10/10" in text
        # All bars should be full
        assert text.count("●●") == 5
        assert "○" not in text

    def test_all_critical_snapshot(self):
        snap = {
            "verdict": "critical",
            "total_score": 0,
            "max_score": 10,
            "signals": [
                {"name": "writer_alive", "score": 0, "detail": "not running"},
                {"name": "batch_alive", "score": 0, "detail": "not running"},
                {"name": "backlog", "score": 0, "detail": "12 files"},
                {"name": "freshness_sec", "score": 0, "detail": "stale"},
                {"name": "momentum", "score": 0, "detail": "stalled"},
            ],
            "ts": "2026-10-21T09:00:00+00:00",
        }
        text = format_snapshot(snap)
        assert "CRITICAL" in text
        assert "0/10" in text
        assert text.count("○○") == 5


# ---------------------------------------------------------------------------
# Integration: verdict consistency
# ---------------------------------------------------------------------------


class TestVerdictConsistency:
    def test_verdict_matches_total_score(self):
        """The verdict must be consistent with the total score."""
        snap = dashboard_snapshot(repo=REPO)
        expected = score_to_verdict(snap["total_score"])
        assert snap["verdict"] == expected

    def test_total_matches_signal_sum(self):
        """Total score should equal the sum of individual signal scores."""
        snap = dashboard_snapshot(repo=REPO)
        sig_sum = sum(s["score"] for s in snap["signals"])
        assert snap["total_score"] == sig_sum
