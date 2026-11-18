"""Tests for iamai.push_guard — pre-push divergence detection and recovery."""

import json
import pytest

from iamai.push_guard import (
    DivergenceState,
    DivergenceResult,
    RecoveryPlan,
    WRITER_MANAGED_FILES,
    detect_divergence,
    divergence_from_json,
    divergence_to_json,
    plan_recovery,
    summarise,
)


# ── helpers ──────────────────────────────────────────────────────────────

def sha(label: str) -> str:
    """Deterministic 40-char hex SHA from a label."""
    import hashlib
    return hashlib.sha1(label.encode()).hexdigest()


LOCAL = sha("local")
REMOTE = sha("remote")
BASE = sha("base")


# ═══════════════════════════════════════════════════════════════════════════
# detect_divergence
# ═══════════════════════════════════════════════════════════════════════════

class TestDetectDivergence:
    def test_clean(self):
        r = detect_divergence(LOCAL, LOCAL, LOCAL)
        assert r.state == DivergenceState.CLEAN
        assert not r.needs_recovery()

    def test_ahead(self):
        r = detect_divergence(LOCAL, BASE, BASE, local_ahead=3)
        assert r.state == DivergenceState.AHEAD
        assert not r.needs_recovery()
        assert r.local_ahead == 3

    def test_behind(self):
        r = detect_divergence(BASE, REMOTE, BASE, remote_ahead=5)
        assert r.state == DivergenceState.BEHIND
        assert r.needs_recovery()
        assert r.remote_ahead == 5

    def test_diverged(self):
        r = detect_divergence(LOCAL, REMOTE, BASE, local_ahead=2, remote_ahead=4)
        assert r.state == DivergenceState.DIVERGED
        assert r.needs_recovery()

    def test_same_sha_clean(self):
        s = sha("same")
        r = detect_divergence(s, s, s)
        assert r.state == DivergenceState.CLEAN

    def test_local_equals_base_means_behind(self):
        r = detect_divergence(BASE, REMOTE, BASE)
        assert r.state == DivergenceState.BEHIND

    def test_remote_equals_base_means_ahead(self):
        r = detect_divergence(LOCAL, BASE, BASE)
        assert r.state == DivergenceState.AHEAD

    def test_all_different_means_diverged(self):
        r = detect_divergence(sha("a"), sha("b"), sha("c"))
        assert r.state == DivergenceState.DIVERGED


class TestDivergenceResult:
    def test_needs_recovery_clean(self):
        r = DivergenceResult(DivergenceState.CLEAN, LOCAL, REMOTE, BASE)
        assert not r.needs_recovery()

    def test_needs_recovery_behind(self):
        r = DivergenceResult(DivergenceState.BEHIND, LOCAL, REMOTE, BASE)
        assert r.needs_recovery()

    def test_needs_recovery_diverged(self):
        r = DivergenceResult(DivergenceState.DIVERGED, LOCAL, REMOTE, BASE)
        assert r.needs_recovery()

    def test_needs_recovery_ahead(self):
        r = DivergenceResult(DivergenceState.AHEAD, LOCAL, REMOTE, BASE)
        assert not r.needs_recovery()

    def test_frozen(self):
        r = DivergenceResult(DivergenceState.CLEAN, LOCAL, REMOTE, BASE)
        with pytest.raises(AttributeError):
            r.state = DivergenceState.AHEAD


# ═══════════════════════════════════════════════════════════════════════════
# plan_recovery
# ═══════════════════════════════════════════════════════════════════════════

class TestPlanRecoveryClean:
    def test_clean_returns_empty_plan(self):
        div = detect_divergence(LOCAL, LOCAL, LOCAL)
        plan = plan_recovery(div)
        assert plan.is_empty()
        assert "sync" in plan.note.lower()

    def test_ahead_returns_empty_plan(self):
        div = detect_divergence(LOCAL, BASE, BASE, local_ahead=2)
        plan = plan_recovery(div)
        assert plan.is_empty()
        assert "safe" in plan.note.lower()


