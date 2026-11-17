"""Tests for caretaker_overnight_strategy module.

Covers:
- NightRecord construction and defaults
- OvernightPlan summary formatting
- compute_baseline: median computation, empty input, odd/even counts
- compute_recent_trend: mean of last N, edge cases
- compute_risk_score: all quadrants (low/normal/elevated/high)
- recommend_plan: verdict mapping, empty history, edge cases
- build_night_record: convenience constructor, clamping negatives
- plan_from_stall_counts: parallel list input, mismatch error
- compare_plans: escalation/de-escalation detection
"""

import pytest

from iamai.caretaker_overnight_strategy import (
    NightRecord,
    OvernightPlan,
    build_night_record,
    compare_plans,
    compute_baseline,
    compute_recent_trend,
    compute_risk_score,
    plan_from_stall_counts,
    recommend_plan,
)


# ===========================================================================
# NightRecord
# ===========================================================================

class TestNightRecord:
    def test_defaults(self):
        r = NightRecord(date="2026-11-17")
        assert r.stall_count == 0
        assert r.total_stall_seconds == 0
        assert r.checks_performed == 0
        assert r.max_gap == 0

    def test_full_construction(self):
        r = NightRecord(
            date="2026-11-17",
            stall_count=5,
            total_stall_seconds=1200,
            checks_performed=32,
            max_gap=600,
        )
        assert r.date == "2026-11-17"
        assert r.stall_count == 5
        assert r.total_stall_seconds == 1200
        assert r.checks_performed == 32
        assert r.max_gap == 600


# ===========================================================================
# OvernightPlan
# ===========================================================================

class TestOvernightPlan:
    def test_default_values(self):
        p = OvernightPlan()
        assert p.verdict == "normal"
        assert p.check_interval_minutes == 15
        assert p.risk_score == 0.5

    def test_summary_contains_key_fields(self):
        p = OvernightPlan(
            verdict="elevated",
            check_interval_minutes=10,
            risk_score=0.65,
            expected_stalls=3.2,
        )
        s = p.summary()
        assert "elevated" in s
        assert "0.65" in s
        assert "10min" in s
        assert "3.2" in s

    def test_summary_relaxed(self):
        p = OvernightPlan(verdict="relaxed", risk_score=0.1,
                          check_interval_minutes=30, expected_stalls=0.0)
        s = p.summary()
        assert "relaxed" in s
        assert "30min" in s


# ===========================================================================
# compute_baseline
# ===========================================================================

class TestComputeBaseline:
    def test_empty(self):
        assert compute_baseline([]) == 0.0

    def test_single(self):
        records = [NightRecord(date="d1", stall_count=3)]
        assert compute_baseline(records) == 3.0

    def test_odd_count(self):
        records = [
            NightRecord(date="d1", stall_count=1),
            NightRecord(date="d2", stall_count=3),
            NightRecord(date="d3", stall_count=5),
        ]
        assert compute_baseline(records) == 3.0

    def test_even_count(self):
        records = [
            NightRecord(date="d1", stall_count=1),
            NightRecord(date="d2", stall_count=3),
            NightRecord(date="d3", stall_count=5),
            NightRecord(date="d4", stall_count=7),
        ]
        assert compute_baseline(records) == 4.0

    def test_unsorted_input(self):
        records = [
            NightRecord(date="d1", stall_count=5),
            NightRecord(date="d2", stall_count=1),
            NightRecord(date="d3", stall_count=3),
        ]
        assert compute_baseline(records) == 3.0

    def test_all_zeros(self):
        records = [NightRecord(date=f"d{i}", stall_count=0) for i in range(5)]
        assert compute_baseline(records) == 0.0

    def test_all_same(self):
        records = [NightRecord(date=f"d{i}", stall_count=4) for i in range(6)]
        assert compute_baseline(records) == 4.0

    def test_large_values(self):
        records = [
            NightRecord(date="d1", stall_count=100),
            NightRecord(date="d2", stall_count=200),
            NightRecord(date="d3", stall_count=300),
        ]
        assert compute_baseline(records) == 200.0


