"""Tests for iamai.writer_liveness_probe — composite pipeline health check."""

from __future__ import annotations

import pytest

from iamai.writer_liveness_probe import (
    LivenessSignals,
    LivenessVerdict,
    evaluate_liveness,
    liveness_summary,
    verdict_from_dict,
    DEFAULT_STALE_THRESHOLD,
    DEFAULT_BACKLOG_LIMIT,
    DEFAULT_COMMIT_STALE,
)


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


def _healthy_signals() -> LivenessSignals:
    """All-green signal snapshot."""
    return LivenessSignals(
        process_alive=True,
        stroke_age_seconds=30.0,
        uncommitted_files=2,
        commit_age_seconds=120.0,
    )


def _fully_dead_signals() -> LivenessSignals:
    """All-red signal snapshot."""
    return LivenessSignals(
        process_alive=False,
        stroke_age_seconds=9999.0,
        uncommitted_files=50,
        commit_age_seconds=9999.0,
    )


# ---------------------------------------------------------------------------
# all-green: healthy
# ---------------------------------------------------------------------------


class TestHealthy:
    def test_all_signals_pass(self):
        v = evaluate_liveness(_healthy_signals())
        assert v.status == "healthy"
        assert v.passed == 4
        assert v.total == 4
        assert v.failed_signals == []

    def test_healthy_boundary_stroke(self):
        """stroke_age exactly at threshold still passes."""
        sigs = LivenessSignals(
            process_alive=True,
            stroke_age_seconds=DEFAULT_STALE_THRESHOLD,
            uncommitted_files=0,
            commit_age_seconds=100.0,
        )
        v = evaluate_liveness(sigs)
        assert v.status == "healthy"

    def test_healthy_boundary_backlog(self):
        """uncommitted exactly at limit still passes."""
        sigs = LivenessSignals(
            process_alive=True,
            stroke_age_seconds=10.0,
            uncommitted_files=DEFAULT_BACKLOG_LIMIT,
            commit_age_seconds=100.0,
        )
        v = evaluate_liveness(sigs)
        assert v.status == "healthy"

    def test_healthy_boundary_commit(self):
        """commit_age exactly at threshold still passes."""
        sigs = LivenessSignals(
            process_alive=True,
            stroke_age_seconds=10.0,
            uncommitted_files=0,
            commit_age_seconds=DEFAULT_COMMIT_STALE,
        )
        v = evaluate_liveness(sigs)
        assert v.status == "healthy"

    def test_zero_strokes_zero_backlog(self):
        """Best possible numbers."""
        sigs = LivenessSignals(
            process_alive=True,
            stroke_age_seconds=0.0,
            uncommitted_files=0,
            commit_age_seconds=0.0,
        )
        v = evaluate_liveness(sigs)
        assert v.status == "healthy"
        assert v.failed_signals == []


# ---------------------------------------------------------------------------
# degraded: 1–2 failures
# ---------------------------------------------------------------------------


class TestDegraded:
    def test_process_dead_only(self):
        sigs = LivenessSignals(
            process_alive=False,
            stroke_age_seconds=30.0,
            uncommitted_files=2,
            commit_age_seconds=120.0,
        )
        v = evaluate_liveness(sigs)
        assert v.status == "degraded"
        assert v.passed == 3
        assert "process_alive" in v.failed_signals

    def test_stroke_stale_only(self):
        sigs = LivenessSignals(
            process_alive=True,
            stroke_age_seconds=500.0,
            uncommitted_files=2,
            commit_age_seconds=120.0,
        )
        v = evaluate_liveness(sigs)
        assert v.status == "degraded"
        assert "stroke_fresh" in v.failed_signals

    def test_backlog_overflow_only(self):
        sigs = LivenessSignals(
            process_alive=True,
            stroke_age_seconds=30.0,
            uncommitted_files=25,
            commit_age_seconds=120.0,
        )
        v = evaluate_liveness(sigs)
        assert v.status == "degraded"
        assert "backlog_clear" in v.failed_signals

    def test_commit_stale_only(self):
        sigs = LivenessSignals(
            process_alive=True,
            stroke_age_seconds=30.0,
            uncommitted_files=2,
            commit_age_seconds=1200.0,
        )
        v = evaluate_liveness(sigs)
        assert v.status == "degraded"
        assert "commit_fresh" in v.failed_signals

    def test_two_failures(self):
        """Process dead + stroke stale = degraded (2 failures)."""
        sigs = LivenessSignals(
            process_alive=False,
            stroke_age_seconds=500.0,
            uncommitted_files=2,
            commit_age_seconds=120.0,
        )
        v = evaluate_liveness(sigs)
        assert v.status == "degraded"
        assert v.passed == 2
        assert set(v.failed_signals) == {"process_alive", "stroke_fresh"}

    def test_two_failures_backlog_commit(self):
        sigs = LivenessSignals(
            process_alive=True,
            stroke_age_seconds=30.0,
            uncommitted_files=30,
            commit_age_seconds=2000.0,
        )
        v = evaluate_liveness(sigs)
        assert v.status == "degraded"
        assert set(v.failed_signals) == {"backlog_clear", "commit_fresh"}


