"""Tests for iamai.intervention_tracker — measuring intervention effectiveness.

Each test constructs intervention and failure sequences with known
timing patterns and verifies outcomes and metrics are computed
correctly.  No file I/O needed — all timestamps are synthetic.
"""

import pytest

from iamai.intervention_tracker import (
    DEFAULT_TREATMENT_MAP,
    Failure,
    Intervention,
    InterventionOutcome,
    InterventionTracker,
    intervention_report,
)


# --- helpers ---


def _make_tracker(interventions=None, failures=None, **kwargs):
    """Build a tracker pre-loaded with events."""
    t = InterventionTracker(**kwargs)
    if interventions:
        for kind, ts, target in interventions:
            t.record_intervention(kind, ts, target)
    if failures:
        for kind, ts, target in failures:
            t.record_failure(kind, ts, target)
    return t


# --- Intervention dataclass ---


class TestIntervention:
    def test_frozen(self):
        iv = Intervention(kind="writer_restart", timestamp=100.0, target="w1")
        with pytest.raises(AttributeError):
            iv.timestamp = 200.0

    def test_negative_timestamp_rejected(self):
        with pytest.raises(ValueError):
            Intervention(kind="writer_restart", timestamp=-1.0, target="w1")

    def test_empty_kind_rejected(self):
        with pytest.raises(ValueError):
            Intervention(kind="", timestamp=100.0, target="w1")

    def test_empty_target_rejected(self):
        with pytest.raises(ValueError):
            Intervention(kind="writer_restart", timestamp=100.0, target="")

    def test_valid_creation(self):
        iv = Intervention(kind="lock_clear", timestamp=50.0, target="batch", note="stale lock")
        assert iv.kind == "lock_clear"
        assert iv.timestamp == 50.0
        assert iv.target == "batch"
        assert iv.note == "stale lock"


# --- Failure dataclass ---


class TestFailure:
    def test_frozen(self):
        f = Failure(kind="writer_stall", timestamp=100.0, target="w1")
        with pytest.raises(AttributeError):
            f.kind = "other"

    def test_negative_timestamp_rejected(self):
        with pytest.raises(ValueError):
            Failure(kind="writer_stall", timestamp=-1.0, target="w1")

    def test_empty_kind_rejected(self):
        with pytest.raises(ValueError):
            Failure(kind="", timestamp=100.0, target="w1")

    def test_valid_creation(self):
        f = Failure(kind="push_failed", timestamp=200.0, target="batch")
        assert f.kind == "push_failed"
        assert f.timestamp == 200.0


# --- recording ---


class TestRecording:
    def test_empty_tracker(self):
        t = InterventionTracker()
        assert t.intervention_count == 0
        assert t.failure_count == 0

    def test_record_single_intervention(self):
        t = InterventionTracker()
        iv = t.record_intervention("writer_restart", 100.0, "w1")
        assert t.intervention_count == 1
        assert iv.kind == "writer_restart"

    def test_record_single_failure(self):
        t = InterventionTracker()
        f = t.record_failure("writer_stall", 100.0, "w1")
        assert t.failure_count == 1
        assert f.kind == "writer_stall"

    def test_batch_record(self):
        t = InterventionTracker()
        t.record_interventions([
            ("writer_restart", 100.0, "w1"),
            ("lock_clear", 200.0, "batch"),
            ("push_retry", 300.0, "push"),
        ])
        assert t.intervention_count == 3

    def test_record_preserves_order(self):
        """Out-of-order timestamps still produce correct query results."""
        t = InterventionTracker()
        t.record_intervention("writer_restart", 300.0, "w1")
        t.record_intervention("writer_restart", 100.0, "w1")
        ivs = t.interventions_for("writer_restart")
        assert ivs[0].timestamp == 100.0
        assert ivs[1].timestamp == 300.0


# --- querying ---


class TestQuerying:
    def test_interventions_for_kind(self):
        t = _make_tracker(interventions=[
            ("writer_restart", 100.0, "w1"),
            ("lock_clear", 200.0, "batch"),
            ("writer_restart", 300.0, "w1"),
        ])
        ivs = t.interventions_for("writer_restart")
        assert len(ivs) == 2

    def test_interventions_for_kind_and_target(self):
        t = _make_tracker(interventions=[
            ("writer_restart", 100.0, "w1"),
            ("writer_restart", 200.0, "w2"),
            ("writer_restart", 300.0, "w1"),
        ])
        ivs = t.interventions_for("writer_restart", target="w1")
        assert len(ivs) == 2
        assert all(iv.target == "w1" for iv in ivs)

    def test_interventions_for_no_match(self):
        t = _make_tracker(interventions=[
            ("writer_restart", 100.0, "w1"),
        ])
        assert t.interventions_for("nonexistent") == []

    def test_failures_for_kind(self):
        t = _make_tracker(failures=[
            ("writer_stall", 100.0, "w1"),
            ("push_failed", 200.0, "batch"),
            ("writer_stall", 300.0, "w1"),
        ])
        fs = t.failures_for("writer_stall")
        assert len(fs) == 2

    def test_failures_for_with_target(self):
        t = _make_tracker(failures=[
            ("writer_stall", 100.0, "w1"),
            ("writer_stall", 200.0, "w2"),
        ])
        fs = t.failures_for("writer_stall", target="w1")
        assert len(fs) == 1


