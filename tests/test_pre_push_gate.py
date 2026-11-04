"""Tests for iamai.pre_push_gate — the automatic push gate.

Covers:
  - DivergenceInfo severity classification at all boundaries
  - measure() with injected count_fn (success + failure)
  - resolve() decision tree: no divergence, critical, rebase ok, rebase fail
  - push_phase() terminal vs non-terminal outcomes
  - run_gate() end-to-end scenarios
  - GateConfig defaults and frozen dataclass properties
"""

import pytest
from iamai.pre_push_gate import (
    DivergenceInfo,
    GateConfig,
    GateResult,
    Outcome,
    Severity,
    measure,
    push_phase,
    resolve,
    run_gate,
)


# =========================================================================
# DivergenceInfo
# =========================================================================

class TestDivergenceInfo:
    def test_total(self):
        d = DivergenceInfo(local_ahead=3, remote_ahead=5)
        assert d.total == 8

    def test_total_zero(self):
        d = DivergenceInfo(local_ahead=0, remote_ahead=0)
        assert d.total == 0

    def test_severity_none(self):
        assert DivergenceInfo(5, 0).severity == Severity.NONE

    def test_severity_low_at_1(self):
        assert DivergenceInfo(0, 1).severity == Severity.LOW

    def test_severity_low_at_3(self):
        assert DivergenceInfo(0, 3).severity == Severity.LOW

    def test_severity_medium_at_4(self):
        assert DivergenceInfo(0, 4).severity == Severity.MEDIUM

    def test_severity_medium_at_10(self):
        assert DivergenceInfo(0, 10).severity == Severity.MEDIUM

    def test_severity_critical_at_11(self):
        assert DivergenceInfo(0, 11).severity == Severity.CRITICAL

    def test_severity_critical_large(self):
        assert DivergenceInfo(0, 999).severity == Severity.CRITICAL

    def test_frozen(self):
        d = DivergenceInfo(1, 2)
        with pytest.raises(AttributeError):
            d.local_ahead = 5  # type: ignore[misc]


# =========================================================================
# measure()
# =========================================================================

class TestMeasure:
    def test_synced(self):
        cfg = GateConfig(count_fn=lambda r, rem, b: (0, 0))
        result = measure(cfg)
        assert result.divergence == DivergenceInfo(0, 0)
        assert result.outcome == Outcome.PUSHED

    def test_local_ahead_only(self):
        cfg = GateConfig(count_fn=lambda r, rem, b: (5, 0))
        result = measure(cfg)
        assert result.divergence.local_ahead == 5
        assert result.divergence.remote_ahead == 0

    def test_remote_ahead(self):
        cfg = GateConfig(count_fn=lambda r, rem, b: (2, 7))
        result = measure(cfg)
        assert result.divergence.remote_ahead == 7

    def test_count_failure(self):
        def bad_count(r, rem, b):
            raise RuntimeError("network down")
        cfg = GateConfig(count_fn=bad_count)
        result = measure(cfg)
        assert result.outcome == Outcome.BLOCKED_NO_REMOTE
        assert "network down" in result.detail

    def test_default_count_raises(self):
        cfg = GateConfig()
        result = measure(cfg)
        assert result.outcome == Outcome.BLOCKED_NO_REMOTE


# =========================================================================
# resolve()
# =========================================================================

class TestResolve:
    def test_no_divergence_passthrough(self):
        cfg = GateConfig()
        m = GateResult(
            outcome=Outcome.PUSHED,
            divergence=DivergenceInfo(3, 0),
        )
        r = resolve(cfg, m)
        assert r.outcome == Outcome.PUSHED
        assert r.rebased is False

    def test_blocked_no_remote_passthrough(self):
        cfg = GateConfig()
        m = GateResult(outcome=Outcome.BLOCKED_NO_REMOTE, detail="oops")
        r = resolve(cfg, m)
        assert r.outcome == Outcome.BLOCKED_NO_REMOTE

    def test_critical_divergence_blocked(self):
        cfg = GateConfig(max_remote_ahead=10)
        m = GateResult(
            outcome=Outcome.PUSHED,
            divergence=DivergenceInfo(2, 11),
        )
        r = resolve(cfg, m)
        assert r.outcome == Outcome.BLOCKED_CRITICAL
        assert "exceeds" in r.detail

    def test_rebase_success(self):
        cfg = GateConfig(rebase_fn=lambda r, rem, b: (True, "rebased 3 commits"))
        m = GateResult(
            outcome=Outcome.PUSHED,
            divergence=DivergenceInfo(1, 3),
        )
        r = resolve(cfg, m)
        assert r.outcome == Outcome.RESOLVED_AND_PUSHED
        assert r.rebased is True
        assert "rebased 3 commits" in r.detail

    def test_rebase_failure(self):
        cfg = GateConfig(
            rebase_fn=lambda r, rem, b: (False, "CONFLICT in foo.py")
        )
        m = GateResult(
            outcome=Outcome.PUSHED,
            divergence=DivergenceInfo(1, 5),
        )
        r = resolve(cfg, m)
        assert r.outcome == Outcome.BLOCKED_CONFLICT
        assert "CONFLICT" in r.detail

    def test_boundary_at_10_not_critical(self):
        """remote_ahead=10 should attempt rebase, not block."""
        cfg = GateConfig(
            max_remote_ahead=10,
            rebase_fn=lambda r, rem, b: (True, "ok"),
        )
        m = GateResult(
            outcome=Outcome.PUSHED,
            divergence=DivergenceInfo(0, 10),
        )
        r = resolve(cfg, m)
        # Severity.MEDIUM (not CRITICAL) → rebase attempted
        assert r.outcome == Outcome.RESOLVED_AND_PUSHED

    def test_boundary_at_11_is_critical(self):
        cfg = GateConfig(max_remote_ahead=10)
        m = GateResult(
            outcome=Outcome.PUSHED,
            divergence=DivergenceInfo(0, 11),
        )
        r = resolve(cfg, m)
        assert r.outcome == Outcome.BLOCKED_CRITICAL


