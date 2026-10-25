"""Tests for iamai.caretaker_verdict — fused health verdict."""

from __future__ import annotations

import pytest

from iamai.caretaker_verdict import (
    caretaker_verdict,
    verdict_score,
    verdict_summary,
)


# ---------------------------------------------------------------------------
# caretaker_verdict — healthy cases
# ---------------------------------------------------------------------------

class TestHealthy:
    def test_all_nominal(self):
        assert caretaker_verdict("ok", "stable", "healthy") == "healthy"

    def test_all_none(self):
        """Missing signals treated as nominal."""
        assert caretaker_verdict(None, None, None) == "healthy"

    def test_no_args(self):
        assert caretaker_verdict() == "healthy"

    def test_ok_normal_sparse(self):
        assert caretaker_verdict("ok", "normal", "sparse") == "healthy"


# ---------------------------------------------------------------------------
# caretaker_verdict — watch cases
# ---------------------------------------------------------------------------

class TestWatch:
    def test_recoverable_stall_only(self):
        assert caretaker_verdict("recoverable", "stable", "healthy") == "watch"

    def test_aggressive_restart_only(self):
        assert caretaker_verdict("ok", "aggressive", "healthy") == "watch"

    def test_dense_only(self):
        assert caretaker_verdict("ok", "stable", "dense") == "watch"


# ---------------------------------------------------------------------------
# caretaker_verdict — warn cases
# ---------------------------------------------------------------------------

class TestWarn:
    def test_concerning_stall_only(self):
        assert caretaker_verdict("concerning", "stable", "healthy") == "warn"

    def test_two_minor_signals_bump(self):
        """recoverable(1) + aggressive(1) = 2, plus multi-signal bump → 3 → alert."""
        assert caretaker_verdict("recoverable", "aggressive", "healthy") == "alert"

    def test_dense_plus_aggressive(self):
        """dense(1) + aggressive(1) = 2, bump → 3 → alert."""
        assert caretaker_verdict("ok", "aggressive", "dense") == "alert"

    def test_compact_density_alone(self):
        assert caretaker_verdict("ok", "stable", "compact") == "warn"


# ---------------------------------------------------------------------------
# caretaker_verdict — alert cases
# ---------------------------------------------------------------------------

class TestAlert:
    def test_thrashing_restart(self):
        """Rule 2: thrashing → at least alert."""
        assert caretaker_verdict("ok", "thrashing", "healthy") == "alert"

    def test_thrashing_with_healthy_elsewhere(self):
        assert caretaker_verdict("ok", "thrashing", "sparse") == "alert"

    def test_thrashing_overrides_dense(self):
        assert caretaker_verdict("ok", "thrashing", "dense") == "alert"

    def test_thrashing_with_recoverable_stall(self):
        """Thrashing + recoverable stall → still alert (rule 2 caps it)."""
        assert caretaker_verdict("recoverable", "thrashing", "healthy") == "alert"

    def test_high_combined_weight(self):
        """concerning(2) + aggressive(1) + dense(1) = 4, bump → 5 → alert."""
        assert caretaker_verdict("concerning", "aggressive", "dense") == "alert"


# ---------------------------------------------------------------------------
# caretaker_verdict — escalate cases
# ---------------------------------------------------------------------------

class TestEscalate:
    def test_critical_stall(self):
        """Rule 1: critical stall → escalate."""
        assert caretaker_verdict("critical", "stable", "healthy") == "escalate"

    def test_critical_overrides_everything(self):
        assert caretaker_verdict("critical", "thrashing", "compact") == "escalate"

    def test_critical_with_nominal(self):
        assert caretaker_verdict("critical", "stable", "sparse") == "escalate"


# ---------------------------------------------------------------------------
# caretaker_verdict — unknown input handling
# ---------------------------------------------------------------------------

class TestUnknownInputs:
    def test_unknown_stall_treated_as_worst(self):
        """Unknown stall level maps to weight 4."""
        result = caretaker_verdict("alien_value", "stable", "healthy")
        # weight 4 + 0 + 0 = 4, 1 signal → no bump → alert
        assert result == "alert"

    def test_unknown_restart_treated_as_worst(self):
        result = caretaker_verdict("ok", "alien_value", "healthy")
        # weight 3 + 0 + 0 = 3, 1 signal → no bump → alert
        assert result == "alert"

    def test_unknown_density_treated_as_worst(self):
        result = caretaker_verdict("ok", "stable", "alien_value")
        # weight 2 + 0 + 0 = 2, 1 signal → no bump → warn
        assert result == "warn"

    def test_all_unknown(self):
        result = caretaker_verdict("x", "y", "z")
        # stall unknown doesn't trigger rule 1 (not "critical")
        # restart unknown doesn't trigger rule 2 (not "thrashing")
        # weights: 4 + 3 + 2 = 9, 3 signals → bump → 10 → alert
        assert result == "alert"


