"""Tests for iamai.ghost_writer_detector -- alive-but-silent process detection."""

import pytest

from iamai.ghost_writer_detector import (
    ALIVE,
    DEAD,
    GHOST,
    SUSPICIOUS,
    GhostWriterDetector,
    diagnose_writer,
)


# ---------------------------------------------------------------------------
# Basic classification
# ---------------------------------------------------------------------------

class TestBasicClassification:
    def test_alive_right_after_heartbeat(self):
        d = GhostWriterDetector(cadence=15.0)
        d.record_heartbeat(now=100.0)
        assert d.classify(now=100.0) == ALIVE

    def test_alive_within_deadline(self):
        d = GhostWriterDetector(cadence=15.0, tolerance=2.0)
        d.record_heartbeat(now=100.0)
        # deadline = 15 * 2 = 30s; at t=125 silence=25s < 30s
        assert d.classify(now=125.0) == ALIVE

    def test_suspicious_past_deadline(self):
        d = GhostWriterDetector(cadence=15.0, tolerance=2.0)
        d.record_heartbeat(now=100.0)
        # deadline = 30s, ghost_threshold = 60s; silence=35s
        assert d.classify(now=135.0) == SUSPICIOUS

    def test_ghost_past_ghost_threshold(self):
        d = GhostWriterDetector(cadence=15.0, tolerance=2.0, ghost_multiplier=2.0)
        d.record_heartbeat(now=100.0)
        # ghost_threshold = 30 * 2 = 60s; silence=65s
        assert d.classify(now=165.0) == GHOST

    def test_ghost_when_no_heartbeat(self):
        d = GhostWriterDetector(cadence=15.0)
        assert d.classify(now=100.0) == GHOST

    def test_exactly_at_deadline_is_alive(self):
        d = GhostWriterDetector(cadence=15.0, tolerance=2.0)
        d.record_heartbeat(now=0.0)
        # deadline = 30.0; silence exactly 30s => alive (<=)
        assert d.classify(now=30.0) == ALIVE

    def test_exactly_at_ghost_threshold_is_ghost(self):
        d = GhostWriterDetector(cadence=15.0, tolerance=2.0, ghost_multiplier=2.0)
        d.record_heartbeat(now=0.0)
        # ghost_threshold = 60.0; silence exactly 60s => ghost (>=)
        assert d.classify(now=60.0) == GHOST


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class TestProperties:
    def test_deadline_calculation(self):
        d = GhostWriterDetector(cadence=10.0, tolerance=3.0)
        assert d.deadline == 30.0

    def test_ghost_threshold_calculation(self):
        d = GhostWriterDetector(cadence=10.0, tolerance=3.0, ghost_multiplier=2.0)
        assert d.ghost_threshold == 60.0

    def test_default_tolerance(self):
        d = GhostWriterDetector(cadence=15.0)
        assert d.deadline == 30.0  # 15 * 2.0

    def test_default_ghost_multiplier(self):
        d = GhostWriterDetector(cadence=15.0)
        assert d.ghost_threshold == 60.0  # 30 * 2.0


# ---------------------------------------------------------------------------
# Heartbeat recording
# ---------------------------------------------------------------------------

class TestHeartbeat:
    def test_heartbeat_resets_suspicion(self):
        d = GhostWriterDetector(cadence=15.0, tolerance=2.0)
        d.record_heartbeat(now=0.0)
        # At t=35, would be suspicious
        assert d.classify(now=35.0) == SUSPICIOUS
        # New heartbeat at t=35
        d.record_heartbeat(now=35.0)
        assert d.classify(now=35.0) == ALIVE

    def test_total_heartbeats_increments(self):
        d = GhostWriterDetector(cadence=15.0)
        d.record_heartbeat(now=0.0)
        d.record_heartbeat(now=15.0)
        d.record_heartbeat(now=30.0)
        assert d._total_heartbeats == 3

    def test_multiple_heartbeats_track_latest(self):
        d = GhostWriterDetector(cadence=15.0, tolerance=2.0)
        d.record_heartbeat(now=0.0)
        d.record_heartbeat(now=100.0)
        # Latest heartbeat at 100, so at t=120 silence=20s < deadline 30s
        assert d.classify(now=120.0) == ALIVE


