"""Tests for iamai.remote_drift — local/remote branch divergence detection.

Covers: analyse_counts, reconciliation_cost, drift_score, classify_drift,
suggest_action, DriftReport properties, edge cases, boundary conditions,
weight overrides, verdict thresholds.
"""

import pytest

from iamai.remote_drift import (
    DEFAULT_BRANCH,
    DEFAULT_REMOTE,
    DEFAULT_WEIGHTS,
    HIGH_COST_BEHIND,
    LOW_COST_AHEAD,
    LOW_COST_BEHIND,
    VERDICT_THRESHOLDS,
    DriftReport,
    _drift_score,
    _reconciliation_cost,
    analyse_counts,
    classify_drift,
    is_push_safe,
    suggest_action,
)


# ---------------------------------------------------------------------------
# DriftReport properties
# ---------------------------------------------------------------------------

class TestDriftReportProperties:
    def test_synced(self):
        r = analyse_counts(0, 0)
        assert r.verdict == "synced"
        assert r.diverged is False
        assert r.push_will_succeed is True

    def test_ahead_only(self):
        r = analyse_counts(3, 0)
        assert r.verdict == "ahead"
        assert r.diverged is False
        assert r.push_will_succeed is True

    def test_behind_only(self):
        r = analyse_counts(0, 5)
        assert r.verdict == "behind"
        assert r.diverged is False
        assert r.push_will_succeed is False

    def test_diverged(self):
        r = analyse_counts(2, 3)
        assert r.verdict == "diverged"
        assert r.diverged is True
        assert r.push_will_succeed is False

    def test_summary_synced(self):
        r = analyse_counts(0, 0)
        assert "synced" in r.summary()

    def test_summary_diverged(self):
        r = analyse_counts(1, 1)
        s = r.summary()
        assert "1 ahead" in s
        assert "1 behind" in s
        assert "diverged" in s

    def test_summary_ahead_only(self):
        r = analyse_counts(5, 0)
        s = r.summary()
        assert "5 ahead" in s
        assert "behind" not in s

    def test_summary_behind_only(self):
        r = analyse_counts(0, 7)
        s = r.summary()
        assert "7 behind" in s
        assert "ahead" not in s

    def test_frozen(self):
        r = analyse_counts(1, 0)
        with pytest.raises(AttributeError):
            r.ahead_count = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# reconciliation cost
# ---------------------------------------------------------------------------

class TestReconciliationCost:
    def test_synced_is_zero(self):
        assert _reconciliation_cost(0, 0) == 0.0

    def test_ahead_only_is_cheap(self):
        cost = _reconciliation_cost(2, 0)
        assert cost < 0.25

    def test_ahead_scales_gently(self):
        c1 = _reconciliation_cost(1, 0)
        c2 = _reconciliation_cost(10, 0)
        assert c1 <= c2
        assert c2 <= 0.25  # capped

    def test_behind_few_is_cheap(self):
        cost = _reconciliation_cost(0, 2)
        assert 0.1 <= cost < 0.3

    def test_behind_many_is_expensive(self):
        cost = _reconciliation_cost(0, 20)
        assert cost > 0.5

    def test_behind_scales(self):
        costs = [_reconciliation_cost(0, n) for n in [1, 5, 10, 20]]
        assert costs == sorted(costs)  # monotonically increasing

    def test_diverged_has_baseline(self):
        cost = _reconciliation_cost(1, 1)
        assert cost >= 0.4  # baseline for diverged

    def test_diverged_scales_with_counts(self):
        c_small = _reconciliation_cost(1, 1)
        c_big = _reconciliation_cost(5, 10)
        assert c_big > c_small

    def test_diverged_capped_at_one(self):
        cost = _reconciliation_cost(50, 50)
        assert cost <= 1.0

    def test_all_bounded(self):
        for a in range(0, 30, 5):
            for b in range(0, 30, 5):
                c = _reconciliation_cost(a, b)
                assert 0.0 <= c <= 1.0


# ---------------------------------------------------------------------------
# drift score
# ---------------------------------------------------------------------------

class TestDriftScore:
    def test_synced_is_zero(self):
        assert _drift_score(0, 0, DEFAULT_WEIGHTS) == 0.0

    def test_ahead_only_moderate(self):
        score = _drift_score(5, 0, DEFAULT_WEIGHTS)
        assert 0.0 < score < 0.5

    def test_behind_scores_higher_than_ahead(self):
        """Same count behind should score higher than same count ahead."""
        s_ahead = _drift_score(5, 0, DEFAULT_WEIGHTS)
        s_behind = _drift_score(0, 5, DEFAULT_WEIGHTS)
        assert s_behind > s_ahead

    def test_diverged_scores_highest(self):
        s_ahead = _drift_score(3, 0, DEFAULT_WEIGHTS)
        s_behind = _drift_score(0, 3, DEFAULT_WEIGHTS)
        s_diverged = _drift_score(3, 3, DEFAULT_WEIGHTS)
        assert s_diverged > s_ahead
        assert s_diverged > s_behind

    def test_capped_at_one(self):
        score = _drift_score(100, 100, DEFAULT_WEIGHTS)
        assert score <= 1.0

    def test_monotonic_ahead(self):
        scores = [_drift_score(n, 0, DEFAULT_WEIGHTS) for n in range(0, 20)]
        assert scores == sorted(scores)

    def test_monotonic_behind(self):
        scores = [_drift_score(0, n, DEFAULT_WEIGHTS) for n in range(0, 20)]
        assert scores == sorted(scores)

    def test_custom_weights(self):
        """Custom weights override defaults."""
        w = {"ahead": 0.9, "behind": 0.05, "divergence": 0.05}
        s_ahead = _drift_score(10, 0, w)
        s_behind = _drift_score(0, 10, w)
        # with these weights, ahead should score higher
        assert s_ahead > s_behind

    def test_partial_weights_merge(self):
        """Partial weights are merged with defaults."""
        w = {"ahead": 0.5}
        score = _drift_score(5, 5, w)
        assert 0.0 < score <= 1.0


