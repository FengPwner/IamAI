"""tests for commit_backlog_forecaster (visit 588).

covers: sample ingestion, linear velocity, eta calculation,
        pressure levels, forecast report, edge cases.
"""

import sys, os, pytest, math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "snippets"))
from commit_backlog_forecaster import CommitBacklogForecaster, ForecastReport


# ── helpers ─────────────────────────────────────────────────────

class FakeClock:
    """deterministic clock that advances manually."""
    def __init__(self, t=1000.0):
        self.t = t
    def __call__(self):
        return self.t
    def advance(self, seconds):
        self.t += seconds


# ── sample ingestion ────────────────────────────────────────────

class TestSampleIngestion:

    def test_add_single_sample(self):
        clk = FakeClock()
        f = CommitBacklogForecaster(clock=clk)
        f.add_sample(5)
        assert f.sample_count == 1
        assert f.latest == (1000.0, 5)

    def test_add_multiple_samples(self):
        clk = FakeClock()
        f = CommitBacklogForecaster(clock=clk)
        for i in range(5):
            f.add_sample(i)
            clk.advance(60)
        assert f.sample_count == 5
        assert f.latest == (1240.0, 4)

    def test_max_samples_cap(self):
        f = CommitBacklogForecaster(max_samples=10, clock=FakeClock())
        for i in range(20):
            f.add_sample(i, timestamp=1000.0 + i)
        assert f.sample_count == 10

    def test_negative_count_clamped_to_zero(self):
        f = CommitBacklogForecaster(clock=FakeClock())
        f.add_sample(-5)
        assert f.latest == (1000.0, 0)

    def test_bulk_load(self):
        f = CommitBacklogForecaster(clock=FakeClock())
        obs = [(100.0 + i * 60, 10 - i) for i in range(5)]
        f.add_samples(obs)
        assert f.sample_count == 5

    def test_empty_latest_is_none(self):
        f = CommitBacklogForecaster()
        assert f.latest is None

    def test_explicit_timestamp(self):
        f = CommitBacklogForecaster(clock=FakeClock())
        f.add_sample(3, timestamp=999.0)
        assert f.latest == (999.0, 3)


# ── velocity calculation ────────────────────────────────────────

class TestVelocity:

    def test_shrinking_backlog_positive_velocity(self):
        """backlog going from 20 to 10 over 10 minutes → positive vel."""
        f = CommitBacklogForecaster(clock=FakeClock())
        # 20 → 10 over 600 seconds
        for i in range(11):
            count = 20 - i  # 20, 19, ..., 10
            f.add_sample(count, timestamp=1000.0 + i * 60)
        vel = f.velocity()
        assert vel > 0  # shrinking = positive

    def test_growing_backlog_negative_velocity(self):
        """backlog going from 5 to 15 → negative vel."""
        f = CommitBacklogForecaster(clock=FakeClock())
        for i in range(11):
            count = 5 + i  # 5, 6, ..., 15
            f.add_sample(count, timestamp=1000.0 + i * 60)
        vel = f.velocity()
        assert vel < 0  # growing = negative

    def test_stable_backlog_zero_velocity(self):
        """constant backlog → velocity near zero."""
        f = CommitBacklogForecaster(clock=FakeClock())
        for i in range(10):
            f.add_sample(8, timestamp=1000.0 + i * 60)
        vel = f.velocity()
        assert abs(vel) < 1e-6

    def test_single_sample_velocity_zero(self):
        f = CommitBacklogForecaster(clock=FakeClock())
        f.add_sample(10)
        assert f.velocity() == 0.0

    def test_no_samples_velocity_zero(self):
        f = CommitBacklogForecaster()
        assert f.velocity() == 0.0

    def test_velocity_magnitude_linear(self):
        """1 file per 60 seconds → vel ≈ 1/60 files/s."""
        f = CommitBacklogForecaster(clock=FakeClock())
        for i in range(11):
            f.add_sample(30 - i, timestamp=1000.0 + i * 60)
        vel = f.velocity()
        # shrinking at 1 file per 60s → vel = +1/60 ≈ 0.01667
        assert abs(vel - 1.0 / 60) < 1e-6


