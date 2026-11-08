"""Tests for iamai.visit_density module."""

import pytest

from iamai.visit_density import VisitDensity, density_report


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_visits(start, interval, count, jitter=None):
    """Generate visit timestamps with optional jitter."""
    import random

    if jitter is not None:
        random.seed(42)
    times = []
    t = start
    for _ in range(count):
        times.append(t)
        delta = interval
        if jitter:
            delta += random.uniform(-jitter, jitter)
        t += max(0.1, delta)
    return times


@pytest.fixture
def steady_visits():
    """20 visits at perfect 600s cadence."""
    return _make_visits(1000.0, 600.0, 20)


@pytest.fixture
def rhythmic_visits():
    """20 visits at 600s with minor jitter (±60s)."""
    return _make_visits(1000.0, 600.0, 20, jitter=60.0)


@pytest.fixture
def clustered_visits():
    """10 normal visits, then 5 tight visits (burst), then 5 normal."""
    normal1 = _make_visits(1000.0, 600.0, 10)
    # burst: 5 visits at 120s apart (0.2× expected)
    burst_start = normal1[-1] + 600.0
    burst = _make_visits(burst_start, 120.0, 5)
    # gap then normal
    normal2_start = burst[-1] + 600.0
    normal2 = _make_visits(normal2_start, 600.0, 5)
    return normal1 + burst + normal2


@pytest.fixture
def gappy_visits():
    """5 visits, then 7200s gap, then 5 visits."""
    pre = _make_visits(1000.0, 600.0, 5)
    post = _make_visits(pre[-1] + 7200.0, 600.0, 5)
    return pre + post


@pytest.fixture
def erratic_visits():
    """Mix of bursts and gaps — no discernible rhythm."""
    visits = [1000.0]
    # burst of 5 at 100s
    for i in range(5):
        visits.append(visits[-1] + 100.0)
    # gap of 5000s
    visits.append(visits[-1] + 5000.0)
    # burst of 3 at 80s
    for i in range(3):
        visits.append(visits[-1] + 80.0)
    # gap of 4000s
    visits.append(visits[-1] + 4000.0)
    # 5 normal
    for i in range(5):
        visits.append(visits[-1] + 600.0)
    return visits


# ---------------------------------------------------------------------------
# Interval computation
# ---------------------------------------------------------------------------


class TestIntervals:
    def test_interval_count(self, steady_visits):
        vd = VisitDensity(steady_visits, expected_interval=600.0)
        assert len(vd.intervals) == 19

    def test_perfect_intervals(self, steady_visits):
        vd = VisitDensity(steady_visits, expected_interval=600.0)
        for iv in vd.intervals:
            assert abs(iv - 600.0) < 0.01

    def test_single_visit(self):
        vd = VisitDensity([1000.0], expected_interval=600.0)
        assert vd.intervals == []

    def test_empty(self):
        vd = VisitDensity([], expected_interval=600.0)
        assert vd.intervals == []

    def test_unsorted_input_handled(self):
        vd = VisitDensity([1600.0, 1000.0, 2200.0], expected_interval=600.0)
        assert vd.intervals == [600.0, 600.0]


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TestClassification:
    def test_steady_all_normal(self, steady_visits):
        vd = VisitDensity(steady_visits, expected_interval=600.0)
        assert all(c == "normal" for c in vd.categories)

    def test_burst_detected(self, clustered_visits):
        vd = VisitDensity(clustered_visits, expected_interval=600.0)
        assert "tight" in vd.categories

    def test_gap_detected(self, gappy_visits):
        vd = VisitDensity(gappy_visits, expected_interval=600.0)
        assert "gap" in vd.categories

    def test_category_count_matches_intervals(self, rhythmic_visits):
        vd = VisitDensity(rhythmic_visits, expected_interval=600.0)
        assert len(vd.categories) == len(vd.intervals)

    def test_loose_category(self):
        # interval = 1500s = 2.5× of 600 → loose
        vd = VisitDensity([1000.0, 2500.0, 3100.0], expected_interval=600.0)
        cats = vd.categories
        assert cats[0] == "loose"  # 1500s gap
        assert cats[1] == "normal"  # 600s gap


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestClustering:
    def test_steady_zero_clustering(self, steady_visits):
        vd = VisitDensity(steady_visits, expected_interval=600.0)
        assert vd.clustering() == 0.0

    def test_clustered_has_tight(self, clustered_visits):
        vd = VisitDensity(clustered_visits, expected_interval=600.0)
        assert vd.clustering() > 0.0

    def test_all_tight_is_one(self):
        # 5 visits at 100s apart = 0.167× of 600 → all tight
        visits = [1000.0, 1100.0, 1200.0, 1300.0, 1400.0]
        vd = VisitDensity(visits, expected_interval=600.0)
        assert vd.clustering() == 1.0

    def test_empty_returns_zero(self):
        vd = VisitDensity([], expected_interval=600.0)
        assert vd.clustering() == 0.0


class TestEvenness:
    def test_perfect_evenness(self, steady_visits):
        vd = VisitDensity(steady_visits, expected_interval=600.0)
        assert vd.evenness() == pytest.approx(1.0, abs=0.01)

    def test_uneven_lower(self, erratic_visits):
        vd = VisitDensity(erratic_visits, expected_interval=600.0)
        assert vd.evenness() < 0.5

    def test_single_visit_evenness(self):
        vd = VisitDensity([1000.0], expected_interval=600.0)
        assert vd.evenness() == 1.0

    def test_two_visits_evenness(self):
        vd = VisitDensity([1000.0, 1600.0], expected_interval=600.0)
        assert vd.evenness() == 1.0  # one interval, CV=0

    def test_rhythmic_high_evenness(self, rhythmic_visits):
        vd = VisitDensity(rhythmic_visits, expected_interval=600.0)
        assert vd.evenness() > 0.7


