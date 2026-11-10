#!/usr/bin/env python3
"""Tests for caretaker_entropy.py — is the caretaker building or firefighting?"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import caretaker_entropy as ce


# ---------------------------------------------------------------------------
# classify_action
# ---------------------------------------------------------------------------

class TestClassifyAction:
    def test_restart_is_reactive(self):
        assert ce.classify_action("restart") == "reactive"

    def test_push_repair_is_reactive(self):
        assert ce.classify_action("push_repair") == "reactive"

    def test_backlog_drain_is_reactive(self):
        assert ce.classify_action("backlog_drain") == "reactive"

    def test_lock_cleanup_is_reactive(self):
        assert ce.classify_action("lock_cleanup") == "reactive"

    def test_ssh_rescue_is_reactive(self):
        assert ce.classify_action("ssh_rescue") == "reactive"

    def test_new_content_is_proactive(self):
        assert ce.classify_action("new_content") == "proactive"

    def test_new_module_is_proactive(self):
        assert ce.classify_action("new_module") == "proactive"

    def test_tooling_is_proactive(self):
        assert ce.classify_action("tooling") == "proactive"

    def test_analysis_is_proactive(self):
        assert ce.classify_action("analysis") == "proactive"

    def test_maintenance_is_neutral(self):
        assert ce.classify_action("maintenance") == "neutral"

    def test_unknown_action_is_neutral(self):
        assert ce.classify_action("something_completely_new") == "neutral"

    def test_empty_string_is_neutral(self):
        assert ce.classify_action("") == "neutral"

    def test_all_reactive_actions(self):
        for action in ce.REACTIVE_ACTIONS:
            assert ce.classify_action(action) == "reactive"

    def test_all_proactive_actions(self):
        for action in ce.PROACTIVE_ACTIONS:
            assert ce.classify_action(action) == "proactive"

    def test_all_neutral_actions(self):
        for action in ce.NEUTRAL_ACTIONS:
            assert ce.classify_action(action) == "neutral"


# ---------------------------------------------------------------------------
# classify_visit
# ---------------------------------------------------------------------------

class TestClassifyVisit:
    def test_empty_actions_is_mixed(self):
        assert ce.classify_visit([]) == "mixed"

    def test_single_reactive(self):
        assert ce.classify_visit(["restart"]) == "reactive"

    def test_single_proactive(self):
        assert ce.classify_visit(["new_module"]) == "proactive"

    def test_single_neutral_is_mixed(self):
        assert ce.classify_visit(["maintenance"]) == "mixed"

    def test_proactive_outweighs_single_reactive(self):
        # proactive weight=2, reactive weight=1
        # 1 proactive (2) vs 1 reactive (1) → proactive wins
        assert ce.classify_visit(["restart", "new_module"]) == "proactive"

    def test_two_reactive_outweighs_one_proactive(self):
        # 2 reactive (2) vs 1 proactive (2) → tie → mixed
        assert ce.classify_visit(
            ["restart", "push_repair", "new_content"]
        ) == "mixed"

    def test_three_reactive_beats_one_proactive(self):
        # 3 reactive (3) vs 1 proactive (2) → reactive wins
        assert ce.classify_visit(
            ["restart", "push_repair", "backlog_drain", "new_content"]
        ) == "reactive"

    def test_two_proactive_beats_two_reactive(self):
        # 2 proactive (4) vs 2 reactive (2) → proactive wins
        assert ce.classify_visit(
            ["restart", "lock_cleanup", "new_module", "analysis"]
        ) == "proactive"

    def test_all_reactive(self):
        assert ce.classify_visit(
            ["restart", "push_repair", "backlog_drain", "lock_cleanup", "ssh_rescue"]
        ) == "reactive"

    def test_all_proactive(self):
        assert ce.classify_visit(
            ["new_content", "new_module", "tooling", "analysis"]
        ) == "proactive"

    def test_only_unknowns_is_mixed(self):
        assert ce.classify_visit(["foo", "bar"]) == "mixed"

    def test_neutral_plus_reactive(self):
        # 1 reactive (1) vs 0 proactive (0) → reactive wins
        assert ce.classify_visit(["maintenance", "restart"]) == "reactive"

    def test_neutral_plus_proactive(self):
        # 0 reactive (0) vs 1 proactive (2) → proactive wins
        assert ce.classify_visit(["maintenance", "new_content"]) == "proactive"

    def test_all_neutral_is_mixed(self):
        assert ce.classify_visit(["maintenance", "maintenance"]) == "mixed"


# ---------------------------------------------------------------------------
# classify_visits
# ---------------------------------------------------------------------------

class TestClassifyVisits:
    def test_empty_list(self):
        assert ce.classify_visits([]) == []

    def test_basic_ordering(self):
        visits = [
            {"actions": ["restart"]},
            {"actions": ["new_module"]},
            {"actions": []},
        ]
        assert ce.classify_visits(visits) == ["reactive", "proactive", "mixed"]

    def test_missing_actions_key(self):
        visits = [{"id": 1}, {"id": 2, "actions": ["analysis"]}]
        assert ce.classify_visits(visits) == ["mixed", "proactive"]


# ---------------------------------------------------------------------------
# _fractions
# ---------------------------------------------------------------------------

class TestFractions:
    def test_empty(self):
        result = ce._fractions([])
        assert result == {
            "proactive_fraction": 0.0,
            "reactive_fraction": 0.0,
            "mixed_fraction": 0.0,
        }

    def test_all_proactive(self):
        result = ce._fractions(["proactive", "proactive", "proactive"])
        assert result["proactive_fraction"] == 1.0
        assert result["reactive_fraction"] == 0.0
        assert result["mixed_fraction"] == 0.0

    def test_all_reactive(self):
        result = ce._fractions(["reactive", "reactive"])
        assert result["proactive_fraction"] == 0.0
        assert result["reactive_fraction"] == 1.0

    def test_even_split(self):
        result = ce._fractions(["proactive", "reactive", "mixed", "mixed"])
        assert result["proactive_fraction"] == 0.25
        assert result["reactive_fraction"] == 0.25
        assert result["mixed_fraction"] == 0.5

    def test_fractions_sum_to_one(self):
        cls = ["proactive", "reactive", "mixed", "proactive", "reactive"]
        result = ce._fractions(cls)
        total = result["proactive_fraction"] + result["reactive_fraction"] + result["mixed_fraction"]
        assert abs(total - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# entropy_score
# ---------------------------------------------------------------------------

class TestEntropyScore:
    def test_single_proactive_visit(self):
        result = ce.entropy_score([{"actions": ["new_module"]}], window=20)
        assert result["proactive_fraction"] == 1.0
        assert result["reactive_fraction"] == 0.0
        assert result["window_size"] == 1

    def test_window_truncation(self):
        visits = [{"actions": ["restart"]}] * 30
        result = ce.entropy_score(visits, window=20)
        assert result["window_size"] == 20
        assert result["reactive_fraction"] == 1.0

    def test_window_uses_all_when_small(self):
        visits = [{"actions": ["analysis"]}] * 5
        result = ce.entropy_score(visits, window=20)
        assert result["window_size"] == 5
        assert result["proactive_fraction"] == 1.0

    def test_empty_visits(self):
        result = ce.entropy_score([], window=20)
        assert result["proactive_fraction"] == 0.0
        assert result["window_size"] == 0

    def test_mixed_window(self):
        visits = (
            [{"actions": ["restart"]}] * 10
            + [{"actions": ["new_module"]}] * 10
        )
        result = ce.entropy_score(visits, window=20)
        assert result["proactive_fraction"] == 0.5
        assert result["reactive_fraction"] == 0.5

    def test_mostly_proactive(self):
        visits = (
            [{"actions": ["new_module"]}] * 15
            + [{"actions": ["restart"]}] * 5
        )
        result = ce.entropy_score(visits, window=20)
        assert result["proactive_fraction"] == 0.75
        assert result["reactive_fraction"] == 0.25


# ---------------------------------------------------------------------------
# _linear_slope
# ---------------------------------------------------------------------------

class TestLinearSlope:
    def test_empty(self):
        assert ce._linear_slope([]) == 0.0

    def test_single_value(self):
        assert ce._linear_slope([0.5]) == 0.0

    def test_increasing(self):
        slope = ce._linear_slope([0.0, 0.5, 1.0])
        assert slope == pytest.approx(0.5)

    def test_decreasing(self):
        slope = ce._linear_slope([1.0, 0.5, 0.0])
        assert slope == pytest.approx(-0.5)

    def test_flat(self):
        slope = ce._linear_slope([0.5, 0.5, 0.5, 0.5])
        assert slope == pytest.approx(0.0)

    def test_noisy_increasing(self):
        # Generally increasing but with noise
        slope = ce._linear_slope([0.1, 0.3, 0.2, 0.5, 0.4, 0.7, 0.6, 0.9])
        assert slope > 0.0

    def test_two_points(self):
        slope = ce._linear_slope([0.0, 1.0])
        assert slope == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# entropy_trend
# ---------------------------------------------------------------------------

class TestEntropyTrend:
    def test_fewer_visits_than_window(self):
        visits = [{"actions": ["new_module"]}] * 5
        result = ce.entropy_trend(visits, window=20)
        assert result["trend_direction"] == "stable"
        assert len(result["proactive_series"]) == 1

    def test_all_reactive_is_stable(self):
        visits = [{"actions": ["restart"]}] * 40
        result = ce.entropy_trend(visits, window=20, step=5)
        assert result["trend_direction"] == "stable"
        # All values in series should be 0.0
        assert all(v == 0.0 for v in result["proactive_series"])

    def test_all_proactive_is_stable(self):
        visits = [{"actions": ["new_module"]}] * 40
        result = ce.entropy_trend(visits, window=20, step=5)
        assert result["trend_direction"] == "stable"
        assert all(v == 1.0 for v in result["proactive_series"])

    def test_improving_trend(self):
        # First half all reactive, second half all proactive
        visits = (
            [{"actions": ["restart"]}] * 20
            + [{"actions": ["new_module"]}] * 20
        )
        result = ce.entropy_trend(visits, window=10, step=5)
        assert result["trend_direction"] == "improving"
        assert result["trend_slope"] > 0.0

    def test_degrading_trend(self):
        # First half all proactive, second half all reactive
        visits = (
            [{"actions": ["new_module"]}] * 20
            + [{"actions": ["restart"]}] * 20
        )
        result = ce.entropy_trend(visits, window=10, step=5)
        assert result["trend_direction"] == "degrading"
        assert result["trend_slope"] < 0.0

    def test_empty_visits(self):
        result = ce.entropy_trend([], window=20)
        assert result["trend_direction"] == "stable"
        assert result["proactive_series"] == [0.0]

    def test_series_length(self):
        visits = [{"actions": ["new_module"]}] * 50
        result = ce.entropy_trend(visits, window=20, step=10)
        # Positions: 0, 10, 20, 30 → 4 windows
        assert len(result["proactive_series"]) == 4

    def test_step_one(self):
        visits = [{"actions": ["restart"]}] * 25
        result = ce.entropy_trend(visits, window=20, step=1)
        # Positions: 0..5 → 6 windows
        assert len(result["proactive_series"]) == 6


# ---------------------------------------------------------------------------
# assess_health
# ---------------------------------------------------------------------------

class TestAssessHealth:
    def test_winning_high_pf_improving(self):
        assert ce.assess_health(0.7, "improving", 20) == "winning"

    def test_winning_high_pf_stable(self):
        # pf >= 0.6 and trend not degrading → winning (stable is not degrading)
        assert ce.assess_health(0.65, "stable", 20) == "winning"

    def test_winning_boundary(self):
        assert ce.assess_health(0.6, "improving", 20) == "winning"

    def test_winning_degrading_is_treading(self):
        assert ce.assess_health(0.65, "degrading", 20) == "treading_water"

    def test_treading_water_mid_range(self):
        assert ce.assess_health(0.5, "stable", 20) == "treading_water"

    def test_treading_water_low_stable(self):
        assert ce.assess_health(0.3, "stable", 20) == "treading_water"

    def test_treading_water_low_improving(self):
        assert ce.assess_health(0.3, "improving", 20) == "treading_water"

    def test_losing(self):
        assert ce.assess_health(0.3, "degrading", 20) == "losing"

    def test_losing_at_boundary(self):
        assert ce.assess_health(0.39, "degrading", 20) == "losing"

    def test_not_losing_at_04(self):
        # 0.4 is not < 0.4 so not losing
        assert ce.assess_health(0.4, "degrading", 20) == "treading_water"

    def test_unknown_insufficient_data(self):
        assert ce.assess_health(0.8, "improving", 5, window=20) == "unknown"

    def test_unknown_at_boundary(self):
        assert ce.assess_health(0.8, "improving", 19, window=20) == "unknown"

    def test_known_at_boundary(self):
        assert ce.assess_health(0.8, "improving", 20, window=20) == "winning"

    def test_perfect_score(self):
        assert ce.assess_health(1.0, "improving", 100) == "winning"

    def test_zero_score_degrading(self):
        assert ce.assess_health(0.0, "degrading", 50) == "losing"


# ---------------------------------------------------------------------------
# entropy_class
# ---------------------------------------------------------------------------

class TestEntropyClass:
    def test_low_entropy(self):
        assert ce.entropy_class(0.8, 0.1) == "low-entropy"

    def test_low_entropy_boundary(self):
        assert ce.entropy_class(0.6, 0.3) == "low-entropy"

    def test_high_entropy(self):
        assert ce.entropy_class(0.2, 0.7) == "high-entropy"

    def test_high_entropy_boundary(self):
        assert ce.entropy_class(0.3, 0.6) == "high-entropy"

    def test_medium_entropy_middle(self):
        assert ce.entropy_class(0.4, 0.4) == "medium-entropy"

    def test_medium_entropy_low_both(self):
        assert ce.entropy_class(0.3, 0.3) == "medium-entropy"

    def test_just_below_low_entropy(self):
        # pf=0.59 < 0.6 threshold
        assert ce.entropy_class(0.59, 0.2) == "medium-entropy"

    def test_just_below_high_entropy(self):
        # rf=0.59 < 0.6 threshold
        assert ce.entropy_class(0.2, 0.59) == "medium-entropy"

    def test_zero_zero(self):
        assert ce.entropy_class(0.0, 0.0) == "medium-entropy"

    def test_one_zero(self):
        assert ce.entropy_class(1.0, 0.0) == "low-entropy"

    def test_zero_one(self):
        assert ce.entropy_class(0.0, 1.0) == "high-entropy"


# ---------------------------------------------------------------------------
# parse_actions_from_text
# ---------------------------------------------------------------------------

class TestParseActionsFromText:
    def test_empty_text(self):
        assert ce.parse_actions_from_text("") == []

    def test_restart_detection(self):
        actions = ce.parse_actions_from_text("restarted both processes")
        assert "restart" in actions

    def test_new_module_detection(self):
        actions = ce.parse_actions_from_text("added a new module with 109 tests")
        assert "new_module" in actions

    def test_new_content_detection(self):
        actions = ce.parse_actions_from_text("wrote a new note about entropy")
        assert "new_content" in actions

    def test_backlog_detection(self):
        actions = ce.parse_actions_from_text("catch-up commit for pending changes")
        assert "backlog_drain" in actions

    def test_ssh_detection(self):
        actions = ce.parse_actions_from_text("ssh key was missing, rescued it")
        assert "ssh_rescue" in actions

    def test_push_repair_detection(self):
        actions = ce.parse_actions_from_text("had to rebase onto origin/main")
        assert "push_repair" in actions

    def test_maintenance_detection(self):
        actions = ce.parse_actions_from_text("routine status check, all clear")
        assert "maintenance" in actions

    def test_multiple_actions(self):
        text = "restarted both processes and wrote a new note about entropy"
        actions = ce.parse_actions_from_text(text)
        assert "restart" in actions
        assert "new_content" in actions

    def test_case_insensitive(self):
        actions = ce.parse_actions_from_text("RESTARTED the process")
        assert "restart" in actions

    def test_no_duplicates(self):
        text = "restarted writer, then restarted batch"
        actions = ce.parse_actions_from_text(text)
        assert actions.count("restart") == 1

    def test_analysis_detection(self):
        actions = ce.parse_actions_from_text("did a trend analysis of recent metrics")
        assert "analysis" in actions

    def test_tooling_detection(self):
        actions = ce.parse_actions_from_text("created a new monitoring script")
        assert "tooling" in actions

    def test_lock_cleanup_detection(self):
        actions = ce.parse_actions_from_text("removed stale lock file")
        assert "lock_cleanup" in actions

    def test_complex_visit_text(self):
        text = (
            "arrived to find both processes down. restarted writer and batch, "
            "committed the backlog of 9 pending files, then wrote this note "
            "as a proactive contribution. routine status check confirmed healthy."
        )
        actions = ce.parse_actions_from_text(text)
        assert "restart" in actions
        assert "backlog_drain" in actions
        assert "new_content" in actions
        assert "maintenance" in actions


# ---------------------------------------------------------------------------
# classify_history
# ---------------------------------------------------------------------------

class TestClassifyHistory:
    def test_pre_classified_visits(self):
        history = [
            {"id": 1, "actions": ["restart"]},
            {"id": 2, "actions": ["new_module"]},
        ]
        result = ce.classify_history(history)
        assert result[0]["classification"] == "reactive"
        assert result[1]["classification"] == "proactive"

    def test_text_based_classification(self):
        history = [
            {"id": 1, "text": "restarted both processes"},
            {"id": 2, "text": "added a new module with tests"},
        ]
        result = ce.classify_history(history)
        assert result[0]["classification"] == "reactive"
        assert result[1]["classification"] == "proactive"

    def test_actions_key_takes_priority(self):
        history = [
            {
                "id": 1,
                "actions": ["new_module"],
                "text": "restarted both processes",
            },
        ]
        result = ce.classify_history(history)
        # actions key exists and is non-empty, so it's used
        assert result[0]["classification"] == "proactive"

    def test_empty_actions_falls_back_to_text(self):
        history = [
            {"id": 1, "actions": [], "text": "restarted both processes"},
        ]
        result = ce.classify_history(history)
        assert result[0]["classification"] == "reactive"

    def test_original_dicts_preserved(self):
        history = [{"id": 1, "actions": ["restart"]}]
        result = ce.classify_history(history)
        # Original dict not mutated
        assert "classification" not in history[0]
        assert "classification" in result[0]

    def test_custom_text_key(self):
        history = [{"id": 1, "note": "restarted processes"}]
        result = ce.classify_history(history, text_key="note")
        assert result[0]["classification"] == "reactive"

    def test_empty_history(self):
        assert ce.classify_history([]) == []


# ---------------------------------------------------------------------------
# entropy_report (integration)
# ---------------------------------------------------------------------------

class TestEntropyReport:
    def test_all_proactive_history(self):
        visits = [{"actions": ["new_module"]}] * 25
        r = ce.entropy_report(visits, window=20)
        assert r["health"] == "winning"
        assert r["proactive_fraction"] == 1.0
        assert r["entropy_class"] == "low-entropy"

    def test_all_reactive_history(self):
        # All-reactive with flat trend → treading_water (not degrading,
        # just stuck). "losing" requires trend actually getting worse.
        visits = [{"actions": ["restart"]}] * 25
        r = ce.entropy_report(visits, window=20)
        assert r["health"] == "treading_water"
        assert r["proactive_fraction"] == 0.0
        assert r["entropy_class"] == "high-entropy"

    def test_mixed_history(self):
        visits = (
            [{"actions": ["restart"]}] * 10
            + [{"actions": ["new_module"]}] * 15
        )
        r = ce.entropy_report(visits, window=20)
        assert 0.0 < r["proactive_fraction"] < 1.0

    def test_report_has_all_keys(self):
        visits = [{"actions": ["new_module"]}] * 25
        r = ce.entropy_report(visits, window=20)
        expected_keys = {
            "proactive_fraction",
            "reactive_fraction",
            "mixed_fraction",
            "window_size",
            "trend_direction",
            "trend_slope",
            "proactive_series",
            "health",
            "entropy_class",
        }
        assert set(r.keys()) == expected_keys

    def test_insufficient_data_health_unknown(self):
        visits = [{"actions": ["new_module"]}] * 5
        r = ce.entropy_report(visits, window=20)
        assert r["health"] == "unknown"

    def test_empty_visits(self):
        r = ce.entropy_report([], window=20)
        assert r["health"] == "unknown"
        assert r["proactive_fraction"] == 0.0
        assert r["window_size"] == 0

    def test_improving_trajectory(self):
        # 10 reactive → 10 mixed → 20 proactive (enough for window=10)
        visits = (
            [{"actions": ["restart"]}] * 10
            + [{"actions": ["maintenance"]}] * 10
            + [{"actions": ["new_module"]}] * 20
        )
        r = ce.entropy_report(visits, window=10, step=5)
        assert r["proactive_fraction"] == 1.0  # last 10 are all proactive
        assert r["trend_direction"] == "improving"

    def test_degrading_trajectory(self):
        # 20 proactive → 20 reactive
        visits = (
            [{"actions": ["new_module"]}] * 20
            + [{"actions": ["restart"]}] * 20
        )
        r = ce.entropy_report(visits, window=10, step=5)
        assert r["proactive_fraction"] == 0.0  # last 10 are all reactive
        assert r["trend_direction"] == "degrading"
        assert r["health"] == "losing"

    def test_realistic_visit_pattern(self):
        """Simulate a realistic visit history: mostly reactive early,
        gradually shifting to more proactive as the system stabilizes."""
        visits = []
        # Phase 1: heavy firefighting (visits 1-10)
        for _ in range(10):
            visits.append({"actions": ["restart", "backlog_drain"]})
        # Phase 2: stabilizing (visits 11-20) — mix
        for i in range(10):
            if i % 3 == 0:
                visits.append({"actions": ["restart"]})
            else:
                visits.append({"actions": ["new_content"]})
        # Phase 3: healthy (visits 21-30) — mostly proactive
        for i in range(10):
            if i % 5 == 0:
                visits.append({"actions": ["maintenance"]})
            else:
                visits.append({"actions": ["new_module", "analysis"]})

        r = ce.entropy_report(visits, window=15, step=5)
        # Last 15 visits should be mostly proactive
        assert r["proactive_fraction"] > 0.5
        assert r["trend_direction"] == "improving"


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------

class TestConstants:
    def test_no_overlap_between_action_sets(self):
        assert ce.REACTIVE_ACTIONS & ce.PROACTIVE_ACTIONS == set()
        assert ce.REACTIVE_ACTIONS & ce.NEUTRAL_ACTIONS == set()
        assert ce.PROACTIVE_ACTIONS & ce.NEUTRAL_ACTIONS == set()

    def test_all_known_is_union(self):
        assert ce.ALL_KNOWN_ACTIONS == (
            ce.REACTIVE_ACTIONS | ce.PROACTIVE_ACTIONS | ce.NEUTRAL_ACTIONS
        )

    def test_proactive_weight_greater_than_reactive(self):
        assert ce.PROACTIVE_WEIGHT > ce.REACTIVE_WEIGHT

    def test_neutral_weight_is_zero(self):
        assert ce.NEUTRAL_WEIGHT == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_very_large_window(self):
        visits = [{"actions": ["new_module"]}] * 5
        result = ce.entropy_score(visits, window=10000)
        assert result["window_size"] == 5
        assert result["proactive_fraction"] == 1.0

    def test_window_of_one(self):
        visits = [{"actions": ["restart"]}, {"actions": ["new_module"]}]
        result = ce.entropy_score(visits, window=1)
        assert result["proactive_fraction"] == 1.0  # last visit only
        assert result["window_size"] == 1

    def test_step_larger_than_data(self):
        visits = [{"actions": ["restart"]}] * 25
        result = ce.entropy_trend(visits, window=20, step=100)
        assert len(result["proactive_series"]) == 1

    def test_negative_window_not_tested(self):
        # Negative window is not a supported use case; we just verify
        # it doesn't crash catastrophically
        visits = [{"actions": ["restart"]}] * 5
        # This is undefined behavior — just don't crash
        try:
            ce.entropy_score(visits, window=-1)
        except (ValueError, IndexError):
            pass  # acceptable

    def test_visit_with_none_actions(self):
        # Gracefully handle None in actions list
        visit = {"actions": [None, "restart"]}
        cls = ce.classify_visit(visit["actions"])
        assert cls == "reactive"