# ===========================================================================
# compute_recent_trend
# ===========================================================================

class TestComputeRecentTrend:
    def test_empty(self):
        assert compute_recent_trend([]) == 0.0

    def test_default_recent_n(self):
        records = [
            NightRecord(date="d1", stall_count=1),
            NightRecord(date="d2", stall_count=2),
            NightRecord(date="d3", stall_count=3),
            NightRecord(date="d4", stall_count=6),
        ]
        # last 3: 2, 3, 6 → mean = 11/3
        assert abs(compute_recent_trend(records) - 11 / 3) < 1e-9

    def test_custom_recent_n(self):
        records = [
            NightRecord(date="d1", stall_count=10),
            NightRecord(date="d2", stall_count=20),
        ]
        assert compute_recent_trend(records, recent_n=1) == 20.0

    def test_recent_n_larger_than_records(self):
        records = [
            NightRecord(date="d1", stall_count=4),
            NightRecord(date="d2", stall_count=6),
        ]
        # recent_n=5 but only 2 records → mean of all = 5
        assert compute_recent_trend(records, recent_n=5) == 5.0

    def test_single_record(self):
        records = [NightRecord(date="d1", stall_count=7)]
        assert compute_recent_trend(records) == 7.0


# ===========================================================================
# compute_risk_score
# ===========================================================================

class TestComputeRiskScore:
    def test_empty_returns_default(self):
        assert compute_risk_score([]) == 0.5

    def test_all_zeros_returns_zero(self):
        records = [NightRecord(date=f"d{i}", stall_count=0) for i in range(7)]
        assert compute_risk_score(records) == 0.0

    def test_recent_equals_baseline(self):
        """When recent == baseline, risk should be ~0.5."""
        records = [NightRecord(date=f"d{i}", stall_count=4) for i in range(7)]
        risk = compute_risk_score(records)
        assert abs(risk - 0.5) < 1e-9

    def test_recent_below_baseline(self):
        """Improving trend → risk < 0.5."""
        records = [
            NightRecord(date="d1", stall_count=8),
            NightRecord(date="d2", stall_count=8),
            NightRecord(date="d3", stall_count=8),
            NightRecord(date="d4", stall_count=2),
            NightRecord(date="d5", stall_count=2),
            NightRecord(date="d6", stall_count=2),
        ]
        risk = compute_risk_score(records, recent_n=3)
        assert 0.0 <= risk < 0.5

    def test_recent_above_baseline(self):
        """Degrading trend → risk > 0.5."""
        records = [
            NightRecord(date="d1", stall_count=2),
            NightRecord(date="d2", stall_count=2),
            NightRecord(date="d3", stall_count=2),
            NightRecord(date="d4", stall_count=8),
            NightRecord(date="d5", stall_count=8),
            NightRecord(date="d6", stall_count=8),
        ]
        risk = compute_risk_score(records, recent_n=3)
        assert risk > 0.5

    def test_high_risk_clamped_at_one(self):
        """Extreme degradation → risk clamped at 1.0."""
        records = [
            NightRecord(date="d1", stall_count=1),
            NightRecord(date="d2", stall_count=1),
            NightRecord(date="d3", stall_count=1),
            NightRecord(date="d4", stall_count=1),
            NightRecord(date="d5", stall_count=100),
            NightRecord(date="d6", stall_count=100),
            NightRecord(date="d7", stall_count=100),
        ]
        risk = compute_risk_score(records, recent_n=3)
        assert risk == 1.0

    def test_no_baseline_with_recent_stalls(self):
        """Baseline=0 but recent has stalls → risk from recent/5."""
        records = [
            NightRecord(date="d1", stall_count=0),
            NightRecord(date="d2", stall_count=0),
            NightRecord(date="d3", stall_count=0),
            NightRecord(date="d4", stall_count=2),
        ]
        risk = compute_risk_score(records, recent_n=1)
        assert 0.0 < risk <= 1.0
        assert abs(risk - 2 / 5) < 1e-9

    def test_no_baseline_no_recent(self):
        records = [NightRecord(date=f"d{i}", stall_count=0) for i in range(5)]
        assert compute_risk_score(records) == 0.0

    def test_single_high_record(self):
        records = [NightRecord(date="d1", stall_count=10)]
        risk = compute_risk_score(records)
        # baseline=10, recent=10, ratio=1 → risk=0.5
        assert abs(risk - 0.5) < 1e-9

    def test_risk_monotonic_with_degradation(self):
        """Increasing recent stalls should produce increasing risk."""
        base = [NightRecord(date=f"d{i}", stall_count=4) for i in range(4)]
        risks = []
        for extra in [2, 4, 8, 16]:
            records = base + [NightRecord(date="dx", stall_count=extra)]
            risks.append(compute_risk_score(records, recent_n=1))
        for i in range(len(risks) - 1):
            assert risks[i] <= risks[i + 1]


