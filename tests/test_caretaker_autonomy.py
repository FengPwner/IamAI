"""Tests for iamai.caretaker_autonomy — measuring system self-sufficiency.

Each test constructs visit sequences with known intervention patterns
and verifies the autonomy metrics are computed correctly.  No file I/O
needed — all visits are synthetic.
"""

import pytest

from iamai.caretaker_autonomy import (
    AutonomyTracker,
    Visit,
    autonomy_report,
)


# --- helpers ---


def _make_tracker(visits_spec):
    """Build a tracker from a list of (time, intervened, actions) tuples."""
    tracker = AutonomyTracker()
    for time, intervened, actions in visits_spec:
        tracker.record_visit(time, intervened, actions)
    return tracker


# --- Visit dataclass ---


class TestVisit:
    def test_action_count(self):
        v = Visit(timestamp=1000.0, intervened=True, actions=("restart", "backlog_commit"))
        assert v.action_count == 2

    def test_is_routine_when_no_intervention_no_actions(self):
        v = Visit(timestamp=1000.0, intervened=False, actions=())
        assert v.is_routine is True

    def test_not_routine_when_intervened(self):
        v = Visit(timestamp=1000.0, intervened=True, actions=())
        assert v.is_routine is False

    def test_not_routine_when_has_actions(self):
        v = Visit(timestamp=1000.0, intervened=False, actions=("process_check",))
        assert v.is_routine is False

    def test_frozen(self):
        v = Visit(timestamp=1000.0, intervened=False, actions=())
        with pytest.raises(AttributeError):
            v.timestamp = 2000.0


# --- record_visit ---


class TestRecordVisit:
    def test_basic_record(self):
        t = AutonomyTracker()
        v = t.record_visit(1000.0, False, [])
        assert t.total_visits == 1
        assert v.timestamp == 1000.0
        assert v.is_routine is True

    def test_deduplicates_actions(self):
        t = AutonomyTracker()
        v = t.record_visit(1000.0, True, ["restart", "restart", "backlog_commit"])
        assert v.actions == ("backlog_commit", "restart")
        assert v.action_count == 2

    def test_sorts_actions(self):
        t = AutonomyTracker()
        v = t.record_visit(1000.0, True, ["push_fix", "restart"])
        assert v.actions == ("push_fix", "restart")

    def test_none_actions_defaults_to_empty(self):
        t = AutonomyTracker()
        v = t.record_visit(1000.0, False, None)
        assert v.actions == ()

    def test_multiple_records(self):
        t = AutonomyTracker()
        t.record_visit(1000.0, False)
        t.record_visit(2000.0, True, ["restart"])
        t.record_visit(3000.0, False)
        assert t.total_visits == 3
        assert t.intervention_visits == 1
        assert t.routine_visits == 2


# --- autonomy_score ---


class TestAutonomyScore:
    def test_no_visits_returns_one(self):
        t = AutonomyTracker()
        assert t.autonomy_score() == 1.0

    def test_single_intervention_returns_zero(self):
        t = AutonomyTracker()
        t.record_visit(1000.0, True, ["restart"])
        assert t.autonomy_score() == 0.0

    def test_single_routine_returns_one(self):
        t = AutonomyTracker()
        t.record_visit(1000.0, False)
        assert t.autonomy_score() == 1.0

    def test_all_routine_high_score(self):
        visits = [(1000 + i * 600, False, []) for i in range(10)]
        t = _make_tracker(visits)
        assert t.autonomy_score() == 1.0

    def test_all_interventions_zero_score(self):
        visits = [(1000 + i * 600, True, ["restart"]) for i in range(10)]
        t = _make_tracker(visits)
        assert t.autonomy_score() == 0.0

    def test_half_and_half_mixed_score(self):
        # Alternating: routine, intervention, routine, intervention...
        visits = []
        for i in range(10):
            intervened = i % 2 == 1
            actions = ["restart"] if intervened else []
            visits.append((1000 + i * 600, intervened, actions))
        t = _make_tracker(visits)
        score = t.autonomy_score()
        # Should be around 0.5 but weighted toward recent
        assert 0.3 < score < 0.7

    def test_recent_intervention_lowers_score(self):
        # Many routine visits, then one recent intervention
        visits = [(1000 + i * 600, False, []) for i in range(9)]
        visits.append((1000 + 9 * 600, True, ["restart"]))
        t = _make_tracker(visits)
        score = t.autonomy_score()
        # Recent intervention should pull score below 1.0
        assert score < 0.95

    def test_old_intervention_barely_affects_score(self):
        # One intervention long ago, then many routine visits
        visits = [(1000.0, True, ["restart"])]
        for i in range(1, 20):
            visits.append((1000 + i * 600, False, []))
        t = _make_tracker(visits)
        score = t.autonomy_score()
        # Old intervention should be heavily decayed
        assert score > 0.9

    def test_same_timestamp_visits(self):
        visits = [(1000.0, False, []), (1000.0, True, ["restart"])]
        t = _make_tracker(visits)
        score = t.autonomy_score()
        assert score == 0.5


# --- mean_time_between_interventions ---