# ---------------------------------------------------------------------------
# Silence duration
# ---------------------------------------------------------------------------

class TestSilenceDuration:
    def test_silence_after_heartbeat(self):
        d = GhostWriterDetector(cadence=15.0)
        d.record_heartbeat(now=50.0)
        assert d.silence_duration(now=80.0) == 30.0

    def test_silence_zero_when_just_heartbeated(self):
        d = GhostWriterDetector(cadence=15.0)
        d.record_heartbeat(now=50.0)
        assert d.silence_duration(now=50.0) == 0.0

    def test_silence_zero_when_no_heartbeat(self):
        d = GhostWriterDetector(cadence=15.0)
        assert d.silence_duration(now=100.0) == 0.0

    def test_silence_clamped_to_zero(self):
        d = GhostWriterDetector(cadence=15.0)
        d.record_heartbeat(now=100.0)
        # Querying before last heartbeat
        assert d.silence_duration(now=50.0) == 0.0


# ---------------------------------------------------------------------------
# Health score
# ---------------------------------------------------------------------------

class TestHealthScore:
    def test_perfect_health_right_after_heartbeat(self):
        d = GhostWriterDetector(cadence=15.0)
        d.record_heartbeat(now=0.0)
        assert d.health_score(now=0.0) == 1.0

    def test_zero_health_at_ghost_threshold(self):
        d = GhostWriterDetector(cadence=15.0, tolerance=2.0, ghost_multiplier=2.0)
        d.record_heartbeat(now=0.0)
        # ghost_threshold = 60s
        assert d.health_score(now=60.0) == 0.0

    def test_zero_health_beyond_ghost_threshold(self):
        d = GhostWriterDetector(cadence=15.0)
        d.record_heartbeat(now=0.0)
        assert d.health_score(now=10000.0) == 0.0

    def test_zero_health_no_heartbeat(self):
        d = GhostWriterDetector(cadence=15.0)
        assert d.health_score(now=100.0) == 0.0

    def test_health_decreases_with_silence(self):
        d = GhostWriterDetector(cadence=15.0, tolerance=2.0, ghost_multiplier=2.0)
        d.record_heartbeat(now=0.0)
        # ghost_threshold = 60s
        h1 = d.health_score(now=10.0)  # silence=10s
        h2 = d.health_score(now=30.0)  # silence=30s
        h3 = d.health_score(now=50.0)  # silence=50s
        assert h1 > h2 > h3

    def test_health_half_at_half_threshold(self):
        d = GhostWriterDetector(cadence=15.0, tolerance=2.0, ghost_multiplier=2.0)
        d.record_heartbeat(now=0.0)
        # ghost_threshold = 60s; at 30s silence -> health = 1 - 30/60 = 0.5
        assert abs(d.health_score(now=30.0) - 0.5) < 1e-6


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_keys(self):
        d = GhostWriterDetector(cadence=15.0)
        d.record_heartbeat(now=0.0)
        s = d.summary(now=10.0)
        expected = {
            "state", "silence_seconds", "deadline",
            "ghost_threshold", "health_score", "total_heartbeats",
            "pid", "pid_alive",
        }
        assert set(s.keys()) == expected

    def test_summary_alive_state(self):
        d = GhostWriterDetector(cadence=15.0, tolerance=2.0)
        d.record_heartbeat(now=100.0)
        s = d.summary(now=110.0)
        assert s["state"] == ALIVE
        assert s["silence_seconds"] == 10.0
        assert s["total_heartbeats"] == 1

    def test_summary_no_pid(self):
        d = GhostWriterDetector(cadence=15.0)
        s = d.summary(now=0.0)
        assert s["pid"] is None
        assert s["pid_alive"] is None


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_clears_state(self):
        d = GhostWriterDetector(cadence=15.0)
        d.record_heartbeat(now=100.0)
        d.record_heartbeat(now=115.0)
        d.reset()
        assert d._last_heartbeat == -1.0
        assert d._total_heartbeats == 0
        assert d._missed_deadlines == 0

    def test_reset_returns_to_ghost(self):
        d = GhostWriterDetector(cadence=15.0)
        d.record_heartbeat(now=100.0)
        assert d.classify(now=105.0) == ALIVE
        d.reset()
        assert d.classify(now=105.0) == GHOST