# --- outcome computation ---


class TestOutcome:
    def test_no_relapse(self):
        """Intervention with no matching failure → cured."""
        t = _make_tracker(
            interventions=[("writer_restart", 100.0, "w1")],
            failures=[],
        )
        outcome = t.last_outcome("writer_restart")
        assert outcome is not None
        assert outcome.relapsed is False
        assert outcome.relapse_window is None

    def test_relapse_within_window(self):
        """Failure after intervention within observation window → relapsed."""
        t = _make_tracker(
            interventions=[("writer_restart", 100.0, "w1")],
            failures=[("writer_stall", 150.0, "w1")],
            observation_window=3600.0,
        )
        outcome = t.last_outcome("writer_restart")
        assert outcome.relapsed is True
        assert outcome.relapse_window == 50.0

    def test_relapse_outside_window(self):
        """Failure beyond observation window → not a relapse."""
        t = _make_tracker(
            interventions=[("writer_restart", 100.0, "w1")],
            failures=[("writer_stall", 5000.0, "w1")],
            observation_window=3600.0,
        )
        outcome = t.last_outcome("writer_restart")
        assert outcome.relapsed is False

    def test_failure_before_intervention_ignored(self):
        """A failure that happened before the intervention is not a relapse."""
        t = _make_tracker(
            interventions=[("writer_restart", 200.0, "w1")],
            failures=[("writer_stall", 100.0, "w1")],
        )
        outcome = t.last_outcome("writer_restart")
        assert outcome.relapsed is False

    def test_wrong_target_not_relapse(self):
        """Failure on a different target is not a relapse."""
        t = _make_tracker(
            interventions=[("writer_restart", 100.0, "w1")],
            failures=[("writer_stall", 150.0, "w2")],
        )
        outcome = t.last_outcome("writer_restart")
        assert outcome.relapsed is False

    def test_wrong_failure_kind_not_relapse(self):
        """Failure of a kind not in the treatment map is not a relapse."""
        t = _make_tracker(
            interventions=[("writer_restart", 100.0, "w1")],
            failures=[("push_failed", 150.0, "w1")],
        )
        outcome = t.last_outcome("writer_restart")
        # push_failed is not in writer_restart's treatment list
        assert outcome.relapsed is False

    def test_unknown_intervention_kind_no_relapse(self):
        """An intervention kind not in treatment_map can never relapse."""
        t = _make_tracker(
            interventions=[("mystery_fix", 100.0, "w1")],
            failures=[("writer_stall", 150.0, "w1")],
        )
        outcome = t.last_outcome("mystery_fix")
        assert outcome.relapsed is False

    def test_next_intervention_tracked(self):
        """next_intervention field should show time to next same-kind intervention."""
        t = _make_tracker(
            interventions=[
                ("writer_restart", 100.0, "w1"),
                ("writer_restart", 250.0, "w1"),
            ],
        )
        outcomes = t.outcomes("writer_restart")
        assert outcomes[0].next_intervention == 150.0
        assert outcomes[1].next_intervention is None

    def test_last_outcome_returns_most_recent(self):
        t = _make_tracker(
            interventions=[
                ("writer_restart", 100.0, "w1"),
                ("writer_restart", 300.0, "w1"),
            ],
            failures=[("writer_stall", 350.0, "w1")],
        )
        outcome = t.last_outcome("writer_restart")
        assert outcome.intervention.timestamp == 300.0
        assert outcome.relapsed is True

    def test_last_outcome_no_data(self):
        t = InterventionTracker()
        assert t.last_outcome("writer_restart") is None


# --- metrics ---


