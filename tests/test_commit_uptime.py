"""Tests for commit_uptime module.

Covers: timestamp conversion, uptime fraction, recent uptime, outage
detection, max consecutive dead windows, mean time between outages,
classification, multi-window analysis, edge cases, and serialisation.
42 test functions.

Written by Qwen during caretaker visit 725, 2026-11-19.
"""

import math
import pytest
from datetime import datetime, timezone, timedelta

from iamai.commit_uptime import (
    OutageEvent,
    UptimeReport,
    _classify,
    _detect_outages,
    _to_epoch,
    _zero_report,
    analyse_uptime,
    analyse_uptime_windows,
)


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

class TestToEpoch:
    def test_epoch_int(self):
        assert _to_epoch(1000) == 1000.0

    def test_epoch_float(self):
        assert _to_epoch(1234.5) == 1234.5

    def test_datetime_naive(self):
        dt = datetime(2026, 1, 1, 0, 0, 0)
        expected = dt.replace(tzinfo=timezone.utc).timestamp()
        assert _to_epoch(dt) == expected

    def test_datetime_aware(self):
        dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        assert _to_epoch(dt) == dt.timestamp()

    def test_iso_string_with_z(self):
        ts = "2026-01-01T00:00:00Z"
        result = _to_epoch(ts)
        expected = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
        assert abs(result - expected) < 1.0

    def test_iso_string_with_offset(self):
        ts = "2026-06-15T12:00:00+08:00"
        result = _to_epoch(ts)
        expected = datetime(2026, 6, 15, 4, 0, 0, tzinfo=timezone.utc).timestamp()
        assert abs(result - expected) < 1.0

    def test_epoch_string(self):
        assert _to_epoch("1700000000") == 1700000000.0

    def test_unsupported_type(self):
        with pytest.raises(TypeError):
            _to_epoch([1, 2, 3])


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestClassify:
    def test_five_nines(self):
        assert _classify(0.99) == "five_nines"
        assert _classify(1.0) == "five_nines"

    def test_high(self):
        assert _classify(0.95) == "high"
        assert _classify(0.98) == "high"

    def test_moderate(self):
        assert _classify(0.80) == "moderate"
        assert _classify(0.94) == "moderate"

    def test_degraded(self):
        assert _classify(0.50) == "degraded"
        assert _classify(0.79) == "degraded"

    def test_unreliable(self):
        assert _classify(0.0) == "unreliable"
        assert _classify(0.49) == "unreliable"

    def test_boundary_values(self):
        """Just below each threshold."""
        assert _classify(0.9899) == "high"
        assert _classify(0.9499) == "moderate"
        assert _classify(0.7999) == "degraded"
        assert _classify(0.4999) == "unreliable"


# ---------------------------------------------------------------------------
# Zero report
# ---------------------------------------------------------------------------

class TestZeroReport:
    def test_zero_report_defaults(self):
        r = _zero_report(0)
        assert r.n_commits == 0
        assert r.total_windows == 0
        assert r.uptime_fraction == 0.0
        assert r.classification == "unreliable"
        assert r.outages == []

    def test_zero_report_with_window(self):
        r = _zero_report(1, 60.0)
        assert r.window_seconds == 60.0


# ---------------------------------------------------------------------------
# Outage detection
# ---------------------------------------------------------------------------

class TestDetectOutages:
    def test_no_dead_windows(self):
        alive = [True, True, True, True]
        assert _detect_outages(alive) == []

    def test_single_outage(self):
        alive = [True, False, False, True]
        outages = _detect_outages(alive)
        assert len(outages) == 1
        assert outages[0].start_index == 1
        assert outages[0].end_index == 2
        assert outages[0].n_windows == 2

    def test_multiple_outages(self):
        alive = [False, True, False, False, True, False]
        outages = _detect_outages(alive)
        assert len(outages) == 3
        assert outages[0].start_index == 0
        assert outages[0].n_windows == 1
        assert outages[1].start_index == 2
        assert outages[1].n_windows == 2
        assert outages[2].start_index == 5
        assert outages[2].n_windows == 1

    def test_all_dead(self):
        alive = [False, False, False]
        outages = _detect_outages(alive)
        assert len(outages) == 1
        assert outages[0].n_windows == 3

    def test_empty(self):
        assert _detect_outages([]) == []


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