# =========================================================================
# push_phase()
# =========================================================================

class TestPushPhase:
    def test_push_success(self):
        cfg = GateConfig(push_fn=lambda r, rem, b: (True, "main -> main"))
        r = GateResult(outcome=Outcome.PUSHED, divergence=DivergenceInfo(1, 0))
        result = push_phase(cfg, r)
        assert result.pushed is True
        assert "push ok" in result.detail

    def test_push_failure(self):
        cfg = GateConfig(push_fn=lambda r, rem, b: (False, "rejected"))
        r = GateResult(outcome=Outcome.PUSHED, divergence=DivergenceInfo(1, 0))
        result = push_phase(cfg, r)
        assert result.pushed is False
        assert "push failed" in result.detail

    def test_resolved_then_push(self):
        cfg = GateConfig(push_fn=lambda r, rem, b: (True, "done"))
        r = GateResult(
            outcome=Outcome.RESOLVED_AND_PUSHED,
            divergence=DivergenceInfo(1, 3),
            rebased=True,
        )
        result = push_phase(cfg, r)
        assert result.pushed is True

    def test_blocked_conflict_skips_push(self):
        cfg = GateConfig(push_fn=lambda r, rem, b: (True, "should not run"))
        r = GateResult(outcome=Outcome.BLOCKED_CONFLICT)
        result = push_phase(cfg, r)
        assert result.outcome == Outcome.BLOCKED_CONFLICT
        assert result.pushed is False

    def test_blocked_critical_skips_push(self):
        cfg = GateConfig(push_fn=lambda r, rem, b: (True, "nope"))
        r = GateResult(outcome=Outcome.BLOCKED_CRITICAL)
        result = push_phase(cfg, r)
        assert result.outcome == Outcome.BLOCKED_CRITICAL

    def test_blocked_no_remote_skips_push(self):
        cfg = GateConfig(push_fn=lambda r, rem, b: (True, "nope"))
        r = GateResult(outcome=Outcome.BLOCKED_NO_REMOTE)
        result = push_phase(cfg, r)
        assert result.outcome == Outcome.BLOCKED_NO_REMOTE


# =========================================================================
# run_gate() — end-to-end
# =========================================================================

class TestRunGate:
    def test_synced_push_directly(self):
        cfg = GateConfig(
            count_fn=lambda r, rem, b: (3, 0),
            push_fn=lambda r, rem, b: (True, "ok"),
        )
        result = run_gate(cfg)
        assert result.outcome == Outcome.PUSHED
        assert result.pushed is True
        assert result.rebased is False

    def test_divergence_rebase_and_push(self):
        cfg = GateConfig(
            count_fn=lambda r, rem, b: (2, 4),
            rebase_fn=lambda r, rem, b: (True, "fast-forwarded"),
            push_fn=lambda r, rem, b: (True, "pushed"),
        )
        result = run_gate(cfg)
        assert result.outcome == Outcome.RESOLVED_AND_PUSHED
        assert result.rebased is True
        assert result.pushed is True

    def test_critical_blocked(self):
        cfg = GateConfig(
            count_fn=lambda r, rem, b: (1, 15),
            rebase_fn=lambda r, rem, b: (True, "should not run"),
            push_fn=lambda r, rem, b: (True, "should not run"),
        )
        result = run_gate(cfg)
        assert result.outcome == Outcome.BLOCKED_CRITICAL

    def test_rebase_conflict_blocked(self):
        cfg = GateConfig(
            count_fn=lambda r, rem, b: (1, 2),
            rebase_fn=lambda r, rem, b: (False, "merge conflict"),
            push_fn=lambda r, rem, b: (True, "should not run"),
        )
        result = run_gate(cfg)
        assert result.outcome == Outcome.BLOCKED_CONFLICT

    def test_remote_unreachable(self):
        def bad_count(r, rem, b):
            raise OSError("unreachable")
        cfg = GateConfig(count_fn=bad_count)
        result = run_gate(cfg)
        assert result.outcome == Outcome.BLOCKED_NO_REMOTE

    def test_push_after_resolve_fails(self):
        cfg = GateConfig(
            count_fn=lambda r, rem, b: (1, 2),
            rebase_fn=lambda r, rem, b: (True, "ok"),
            push_fn=lambda r, rem, b: (False, "rejected again"),
        )
        result = run_gate(cfg)
        assert result.outcome == Outcome.RESOLVED_AND_PUSHED
        assert result.rebased is True
        assert result.pushed is False
        assert "push failed" in result.detail


# =========================================================================
# GateConfig defaults
# =========================================================================

class TestGateConfig:
    def test_defaults(self):
        cfg = GateConfig()
        assert cfg.repo == "."
        assert cfg.remote == "origin"
        assert cfg.branch == "main"
        assert cfg.max_remote_ahead == 10
        assert cfg.count_fn is None
        assert cfg.rebase_fn is None
        assert cfg.push_fn is None

    def test_custom_values(self):
        cfg = GateConfig(repo="/tmp/x", remote="upstream",
                         branch="develop", max_remote_ahead=5)
        assert cfg.repo == "/tmp/x"
        assert cfg.remote == "upstream"
        assert cfg.branch == "develop"
        assert cfg.max_remote_ahead == 5