# ── eta calculation ─────────────────────────────────────────────

class TestEtaClear:

    def test_shrinking_backlog_finite_eta(self):
        f = CommitBacklogForecaster(clock=FakeClock())
        # 10 files, shrinking at 1 per 60s → eta = 600s
        for i in range(11):
            f.add_sample(10 - i, timestamp=1000.0 + i * 60)
        eta = f.eta_clear()
        # current count is 0, so eta should be 0
        # (backlog already at 0)
        assert eta == 0.0

    def test_growing_backlog_infinite_eta(self):
        f = CommitBacklogForecaster(clock=FakeClock())
        for i in range(11):
            f.add_sample(5 + i, timestamp=1000.0 + i * 60)
        assert f.eta_clear() == float("inf")

    def test_zero_count_eta_zero(self):
        f = CommitBacklogForecaster(clock=FakeClock())
        f.add_sample(0)
        assert f.eta_clear() == 0.0

    def test_no_samples_eta_inf(self):
        f = CommitBacklogForecaster()
        assert f.eta_clear() == float("inf")

    def test_partial_clear(self):
        """10 files at t=0, 5 at t=300 → vel=1/60, eta=5*60=300s."""
        f = CommitBacklogForecaster(clock=FakeClock())
        f.add_sample(10, timestamp=0.0)
        f.add_sample(8, timestamp=120.0)
        f.add_sample(5, timestamp=300.0)
        eta = f.eta_clear()
        # current=5, vel = 10-5 / 300 = 5/300 = 0.01667/s
        # eta = 5 / 0.01667 ≈ 300s
        assert 250 < eta < 350


# ── pressure levels ─────────────────────────────────────────────

class TestPressureLevel:

    def test_green_small_stable_backlog(self):
        f = CommitBacklogForecaster(clock=FakeClock())
        for i in range(5):
            f.add_sample(3, timestamp=1000.0 + i * 60)
        assert f.pressure_level() == "green"

    def test_red_large_backlog(self):
        f = CommitBacklogForecaster(
            pressure_red_size=20, clock=FakeClock()
        )
        for i in range(5):
            f.add_sample(25, timestamp=1000.0 + i * 60)
        assert f.pressure_level() == "red"

    def test_yellow_moderate_backlog(self):
        f = CommitBacklogForecaster(
            pressure_yellow_size=10,
            pressure_red_size=25,
            clock=FakeClock(),
        )
        for i in range(5):
            f.add_sample(15, timestamp=1000.0 + i * 60)
        assert f.pressure_level() == "yellow"

    def test_red_fast_growing(self):
        """even small backlog is red if growing fast."""
        f = CommitBacklogForecaster(
            pressure_red_velocity=-0.05,
            clock=FakeClock(),
        )
        # growing at ~0.1 files/s
        for i in range(11):
            f.add_sample(i * 6, timestamp=1000.0 + i * 60)
        assert f.pressure_level() == "red"

    def test_yellow_slow_growing(self):
        f = CommitBacklogForecaster(
            pressure_yellow_velocity=-0.01,
            pressure_red_velocity=-0.05,
            clock=FakeClock(),
        )
        # growing at ~0.017 files/s (1 per minute)
        for i in range(11):
            f.add_sample(i, timestamp=1000.0 + i * 60)
        assert f.pressure_level() == "yellow"

    def test_green_empty(self):
        f = CommitBacklogForecaster()
        assert f.pressure_level() == "green"

    def test_custom_thresholds(self):
        f = CommitBacklogForecaster(
            pressure_yellow_size=5,
            pressure_red_size=10,
            clock=FakeClock(),
        )
        for i in range(5):
            f.add_sample(7, timestamp=1000.0 + i * 60)
        assert f.pressure_level() == "yellow"


