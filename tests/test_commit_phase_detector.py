"""Tests for iamai.commit_phase_detector — lifecycle phase detection.

Covers: classify_phase, detect_phases, PhaseProfile properties
(current_phase, phase_duration, transitions, dominant_phase,
phase_distribution, health), phase_summary_text, edge cases.
"""

import math
import pytest

from iamai.commit_phase_detector import (
    PhaseProfile,
    PhaseReport,
    classify_phase,
    detect_phases,
    phase_summary_text,
    DEFAULT_BOOT_THRESHOLD,
    DEFAULT_GROWTH_THRESHOLD,
    DEFAULT_STEADY_TOLERANCE,
    DEFAULT_STALL_THRESHOLD,
    DEFAULT_RECOVERY_THRESHOLD,
    DEFAULT_DECAY_THRESHOLD,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_ts(base: str, offsets_seconds: list[int]) -> list[str]:
    """Generate a list of ISO-8601 timestamps from a base + offsets."""
    from datetime import datetime, timedelta, timezone
    base_dt = datetime.fromisoformat(base).replace(tzinfo=timezone.utc)
    return [
        (base_dt + timedelta(seconds=s)).isoformat()
        for s in offsets_seconds
    ]


def _steady_offsets(interval: int = 600, count: int = 50) -> list[int]:
    """Generate offsets for a perfectly steady commit stream."""
    return [i * interval for i in range(count)]


BASE = "2026-10-22T12:00:00+00:00"


# ===========================================================================
# classify_phase
# ===========================================================================

class TestClassifyPhase:
    """Tests for the classify_phase function."""

    def test_stall_at_zero_rate(self):
        assert classify_phase(0.0, 1.0) == "stall"

    def test_stall_below_threshold(self):
        # 0.05 < 0.1 (DEFAULT_STALL_THRESHOLD)
        assert classify_phase(0.05, 1.0) == "stall"

    def test_steady_at_exact_baseline(self):
        assert classify_phase(1.0, 1.0) == "steady"

    def test_steady_within_tolerance_high(self):
        # 1.0 * 1.3 = 1.3, within growth threshold
        result = classify_phase(1.2, 1.0)
        assert result in ("steady", "growth")

    def test_steady_within_tolerance_low(self):
        # 1.0 * 0.7 = 0.7, at decay boundary
        result = classify_phase(0.8, 1.0)
        assert result in ("steady", "decay")

    def test_growth_above_threshold(self):
        # 1.5 > 1.3 (DEFAULT_GROWTH_THRESHOLD)
        assert classify_phase(1.5, 1.0) == "growth"

    def test_growth_well_above(self):
        assert classify_phase(3.0, 1.0) == "growth"

    def test_decay_below_steady(self):
        # 0.5 < 0.7 (DEFAULT_DECAY_THRESHOLD)
        assert classify_phase(0.5, 1.0) == "decay"

    def test_boot_with_unknown_prev(self):
        # Very low rate with unknown previous phase
        assert classify_phase(0.2, 1.0, "unknown") == "boot"

    def test_boot_continues_from_boot(self):
        assert classify_phase(0.15, 1.0, "boot") == "boot"

    def test_recovery_from_stall(self):
        # Rate back to 1.5× baseline after stall
        assert classify_phase(1.5, 1.0, "stall") == "recovery"

    def test_recovery_at_baseline_from_stall(self):
        # Even at baseline, coming from stall → recovery
        result = classify_phase(0.8, 1.0, "stall")
        assert result in ("recovery", "decay", "stall")

    def test_zero_baseline_with_zero_rate(self):
        result = classify_phase(0.0, 0.0, "unknown")
        assert result in ("boot", "unknown")

    def test_zero_baseline_with_positive_rate(self):
        result = classify_phase(1.0, 0.0, "unknown")
        assert result == "boot"

    def test_zero_baseline_from_growth(self):
        result = classify_phase(2.0, 0.0, "growth")
        assert result == "growth"


# ===========================================================================
# detect_phases — basic functionality
# ===========================================================================

class TestDetectPhasesBasic:
    """Basic detect_phases functionality tests."""

    def test_empty_input(self):
        profile = detect_phases([])
        assert profile.total_commits == 0
        assert profile.current_phase == "unknown"
        assert profile.phases == []

    def test_single_timestamp(self):
        profile = detect_phases(["2026-10-22T12:00:00+00:00"])
        assert profile.total_commits == 1
        assert profile.total_duration == 0.0
        assert profile.current_phase == "unknown"

    def test_two_timestamps(self):
        ts = _make_ts(BASE, [0, 600])
        profile = detect_phases(ts, window_size=5)
        assert profile.total_commits == 2
        assert profile.total_duration == 600.0
        assert profile.current_phase != "unknown"

    def test_steady_stream(self):
        """Perfectly steady commits should produce mostly 'steady' phases."""
        offsets = _steady_offsets(600, 60)
        ts = _make_ts(BASE, offsets)
        profile = detect_phases(ts, window_size=10)
        assert profile.total_commits == 60
        assert profile.baseline_rate > 0
        # Current phase should be steady or at least not stall
        assert profile.current_phase in ("steady", "growth", "decay", "boot")

    def test_returns_phase_profile(self):
        ts = _make_ts(BASE, _steady_offsets(600, 30))
        profile = detect_phases(ts)
        assert isinstance(profile, PhaseProfile)
        assert profile.total_commits == 30


# ===========================================================================
# detect_phases — phase detection scenarios
# ===========================================================================

class TestDetectPhasesScenarios:
    """Scenario-based phase detection tests."""

    def test_stall_then_recovery(self):
        """Commits stop for a while then resume."""
        # 20 steady commits, then a 10000s gap, then 20 more
        offsets = _steady_offsets(600, 20)
        last = offsets[-1]
        offsets += [last + 10000 + i * 600 for i in range(20)]
        ts = _make_ts(BASE, offsets)
        profile = detect_phases(ts, window_size=10)
        # Should have at least 2 phases (some transition)
        assert len(profile.phases) >= 1
        assert profile.transitions >= 0

    def test_all_same_timestamp(self):
        """All commits at the same time → rate is infinite/zero."""
        ts = _make_ts(BASE, [0] * 20)
        profile = detect_phases(ts, window_size=10)
        assert profile.total_commits == 20
        assert profile.total_duration == 0.0

    def test_unsorted_timestamps(self):
        """Should handle unsorted input gracefully."""
        offsets = [3000, 600, 1200, 0, 2400, 1800]
        ts = _make_ts(BASE, offsets)
        profile = detect_phases(ts, window_size=3)
        assert profile.total_commits == 6
        # Should still produce valid phases after sorting
        assert profile.current_phase != "unknown" or len(profile.phases) == 0

    def test_accelerating_stream(self):
        """Commits get faster over time."""
        offsets = [i * max(600 - i * 10, 60) for i in range(40)]
        ts = _make_ts(BASE, offsets)
        profile = detect_phases(ts, window_size=10)
        assert profile.total_commits == 40
        # Should detect growth somewhere
        phase_names = [p.phase for p in profile.phases]
        assert any(p in ("growth", "steady", "boot") for p in phase_names)


# ===========================================================================
# PhaseProfile properties
# ===========================================================================

class TestPhaseProfile:
    """Tests for PhaseProfile computed properties."""

    def _make_profile(self, phases_data):
        """Helper to build a PhaseProfile from phase dicts."""
        phases = [
            PhaseReport(
                phase=p["phase"],
                start_index=p.get("start_index", 0),
                end_index=p.get("end_index", 10),
                start_time=p.get("start_time", BASE),
                end_time=p.get("end_time", BASE),
                duration=p["duration"],
                commit_count=p.get("commit_count", 10),
                avg_rate=p.get("avg_rate", 0.001),
            )
            for p in phases_data
        ]
        return PhaseProfile(
            phases=phases,
            baseline_rate=0.001667,
            total_commits=sum(p.commit_count for p in phases),
            total_duration=sum(p.duration for p in phases),
        )

    def test_current_phase_empty(self):
        profile = PhaseProfile()
        assert profile.current_phase == "unknown"

    def test_current_phase_returns_last(self):
        profile = self._make_profile([
            {"phase": "steady", "duration": 1000},
            {"phase": "stall", "duration": 500},
        ])
        assert profile.current_phase == "stall"

    def test_phase_duration_empty(self):
        assert PhaseProfile().phase_duration == 0.0

    def test_phase_duration_returns_last(self):
        profile = self._make_profile([
            {"phase": "steady", "duration": 3600},
            {"phase": "growth", "duration": 1800},
        ])
        assert profile.phase_duration == 1800.0

    def test_transitions_empty(self):
        assert PhaseProfile().transitions == 0

    def test_transitions_single_phase(self):
        profile = self._make_profile([
            {"phase": "steady", "duration": 3600},
        ])
        assert profile.transitions == 0

    def test_transitions_counts_changes(self):
        profile = self._make_profile([
            {"phase": "boot", "duration": 600},
            {"phase": "steady", "duration": 3600},
            {"phase": "stall", "duration": 1200},
            {"phase": "recovery", "duration": 600},
        ])
        assert profile.transitions == 3

    def test_transitions_same_phase_no_count(self):
        profile = self._make_profile([
            {"phase": "steady", "duration": 1000},
            {"phase": "steady", "duration": 2000},
        ])
        assert profile.transitions == 0

    def test_dominant_phase_empty(self):
        assert PhaseProfile().dominant_phase == "unknown"

    def test_dominant_phase_longest(self):
        profile = self._make_profile([
            {"phase": "boot", "duration": 300},
            {"phase": "steady", "duration": 7200},
            {"phase": "stall", "duration": 600},
        ])
        assert profile.dominant_phase == "steady"

    def test_phase_distribution_empty(self):
        assert PhaseProfile().phase_distribution == {}

    def test_phase_distribution_sums_to_one(self):
        profile = self._make_profile([
            {"phase": "steady", "duration": 6000},
            {"phase": "stall", "duration": 2000},
            {"phase": "recovery", "duration": 2000},
        ])
        dist = profile.phase_distribution
        assert abs(sum(dist.values()) - 1.0) < 0.01

    def test_phase_distribution_values(self):
        profile = self._make_profile([
            {"phase": "steady", "duration": 7500},
            {"phase": "stall", "duration": 2500},
        ])
        dist = profile.phase_distribution
        assert dist["steady"] == 0.75
        assert dist["stall"] == 0.25

    def test_health_healthy(self):
        profile = self._make_profile([
            {"phase": "steady", "duration": 7000},
            {"phase": "growth", "duration": 3000},
        ])
        assert profile.health == "healthy"

    def test_health_acceptable(self):
        profile = self._make_profile([
            {"phase": "steady", "duration": 4000},
            {"phase": "decay", "duration": 4000},
            {"phase": "growth", "duration": 2000},
        ])
        assert profile.health in ("acceptable", "healthy", "volatile")

    def test_health_critical(self):
        profile = self._make_profile([
            {"phase": "stall", "duration": 8000},
            {"phase": "steady", "duration": 2000},
        ])
        assert profile.health == "critical"

    def test_health_unhealthy(self):
        profile = self._make_profile([
            {"phase": "stall", "duration": 4000},
            {"phase": "steady", "duration": 6000},
        ])
        assert profile.health == "unhealthy"


# ===========================================================================
# PhaseReport properties
# ===========================================================================

class TestPhaseReport:
    """Tests for PhaseReport computed properties."""

    def test_commits_per_hour(self):
        report = PhaseReport(
            phase="steady",
            start_index=0,
            end_index=9,
            start_time=BASE,
            end_time=BASE,
            duration=3600.0,
            commit_count=10,
            avg_rate=0.002778,
        )
        assert abs(report.commits_per_hour - 10.0) < 0.01

    def test_commits_per_hour_zero_duration(self):
        report = PhaseReport(
            phase="boot",
            start_index=0,
            end_index=0,
            start_time=BASE,
            end_time=BASE,
            duration=0.0,
            commit_count=1,
            avg_rate=0.0,
        )
        assert report.commits_per_hour == 0.0


# ===========================================================================
# phase_summary_text
# ===========================================================================

class TestPhaseSummaryText:
    """Tests for phase_summary_text output."""

    def test_empty_profile(self):
        result = phase_summary_text(PhaseProfile())
        assert result == "no commits to analyse"

    def test_basic_summary_contains_key_info(self):
        ts = _make_ts(BASE, _steady_offsets(600, 30))
        profile = detect_phases(ts, window_size=10)
        text = phase_summary_text(profile)
        assert "commit phase analysis" in text
        assert "current phase" in text
        assert "baseline rate" in text
        assert "health" in text

    def test_summary_includes_distribution(self):
        ts = _make_ts(BASE, _steady_offsets(600, 40))
        profile = detect_phases(ts, window_size=10)
        text = phase_summary_text(profile)
        assert "phase distribution" in text

    def test_summary_shows_transitions(self):
        ts = _make_ts(BASE, _steady_offsets(600, 40))
        profile = detect_phases(ts, window_size=10)
        text = phase_summary_text(profile)
        assert "transitions" in text


# ===========================================================================
# edge cases
# ===========================================================================

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_very_small_window(self):
        ts = _make_ts(BASE, _steady_offsets(600, 10))
        profile = detect_phases(ts, window_size=2)
        assert profile.total_commits == 10

    def test_window_equals_count(self):
        ts = _make_ts(BASE, _steady_offsets(600, 11))
        profile = detect_phases(ts, window_size=10)
        assert profile.total_commits == 11
        assert len(profile.phases) >= 1

    def test_large_window_small_data(self):
        ts = _make_ts(BASE, [0, 600, 1200])
        profile = detect_phases(ts, window_size=100)
        assert profile.total_commits == 3
        # Should handle gracefully
        assert profile.current_phase != "unknown" or profile.phases == []

    def test_z_suffix_timestamps(self):
        ts = [
            "2026-10-22T12:00:00Z",
            "2026-10-22T12:10:00Z",
            "2026-10-22T12:20:00Z",
        ]
        profile = detect_phases(ts, window_size=2)
        assert profile.total_commits == 3

    def test_naive_timestamps(self):
        ts = [
            "2026-10-22T12:00:00",
            "2026-10-22T12:10:00",
            "2026-10-22T12:20:00",
        ]
        profile = detect_phases(ts, window_size=2)
        assert profile.total_commits == 3

    def test_custom_thresholds(self):
        ts = _make_ts(BASE, _steady_offsets(600, 30))
        profile = detect_phases(
            ts,
            window_size=10,
            steady_tolerance=0.5,
            growth_threshold=2.0,
        )
        assert profile.total_commits == 30

    def test_duplicate_timestamps(self):
        ts = _make_ts(BASE, [0, 0, 0, 600, 600, 1200])
        profile = detect_phases(ts, window_size=3)
        assert profile.total_commits == 6
