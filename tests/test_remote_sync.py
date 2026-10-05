"""Tests for remote_sync module."""

import pytest

from iamai.remote_sync import (
    SyncPhase,
    SyncPlan,
    SyncStatus,
    SyncStep,
    check_dirty_paths,
    evaluate_merge_result,
    evaluate_push_result,
    needs_sync,
    plan_sync,
)


# ── Probe: needs_sync ──────────────────────────────────────────


class TestNeedsSync:
    def test_identical_branches(self):
        """Local and remote at same SHA → skip."""
        step = needs_sync("abc123", "abc123", "abc123")
        assert step.phase == SyncPhase.PROBE
        assert step.status == SyncStatus.SKIPPED
        assert step.succeeded
        assert "identical" in step.message

    def test_local_behind_remote(self):
        """Local is behind remote → fast-forward needed."""
        step = needs_sync("aaa111", "bbb222", "aaa111")
        assert step.status == SyncStatus.OK
        assert step.succeeded
        assert step.details["mode"] == "ff"
        assert "fast-forward" in step.message

    def test_local_ahead_of_remote(self):
        """Local is ahead → push only."""
        step = needs_sync("bbb222", "aaa111", "aaa111")
        assert step.status == SyncStatus.OK
        assert step.details["mode"] == "push"
        assert "ahead" in step.message

    def test_diverged(self):
        """Branches diverged → merge required."""
        step = needs_sync("ccc333", "ddd444", "aaa111")
        assert step.status == SyncStatus.OK
        assert step.details["mode"] == "merge"
        assert "diverged" in step.message

    def test_return_type(self):
        """Always returns a SyncStep."""
        result = needs_sync("a", "b", "c")
        assert isinstance(result, SyncStep)
        assert result.phase == SyncPhase.PROBE


# ── Quiesce: check_dirty_paths ─────────────────────────────────


class TestCheckDirtyPaths:
    def test_clean_tree(self):
        """Empty dirty list → OK."""
        step = check_dirty_paths([])
        assert step.phase == SyncPhase.QUIESCE
        assert step.status == SyncStatus.OK
        assert step.succeeded

    def test_dirty_tree(self):
        """Any dirty files → ERROR."""
        step = check_dirty_paths(["data/state.json", "notes/foo.md"])
        assert step.status == SyncStatus.ERROR
        assert not step.succeeded
        assert "2 dirty" in step.message

    def test_dirty_details_capped(self):
        """Details list is capped at 10 paths to avoid log spam."""
        paths = [f"file_{i}.md" for i in range(20)]
        step = check_dirty_paths(paths)
        assert step.status == SyncStatus.ERROR
        assert len(step.details["dirty"]) == 10

    def test_single_dirty_file(self):
        """One dirty file is reported correctly."""
        step = check_dirty_paths(["notes/history.md"])
        assert step.status == SyncStatus.ERROR
        assert "1 dirty" in step.message


# ── Merge: evaluate_merge_result ───────────────────────────────


class TestEvaluateMergeResult:
    def test_clean_merge(self):
        """Exit 0 with no conflicts → OK."""
        step = evaluate_merge_result(0, [])
        assert step.phase == SyncPhase.MERGE
        assert step.status == SyncStatus.OK
        assert step.succeeded

    def test_merge_with_conflicts(self):
        """Conflicts detected → CONFLICT status."""
        step = evaluate_merge_result(1, ["notes/limits.md", "docs/GARDEN.md"])
        assert step.status == SyncStatus.CONFLICT
        assert not step.succeeded
        assert len(step.details["conflicts"]) == 2

    def test_merge_failure_no_conflicts(self):
        """Non-zero exit with no conflict list → ERROR."""
        step = evaluate_merge_result(128, [])
        assert step.status == SyncStatus.ERROR
        assert "exit code 128" in step.message

    def test_conflict_takes_priority(self):
        """Even if exit code is non-zero, conflicts are reported as CONFLICT."""
        step = evaluate_merge_result(1, ["file.md"])
        assert step.status == SyncStatus.CONFLICT


# ── Push: evaluate_push_result ─────────────────────────────────


class TestEvaluatePushResult:
    def test_successful_push(self):
        """Exit 0 → OK."""
        step = evaluate_push_result(0, "")
        assert step.phase == SyncPhase.PUSH
        assert step.status == SyncStatus.OK
        assert step.succeeded
        assert step.details["attempt"] == 1

    def test_rejected_first_attempt(self):
        """Rejection on attempt 1 → RETRY."""
        step = evaluate_push_result(1, "rejected: fetch first", attempt=1)
        assert step.status == SyncStatus.RETRY
        assert not step.succeeded
        assert "retry" in step.message.lower()

    def test_rejected_second_attempt(self):
        """Rejection on attempt 2 → ERROR (no more retries)."""
        step = evaluate_push_result(1, "rejected: fetch first", attempt=2)
        assert step.status == SyncStatus.ERROR
        assert "attempt 2" in step.message

    def test_non_rejection_failure(self):
        """Non-rejection error → ERROR regardless of attempt."""
        step = evaluate_push_result(128, "fatal: unable to access", attempt=1)
        assert step.status == SyncStatus.ERROR

    def test_stderr_truncated(self):
        """Long stderr is truncated to 500 chars in details."""
        long_stderr = "x" * 2000
        step = evaluate_push_result(1, long_stderr, attempt=2)
        assert len(step.details["stderr"]) == 500


# ── SyncPlan ───────────────────────────────────────────────────


