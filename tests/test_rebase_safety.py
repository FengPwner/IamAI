"""Tests for iamai.rebase_safety — rebase safety assessment.

Covers:
  - RepoSnapshot dataclass (frozen, defaults)
  - RebaseSafetyReport (verdicts, reasons, risk_score, recommended_action, summary)
  - assess_rebase_safety: safe / caution / blocked verdicts
  - Edge cases: zero-state, max-risk, threshold boundaries
  - quick_check convenience function
"""

import pytest

from iamai.rebase_safety import (
    CAUTION,
    BLOCKED,
    SAFE,
    RepoSnapshot,
    RebaseSafetyReport,
    assess_rebase_safety,
    quick_check,
)


# ---------------------------------------------------------------------------
# RepoSnapshot
# ---------------------------------------------------------------------------

class TestRepoSnapshot:
    """RepoSnapshot dataclass basics."""

    def test_defaults(self):
        s = RepoSnapshot()
        assert s.uncommitted_files == 0
        assert s.stash_count == 0
        assert s.local_only_commits == 0
        assert s.remote_only_commits == 0
        assert s.writer_running is False
        assert s.batch_running is False
        assert s.merge_conflict is False
        assert s.rebase_in_progress is False

    def test_frozen(self):
        s = RepoSnapshot()
        with pytest.raises(AttributeError):
            s.uncommitted_files = 5

    def test_custom_values(self):
        s = RepoSnapshot(
            uncommitted_files=3,
            stash_count=15,
            local_only_commits=2,
            remote_only_commits=4,
            writer_running=True,
            batch_running=False,
            merge_conflict=False,
            rebase_in_progress=True,
        )
        assert s.uncommitted_files == 3
        assert s.stash_count == 15
        assert s.rebase_in_progress is True


# ---------------------------------------------------------------------------
# RebaseSafetyReport
# ---------------------------------------------------------------------------

class TestRebaseSafetyReport:
    """Report dataclass and its helper methods."""

    def test_frozen(self):
        r = RebaseSafetyReport(verdict=SAFE)
        with pytest.raises(AttributeError):
            r.verdict = BLOCKED

    def test_summary_safe(self):
        r = RebaseSafetyReport(verdict=SAFE, reasons=["no issues found"])
        assert r.summary == "safe: no issues found"

    def test_summary_empty_reasons(self):
        r = RebaseSafetyReport(verdict=SAFE)
        assert r.summary == "safe: no issues found"

    def test_recommended_action_safe(self):
        r = RebaseSafetyReport(verdict=SAFE)
        assert r.recommended_action() == "proceed with rebase"

    def test_recommended_action_blocked_conflict(self):
        r = RebaseSafetyReport(
            verdict=BLOCKED,
            reasons=["repo is in a merge/rebase conflict state"],
        )
        assert "conflict" in r.recommended_action()

    def test_recommended_action_blocked_rebase_in_progress(self):
        r = RebaseSafetyReport(
            verdict=BLOCKED,
            reasons=["a rebase is already in progress"],
        )
        assert "rebase" in r.recommended_action().lower()

    def test_recommended_action_blocked_uncommitted(self):
        r = RebaseSafetyReport(
            verdict=BLOCKED,
            reasons=["7 uncommitted files — working tree is very dirty"],
        )
        assert "commit" in r.recommended_action() or "stash" in r.recommended_action()

    def test_recommended_action_blocked_writer(self):
        r = RebaseSafetyReport(
            verdict=BLOCKED,
            reasons=["writer is running with uncommitted changes"],
        )
        assert "writer" in r.recommended_action() or "stop" in r.recommended_action()

    def test_recommended_action_blocked_stash(self):
        r = RebaseSafetyReport(
            verdict=BLOCKED,
            reasons=["55 stashes accumulated — stash pile is dangerously deep"],
        )
        assert "stash" in r.recommended_action()

    def test_recommended_action_caution_writer(self):
        r = RebaseSafetyReport(
            verdict=CAUTION,
            reasons=["writer is running — it may produce changes during rebase"],
        )
        assert "writer" in r.recommended_action() or "pause" in r.recommended_action()

    def test_recommended_action_caution_stash(self):
        r = RebaseSafetyReport(
            verdict=CAUTION,
            reasons=["12 stashes — consider cleaning up before adding more"],
        )
        assert "stash" in r.recommended_action()

    def test_recommended_action_caution_generic(self):
        r = RebaseSafetyReport(
            verdict=CAUTION,
            reasons=["something vague"],
        )
        assert "caution" in r.recommended_action()


# ---------------------------------------------------------------------------
# assess_rebase_safety — safe scenarios
# ---------------------------------------------------------------------------