# ---------------------------------------------------------------------------
# PID liveness (mock-based)
# ---------------------------------------------------------------------------

class TestPIDLiveness:
    def test_dead_process_returns_dead(self):
        """A non-existent PID should result in DEAD classification."""
        # PID 999999 almost certainly doesn't exist
        d = GhostWriterDetector(cadence=15.0, pid=999999)
        d.record_heartbeat(now=0.0)
        assert d.classify(now=1.0) == DEAD

    def test_no_pid_skips_liveness_check(self):
        d = GhostWriterDetector(cadence=15.0, pid=None)
        d.record_heartbeat(now=0.0)
        # Should not be DEAD since no PID to check
        assert d.classify(now=1.0) == ALIVE


# ---------------------------------------------------------------------------
# diagnose_writer (one-shot function)
# ---------------------------------------------------------------------------

class TestDiagnoseWriter:
    def test_healthy_writer(self):
        result = diagnose_writer(last_output=100.0, now=105.0, cadence=15.0)
        assert result["state"] == ALIVE
        assert result["silence_seconds"] == 5.0

    def test_stalled_writer(self):
        result = diagnose_writer(last_output=0.0, now=100.0, cadence=15.0)
        assert result["state"] == GHOST
        assert result["silence_seconds"] == 100.0

    def test_suspicious_writer(self):
        result = diagnose_writer(
            last_output=0.0, now=35.0, cadence=15.0,
        )
        # deadline = 30s, ghost = 60s; silence=35s → suspicious
        assert result["state"] == SUSPICIOUS

    def test_no_output_ever(self):
        result = diagnose_writer(last_output=-1.0, now=100.0, cadence=15.0)
        assert result["state"] == GHOST

    def test_result_keys(self):
        result = diagnose_writer(last_output=0.0, now=10.0, cadence=15.0)
        expected = {"state", "silence_seconds", "health_score", "pid_alive"}
        assert set(result.keys()) == expected

    def test_health_score_in_range(self):
        result = diagnose_writer(last_output=0.0, now=20.0, cadence=15.0)
        assert 0.0 <= result["health_score"] <= 1.0

    def test_dead_writer_bad_pid(self):
        result = diagnose_writer(
            last_output=100.0, now=105.0, cadence=15.0, pid=999999,
        )
        assert result["state"] == DEAD
        assert result["pid_alive"] is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_zero_cadence(self):
        """Zero cadence means instant deadline — any silence is suspicious."""
        d = GhostWriterDetector(cadence=0.0, tolerance=2.0, ghost_multiplier=2.0)
        d.record_heartbeat(now=0.0)
        # deadline=0, ghost_threshold=0; silence=1s > 0 → ghost
        assert d.classify(now=1.0) == GHOST

    def test_very_large_tolerance(self):
        d = GhostWriterDetector(cadence=15.0, tolerance=100.0, ghost_multiplier=2.0)
        d.record_heartbeat(now=0.0)
        # deadline=1500s, ghost_threshold=3000s
        assert d.classify(now=500.0) == ALIVE

    def test_classify_at_exact_now_equals_heartbeat(self):
        d = GhostWriterDetector(cadence=15.0)
        d.record_heartbeat(now=42.0)
        assert d.classify(now=42.0) == ALIVE