class TestMTBI:
    def test_no_interventions_returns_zero(self):
        visits = [(1000 + i * 600, False, []) for i in range(5)]
        t = _make_tracker(visits)
        assert t.mean_time_between_interventions() == 0.0

    def test_single_intervention_returns_zero(self):
        t = AutonomyTracker()
        t.record_visit(1000.0, True, ["restart"])
        assert t.mean_time_between_interventions() == 0.0

    def test_two_interventions(self):
        visits = [
            (1000.0, True, ["restart"]),
            (2000.0, False, []),
            (4000.0, True, ["backlog_commit"]),
        ]
        t = _make_tracker(visits)
        assert t.mean_time_between_interventions() == 3000.0

    def test_three_interventions(self):
        visits = [
            (1000.0, True, ["restart"]),
            (3000.0, True, ["restart"]),
            (6000.0, True, ["restart"]),
        ]
        t = _make_tracker(visits)
        # Gaps: 2000, 3000 → mean 2500
        assert t.mean_time_between_interventions() == 2500.0


# --- intervention_breakdown ---


class TestInterventionBreakdown:
    def test_empty_tracker(self):
        t = AutonomyTracker()
        assert t.intervention_breakdown() == {}

    def test_counts_actions(self):
        visits = [
            (1000.0, True, ["restart"]),
            (2000.0, True, ["restart", "backlog_commit"]),
            (3000.0, True, ["restart"]),
        ]
        t = _make_tracker(visits)
        breakdown = t.intervention_breakdown()
        assert breakdown == {"restart": 3, "backlog_commit": 1}

    def test_ignores_routine_visits(self):
        visits = [
            (1000.0, False, []),
            (2000.0, True, ["push_fix"]),
            (3000.0, False, []),
        ]
        t = _make_tracker(visits)
        breakdown = t.intervention_breakdown()
        assert breakdown == {"push_fix": 1}


# --- autonomy_grade ---


class TestAutonomyGrade:
    def test_autonomous(self):
        visits = [(1000 + i * 600, False, []) for i in range(10)]
        t = _make_tracker(visits)
        assert t.autonomy_grade() == "autonomous"

    def test_critical(self):
        visits = [(1000 + i * 600, True, ["restart"]) for i in range(10)]
        t = _make_tracker(visits)
        assert t.autonomy_grade() == "critical"

    def test_grade_is_string(self):
        t = AutonomyTracker()
        assert isinstance(t.autonomy_grade(), str)


# --- longest_streak_without_intervention ---


class TestLongestStreak:
    def test_empty(self):
        t = AutonomyTracker()
        assert t.longest_streak_without_intervention() == 0

    def test_all_routine(self):
        visits = [(1000 + i * 600, False, []) for i in range(5)]
        t = _make_tracker(visits)
        assert t.longest_streak_without_intervention() == 5

    def test_all_interventions(self):
        visits = [(1000 + i * 600, True, ["restart"]) for i in range(5)]
        t = _make_tracker(visits)
        assert t.longest_streak_without_intervention() == 0

    def test_streak_in_middle(self):
        visits = [
            (1000.0, True, ["restart"]),
            (2000.0, False, []),
            (3000.0, False, []),
            (4000.0, False, []),
            (5000.0, True, ["restart"]),
            (6000.0, False, []),
            (7000.0, False, []),
        ]
        t = _make_tracker(visits)
        assert t.longest_streak_without_intervention() == 3

    def test_streak_at_end(self):
        visits = [
            (1000.0, True, ["restart"]),
            (2000.0, False, []),
            (3000.0, False, []),
        ]
        t = _make_tracker(visits)
        assert t.longest_streak_without_intervention() == 2


# --- summary ---


class TestSummary:
    def test_keys(self):
        t = _make_tracker([
            (1000.0, True, ["restart"]),
            (2000.0, False, []),
            (3000.0, False, []),
        ])
        s = t.summary()
        expected_keys = {
            "score", "grade", "total_visits", "interventions",
            "routine", "mtbi", "longest_streak", "breakdown",
        }
        assert set(s.keys()) == expected_keys

    def test_values(self):
        t = _make_tracker([
            (1000.0, True, ["restart"]),
            (2000.0, False, []),
            (3000.0, False, []),
        ])
        s = t.summary()
        assert s["total_visits"] == 3
        assert s["interventions"] == 1
        assert s["routine"] == 2
        assert s["longest_streak"] == 2
        assert isinstance(s["score"], float)
        assert isinstance(s["grade"], str)


# --- autonomy_report ---


class TestAutonomyReport:
    def test_no_visits(self):
        t = AutonomyTracker()
        report = autonomy_report(t)
        assert "no visits" in report

    def test_healthy_system(self):
        visits = [(1000 + i * 600, False, []) for i in range(10)]
        t = _make_tracker(visits)
        report = autonomy_report(t)
        assert "autonomy" in report
        assert "self-sustaining" in report

    def test_intervention_shows_actions(self):
        visits = [
            (1000.0, True, ["restart"]),
            (2000.0, True, ["restart", "backlog_commit"]),
            (3000.0, False, []),
        ]
        t = _make_tracker(visits)
        report = autonomy_report(t)
        assert "restart" in report
        assert "interventions" in report

    def test_report_is_string(self):
        t = _make_tracker([(1000.0, False, [])])
        assert isinstance(autonomy_report(t), str)

    def test_mtbi_shown_when_positive(self):
        visits = [
            (1000.0, True, ["restart"]),
            (4000.0, True, ["restart"]),
        ]
        t = _make_tracker(visits)
        report = autonomy_report(t)
        assert "mtbi" in report

    def test_mtbi_na_when_no_interventions(self):
        visits = [(1000.0, False, []), (2000.0, False, [])]
        t = _make_tracker(visits)
        report = autonomy_report(t)
        assert "mtbi n/a" in report