# ---------------------------------------------------------------------------
# stalled: 3+ failures
# ---------------------------------------------------------------------------


class TestStalled:
    def test_all_dead(self):
        v = evaluate_liveness(_fully_dead_signals())
        assert v.status == "stalled"
        assert v.passed == 0
        assert v.total == 4
        assert len(v.failed_signals) == 4

    def test_three_failures(self):
        sigs = LivenessSignals(
            process_alive=False,
            stroke_age_seconds=9999.0,
            uncommitted_files=50,
            commit_age_seconds=120.0,  # only commit is fresh
        )
        v = evaluate_liveness(sigs)
        assert v.status == "stalled"
        assert v.passed == 1
        assert "commit_fresh" not in v.failed_signals

    def test_three_failures_different_combo(self):
        sigs = LivenessSignals(
            process_alive=True,  # only process alive
            stroke_age_seconds=9999.0,
            uncommitted_files=50,
            commit_age_seconds=9999.0,
        )
        v = evaluate_liveness(sigs)
        assert v.status == "stalled"
        assert "process_alive" not in v.failed_signals

    def test_four_failures_all_red(self):
        sigs = LivenessSignals(
            process_alive=False,
            stroke_age_seconds=99999.0,
            uncommitted_files=100,
            commit_age_seconds=99999.0,
        )
        v = evaluate_liveness(sigs)
        assert v.status == "stalled"
        assert v.passed == 0


# ---------------------------------------------------------------------------
# custom thresholds
# ---------------------------------------------------------------------------


class TestCustomThresholds:
    def test_tight_stale_threshold(self):
        """A 10-second threshold makes a 30-second-old stroke stale."""
        sigs = LivenessSignals(
            process_alive=True,
            stroke_age_seconds=30.0,
            uncommitted_files=0,
            commit_age_seconds=100.0,
        )
        v = evaluate_liveness(sigs, stale_threshold=10.0)
        assert "stroke_fresh" in v.failed_signals

    def test_tight_backlog_limit(self):
        sigs = LivenessSignals(
            process_alive=True,
            stroke_age_seconds=10.0,
            uncommitted_files=5,
            commit_age_seconds=100.0,
        )
        v = evaluate_liveness(sigs, backlog_limit=3)
        assert "backlog_clear" in v.failed_signals

    def test_tight_commit_stale(self):
        sigs = LivenessSignals(
            process_alive=True,
            stroke_age_seconds=10.0,
            uncommitted_files=0,
            commit_age_seconds=100.0,
        )
        v = evaluate_liveness(sigs, commit_stale=50.0)
        assert "commit_fresh" in v.failed_signals

    def test_relaxed_thresholds_make_everything_healthy(self):
        """Even bad signals pass with generous thresholds."""
        v = evaluate_liveness(
            _fully_dead_signals(),
            stale_threshold=99999.0,
            backlog_limit=999,
            commit_stale=99999.0,
        )
        # process_alive is still False
        assert v.passed == 3
        assert v.status == "degraded"

    def test_invalid_stale_threshold(self):
        with pytest.raises(ValueError, match="stale_threshold"):
            evaluate_liveness(_healthy_signals(), stale_threshold=0)

    def test_invalid_backlog_limit(self):
        with pytest.raises(ValueError, match="backlog_limit"):
            evaluate_liveness(_healthy_signals(), backlog_limit=-1)

    def test_invalid_commit_stale(self):
        with pytest.raises(ValueError, match="commit_stale"):
            evaluate_liveness(_healthy_signals(), commit_stale=0)


# ---------------------------------------------------------------------------
# signal_results detail
# ---------------------------------------------------------------------------


class TestSignalResults:
    def test_healthy_details(self):
        v = evaluate_liveness(_healthy_signals())
        assert v.signal_results["process_alive"][0] is True
        assert "running" in v.signal_results["process_alive"][1]

    def test_dead_process_detail(self):
        sigs = LivenessSignals(
            process_alive=False,
            stroke_age_seconds=10.0,
            uncommitted_files=0,
            commit_age_seconds=100.0,
        )
        v = evaluate_liveness(sigs)
        assert v.signal_results["process_alive"][0] is False
        assert "dead" in v.signal_results["process_alive"][1]

    def test_stroke_detail_includes_age(self):
        sigs = LivenessSignals(
            process_alive=True,
            stroke_age_seconds=456.0,
            uncommitted_files=0,
            commit_age_seconds=100.0,
        )
        v = evaluate_liveness(sigs)
        assert "456" in v.signal_results["stroke_fresh"][1]

    def test_backlog_detail_includes_count(self):
        sigs = LivenessSignals(
            process_alive=True,
            stroke_age_seconds=10.0,
            uncommitted_files=42,
            commit_age_seconds=100.0,
        )
        v = evaluate_liveness(sigs)
        assert "42" in v.signal_results["backlog_clear"][1]


