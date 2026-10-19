"""Tests for iamai.lock_clearance — lock clearance ledger and analytics.

Covers:
  - LockClearance dataclass: construction, frozen, defaults
  - LockClearanceLedger: recording, bounded history, event ordering
  - Analytics: clearance_rate, mean_lock_age, recovery_rate,
    recurrence_risk, method_breakdown, total_backlog
  - Classification: clean / recurring / brittle thresholds
  - Reporting: report() dict structure, clearance_summary() formatting
  - Edge cases: empty ledger, single event, all-failed, all-recovered
"""

from __future__ import annotations

import pytest

from iamai.lock_clearance import (
    BRITTLE_MIN_CLEARANCES,
    CLEAN_MAX_CLEARANCES,
    RECURRING_MIN_RECOVERY,
    RECURRENCE_WINDOW_S,
    LockClearance,
    LockClearanceLedger,
    clearance_summary,
)


# -- LockClearance dataclass ------------------------------------------------

class TestLockClearance:
    def test_construction_with_defaults(self):
        lc = LockClearance(at=1000.0)
        assert lc.at == 1000.0
        assert lc.lock_age == 0.0
        assert lc.recovered is True
        assert lc.method == "auto"
        assert lc.backlog == 0

    def test_construction_with_all_fields(self):
        lc = LockClearance(
            at=1697745600.0,
            lock_age=3600.0,
            recovered=False,
            method="manual",
            backlog=9,
        )
        assert lc.at == 1697745600.0
        assert lc.lock_age == 3600.0
        assert lc.recovered is False
        assert lc.method == "manual"
        assert lc.backlog == 9

    def test_frozen(self):
        lc = LockClearance(at=100.0)
        with pytest.raises(AttributeError):
            lc.at = 200.0


# -- Ledger recording -------------------------------------------------------

class TestLedgerRecording:
    def test_empty_ledger(self):
        ledger = LockClearanceLedger()
        assert len(ledger) == 0
        assert ledger.events == []

    def test_record_returns_count(self):
        ledger = LockClearanceLedger()
        assert ledger.record(LockClearance(at=1.0)) == 1
        assert ledger.record(LockClearance(at=2.0)) == 2

    def test_events_in_chronological_order(self):
        ledger = LockClearanceLedger()
        ledger.record(LockClearance(at=300.0))
        ledger.record(LockClearance(at=100.0))
        ledger.record(LockClearance(at=200.0))
        times = [e.at for e in ledger.events]
        assert times == [300.0, 100.0, 200.0]  # insertion order preserved

    def test_bounded_history(self):
        ledger = LockClearanceLedger(max_events=3)
        for i in range(10):
            ledger.record(LockClearance(at=float(i)))
        assert len(ledger) == 3
        times = [e.at for e in ledger.events]
        assert times == [7.0, 8.0, 9.0]

    def test_default_max_events(self):
        ledger = LockClearanceLedger()
        assert ledger.max_events == 100


# -- clearance_rate ---------------------------------------------------------

class TestClearanceRate:
    def test_empty_returns_zero(self):
        ledger = LockClearanceLedger()
        assert ledger.clearance_rate() == 0.0

    def test_single_event(self):
        ledger = LockClearanceLedger()
        ledger.record(LockClearance(at=1000.0))
        assert ledger.clearance_rate() == 1.0

    def test_multiple_events_within_window(self):
        ledger = LockClearanceLedger()
        base = 1000000.0
        for i in range(5):
            ledger.record(LockClearance(at=base + i * 3600))
        # All 5 within 5 hours, well inside 24h window
        assert ledger.clearance_rate() == 5.0

    def test_events_outside_window_excluded(self):
        ledger = LockClearanceLedger()
        # Event 48 hours ago (outside 24h window)
        ledger.record(LockClearance(at=1000.0))
        # Event 1 hour ago (inside window)
        ledger.record(LockClearance(at=1000.0 + 47 * 3600))
        now = 1000.0 + 48 * 3600
        # Only the recent event falls within the 24h window
        assert ledger.clearance_rate(now=now) == 1.0

    def test_custom_window(self):
        ledger = LockClearanceLedger()
        base = 1000.0
        ledger.record(LockClearance(at=base))
        ledger.record(LockClearance(at=base + 6 * 3600))  # 6h later
        # With a 12h window, both should count
        assert ledger.clearance_rate(now=base + 6 * 3600, window_hours=12) == 2.0
        # With a 3h window, only the recent one counts
        assert ledger.clearance_rate(now=base + 6 * 3600, window_hours=3) == 1.0


# -- mean_lock_age ----------------------------------------------------------

