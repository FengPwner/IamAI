"""Tests for iamai.pulse_score — composite pipeline health scorer.

15 tests covering:
  - normaliser math (alive, backlog, freshness, push)
  - dead-writer cap
  - grade boundaries
  - summary formatting
  - edge cases (unknown values, zero/negative inputs)
"""

import math
import pytest
from unittest.mock import patch, MagicMock
from iamai.pulse_score import (
    PulseScore,
    PulseReport,
    W_WRITER,
    W_BATCH,
    W_BACKLOG,
    W_FRESHNESS,
    W_PUSH,
    BACKLOG_SOFT,
    FRESHNESS_HALFLIFE,
)


# ---------------------------------------------------------------------------
# Normaliser unit tests
# ---------------------------------------------------------------------------
class TestNormAlive:
    def test_alive_returns_one(self):
        assert PulseScore._norm_alive(True) == 1.0

    def test_dead_returns_zero(self):
        assert PulseScore._norm_alive(False) == 0.0


class TestNormBacklog:
    def test_zero_files_full_score(self):
        assert PulseScore._norm_backlog(0) == 1.0

    def test_soft_point_half_score(self):
        # At BACKLOG_SOFT files, score should be 0.5
        score = PulseScore._norm_backlog(BACKLOG_SOFT)
        assert abs(score - 0.5) < 0.01

    def test_large_backlog_near_zero(self):
        score = PulseScore._norm_backlog(100)
        assert score < 0.05

    def test_negative_means_unknown(self):
        score = PulseScore._norm_backlog(-1)
        assert score == 0.2

    def test_monotonically_decreasing(self):
        prev = 1.0
        for n in range(1, 50):
            s = PulseScore._norm_backlog(n)
            assert s <= prev
            prev = s


class TestNormFreshness:
    def test_zero_seconds_full_score(self):
        assert PulseScore._norm_freshness(0) == 1.0

    def test_halflife_gives_half(self):
        score = PulseScore._norm_freshness(FRESHNESS_HALFLIFE)
        assert abs(score - 0.5) < 0.02

    def test_two_halflives_gives_quarter(self):
        score = PulseScore._norm_freshness(2 * FRESHNESS_HALFLIFE)
        assert abs(score - 0.25) < 0.02

    def test_very_stale_near_zero(self):
        score = PulseScore._norm_freshness(10 * FRESHNESS_HALFLIFE)
        assert score < 0.01

    def test_negative_treated_as_zero(self):
        assert PulseScore._norm_freshness(-5) == 1.0


class TestNormPush:
    def test_zero_lag_full_score(self):
        assert PulseScore._norm_push(0) == 1.0

    def test_one_commit_lag(self):
        score = PulseScore._norm_push(1)
        assert 0.7 < score < 0.8  # 1/(1+0.3) ≈ 0.769

    def test_large_lag_low_score(self):
        score = PulseScore._norm_push(20)
        assert score < 0.15

    def test_negative_means_unknown(self):
        assert PulseScore._norm_push(-1) == 0.5


# ---------------------------------------------------------------------------
# Grade boundary tests
# ---------------------------------------------------------------------------
class TestGrade:
    @pytest.mark.parametrize("total,expected", [
        (95, "A"), (90, "A"),
        (85, "B"), (70, "B"),
        (60, "C"), (50, "C"),
        (40, "D"), (30, "D"),
        (20, "F"), (0, "F"),
    ])
    def test_grade_boundaries(self, total, expected):
        r = PulseReport(total=total)
        assert r.grade == expected


# ---------------------------------------------------------------------------
# Summary format
# ---------------------------------------------------------------------------
class TestSummary:
    def test_summary_contains_grade(self):
        r = PulseReport(total=82, writer_alive=True, batch_alive=True,
                        backlog_count=3, seconds_since_commit=120,
                        push_lag_commits=0)
        s = r.summary
        assert "82" in s
        assert "B" in s
        assert "backlog=3" in s

    def test_summary_shows_dead_writer(self):
        r = PulseReport(total=40, writer_alive=False)
        assert "✗" in r.summary


# ---------------------------------------------------------------------------
# Composite score with mocked probes
# ---------------------------------------------------------------------------
class TestCompositeScore:
    def _make_ps(self):
        return PulseScore("/fake/repo")

    @patch.object(PulseScore, "push_lag", return_value=0)
    @patch.object(PulseScore, "seconds_since_commit", return_value=60.0)
    @patch.object(PulseScore, "backlog_count", return_value=0)
    @patch.object(PulseScore, "batch_alive", return_value=True)
    @patch.object(PulseScore, "writer_alive", return_value=True)
    def test_healthy_pipeline_high_score(self, *_):
        ps = self._make_ps()
        r = ps.score()
        assert r.total >= 90
        assert r.grade == "A"

    @patch.object(PulseScore, "push_lag", return_value=5)
    @patch.object(PulseScore, "seconds_since_commit", return_value=1800.0)
    @patch.object(PulseScore, "backlog_count", return_value=10)
    @patch.object(PulseScore, "batch_alive", return_value=False)
    @patch.object(PulseScore, "writer_alive", return_value=False)
    def test_dead_everything_low_score(self, *_):
        ps = self._make_ps()
        r = ps.score()
        # writer dead → cap at 70; everything else bad → well below 70
        assert r.total < 40
        assert r.grade in ("D", "F")

    @patch.object(PulseScore, "push_lag", return_value=0)
    @patch.object(PulseScore, "seconds_since_commit", return_value=300.0)
    @patch.object(PulseScore, "backlog_count", return_value=2)
    @patch.object(PulseScore, "batch_alive", return_value=True)
    @patch.object(PulseScore, "writer_alive", return_value=False)
    def test_dead_writer_caps_at_70(self, *_):
        ps = self._make_ps()
        r = ps.score()
        # Even though batch/backlog/freshness/push are fine,
        # dead writer caps the score at 70
        assert r.total <= 70.0

    @patch.object(PulseScore, "push_lag", return_value=0)
    @patch.object(PulseScore, "seconds_since_commit", return_value=0.0)
    @patch.object(PulseScore, "backlog_count", return_value=0)
    @patch.object(PulseScore, "batch_alive", return_value=True)
    @patch.object(PulseScore, "writer_alive", return_value=True)
    def test_perfect_score_is_100(self, *_):
        ps = self._make_ps()
        r = ps.score()
        assert abs(r.total - 100.0) < 0.1

    def test_weights_sum_to_100(self):
        assert W_WRITER + W_BATCH + W_BACKLOG + W_FRESHNESS + W_PUSH == 100
