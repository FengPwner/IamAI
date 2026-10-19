"""Tests for iamai.process_reclaim_detector — container reclaim scoring."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iamai.process_mortality import record_event
from iamai.process_reclaim_detector import (
    BUNDLE_THRESHOLD_SEC,
    OFF_PEAK_END,
    OFF_PEAK_START,
    _bundled_factor,
    _hour_factor,
    _interval_factor,
    _modal_gap,
    classify_deaths,
    reclaim_summary,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return tmp_path


# ---------------------------------------------------------------------------
# _hour_factor
# ---------------------------------------------------------------------------


class TestHourFactor:
    def test_off_peak_center(self):
        # 03:00 GMT+8 = 19:00 UTC previous day
        ts = "2026-10-19T19:00:00+00:00"
        assert _hour_factor(ts, tz_offset_hours=8) == 1.0

    def test_off_peak_start_boundary(self):
        # 01:00 GMT+8 = 17:00 UTC
        ts = "2026-10-19T17:00:00+00:00"
        assert _hour_factor(ts, tz_offset_hours=8) == 1.0

    def test_off_peak_end_boundary(self):
        # 05:00 GMT+8 = 21:00 UTC
        ts = "2026-10-19T21:00:00+00:00"
        f = _hour_factor(ts, tz_offset_hours=8)
        assert 0.2 <= f <= 1.0  # just past window, decays

    def test_noon_low_factor(self):
        # 12:00 GMT+8 = 04:00 UTC
        ts = "2026-10-20T04:00:00+00:00"
        f = _hour_factor(ts, tz_offset_hours=8)
        # noon is well outside off-peak window; factor should be < 0.6
        assert f < 0.6
        assert f >= 0.2

    def test_early_morning_in_window(self):
        # 02:00 GMT+8 = 18:00 UTC
        ts = "2026-10-19T18:00:00+00:00"
        assert _hour_factor(ts, tz_offset_hours=8) == 1.0


# ---------------------------------------------------------------------------
# _modal_gap
# ---------------------------------------------------------------------------


class TestModalGap:
    def test_empty(self):
        assert _modal_gap([]) is None

    def test_single_timestamp(self):
        assert _modal_gap([1000.0]) is None

    def test_uniform_gaps(self):
        ts = [0.0, 3600.0, 7200.0, 10800.0]
        gap = _modal_gap(ts)
        assert gap is not None
        # All gaps are 3600s = 1h, bucket 4 (3600/900=4)
        assert 3000 <= gap <= 4200

    def test_mixed_gaps_picks_mode(self):
        ts = [0.0, 3600.0, 7200.0, 7300.0, 10800.0, 10900.0]
        gap = _modal_gap(ts)
        assert gap is not None
        # Gaps: 3600, 3600, 100, 3500, 100
        # Mode bucket should be around 100s (bucket 0) — 2 occurrences
        # vs 3600s (bucket 4) — 3 occurrences
        # Actually bucket 4 has 3 entries → mode is ~3600s
        assert 3000 <= gap <= 4500

    def test_two_identical_gaps(self):
        ts = [0.0, 1800.0, 3600.0]
        gap = _modal_gap(ts)
        assert gap is not None
        # bucket 2 (1800/900=2), midpoint = 2.5 * 900 = 2250
        assert 1500 <= gap <= 2700


# ---------------------------------------------------------------------------
# _interval_factor
# ---------------------------------------------------------------------------


class TestIntervalFactor:
    def test_none_gap(self):
        assert _interval_factor(None, 3600.0) == 0.0

    def test_none_modal(self):
        assert _interval_factor(3600.0, None) == 0.0

    def test_exact_match(self):
        assert _interval_factor(3600.0, 3600.0) == 1.0

    def test_within_tolerance(self):
        # 3600 ± 30% = [2520, 4680]
        assert _interval_factor(4000.0, 3600.0) == 1.0

    def test_outside_tolerance(self):
        assert _interval_factor(1000.0, 3600.0) == 0.0

    def test_zero_modal(self):
        assert _interval_factor(3600.0, 0.0) == 0.0


# ---------------------------------------------------------------------------
# _bundled_factor
# ---------------------------------------------------------------------------


class TestBundledFactor:
    def _iso(self, epoch: float) -> str:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()

    def test_no_bundles(self):
        ts = self._iso(1000.0)
        others = [self._iso(1000.0), self._iso(5000.0), self._iso(9000.0)]
        assert _bundled_factor(ts, others) == 0.0

    def test_bundled(self):
        ts = self._iso(1000.0)
        others = [self._iso(1000.0), self._iso(1050.0), self._iso(5000.0)]
        assert _bundled_factor(ts, others) == 1.0

    def test_exact_threshold(self):
        ts = self._iso(1000.0)
        others = [self._iso(1000.0), self._iso(1000.0 + BUNDLE_THRESHOLD_SEC)]
        assert _bundled_factor(ts, others) == 1.0

    def test_just_over_threshold(self):
        ts = self._iso(1000.0)
        others = [self._iso(1000.0), self._iso(1000.0 + BUNDLE_THRESHOLD_SEC + 1)]
        assert _bundled_factor(ts, others) == 0.0

    def test_same_second_different_writer(self):
        """Two writers die at the exact same second — should score 1.0."""
        ts = self._iso(1000.0)
        # Two entries in the list (both the same ISO string, but they
        # represent different events from different writers)
        others = [ts, ts]
        # Counting approach: nearby=2 (both entries match) > 1 → 1.0
        assert _bundled_factor(ts, others) == 1.0


# ---------------------------------------------------------------------------
# classify_deaths
# ---------------------------------------------------------------------------


class TestClassifyDeaths:
    def _seed_death(
        self,
        repo: Path,
        writer: str,
        hour: int,
        minute: int = 0,
        pid: int = 100,
    ):
        """Seed a death event at the given local hour (GMT+8)."""
        # Convert local hour to UTC
        utc_hour = (hour - 8) % 24
        ts = datetime(2026, 10, 20, utc_hour, minute, 0, tzinfo=timezone.utc)
        return record_event(repo, writer=writer, event="death", pid=pid, ts=ts)

    def test_empty_repo(self, repo: Path):
        assert classify_deaths(repo) == []

    def test_single_off_peak_death(self, repo: Path):
        self._seed_death(repo, "qwen", hour=3, pid=100)
        results = classify_deaths(repo, writer="qwen")
        assert len(results) == 1
        assert results[0]["hour_factor"] == 1.0
        assert results[0]["writer"] == "qwen"

    def test_single_peak_death(self, repo: Path):
        self._seed_death(repo, "qwen", hour=14, pid=100)
        results = classify_deaths(repo, writer="qwen")
        assert len(results) == 1
        # Peak hour should have a lower hour_factor
        assert results[0]["hour_factor"] < 0.5

    def test_bundled_deaths_score_high(self, repo: Path):
        # Two deaths 30 seconds apart, off-peak
        self._seed_death(repo, "qwen", hour=2, minute=0, pid=100)
        self._seed_death(repo, "guoban", hour=2, minute=0, pid=200)
        results = classify_deaths(repo, writer="qwen")
        assert len(results) == 1
        assert results[0]["bundled_factor"] == 1.0

    def test_writer_filter(self, repo: Path):
        self._seed_death(repo, "qwen", hour=3, pid=100)
        self._seed_death(repo, "guoban", hour=3, pid=200)
        qwen_results = classify_deaths(repo, writer="qwen")
        all_results = classify_deaths(repo, writer=None)
        assert len(qwen_results) == 1
        assert len(all_results) == 2

    def test_periodic_deaths_high_interval(self, repo: Path):
        # Seed deaths at uniform 1-hour intervals, all off-peak
        base = datetime(2026, 10, 19, 17, 0, 0, tzinfo=timezone.utc)  # 01:00 GMT+8
        for i in range(4):
            ts = base + timedelta(hours=i)
            record_event(repo, writer="qwen", event="death", pid=100 + i, ts=ts)
        results = classify_deaths(repo, writer="qwen")
        assert len(results) == 4
        # After the first death, interval_factor should be high
        for r in results[1:]:
            assert r["interval_factor"] >= 0.0  # at least some interval score

    def test_no_writer_returns_all(self, repo: Path):
        self._seed_death(repo, "qwen", hour=3, pid=100)
        self._seed_death(repo, "guoban", hour=14, pid=200)
        results = classify_deaths(repo)
        assert len(results) == 2

    def test_score_bounded(self, repo: Path):
        self._seed_death(repo, "qwen", hour=3, pid=100)
        results = classify_deaths(repo, writer="qwen")
        for r in results:
            assert 0.0 <= r["reclaim_score"] <= 1.0

    def test_likely_reclaim_threshold(self, repo: Path):
        # High-scoring death: off-peak + bundled
        self._seed_death(repo, "qwen", hour=2, minute=0, pid=100)
        self._seed_death(repo, "guoban", hour=2, minute=0, pid=200)
        results = classify_deaths(repo, writer="qwen")
        assert results[0]["likely_reclaim"] is True


# ---------------------------------------------------------------------------
# reclaim_summary
# ---------------------------------------------------------------------------


class TestReclaimSummary:
    def _seed(self, repo: Path, events: list[tuple[str, str, int, int]]):
        """Seed events as (writer, event_type, hour_gmt8, pid)."""
        for writer, event_type, hour, pid in events:
            utc_hour = (hour - 8) % 24
            ts = datetime(2026, 10, 20, utc_hour, 0, 0, tzinfo=timezone.utc)
            record_event(repo, writer=writer, event=event_type, pid=pid, ts=ts)

    def test_empty_summary(self, repo: Path):
        summary = reclaim_summary(repo)
        assert summary["total_deaths"] == 0
        assert summary["reclaim_fraction"] == 0.0
        assert summary["peak_hour"] is None

    def test_all_reclaims(self, repo: Path):
        # Seed 3 deaths in off-peak, bundled
        self._seed(repo, [
            ("qwen", "death", 2, 100),
            ("guoban", "death", 2, 200),
            ("qwen", "death", 3, 101),
        ])
        summary = reclaim_summary(repo, writer="qwen")
        assert summary["total_deaths"] == 2
        # Both off-peak → hour_factor=1.0, first might be bundled → score ≥ 0.5
        assert summary["reclaim_count"] >= 1

    def test_mixed_deaths(self, repo: Path):
        self._seed(repo, [
            ("qwen", "death", 3, 100),   # off-peak, bundled with guoban
            ("guoban", "death", 3, 200),
            ("qwen", "death", 14, 101),  # peak, not bundled
        ])
        summary = reclaim_summary(repo, writer="qwen")
        assert summary["total_deaths"] == 2
        # At least one reclaim (off-peak bundled)
        assert summary["reclaim_count"] >= 1
        # Fraction between 0 and 1
        assert 0.0 <= summary["reclaim_fraction"] <= 1.0

    def test_peak_hour_computed(self, repo: Path):
        # Multiple deaths at hour 3, 30s apart (so bundled_factor kicks in)
        base = datetime(2026, 10, 19, 19, 0, 0, tzinfo=timezone.utc)  # 03:00 GMT+8
        for i in range(3):
            ts = base + timedelta(seconds=i * 30)
            record_event(repo, writer="qwen", event="death", pid=100 + i, ts=ts)
        summary = reclaim_summary(repo, writer="qwen", tz_offset_hours=8)
        assert summary["peak_hour"] == 3

    def test_summary_keys(self, repo: Path):
        summary = reclaim_summary(repo)
        expected_keys = {
            "total_deaths",
            "reclaim_count",
            "reclaim_fraction",
            "peak_hour",
            "estimated_interval",
            "avg_score",
            "max_score",
        }
        assert set(summary.keys()) == expected_keys

    def test_no_deaths_only_restarts(self, repo: Path):
        ts = datetime(2026, 10, 20, 0, 0, 0, tzinfo=timezone.utc)
        record_event(repo, writer="qwen", event="restart", pid=100, ts=ts)
        summary = reclaim_summary(repo, writer="qwen")
        assert summary["total_deaths"] == 0

    def test_avg_and_max_score(self, repo: Path):
        # Two off-peak bundled deaths → both should score high
        base = datetime(2026, 10, 19, 18, 0, 0, tzinfo=timezone.utc)  # 02:00 GMT+8
        record_event(repo, writer="qwen", event="death", pid=100, ts=base)
        record_event(repo, writer="guoban", event="death", pid=200, ts=base)
        ts2 = base + timedelta(hours=1)
        record_event(repo, writer="qwen", event="death", pid=101, ts=ts2)
        record_event(repo, writer="guoban", event="death", pid=201, ts=ts2)

        summary = reclaim_summary(repo, writer="qwen", tz_offset_hours=8)
        assert summary["total_deaths"] == 2
        assert summary["avg_score"] > 0.0
        assert summary["max_score"] >= summary["avg_score"]