class TestPlanRecoveryBehind:
    def test_behind_no_unstaged(self):
        div = detect_divergence(BASE, REMOTE, BASE, remote_ahead=3)
        plan = plan_recovery(div)
        assert not plan.is_empty()
        assert any("pull --rebase" in s for s in plan.steps)
        assert "fast-forward" in plan.note

    def test_behind_with_unstaged(self):
        div = detect_divergence(BASE, REMOTE, BASE, remote_ahead=2)
        plan = plan_recovery(div, has_unstaged=True, unstaged_files=["src/foo.py"])
        steps_str = " ".join(plan.steps)
        assert "stash" in steps_str
        assert "pull --rebase" in steps_str

    def test_behind_with_writer_files(self):
        div = detect_divergence(BASE, REMOTE, BASE, remote_ahead=1)
        writer_file = list(WRITER_MANAGED_FILES)[0]
        plan = plan_recovery(div, has_unstaged=True, unstaged_files=[writer_file])
        steps_str = " ".join(plan.steps)
        assert f"checkout -- {writer_file}" in steps_str
        assert "pull --rebase" in steps_str


class TestPlanRecoveryDiverged:
    def test_diverged_no_unstaged(self):
        div = detect_divergence(LOCAL, REMOTE, BASE, local_ahead=2, remote_ahead=3)
        plan = plan_recovery(div)
        assert plan.risk == "medium"
        assert "diverged" in plan.note
        assert any("pull --rebase" in s for s in plan.steps)

    def test_diverged_with_unstaged(self):
        div = detect_divergence(LOCAL, REMOTE, BASE, local_ahead=1, remote_ahead=1)
        plan = plan_recovery(div, has_unstaged=True, unstaged_files=["x.py"])
        assert "stash" in " ".join(plan.steps)
        assert plan.risk == "medium"

    def test_diverged_writer_conflict(self):
        div = detect_divergence(LOCAL, REMOTE, BASE, local_ahead=1, remote_ahead=1)
        writer_files = list(WRITER_MANAGED_FILES)[:2]
        plan = plan_recovery(div, has_unstaged=True, unstaged_files=writer_files)
        steps_str = " ".join(plan.steps)
        assert "checkout --" in steps_str
        assert "pull --rebase" in steps_str

    def test_diverged_mixed_files(self):
        div = detect_divergence(LOCAL, REMOTE, BASE, local_ahead=1, remote_ahead=1)
        writer_file = list(WRITER_MANAGED_FILES)[0]
        other_file = "src/unrelated.py"
        plan = plan_recovery(
            div, has_unstaged=True, unstaged_files=[writer_file, other_file]
        )
        steps_str = " ".join(plan.steps)
        # writer file gets checkout, other file gets stash
        assert f"checkout -- {writer_file}" in steps_str
        assert "stash" in steps_str


class TestPlanRecoveryEdgeCases:
    def test_empty_unstaged_list(self):
        div = detect_divergence(BASE, REMOTE, BASE, remote_ahead=1)
        plan = plan_recovery(div, has_unstaged=True, unstaged_files=[])
        # has_unstaged=True but no actual files → stash anyway (git stash with no paths)
        assert "stash" in " ".join(plan.steps)

    def test_none_unstaged_files(self):
        div = detect_divergence(BASE, REMOTE, BASE, remote_ahead=1)
        plan = plan_recovery(div, has_unstaged=False, unstaged_files=None)
        assert any("pull --rebase" in s for s in plan.steps)

    def test_to_list(self):
        div = detect_divergence(BASE, REMOTE, BASE, remote_ahead=1)
        plan = plan_recovery(div)
        lst = plan.to_list()
        assert isinstance(lst, list)
        assert len(lst) == len(plan.steps)


# ═══════════════════════════════════════════════════════════════════════════
# summarise
# ═══════════════════════════════════════════════════════════════════════════

class TestSummarise:
    def test_clean_no_plan(self):
        div = detect_divergence(LOCAL, LOCAL, LOCAL)
        s = summarise(div)
        assert "clean" in s

    def test_ahead_with_counts(self):
        div = detect_divergence(LOCAL, BASE, BASE, local_ahead=5)
        s = summarise(div)
        assert "ahead" in s
        assert "local+5" in s

    def test_behind_with_plan(self):
        div = detect_divergence(BASE, REMOTE, BASE, remote_ahead=3)
        plan = plan_recovery(div)
        s = summarise(div, plan)
        assert "behind" in s
        assert "plan=" in s
        assert "steps" in s

    def test_diverged_shows_both_counts(self):
        div = detect_divergence(LOCAL, REMOTE, BASE, local_ahead=2, remote_ahead=7)
        s = summarise(div)
        assert "local+2" in s
        assert "remote+7" in s

    def test_no_plan_arg(self):
        div = detect_divergence(LOCAL, BASE, BASE)
        s = summarise(div)
        assert "ahead" in s