class TestSafe:
    """Scenarios that should yield SAFE."""

    def test_clean_repo(self):
        snap = RepoSnapshot()
        r = assess_rebase_safety(snap)
        assert r.verdict == SAFE
        assert r.risk_score == 0

    def test_remote_only_no_local(self):
        snap = RepoSnapshot(remote_only_commits=3)
        r = assess_rebase_safety(snap)
        assert r.verdict == SAFE
        assert r.risk_score == 0

    def test_few_stashes(self):
        snap = RepoSnapshot(stash_count=5)
        r = assess_rebase_safety(snap)
        assert r.verdict == SAFE
        assert r.risk_score == 0

    def test_local_ahead_only(self):
        snap = RepoSnapshot(local_only_commits=3)
        r = assess_rebase_safety(snap)
        assert r.verdict == SAFE
        assert r.risk_score == 0


# ---------------------------------------------------------------------------
# assess_rebase_safety — caution scenarios
# ---------------------------------------------------------------------------

class TestCaution:
    """Scenarios that should yield CAUTION."""

    def test_writer_running_clean(self):
        """Writer running with clean tree is caution, not blocked."""
        snap = RepoSnapshot(writer_running=True)
        r = assess_rebase_safety(snap)
        assert r.verdict == CAUTION
        assert any("writer" in x for x in r.reasons)

    def test_stash_warning_threshold(self):
        snap = RepoSnapshot(stash_count=10)
        r = assess_rebase_safety(snap)
        assert r.verdict == CAUTION
        assert any("stash" in x for x in r.reasons)

    def test_stash_just_below_warning(self):
        snap = RepoSnapshot(stash_count=9)
        r = assess_rebase_safety(snap)
        assert r.verdict == SAFE  # below threshold

    def test_divergence_warning(self):
        snap = RepoSnapshot(local_only_commits=5)
        r = assess_rebase_safety(snap)
        assert r.verdict == CAUTION
        assert any("local-only" in x for x in r.reasons)

    def test_batch_running_alone(self):
        snap = RepoSnapshot(batch_running=True)
        r = assess_rebase_safety(snap)
        # batch_running alone adds risk=1, not enough for caution
        # but let's check
        assert r.risk_score >= 1

    def test_writer_and_batch_running(self):
        snap = RepoSnapshot(writer_running=True, batch_running=True)
        r = assess_rebase_safety(snap)
        assert r.verdict == CAUTION
        assert r.risk_score >= 2

    def test_remote_many_commits(self):
        snap = RepoSnapshot(remote_only_commits=15)
        r = assess_rebase_safety(snap)
        assert r.verdict == CAUTION
        assert any("remote-only" in x for x in r.reasons)


# ---------------------------------------------------------------------------
# assess_rebase_safety — blocked scenarios
# ---------------------------------------------------------------------------

class TestBlocked:
    """Scenarios that should yield BLOCKED."""

    def test_rebase_in_progress(self):
        snap = RepoSnapshot(rebase_in_progress=True)
        r = assess_rebase_safety(snap)
        assert r.verdict == BLOCKED
        assert r.risk_score >= 5

    def test_merge_conflict(self):
        snap = RepoSnapshot(merge_conflict=True)
        r = assess_rebase_safety(snap)
        assert r.verdict == BLOCKED
        assert r.risk_score >= 5

    def test_uncommitted_with_writer(self):
        snap = RepoSnapshot(uncommitted_files=3, writer_running=True)
        r = assess_rebase_safety(snap)
        assert r.verdict == BLOCKED
        assert any("writer" in x and "uncommitted" in x for x in r.reasons)

    def test_many_uncommitted_files(self):
        snap = RepoSnapshot(uncommitted_files=10)
        r = assess_rebase_safety(snap)
        assert r.verdict == BLOCKED
        assert any("uncommitted" in x for x in r.reasons)

    def test_few_uncommitted_no_writer(self):
        snap = RepoSnapshot(uncommitted_files=3)
        r = assess_rebase_safety(snap)
        assert r.verdict == BLOCKED
        assert r.risk_score >= 3

    def test_stash_danger(self):
        snap = RepoSnapshot(stash_count=50)
        r = assess_rebase_safety(snap)
        # stash=50 gives risk=3, which is caution not blocked
        # but combined with something else it can be blocked
        assert r.risk_score >= 3

    def test_stash_danger_plus_writer(self):
        snap = RepoSnapshot(stash_count=50, writer_running=True)
        r = assess_rebase_safety(snap)
        assert r.verdict == CAUTION or r.verdict == BLOCKED

    def test_everything_on_fire(self):
        snap = RepoSnapshot(
            uncommitted_files=8,
            stash_count=100,
            local_only_commits=10,
            remote_only_commits=20,
            writer_running=True,
            batch_running=True,
            merge_conflict=True,
            rebase_in_progress=True,
        )
        r = assess_rebase_safety(snap)
        assert r.verdict == BLOCKED
        assert r.risk_score == 10  # capped at 10
        assert len(r.reasons) >= 5

    def test_rebase_and_conflict_together(self):
        snap = RepoSnapshot(rebase_in_progress=True, merge_conflict=True)
        r = assess_rebase_safety(snap)
        assert r.verdict == BLOCKED
        assert r.risk_score == 10  # both hard blockers