# ===========================================================================
# recommend_plan
# ===========================================================================

class TestRecommendPlan:
    def test_empty_history(self):
        plan = recommend_plan([])
        assert plan.verdict == "normal"
        assert plan.check_interval_minutes == 15
        assert plan.history_size == 0
        assert "no history" in plan.recommendation

    def test_quiet_history_gives_relaxed(self):
        records = [
            NightRecord(date=f"d{i}", stall_count=0) for i in range(7)
        ]
        plan = recommend_plan(records)
        assert plan.verdict == "relaxed"
        assert plan.check_interval_minutes == 30

    def test_normal_history(self):
        records = [
            NightRecord(date=f"d{i}", stall_count=2) for i in range(7)
        ]
        plan = recommend_plan(records)
        assert plan.verdict == "normal"
        assert plan.check_interval_minutes == 15

    def test_elevated_history(self):
        records = [
            NightRecord(date="d1", stall_count=2),
            NightRecord(date="d2", stall_count=2),
            NightRecord(date="d3", stall_count=2),
            NightRecord(date="d4", stall_count=6),
            NightRecord(date="d5", stall_count=6),
            NightRecord(date="d6", stall_count=6),
        ]
        plan = recommend_plan(records, recent_n=3)
        assert plan.verdict in ("elevated", "high_alert")
        assert plan.check_interval_minutes <= 10

    def test_high_alert(self):
        # median([1,1,1,1,100,100,100])=1, recent(3)=100, ratio=100
        # risk = 0.5 + 0.5*min(99/2,1.0) = 1.0 → high_alert
        records = [
            NightRecord(date="d1", stall_count=1),
            NightRecord(date="d2", stall_count=1),
            NightRecord(date="d3", stall_count=1),
            NightRecord(date="d4", stall_count=1),
            NightRecord(date="d5", stall_count=100),
            NightRecord(date="d6", stall_count=100),
            NightRecord(date="d7", stall_count=100),
        ]
        plan = recommend_plan(records, recent_n=3)
        assert plan.verdict == "high_alert"
        assert plan.check_interval_minutes == 5

    def test_custom_night_hours(self):
        records = [NightRecord(date=f"d{i}", stall_count=2) for i in range(7)]
        plan = recommend_plan(records, night_hours=12.0)
        assert plan.check_interval_minutes == 15
        # 12h * 60 / 15 = 48 checks
        assert "48" in plan.recommendation

    def test_history_size_recorded(self):
        records = [NightRecord(date=f"d{i}", stall_count=1) for i in range(10)]
        plan = recommend_plan(records)
        assert plan.history_size == 10

    def test_expected_stalls_from_trend(self):
        records = [
            NightRecord(date="d1", stall_count=1),
            NightRecord(date="d2", stall_count=2),
            NightRecord(date="d3", stall_count=3),
        ]
        plan = recommend_plan(records, recent_n=3)
        assert plan.expected_stalls == 2.0

    def test_single_record(self):
        records = [NightRecord(date="d1", stall_count=5)]
        plan = recommend_plan(records)
        assert plan.history_size == 1
        assert plan.risk_score >= 0.0

    def test_verdict_interval_consistency(self):
        """Each verdict should map to its expected interval."""
        expected = {
            "relaxed": 30,
            "normal": 15,
            "elevated": 10,
            "high_alert": 5,
        }
        # Generate records for each risk level
        test_cases = [
            ([NightRecord(date=f"d{i}", stall_count=0) for i in range(7)], "relaxed"),
            ([NightRecord(date=f"d{i}", stall_count=2) for i in range(7)], "normal"),
        ]
        for records, expected_verdict in test_cases:
            plan = recommend_plan(records)
            assert plan.check_interval_minutes == expected[plan.verdict]


