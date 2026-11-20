"""Tests for restart_handoff_quality — scoring how cleanly a writer restarts.

A restart is the most dangerous moment in a continuous writer's life.
The gap between the old process's last stroke and the new process's
first stroke is where data loss hides. These tests verify that the
scoring function catches every failure mode.
"""

from __future__ import annotations

import pytest

from iamai.restart_handoff_quality import score_handoff, classify_handoff


def _stroke(seq: int, at: str, kind: str = "thought") -> dict:
    return {"seq": seq, "at": at, "kind": kind}


# --- clean restart -------------------------------------------------------


class TestCleanRestart:
    """A clean restart: 15s gap, seq continues, cadence stable."""

    old = [_stroke(100, "2026-11-20T14:00:00+00:00")]
    new = [
        _stroke(101, "2026-11-20T14:00:15+00:00"),
        _stroke(102, "2026-11-20T14:00:30+00:00"),
        _stroke(103, "2026-11-20T14:00:45+00:00"),
        _stroke(104, "2026-11-20T14:01:00+00:00"),
        _stroke(105, "2026-11-20T14:01:15+00:00"),
        _stroke(106, "2026-11-20T14:01:30+00:00"),
    ]

    def test_continuity_is_clean(self):
        result = score_handoff(self.old, self.new, target_interval=15)
        assert result["continuity"] == "clean"

    def test_latency_is_excellent(self):
        result = score_handoff(self.old, self.new, target_interval=15)
        assert result["latency_s"] == 15.0

    def test_cadence_is_stable(self):
        result = score_handoff(self.old, self.new, target_interval=15)
        assert result["cadence_ratio"] is not None
        assert result["cadence_ratio"] <= 1.5

    def test_grade_is_clean_or_excellent(self):
        result = score_handoff(self.old, self.new, target_interval=15)
        assert result["grade"] in ("clean", "excellent")


# --- data loss -----------------------------------------------------------


class TestDataLoss:
    """A restart that lost strokes: seq jumps by 10."""

    old = [_stroke(100, "2026-11-20T14:00:00+00:00")]
    new = [
        _stroke(110, "2026-11-20T14:05:00+00:00"),
        _stroke(111, "2026-11-20T14:05:15+00:00"),
        _stroke(112, "2026-11-20T14:05:30+00:00"),
        _stroke(113, "2026-11-20T14:05:45+00:00"),
        _stroke(114, "2026-11-20T14:06:00+00:00"),
        _stroke(115, "2026-11-20T14:06:15+00:00"),
    ]

    def test_continuity_is_data_loss(self):
        result = score_handoff(self.old, self.new, target_interval=15)
        assert result["continuity"] == "data_loss"

    def test_seq_gap_reported(self):
        result = score_handoff(self.old, self.new, target_interval=15)
        assert result["details"]["seq_gap"] == 10

    def test_grade_penalised_by_data_loss(self):
        result = score_handoff(self.old, self.new, target_interval=15)
        assert result["grade"] == "data_loss"


# --- slow restart --------------------------------------------------------


class TestSlowRestart:
    """A restart that took 10 minutes to produce its first stroke."""

    old = [_stroke(100, "2026-11-20T14:00:00+00:00")]
    new = [
        _stroke(101, "2026-11-20T14:10:00+00:00"),
        _stroke(102, "2026-11-20T14:10:15+00:00"),
        _stroke(103, "2026-11-20T14:10:30+00:00"),
        _stroke(104, "2026-11-20T14:10:45+00:00"),
        _stroke(105, "2026-11-20T14:11:00+00:00"),
        _stroke(106, "2026-11-20T14:11:15+00:00"),
    ]

    def test_latency_is_slow(self):
        result = score_handoff(self.old, self.new, target_interval=15)
        assert result["details"]["latency_score"] == "slow"

    def test_latency_value(self):
        result = score_handoff(self.old, self.new, target_interval=15)
        assert result["latency_s"] == 600.0


# --- struggling cadence --------------------------------------------------