# ---------------------------------------------------------------------------
# classify_drift
# ---------------------------------------------------------------------------

class TestClassifyDrift:
    def test_synced_is_clean(self):
        r = analyse_counts(0, 0)
        assert classify_drift(r) == "clean"

    def test_ahead_is_clean(self):
        r = analyse_counts(5, 0)
        assert classify_drift(r) == "clean"

    def test_behind_few_is_needs_pull(self):
        r = analyse_counts(0, 3)
        assert classify_drift(r) == "needs-pull"

    def test_behind_many_is_stale(self):
        r = analyse_counts(0, HIGH_COST_BEHIND + 1)
        assert classify_drift(r) == "stale"

    def test_diverged_is_needs_rebase(self):
        r = analyse_counts(2, 3)
        assert classify_drift(r) == "needs-rebase"

    def test_diverged_but_stale(self):
        """Very far behind + diverged → stale takes priority."""
        r = analyse_counts(1, HIGH_COST_BEHIND + 5)
        assert classify_drift(r) == "stale"


# ---------------------------------------------------------------------------
# is_push_safe
# ---------------------------------------------------------------------------

class TestIsPushSafe:
    def test_synced_safe(self):
        assert is_push_safe(analyse_counts(0, 0)) is True

    def test_ahead_safe(self):
        assert is_push_safe(analyse_counts(5, 0)) is True

    def test_behind_unsafe(self):
        assert is_push_safe(analyse_counts(0, 1)) is False

    def test_diverged_unsafe(self):
        assert is_push_safe(analyse_counts(1, 1)) is False


# ---------------------------------------------------------------------------
# suggest_action
# ---------------------------------------------------------------------------

class TestSuggestAction:
    def test_synced_nothing(self):
        r = analyse_counts(0, 0)
        assert "nothing" in suggest_action(r)

    def test_ahead_push(self):
        r = analyse_counts(3, 0)
        action = suggest_action(r)
        assert "push" in action

    def test_behind_pull(self):
        r = analyse_counts(0, 3)
        action = suggest_action(r)
        assert "pull" in action and "rebase" in action

    def test_diverged_rebase(self):
        r = analyse_counts(2, 3)
        action = suggest_action(r)
        assert "rebase" in action or "fetch" in action

    def test_stale_review(self):
        r = analyse_counts(0, HIGH_COST_BEHIND + 5)
        action = suggest_action(r)
        assert "review" in action or "log" in action


# ---------------------------------------------------------------------------
# analyse_counts (pure helper)
# ---------------------------------------------------------------------------

class TestAnalyseCounts:
    def test_returns_report(self):
        r = analyse_counts(1, 2)
        assert isinstance(r, DriftReport)
        assert r.ahead_count == 1
        assert r.behind_count == 2

    def test_default_branch_and_remote(self):
        r = analyse_counts(0, 0)
        assert r.branch == DEFAULT_BRANCH
        assert r.remote == DEFAULT_REMOTE

    def test_custom_weights(self):
        r1 = analyse_counts(5, 5)
        r2 = analyse_counts(5, 5, weights={"ahead": 0.9, "behind": 0.05, "divergence": 0.05})
        # different weights → different scores
        assert r1.drift_score != r2.drift_score

    def test_scores_bounded(self):
        for a in range(0, 25, 3):
            for b in range(0, 25, 3):
                r = analyse_counts(a, b)
                assert 0.0 <= r.drift_score <= 1.0
                assert 0.0 <= r.reconciliation_cost <= 1.0


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_one_ahead_one_behind(self):
        """Minimal divergence."""
        r = analyse_counts(1, 1)
        assert r.diverged is True
        assert r.verdict == "diverged"
        assert r.push_will_succeed is False
        assert r.drift_score > 0

    def test_large_ahead_zero_behind(self):
        """Many local commits, remote unchanged."""
        r = analyse_counts(100, 0)
        assert r.verdict == "ahead"
        assert r.push_will_succeed is True
        assert r.reconciliation_cost <= 0.25

    def test_zero_ahead_large_behind(self):
        """Remote has many commits we lack."""
        r = analyse_counts(0, 100)
        assert r.verdict == "behind"
        assert r.push_will_succeed is False
        assert r.reconciliation_cost > 0.5

    def test_defaults_are_consistent(self):
        """Module constants are sensible."""
        assert DEFAULT_BRANCH
        assert DEFAULT_REMOTE
        assert LOW_COST_AHEAD > 0
        assert LOW_COST_BEHIND > 0
        assert HIGH_COST_BEHIND > LOW_COST_BEHIND
        assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)
        assert VERDICT_THRESHOLDS["synced"] < VERDICT_THRESHOLDS["diverged"]

    def test_hashes_empty_for_counts_only(self):
        """analyse_counts doesn't populate hashes (no git access)."""
        r = analyse_counts(5, 3)
        assert r.ahead_hashes == ()
        assert r.behind_hashes == ()

    def test_report_fields(self):
        """All fields are present and typed."""
        r = analyse_counts(2, 3)
        assert isinstance(r.branch, str)
        assert isinstance(r.remote, str)
        assert isinstance(r.ahead_count, int)
        assert isinstance(r.behind_count, int)
        assert isinstance(r.reconciliation_cost, float)
        assert isinstance(r.drift_score, float)
