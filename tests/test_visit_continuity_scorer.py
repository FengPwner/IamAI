"""Tests for iamai.visit_continuity_scorer."""

from __future__ import annotations

import pytest

from iamai.visit_continuity_scorer import (
    score_visits,
    health_grade,
    _score_cadence,
    _score_alive,
    _score_recovery,
    _score_momentum,
    _score_commit,
    _empty_result,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_visits(n, interval_s=600, alive=True, strokes_step=6, pending=0):
    """Generate a synthetic visit sequence."""
    base_ts = 1_729_300_000.0
    return [
        {
            "ts": base_ts + i * interval_s,
            "alive": alive,
            "strokes": 3800 + i * strokes_step,
            "pending": pending,
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# health_grade
# ---------------------------------------------------------------------------

class TestHealthGrade:
    def test_a_grade(self):
        assert health_grade(0.85) == "A"
        assert health_grade(1.0) == "A"

    def test_b_grade(self):
        assert health_grade(0.70) == "B"
        assert health_grade(0.84) == "B"

    def test_c_grade(self):
        assert health_grade(0.50) == "C"
        assert health_grade(0.69) == "C"

    def test_d_grade(self):
        assert health_grade(0.30) == "D"
        assert health_grade(0.49) == "D"

    def test_f_grade(self):
        assert health_grade(0.0) == "F"
        assert health_grade(0.29) == "F"

    def test_boundary(self):
        # Exact boundaries
        assert health_grade(0.85) == "A"
        assert health_grade(0.70) == "B"
        assert health_grade(0.50) == "C"
        assert health_grade(0.30) == "D"


# ---------------------------------------------------------------------------
# _score_cadence
# ---------------------------------------------------------------------------

class TestCadence:
    def test_perfect_cadence(self):
        visits = _make_visits(10, interval_s=600)
        score = _score_cadence(visits, target_s=600.0)
        assert score == 1.0

    def test_wrong_interval(self):
        visits = _make_visits(10, interval_s=1200)
        score = _score_cadence(visits, target_s=600.0)
        assert score < 1.0
        assert score > 0.0

    def test_jittery_interval(self):
        base = 1_729_300_000.0
        visits = [
            {"ts": base, "alive": True, "strokes": 3800, "pending": 0},
            {"ts": base + 100, "alive": True, "strokes": 3806, "pending": 0},
            {"ts": base + 5000, "alive": True, "strokes": 3812, "pending": 0},
            {"ts": base + 5100, "alive": True, "strokes": 3818, "pending": 0},
            {"ts": base + 10000, "alive": True, "strokes": 3824, "pending": 0},
        ]
        score = _score_cadence(visits, target_s=600.0)
        assert score < 0.5  # high jitter should penalise

    def test_too_few_visits(self):
        visits = _make_visits(2)
        score = _score_cadence(visits, target_s=600.0)
        assert score == 1.0  # not enough data

    def test_single_visit(self):
        visits = _make_visits(1)
        score = _score_cadence(visits, target_s=600.0)
        assert score == 1.0


# ---------------------------------------------------------------------------
# _score_alive
# ---------------------------------------------------------------------------

class TestAlive:
    def test_all_alive(self):
        visits = _make_visits(5, alive=True)
        assert _score_alive(visits) == 1.0

    def test_all_dead(self):
        visits = _make_visits(5, alive=False)
        assert _score_alive(visits) == 0.0

    def test_half_alive(self):
        visits = [
            {"ts": 100, "alive": True, "strokes": 1, "pending": 0},
            {"ts": 200, "alive": False, "strokes": 2, "pending": 0},
            {"ts": 300, "alive": True, "strokes": 3, "pending": 0},
            {"ts": 400, "alive": False, "strokes": 4, "pending": 0},
        ]
        assert _score_alive(visits) == 0.5

    def test_empty(self):
        assert _score_alive([]) == 1.0


# ---------------------------------------------------------------------------
# _score_recovery
# ---------------------------------------------------------------------------

class TestRecovery:
    def test_no_dead_visits(self):
        visits = _make_visits(5, alive=True)
        assert _score_recovery(visits) == 1.0

    def test_single_dead_then_recovered(self):
        visits = [
            {"ts": 100, "alive": True, "strokes": 1, "pending": 0},
            {"ts": 200, "alive": False, "strokes": 2, "pending": 0},
            {"ts": 300, "alive": True, "strokes": 3, "pending": 0},
        ]
        assert _score_recovery(visits) == 1.0

    def test_two_consecutive_dead(self):
        visits = [
            {"ts": 100, "alive": True, "strokes": 1, "pending": 0},
            {"ts": 200, "alive": False, "strokes": 2, "pending": 0},
            {"ts": 300, "alive": False, "strokes": 3, "pending": 0},
            {"ts": 400, "alive": True, "strokes": 4, "pending": 0},
        ]
        # First dead → next is also dead → 0.5
        # Second dead → next is alive → 1.0
        score = _score_recovery(visits)
        assert score == pytest.approx(0.75)

    def test_all_dead(self):
        visits = _make_visits(4, alive=False)
        # Each dead visit has no recovery: consecutive_dead grows
        # index 0: 3 more dead after → 1/8
        # index 1: 2 more dead after → 1/4
        # index 2: 1 more dead after → 1/2
        # index 3: 0 more dead after → 1/1
        expected = (1 / 8 + 1 / 4 + 1 / 2 + 1) / 4
        assert _score_recovery(visits) == pytest.approx(expected)

    def test_empty(self):
        assert _score_recovery([]) == 1.0


# ---------------------------------------------------------------------------
# _score_momentum
# ---------------------------------------------------------------------------

class TestMomentum:
    def test_growing_strokes(self):
        visits = _make_visits(5, strokes_step=6)
        assert _score_momentum(visits) == 1.0

    def test_flat_strokes(self):
        visits = _make_visits(5, strokes_step=0)
        assert _score_momentum(visits) == pytest.approx(0.3)

    def test_declining_strokes(self):
        base = 1_729_300_000.0
        visits = [
            {"ts": base, "alive": True, "strokes": 100, "pending": 0},
            {"ts": base + 600, "alive": True, "strokes": 90, "pending": 0},
            {"ts": base + 1200, "alive": True, "strokes": 80, "pending": 0},
        ]
        assert _score_momentum(visits) == 0.0

    def test_mixed(self):
        base = 1_729_300_000.0
        visits = [
            {"ts": base, "alive": True, "strokes": 100, "pending": 0},
            {"ts": base + 600, "alive": True, "strokes": 106, "pending": 0},  # +
            {"ts": base + 1200, "alive": True, "strokes": 106, "pending": 0},  # 0
        ]
        assert _score_momentum(visits) == pytest.approx(0.65)

    def test_single_visit(self):
        assert _score_momentum([{"ts": 1, "strokes": 1}]) == 1.0


# ---------------------------------------------------------------------------
# _score_commit
# ---------------------------------------------------------------------------

class TestCommit:
    def test_clean(self):
        visits = _make_visits(5, pending=0)
        assert _score_commit(visits) == 1.0

    def test_few_pending(self):
        visits = _make_visits(5, pending=2)
        assert _score_commit(visits) == pytest.approx(0.7)

    def test_moderate_pending(self):
        visits = _make_visits(5, pending=7)
        assert _score_commit(visits) == pytest.approx(0.4)

    def test_many_pending(self):
        visits = _make_visits(5, pending=15)
        assert _score_commit(visits) == pytest.approx(0.1)

    def test_empty(self):
        assert _score_commit([]) == 1.0


# ---------------------------------------------------------------------------
# score_visits (integration)
# ---------------------------------------------------------------------------

class TestScoreVisits:
    def test_healthy_pipeline(self):
        visits = _make_visits(20, interval_s=600, alive=True, strokes_step=6, pending=0)
        result = score_visits(visits)
        assert result["health_score"] > 0.85
        assert result["grade"] == "A"
        assert result["visit_count"] == 20

    def test_degraded_pipeline(self):
        # Dead on arrival, growing backlog, flat strokes
        base = 1_729_300_000.0
        visits = []
        for i in range(10):
            visits.append({
                "ts": base + i * 3600,  # hourly, not 10-min
                "alive": False,
                "strokes": 3800,  # flat
                "pending": 9 + i,  # growing
            })
        result = score_visits(visits)
        assert result["health_score"] < 0.50
        assert result["grade"] in ("D", "F")

    def test_empty_visits(self):
        result = score_visits([])
        assert result["health_score"] == 0.0
        assert result["grade"] == "F"
        assert result["visit_count"] == 0

    def test_custom_weights(self):
        visits = _make_visits(10, alive=True, pending=5)
        r1 = score_visits(visits)
        r2 = score_visits(visits, weights={"commit": 1.0})
        # With all weight on commit (pending=5 → 0.4), score should differ
        assert r1["health_score"] != r2["health_score"]

    def test_result_keys(self):
        visits = _make_visits(5)
        result = score_visits(visits)
        expected_keys = {
            "cadence_regularity", "alive_fraction", "recovery_promptness",
            "content_momentum", "commit_freshness", "health_score", "grade",
            "visit_count", "span_s",
        }
        assert set(result.keys()) == expected_keys

    def test_unsorted_input(self):
        """score_visits should sort by ts internally."""
        base = 1_729_300_000.0
        visits = [
            {"ts": base + 1200, "alive": True, "strokes": 3812, "pending": 0},
            {"ts": base, "alive": True, "strokes": 3800, "pending": 0},
            {"ts": base + 600, "alive": True, "strokes": 3806, "pending": 0},
        ]
        result = score_visits(visits)
        assert result["visit_count"] == 3
        assert result["health_score"] > 0.0


# ---------------------------------------------------------------------------
# _empty_result
# ---------------------------------------------------------------------------

class TestEmptyResult:
    def test_structure(self):
        r = _empty_result()
        assert r["health_score"] == 0.0
        assert r["grade"] == "F"
        assert r["visit_count"] == 0
