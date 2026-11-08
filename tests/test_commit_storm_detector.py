"""Tests for iamai.commit_storm_detector module."""

import pytest

from iamai.commit_storm_detector import CommitStormDetector, storm_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _even_spaced(start, interval, count):
    """Generate evenly spaced timestamps."""
    return [start + i * interval for i in range(count)]


def _inject_burst(base_times, burst_start, burst_count, burst_interval=2.0):
    """Insert a cluster of rapid commits starting at burst_start."""
    burst = [burst_start + i * burst_interval for i in range(burst_count)]
    return sorted(base_times + burst)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def calm_commits():
    """20 commits, one every 600s — perfectly calm."""
    return _even_spaced(1_000_000, 600, 20)


@pytest.fixture
def stormy_commits():
    """10 calm commits then a burst of 15 in 60s."""
    calm = _even_spaced(1_000_000, 600, 10)
    burst = _even_spaced(calm[-1] + 10, 4.0, 15)
    return sorted(calm + burst)


@pytest.fixture
def all_storm():
    """Every commit is in a storm — 20 commits in 60s."""
    return _even_spaced(1_000_000, 3.0, 20)


@pytest.fixture
def empty():
    return []


# ---------------------------------------------------------------------------
# Basic detection
# ---------------------------------------------------------------------------


class TestBasicDetection:
    def test_calm_is_calm(self, calm_commits):
        csd = CommitStormDetector(calm_commits, window_s=300, threshold=5)
        assert csd.storm_commits() == 0
        assert csd.storm_ratio == 0.0
        assert csd.verdict == "calm"

    def test_all_storm(self, all_storm):
        csd = CommitStormDetector(all_storm, window_s=300, threshold=3)
        assert csd.storm_commits() > 0
        assert csd.storm_ratio > 0.0

    def test_empty_input(self, empty):
        csd = CommitStormDetector(empty)
        assert csd.storm_commits() == 0
        assert csd.storm_ratio == 0.0
        assert csd.verdict == "calm"

    def test_fewer_than_threshold(self):
        csd = CommitStormDetector([1.0, 2.0, 3.0], window_s=10, threshold=5)
        assert csd.storm_commits() == 0


# ---------------------------------------------------------------------------
# Storm ratio
# ---------------------------------------------------------------------------


class TestStormRatio:
    def test_storm_ratio_range(self, stormy_commits):
        csd = CommitStormDetector(stormy_commits, window_s=300, threshold=5)
        ratio = csd.storm_ratio
        assert 0.0 <= ratio <= 1.0

    def test_stormy_has_storms(self, stormy_commits):
        csd = CommitStormDetector(stormy_commits, window_s=300, threshold=5)
        assert csd.storm_commits() > 0

    def test_calm_ratio_zero(self, calm_commits):
        csd = CommitStormDetector(calm_commits, window_s=300, threshold=5)
        assert csd.storm_ratio == 0.0


# ---------------------------------------------------------------------------
# Bursts
# ---------------------------------------------------------------------------


class TestBursts:
    def test_no_bursts_when_calm(self, calm_commits):
        csd = CommitStormDetector(calm_commits, window_s=300, threshold=5)
        assert csd.bursts() == []
        assert csd.max_burst == 0
        assert csd.max_burst_duration_s == 0.0

    def test_burst_detected(self, stormy_commits):
        csd = CommitStormDetector(stormy_commits, window_s=300, threshold=5)
        assert len(csd.bursts()) >= 1

    def test_max_burst_positive(self, stormy_commits):
        csd = CommitStormDetector(stormy_commits, window_s=300, threshold=5)
        assert csd.max_burst > 0

    def test_burst_duration_positive(self, stormy_commits):
        csd = CommitStormDetector(stormy_commits, window_s=300, threshold=5)
        assert csd.max_burst_duration_s > 0.0

    def test_burst_structure(self):
        """Each burst is (start, end, count) with start <= end."""
        times = _even_spaced(0, 1.0, 10)  # all in one window
        csd = CommitStormDetector(times, window_s=300, threshold=3)
        for start, end, count in csd.bursts():
            assert start <= end
            assert count >= 3


