#!/usr/bin/env python3
"""Tests for commit_signal — commit message information density scoring."""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent

from iamai.commit_signal import (
    CommitScore,
    score,
    score_recent,
    average,
    is_healthy,
    KNOWN_PREFIXES,
    FILLER_PATTERNS,
)


# ---------------------------------------------------------------------------
# score — basic behaviour
# ---------------------------------------------------------------------------

class TestScoreBasic:
    def test_empty_message_returns_zero(self):
        cs = score("")
        assert cs.score == 0.0
        assert "empty" in cs.tags

    def test_whitespace_only_returns_zero(self):
        cs = score("   ")
        assert cs.score == 0.0
        assert "empty" in cs.tags

    def test_returns_commit_score(self):
        cs = score("visit 521: process_survival module + 42 tests + visit note")
        assert isinstance(cs, CommitScore)

    def test_score_clamped_to_ten(self):
        # Craft an impossibly rich message
        msg = "visit 1234567890: " + " ".join(f"word{i}" for i in range(20))
        cs = score(msg)
        assert cs.score <= 10.0

    def test_score_not_negative(self):
        cs = score("wip")
        assert cs.score >= 0.0


# ---------------------------------------------------------------------------
# score — length component
# ---------------------------------------------------------------------------

class TestScoreLength:
    def test_short_message_tagged_too_short(self):
        cs = score("fix bug")
        assert "too-short" in cs.tags

    def test_ten_chars_gets_short_ok(self):
        cs = score("fix bug #42 now")
        assert "short-ok" in cs.tags or "has-metrics" in cs.tags

    def test_thirty_chars_gets_medium(self):
        msg = "visit 100: added the new module with tests"
        cs = score(msg)
        assert cs.score >= 3  # at least medium-length

    def test_fifty_chars_gets_long(self):
        msg = "visit 521: process_survival module + 42 tests + visit note for caretaker"
        cs = score(msg)
        assert "long" in cs.tags or "medium-length" in cs.tags


# ---------------------------------------------------------------------------
# score — prefix component
# ---------------------------------------------------------------------------

class TestScorePrefix:
    def test_known_prefix_scores(self):
        for prefix in ["visit", "guoban", "feat", "fix", "docs", "test"]:
            cs = score(f"{prefix}: something reasonable here today")
            assert "has-prefix" in cs.tags, f"prefix {prefix} not detected"

    def test_unknown_prefix_no_tag(self):
        cs = score("random thing that happened in the codebase today")
        assert "has-prefix" not in cs.tags

    def test_catch_up_counts_as_prefix(self):
        cs = score("catch-up: commit pending changes before restart")
        assert "has-prefix" in cs.tags


# ---------------------------------------------------------------------------
# score — metrics component
# ---------------------------------------------------------------------------

class TestScoreMetrics:
    def test_number_present(self):
        cs = score("stroke 285: the electronic scale resets to zero")
        assert "has-metrics" in cs.tags

    def test_no_number(self):
        cs = score("refactor the garden module for clarity")
        assert "has-metrics" not in cs.tags

    def test_multiple_numbers(self):
        cs = score("visit 521: 42 tests across 6 modules")
        assert "has-metrics" in cs.tags


# ---------------------------------------------------------------------------
# score — filler penalty
# ---------------------------------------------------------------------------

class TestScoreFiller:
    def test_wip_penalised(self):
        cs = score("wip")
        assert "filler" in cs.tags
        assert cs.score < 2

    def test_update_penalised(self):
        cs = score("update")
        assert "filler" in cs.tags

    def test_save_penalised(self):
        cs = score("save")
        assert "filler" in cs.tags

    def test_long_message_not_penalised_as_filler(self):
        cs = score("update the process survival module with new tests")
        assert "filler" not in cs.tags


# ---------------------------------------------------------------------------
# score — real messages from the repo
# ---------------------------------------------------------------------------

class TestScoreRealMessages:
    def test_visit_message_scores_high(self):
        msg = "visit 521: process_survival module + 42 tests + visit note"
        cs = score(msg)
        assert cs.score >= 6

    def test_guoban_message_scores_high(self):
        msg = "guoban: note (stroke 285) — the electronic scale resets"
        cs = score(msg)
        assert cs.score >= 5

    def test_catch_up_scores_moderate(self):
        msg = "catch-up: commit pending changes before process restart"
        cs = score(msg)
        assert 3 <= cs.score <= 8


# ---------------------------------------------------------------------------
# score_recent
# ---------------------------------------------------------------------------

class TestScoreRecent:
    def test_returns_list(self):
        # Mock subprocess to avoid depending on actual git state
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "visit 100: added module\nfix: bug in parser\ncatch-up: pending\n"
        with patch("iamai.commit_signal.subprocess.run", return_value=mock_result):
            scores = score_recent("/fake/repo", n=3)
        assert len(scores) == 3
        assert all(isinstance(s, CommitScore) for s in scores)

    def test_git_failure_returns_empty(self):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        with patch("iamai.commit_signal.subprocess.run", return_value=mock_result):
            scores = score_recent("/nonexistent", n=5)
        assert scores == []

    def test_empty_log_returns_empty(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        with patch("iamai.commit_signal.subprocess.run", return_value=mock_result):
            scores = score_recent("/fake/repo", n=5)
        assert scores == []


# ---------------------------------------------------------------------------
# average
# ---------------------------------------------------------------------------

class TestAverage:
    def test_empty_list(self):
        assert average([]) == 0.0

    def test_single_score(self):
        scores = [CommitScore(message="test", score=7.0)]
        assert average(scores) == 7.0

    def test_multiple_scores(self):
        scores = [
            CommitScore(message="a", score=4.0),
            CommitScore(message="b", score=6.0),
            CommitScore(message="c", score=8.0),
        ]
        assert average(scores) == 6.0


# ---------------------------------------------------------------------------
# is_healthy
# ---------------------------------------------------------------------------

class TestIsHealthy:
    def test_healthy_above_threshold(self):
        scores = [CommitScore(message="a", score=7.0)]
        assert is_healthy(scores, threshold=5.0) is True

    def test_unhealthy_below_threshold(self):
        scores = [CommitScore(message="a", score=3.0)]
        assert is_healthy(scores, threshold=5.0) is False

    def test_exactly_at_threshold(self):
        scores = [CommitScore(message="a", score=5.0)]
        assert is_healthy(scores, threshold=5.0) is True

    def test_empty_scores_unhealthy(self):
        assert is_healthy([], threshold=5.0) is False