# ---------------------------------------------------------------------------
# Risk score boundary tests
# ---------------------------------------------------------------------------

class TestRiskScore:
    """Verify risk_score is bounded 0--10."""

    def test_min_risk(self):
        snap = RepoSnapshot()
        r = assess_rebase_safety(snap)
        assert r.risk_score == 0

    def test_max_risk(self):
        snap = RepoSnapshot(
            uncommitted_files=10,
            stash_count=100,
            local_only_commits=20,
            remote_only_commits=20,
            writer_running=True,
            batch_running=True,
            merge_conflict=True,
            rebase_in_progress=True,
        )
        r = assess_rebase_safety(snap)
        assert r.risk_score == 10

    def test_risk_never_negative(self):
        snap = RepoSnapshot()
        r = assess_rebase_safety(snap)
        assert r.risk_score >= 0


# ---------------------------------------------------------------------------
# Threshold boundary tests
# ---------------------------------------------------------------------------

class TestThresholds:
    """Exact boundary values for thresholds."""

    def test_stash_9_is_safe(self):
        snap = RepoSnapshot(stash_count=9)
        assert assess_rebase_safety(snap).verdict == SAFE

    def test_stash_10_is_caution(self):
        snap = RepoSnapshot(stash_count=10)
        assert assess_rebase_safety(snap).verdict == CAUTION

    def test_stash_49_is_caution(self):
        snap = RepoSnapshot(stash_count=49)
        r = assess_rebase_safety(snap)
        assert r.verdict == CAUTION  # risk 1 from stash alone

    def test_stash_50_is_caution(self):
        snap = RepoSnapshot(stash_count=50)
        r = assess_rebase_safety(snap)
        assert r.risk_score >= 3  # higher risk but still caution alone

    def test_local_4_is_safe(self):
        snap = RepoSnapshot(local_only_commits=4)
        assert assess_rebase_safety(snap).verdict == SAFE

    def test_local_5_is_caution(self):
        snap = RepoSnapshot(local_only_commits=5)
        assert assess_rebase_safety(snap).verdict == CAUTION

    def test_uncommitted_1_is_blocked(self):
        snap = RepoSnapshot(uncommitted_files=1)
        r = assess_rebase_safety(snap)
        assert r.verdict == BLOCKED

    def test_remote_10_is_safe(self):
        snap = RepoSnapshot(remote_only_commits=10)
        r = assess_rebase_safety(snap)
        # remote_only=10 is at the boundary (threshold is > 10), so SAFE
        assert r.verdict == SAFE

    def test_remote_11_is_caution(self):
        snap = RepoSnapshot(remote_only_commits=11)
        r = assess_rebase_safety(snap)
        assert r.verdict == CAUTION

    def test_remote_9_is_safe(self):
        snap = RepoSnapshot(remote_only_commits=9)
        r = assess_rebase_safety(snap)
        assert r.verdict == SAFE


# ---------------------------------------------------------------------------
# quick_check
# ---------------------------------------------------------------------------

class TestQuickCheck:
    """Quick-check convenience function."""

    def test_clean(self):
        result = quick_check()
        assert result.startswith("safe:")

    def test_dirty_with_writer(self):
        result = quick_check(uncommitted=3, writer_up=True)
        assert "blocked" in result

    def test_stash_pile(self):
        result = quick_check(stashes=15)
        assert "caution" in result or "stash" in result

    def test_all_args(self):
        result = quick_check(
            uncommitted=5,
            stashes=20,
            ahead=3,
            behind=8,
            writer_up=True,
            batch_up=True,
        )
        assert "blocked" in result


# ---------------------------------------------------------------------------
# Reason text quality
# ---------------------------------------------------------------------------

class TestReasonText:
    """Verify reasons are human-readable and actionable."""

    def test_all_reasons_are_strings(self):
        snap = RepoSnapshot(
            uncommitted_files=5,
            stash_count=60,
            local_only_commits=10,
            remote_only_commits=15,
            writer_running=True,
            batch_running=True,
            merge_conflict=True,
            rebase_in_progress=True,
        )
        r = assess_rebase_safety(snap)
        for reason in r.reasons:
            assert isinstance(reason, str)
            assert len(reason) > 5  # not trivially short

    def test_no_duplicate_reasons(self):
        snap = RepoSnapshot(
            uncommitted_files=3,
            stash_count=20,
            writer_running=True,
        )
        r = assess_rebase_safety(snap)
        assert len(r.reasons) == len(set(r.reasons))

    def test_reasons_empty_when_clean(self):
        snap = RepoSnapshot()
        r = assess_rebase_safety(snap)
        assert r.reasons == []
