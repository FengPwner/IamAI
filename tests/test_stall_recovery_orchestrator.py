"""Tests for iamai.stall_recovery_orchestrator.

35 tests covering:
  - RecoveryStep creation and properties
  - StepResult status checks
  - RecoveryReport aggregation
  - RecoveryPlan default and minimal plans
  - Stall severity classification
  - Plan recommendation
  - Recovery time estimation
  - Step skip logic
  - Recovery scoring
  - Log formatting
  - Orchestrator execution

Written by Qwen during caretaker visit 687, 2026-11-18.
"""

import pytest

from iamai.stall_recovery_orchestrator import (
    RecoveryStep,
    StepResult,
    RecoveryReport,
    RecoveryPlan,
    RecoveryOrchestrator,
    classify_stall_severity,
    recommend_plan,
    estimate_recovery_time,
    should_skip_step,
    compute_recovery_score,
    format_recovery_log,
)


# =========================================================================
# RecoveryStep
# =========================================================================

class TestRecoveryStep:
    def test_basic_creation(self):
        s = RecoveryStep("restart_writer")
        assert s.name == "restart_writer"
        assert s.required is True
        assert s.timeout_s == 30.0

    def test_optional_step(self):
        s = RecoveryStep("snapshot_state", required=False)
        assert s.required is False

    def test_with_rollback(self):
        s = RecoveryStep("clear_locks", rollback="restore_locks")
        assert s.rollback == "restore_locks"

    def test_repr(self):
        s = RecoveryStep("test_step", required=False)
        r = repr(s)
        assert "test_step" in r
        assert "False" in r


# =========================================================================
# StepResult
# =========================================================================

class TestStepResult:
    def test_ok_status(self):
        r = StepResult("step1", "ok", 0.5, "done")
        assert r.ok is True
        assert r.failed is False

    def test_failed_status(self):
        r = StepResult("step1", "failed", 0.5, "error")
        assert r.ok is False
        assert r.failed is True

    def test_skipped_status(self):
        r = StepResult("step1", "skipped", 0.0)
        assert r.ok is False
        assert r.failed is False

    def test_diagnostics(self):
        r = StepResult("step1", "ok", 0.1, diagnostics={"pid": 1234})
        assert r.diagnostics["pid"] == 1234


# =========================================================================
# RecoveryReport
# =========================================================================

class TestRecoveryReport:
    def test_empty_report(self):
        r = RecoveryReport()
        assert r.success_count == 0
        assert r.failure_count == 0
        assert r.is_complete is False
        assert r.verdict == "not_started"

    def test_add_results(self):
        r = RecoveryReport()
        r.add(StepResult("s1", "ok", 0.1))
        r.add(StepResult("s2", "failed", 0.2))
        assert r.success_count == 1
        assert r.failure_count == 1

    def test_total_duration(self):
        r = RecoveryReport()
        r.add(StepResult("s1", "ok", 0.5))
        r.add(StepResult("s2", "ok", 1.5))
        assert r.total_duration == pytest.approx(2.0)

    def test_fully_recovered(self):
        r = RecoveryReport()
        r.add(StepResult("s1", "ok", 0.1))
        r.add(StepResult("s2", "ok", 0.2))
        assert r.is_complete is True
        assert r.verdict == "fully_recovered"

    def test_partial_recovery(self):
        r = RecoveryReport()
        r.add(StepResult("s1", "ok", 0.1))
        r.add(StepResult("s2", "failed", 0.2))
        assert r.is_complete is False
        assert r.verdict == "partial_recovery"

    def test_recovered_with_skips(self):
        r = RecoveryReport()
        r.add(StepResult("s1", "ok", 0.1))
        r.add(StepResult("s2", "skipped", 0.0))
        assert r.verdict == "recovered_with_skips"

    def test_summary_structure(self):
        r = RecoveryReport()
        r.add(StepResult("s1", "ok", 0.1, "done"))
        s = r.summary()
        assert "verdict" in s
        assert "total_duration_s" in s
        assert "step_details" in s
        assert len(s["step_details"]) == 1
        assert s["step_details"][0]["name"] == "s1"


# =========================================================================
# RecoveryPlan
# =========================================================================

class TestRecoveryPlan:
    def test_default_plan(self):
        p = RecoveryPlan.default()
        assert len(p) == 8
        assert p.steps[0].name == "confirm_stall"
        assert p.steps[-1].name == "confirm_health"

    def test_minimal_plan(self):
        p = RecoveryPlan.minimal()
        assert len(p) == 2
        assert p.steps[0].name == "restart_writer"

    def test_step_names(self):
        p = RecoveryPlan.minimal()
        names = p.step_names()
        assert names == ["restart_writer", "push_recover"]

    def test_required_steps(self):
        p = RecoveryPlan.default()
        req = p.required_steps()
        # snapshot_state, drain_backlog, confirm_health are optional
        assert len(req) < len(p.steps)
        assert all(s.required for s in req)

    def test_repr(self):
        p = RecoveryPlan.default()
        assert "8 steps" in repr(p)


# =========================================================================
# classify_stall_severity
# =========================================================================

class TestClassifySeverity:
    def test_transient(self):
        assert classify_stall_severity(20.0) == "transient"

    def test_moderate(self):
        assert classify_stall_severity(120.0) == "moderate"

    def test_severe(self):
        assert classify_stall_severity(600.0) == "severe"

    def test_critical_with_consecutive(self):
        assert classify_stall_severity(600.0, consecutive_stalls=3) == "critical"

    def test_exact_boundary_low(self):
        # ratio = 75/15 = 5.0, should be moderate
        assert classify_stall_severity(75.0) == "moderate"

    def test_exact_boundary_high(self):
        # ratio = 300/15 = 20.0, should be severe
        assert classify_stall_severity(300.0) == "severe"