class TestBurstCount:
    def test_steady_no_bursts(self, steady_visits):
        vd = VisitDensity(steady_visits, expected_interval=600.0)
        assert vd.burst_count() == 0

    def test_one_burst(self, clustered_visits):
        vd = VisitDensity(clustered_visits, expected_interval=600.0)
        assert vd.burst_count() == 1

    def test_multiple_bursts(self, erratic_visits):
        vd = VisitDensity(erratic_visits, expected_interval=600.0)
        assert vd.burst_count() >= 2


class TestGapCount:
    def test_steady_no_gaps(self, steady_visits):
        vd = VisitDensity(steady_visits, expected_interval=600.0)
        assert vd.gap_count() == 0

    def test_one_gap(self, gappy_visits):
        vd = VisitDensity(gappy_visits, expected_interval=600.0)
        assert vd.gap_count() == 1

    def test_erratic_has_gaps(self, erratic_visits):
        vd = VisitDensity(erratic_visits, expected_interval=600.0)
        assert vd.gap_count() >= 1


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------


class TestGrade:
    def test_steady_grade(self, steady_visits):
        vd = VisitDensity(steady_visits, expected_interval=600.0)
        assert vd.grade() == "steady"

    def test_rhythmic_grade(self, rhythmic_visits):
        vd = VisitDensity(rhythmic_visits, expected_interval=600.0)
        g = vd.grade()
        assert g in ("steady", "rhythmic")

    def test_clustered_grade(self, clustered_visits):
        vd = VisitDensity(clustered_visits, expected_interval=600.0)
        g = vd.grade()
        assert g in ("uneven", "clustered", "rhythmic")

    def test_erratic_grade(self, erratic_visits):
        vd = VisitDensity(erratic_visits, expected_interval=600.0)
        g = vd.grade()
        assert g in ("clustered", "erratic", "uneven")

    def test_gappy_not_steady(self, gappy_visits):
        vd = VisitDensity(gappy_visits, expected_interval=600.0)
        assert vd.grade() != "steady"

    def test_grade_returns_string(self, steady_visits):
        vd = VisitDensity(steady_visits, expected_interval=600.0)
        assert isinstance(vd.grade(), str)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class TestSummary:
    def test_summary_keys(self, steady_visits):
        vd = VisitDensity(steady_visits, expected_interval=600.0)
        s = vd.summary()
        expected_keys = {
            "visit_count", "interval_count", "clustering", "evenness",
            "burst_count", "gap_count", "score", "grade",
            "category_breakdown",
        }
        assert set(s.keys()) == expected_keys

    def test_summary_visit_count(self, steady_visits):
        vd = VisitDensity(steady_visits, expected_interval=600.0)
        assert vd.summary()["visit_count"] == 20

    def test_summary_interval_count(self, steady_visits):
        vd = VisitDensity(steady_visits, expected_interval=600.0)
        assert vd.summary()["interval_count"] == 19

    def test_summary_score_range(self, steady_visits):
        vd = VisitDensity(steady_visits, expected_interval=600.0)
        s = vd.summary()
        assert 0.0 <= s["score"] <= 1.0

    def test_summary_category_breakdown(self, clustered_visits):
        vd = VisitDensity(clustered_visits, expected_interval=600.0)
        bd = vd.summary()["category_breakdown"]
        assert isinstance(bd, dict)
        total = sum(bd.values())
        assert total == vd.summary()["interval_count"]

    def test_empty_summary(self):
        vd = VisitDensity([], expected_interval=600.0)
        s = vd.summary()
        assert s["visit_count"] == 0
        assert s["interval_count"] == 0
        assert s["clustering"] == 0.0
        assert s["evenness"] == 1.0


# ---------------------------------------------------------------------------
# density_report function
# ---------------------------------------------------------------------------


class TestDensityReport:
    def test_report_is_string(self, steady_visits):
        r = density_report(steady_visits, expected_interval=600.0)
        assert isinstance(r, str)

    def test_report_contains_grade(self, steady_visits):
        r = density_report(steady_visits, expected_interval=600.0)
        assert "steady" in r

    def test_report_contains_evenness(self, steady_visits):
        r = density_report(steady_visits, expected_interval=600.0)
        assert "evenness" in r

    def test_report_insufficient_data(self):
        r = density_report([1000.0], expected_interval=600.0)
        assert "insufficient" in r

    def test_report_empty(self):
        r = density_report([], expected_interval=600.0)
        assert "insufficient" in r

    def test_report_burst_grammar(self):
        # Exactly one burst → "1 burst" not "1 bursts"
        visits = [1000.0, 1100.0, 1200.0, 1800.0, 2400.0]
        r = density_report(visits, expected_interval=600.0)
        assert "1 burst" in r
        assert "1 bursts" not in r

    def test_report_gap_grammar(self):
        visits = [1000.0, 1600.0, 7000.0, 7600.0]
        r = density_report(visits, expected_interval=600.0)
        assert "1 gap" in r
        assert "1 gaps" not in r