# ---------------------------------------------------------------------------
# Verdict classification
# ---------------------------------------------------------------------------


class TestVerdict:
    def test_calm_verdict(self):
        csd = CommitStormDetector(
            _even_spaced(0, 1000, 50), window_s=300, threshold=5
        )
        assert csd.verdict == "calm"

    def test_tempest_verdict(self):
        # All commits in one burst
        times = _even_spaced(0, 1.0, 30)
        csd = CommitStormDetector(times, window_s=300, threshold=3)
        assert csd.verdict in ("stormy", "tempest")

    def test_breezy_verdict(self):
        # 50 calm + 5 storm = ~9%
        calm = _even_spaced(0, 600, 50)
        burst = _even_spaced(calm[-1] + 5, 2.0, 5)
        csd = CommitStormDetector(sorted(calm + burst), window_s=300, threshold=5)
        assert csd.verdict in ("calm", "breezy")


# ---------------------------------------------------------------------------
# Summary dict
# ---------------------------------------------------------------------------


class TestSummary:
    def test_summary_keys(self, calm_commits):
        csd = CommitStormDetector(calm_commits, window_s=300, threshold=5)
        s = csd.summary()
        expected = {
            "total_commits", "storm_commits", "calm_commits",
            "storm_ratio", "max_burst", "max_burst_duration_s",
            "num_bursts", "verdict",
        }
        assert set(s.keys()) == expected

    def test_summary_values_consistent(self, stormy_commits):
        csd = CommitStormDetector(stormy_commits, window_s=300, threshold=5)
        s = csd.summary()
        assert s["total_commits"] == s["storm_commits"] + s["calm_commits"]
        assert 0.0 <= s["storm_ratio"] <= 1.0
        assert s["num_bursts"] >= 0


# ---------------------------------------------------------------------------
# storm_report convenience function
# ---------------------------------------------------------------------------


class TestStormReport:
    def test_empty_report(self):
        r = storm_report([])
        assert "no commits" in r

    def test_calm_report(self, calm_commits):
        r = storm_report(calm_commits, window_s=300, threshold=5)
        assert "calm" in r

    def test_stormy_report(self, stormy_commits):
        r = storm_report(stormy_commits, window_s=300, threshold=5)
        assert "storm" in r

    def test_report_format(self, calm_commits):
        r = storm_report(calm_commits, window_s=300, threshold=5)
        assert "commits" in r
        assert "—" in r  # em dash before verdict


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_single_commit(self):
        csd = CommitStormDetector([42.0], window_s=300, threshold=5)
        assert csd.storm_commits() == 0

    def test_exact_threshold(self):
        """Exactly threshold commits in window → storm."""
        times = _even_spaced(0, 10, 5)
        csd = CommitStormDetector(times, window_s=300, threshold=5)
        # The 5th commit sees 5 commits in window → storm
        assert csd.storm_commits() >= 1

    def test_unsorted_input(self):
        """Detector should sort internally."""
        times = [100, 10, 50, 30, 70, 20, 90, 40, 60, 80]
        csd = CommitStormDetector(times, window_s=300, threshold=5)
        assert csd.commit_times == sorted(times)

    def test_duplicate_timestamps(self):
        """Multiple commits at the same time — storm once threshold is met."""
        times = [100.0] * 10
        csd = CommitStormDetector(times, window_s=300, threshold=5)
        # First 4 commits see fewer than 5 entries; commits 5-10 each see ≥5
        assert csd.storm_commits() == 6

    def test_large_window_catches_more(self):
        times = _even_spaced(0, 100, 20)
        small = CommitStormDetector(times, window_s=50, threshold=5)
        large = CommitStormDetector(times, window_s=5000, threshold=5)
        assert large.storm_commits() >= small.storm_commits()

    def test_high_threshold_fewer_storms(self):
        times = _even_spaced(0, 10, 30)
        low = CommitStormDetector(times, window_s=300, threshold=3)
        high = CommitStormDetector(times, window_s=300, threshold=20)
        assert high.storm_commits() <= low.storm_commits()