# =========================================================================
# recommend_plan
# =========================================================================

class TestRecommendPlan:
    def test_transient_gets_minimal(self):
        assert recommend_plan("transient") == "minimal"

    def test_moderate_gets_default(self):
        assert recommend_plan("moderate") == "default"

    def test_severe_gets_default(self):
        assert recommend_plan("severe") == "default"

    def test_critical_gets_default(self):
        assert recommend_plan("critical") == "default"


# =========================================================================
# estimate_recovery_time
# =========================================================================

class TestEstimateRecoveryTime:
    def test_minimal(self):
        assert estimate_recovery_time("minimal") == 45.0

    def test_default(self):
        assert estimate_recovery_time("default") == 210.0

    def test_unknown_fallback(self):
        assert estimate_recovery_time("custom") == 120.0


# =========================================================================
# should_skip_step
# =========================================================================

class TestShouldSkipStep:
    def test_required_never_skipped(self):
        assert should_skip_step("confirm_stall", []) is False
        assert should_skip_step("restart_writer", []) is False

    def test_optional_skipped_on_failure(self):
        prior = [StepResult("confirm_stall", "failed")]
        assert should_skip_step("snapshot_state", prior) is True

    def test_optional_not_skipped_on_success(self):
        prior = [StepResult("confirm_stall", "ok")]
        assert should_skip_step("drain_backlog", prior) is False

    def test_optional_not_skipped_empty(self):
        assert should_skip_step("snapshot_state", []) is False


# =========================================================================
# compute_recovery_score
# =========================================================================

class TestComputeRecoveryScore:
    def test_empty_report(self):
        assert compute_recovery_score(RecoveryReport()) == 0.0

    def test_all_ok(self):
        r = RecoveryReport()
        r.add(StepResult("confirm_stall", "ok", 0.1))
        r.add(StepResult("restart_writer", "ok", 0.5))
        score = compute_recovery_score(r)
        assert score == pytest.approx(1.0)

    def test_partial_success(self):
        r = RecoveryReport()
        r.add(StepResult("confirm_stall", "ok", 0.1))
        r.add(StepResult("restart_writer", "failed", 0.5))
        score = compute_recovery_score(r)
        assert 0.0 < score < 1.0

    def test_skipped_counts_half(self):
        r = RecoveryReport()
        r.add(StepResult("confirm_stall", "ok", 0.1))
        r.add(StepResult("snapshot_state", "skipped", 0.0))
        score = compute_recovery_score(r)
        # confirm_stall is required (weight 2), snapshot_state optional (weight 1)
        # earned = 2 + 0.5 = 2.5, total = 2 + 1 = 3
        assert score == pytest.approx(2.5 / 3.0)


# =========================================================================
# format_recovery_log
# =========================================================================

class TestFormatRecoveryLog:
    def test_empty_report(self):
        assert format_recovery_log(RecoveryReport()) == "no recovery executed"

    def test_with_results(self):
        r = RecoveryReport()
        r.add(StepResult("confirm_stall", "ok", 0.1, "stall confirmed"))
        log = format_recovery_log(r)
        assert "confirm_stall" in log
        assert "ok" in log
        assert "stall confirmed" in log

    def test_failed_shows_x(self):
        r = RecoveryReport()
        r.add(StepResult("restart_writer", "failed", 0.5, "timeout"))
        log = format_recovery_log(r)
        assert "✗" in log


# =========================================================================
# RecoveryOrchestrator
# =========================================================================

class TestOrchestrator:
    def test_execute_minimal(self):
        def mock_exec(step_name):
            return StepResult(step_name, "ok", 0.01, "mocked")

        orch = RecoveryOrchestrator(RecoveryPlan.minimal(), mock_exec)
        report = orch.execute()
        assert report.success_count == 2
        assert report.verdict == "fully_recovered"

    def test_execute_with_failure(self):
        def mock_exec(step_name):
            if step_name == "restart_writer":
                return StepResult(step_name, "failed", 0.01, "process died")
            return StepResult(step_name, "ok", 0.01)

        orch = RecoveryOrchestrator(RecoveryPlan.minimal(), mock_exec)
        report = orch.execute()
        assert report.failure_count == 1

    def test_on_step_complete_callback(self):
        completed = []

        def mock_exec(step_name):
            return StepResult(step_name, "ok", 0.01)

        def on_complete(result):
            completed.append(result.step_name)

        orch = RecoveryOrchestrator(
            RecoveryPlan.minimal(), mock_exec, on_step_complete=on_complete
        )
        orch.execute()
        assert len(completed) == 2

    def test_skips_optional_after_failure(self):
        """Optional steps after a required failure are skipped."""

        def mock_exec(step_name):
            if step_name == "confirm_stall":
                return StepResult(step_name, "failed", 0.01, "no stall")
            return StepResult(step_name, "ok", 0.01)

        orch = RecoveryOrchestrator(RecoveryPlan.default(), mock_exec)
        report = orch.execute()
        # confirm_stall failed -> subsequent optional steps skipped
        skipped = [r for r in report.results if r.status == "skipped"]
        assert len(skipped) > 0

    def test_exception_handling(self):
        def mock_exec(step_name):
            raise RuntimeError("unexpected error")

        orch = RecoveryOrchestrator(RecoveryPlan.minimal(), mock_exec)
        report = orch.execute()
        assert report.failure_count >= 1
        failed = [r for r in report.results if r.failed]
        assert "unexpected error" in failed[0].message
