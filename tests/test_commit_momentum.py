#!/usr/bin/env python3
"""Tests for iamai.commit_momentum — commit-momentum tracker."""

import time

import pytest

from iamai.commit_momentum import (
    CommitMomentum,
    MomentumResult,
    classify_momentum,
    fetch_commit_timestamps,
    momentum_report,
)


# ---------------------------------------------------------------------------
# CommitMomentum configuration
# ---------------------------------------------------------------------------


class TestCommitMomentumConfig:
    def test_default_window(self):
        cm = CommitMomentum()
        assert cm.window_hours == 12.0

    def test_window_seconds(self):
        cm = CommitMomentum(window_hours=6)
        assert cm.window_seconds == 6 * 3600

    def test_half_seconds(self):
        cm = CommitMomentum(window_hours=12)
        assert cm.half_seconds == 6 * 3600

    def test_custom_thresholds(self):
        cm = CommitMomentum(accel_threshold=1.5, decel_threshold=0.5, stall_threshold=0.2)
        assert cm.accel_threshold == 1.5
        assert cm.decel_threshold == 0.5
        assert cm.stall_threshold == 0.2


# ---------------------------------------------------------------------------
# classify_momentum
# ---------------------------------------------------------------------------


class TestClassifyMomentum:
    def test_stalled_when_newer_zero(self):
        """Zero newer commits → stalled regardless of ratio."""
        assert classify_momentum(999.0, newer_count=0) == "stalled"

    def test_stalled_when_both_zero(self):
        assert classify_momentum(0.0, newer_count=0) == "stalled"

    def test_accelerating_above_threshold(self):
        assert classify_momentum(1.5, newer_count=10) == "accelerating"

    def test_accelerating_exactly_at_threshold(self):
        assert classify_momentum(1.30, newer_count=10) == "accelerating"

    def test_steady_in_range(self):
        assert classify_momentum(1.0, newer_count=5) == "steady"

    def test_steady_lower_bound(self):
        assert classify_momentum(0.70, newer_count=5) == "steady"

    def test_steady_upper_bound(self):
        assert classify_momentum(1.29, newer_count=5) == "steady"

    def test_decelerating_below_range(self):
        assert classify_momentum(0.50, newer_count=3) == "decelerating"

    def test_decelerating_above_stall(self):
        assert classify_momentum(0.35, newer_count=2) == "decelerating"

    def test_stalled_below_stall_threshold(self):
        assert classify_momentum(0.20, newer_count=1) == "stalled"

    def test_stalled_exactly_at_stall_threshold_minus(self):
        assert classify_momentum(0.29, newer_count=1) == "stalled"

    def test_custom_thresholds(self):
        assert classify_momentum(2.0, newer_count=10, accel=2.5) == "steady"
        assert classify_momentum(2.0, newer_count=10, accel=2.0) == "accelerating"

    def test_negative_ratio(self):
        """Negative ratio is below stall threshold → stalled."""
        assert classify_momentum(-0.5, newer_count=1) == "stalled"


# ---------------------------------------------------------------------------
# CommitMomentum.evaluate
# ---------------------------------------------------------------------------


