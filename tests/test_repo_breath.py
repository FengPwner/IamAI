"""Tests for iamai.repo_breath."""

import math
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.repo_breath import (
    BreathReport,
    breath_report,
    breath_summary,
    _compute_regularity,
    _compute_score,
    _classify,
    _git_log,
    _strokes_between,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _commit(h: str, ts: float) -> dict:
    return {"hash": h, "timestamp": ts, "parents": []}


# Helper: make a list of commits in git-log order (NEWEST first)
def _make_commits_newest_first(count: int, interval: float = 600.0, base: float = 1_700_000_000.0) -> list[dict]:
    """Return *count* commits in git-log order (newest first)."""
    return [
        _commit(f"{'a' + str(i).zfill(7)}" * 5, base + i * interval)
        for i in range(count - 1, -1, -1)
    ]


# ---------------------------------------------------------------------------
# _compute_regularity
# ---------------------------------------------------------------------------

class TestComputeRegularity:
    def test_empty(self):
        assert _compute_regularity([]) == 1.0

    def test_single(self):
        assert _compute_regularity([100.0]) == 1.0

    def test_identical_durations(self):
        assert _compute_regularity([60.0, 60.0, 60.0]) == 1.0

    def test_high_variance(self):
        durations = [10.0, 100.0, 10.0, 100.0]
        r = _compute_regularity(durations)
        assert 0.0 <= r < 0.5

    def test_low_variance(self):
        durations = [59.0, 60.0, 61.0, 60.0, 59.5]
        r = _compute_regularity(durations)
        assert r > 0.9

    def test_clamped_to_zero(self):
        durations = [1.0, 10000.0, 1.0, 10000.0]
        r = _compute_regularity(durations)
        assert r >= 0.0

    def test_zero_mean(self):
        assert _compute_regularity([0.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# _compute_score
# ---------------------------------------------------------------------------

class TestComputeScore:
    def test_perfect_score(self):
        score = _compute_score(
            regularity=1.0, depth=5.0, hold_ratio=0.0, hyperventilation=0.0
        )
        assert score == 100.0

    def test_zero_everything(self):
        score = _compute_score(
            regularity=0.0, depth=0.0, hold_ratio=1.0, hyperventilation=1.0
        )
        assert score == 0.0

    def test_depth_sweet_spot(self):
        s5 = _compute_score(1.0, 5.0, 0.0, 0.0)
        s1 = _compute_score(1.0, 1.0, 0.0, 0.0)
        assert s5 > s1

    def test_depth_too_high(self):
        s5 = _compute_score(1.0, 5.0, 0.0, 0.0)
        s50 = _compute_score(1.0, 50.0, 0.0, 0.0)
        assert s5 > s50

    def test_hold_penalty(self):
        no_hold = _compute_score(1.0, 5.0, 0.0, 0.0)
        high_hold = _compute_score(1.0, 5.0, 0.5, 0.0)
        assert no_hold > high_hold

    def test_hyperventilation_penalty(self):
        no_hyper = _compute_score(1.0, 5.0, 0.0, 0.0)
        high_hyper = _compute_score(1.0, 5.0, 0.0, 0.5)
        assert no_hyper > high_hyper

    def test_clamped_above(self):
        score = _compute_score(2.0, 5.0, 0.0, 0.0)
        assert score <= 100.0

    def test_clamped_below(self):
        score = _compute_score(-1.0, -1.0, 2.0, 2.0)
        assert score >= 0.0


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_steady(self):
        assert _classify(80.0, 0.0, 0.0) == "steady"

    def test_steady_boundary(self):
        assert _classify(75.0, 0.0, 0.0) == "steady"

    def test_distressed(self):
        assert _classify(40.0, 0.0, 0.0) == "distressed"

    def test_shallow(self):
        assert _classify(60.0, 0.0, 0.5) == "shallow"

    def test_holding(self):
        assert _classify(60.0, 0.5, 0.0) == "holding"

    def test_erratic(self):
        assert _classify(60.0, 0.1, 0.1) == "erratic"

    def test_shallow_over_holding(self):
        """Hyperventilation > 0.4 takes precedence over hold_ratio."""
        assert _classify(60.0, 0.5, 0.5) == "shallow"


# ---------------------------------------------------------------------------
# breath_summary
# ---------------------------------------------------------------------------

class TestBreathSummary:
    def test_empty_report(self):
        r = BreathReport()
        assert "insufficient" in breath_summary(r)

    def test_normal_report(self):
        r = BreathReport(
            breath_count=10,
            breath_rate=6.2,
            breath_depth=4.3,
            breath_regularity=0.82,
            breath_score=78.5,
            pattern="steady",
        )
        s = breath_summary(r)
        assert "steady" in s
        assert "6.2" in s
        assert "4.3" in s
        assert "78.5" in s

    def test_contains_pattern(self):
        r = BreathReport(
            breath_count=5,
            breath_rate=3.0,
            breath_depth=2.0,
            breath_regularity=0.5,
            breath_score=45.0,
            pattern="distressed",
        )
        assert "distressed" in breath_summary(r)


# ---------------------------------------------------------------------------
# _git_log
# ---------------------------------------------------------------------------

class TestGitLog:
    @patch("iamai.repo_breath.subprocess.check_output")
    def test_parses_log(self, mock_out):
        mock_out.return_value = (
            "abc123def456\x001700000000\x00parent1\n"
            "def456ghi789\x001700001000\x00abc123def456\n"
        )
        commits = _git_log("/fake", 10)
        assert len(commits) == 2
        assert commits[0]["hash"] == "abc123def456"
        assert commits[0]["timestamp"] == 1700000000.0
        assert commits[1]["parents"] == ["abc123def456"]

    @patch("iamai.repo_breath.subprocess.check_output")
    def test_empty_log(self, mock_out):
        mock_out.return_value = ""
        commits = _git_log("/fake", 10)
        assert commits == []

    @patch("iamai.repo_breath.subprocess.check_output")
    def test_no_parents(self, mock_out):
        """A root commit with no parents has an empty parents list."""
        mock_out.return_value = "abc123\x001700000000\x00\n"
        commits = _git_log("/fake", 10)
        assert commits[0]["parents"] == []

    @patch("iamai.repo_breath.subprocess.check_output")
    def test_passes_max_count(self, mock_out):
        """Ensure --max-count is forwarded correctly."""
        mock_out.return_value = ""
        _git_log("/fake", 50)
        call_args = mock_out.call_args
        assert "--max-count=50" in call_args[0][0]


# ---------------------------------------------------------------------------
# _strokes_between
# ---------------------------------------------------------------------------

class TestStrokesBetween:
    @patch("iamai.repo_breath.subprocess.check_output")
    def test_counts_added_lines(self, mock_out):
        mock_out.return_value = (
            "--- a/data/strokes.jsonl\n"
            "+++ b/data/strokes.jsonl\n"
            '+{"seq":1}\n'
            '+{"seq":2}\n'
            '+{"seq":3}\n'
            '-{"old":true}\n'
        )
        n = _strokes_between("/fake", "aaa", "bbb")
        assert n == 3

    @patch("iamai.repo_breath.subprocess.check_output")
    def test_no_diff(self, mock_out):
        mock_out.return_value = ""
        n = _strokes_between("/fake", "aaa", "bbb")
        assert n == 0

    @patch("iamai.repo_breath.subprocess.check_output")
    def test_handles_error(self, mock_out):
        from subprocess import CalledProcessError
        mock_out.side_effect = CalledProcessError(1, "git")
        n = _strokes_between("/fake", "aaa", "bbb")
        assert n == 0


# ---------------------------------------------------------------------------
# breath_report (integration-style with mocks)
# ---------------------------------------------------------------------------

class TestBreathReport:

    @patch("iamai.repo_breath._strokes_between")
    @patch("iamai.repo_breath._git_log")
    def test_basic_report(self, mock_log, mock_strokes):
        # git log returns NEWEST first
        mock_log.return_value = _make_commits_newest_first(6, interval=600)
        mock_strokes.return_value = 5

        r = breath_report(repo_path="/fake", last=10)
        assert r.breath_count == 5
        assert r.breath_depth == 5.0
        assert r.breath_rate > 0
        assert r.pattern in ("steady", "shallow", "holding", "erratic", "distressed")

    @patch("iamai.repo_breath._git_log")
    def test_insufficient_commits(self, mock_log):
        mock_log.return_value = [_commit("a" * 40, 1000.0)]
        r = breath_report(repo_path="/fake")
        assert r.breath_count == 0
        assert r.breath_score == 0.0

    @patch("iamai.repo_breath._git_log")
    def test_empty_log(self, mock_log):
        mock_log.return_value = []
        r = breath_report(repo_path="/fake")
        assert r.breath_count == 0

    @patch("iamai.repo_breath._strokes_between")
    @patch("iamai.repo_breath._git_log")
    def test_regularity_perfect(self, mock_log, mock_strokes):
        """All intervals identical → regularity = 1.0."""
        mock_log.return_value = _make_commits_newest_first(10, interval=300)
        mock_strokes.return_value = 3

        r = breath_report(repo_path="/fake", last=20)
        assert r.breath_regularity == 1.0

    @patch("iamai.repo_breath._strokes_between")
    @patch("iamai.repo_breath._git_log")
    def test_hyperventilation_all_shallow(self, mock_log, mock_strokes):
        """All breaths with 1 stroke → hyperventilation = 1.0."""
        mock_log.return_value = _make_commits_newest_first(6, interval=60)
        mock_strokes.return_value = 1

        r = breath_report(repo_path="/fake", last=10)
        assert r.hyperventilation == 1.0

    @patch("iamai.repo_breath._strokes_between")
    @patch("iamai.repo_breath._git_log")
    def test_hold_ratio_detected(self, mock_log, mock_strokes):
        """One very long gap among many short ones."""
        base = 1_700_000_000.0
        # git log order: newest first
        commits_newest_first = [
            _commit("e" * 40, base + 10300),   # newest
            _commit("d" * 40, base + 300),
            _commit("c" * 40, base + 200),
            _commit("b" * 40, base + 100),
            _commit("a" * 40, base),             # oldest
        ]
        mock_log.return_value = commits_newest_first
        mock_strokes.return_value = 3

        r = breath_report(repo_path="/fake", last=10)
        # After reverse: durations = [100, 100, 100, 10000]
        # median = 100; one duration (10000) > 200 → hold_ratio = 0.25
        assert r.hold_ratio > 0.0

    @patch("iamai.repo_breath._strokes_between")
    @patch("iamai.repo_breath._git_log")
    def test_breath_count_matches_intervals(self, mock_log, mock_strokes):
        """N commits → N-1 breaths."""
        mock_log.return_value = _make_commits_newest_first(8, interval=120)
        mock_strokes.return_value = 2

        r = breath_report(repo_path="/fake", last=20)
        assert r.breath_count == 7

    @patch("iamai.repo_breath._strokes_between")
    @patch("iamai.repo_breath._git_log")
    def test_window_seconds(self, mock_log, mock_strokes):
        mock_log.return_value = _make_commits_newest_first(5, interval=3600)
        mock_strokes.return_value = 4

        r = breath_report(repo_path="/fake", last=10)
        assert r.window_seconds == 4 * 3600.0

    @patch("iamai.repo_breath._strokes_between")
    @patch("iamai.repo_breath._git_log")
    def test_breath_rate_calculation(self, mock_log, mock_strokes):
        """4 breaths over 1 hour = rate 4.0."""
        # 5 commits, 4 intervals × 900s = 3600s = 1h
        mock_log.return_value = _make_commits_newest_first(5, interval=900)
        mock_strokes.return_value = 5

        r = breath_report(repo_path="/fake", last=10)
        assert abs(r.breath_rate - 4.0) < 0.1

    @patch("iamai.repo_breath._strokes_between")
    @patch("iamai.repo_breath._git_log")
    def test_steady_pattern(self, mock_log, mock_strokes):
        """Regular rhythm, good depth → steady."""
        mock_log.return_value = _make_commits_newest_first(12, interval=600)
        mock_strokes.return_value = 5

        r = breath_report(repo_path="/fake", last=20)
        assert r.pattern == "steady"
        assert r.breath_score >= 75.0

    @patch("iamai.repo_breath._strokes_between")
    @patch("iamai.repo_breath._git_log")
    def test_distressed_pattern(self, mock_log, mock_strokes):
        """Irregular rhythm with zero depth → distressed."""
        base = 1_700_000_000.0
        # git log order: newest first — wildly varying gaps
        commits_newest_first = [
            _commit("e" * 40, base + 20011),  # newest
            _commit("d" * 40, base + 5011),
            _commit("c" * 40, base + 5010),
            _commit("b" * 40, base + 10),
            _commit("a" * 40, base),           # oldest
        ]
        mock_log.return_value = commits_newest_first
        mock_strokes.return_value = 0  # zero strokes → hyperventilation = 1.0

        r = breath_report(repo_path="/fake", last=10)
        assert r.breath_score < 50
        assert r.pattern == "distressed"


# ---------------------------------------------------------------------------
# BreathReport dataclass
# ---------------------------------------------------------------------------

class TestBreathReportDataclass:
    def test_defaults(self):
        r = BreathReport()
        assert r.breath_count == 0
        assert r.breath_rate == 0.0
        assert r.breath_depth == 0.0
        assert r.breath_regularity == 0.0
        assert r.hold_ratio == 0.0
        assert r.hyperventilation == 0.0
        assert r.breath_score == 0.0
        assert r.pattern == "distressed"
        assert r.breaths == []

    def test_breaths_list_independent(self):
        """Each instance gets its own list."""
        a = BreathReport()
        b = BreathReport()
        a.breaths.append({"x": 1})
        assert b.breaths == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    @patch("iamai.repo_breath._strokes_between")
    @patch("iamai.repo_breath._git_log")
    def test_two_commits(self, mock_log, mock_strokes):
        """Minimum valid input: 2 commits → 1 breath."""
        mock_log.return_value = [
            _commit("b" * 40, 1600.0),
            _commit("a" * 40, 1000.0),
        ]
        mock_strokes.return_value = 3

        r = breath_report(repo_path="/fake", last=5)
        assert r.breath_count == 1
        assert r.breath_depth == 3.0

    @patch("iamai.repo_breath._strokes_between")
    @patch("iamai.repo_breath._git_log")
    def test_zero_duration_breaths(self, mock_log, mock_strokes):
        """Same-second commits excluded from regularity duration filter."""
        mock_log.return_value = [
            _commit("c" * 40, 1000.0),
            _commit("b" * 40, 1000.0),
            _commit("a" * 40, 1000.0),
        ]
        mock_strokes.return_value = 2

        r = breath_report(repo_path="/fake", last=5)
        assert r.breath_count == 2
        assert r.window_seconds == 0.0

    @patch("iamai.repo_breath._strokes_between")
    @patch("iamai.repo_breath._git_log")
    def test_last_capped_at_200(self, mock_log, mock_strokes):
        """Even if user passes 1000, breath_report caps at 200."""
        mock_log.return_value = _make_commits_newest_first(5)
        mock_strokes.return_value = 1
        breath_report(repo_path="/fake", last=1000)
        # _git_log was called with last=200 (capped by breath_report)
        call_args = mock_log.call_args
        assert call_args[0][1] == 200  # second positional arg is 'last'