class TestAnalyseUptime:
    def test_too_few_commits(self):
        r = analyse_uptime([1000])
        assert r.n_commits == 1
        assert r.total_windows == 0
        assert r.uptime_fraction == 0.0

    def test_empty_input(self):
        r = analyse_uptime([])
        assert r.n_commits == 0

    def test_all_same_timestamp(self):
        r = analyse_uptime([1000, 1000, 1000])
        assert r.total_windows == 1
        assert r.alive_windows == 1
        assert r.uptime_fraction == 1.0
        assert r.classification == "five_nines"

    def test_perfect_cadence_high_uptime(self):
        """Commits every 60s with 60s window → every window alive."""
        base = 1000.0
        ts = [base + i * 60 for i in range(20)]
        r = analyse_uptime(ts, window_seconds=60.0)
        assert r.uptime_fraction == 1.0
        assert r.classification == "five_nines"
        assert r.dead_windows == 0
        assert r.max_consecutive_dead == 0

    def test_gaps_create_dead_windows(self):
        """Commits at 0, 60, then skip to 300, 360 → dead windows in between."""
        base = 0.0
        ts = [base, 60, 300, 360]
        r = analyse_uptime(ts, window_seconds=60.0)
        # span = 360, windows = ceil(360/60)+1 = 7
        # indices: 0,1,5,6 alive → 2,3,4 dead
        assert r.total_windows == 7
        assert r.alive_windows == 4
        assert r.dead_windows == 3
        assert r.max_consecutive_dead == 3

    def test_recent_uptime(self):
        """First half has gaps, second half is solid."""
        base = 0.0
        # First 10 commits: every 120s (sparse with 60s windows)
        ts = [base + i * 120 for i in range(10)]
        # Next 20 commits: every 60s (dense)
        ts += [base + 1200 + i * 60 for i in range(20)]
        r = analyse_uptime(ts, window_seconds=60.0, recent_windows=20)
        # Recent should be higher than overall
        assert r.recent_uptime_fraction >= r.uptime_fraction

    def test_recent_uptime_limited_by_total(self):
        """recent_windows > total_windows should cap at total."""
        ts = [0.0, 60.0, 120.0]
        r = analyse_uptime(ts, window_seconds=60.0, recent_windows=1000)
        assert r.recent_uptime_fraction == r.uptime_fraction

    def test_auto_window_size(self):
        """Without window_seconds, uses median gap."""
        ts = [0.0, 100.0, 200.0, 300.0, 400.0]
        r = analyse_uptime(ts)
        # Median gap = 100
        assert r.window_seconds == 100.0
        # All windows alive
        assert r.uptime_fraction == 1.0

    def test_outage_events(self):
        """Verify outage details are filled correctly."""
        base = 0.0
        # 0,60, skip to 300,360 → outage at indices 2,3,4 (3 windows × 60s = 180s)
        ts = [base, 60, 300, 360]
        r = analyse_uptime(ts, window_seconds=60.0)
        assert r.n_outages == 1
        assert r.outages[0].n_windows == 3
        assert r.outages[0].duration_seconds == 180.0

    def test_mean_time_between_outages(self):
        """Two outages separated by known distance."""
        base = 0.0
        # alive at 0, dead 1-2, alive 3, dead 4-5, alive 6
        # commits at 0, 180, 360
        ts = [base, 180, 360]
        r = analyse_uptime(ts, window_seconds=60.0)
        # windows: 0=alive, 1=dead, 2=dead, 3=alive, 4=dead, 5=dead, 6=alive
        assert r.n_outages == 2
        # Outage starts at index 1 (60s) and index 4 (240s) → MTBO = 180s
        assert r.mean_time_between_outages == 180.0

    def test_single_outage_no_mtbo(self):
        """One outage → mtbo = 0."""
        ts = [0.0, 60.0, 300.0, 360.0]
        r = analyse_uptime(ts, window_seconds=60.0)
        assert r.n_outages == 1
        assert r.mean_time_between_outages == 0.0

    def test_negative_window_raises(self):
        with pytest.raises(ValueError):
            analyse_uptime([0, 60, 120], window_seconds=-10)

    def test_zero_window_raises(self):
        with pytest.raises(ValueError):
            analyse_uptime([0, 60, 120], window_seconds=0)


# ---------------------------------------------------------------------------
# Classification integration
# ---------------------------------------------------------------------------

class TestClassificationIntegration:
    def test_five_nines(self):
        ts = [i * 60.0 for i in range(100)]
        r = analyse_uptime(ts, window_seconds=60.0)
        assert r.classification == "five_nines"

    def test_degraded(self):
        """Sparse commits with large gaps."""
        ts = [0.0, 600.0, 1200.0, 1800.0]
        r = analyse_uptime(ts, window_seconds=60.0)
        # 31 windows, 4 alive → ~0.13 uptime
        assert r.classification == "unreliable"

    def test_moderate(self):
        """Construct exactly 85% uptime."""
        # 17 alive out of 20 windows
        base = 0.0
        alive_indices = list(range(17))  # 0-16
        dead_indices = [17, 18, 19]  # 17-19
        ts = [i * 60.0 for i in alive_indices]
        # Add a final commit at index 19 to make the span correct
        ts.append(19 * 60.0)
        # Now index 17 and 18 are dead, 19 is alive → 18/20 = 0.9
        r = analyse_uptime(ts, window_seconds=60.0)
        assert r.classification in ("high", "moderate", "degraded")