class TestEvaluate:
    @pytest.fixture()
    def cm(self):
        return CommitMomentum(window_hours=12)

    def test_empty_timestamps(self, cm):
        now = time.time()
        result = cm.evaluate([], now=now)
        assert result.verdict == "stalled"
        assert result.older_count == 0
        assert result.newer_count == 0
        assert result.ratio == 0.0

    def test_all_old_commits(self, cm):
        """All commits outside the window → stalled."""
        now = time.time()
        old_ts = [now - 24 * 3600, now - 20 * 3600, now - 18 * 3600]
        result = cm.evaluate(old_ts, now=now)
        assert result.verdict == "stalled"
        assert result.older_count == 0
        assert result.newer_count == 0

    def test_all_in_older_half(self, cm):
        """Commits only in the older half, none in newer → stalled."""
        now = time.time()
        # Window: [now-12h, now].  Midpoint: now-6h.
        # Place commits at now-8h (older half).
        older_ts = [now - 8 * 3600 + i * 60 for i in range(5)]
        result = cm.evaluate(older_ts, now=now)
        assert result.older_count == 5
        assert result.newer_count == 0
        assert result.verdict == "stalled"

    def test_balanced_steady(self, cm):
        """Equal commits in both halves → steady (ratio=1.0)."""
        now = time.time()
        older = [now - 8 * 3600 + i * 120 for i in range(10)]
        newer = [now - 3 * 3600 + i * 120 for i in range(10)]
        result = cm.evaluate(older + newer, now=now)
        assert result.older_count == 10
        assert result.newer_count == 10
        assert result.ratio == pytest.approx(1.0)
        assert result.verdict == "steady"

    def test_accelerating(self, cm):
        """More commits in newer half → accelerating."""
        now = time.time()
        older = [now - 8 * 3600 + i * 600 for i in range(5)]
        newer = [now - 3 * 3600 + i * 180 for i in range(15)]
        result = cm.evaluate(older + newer, now=now)
        assert result.older_count == 5
        assert result.newer_count == 15
        assert result.ratio == pytest.approx(3.0)
        assert result.verdict == "accelerating"

    def test_decelerating(self, cm):
        """Fewer commits in newer half → decelerating."""
        now = time.time()
        older = [now - 8 * 3600 + i * 120 for i in range(20)]
        newer = [now - 3 * 3600 + i * 600 for i in range(8)]
        result = cm.evaluate(older + newer, now=now)
        assert result.older_count == 20
        assert result.newer_count == 8
        assert result.ratio == pytest.approx(0.4)
        assert result.verdict == "decelerating"

    def test_only_newer_half(self, cm):
        """Commits only in newer half, none in older → accelerating."""
        now = time.time()
        newer = [now - 2 * 3600 + i * 60 for i in range(8)]
        result = cm.evaluate(newer, now=now)
        assert result.older_count == 0
        assert result.newer_count == 8
        # ratio = newer_count when older is 0
        assert result.ratio == 8.0
        assert result.verdict == "accelerating"

    def test_boundary_at_midpoint(self, cm):
        """Commit exactly at midpoint falls in newer half."""
        now = time.time()
        midpoint = now - cm.half_seconds
        result = cm.evaluate([midpoint], now=now)
        assert result.newer_count == 1
        assert result.older_count == 0

    def test_boundary_at_window_start(self, cm):
        """Commit exactly at window_start falls in older half."""
        now = time.time()
        window_start = now - cm.window_seconds
        result = cm.evaluate([window_start], now=now)
        # window_start is the inclusive boundary for the window
        # ts >= window_start and ts < midpoint → older
        assert result.older_count == 1

    def test_unsorted_timestamps(self, cm):
        """Timestamps don't need to be sorted."""
        now = time.time()
        ts = [now - 1 * 3600, now - 10 * 3600, now - 2 * 3600, now - 9 * 3600]
        result = cm.evaluate(ts, now=now)
        assert result.newer_count == 2
        assert result.older_count == 2
        assert result.verdict == "steady"

    def test_custom_window(self):
        cm = CommitMomentum(window_hours=6)
        now = time.time()
        # 4h ago = older half (before 3h midpoint), 1h ago = newer
        older = [now - 4 * 3600 + i * 300 for i in range(10)]
        newer = [now - 1 * 3600 + i * 300 for i in range(10)]
        result = cm.evaluate(older + newer, now=now)
        assert result.older_count == 10
        assert result.newer_count == 10
        assert result.verdict == "steady"


# ---------------------------------------------------------------------------
# MomentumResult
# ---------------------------------------------------------------------------


class TestMomentumResult:
    def test_to_dict(self):
        r = MomentumResult(
            older_count=10,
            newer_count=15,
            ratio=1.5,
            verdict="accelerating",
            window_hours=12.0,
        )
        d = r.to_dict()
        assert d["older_count"] == 10
        assert d["newer_count"] == 15
        assert d["ratio"] == 1.5
        assert d["verdict"] == "accelerating"
        assert d["window_hours"] == 12.0

    def test_frozen(self):
        r = MomentumResult(0, 0, 0.0, "stalled", 12.0)
        with pytest.raises(AttributeError):
            r.verdict = "steady"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# fetch_commit_timestamps
# ---------------------------------------------------------------------------


class TestFetchCommitTimestamps:
    def test_returns_list(self):
        from pathlib import Path
        repo = Path(__file__).resolve().parent.parent
        ts = fetch_commit_timestamps(repo=repo)
        assert isinstance(ts, list)
        assert len(ts) > 0

    def test_timestamps_are_floats(self):
        from pathlib import Path
        repo = Path(__file__).resolve().parent.parent
        ts = fetch_commit_timestamps(repo=repo, max_count=10)
        for t in ts:
            assert isinstance(t, float)

    def test_nonexistent_repo(self):
        from pathlib import Path
        ts = fetch_commit_timestamps(repo=Path("/tmp/nonexistent_repo_xyz"))
        assert ts == []

    def test_max_count_respected(self):
        from pathlib import Path
        repo = Path(__file__).resolve().parent.parent
        ts = fetch_commit_timestamps(repo=repo, max_count=5)
        assert len(ts) <= 5


# ---------------------------------------------------------------------------
# momentum_report (integration)
# ---------------------------------------------------------------------------


class TestMomentumReport:
    def test_returns_result(self):
        from pathlib import Path
        repo = Path(__file__).resolve().parent.parent
        result = momentum_report(window_hours=12, repo=repo)
        assert isinstance(result, MomentumResult)
        assert result.verdict in ("accelerating", "steady", "decelerating", "stalled")

    def test_custom_window(self):
        from pathlib import Path
        repo = Path(__file__).resolve().parent.parent
        result = momentum_report(window_hours=1, repo=repo)
        assert result.window_hours == 1.0