# ===========================================================================
# build_night_record
# ===========================================================================

class TestBuildNightRecord:
    def test_defaults(self):
        r = build_night_record("2026-11-17")
        assert r.date == "2026-11-17"
        assert r.stall_count == 0

    def test_with_values(self):
        r = build_night_record("2026-11-17", stall_count=5, max_gap=300)
        assert r.stall_count == 5
        assert r.max_gap == 300

    def test_negative_clamping(self):
        r = build_night_record(
            "2026-11-17",
            stall_count=-3,
            total_stall_seconds=-100,
            checks_performed=-5,
            max_gap=-50,
        )
        assert r.stall_count == 0
        assert r.total_stall_seconds == 0
        assert r.checks_performed == 0
        assert r.max_gap == 0


# ===========================================================================
# plan_from_stall_counts
# ===========================================================================

class TestPlanFromStallCounts:
    def test_basic(self):
        dates = ["d1", "d2", "d3"]
        counts = [0, 0, 0]
        plan = plan_from_stall_counts(dates, counts)
        assert plan.verdict == "relaxed"

    def test_mismatch_raises(self):
        with pytest.raises(ValueError, match="equal length"):
            plan_from_stall_counts(["d1", "d2"], [1])

    def test_negative_counts_clamped(self):
        dates = ["d1", "d2", "d3"]
        counts = [-1, -2, -3]
        plan = plan_from_stall_counts(dates, counts)
        assert plan.verdict == "relaxed"

    def test_empty_lists(self):
        plan = plan_from_stall_counts([], [])
        assert plan.verdict == "normal"

    def test_custom_recent_n(self):
        dates = [f"d{i}" for i in range(5)]
        counts = [0, 0, 0, 10, 10]
        plan1 = plan_from_stall_counts(dates, counts, recent_n=2)
        plan2 = plan_from_stall_counts(dates, counts, recent_n=5)
        # recent_n=2 should show higher risk than recent_n=5
        assert plan1.risk_score > plan2.risk_score


# ===========================================================================
# compare_plans
# ===========================================================================