class TestMeanLockAge:
    def test_empty_returns_zero(self):
        ledger = LockClearanceLedger()
        assert ledger.mean_lock_age() == 0.0

    def test_single_event(self):
        ledger = LockClearanceLedger()
        ledger.record(LockClearance(at=1000.0, lock_age=120.0))
        assert ledger.mean_lock_age() == 120.0

    def test_average_of_multiple(self):
        ledger = LockClearanceLedger()
        base = 1000.0
        ledger.record(LockClearance(at=base, lock_age=100.0))
        ledger.record(LockClearance(at=base + 60, lock_age=200.0))
        ledger.record(LockClearance(at=base + 120, lock_age=300.0))
        assert ledger.mean_lock_age() == 200.0


# -- recovery_rate ----------------------------------------------------------

class TestRecoveryRate:
    def test_empty_returns_one(self):
        """Vacuously healthy — no failures to report."""
        ledger = LockClearanceLedger()
        assert ledger.recovery_rate() == 1.0

    def test_all_recovered(self):
        ledger = LockClearanceLedger()
        for i in range(5):
            ledger.record(LockClearance(at=float(i), recovered=True))
        assert ledger.recovery_rate() == 1.0

    def test_all_failed(self):
        ledger = LockClearanceLedger()
        for i in range(5):
            ledger.record(LockClearance(at=float(i), recovered=False))
        assert ledger.recovery_rate() == 0.0

    def test_mixed(self):
        ledger = LockClearanceLedger()
        ledger.record(LockClearance(at=1.0, recovered=True))
        ledger.record(LockClearance(at=2.0, recovered=False))
        ledger.record(LockClearance(at=3.0, recovered=True))
        ledger.record(LockClearance(at=4.0, recovered=True))
        # 3 out of 4 recovered
        assert ledger.recovery_rate() == 0.75


# -- recurrence_risk --------------------------------------------------------

class TestRecurrenceRisk:
    def test_empty_returns_zero(self):
        ledger = LockClearanceLedger()
        assert ledger.recurrence_risk() == 0.0

    def test_single_event_returns_zero(self):
        ledger = LockClearanceLedger()
        ledger.record(LockClearance(at=1000.0))
        assert ledger.recurrence_risk() == 0.0

    def test_two_events_within_window(self):
        """Second event within 1 hour of first → recurrence risk 1.0."""
        ledger = LockClearanceLedger()
        ledger.record(LockClearance(at=1000.0))
        ledger.record(LockClearance(at=1000.0 + 1800))  # 30 min later
        assert ledger.recurrence_risk() == 1.0

    def test_two_events_outside_window(self):
        """Second event more than 1 hour after first → recurrence risk 0.0."""
        ledger = LockClearanceLedger()
        ledger.record(LockClearance(at=1000.0))
        ledger.record(LockClearance(at=1000.0 + 7200))  # 2 hours later
        assert ledger.recurrence_risk() == 0.0

    def test_mixed_recurrences(self):
        """Three events: first pair recurs, second pair doesn't."""
        ledger = LockClearanceLedger()
        ledger.record(LockClearance(at=1000.0))
        ledger.record(LockClearance(at=1000.0 + 1800))  # 30 min → recur
        ledger.record(LockClearance(at=1000.0 + 7200))  # 5400s from 2nd → no recur
        # First event: next at +1800 (recur). Second: next at +5400 (no recur).
        # recurrences=1, pairs=2 → risk=0.5
        assert ledger.recurrence_risk() == 0.5


# -- method_breakdown -------------------------------------------------------

class TestMethodBreakdown:
    def test_empty_returns_empty_dict(self):
        ledger = LockClearanceLedger()
        assert ledger.method_breakdown() == {}

    def test_counts_methods(self):
        ledger = LockClearanceLedger()
        base = 1000.0
        ledger.record(LockClearance(at=base, method="auto"))
        ledger.record(LockClearance(at=base + 60, method="auto"))
        ledger.record(LockClearance(at=base + 120, method="manual"))
        breakdown = ledger.method_breakdown()
        assert breakdown == {"auto": 2, "manual": 1}

    def test_sorted_by_count_descending(self):
        ledger = LockClearanceLedger()
        base = 1000.0
        ledger.record(LockClearance(at=base, method="caretaker"))
        ledger.record(LockClearance(at=base + 60, method="auto"))
        ledger.record(LockClearance(at=base + 120, method="auto"))
        ledger.record(LockClearance(at=base + 180, method="auto"))
        ledger.record(LockClearance(at=base + 240, method="caretaker"))
        breakdown = ledger.method_breakdown()
        keys = list(breakdown.keys())
        assert keys[0] == "auto"


# -- total_backlog ----------------------------------------------------------

class TestTotalBacklog:
    def test_empty_returns_zero(self):
        ledger = LockClearanceLedger()
        assert ledger.total_backlog() == 0

    def test_sums_backlog(self):
        ledger = LockClearanceLedger()
        base = 1000.0
        ledger.record(LockClearance(at=base, backlog=9))
        ledger.record(LockClearance(at=base + 60, backlog=3))
        ledger.record(LockClearance(at=base + 120, backlog=7))
        assert ledger.total_backlog() == 19


