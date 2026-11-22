"""tests for stall_recovery_timer module — 48 tests."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import pytest
from datetime import datetime, timedelta, timezone

from stall_recovery_timer import (
    RecoveryPhase,
    StallRecovery,
    RecoveryMetrics,
    RecoveryTrend,
    compute_metrics,
    grade,
    build_trend,
    metrics_to_text,
    trend_to_text,
    TARGET_RECOVERY_SEC,
    GRADE_THRESHOLDS,
)


# ============================================================
# helpers
# ============================================================

BASE = datetime(2026, 11, 22, 20, 0, 0, tzinfo=timezone.utc)


def _dt(seconds: float = 0) -> datetime:
    return BASE + timedelta(seconds=seconds)


def _phase(name: str, start_s: float, end_s: float) -> RecoveryPhase:
    return RecoveryPhase(name=name, started_at=_dt(start_s), ended_at=_dt(end_s))


def _recovery(
    visit: int = 797,
    detect_s: float = 0,
    push_s: float = 120,
    phases: tuple = (),
    stall_dur: float = 0,
    notes: str = "",
) -> StallRecovery:
    return StallRecovery(
        visit_id=visit,
        stall_detected_at=_dt(detect_s),
        push_confirmed_at=_dt(push_s),
        phases=phases,
        stall_duration_sec=stall_dur,
        notes=notes,
    )


# ============================================================
# RecoveryPhase — 8 tests
# ============================================================

class TestRecoveryPhase:
    def test_duration_basic(self):
        p = _phase("detect", 0, 30)
        assert p.duration_sec == 30.0

    def test_duration_zero(self):
        p = _phase("restart", 10, 10)
        assert p.duration_sec == 0.0

    def test_duration_negative_clamped(self):
        p = _phase("commit", 50, 40)  # ended before started
        assert p.duration_sec == 0.0

    def test_is_valid_true(self):
        p = _phase("push", 0, 60)
        assert p.is_valid is True

    def test_is_valid_equal_times(self):
        p = _phase("confirm", 30, 30)
        assert p.is_valid is True

    def test_is_valid_false(self):
        p = _phase("detect", 60, 0)
        assert p.is_valid is False

    def test_frozen(self):
        p = _phase("detect", 0, 10)
        with pytest.raises(AttributeError):
            p.name = "other"

    def test_different_phase_names(self):
        for name in ["detect", "restart", "commit", "pull_merge", "push", "confirm"]:
            p = _phase(name, 0, 5)
            assert p.name == name


# ============================================================
# StallRecovery — 7 tests
# ============================================================

class TestStallRecovery:
    def test_total_recovery_sec(self):
        r = _recovery(detect_s=0, push_s=120)
        assert r.total_recovery_sec == 120.0

    def test_total_recovery_zero(self):
        r = _recovery(detect_s=50, push_s=50)
        assert r.total_recovery_sec == 0.0

    def test_total_recovery_negative_clamped(self):
        r = _recovery(detect_s=100, push_s=50)
        assert r.total_recovery_sec == 0.0

    def test_phase_count_empty(self):
        r = _recovery()
        assert r.phase_count == 0

    def test_phase_count_with_phases(self):
        phases = (_phase("detect", 0, 10), _phase("restart", 10, 30))
        r = _recovery(phases=phases)
        assert r.phase_count == 2

    def test_is_valid_true(self):
        r = _recovery(detect_s=0, push_s=60)
        assert r.is_valid is True

    def test_is_valid_false(self):
        r = _recovery(detect_s=60, push_s=0)
        assert r.is_valid is False


# ============================================================
# grade() — 6 tests
# ============================================================

class TestGrade:
    def test_grade_a(self):
        assert grade(30) == "A"

    def test_grade_a_boundary(self):
        assert grade(60) == "A"

    def test_grade_b(self):
        assert grade(120) == "B"

    def test_grade_c(self):
        assert grade(250) == "C"

    def test_grade_d(self):
        assert grade(500) == "D"

    def test_grade_f(self):
        assert grade(601) == "F"


# ============================================================
# compute_metrics — 10 tests
# ============================================================

class TestComputeMetrics:
    def test_basic(self):
        phases = (
            _phase("detect", 0, 10),
            _phase("restart", 10, 40),
            _phase("commit", 40, 60),
            _phase("push", 60, 90),
        )
        r = _recovery(detect_s=0, push_s=120, phases=phases, visit=797)
        m = compute_metrics(r)
        assert m.visit_id == 797
        assert m.total_sec == 120.0
        assert m.grade == "B"
        assert m.within_target is True

    def test_no_phases(self):
        r = _recovery(detect_s=0, push_s=60)
        m = compute_metrics(r)
        assert m.longest_phase == "none"
        assert m.longest_phase_sec == 0.0
        assert m.efficiency == 0.0  # no measured phase time, all time unaccounted

    def test_phase_breakdown(self):
        phases = (
            _phase("detect", 0, 15),
            _phase("restart", 15, 45),
        )
        r = _recovery(detect_s=0, push_s=60, phases=phases)
        m = compute_metrics(r)
        assert m.phase_breakdown["detect"] == 15.0
        assert m.phase_breakdown["restart"] == 30.0

    def test_longest_phase(self):
        phases = (
            _phase("detect", 0, 5),
            _phase("restart", 5, 55),
            _phase("commit", 55, 60),
        )
        r = _recovery(detect_s=0, push_s=65, phases=phases)
        m = compute_metrics(r)
        assert m.longest_phase == "restart"
        assert m.longest_phase_sec == 50.0

    def test_efficiency(self):
        # phase sum = 60s, total wall clock = 120s → efficiency = 0.5
        phases = (_phase("detect", 0, 30), _phase("push", 60, 90))
        r = _recovery(detect_s=0, push_s=120, phases=phases)
        m = compute_metrics(r)
        assert abs(m.efficiency - 0.5) < 0.01

    def test_efficiency_clamped_at_1(self):
        # phases extend beyond push_confirmed (edge case)
        phases = (_phase("detect", 0, 200),)
        r = _recovery(detect_s=0, push_s=100, phases=phases)
        m = compute_metrics(r)
        assert m.efficiency <= 1.0

    def test_within_target_true(self):
        r = _recovery(detect_s=0, push_s=60)
        m = compute_metrics(r)
        assert m.within_target is True

    def test_within_target_false(self):
        r = _recovery(detect_s=0, push_s=300)
        m = compute_metrics(r)
        assert m.within_target is False

    def test_summary_keys(self):
        r = _recovery(detect_s=0, push_s=120, phases=(_phase("detect", 0, 10),))
        m = compute_metrics(r)
        s = m.summary()
        expected_keys = {
            "visit_id", "total_sec", "grade", "within_target",
            "efficiency_pct", "longest_phase", "longest_phase_sec",
            "stall_duration_sec", "phase_breakdown",
        }
        assert set(s.keys()) == expected_keys

    def test_efficiency_pct(self):
        phases = (_phase("detect", 0, 60),)
        r = _recovery(detect_s=0, push_s=120, phases=phases)
        m = compute_metrics(r)
        assert m.efficiency_pct == 50.0


# ============================================================
# RecoveryTrend — 10 tests
# ============================================================

class TestRecoveryTrend:
    def test_empty(self):
        t = build_trend([])
        assert t.count == 0
        assert t.direction == "insufficient_data"
        assert t.verdict() == "no_data"

    def test_single(self):
        r = _recovery(detect_s=0, push_s=60)
        t = build_trend([r])
        assert t.count == 1
        assert t.mean_sec == 60.0
        assert t.median_sec == 60.0
        assert t.best_sec == 60.0
        assert t.worst_sec == 60.0

    def test_multiple_averages(self):
        rs = [
            _recovery(detect_s=0, push_s=60, visit=1),
            _recovery(detect_s=0, push_s=120, visit=2),
            _recovery(detect_s=0, push_s=180, visit=3),
        ]
        t = build_trend(rs)
        assert t.count == 3
        assert abs(t.mean_sec - 120.0) < 0.1
        assert t.median_sec == 120.0

    def test_best_worst(self):
        rs = [
            _recovery(detect_s=0, push_s=200, visit=1),
            _recovery(detect_s=0, push_s=30, visit=2),
            _recovery(detect_s=0, push_s=500, visit=3),
        ]
        t = build_trend(rs)
        assert t.best_sec == 30.0
        assert t.worst_sec == 500.0

    def test_target_compliance_all_met(self):
        rs = [
            _recovery(detect_s=0, push_s=60, visit=1),
            _recovery(detect_s=0, push_s=120, visit=2),
        ]
        t = build_trend(rs)
        assert t.target_compliance_pct == 100.0
        assert t.within_target_count == 2

    def test_target_compliance_mixed(self):
        rs = [
            _recovery(detect_s=0, push_s=60, visit=1),   # met
            _recovery(detect_s=0, push_s=300, visit=2),  # missed
        ]
        t = build_trend(rs)
        assert t.target_compliance_pct == 50.0

    def test_direction_improving(self):
        rs = [
            _recovery(detect_s=0, push_s=300, visit=1),
            _recovery(detect_s=0, push_s=280, visit=2),
            _recovery(detect_s=0, push_s=100, visit=3),
            _recovery(detect_s=0, push_s=60, visit=4),
        ]
        t = build_trend(rs)
        assert t.direction == "improving"

    def test_direction_worsening(self):
        rs = [
            _recovery(detect_s=0, push_s=30, visit=1),
            _recovery(detect_s=0, push_s=40, visit=2),
            _recovery(detect_s=0, push_s=300, visit=3),
            _recovery(detect_s=0, push_s=500, visit=4),
        ]
        t = build_trend(rs)
        assert t.direction == "worsening"

    def test_direction_steady(self):
        rs = [
            _recovery(detect_s=0, push_s=100, visit=1),
            _recovery(detect_s=0, push_s=105, visit=2),
            _recovery(detect_s=0, push_s=98, visit=3),
            _recovery(detect_s=0, push_s=102, visit=4),
        ]
        t = build_trend(rs)
        assert t.direction == "steady"

    def test_verdict_healthy(self):
        rs = [
            _recovery(detect_s=0, push_s=60, visit=1),
            _recovery(detect_s=0, push_s=90, visit=2),
        ]
        t = build_trend(rs)
        assert t.verdict() == "healthy"

    def test_verdict_needs_improvement(self):
        rs = [
            _recovery(detect_s=0, push_s=400, visit=1),
            _recovery(detect_s=0, push_s=500, visit=2),
        ]
        t = build_trend(rs)
        assert t.verdict() == "needs_improvement"


# ============================================================
# text output — 7 tests
# ============================================================

class TestTextOutput:
    def test_metrics_to_text_contains_grade(self):
        r = _recovery(detect_s=0, push_s=60, phases=(_phase("detect", 0, 10),))
        m = compute_metrics(r)
        text = metrics_to_text(m)
        assert "grade=A" in text

    def test_metrics_to_text_contains_visit(self):
        r = _recovery(detect_s=0, push_s=120, visit=797)
        m = compute_metrics(r)
        text = metrics_to_text(m)
        assert "visit 797" in text

    def test_metrics_to_text_target_met(self):
        r = _recovery(detect_s=0, push_s=60)
        m = compute_metrics(r)
        text = metrics_to_text(m)
        assert "target=met" in text

    def test_metrics_to_text_target_missed(self):
        r = _recovery(detect_s=0, push_s=300)
        m = compute_metrics(r)
        text = metrics_to_text(m)
        assert "target=missed" in text

    def test_trend_to_text_empty(self):
        t = build_trend([])
        text = trend_to_text(t)
        assert "no data" in text

    def test_trend_to_text_has_direction(self):
        rs = [
            _recovery(detect_s=0, push_s=100, visit=1),
            _recovery(detect_s=0, push_s=105, visit=2),
        ]
        t = build_trend(rs)
        text = trend_to_text(t)
        assert "direction=" in text

    def test_trend_to_text_has_verdict(self):
        rs = [_recovery(detect_s=0, push_s=60, visit=1)]
        t = build_trend(rs)
        text = trend_to_text(t)
        assert "verdict=" in text