# ═══════════════════════════════════════════════════════════════════════════
# serialisation
# ═══════════════════════════════════════════════════════════════════════════

class TestSerialisation:
    def test_round_trip(self):
        original = DivergenceResult(
            state=DivergenceState.DIVERGED,
            local_sha=LOCAL,
            remote_sha=REMOTE,
            base_sha=BASE,
            local_ahead=3,
            remote_ahead=5,
        )
        raw = divergence_to_json(original)
        restored = divergence_from_json(raw)
        assert restored.state == original.state
        assert restored.local_ahead == 3
        assert restored.remote_ahead == 5
        # SHAs are truncated to 12 chars in JSON
        assert restored.local_sha == LOCAL[:12]

    def test_json_compact(self):
        r = DivergenceResult(DivergenceState.CLEAN, LOCAL, LOCAL, LOCAL)
        raw = divergence_to_json(r)
        assert " " not in raw  # compact separators

    def test_from_json_defaults(self):
        raw = json.dumps({
            "state": "ahead",
            "local_sha": "abc123def456",
            "remote_sha": "789012345678",
            "base_sha": "aaaabbbbcccc",
        })
        r = divergence_from_json(raw)
        assert r.local_ahead == 0
        assert r.remote_ahead == 0

    def test_all_states_serialise(self):
        for state in DivergenceState:
            r = DivergenceResult(state, LOCAL, REMOTE, BASE)
            raw = divergence_to_json(r)
            restored = divergence_from_json(raw)
            assert restored.state == state


# ═══════════════════════════════════════════════════════════════════════════
# WRITER_MANAGED_FILES
# ═══════════════════════════════════════════════════════════════════════════

class TestWriterManagedFiles:
    def test_is_frozenset(self):
        assert isinstance(WRITER_MANAGED_FILES, frozenset)

    def test_contains_strokes(self):
        assert "data/strokes.jsonl" in WRITER_MANAGED_FILES

    def test_contains_state(self):
        assert "data/writer_state.qwen.json" in WRITER_MANAGED_FILES

    def test_contains_devlog(self):
        assert "docs/DEVLOG.md" in WRITER_MANAGED_FILES

    def test_not_empty(self):
        assert len(WRITER_MANAGED_FILES) >= 4


# ═══════════════════════════════════════════════════════════════════════════
# integration-style scenarios
# ═══════════════════════════════════════════════════════════════════════════

class TestScenarios:
    """End-to-end scenarios mirroring real caretaker push failures."""

    def test_scenario_rejected_fetch_first(self):
        """Simulate the exact error: remote pushed between local commit and push."""
        # local committed (sha differs from base), remote also moved
        local = sha("local-commit-8421d42")
        remote = sha("remote-commit-cb51572")
        base = sha("common-ancestor-e41c873")

        div = detect_divergence(local, remote, base, local_ahead=1, remote_ahead=3)
        assert div.state == DivergenceState.DIVERGED
        assert div.needs_recovery()

        plan = plan_recovery(div, has_unstaged=True, unstaged_files=[
            "data/strokes.jsonl",
            "data/writer_state.qwen.json",
            "docs/DEVLOG.md",
        ])
        assert plan.risk == "medium"
        # writer files should be checked out, not stashed
        steps_text = " ".join(plan.steps)
        assert "checkout -- data/strokes.jsonl" in steps_text
        assert "checkout -- data/writer_state.qwen.json" in steps_text
        assert "pull --rebase" in steps_text

    def test_scenario_clean_push(self):
        """Normal case: local ahead, remote unchanged."""
        local = sha("new-commit")
        base = sha("old-remote")

        div = detect_divergence(local, base, base, local_ahead=1)
        assert div.state == DivergenceState.AHEAD
        plan = plan_recovery(div)
        assert plan.is_empty()

    def test_scenario_fast_forward_needed(self):
        """Local hasn't committed yet, remote moved."""
        base = sha("shared-base")
        remote = sha("remote-new")

        div = detect_divergence(base, remote, base, remote_ahead=5)
        assert div.state == DivergenceState.BEHIND
        plan = plan_recovery(div)
        assert "pull --rebase" in " ".join(plan.steps)
        assert plan.risk == "low"