class TestComparePlans:
    def test_escalation(self):
        old = OvernightPlan(verdict="normal", check_interval_minutes=15,
                            risk_score=0.4)
        new = OvernightPlan(verdict="elevated", check_interval_minutes=10,
                            risk_score=0.65)
        diff = compare_plans(old, new)
        assert diff["direction"] == "more_frequent"
        assert diff["interval_change_minutes"] == -5
        assert diff["escalated"] is True
        assert diff["de_escalated"] is False

    def test_de_escalation(self):
        old = OvernightPlan(verdict="elevated", check_interval_minutes=10,
                            risk_score=0.65)
        new = OvernightPlan(verdict="normal", check_interval_minutes=15,
                            risk_score=0.35)
        diff = compare_plans(old, new)
        assert diff["direction"] == "less_frequent"
        assert diff["interval_change_minutes"] == 5
        assert diff["de_escalated"] is True
        assert diff["escalated"] is False

    def test_unchanged(self):
        p = OvernightPlan(verdict="normal", check_interval_minutes=15,
                          risk_score=0.45)
        diff = compare_plans(p, p)
        assert diff["direction"] == "unchanged"
        assert diff["interval_change_minutes"] == 0
        assert diff["escalated"] is False
        assert diff["de_escalated"] is False

    def test_small_risk_change_not_escalated(self):
        old = OvernightPlan(risk_score=0.40)
        new = OvernightPlan(risk_score=0.45)
        diff = compare_plans(old, new)
        assert diff["escalated"] is False
        assert diff["de_escalated"] is False

    def test_verdict_fields_present(self):
        old = OvernightPlan(verdict="relaxed")
        new = OvernightPlan(verdict="high_alert")
        diff = compare_plans(old, new)
        assert diff["old_verdict"] == "relaxed"
        assert diff["new_verdict"] == "high_alert"


# ===========================================================================
# Integration / end-to-end
# ===========================================================================

class TestIntegration:
    def test_full_workflow(self):
        """Build records, get plan, compare with updated data."""
        history = [
            build_night_record("2026-11-10", stall_count=1, max_gap=200),
            build_night_record("2026-11-11", stall_count=2, max_gap=300),
            build_night_record("2026-11-12", stall_count=1, max_gap=250),
            build_night_record("2026-11-13", stall_count=0, max_gap=100),
            build_night_record("2026-11-14", stall_count=1, max_gap=180),
            build_night_record("2026-11-15", stall_count=0, max_gap=90),
            build_night_record("2026-11-16", stall_count=1, max_gap=200),
        ]
        plan = recommend_plan(history, recent_n=3)
        assert plan.verdict in ("relaxed", "normal")
        assert plan.history_size == 7

        # Simulate a bad night and re-evaluate
        history.append(
            build_night_record("2026-11-17", stall_count=8, max_gap=1200)
        )
        new_plan = recommend_plan(history, recent_n=3)
        diff = compare_plans(plan, new_plan)
        assert diff["risk_change"] > 0  # risk should increase

    def test_all_verdicts_reachable(self):
        """Verify each verdict can be produced."""
        verdicts_seen = set()

        # relaxed: all zeros
        p = recommend_plan([NightRecord(date=f"d{i}") for i in range(5)])
        verdicts_seen.add(p.verdict)

        # normal: steady low
        p = recommend_plan([
            NightRecord(date=f"d{i}", stall_count=2) for i in range(7)
        ])
        verdicts_seen.add(p.verdict)

        # elevated: moderate degradation (recent ~1.5x baseline)
        # baseline=median([2,2,2,2,2,3,3])=2, recent(2)=[3,3]→3, ratio=1.5
        records = [NightRecord(date=f"d{i}", stall_count=2) for i in range(5)]
        records += [NightRecord(date=f"d{i}", stall_count=3) for i in range(2)]
        p = recommend_plan(records, recent_n=2)
        verdicts_seen.add(p.verdict)

        # high_alert: extreme degradation
        # baseline=median([1,1,1,1,1,50,50])=1, recent(2)=[50,50]→50, ratio=50
        records = [NightRecord(date=f"d{i}", stall_count=1) for i in range(5)]
        records += [NightRecord(date=f"d{i}", stall_count=50) for i in range(2)]
        p = recommend_plan(records, recent_n=2)
        verdicts_seen.add(p.verdict)

        assert verdicts_seen == {"relaxed", "normal", "elevated", "high_alert"}

    def test_plan_summary_is_informative(self):
        records = [
            NightRecord(date=f"d{i}", stall_count=3) for i in range(7)
        ]
        plan = recommend_plan(records)
        s = plan.summary()
        assert "overnight plan:" in s
        assert "risk=" in s
        assert "check every" in s