# ---------------------------------------------------------------------------
# liveness_summary
# ---------------------------------------------------------------------------


class TestLivenessSummary:
    def test_healthy_summary(self):
        s = liveness_summary(_healthy_signals())
        assert "healthy" in s
        assert "4/4" in s

    def test_degraded_summary_shows_failed(self):
        sigs = LivenessSignals(
            process_alive=False,
            stroke_age_seconds=10.0,
            uncommitted_files=0,
            commit_age_seconds=100.0,
        )
        s = liveness_summary(sigs)
        assert "degraded" in s
        assert "process_alive" in s

    def test_stalled_summary(self):
        s = liveness_summary(_fully_dead_signals())
        assert "stalled" in s
        assert "0/4" in s

    def test_summary_with_custom_thresholds(self):
        s = liveness_summary(_healthy_signals(), stale_threshold=10.0)
        assert "stroke_fresh" in s  # should fail with 10s threshold


# ---------------------------------------------------------------------------
# verdict_from_dict round-trip
# ---------------------------------------------------------------------------


class TestVerdictFromDict:
    def test_round_trip_healthy(self):
        original = evaluate_liveness(_healthy_signals())
        # Simulate JSON serialisation: tuples → lists
        serialised = {
            "status": original.status,
            "passed": original.passed,
            "total": original.total,
            "failed_signals": original.failed_signals,
            "signal_results": {
                k: list(v) for k, v in original.signal_results.items()
            },
        }
        restored = verdict_from_dict(serialised)
        assert restored.status == original.status
        assert restored.passed == original.passed
        assert restored.total == original.total
        assert restored.failed_signals == original.failed_signals

    def test_round_trip_stalled(self):
        original = evaluate_liveness(_fully_dead_signals())
        serialised = {
            "status": original.status,
            "passed": original.passed,
            "total": original.total,
            "failed_signals": original.failed_signals,
            "signal_results": {
                k: list(v) for k, v in original.signal_results.items()
            },
        }
        restored = verdict_from_dict(serialised)
        assert restored.status == "stalled"
        assert restored.passed == 0
        assert len(restored.failed_signals) == 4

    def test_empty_dict(self):
        v = verdict_from_dict({})
        assert v.status == "unknown"
        assert v.passed == 0
        assert v.total == 0

    def test_partial_dict(self):
        v = verdict_from_dict({"status": "healthy", "passed": 4, "total": 4})
        assert v.status == "healthy"
        assert v.failed_signals == []


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_zero_stroke_age(self):
        sigs = LivenessSignals(
            process_alive=True,
            stroke_age_seconds=0.0,
            uncommitted_files=0,
            commit_age_seconds=0.0,
        )
        v = evaluate_liveness(sigs)
        assert v.status == "healthy"

    def test_exact_threshold_boundary_all(self):
        """All signals exactly at their thresholds — should pass."""
        sigs = LivenessSignals(
            process_alive=True,
            stroke_age_seconds=DEFAULT_STALE_THRESHOLD,
            uncommitted_files=DEFAULT_BACKLOG_LIMIT,
            commit_age_seconds=DEFAULT_COMMIT_STALE,
        )
        v = evaluate_liveness(sigs)
        assert v.status == "healthy"

    def test_one_over_threshold_all(self):
        """All signals just over their thresholds — 3 failures = stalled."""
        sigs = LivenessSignals(
            process_alive=True,
            stroke_age_seconds=DEFAULT_STALE_THRESHOLD + 1,
            uncommitted_files=DEFAULT_BACKLOG_LIMIT + 1,
            commit_age_seconds=DEFAULT_COMMIT_STALE + 1,
        )
        v = evaluate_liveness(sigs)
        assert v.status == "stalled"
        assert v.passed == 1  # only process_alive

    def test_frozen_signals(self):
        """LivenessSignals is frozen — cannot mutate after creation."""
        sigs = _healthy_signals()
        with pytest.raises(AttributeError):
            sigs.process_alive = False  # type: ignore[misc]

    def test_frozen_verdict(self):
        """LivenessVerdict is frozen — cannot mutate after creation."""
        v = evaluate_liveness(_healthy_signals())
        with pytest.raises(AttributeError):
            v.status = "stalled"  # type: ignore[misc]

    def test_very_large_numbers(self):
        """Handles extreme values without overflow."""
        sigs = LivenessSignals(
            process_alive=False,
            stroke_age_seconds=1e15,
            uncommitted_files=999999,
            commit_age_seconds=1e15,
        )
        v = evaluate_liveness(sigs)
        assert v.status == "stalled"

    def test_negative_stroke_age_treated_as_fresh(self):
        """Negative age is technically fresh (shouldn't happen but safe)."""
        sigs = LivenessSignals(
            process_alive=True,
            stroke_age_seconds=-10.0,
            uncommitted_files=0,
            commit_age_seconds=-5.0,
        )
        v = evaluate_liveness(sigs)
        assert v.status == "healthy"