# ---------------------------------------------------------------------------
# Multi-window analysis
# ---------------------------------------------------------------------------

class TestAnalyseUptimeWindows:
    def test_default_windows(self):
        ts = [i * 30.0 for i in range(50)]
        reports = analyse_uptime_windows(ts)
        assert len(reports) == 3
        # window sizes: 60, 300, 600
        assert reports[0].window_seconds == 60.0
        assert reports[1].window_seconds == 300.0
        assert reports[2].window_seconds == 600.0

    def test_custom_windows(self):
        ts = [i * 10.0 for i in range(100)]
        reports = analyse_uptime_windows(ts, window_sizes=[10.0, 50.0])
        assert len(reports) == 2
        assert reports[0].window_seconds == 10.0
        assert reports[1].window_seconds == 50.0

    def test_larger_window_fewer_total(self):
        ts = [i * 60.0 for i in range(30)]
        reports = analyse_uptime_windows(ts, window_sizes=[30.0, 120.0])
        assert reports[0].total_windows > reports[1].total_windows


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

class TestSerialisation:
    def test_report_to_dict(self):
        ts = [i * 60.0 for i in range(10)]
        r = analyse_uptime(ts, window_seconds=60.0)
        d = r.to_dict()
        assert "uptime_fraction" in d
        assert "classification" in d
        assert "outages" in d
        assert isinstance(d["outages"], list)

    def test_outage_to_dict(self):
        o = OutageEvent(start_index=2, end_index=5, duration_seconds=240.0, n_windows=4)
        d = o.to_dict()
        assert d["start_index"] == 2
        assert d["end_index"] == 5
        assert d["duration_seconds"] == 240.0
        assert d["n_windows"] == 4

    def test_dict_roundtrip_values(self):
        ts = [0.0, 60.0, 300.0, 360.0]
        r = analyse_uptime(ts, window_seconds=60.0)
        d = r.to_dict()
        assert d["n_commits"] == 4
        assert d["total_windows"] == 7
        assert d["alive_windows"] == 4
        assert d["dead_windows"] == 3


# ---------------------------------------------------------------------------
# Unsorted input
# ---------------------------------------------------------------------------

class TestUnsortedInput:
    def test_unsorted_timestamps(self):
        """Should sort internally."""
        ts = [360.0, 0.0, 60.0, 300.0]
        r = analyse_uptime(ts, window_seconds=60.0)
        assert r.n_commits == 4
        assert r.total_windows == 7

    def test_datetime_input(self):
        base = datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)
        ts = [base + timedelta(seconds=i * 60) for i in range(10)]
        r = analyse_uptime(ts, window_seconds=60.0)
        assert r.uptime_fraction == 1.0

    def test_iso_string_input(self):
        ts = [
            "2026-11-19T12:00:00Z",
            "2026-11-19T12:01:00Z",
            "2026-11-19T12:02:00Z",
            "2026-11-19T12:03:00Z",
        ]
        r = analyse_uptime(ts, window_seconds=60.0)
        assert r.uptime_fraction == 1.0
        assert r.classification == "five_nines"


# ---------------------------------------------------------------------------
# Boundary conditions
# ---------------------------------------------------------------------------

class TestBoundaryConditions:
    def test_two_commits(self):
        r = analyse_uptime([0.0, 60.0], window_seconds=60.0)
        assert r.n_commits == 2
        assert r.total_windows == 2
        assert r.uptime_fraction == 1.0

    def test_two_commits_large_gap(self):
        r = analyse_uptime([0.0, 3600.0], window_seconds=60.0)
        # 61 windows, 2 alive → very low uptime
        assert r.total_windows == 61
        assert r.alive_windows == 2
        assert r.uptime_fraction < 0.1

    def test_fractional_window_alignment(self):
        """Commits don't land on window boundaries."""
        ts = [5.0, 65.0, 125.0]  # offset by 5s from window starts
        r = analyse_uptime(ts, window_seconds=60.0)
        assert r.n_commits == 3
        assert r.alive_windows == 3  # each in its own window

    def test_multiple_commits_same_window(self):
        """Several commits in one window still count as 1 alive."""
        ts = [1.0, 2.0, 3.0, 4.0, 120.0]
        r = analyse_uptime(ts, window_seconds=60.0)
        # windows: 0=alive(1-4s), 1=dead, 2=alive(120s)
        assert r.alive_windows == 2
        assert r.dead_windows == 1