class TestMetrics:
    def test_cure_rate_all_cured(self):
        t = _make_tracker(
            interventions=[
                ("writer_restart", 100.0, "w1"),
                ("writer_restart", 300.0, "w1"),
                ("writer_restart", 500.0, "w1"),
            ],
            failures=[],
        )
        assert t.cure_rate() == 1.0

    def test_cure_rate_all_relapsed(self):
        t = _make_tracker(
            interventions=[
                ("writer_restart", 100.0, "w1"),
                ("writer_restart", 300.0, "w1"),
            ],
            failures=[
                ("writer_stall", 150.0, "w1"),
                ("writer_stall", 350.0, "w1"),
            ],
        )
        assert t.cure_rate() == 0.0

    def test_cure_rate_mixed(self):
        t = _make_tracker(
            interventions=[
                ("writer_restart", 100.0, "w1"),
                ("writer_restart", 300.0, "w1"),
            ],
            failures=[("writer_stall", 150.0, "w1")],
        )
        assert t.cure_rate() == 0.5

    def test_cure_rate_empty(self):
        t = InterventionTracker()
        assert t.cure_rate() is None

    def test_cure_rate_filtered_by_kind(self):
        t = _make_tracker(
            interventions=[
                ("writer_restart", 100.0, "w1"),
                ("lock_clear", 200.0, "batch"),
            ],
            failures=[("writer_stall", 150.0, "w1")],
        )
        # writer_restart: 1 intervention, 1 relapse → cure_rate = 0
        assert t.cure_rate("writer_restart") == 0.0
        # lock_clear: 1 intervention, 0 relapses → cure_rate = 1
        assert t.cure_rate("lock_clear") == 1.0

    def test_relapse_rate_complement(self):
        t = _make_tracker(
            interventions=[("writer_restart", 100.0, "w1")],
            failures=[("writer_stall", 150.0, "w1")],
        )
        assert t.relapse_rate() == 1.0 - t.cure_rate()

    def test_mean_relapse_window(self):
        t = _make_tracker(
            interventions=[
                ("writer_restart", 100.0, "w1"),
                ("writer_restart", 300.0, "w1"),
            ],
            failures=[
                ("writer_stall", 150.0, "w1"),  # window = 50
                ("writer_stall", 400.0, "w1"),  # window = 100
            ],
        )
        mrw = t.mean_relapse_window()
        assert mrw == pytest.approx(75.0)

    def test_mean_relapse_window_no_relapses(self):
        t = _make_tracker(
            interventions=[("writer_restart", 100.0, "w1")],
            failures=[],
        )
        assert t.mean_relapse_window() is None

    def test_mean_time_to_next_intervention(self):
        t = _make_tracker(
            interventions=[
                ("writer_restart", 100.0, "w1"),
                ("writer_restart", 300.0, "w1"),
                ("writer_restart", 600.0, "w1"),
            ],
        )
        mtt = t.mean_time_to_next_intervention()
        # gaps: 200, 300 → mean = 250
        assert mtt == pytest.approx(250.0)

    def test_mean_time_to_next_no_pairs(self):
        t = _make_tracker(
            interventions=[("writer_restart", 100.0, "w1")],
        )
        assert t.mean_time_to_next_intervention() is None


# --- repeat offenders ---


class TestRepeatOffenders:
    def test_no_offenders(self):
        t = _make_tracker(
            interventions=[
                ("writer_restart", 100.0, "w1"),
                ("writer_restart", 200.0, "w1"),
            ],
        )
        assert t.repeat_offenders(min_count=3) == []

    def test_single_offender(self):
        t = _make_tracker(
            interventions=[
                ("writer_restart", 100.0, "w1"),
                ("writer_restart", 200.0, "w1"),
                ("writer_restart", 300.0, "w1"),
            ],
        )
        offenders = t.repeat_offenders(min_count=3)
        assert len(offenders) == 1
        assert offenders[0] == ("writer_restart", "w1", 3)

    def test_multiple_offenders_sorted(self):
        t = _make_tracker(
            interventions=[
                ("writer_restart", 100.0, "w1"),
                ("writer_restart", 200.0, "w1"),
                ("writer_restart", 300.0, "w1"),
                ("lock_clear", 100.0, "batch"),
                ("lock_clear", 200.0, "batch"),
                ("lock_clear", 300.0, "batch"),
                ("lock_clear", 400.0, "batch"),
            ],
        )
        offenders = t.repeat_offenders(min_count=3)
        assert len(offenders) == 2
        # sorted by count descending
        assert offenders[0][2] >= offenders[1][2]

    def test_custom_min_count(self):
        t = _make_tracker(
            interventions=[
                ("writer_restart", 100.0, "w1"),
                ("writer_restart", 200.0, "w1"),
            ],
        )
        assert t.repeat_offenders(min_count=2) == [
            ("writer_restart", "w1", 2)
        ]
        assert t.repeat_offenders(min_count=3) == []


# --- effectiveness grade ---


