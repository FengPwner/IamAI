"""Tests for iamai.commit_tempo — musical tempo classification for commit rhythms."""

from __future__ import annotations

import pytest

from iamai.commit_tempo import (
    TEMPO_ORDER,
    _intervals_to_cph,
    _tempo_rank,
    classify_tempo,
    tempo_summary_line,
    tempo_trend,
)


# ---------------------------------------------------------------------------
# _intervals_to_cph
# ---------------------------------------------------------------------------


class TestIntervalsToCph:
    def test_empty(self):
        assert _intervals_to_cph([]) == 0.0

    def test_one_per_minute(self):
        # 60s intervals → 60 commits/hour
        assert _intervals_to_cph([60, 60, 60]) == pytest.approx(60.0)

    def test_one_per_hour(self):
        assert _intervals_to_cph([3600]) == pytest.approx(1.0)

    def test_zero_interval(self):
        assert _intervals_to_cph([0]) == 0.0

    def test_mixed(self):
        # avg of [120, 180] = 150s → 3600/150 = 24 cph
        assert _intervals_to_cph([120, 180]) == pytest.approx(24.0)


# ---------------------------------------------------------------------------
# classify_tempo
# ---------------------------------------------------------------------------


class TestClassifyTempo:
    def test_empty_is_largo(self):
        assert classify_tempo([]) == "largo"

    def test_presto(self):
        # 30s intervals → 120 cph → presto
        assert classify_tempo([30, 30, 30]) == "presto"

    def test_allegro(self):
        # 300s (5min) → 12 cph → allegro
        assert classify_tempo([300, 300, 300]) == "allegro"

    def test_andante(self):
        # 900s (15min) → 4 cph → andante
        assert classify_tempo([900, 900]) == "andante"

    def test_adagio(self):
        # 2400s (40min) → 1.5 cph → adagio
        assert classify_tempo([2400, 2400]) == "adagio"

    def test_largo(self):
        # 7200s (2h) → 0.5 cph → largo
        assert classify_tempo([7200]) == "largo"

    def test_boundary_presto_allegro(self):
        # exactly 30 cph = 120s intervals → presto (≥ 30)
        assert classify_tempo([120]) == "presto"

    def test_boundary_allegro_andante(self):
        # exactly 10 cph = 360s intervals → allegro (≥ 10)
        assert classify_tempo([360]) == "allegro"

    def test_boundary_andante_adagio(self):
        # exactly 3 cph = 1200s intervals → andante (≥ 3)
        assert classify_tempo([1200]) == "andante"

    def test_boundary_adagio_largo(self):
        # exactly 1 cph = 3600s → adagio (≥ 1)
        assert classify_tempo([3600]) == "adagio"


# ---------------------------------------------------------------------------
# _tempo_rank
# ---------------------------------------------------------------------------


class TestTempoRank:
    def test_presto_is_zero(self):
        assert _tempo_rank("presto") == 0

    def test_largo_is_last(self):
        assert _tempo_rank("largo") == len(TEMPO_ORDER) - 1

    def test_unknown(self):
        assert _tempo_rank("unknown") == len(TEMPO_ORDER)


# ---------------------------------------------------------------------------
# tempo_trend
# ---------------------------------------------------------------------------


class TestTempoTrend:
    def test_not_enough_data(self):
        result = tempo_trend([600], recent=5, prior=5)
        assert result["trend"] == "steady"

    def test_steady(self):
        # All intervals similar → steady
        intervals = [600] * 12
        result = tempo_trend(intervals, recent=5, prior=5)
        assert result["trend"] == "steady"
        assert result["recent_tempo"] == result["prior_tempo"]

    def test_decay(self):
        # Fast commits then slows dramatically
        prior = [60] * 5       # 60 cph → presto
        recent = [7200] * 5    # 0.5 cph → largo
        intervals = prior + recent
        result = tempo_trend(intervals, recent=5, prior=5)
        assert result["trend"] == "decaying"
        assert result["prior_tempo"] == "presto"
        assert result["recent_tempo"] == "largo"

    def test_accelerate(self):
        # Slow commits then speeds up
        prior = [3600] * 5     # 1 cph → adagio
        recent = [60] * 5      # 60 cph → presto
        intervals = prior + recent
        result = tempo_trend(intervals, recent=5, prior=5)
        assert result["trend"] == "accelerating"

    def test_mild_slowdown_is_steady(self):
        # allegro → andante (only 1 level drop) = steady
        prior = [300] * 5      # 12 cph → allegro
        recent = [900] * 5     # 4 cph → andante
        intervals = prior + recent
        result = tempo_trend(intervals, recent=5, prior=5)
        assert result["trend"] == "steady"

    def test_return_keys_present(self):
        result = tempo_trend([600] * 10)
        assert "recent_tempo" in result
        assert "prior_tempo" in result
        assert "recent_cph" in result
        assert "prior_cph" in result
        assert "trend" in result


# ---------------------------------------------------------------------------
# tempo_summary_line
# ---------------------------------------------------------------------------


class TestTempoSummaryLine:
    def test_empty(self):
        line = tempo_summary_line([])
        assert "largo" in line
        assert "no data" in line

    def test_contains_tempo_name(self):
        line = tempo_summary_line([300] * 10)
        assert "allegro" in line

    def test_contains_cph(self):
        line = tempo_summary_line([600] * 10)
        assert "cph" in line

    def test_contains_trend(self):
        # decaying scenario
        intervals = [60] * 5 + [7200] * 5
        line = tempo_summary_line(intervals)
        assert "decaying" in line
