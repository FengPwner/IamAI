"""Tests for push_resilience module"""

import pytest
import time
from iamai.push_resilience import (
    PushResilience, PushEvent, ResilienceSnapshot
)


class TestPushResilience:
    """Test PushResilience tracking and analysis"""

    def test_init_default_window(self):
        """Test initialization with default window size"""
        pr = PushResilience()
        assert pr.window_size == 50
        assert len(pr.events) == 0

    def test_init_custom_window(self):
        """Test initialization with custom window size"""
        pr = PushResilience(window_size=20)
        assert pr.window_size == 20

    def test_record_successful_push(self):
        """Test recording a successful push"""
        pr = PushResilience()
        event = pr.record_push(success=True)
        assert event.success is True
        assert event.failure_type is None
        assert event.retry_count == 0
        assert len(pr.events) == 1

    def test_record_failed_push(self):
        """Test recording a failed push with failure type"""
        pr = PushResilience()
        event = pr.record_push(
            success=False,
            failure_type="race",
            retry_count=2,
            recovery_time=45.0
        )
        assert event.success is False
        assert event.failure_type == "race"
        assert event.retry_count == 2
        assert event.recovery_time == 45.0

    def test_snapshot_empty(self):
        """Test snapshot with no events"""
        pr = PushResilience()
        snap = pr.snapshot()
        assert snap.total_pushes == 0
        assert snap.success_rate == 0.0
        assert snap.resilience_score == 0.0

    def test_snapshot_all_success(self):
        """Test snapshot with all successful pushes"""
        pr = PushResilience()
        for _ in range(10):
            pr.record_push(success=True)

        snap = pr.snapshot()
        assert snap.total_pushes == 10
        assert snap.success_rate == 1.0
        assert snap.resilience_score >= 0.8  # high score for perfect success

    def test_snapshot_mixed_results(self):
        """Test snapshot with mixed success and failure"""
        pr = PushResilience()
        # 7 successes, 3 failures
        for _ in range(7):
            pr.record_push(success=True)
        for _ in range(3):
            pr.record_push(success=False, failure_type="network", recovery_time=30.0)

        snap = pr.snapshot()
        assert snap.total_pushes == 10
        assert 0.6 < snap.success_rate < 0.8
        assert snap.mttr == 30.0

    def test_race_frequency(self):
        """Test race condition frequency calculation"""
        pr = PushResilience()
        # 10 pushes, 4 are race failures
        for _ in range(6):
            pr.record_push(success=True)
        for _ in range(4):
            pr.record_push(success=False, failure_type="race")

        snap = pr.snapshot()
        assert 0.35 < snap.race_frequency < 0.45

    def test_retry_effectiveness(self):
        """Test retry effectiveness calculation"""
        pr = PushResilience()
        # 5 retried pushes, 3 succeeded
        pr.record_push(success=True, retry_count=1)
        pr.record_push(success=True, retry_count=2)
        pr.record_push(success=True, retry_count=1)
        pr.record_push(success=False, retry_count=3, failure_type="auth")
        pr.record_push(success=False, retry_count=2, failure_type="network")
        # 5 non-retried pushes
        for _ in range(5):
            pr.record_push(success=True)

        snap = pr.snapshot()
        assert 0.5 < snap.retry_effectiveness < 0.7

    def test_dominant_failure(self):
        """Test dominant failure type identification"""
        pr = PushResilience()
        pr.record_push(success=False, failure_type="network")
        pr.record_push(success=False, failure_type="race")
        pr.record_push(success=False, failure_type="race")
        pr.record_push(success=False, failure_type="race")
        pr.record_push(success=False, failure_type="auth")

        snap = pr.snapshot()
        assert snap.dominant_failure == "race"

    def test_classify_reliable(self):
        """Test classification as reliable"""
        pr = PushResilience()
        for _ in range(20):
            pr.record_push(success=True)

        assert pr.classify_pattern() == "reliable"

    def test_classify_high_contention(self):
        """Test classification as high contention"""
        pr = PushResilience()
        # 10 pushes, 4 are race failures (40% > 30% threshold)
        for _ in range(6):
            pr.record_push(success=True)
        for _ in range(4):
            pr.record_push(success=False, failure_type="race")

        assert pr.classify_pattern() == "high_contention"

    def test_classify_slow_recovery(self):
        """Test classification as slow recovery"""
        pr = PushResilience()
        # Pushes with long recovery times (> 180s)
        for _ in range(5):
            pr.record_push(success=True)
        for _ in range(5):
            pr.record_push(
                success=False,
                failure_type="network",
                recovery_time=250.0
            )

        assert pr.classify_pattern() == "slow_recovery"

    def test_classify_insufficient_data(self):
        """Test classification with insufficient data"""
        pr = PushResilience()
        for _ in range(3):
            pr.record_push(success=True)

        assert pr.classify_pattern() == "insufficient_data"

    def test_recommend_strategy_reliable(self):
        """Test strategy recommendation for reliable pattern"""
        pr = PushResilience()
        for _ in range(20):
            pr.record_push(success=True)

        strategy = pr.recommend_strategy()
        assert "maintain" in strategy.lower()

    def test_recommend_strategy_high_contention(self):
        """Test strategy recommendation for high contention"""
        pr = PushResilience()
        for _ in range(6):
            pr.record_push(success=True)
        for _ in range(4):
            pr.record_push(success=False, failure_type="race")

        strategy = pr.recommend_strategy()
        assert "jitter" in strategy.lower()

    def test_failure_distribution(self):
        """Test failure type distribution"""
        pr = PushResilience()
        pr.record_push(success=False, failure_type="network")
        pr.record_push(success=False, failure_type="network")
        pr.record_push(success=False, failure_type="race")
        pr.record_push(success=False, failure_type="auth")

        dist = pr.failure_distribution()
        assert "network" in dist
        assert "race" in dist
        assert "auth" in dist
        assert dist["network"][0] == 2
        assert dist["network"][1] == 0.5
        assert dist["race"][0] == 1
        assert dist["race"][1] == 0.25

    def test_window_overflow(self):
        """Test that old events are dropped when window is full"""
        pr = PushResilience(window_size=10)
        # Add 15 events
        for i in range(15):
            pr.record_push(success=(i % 2 == 0))

        assert len(pr.events) == 10

    def test_mttr_calculation(self):
        """Test mean time to recovery calculation"""
        pr = PushResilience()
        pr.record_push(success=False, failure_type="network", recovery_time=10.0)
        pr.record_push(success=False, failure_type="race", recovery_time=20.0)
        pr.record_push(success=False, failure_type="network", recovery_time=30.0)
        pr.record_push(success=True)  # no recovery_time

        snap = pr.snapshot()
        assert snap.mttr == 20.0  # (10 + 20 + 30) / 3

    def test_resilience_score_components(self):
        """Test that resilience score combines components correctly"""
        pr = PushResilience()
        # Create a scenario with known values
        for _ in range(8):
            pr.record_push(success=True)
        for _ in range(2):
            pr.record_push(
                success=False,
                failure_type="network",
                retry_count=1,
                recovery_time=150.0
            )

        snap = pr.snapshot()
        # success_rate = 0.8
        # recovery_score = 1 - (150/300) = 0.5
        # retry_effectiveness = 0 (no retried successes)
        # resilience = 0.8 * 0.4 + 0.5 * 0.3 + 0 * 0.3 = 0.32 + 0.15 = 0.47
        assert 0.4 < snap.resilience_score < 0.6

    def test_no_retried_pushes(self):
        """Test retry effectiveness with no retried pushes"""
        pr = PushResilience()
        for _ in range(10):
            pr.record_push(success=True, retry_count=0)

        snap = pr.snapshot()
        assert snap.retry_effectiveness == 0.5  # neutral when no retries needed

    def test_empty_failure_distribution(self):
        """Test failure distribution with no failures"""
        pr = PushResilience()
        for _ in range(10):
            pr.record_push(success=True)

        dist = pr.failure_distribution()
        assert dist == {}


class TestPushEvent:
    """Test PushEvent dataclass"""

    def test_event_creation(self):
        """Test creating a push event"""
        event = PushEvent(
            timestamp=time.time(),
            success=True,
            failure_type=None,
            retry_count=0,
            recovery_time=0.0
        )
        assert event.success is True
        assert event.failure_type is None

    def test_event_with_failure(self):
        """Test creating a failed push event"""
        ts = time.time()
        event = PushEvent(
            timestamp=ts,
            success=False,
            failure_type="race",
            retry_count=3,
            recovery_time=45.5
        )
        assert event.success is False
        assert event.failure_type == "race"
        assert event.retry_count == 3
        assert event.recovery_time == 45.5


class TestResilienceSnapshot:
    """Test ResilienceSnapshot dataclass"""

    def test_snapshot_creation(self):
        """Test creating a resilience snapshot"""
        snap = ResilienceSnapshot(
            total_pushes=100,
            success_rate=0.95,
            mttr=30.0,
            race_frequency=0.05,
            retry_effectiveness=0.8,
            resilience_score=0.9,
            dominant_failure="network"
        )
        assert snap.total_pushes == 100
        assert snap.success_rate == 0.95
        assert snap.dominant_failure == "network"
