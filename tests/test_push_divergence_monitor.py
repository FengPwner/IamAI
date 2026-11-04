"""Tests for iamai.push_divergence_monitor — 22 tests covering:

  1. DivergenceReport properties (divergence, urgency, recommended)
  2. Edge cases (zero divergence, one-sided, large divergence)
  3. measure_divergence with injected mock count_fn
  4. divergence_summary output format
"""

import pytest
from iamai.push_divergence_monitor import (
    DivergenceReport,
    measure_divergence,
    divergence_summary,
)


# ---------------------------------------------------------------------------
# DivergenceReport.divergence
# ---------------------------------------------------------------------------

class TestDivergence:
    def test_zero(self):
        assert DivergenceReport(0, 0).divergence == 0

    def test_local_only(self):
        assert DivergenceReport(5, 0).divergence == 5

    def test_remote_only(self):
        assert DivergenceReport(0, 7).divergence == 7

    def test_both(self):
        assert DivergenceReport(3, 4).divergence == 7


# ---------------------------------------------------------------------------
# DivergenceReport.urgency
# ---------------------------------------------------------------------------

class TestUrgency:
    def test_synced(self):
        assert DivergenceReport(0, 0).urgency == "synced"

    def test_nominal_low(self):
        assert DivergenceReport(1, 0).urgency == "nominal"

    def test_nominal_high(self):
        assert DivergenceReport(2, 1).urgency == "nominal"

    def test_growing_low(self):
        assert DivergenceReport(4, 0).urgency == "growing"

    def test_growing_high(self):
        assert DivergenceReport(5, 5).urgency == "growing"

    def test_critical_low(self):
        assert DivergenceReport(11, 0).urgency == "critical"

    def test_critical_large(self):
        assert DivergenceReport(50, 50).urgency == "critical"


# ---------------------------------------------------------------------------
# DivergenceReport.recommended
# ---------------------------------------------------------------------------

class TestRecommended:
    def test_synced_recommends_push(self):
        assert DivergenceReport(0, 0).recommended == "push"

    def test_local_only_recommends_push(self):
        assert DivergenceReport(5, 0).recommended == "push"

    def test_remote_only_recommends_pull_ff(self):
        assert DivergenceReport(0, 3).recommended == "pull_ff"

    def test_small_divergence_recommends_rebase(self):
        assert DivergenceReport(3, 4).recommended == "pull_rebase"

    def test_large_divergence_recommends_manual(self):
        assert DivergenceReport(8, 8).recommended == "manual_merge"

    def test_boundary_rebase(self):
        # divergence == 10 should still be pull_rebase
        assert DivergenceReport(5, 5).recommended == "pull_rebase"

    def test_boundary_manual(self):
        # divergence == 11 crosses into manual_merge
        assert DivergenceReport(6, 5).recommended == "manual_merge"


# ---------------------------------------------------------------------------
# DivergenceReport.as_dict
# ---------------------------------------------------------------------------

class TestAsDict:
    def test_keys(self):
        d = DivergenceReport(2, 3).as_dict()
        assert set(d.keys()) == {
            "local_ahead", "remote_ahead", "divergence",
            "urgency", "recommended",
        }

    def test_values(self):
        d = DivergenceReport(2, 3).as_dict()
        assert d["local_ahead"] == 2
        assert d["remote_ahead"] == 3
        assert d["divergence"] == 5


# ---------------------------------------------------------------------------
# measure_divergence with mock
# ---------------------------------------------------------------------------

class TestMeasureDivergence:
    def test_synced(self):
        def mock(path, rev_range):
            return 0
        r = measure_divergence(".", count_fn=mock)
        assert r.divergence == 0

    def test_local_ahead(self):
        def mock(path, rev_range):
            if ".." in rev_range and rev_range.startswith("origin/"):
                return 5  # origin..local = 5
            return 0       # local..origin = 0
        r = measure_divergence(".", count_fn=mock)
        assert r.local_ahead == 5
        assert r.remote_ahead == 0

    def test_negative_treated_as_zero(self):
        def mock(path, rev_range):
            return -1  # simulates git command failure
        r = measure_divergence(".", count_fn=mock)
        assert r.local_ahead == 0
        assert r.remote_ahead == 0
        assert r.urgency == "synced"


# ---------------------------------------------------------------------------
# divergence_summary
# ---------------------------------------------------------------------------

class TestSummary:
    def test_synced(self):
        def mock(path, rev_range):
            return 0
        s = divergence_summary(".", count_fn=mock)
        assert "sync" in s.lower()

    def test_diverged(self):
        def mock(path, rev_range):
            if rev_range.startswith("origin/"):
                return 3
            return 2
        s = divergence_summary(".", count_fn=mock)
        assert "divergence=5" in s
        assert "growing" in s
