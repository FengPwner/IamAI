"""Tests for iamai.commit_gap_analyzer — commit timing rhythm analysis.

Covers: classify_gap, analyze_single_gap, analyze_gaps (aggregate),
GapProfile properties (health, score, ratios), recent_trend,
gap_summary_text, and edge cases.
"""

import math
import pytest

from iamai.commit_gap_analyzer import (
    GapProfile,
    GapReport,
    analyze_gaps,
    analyze_single_gap,
    classify_gap,
    gap_summary_text,
    recent_trend,
    DEFAULT_BATCH_INTERVAL,
    DEFAULT_TOLERANCE,
    DEFAULT_DEAD_THRESHOLD,
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


# ===========================================================================
# classify_gap
# ===========================================================================

class TestClassifyGap:
    """Tests for the classify_gap function."""

    def test_regular_at_exact_interval(self):
        assert classify_gap(600.0) == "regular"

    def test_regular_within_tolerance_low(self):
        # 600 * 0.70 = 420 is the lower bound
        assert classify_gap(420.0) == "regular"

    def test_regular_within_tolerance_high(self):
        # 600 * 1.30 = 780 is the upper bound
        assert classify_gap(780.0) == "regular"

    def test_regular_mid_range(self):
        assert classify_gap(550.0) == "regular"
        assert classify_gap(650.0) == "regular"

    def test_accelerated_below_lower(self):
        assert classify_gap(300.0) == "accelerated"
        assert classify_gap(100.0) == "accelerated"
        assert classify_gap(419.0) == "accelerated"

    def test_stalled_above_upper(self):
        assert classify_gap(781.0) == "stalled"
        assert classify_gap(1200.0) == "stalled"

    def test_dead_at_threshold(self):
        assert classify_gap(1800.0) == "dead"

    def test_dead_above_threshold(self):
        assert classify_gap(3600.0) == "dead"
        assert classify_gap(7200.0) == "dead"

    def test_dead_takes_priority_over_stalled(self):
        # A gap of 2000s is both stalled and dead; dead wins
        assert classify_gap(2000.0) == "dead"

    def test_zero_gap_is_regular(self):
        assert classify_gap(0.0) == "regular"

    def test_negative_gap_is_regular(self):
        assert classify_gap(-10.0) == "regular"

    def test_custom_batch_interval(self):
        # With batch_interval=120 and tolerance=0.25:
        # regular range = [90, 150]
        assert classify_gap(100.0, batch_interval=120.0, tolerance=0.25) == "regular"
        assert classify_gap(80.0, batch_interval=120.0, tolerance=0.25) == "accelerated"
        assert classify_gap(160.0, batch_interval=120.0, tolerance=0.25) == "stalled"

    def test_custom_dead_threshold(self):
        assert classify_gap(500.0, dead_threshold=400.0) == "dead"
        assert classify_gap(500.0, dead_threshold=600.0) == "regular"

    def test_boundary_just_below_regular(self):
        # 419.99 is just below the lower bound of 420
        assert classify_gap(419.99) == "accelerated"

    def test_boundary_just_above_regular(self):
        # 780.01 is just above the upper bound of 780
        assert classify_gap(780.01) == "stalled"


# ===========================================================================
# analyze_single_gap
# ===========================================================================

class TestAnalyzeSingleGap:
    """Tests for the analyze_single_gap function."""

    def test_returns_gap_report(self):
        report = analyze_single_gap(600.0)
        assert isinstance(report, GapReport)

    def test_gap_seconds_preserved(self):
        report = analyze_single_gap(456.7)
        assert report.gap_seconds == 456.7

    def test_gap_type_matches_classify(self):
        for gap_s in [100, 500, 600, 800, 1500, 2000]:
            report = analyze_single_gap(float(gap_s))
            assert report.gap_type == classify_gap(float(gap_s))

    def test_deviation_zero_at_exact_interval(self):
        report = analyze_single_gap(600.0)
        assert report.deviation == pytest.approx(0.0)

    def test_deviation_negative_when_fast(self):
        report = analyze_single_gap(300.0)
        assert report.deviation < 0.0
        assert report.deviation == pytest.approx(-0.5)

    def test_deviation_positive_when_slow(self):
        report = analyze_single_gap(900.0)
        assert report.deviation > 0.0
        assert report.deviation == pytest.approx(0.5)

    def test_z_score_none_without_population(self):
        report = analyze_single_gap(600.0)
        assert report.z_score is None

    def test_z_score_computed_with_population(self):
        report = analyze_single_gap(700.0, mean_gap=600.0, std_gap=100.0)
        assert report.z_score == pytest.approx(1.0)

    def test_z_score_zero_at_mean(self):
        report = analyze_single_gap(600.0, mean_gap=600.0, std_gap=100.0)
        assert report.z_score == pytest.approx(0.0)

    def test_z_score_none_when_std_zero(self):
        report = analyze_single_gap(600.0, mean_gap=600.0, std_gap=0.0)
        assert report.z_score is None


# ===========================================================================
# analyze_gaps (aggregate)
# ===========================================================================

class TestAnalyzeGaps:
    """Tests for the analyze_gaps function."""

    def test_empty_timestamps(self):
        profile = analyze_gaps([])
        assert profile.total_gaps == 0
        assert profile.health == "unknown"

    def test_single_timestamp(self):
        profile = analyze_gaps(["2026-10-22T10:00:00+00:00"])
        assert profile.total_gaps == 0

    def test_two_regular_timestamps(self):
        ts = _make_ts("2026-10-22T10:00:00", [0, 600])
        profile = analyze_gaps(ts)
        assert profile.total_gaps == 1
        assert profile.regular_count == 1
        assert profile.health == "rhythmic"

    def test_all_regular(self):
        ts = _make_ts("2026-10-22T10:00:00", [0, 600, 1200, 1800, 2400])
        profile = analyze_gaps(ts)
        assert profile.total_gaps == 4
        assert profile.regular_count == 4
        assert profile.health == "rhythmic"
        assert profile.regular_ratio == 1.0

    def test_mixed_gaps(self):
        # regular(600), accelerated(200), stalled(900), dead(2000)
        ts = _make_ts("2026-10-22T10:00:00", [0, 600, 800, 1700, 3700])
        profile = analyze_gaps(ts)
        assert profile.total_gaps == 4
        assert profile.regular_count == 1
        assert profile.accelerated_count == 1
        assert profile.stalled_count == 1
        assert profile.dead_count == 1

    def test_statistics_computed(self):
        ts = _make_ts("2026-10-22T10:00:00", [0, 600, 1200, 1800])
        profile = analyze_gaps(ts)
        assert profile.mean_gap == pytest.approx(600.0)
        assert profile.median_gap == pytest.approx(600.0)
        assert profile.std_gap == pytest.approx(0.0, abs=0.01)
        assert profile.min_gap == pytest.approx(600.0)
        assert profile.max_gap == pytest.approx(600.0)

    def test_z_scores_populated(self):
        # With varied gaps, z-scores should be computed
        ts = _make_ts("2026-10-22T10:00:00", [0, 400, 1000, 1600])
        profile = analyze_gaps(ts)
        for gap in profile.gaps:
            assert gap.z_score is not None

    def test_unsorted_timestamps_get_sorted(self):
        # Pass timestamps out of order — should still work
        ts = [
            "2026-10-22T10:10:00+00:00",
            "2026-10-22T10:00:00+00:00",
            "2026-10-22T10:20:00+00:00",
        ]
        profile = analyze_gaps(ts)
        assert profile.total_gaps == 2
        assert profile.mean_gap == pytest.approx(600.0)

    def test_large_number_of_gaps(self):
        offsets = [i * 600 for i in range(101)]
        ts = _make_ts("2026-10-22T00:00:00", offsets)
        profile = analyze_gaps(ts)
        assert profile.total_gaps == 100
        assert profile.regular_count == 100


# ===========================================================================
# GapProfile properties
# ===========================================================================

class TestGapProfileProperties:
    """Tests for GapProfile computed properties."""

    def test_regular_ratio_empty(self):
        p = GapProfile()
        assert p.regular_ratio == 0.0

    def test_regular_ratio_all_regular(self):
        p = GapProfile(total_gaps=10, regular_count=10)
        assert p.regular_ratio == 1.0

    def test_regular_ratio_mixed(self):
        p = GapProfile(total_gaps=10, regular_count=7)
        assert p.regular_ratio == pytest.approx(0.7)

    def test_dead_ratio_empty(self):
        p = GapProfile()
        assert p.dead_ratio == 0.0

    def test_dead_ratio_some_dead(self):
        p = GapProfile(total_gaps=20, dead_count=4)
        assert p.dead_ratio == pytest.approx(0.2)

    def test_health_unknown_empty(self):
        p = GapProfile()
        assert p.health == "unknown"

    def test_health_rhythmic(self):
        # ≥80% regular, ≤1 dead
        p = GapProfile(total_gaps=10, regular_count=9, dead_count=0)
        assert p.health == "rhythmic"

    def test_health_rhythmic_with_one_dead(self):
        p = GapProfile(total_gaps=10, regular_count=8, dead_count=1)
        assert p.health == "rhythmic"

    def test_health_irregular(self):
        # ≥50% regular but not enough for rhythmic
        p = GapProfile(total_gaps=10, regular_count=6, dead_count=1)
        assert p.health == "irregular"

    def test_health_erratic_low_regular(self):
        p = GapProfile(total_gaps=10, regular_count=3, dead_count=0)
        assert p.health == "erratic"

    def test_health_erratic_many_dead(self):
        p = GapProfile(total_gaps=10, regular_count=7, dead_count=4)
        assert p.health == "erratic"

    def test_score_empty(self):
        p = GapProfile()
        assert p.score == 0.0

    def test_score_perfect(self):
        # All regular, no dead, zero variance
        p = GapProfile(
            total_gaps=10,
            regular_count=10,
            dead_count=0,
            mean_gap=600.0,
            std_gap=0.0,
        )
        assert p.score == pytest.approx(0.6)  # 1.0*0.6 - 0 + 0 (std=0 → no var bonus)

    def test_score_good_with_variance(self):
        p = GapProfile(
            total_gaps=10,
            regular_count=10,
            dead_count=0,
            mean_gap=600.0,
            std_gap=60.0,  # CV = 0.1
        )
        # 1.0*0.6 - 0 + 0.2*(1-0.1) = 0.6 + 0.18 = 0.78
        assert p.score == pytest.approx(0.78, abs=0.01)

    def test_score_penalised_by_dead(self):
        p = GapProfile(
            total_gaps=10,
            regular_count=8,
            dead_count=2,
            mean_gap=700.0,
            std_gap=200.0,
        )
        # base = 0.8*0.6 = 0.48
        # dead_penalty = min(2*0.05, 0.3) = 0.10
        # cv = 200/700 ≈ 0.286, var_bonus = 0.2*(1-0.286) ≈ 0.143
        # score = 0.48 - 0.10 + 0.143 ≈ 0.523
        assert 0.4 < p.score < 0.7

    def test_score_clamped_to_unit_interval(self):
        # Even with extreme values, score stays in [0, 1]
        p = GapProfile(
            total_gaps=10,
            regular_count=10,
            dead_count=20,  # extreme dead penalty
            mean_gap=600.0,
            std_gap=60.0,
        )
        assert 0.0 <= p.score <= 1.0


# ===========================================================================
# recent_trend
# ===========================================================================

class TestRecentTrend:
    """Tests for the recent_trend function."""

    def test_insufficient_data_empty(self):
        p = GapProfile()
        assert recent_trend(p) == "insufficient_data"

    def test_insufficient_data_too_few(self):
        p = GapProfile(gaps=[GapReport(600, "regular", 0.0)] * 5, total_gaps=5)
        assert recent_trend(p, recent_count=10) == "insufficient_data"

    def test_stable_trend(self):
        # All regular — should be stable
        gaps = [GapReport(600, "regular", 0.0)] * 40
        p = GapProfile(gaps=gaps, total_gaps=40)
        assert recent_trend(p, recent_count=20) == "stable"

    def test_improving_trend(self):
        # Earlier half: mostly non-regular. Recent half: all regular.
        earlier = [GapReport(200, "accelerated", -0.67)] * 20
        recent = [GapReport(600, "regular", 0.0)] * 20
        p = GapProfile(gaps=earlier + recent, total_gaps=40)
        assert recent_trend(p, recent_count=20) == "improving"

    def test_deteriorating_trend(self):
        # Earlier half: all regular. Recent half: mostly dead.
        earlier = [GapReport(600, "regular", 0.0)] * 20
        recent = [GapReport(2000, "dead", 2.33)] * 20
        p = GapProfile(gaps=earlier + recent, total_gaps=40)
        assert recent_trend(p, recent_count=20) == "deteriorating"


# ===========================================================================
# gap_summary_text
# ===========================================================================

class TestGapSummaryText:
    """Tests for the gap_summary_text function."""

    def test_empty_profile(self):
        p = GapProfile()
        text = gap_summary_text(p)
        assert "unknown" in text
        assert "0/0" in text

    def test_rhythmic_no_dead(self):
        p = GapProfile(
            total_gaps=20,
            regular_count=18,
            accelerated_count=2,
        )
        text = gap_summary_text(p)
        assert "rhythmic" in text
        assert "18/20" in text
        assert "2 accelerated" in text
        assert "dead" not in text

    def test_erratic_with_dead(self):
        p = GapProfile(
            total_gaps=10,
            regular_count=3,
            dead_count=5,
        )
        text = gap_summary_text(p)
        assert "erratic" in text
        assert "5 dead" in text

    def test_score_in_output(self):
        p = GapProfile(
            total_gaps=10,
            regular_count=10,
            mean_gap=600.0,
            std_gap=60.0,
        )
        text = gap_summary_text(p)
        assert "score" in text


# ===========================================================================
# edge cases and integration
# ===========================================================================

class TestEdgeCases:
    """Edge cases and integration scenarios."""

    def test_identical_timestamps(self):
        ts = ["2026-10-22T10:00:00+00:00"] * 5
        profile = analyze_gaps(ts)
        assert profile.total_gaps == 4
        # All zero gaps → regular
        assert profile.regular_count == 4

    def test_single_large_gap_in_regular_sequence(self):
        offsets = list(range(0, 6000, 600)) + [6000 + 3600] + list(range(9600, 12000, 600))
        ts = _make_ts("2026-10-22T00:00:00", offsets)
        profile = analyze_gaps(ts)
        # Most gaps are regular, one is dead (3600s)
        assert profile.dead_count == 1
        assert profile.regular_count == profile.total_gaps - 1

    def test_timezone_handling(self):
        # Mix of UTC and offset formats
        ts = [
            "2026-10-22T10:00:00Z",
            "2026-10-22T10:10:00+00:00",
            "2026-10-22T10:20:00Z",
        ]
        profile = analyze_gaps(ts)
        assert profile.total_gaps == 2
        assert profile.mean_gap == pytest.approx(600.0)

    def test_full_pipeline(self):
        """Integration test: generate timestamps, analyze, check all outputs."""
        offsets = [0, 600, 1200, 1800, 2400, 3000, 3600, 4200, 7800, 8400]
        ts = _make_ts("2026-10-22T00:00:00", offsets)
        profile = analyze_gaps(ts)

        assert profile.total_gaps == 9
        assert profile.health in ("rhythmic", "irregular", "erratic")
        assert 0.0 <= profile.score <= 1.0
        assert len(profile.gaps) == 9
        text = gap_summary_text(profile)
        assert isinstance(text, str)
        assert len(text) > 0
        trend = recent_trend(profile, recent_count=4)
        assert trend in ("improving", "stable", "deteriorating", "insufficient_data")
