"""Tests for iamai/push_race_classifier.py — push-rejection scenario classification."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.push_race_classifier import (
    classify,
    recovery_cost,
    recovery_steps,
    scenario_summary,
)


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_clean_push(self):
        assert classify(tree_dirty=False, remote_ahead=False) == "clean_push"

    def test_dirty_tree(self):
        assert classify(tree_dirty=True, remote_ahead=False) == "dirty_tree"

    def test_remote_advanced(self):
        assert classify(tree_dirty=False, remote_ahead=True) == "remote_advanced"

    def test_diverged_dirty(self):
        assert classify(tree_dirty=True, remote_ahead=True) == "diverged_dirty"

    def test_stale_stash(self):
        assert classify(tree_dirty=False, remote_ahead=False, stash_count=3) == "stale_stash"

    def test_locked_overrides_all(self):
        assert classify(tree_dirty=False, remote_ahead=False, lock=True) == "locked"

    def test_locked_overrides_dirty(self):
        assert classify(tree_dirty=True, remote_ahead=True, lock=True) == "locked"

    def test_diverged_dirty_over_stash(self):
        """Diverged + dirty takes priority over stash count."""
        assert classify(tree_dirty=True, remote_ahead=True, stash_count=5) == "diverged_dirty"

    def test_zero_stash_is_clean(self):
        assert classify(tree_dirty=False, remote_ahead=False, stash_count=0) == "clean_push"

    def test_single_stash_entry(self):
        assert classify(tree_dirty=False, remote_ahead=False, stash_count=1) == "stale_stash"


# ---------------------------------------------------------------------------
# recovery_steps
# ---------------------------------------------------------------------------

class TestRecoverySteps:
    def test_clean_push_single_step(self):
        steps = recovery_steps("clean_push")
        assert len(steps) == 1
        assert "push" in steps[0]["action"]

    def test_dirty_tree_starts_with_kill(self):
        steps = recovery_steps("dirty_tree")
        assert steps[0]["action"] == "kill writer"

    def test_dirty_tree_ends_with_restart(self):
        steps = recovery_steps("dirty_tree")
        assert steps[-1]["action"] == "restart writer"

    def test_remote_advanced_has_rebase(self):
        steps = recovery_steps("remote_advanced")
        actions = [s["action"] for s in steps]
        assert any("rebase" in a for a in actions)

    def test_diverged_dirty_full_sequence(self):
        steps = recovery_steps("diverged_dirty")
        assert len(steps) == 5
        assert steps[0]["action"] == "kill writer"
        assert steps[-1]["action"] == "restart writer"
        # rebase must happen after commit but before push
        actions = [s["action"] for s in steps]
        commit_idx = next(i for i, a in enumerate(actions) if "commit" in a)
        rebase_idx = next(i for i, a in enumerate(actions) if "rebase" in a)
        push_idx = next(i for i, a in enumerate(actions) if "push" in a)
        assert commit_idx < rebase_idx < push_idx

    def test_stale_stash_involves_drop(self):
        steps = recovery_steps("stale_stash")
        actions = [s["action"] for s in steps]
        assert any("drop" in a for a in actions)

    def test_locked_starts_with_identify(self):
        steps = recovery_steps("locked")
        assert "identify" in steps[0]["action"]

    def test_unknown_scenario_returns_empty(self):
        assert recovery_steps("nonexistent") == []

    def test_all_steps_have_action_and_purpose(self):
        for scenario in ["clean_push", "dirty_tree", "remote_advanced",
                         "diverged_dirty", "stale_stash", "locked"]:
            for step in recovery_steps(scenario):
                assert "action" in step
                assert "purpose" in step
                assert len(step["action"]) > 0
                assert len(step["purpose"]) > 0

    def test_returns_copy_not_reference(self):
        """Modifying returned steps should not affect the template."""
        steps = recovery_steps("clean_push")
        steps.append({"action": "extra", "purpose": "test"})
        assert len(recovery_steps("clean_push")) == 1


# ---------------------------------------------------------------------------
# recovery_cost
# ---------------------------------------------------------------------------

class TestRecoveryCost:
    def test_clean_push_cost(self):
        assert recovery_cost("clean_push") == 1

    def test_dirty_tree_cost(self):
        assert recovery_cost("dirty_tree") == 4

    def test_remote_advanced_cost(self):
        assert recovery_cost("remote_advanced") == 2

    def test_diverged_dirty_cost(self):
        assert recovery_cost("diverged_dirty") == 5

    def test_stale_stash_cost(self):
        assert recovery_cost("stale_stash") == 3

    def test_locked_cost(self):
        assert recovery_cost("locked") == 3

    def test_unknown_cost(self):
        assert recovery_cost("unknown") == 0

    def test_cost_matches_steps_length(self):
        for scenario in ["clean_push", "dirty_tree", "remote_advanced",
                         "diverged_dirty", "stale_stash", "locked"]:
            assert recovery_cost(scenario) == len(recovery_steps(scenario))


# ---------------------------------------------------------------------------
# scenario_summary
# ---------------------------------------------------------------------------

class TestScenarioSummary:
    def test_clean_summary(self):
        s = scenario_summary(tree_dirty=False, remote_ahead=False)
        assert s["scenario"] == "clean_push"
        assert s["step_count"] == 1
        assert len(s["steps"]) == 1

    def test_diverged_summary(self):
        s = scenario_summary(tree_dirty=True, remote_ahead=True)
        assert s["scenario"] == "diverged_dirty"
        assert s["step_count"] == 5

    def test_inputs_recorded(self):
        s = scenario_summary(tree_dirty=True, remote_ahead=False, stash_count=2, lock=False)
        assert s["inputs"]["tree_dirty"] is True
        assert s["inputs"]["remote_ahead"] is False
        assert s["inputs"]["stash_count"] == 2
        assert s["inputs"]["lock"] is False

    def test_summary_consistent_with_classify(self):
        s = scenario_summary(tree_dirty=False, remote_ahead=True, stash_count=0)
        assert s["scenario"] == classify(tree_dirty=False, remote_ahead=True)

    def test_summary_with_lock(self):
        s = scenario_summary(tree_dirty=True, remote_ahead=True, lock=True)
        assert s["scenario"] == "locked"
        assert s["inputs"]["lock"] is True

    def test_summary_has_all_keys(self):
        s = scenario_summary(tree_dirty=False, remote_ahead=False)
        assert "scenario" in s
        assert "steps" in s
        assert "step_count" in s
        assert "inputs" in s
