"""Tests for iamai.mortality: can this repo tell whether it is alive?

A continuously writing repository has four failure modes: alive, zombie (writer
running but silent), ghost (strokes flowing but uncommitted), and dead (both
processes gone). These tests pin down the classification logic.
"""

from __future__ import annotations

import pytest

from iamai.mortality import classify, diagnose, mortality_summary


# ---------------------------------------------------------------------------
# classify — the four states
# ---------------------------------------------------------------------------


class TestClassify:
    """State classification from raw signals."""

    def test_alive_when_both_healthy(self):
        result = classify(
            writer_alive=True,
            batch_alive=True,
            stroke_gap_seconds=12,
            commit_gap_seconds=300,
        )
        assert result["state"] == "alive"

    def test_alive_ignores_stale_commits_if_strokes_flow(self):
        # Commit gap exceeds 2x interval but strokes are fresh
        result = classify(
            writer_alive=True,
            batch_alive=True,
            stroke_gap_seconds=10,
            commit_gap_seconds=1500,
        )
        assert result["state"] == "alive"

    def test_zombie_when_writer_up_but_stale(self):
        result = classify(
            writer_alive=True,
            batch_alive=True,
            stroke_gap_seconds=120,  # 8x cadence
            commit_gap_seconds=300,
        )
        assert result["state"] == "zombie"

    def test_zombie_when_writer_just_died_strokes_fresh(self):
        # Writer process gone but last stroke was very recent
        result = classify(
            writer_alive=False,
            batch_alive=True,
            stroke_gap_seconds=20,
            commit_gap_seconds=300,
        )
        assert result["state"] == "zombie"

    def test_ghost_when_batch_alive_strokes_stale(self):
        result = classify(
            writer_alive=False,
            batch_alive=True,
            stroke_gap_seconds=600,
            commit_gap_seconds=300,
        )
        assert result["state"] == "ghost"

    def test_dead_when_both_down(self):
        result = classify(
            writer_alive=False,
            batch_alive=False,
            stroke_gap_seconds=3600,
            commit_gap_seconds=3600,
        )
        assert result["state"] == "dead"

    def test_ghost_when_writer_down_batch_up_commits_fresh(self):
        result = classify(
            writer_alive=False,
            batch_alive=True,
            stroke_gap_seconds=60,
            commit_gap_seconds=500,
        )
        # Writer just died but batch is still committing — ghost
        assert result["state"] in ("zombie", "ghost")

    def test_dead_when_both_down_stale(self):
        result = classify(
            writer_alive=False,
            batch_alive=False,
            stroke_gap_seconds=7200,
            commit_gap_seconds=7200,
        )
        assert result["state"] == "dead"

    def test_zombie_at_exact_2x_boundary(self):
        # At exactly 2x cadence, stroke is still "fresh" (<=)
        result = classify(
            writer_alive=True,
            batch_alive=True,
            stroke_gap_seconds=30,  # exactly 2x 15
            commit_gap_seconds=300,
        )
        assert result["state"] == "alive"

    def test_zombie_just_past_2x_boundary(self):
        result = classify(
            writer_alive=True,
            batch_alive=True,
            stroke_gap_seconds=31,  # just past 2x 15
            commit_gap_seconds=300,
        )
        assert result["state"] == "zombie"


# ---------------------------------------------------------------------------
# classify — custom cadences
# ---------------------------------------------------------------------------


class TestCustomCadence:
    """Verify that the classification respects caller-supplied intervals."""

    def test_slow_writer_needs_wider_window(self):
        result = classify(
            writer_alive=True,
            batch_alive=True,
            stroke_gap_seconds=120,
            commit_gap_seconds=300,
            cadence_seconds=120,  # slow writer: 2 min cadence
        )
        assert result["state"] == "alive"

    def test_fast_committer_needs_wider_window(self):
        result = classify(
            writer_alive=True,
            batch_alive=True,
            stroke_gap_seconds=10,
            commit_gap_seconds=30,
            commit_interval_seconds=60,
        )
        assert result["state"] == "alive"


# ---------------------------------------------------------------------------
# diagnose — richer output
# ---------------------------------------------------------------------------


class TestDiagnose:
    """Diagnose adds advice and severity to the classification."""

    def test_alive_has_ok_severity(self):
        info = diagnose(
            writer_alive=True,
            batch_alive=True,
            stroke_gap_seconds=12,
            commit_gap_seconds=300,
        )
        assert info["state"] == "alive"
        assert info["severity"] == "ok"
        assert "no action" in info["advice"]

    def test_zombie_advises_writer_restart(self):
        info = diagnose(
            writer_alive=True,
            batch_alive=True,
            stroke_gap_seconds=120,
            commit_gap_seconds=300,
        )
        assert info["state"] == "zombie"
        assert info["severity"] == "warning"
        assert "restart" in info["advice"].lower()
        assert "writer" in info["advice"].lower()

    def test_dead_is_critical(self):
        info = diagnose(
            writer_alive=False,
            batch_alive=False,
            stroke_gap_seconds=3600,
            commit_gap_seconds=3600,
        )
        assert info["state"] == "dead"
        assert info["severity"] == "critical"
        assert "both" in info["advice"].lower()

    def test_echoes_input_signals(self):
        info = diagnose(
            writer_alive=True,
            batch_alive=False,
            stroke_gap_seconds=45,
            commit_gap_seconds=800,
            cadence_seconds=15,
            commit_interval_seconds=600,
        )
        assert info["writer_alive"] is True
        assert info["batch_alive"] is False
        assert info["stroke_gap_seconds"] == 45
        assert info["commit_gap_seconds"] == 800


# ---------------------------------------------------------------------------
# mortality_summary — human-readable one-liner
# ---------------------------------------------------------------------------


class TestMortalitySummary:
    """One-line summaries for caretaker logs."""

    def test_alive_summary(self):
        info = diagnose(
            writer_alive=True,
            batch_alive=True,
            stroke_gap_seconds=12,
            commit_gap_seconds=300,
        )
        s = mortality_summary(info)
        assert "alive" in s
        assert "12s" in s

    def test_zombie_summary_mentions_restart(self):
        info = diagnose(
            writer_alive=True,
            batch_alive=True,
            stroke_gap_seconds=120,
            commit_gap_seconds=300,
        )
        s = mortality_summary(info)
        assert "zombie" in s
        assert "restart" in s.lower()

    def test_dead_summary_mentions_full_restart(self):
        info = diagnose(
            writer_alive=False,
            batch_alive=False,
            stroke_gap_seconds=7200,
            commit_gap_seconds=7200,
        )
        s = mortality_summary(info)
        assert "dead" in s
        assert "restart" in s.lower()

    def test_ghost_summary(self):
        info = diagnose(
            writer_alive=False,
            batch_alive=True,
            stroke_gap_seconds=600,
            commit_gap_seconds=300,
        )
        s = mortality_summary(info)
        assert "ghost" in s or "zombie" in s  # boundary case


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Boundary and edge-case inputs."""

    def test_zero_gaps(self):
        result = classify(
            writer_alive=True,
            batch_alive=True,
            stroke_gap_seconds=0,
            commit_gap_seconds=0,
        )
        assert result["state"] == "alive"

    def test_very_large_gaps(self):
        result = classify(
            writer_alive=False,
            batch_alive=False,
            stroke_gap_seconds=86400,
            commit_gap_seconds=86400,
        )
        assert result["state"] == "dead"

    def test_float_gap_seconds(self):
        result = classify(
            writer_alive=True,
            batch_alive=True,
            stroke_gap_seconds=14.7,
            commit_gap_seconds=599.5,
        )
        assert result["state"] == "alive"
