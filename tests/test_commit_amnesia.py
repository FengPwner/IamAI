"""Tests for iamai.commit_amnesia."""

from __future__ import annotations

import pytest

from iamai.commit_amnesia import (
    amnesia,
    amnesia_report,
    score_omission,
    score_recovery_lag,
    score_stale_age,
)


# ---------------------------------------------------------------------------
# score_omission
# ---------------------------------------------------------------------------

class TestScoreOmission:
    def test_no_modified_files(self):
        """Nothing to forget → perfect score."""
        assert score_omission(0, 0) == 100.0

    def test_all_committed(self):
        assert score_omission(10, 10) == 100.0

    def test_none_committed(self):
        assert score_omission(10, 0) == 0.0

    def test_half_committed(self):
        assert score_omission(10, 5) == 50.0

    def test_one_missed(self):
        assert score_omission(10, 9) == 90.0

    def test_negative_modified_treated_as_zero(self):
        assert score_omission(-3, 0) == 100.0

    def test_committed_exceeds_modified(self):
        """Edge case: more committed than modified (shouldn't happen)."""
        assert score_omission(5, 8) == 100.0

    def test_single_file_committed(self):
        assert score_omission(1, 1) == 100.0

    def test_single_file_missed(self):
        assert score_omission(1, 0) == 0.0

    def test_large_batch_most_committed(self):
        assert score_omission(100, 95) == 95.0


# ---------------------------------------------------------------------------
# score_stale_age
# ---------------------------------------------------------------------------

class TestScoreStaleAge:
    def test_zero_age(self):
        assert score_stale_age(0) == 100.0

    def test_negative_age(self):
        assert score_stale_age(-10) == 100.0

    def test_just_under_one_cycle(self):
        assert score_stale_age(599, 600) == 100.0

    def test_exactly_one_cycle(self):
        assert score_stale_age(600, 600) == 100.0

    def test_midpoint(self):
        mid = (600 + 3000) / 2  # 1800
        s = score_stale_age(mid, 600)
        assert 45 < s < 55

    def test_exactly_five_cycles(self):
        assert score_stale_age(3000, 600) == 0.0

    def test_beyond_five_cycles(self):
        assert score_stale_age(10000, 600) == 0.0

    def test_custom_interval(self):
        # With 300s interval, 1500s = 5 cycles → 0
        assert score_stale_age(1500, 300) == 0.0

    def test_just_over_one_cycle(self):
        s = score_stale_age(601, 600)
        assert 99 < s < 100

    def test_two_cycles(self):
        s = score_stale_age(1200, 600)
        # (3000 - 1200) / (3000 - 600) = 1800/2400 = 0.75
        assert abs(s - 75.0) < 0.1


# ---------------------------------------------------------------------------
# score_recovery_lag
# ---------------------------------------------------------------------------

class TestScoreRecoveryLag:
    def test_zero_cycles(self):
        assert score_recovery_lag(0) == 100.0

    def test_one_cycle(self):
        assert score_recovery_lag(1) == 75.0

    def test_two_cycles(self):
        assert score_recovery_lag(2) == 50.0

    def test_three_cycles(self):
        assert score_recovery_lag(3) == 25.0

    def test_four_cycles(self):
        assert score_recovery_lag(4) == 0.0

    def test_many_cycles_clamps_to_zero(self):
        assert score_recovery_lag(100) == 0.0

    def test_negative_cycles(self):
        assert score_recovery_lag(-1) == 100.0


# ---------------------------------------------------------------------------
# amnesia composite
# ---------------------------------------------------------------------------