class TestStrugglingCadence:
    """New process starts but takes increasingly long between strokes."""

    old = [_stroke(100, "2026-11-20T14:00:00+00:00")]
    new = [
        _stroke(101, "2026-11-20T14:00:15+00:00"),
        _stroke(102, "2026-11-20T14:00:45+00:00"),  # 30s
        _stroke(103, "2026-11-20T14:01:45+00:00"),  # 60s
        _stroke(104, "2026-11-20T14:03:45+00:00"),  # 120s
        _stroke(105, "2026-11-20T14:07:45+00:00"),  # 240s
        _stroke(106, "2026-11-20T14:15:45+00:00"),  # 480s
    ]

    def test_cadence_is_struggling(self):
        result = score_handoff(self.old, self.new, target_interval=15)
        assert result["cadence_ratio"] is not None
        assert result["cadence_ratio"] > 3.0

    def test_grade_reflects_struggle(self):
        result = score_handoff(self.old, self.new, target_interval=15)
        # grade should be pulled down by cadence even if latency is fine
        assert result["grade"] in ("struggling", "slow", "stalled")


# --- edge cases ----------------------------------------------------------


class TestEdgeCases:
    """Boundary conditions that should not crash the scorer."""

    def test_empty_old_history(self):
        new = [_stroke(1, "2026-11-20T14:00:00+00:00")]
        result = score_handoff([], new, target_interval=15)
        assert result["grade"] == "unknown"

    def test_empty_new_history(self):
        old = [_stroke(1, "2026-11-20T14:00:00+00:00")]
        result = score_handoff(old, [], target_interval=15)
        assert result["grade"] == "unknown"

    def test_both_empty(self):
        result = score_handoff([], [], target_interval=15)
        assert result["grade"] == "unknown"

    def test_new_history_too_short_for_cadence(self):
        old = [_stroke(100, "2026-11-20T14:00:00+00:00")]
        new = [
            _stroke(101, "2026-11-20T14:00:15+00:00"),
            _stroke(102, "2026-11-20T14:00:30+00:00"),
        ]
        result = score_handoff(old, new, target_interval=15)
        # cadence can't be measured with only 2 new strokes
        assert result["cadence_ratio"] is None
        # but continuity and latency should still work
        assert result["continuity"] == "clean"
        assert result["latency_s"] == 15.0

    def test_overlap_detected(self):
        """Old process wrote a stroke AFTER new process started."""
        old = [_stroke(100, "2026-11-20T14:00:30+00:00")]
        new = [_stroke(101, "2026-11-20T14:00:15+00:00")]
        result = score_handoff(old, new, target_interval=15)
        assert result["latency_s"] < 0
        assert result["details"]["latency_score"] == "overlap"

    def test_minor_sequence_gap(self):
        old = [_stroke(100, "2026-11-20T14:00:00+00:00")]
        new = [
            _stroke(102, "2026-11-20T14:00:15+00:00"),
            _stroke(103, "2026-11-20T14:00:30+00:00"),
        ]
        result = score_handoff(old, new, target_interval=15)
        assert result["continuity"] == "minor_gap"

    def test_zero_target_interval(self):
        """Should not crash with division by zero."""
        old = [_stroke(100, "2026-11-20T14:00:00+00:00")]
        new = [
            _stroke(101, "2026-11-20T14:00:15+00:00"),
            _stroke(102, "2026-11-20T14:00:30+00:00"),
            _stroke(103, "2026-11-20T14:00:45+00:00"),
            _stroke(104, "2026-11-20T14:01:00+00:00"),
            _stroke(105, "2026-11-20T14:01:15+00:00"),
            _stroke(106, "2026-11-20T14:01:30+00:00"),
        ]
        result = score_handoff(old, new, target_interval=0)
        assert result["cadence_ratio"] is None


# --- classify_handoff ----------------------------------------------------


class TestClassify:
    """Human-readable classification strings."""

    def test_clean_classification(self):
        result = classify_handoff({"grade": "clean", "latency_s": 18.0, "details": {}})
        assert "clean restart" in result
        assert "18.0s" in result

    def test_unknown_classification(self):
        result = classify_handoff({"grade": "unknown"})
        assert "insufficient" in result.lower()

    def test_data_loss_classification(self):
        result = classify_handoff({
            "grade": "data_loss",
            "latency_s": 300.0,
            "details": {"seq_gap": 15},
        })
        assert "data loss" in result.lower()
        assert "15" in result

    def test_slow_classification(self):
        result = classify_handoff({
            "grade": "slow",
            "latency_s": 800.0,
            "details": {},
        })
        assert "slow" in result.lower()

    def test_stalled_classification(self):
        result = classify_handoff({
            "grade": "stalled",
            "latency_s": 3600.0,
            "details": {},
        })
        assert "stalled" in result.lower()