# -- Classification ---------------------------------------------------------

class TestClassification:
    def test_empty_is_clean(self):
        ledger = LockClearanceLedger()
        assert ledger.classify() == "clean"

    def test_few_recovered_is_clean(self):
        ledger = LockClearanceLedger()
        base = 1000.0
        for i in range(CLEAN_MAX_CLEARANCES):
            ledger.record(LockClearance(at=base + i * 60, recovered=True))
        assert ledger.classify() == "clean"

    def test_many_recovered_is_recurring(self):
        """More than CLEAN_MAX clearances, all recovered → recurring."""
        ledger = LockClearanceLedger()
        base = 1000.0
        for i in range(CLEAN_MAX_CLEARANCES + 3):
            ledger.record(LockClearance(at=base + i * 60, recovered=True))
        assert ledger.classify() == "recurring"

    def test_many_mostly_failed_is_brittle(self):
        """BRITTLE_MIN+ clearances, recovery below threshold → brittle."""
        ledger = LockClearanceLedger()
        base = 1000.0
        # 5 failed, 1 recovered → recovery = 1/6 ≈ 0.167
        for i in range(BRITTLE_MIN_CLEARANCES):
            ledger.record(LockClearance(at=base + i * 60, recovered=False))
        ledger.record(LockClearance(at=base + 360, recovered=True))
        assert ledger.classify() == "brittle"

    def test_many_mostly_recovered_not_brittle(self):
        """BRITTLE_MIN+ clearances but recovery above threshold → recurring."""
        ledger = LockClearanceLedger()
        base = 1000.0
        # 5 recovered, 1 failed → recovery = 5/6 ≈ 0.833 (above 0.7)
        for i in range(BRITTLE_MIN_CLEARANCES):
            ledger.record(LockClearance(at=base + i * 60, recovered=True))
        ledger.record(LockClearance(at=base + 360, recovered=False))
        # 6 clearances > CLEAN_MAX, recovery > RECURRING_MIN → recurring
        assert ledger.classify() == "recurring"


# -- Report -----------------------------------------------------------------

class TestReport:
    def test_empty_report_structure(self):
        ledger = LockClearanceLedger()
        r = ledger.report()
        assert r["total_events"] == 0
        assert r["classification"] == "clean"
        assert r["clearances_24h"] == 0.0
        assert r["mean_lock_age_s"] == 0.0
        assert r["recovery_rate"] == 1.0
        assert r["recurrence_risk"] == 0.0
        assert r["total_backlog"] == 0
        assert r["method_breakdown"] == {}
        assert r["latest_event"] is None

    def test_populated_report(self):
        ledger = LockClearanceLedger()
        ledger.record(LockClearance(
            at=1000.0, lock_age=120.0, recovered=True,
            method="auto", backlog=5,
        ))
        ledger.record(LockClearance(
            at=1060.0, lock_age=180.0, recovered=False,
            method="manual", backlog=3,
        ))
        r = ledger.report()
        assert r["total_events"] == 2
        assert r["clearances_24h"] == 2.0
        assert r["mean_lock_age_s"] == 150.0
        assert r["recovery_rate"] == 0.5
        assert r["total_backlog"] == 8
        assert r["latest_event"]["method"] == "manual"
        assert r["latest_event"]["backlog"] == 3

    def test_report_with_explicit_now(self):
        ledger = LockClearanceLedger()
        ledger.record(LockClearance(at=1000.0))
        r = ledger.report(now=1000.0)
        assert r["total_events"] == 1


# -- clearance_summary ------------------------------------------------------

class TestClearanceSummary:
    def test_empty_ledger(self):
        ledger = LockClearanceLedger()
        s = clearance_summary(ledger)
        assert "no events" in s
        assert "clean" in s

    def test_summary_includes_classification(self):
        ledger = LockClearanceLedger()
        ledger.record(LockClearance(at=1000.0, lock_age=60.0, recovered=True))
        s = clearance_summary(ledger)
        assert "1 event(s)" in s
        assert "clean" in s
        assert "100%" in s

    def test_summary_shows_recovery_percentage(self):
        ledger = LockClearanceLedger()
        ledger.record(LockClearance(at=1.0, recovered=True))
        ledger.record(LockClearance(at=2.0, recovered=False))
        s = clearance_summary(ledger)
        assert "50%" in s

    def test_summary_shows_mean_age(self):
        ledger = LockClearanceLedger()
        ledger.record(LockClearance(at=1.0, lock_age=100.0))
        ledger.record(LockClearance(at=2.0, lock_age=200.0))
        s = clearance_summary(ledger)
        assert "150s" in s