class TestEffectivenessGrade:
    def test_excellent(self):
        t = _make_tracker(
            interventions=[
                ("writer_restart", i * 200.0, "w1") for i in range(10)
            ],
            failures=[],  # 100% cure rate
        )
        assert t.effectiveness_grade() == "excellent"

    def test_critical(self):
        t = _make_tracker(
            interventions=[
                ("writer_restart", i * 200.0, "w1") for i in range(10)
            ],
            failures=[
                ("writer_stall", i * 200.0 + 50.0, "w1") for i in range(10)
            ],
        )
        assert t.effectiveness_grade() == "critical"

    def test_empty_returns_none(self):
        t = InterventionTracker()
        assert t.effectiveness_grade() is None

    def test_fair_grade(self):
        # 5 interventions, 2 cured, 3 relapsed → cure_rate = 0.4 → poor
        t = _make_tracker(
            interventions=[
                ("writer_restart", i * 200.0, "w1") for i in range(5)
            ],
            failures=[
                ("writer_stall", i * 200.0 + 50.0, "w1") for i in range(3)
            ],
        )
        # cure_rate = 2/5 = 0.4 → poor (0.3 ≤ 0.4 < 0.5)
        assert t.effectiveness_grade() == "poor"


# --- summary ---


class TestSummary:
    def test_summary_keys(self):
        t = _make_tracker(
            interventions=[("writer_restart", 100.0, "w1")],
            failures=[],
        )
        s = t.summary()
        expected_keys = {
            "intervention_count",
            "failure_count",
            "cure_rate",
            "relapse_rate",
            "mean_relapse_window",
            "mean_time_to_next_intervention",
            "repeat_offenders",
            "effectiveness_grade",
        }
        assert set(s.keys()) == expected_keys

    def test_summary_values(self):
        t = _make_tracker(
            interventions=[
                ("writer_restart", 100.0, "w1"),
                ("writer_restart", 300.0, "w1"),
            ],
            failures=[("writer_stall", 150.0, "w1")],
        )
        s = t.summary()
        assert s["intervention_count"] == 2
        assert s["failure_count"] == 1
        assert s["cure_rate"] == 0.5
        assert s["relapse_rate"] == 0.5


# --- report ---


class TestReport:
    def test_empty_tracker(self):
        t = InterventionTracker()
        report = intervention_report(t)
        assert "no data" in report

    def test_normal_report(self):
        t = _make_tracker(
            interventions=[
                ("writer_restart", 100.0, "w1"),
                ("writer_restart", 300.0, "w1"),
            ],
            failures=[("writer_stall", 150.0, "w1")],
        )
        report = intervention_report(t)
        assert "2 interventions" in report
        assert "cure rate" in report
        assert "50%" in report

    def test_report_includes_grade(self):
        t = _make_tracker(
            interventions=[("writer_restart", 100.0, "w1")],
            failures=[],
        )
        report = intervention_report(t)
        assert "excellent" in report


# --- custom treatment map ---


class TestCustomTreatmentMap:
    def test_custom_map(self):
        custom = {"reboot": ["crash", "hang"]}
        t = InterventionTracker(treatment_map=custom)
        t.record_intervention("reboot", 100.0, "server1")
        t.record_failure("crash", 150.0, "server1")
        outcome = t.last_outcome("reboot")
        assert outcome.relapsed is True

    def test_default_treatment_map_contents(self):
        assert "writer_restart" in DEFAULT_TREATMENT_MAP
        assert "writer_stall" in DEFAULT_TREATMENT_MAP["writer_restart"]
        assert "lock_clear" in DEFAULT_TREATMENT_MAP
        assert "ssh_key_rescue" in DEFAULT_TREATMENT_MAP


# --- edge cases ---


class TestEdgeCases:
    def test_intervention_and_failure_same_timestamp(self):
        """Failure at the exact same time as intervention is NOT a relapse
        (failure must be strictly after)."""
        t = _make_tracker(
            interventions=[("writer_restart", 100.0, "w1")],
            failures=[("writer_stall", 100.0, "w1")],
        )
        outcome = t.last_outcome("writer_restart")
        assert outcome.relapsed is False

    def test_multiple_failures_closest_wins(self):
        """The first matching failure after the intervention should be used."""
        t = _make_tracker(
            interventions=[("writer_restart", 100.0, "w1")],
            failures=[
                ("writer_stall", 120.0, "w1"),
                ("writer_stall", 180.0, "w1"),
            ],
        )
        outcome = t.last_outcome("writer_restart")
        assert outcome.relapsed is True
        assert outcome.relapse_window == 20.0

    def test_observation_window_zero(self):
        """Zero observation window means nothing can relapse."""
        t = _make_tracker(
            interventions=[("writer_restart", 100.0, "w1")],
            failures=[("writer_stall", 110.0, "w1")],
            observation_window=0.0,
        )
        outcome = t.last_outcome("writer_restart")
        assert outcome.relapsed is False

    def test_large_number_of_events(self):
        """Performance: 1000 interventions and failures should not hang."""
        t = InterventionTracker()
        for i in range(1000):
            t.record_intervention("writer_restart", float(i * 10), "w1")
            t.record_failure("writer_stall", float(i * 10 + 5), "w1")
        assert t.intervention_count == 1000
        assert t.failure_count == 1000
        # Should complete without timeout
        s = t.summary()
        assert s["intervention_count"] == 1000
