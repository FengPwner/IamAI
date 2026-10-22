"""Tests for iamai.process_zombie."""

import pytest

from iamai.process_zombie import (
    DEFAULT_GRACE_S,
    DEFAULT_HARD_LIMIT_S,
    DualZombieReport,
    ZombieReport,
    classify,
    classify_dual,
)


# ---------------------------------------------------------------------------
# classify — dead process
# ---------------------------------------------------------------------------

class TestDead:
    def test_dead_pid_not_alive(self):
        r = classify(pid_alive=False, last_output_age_s=10)
        assert r.status == "dead"
        assert r.action == "restart"
        assert r.needs_intervention is True

    def test_dead_with_no_output_age(self):
        r = classify(pid_alive=False, last_output_age_s=None)
        assert r.status == "dead"

    def test_dead_with_fresh_output(self):
        """Even if output is fresh, a dead PID is still dead."""
        r = classify(pid_alive=False, last_output_age_s=5)
        assert r.status == "dead"


# ---------------------------------------------------------------------------
# classify — unknown (no output age available)
# ---------------------------------------------------------------------------

class TestUnknown:
    def test_alive_but_no_timestamp(self):
        r = classify(pid_alive=True, last_output_age_s=None)
        assert r.status == "unknown"
        assert r.action == "investigate"
        assert r.needs_intervention is True

    def test_unknown_summary_shows_question_mark(self):
        r = classify(pid_alive=True, last_output_age_s=None)
        assert "?" in r.summary()


# ---------------------------------------------------------------------------
# classify — healthy
# ---------------------------------------------------------------------------

class TestHealthy:
    def test_fresh_output(self):
        r = classify(pid_alive=True, last_output_age_s=60, grace_s=900)
        assert r.status == "healthy"
        assert r.action == "none"
        assert r.needs_intervention is False

    def test_exactly_at_grace_boundary(self):
        r = classify(pid_alive=True, last_output_age_s=900, grace_s=900)
        assert r.status == "healthy"

    def test_very_fresh(self):
        r = classify(pid_alive=True, last_output_age_s=1)
        assert r.status == "healthy"

    def test_zero_age(self):
        r = classify(pid_alive=True, last_output_age_s=0)
        assert r.status == "healthy"


# ---------------------------------------------------------------------------
# classify — zombie
# ---------------------------------------------------------------------------

class TestZombie:
    def test_just_past_grace(self):
        r = classify(pid_alive=True, last_output_age_s=901, grace_s=900)
        assert r.status == "zombie"
        assert r.action == "restart"
        assert r.needs_intervention is True

    def test_well_past_grace_under_hard_limit(self):
        r = classify(pid_alive=True, last_output_age_s=1800, grace_s=900)
        assert r.status == "zombie"

    def test_at_hard_limit(self):
        r = classify(
            pid_alive=True,
            last_output_age_s=DEFAULT_HARD_LIMIT_S,
            grace_s=DEFAULT_GRACE_S,
        )
        assert r.status == "zombie"

    def test_past_hard_limit(self):
        r = classify(
            pid_alive=True,
            last_output_age_s=7200,
            grace_s=900,
            hard_limit_s=3600,
        )
        assert r.status == "zombie"
        assert "hard limit" in r.detail

    def test_zombie_summary_includes_age(self):
        r = classify(pid_alive=True, last_output_age_s=1800, grace_s=900)
        assert "1800s" in r.summary()
        assert "up" in r.summary()


# ---------------------------------------------------------------------------
# classify — custom grace windows
# ---------------------------------------------------------------------------

class TestCustomGrace:
    def test_tight_grace(self):
        r = classify(pid_alive=True, last_output_age_s=60, grace_s=30)
        assert r.status == "zombie"

    def test_loose_grace(self):
        r = classify(pid_alive=True, last_output_age_s=3000, grace_s=3600)
        assert r.status == "healthy"

    def test_custom_hard_limit(self):
        r = classify(
            pid_alive=True,
            last_output_age_s=500,
            grace_s=100,
            hard_limit_s=400,
        )
        assert r.status == "zombie"
        assert "hard limit" in r.detail


# ---------------------------------------------------------------------------
# ZombieReport properties
# ---------------------------------------------------------------------------

class TestZombieReport:
    def test_frozen(self):
        r = classify(pid_alive=True, last_output_age_s=60)
        with pytest.raises(AttributeError):
            r.status = "dead"  # type: ignore[misc]

    def test_summary_contains_pid_status(self):
        r = classify(pid_alive=True, last_output_age_s=60)
        s = r.summary()
        assert "up" in s
        assert "healthy" in s

    def test_summary_dead_shows_down(self):
        r = classify(pid_alive=False)
        assert "down" in r.summary()


# ---------------------------------------------------------------------------
# classify_dual
# ---------------------------------------------------------------------------

class TestClassifyDual:
    def test_both_healthy(self):
        r = classify_dual(
            writer_pid_alive=True,
            writer_last_output_s=60,
            batch_pid_alive=True,
            batch_last_output_s=300,
        )
        assert r.all_healthy is True
        assert r.any_zombie is False
        assert r.any_dead is False

    def test_writer_zombie_batch_healthy(self):
        r = classify_dual(
            writer_pid_alive=True,
            writer_last_output_s=1800,
            batch_pid_alive=True,
            batch_last_output_s=300,
        )
        assert r.all_healthy is False
        assert r.any_zombie is True
        assert r.any_dead is False

    def test_both_dead(self):
        r = classify_dual(
            writer_pid_alive=False,
            batch_pid_alive=False,
        )
        assert r.all_healthy is False
        assert r.any_dead is True

    def test_writer_dead_batch_zombie(self):
        r = classify_dual(
            writer_pid_alive=False,
            batch_pid_alive=True,
            batch_last_output_s=2000,
        )
        assert r.any_dead is True
        assert r.any_zombie is True
        assert r.writer.status == "dead"
        assert r.batch.status == "zombie"

    def test_summary_format(self):
        r = classify_dual(
            writer_pid_alive=True,
            writer_last_output_s=60,
            batch_pid_alive=True,
            batch_last_output_s=120,
        )
        s = r.summary()
        assert "writer:" in s
        assert "batch:" in s

    def test_dual_is_frozen(self):
        r = classify_dual(
            writer_pid_alive=True,
            writer_last_output_s=60,
            batch_pid_alive=True,
            batch_last_output_s=120,
        )
        with pytest.raises(AttributeError):
            r.writer = None  # type: ignore[misc]

    def test_unknown_writer(self):
        r = classify_dual(
            writer_pid_alive=True,
            writer_last_output_s=None,
            batch_pid_alive=True,
            batch_last_output_s=60,
        )
        assert r.writer.status == "unknown"
        assert r.batch.status == "healthy"
        assert r.all_healthy is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_negative_age_treated_as_healthy(self):
        """Negative age is nonsensical but ≤ grace_s, so healthy."""
        r = classify(pid_alive=True, last_output_age_s=-10, grace_s=900)
        assert r.status == "healthy"

    def test_very_large_age(self):
        r = classify(pid_alive=True, last_output_age_s=999999)
        assert r.status == "zombie"

    def test_float_grace_boundary(self):
        r = classify(pid_alive=True, last_output_age_s=100.5, grace_s=100.0)
        assert r.status == "zombie"

    def test_default_constants_are_sensible(self):
        assert DEFAULT_GRACE_S == 900
        assert DEFAULT_HARD_LIMIT_S == 3600
        assert DEFAULT_HARD_LIMIT_S > DEFAULT_GRACE_S