# ---------------------------------------------------------------------------
# caretaker_verdict — signal counting edge cases
# ---------------------------------------------------------------------------

class TestSignalCounting:
    def test_exactly_one_signal_no_bump(self):
        """One non-nominal signal should not get the multi-signal bump."""
        # recoverable(1), normal(0), healthy(0) → 1 signal, total=1 → watch
        assert caretaker_verdict("recoverable", "normal", "healthy") == "watch"

    def test_three_signals_get_bump(self):
        """All three non-nominal → bump."""
        # recoverable(1) + aggressive(1) + dense(1) = 3, bump → 4 → alert
        assert caretaker_verdict("recoverable", "aggressive", "dense") == "alert"


# ---------------------------------------------------------------------------
# caretaker_verdict — rule precedence
# ---------------------------------------------------------------------------

class TestRulePrecedence:
    def test_critical_stall_beats_thrashing(self):
        """Rule 1 (escalate) takes priority over rule 2 (alert)."""
        assert caretaker_verdict("critical", "thrashing", "compact") == "escalate"

    def test_thrashing_ignores_density(self):
        """Even with sparse density, thrashing → alert."""
        assert caretaker_verdict("ok", "thrashing", "sparse") == "alert"


# ---------------------------------------------------------------------------
# verdict_score
# ---------------------------------------------------------------------------

class TestVerdictScore:
    def test_healthy_score(self):
        assert verdict_score("healthy") == 0

    def test_watch_score(self):
        assert verdict_score("watch") == 1

    def test_warn_score(self):
        assert verdict_score("warn") == 2

    def test_alert_score(self):
        assert verdict_score("alert") == 3

    def test_escalate_score(self):
        assert verdict_score("escalate") == 4

    def test_unknown_defaults_to_worst(self):
        assert verdict_score("garbage") == 4

    def test_empty_string_defaults_to_worst(self):
        assert verdict_score("") == 4


# ---------------------------------------------------------------------------
# verdict_summary
# ---------------------------------------------------------------------------

class TestVerdictSummary:
    def test_healthy_summary(self):
        result = verdict_summary("ok", "stable", "healthy")
        assert result == "verdict=healthy stall=ok restart=stable density=healthy"

    def test_escalate_summary(self):
        result = verdict_summary("critical", "thrashing", "compact")
        assert result == "verdict=escalate stall=critical restart=thrashing density=compact"

    def test_none_signals_show_as_none(self):
        result = verdict_summary(None, None, None)
        assert result == "verdict=healthy stall=none restart=none density=none"

    def test_partial_none(self):
        result = verdict_summary("ok", None, "dense")
        assert "verdict=watch" in result
        assert "restart=none" in result

    def test_summary_contains_verdict(self):
        result = verdict_summary("concerning", "aggressive", "dense")
        assert result.startswith("verdict=")

    def test_summary_contains_all_signals(self):
        result = verdict_summary("recoverable", "normal", "sparse")
        for key in ("stall=", "restart=", "density="):
            assert key in result


# ---------------------------------------------------------------------------
# integration-style: realistic caretaker scenarios
# ---------------------------------------------------------------------------

class TestRealisticScenarios:
    def test_post_restart_healthy(self):
        """Just restarted, everything fresh."""
        assert caretaker_verdict("ok", "normal", "healthy") == "healthy"

    def test_growing_density_after_hours(self):
        """System running for hours, commit log filling up."""
        assert caretaker_verdict("ok", "normal", "dense") == "watch"

    def test_reclamation_storm(self):
        """Container keeps killing processes."""
        assert caretaker_verdict("ok", "thrashing", "healthy") == "alert"

    def test_extended_outage(self):
        """Writer down for a long time."""
        assert caretaker_verdict("critical", "aggressive", "sparse") == "escalate"

    def test_everything_degraded(self):
        """All signals bad but not critical."""
        result = caretaker_verdict("concerning", "aggressive", "compact")
        # concerning(2) + aggressive(1) + compact(2) = 5, bump → 6 → alert
        assert result == "alert"