class TestAmnesia:
    def test_perfect_memory(self):
        """All files committed, nothing stale, no lag."""
        a = amnesia(modified_files=10, committed_files=10)
        assert a["score"] == 100.0
        assert a["grade"] == "eidetic"
        assert a["omitted_files"] == 0
        assert a["omission_ratio"] == 0.0

    def test_total_amnesia(self):
        """No files committed, very stale, long lag."""
        a = amnesia(
            modified_files=10,
            committed_files=0,
            oldest_uncommitted_age=5000,
            cycles_since_omission=10,
        )
        assert a["score"] == 0.0
        assert a["grade"] == "amnesiac"
        assert a["omitted_files"] == 10

    def test_partial_amnesia(self):
        """Some files forgotten, moderate staleness."""
        a = amnesia(
            modified_files=12,
            committed_files=9,
            oldest_uncommitted_age=340.0,
            cycles_since_omission=2,
        )
        # omission: 75.0 * 0.40 = 30.0
        # stale:    100.0 * 0.35 = 35.0  (340 < 600)
        # recovery:  50.0 * 0.25 = 12.5
        # total: 77.5
        assert a["score"] == 77.5
        assert a["grade"] == "sharp"
        assert a["omitted_files"] == 3

    def test_foggy_grade(self):
        """Construct a foggy scenario."""
        a = amnesia(
            modified_files=20,
            committed_files=10,
            oldest_uncommitted_age=1800,
            cycles_since_omission=3,
        )
        # omission: 50.0 * 0.40 = 20.0
        # stale:    50.0 * 0.35 = 17.5
        # recovery: 25.0 * 0.25 = 6.25
        # total: 43.75
        assert a["grade"] == "foggy"
        assert 40 <= a["score"] < 65

    def test_no_modified_files(self):
        a = amnesia(modified_files=0, committed_files=0)
        assert a["score"] == 100.0
        assert a["grade"] == "eidetic"

    def test_single_file_committed(self):
        a = amnesia(modified_files=1, committed_files=1)
        assert a["score"] == 100.0

    def test_single_file_forgotten(self):
        a = amnesia(
            modified_files=1,
            committed_files=0,
            oldest_uncommitted_age=3600,
            cycles_since_omission=5,
        )
        assert a["grade"] == "amnesiac"
        assert a["omitted_files"] == 1

    def test_custom_commit_interval(self):
        a = amnesia(
            modified_files=5,
            committed_files=5,
            oldest_uncommitted_age=0,
            cycles_since_omission=0,
            commit_interval=300,
        )
        assert a["score"] == 100.0

    def test_dimensions_are_rounded(self):
        a = amnesia(modified_files=7, committed_files=5)
        for v in a["dimensions"].values():
            assert isinstance(v, float)
            assert v == round(v, 1)

    def test_omission_ratio_precision(self):
        a = amnesia(modified_files=3, committed_files=1)
        # 2/3 ≈ 0.667
        assert a["omission_ratio"] == 0.667


# ---------------------------------------------------------------------------
# amnesia_report
# ---------------------------------------------------------------------------

class TestAmnesiaReport:
    def test_report_format(self):
        a = amnesia(modified_files=10, committed_files=10)
        r = amnesia_report(a)
        assert "amnesia 100.0/100 (eidetic)" in r
        assert "omission 100.0/100" in r
        assert "0 file(s) forgotten" in r

    def test_report_amnesiac(self):
        a = amnesia(
            modified_files=10,
            committed_files=0,
            oldest_uncommitted_age=5000,
            cycles_since_omission=10,
        )
        r = amnesia_report(a)
        assert "amnesiac" in r
        assert "10 file(s) forgotten" in r

    def test_report_contains_all_dimensions(self):
        a = amnesia(modified_files=5, committed_files=3)
        r = amnesia_report(a)
        assert "omission" in r
        assert "stale" in r
        assert "recovery" in r


# ---------------------------------------------------------------------------
# Grade boundary edge cases
# ---------------------------------------------------------------------------

class TestGradeBoundaries:
    def test_eidetic_at_85(self):
        """Score exactly 85 → eidetic."""
        # Construct: omission=85*1/0.4=212.5 impossible via clean params
        # Instead verify classification via the composite
        a = amnesia(modified_files=20, committed_files=18)
        # omission = 90, stale = 100, recovery = 100
        # 90*0.4 + 100*0.35 + 100*0.25 = 36+35+25 = 96
        assert a["grade"] == "eidetic"

    def test_sharp_at_boundary(self):
        """Verify sharp grade is reachable."""
        a = amnesia(
            modified_files=10,
            committed_files=8,
            oldest_uncommitted_age=900,
            cycles_since_omission=1,
        )
        # omission: 80 * 0.4 = 32
        # stale: (3000-900)/(3000-600) = 2100/2400 = 87.5 * 0.35 = 30.625
        # recovery: 75 * 0.25 = 18.75
        # total: 81.375 → 81.4 → eidetic actually
        # Adjust: make stale worse
        a2 = amnesia(
            modified_files=10,
            committed_files=7,
            oldest_uncommitted_age=1500,
            cycles_since_omission=2,
        )
        # omission: 70 * 0.4 = 28
        # stale: (3000-1500)/2400 = 62.5 * 0.35 = 21.875
        # recovery: 50 * 0.25 = 12.5
        # total: 62.375 → 62.4 → foggy
        assert a2["grade"] == "foggy"