# ── forecast report ─────────────────────────────────────────────

class TestForecastReport:

    def test_report_fields(self):
        f = CommitBacklogForecaster(clock=FakeClock())
        for i in range(5):
            f.add_sample(10 - i, timestamp=1000.0 + i * 60)
        r = f.forecast()
        assert isinstance(r, ForecastReport)
        assert r.pending_count == 6
        assert r.velocity > 0
        assert r.trend_samples == 5
        assert r.pressure in ("green", "yellow", "red")
        assert isinstance(r.detail, str)

    def test_report_is_clearing(self):
        f = CommitBacklogForecaster(clock=FakeClock())
        for i in range(11):
            f.add_sample(20 - i, timestamp=1000.0 + i * 60)
        r = f.forecast()
        # count=10, vel>0, eta finite → clearing
        # actually latest count is 10, but vel is positive
        assert r.is_clearing

    def test_report_is_growing(self):
        f = CommitBacklogForecaster(clock=FakeClock())
        for i in range(11):
            f.add_sample(i, timestamp=1000.0 + i * 60)
        r = f.forecast()
        assert r.is_growing

    def test_report_empty(self):
        f = CommitBacklogForecaster()
        r = f.forecast()
        assert r.pending_count == 0
        assert r.velocity == 0.0
        assert r.eta_seconds == float("inf")
        assert r.pressure == "green"
        assert "no samples" in r.detail

    def test_report_repr(self):
        f = CommitBacklogForecaster(clock=FakeClock())
        f.add_sample(5)
        r = f.forecast()
        s = repr(r)
        assert "ForecastReport" in s
        assert "pending=5" in s


# ── utilities ───────────────────────────────────────────────────

class TestUtilities:

    def test_clear(self):
        f = CommitBacklogForecaster(clock=FakeClock())
        for i in range(5):
            f.add_sample(i)
        f.clear()
        assert f.sample_count == 0
        assert f.latest is None

    def test_samples_as_list(self):
        f = CommitBacklogForecaster(clock=FakeClock())
        f.add_sample(3, timestamp=100.0)
        f.add_sample(5, timestamp=200.0)
        lst = f.samples_as_list()
        assert lst == [(100.0, 3), (200.0, 5)]

    def test_samples_as_list_is_copy(self):
        f = CommitBacklogForecaster(clock=FakeClock())
        f.add_sample(1)
        lst = f.samples_as_list()
        lst.append((9999.0, 99))
        assert f.sample_count == 1  # original unchanged


# ── integration: realistic scenario ─────────────────────────────

class TestRealisticScenario:

    def test_backlog_builds_then_clears(self):
        """simulate: push fails (backlog grows), then batch catches up."""
        f = CommitBacklogForecaster(max_samples=10, clock=FakeClock())

        # phase 1: backlog growing (0-300s)
        for i in range(6):
            f.add_sample(i * 2, timestamp=1000.0 + i * 60)

        r1 = f.forecast()
        assert r1.is_growing
        assert r1.pressure in ("yellow", "red")

        # phase 2: batch committer kicks in, backlog shrinks fast (300-660s)
        # use more samples with sharper decline to dominate the window
        for i in range(10):
            count = max(0, 12 - i * 2)
            f.add_sample(count, timestamp=1360.0 + i * 60)

        r2 = f.forecast()
        assert r2.velocity > 0
        assert r2.is_clearing

    def test_max_samples_rolling_window(self):
        """old samples fall off as new ones arrive."""
        f = CommitBacklogForecaster(max_samples=5, clock=FakeClock())
        # add 10 samples — only last 5 should remain
        for i in range(10):
            f.add_sample(i, timestamp=1000.0 + i * 60)
        assert f.sample_count == 5
        lst = f.samples_as_list()
        assert lst[0] == (1300.0, 5)
        assert lst[-1] == (1540.0, 9)