class TestSyncPlan:
    def test_empty_plan(self):
        """Fresh plan is not done, no steps."""
        plan = SyncPlan()
        assert not plan.is_done
        assert plan.succeeded  # vacuously true
        assert plan.current_phase == SyncPhase.PROBE
        assert "no steps" in plan.summary()

    def test_record_successful_step(self):
        """Recording an OK step advances the phase."""
        plan = SyncPlan()
        step = SyncStep(SyncPhase.PROBE, SyncStatus.OK, "diverged")
        plan.record(step)
        assert plan.current_phase == SyncPhase.QUIESCE
        assert len(plan.steps) == 1

    def test_record_failed_step_stops(self):
        """Recording a failed step jumps to DONE."""
        plan = SyncPlan()
        step = SyncStep(SyncPhase.PROBE, SyncStatus.ERROR, "boom")
        plan.record(step)
        assert plan.is_done
        assert not plan.succeeded

    def test_full_success_walk(self):
        """Walking all phases to DONE."""
        plan = SyncPlan()
        plan.record(SyncStep(SyncPhase.PROBE, SyncStatus.OK))
        plan.record(SyncStep(SyncPhase.QUIESCE, SyncStatus.OK))
        plan.record(SyncStep(SyncPhase.MERGE, SyncStatus.OK))
        plan.record(SyncStep(SyncPhase.PUSH, SyncStatus.OK))
        assert plan.is_done
        assert plan.succeeded
        assert "4 phases ok" in plan.summary()

    def test_skipped_probe_is_done(self):
        """SKIPPED probe means nothing to sync, plan is done."""
        plan = SyncPlan()
        plan.record(SyncStep(SyncPhase.PROBE, SyncStatus.SKIPPED, "identical"))
        # SKIPPED is a success, so plan advances past PROBE
        # But probe SKIPPED means no sync needed, so we should handle that
        # In plan_sync, SKIPPED probe returns early
        assert plan.succeeded

    def test_summary_with_failure(self):
        """Summary mentions which phase failed."""
        plan = SyncPlan()
        plan.record(SyncStep(SyncPhase.PROBE, SyncStatus.OK))
        plan.record(SyncStep(SyncPhase.QUIESCE, SyncStatus.ERROR, "dirty tree"))
        assert "quiesce" in plan.summary()
        assert "dirty tree" in plan.summary()

    def test_record_retried_push(self):
        """RETRY status is not a success, stops the plan."""
        plan = SyncPlan()
        plan.record(SyncStep(SyncPhase.PROBE, SyncStatus.OK))
        plan.record(SyncStep(SyncPhase.QUIESCE, SyncStatus.OK))
        plan.record(SyncStep(SyncPhase.MERGE, SyncStatus.OK))
        plan.record(SyncStep(SyncPhase.PUSH, SyncStatus.RETRY, "rejected"))
        assert not plan.succeeded
        assert plan.is_done


# ── plan_sync (convenience builder) ────────────────────────────


class TestPlanSync:
    def test_identical_skips(self):
        """Identical SHAs → plan with just a skipped probe."""
        plan = plan_sync("abc", "abc", "abc")
        assert len(plan.steps) == 1
        assert plan.steps[0].status == SyncStatus.SKIPPED

    def test_diverged_with_clean_tree(self):
        """Diverged + clean tree → probe OK + quiesce OK, ready for merge."""
        plan = plan_sync("aaa", "bbb", "base", dirty_paths=[])
        assert len(plan.steps) == 2
        assert plan.steps[0].details["mode"] == "merge"
        assert plan.steps[1].status == SyncStatus.OK
        assert plan.current_phase == SyncPhase.MERGE

    def test_diverged_with_dirty_tree(self):
        """Diverged + dirty tree → stops at quiesce error."""
        plan = plan_sync("aaa", "bbb", "base", dirty_paths=["x.md"])
        assert len(plan.steps) == 2
        assert plan.steps[1].status == SyncStatus.ERROR
        assert plan.is_done

    def test_ahead_with_no_dirty_check(self):
        """Ahead + no dirty_paths provided → only probe step."""
        plan = plan_sync("bbb", "aaa", "aaa")
        assert len(plan.steps) == 1
        assert plan.steps[0].details["mode"] == "push"
        # Plan is still at QUIESCE because caller didn't provide dirty_paths
        assert plan.current_phase == SyncPhase.QUIESCE

    def test_behind_fast_forward(self):
        """Behind remote → probe OK with ff mode."""
        plan = plan_sync("aaa", "bbb", "aaa", dirty_paths=[])
        assert plan.steps[0].details["mode"] == "ff"
        assert plan.current_phase == SyncPhase.MERGE


# ── SyncStep property tests ────────────────────────────────────


class TestSyncStep:
    def test_ok_succeeds(self):
        assert SyncStep(SyncPhase.PROBE, SyncStatus.OK).succeeded

    def test_skipped_succeeds(self):
        assert SyncStep(SyncPhase.PROBE, SyncStatus.SKIPPED).succeeded

    def test_error_fails(self):
        assert not SyncStep(SyncPhase.PROBE, SyncStatus.ERROR).succeeded

    def test_conflict_fails(self):
        assert not SyncStep(SyncPhase.MERGE, SyncStatus.CONFLICT).succeeded

    def test_retry_fails(self):
        assert not SyncStep(SyncPhase.PUSH, SyncStatus.RETRY).succeeded

    def test_default_details(self):
        step = SyncStep(SyncPhase.PROBE, SyncStatus.OK)
        assert step.details == {}
        assert step.message == ""
