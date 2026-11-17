"""tests for iamai.process_recycling_tax — recycling overhead measurement.

covers:
  - RecyclingEvent dataclass (tax property, negative gap)
  - classify() threshold boundaries
  - RecyclingLedger: add, count, clear, events copy
  - TaxReport: to_dict, summary, severity labels
  - edge cases: empty ledger, zero window, single event, ring buffer cap
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.process_recycling_tax import (
    EXIT_CRITICAL,
    EXIT_HIGH,
    EXIT_LOW,
    EXIT_MODERATE,
    EXIT_NEGLIGIBLE,
    EXIT_NO_DATA,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MODERATE,
    SEVERITY_NEGLIGIBLE,
    SEVERITY_NO_DATA,
    RecyclingEvent,
    RecyclingLedger,
    TaxReport,
    classify,
)


# ---------------------------------------------------------------------------
# RecyclingEvent
# ---------------------------------------------------------------------------


class TestRecyclingEvent:
    def test_tax_normal(self):
        ev = RecyclingEvent(death_ts=1000.0, recovery_ts=1012.0)
        assert ev.tax == 12.0

    def test_tax_zero_gap(self):
        ev = RecyclingEvent(death_ts=500.0, recovery_ts=500.0)
        assert ev.tax == 0.0

    def test_tax_negative_gap_clamped(self):
        """recovery before death should not produce negative tax."""
        ev = RecyclingEvent(death_ts=1000.0, recovery_ts=990.0)
        assert ev.tax == 0.0

    def test_frozen(self):
        ev = RecyclingEvent(death_ts=1.0, recovery_ts=2.0)
        with pytest.raises(AttributeError):
            ev.death_ts = 3.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


class TestClassify:
    def test_negligible(self):
        label, code = classify(0.0)
        assert label == SEVERITY_NEGLIGIBLE
        assert code == EXIT_NEGLIGIBLE

    def test_negligible_boundary(self):
        label, code = classify(0.009)
        assert label == SEVERITY_NEGLIGIBLE

    def test_low(self):
        label, code = classify(0.01)
        assert label == SEVERITY_LOW
        assert code == EXIT_LOW

    def test_low_upper(self):
        label, code = classify(0.049)
        assert label == SEVERITY_LOW

    def test_moderate(self):
        label, code = classify(0.05)
        assert label == SEVERITY_MODERATE
        assert code == EXIT_MODERATE

    def test_moderate_upper(self):
        label, code = classify(0.099)
        assert label == SEVERITY_MODERATE

    def test_high(self):
        label, code = classify(0.10)
        assert label == SEVERITY_HIGH
        assert code == EXIT_HIGH

    def test_high_upper(self):
        label, code = classify(0.199)
        assert label == SEVERITY_HIGH

    def test_critical(self):
        label, code = classify(0.20)
        assert label == SEVERITY_CRITICAL
        assert code == EXIT_CRITICAL

    def test_critical_high_value(self):
        label, code = classify(0.99)
        assert label == SEVERITY_CRITICAL


# ---------------------------------------------------------------------------
# RecyclingLedger
# ---------------------------------------------------------------------------


class TestRecyclingLedger:
    def test_add_and_count(self):
        ledger = RecyclingLedger()
        ledger.add(death_ts=100.0, recovery_ts=110.0)
        ledger.add(death_ts=200.0, recovery_ts=220.0)
        assert ledger.count() == 2

    def test_add_returns_event(self):
        ledger = RecyclingLedger()
        ev = ledger.add(death_ts=50.0, recovery_ts=55.0)
        assert isinstance(ev, RecyclingEvent)
        assert ev.tax == 5.0

    def test_events_is_copy(self):
        ledger = RecyclingLedger()
        ledger.add(death_ts=1.0, recovery_ts=2.0)
        events = ledger.events
        events.clear()
        assert ledger.count() == 1

    def test_clear(self):
        ledger = RecyclingLedger()
        ledger.add(death_ts=1.0, recovery_ts=2.0)
        ledger.clear()
        assert ledger.count() == 0

    def test_ring_buffer_cap(self):
        ledger = RecyclingLedger(max_events=5)
        for i in range(10):
            ledger.add(death_ts=float(i * 100), recovery_ts=float(i * 100 + 5))
        assert ledger.count() == 5
        # oldest events (0..4) should have been dropped
        assert ledger.events[0].death_ts == 500.0

    def test_report_empty_ledger(self):
        ledger = RecyclingLedger()
        r = ledger.report(window_start=0.0, window_end=3600.0)
        assert r.severity == SEVERITY_NO_DATA
        assert r.exit_code == EXIT_NO_DATA
        assert r.event_count == 0

    def test_report_zero_window(self):
        ledger = RecyclingLedger()
        ledger.add(death_ts=100.0, recovery_ts=110.0)
        r = ledger.report(window_start=100.0, window_end=100.0)
        assert r.severity == SEVERITY_NO_DATA
        assert r.window_s == 0.0

    def test_report_events_outside_window_excluded(self):
        ledger = RecyclingLedger()
        ledger.add(death_ts=100.0, recovery_ts=110.0)  # inside
        ledger.add(death_ts=5000.0, recovery_ts=5050.0)  # outside
        r = ledger.report(window_start=0.0, window_end=3600.0)
        assert r.event_count == 1
        assert r.total_tax_s == 10.0

    def test_report_single_event_negligible(self):
        ledger = RecyclingLedger()
        ledger.add(death_ts=1000.0, recovery_ts=1005.0)  # 5s tax
        r = ledger.report(window_start=0.0, window_end=3600.0)
        # 5/3600 ≈ 0.00139 → negligible
        assert r.event_count == 1
        assert r.total_tax_s == 5.0
        assert r.severity == SEVERITY_NEGLIGIBLE
        assert r.exit_code == EXIT_NEGLIGIBLE

    def test_report_moderate_tax(self):
        ledger = RecyclingLedger()
        # 10 events × 30s each = 300s in a 3600s window → 8.3% → moderate
        for i in range(10):
            base = float(i * 300)
            ledger.add(death_ts=base, recovery_ts=base + 30.0)
        r = ledger.report(window_start=0.0, window_end=3600.0)
        assert r.event_count == 10
        assert r.total_tax_s == 300.0
        assert r.severity == SEVERITY_MODERATE
        assert r.exit_code == EXIT_MODERATE

    def test_report_critical_tax(self):
        ledger = RecyclingLedger()
        # 5 events × 200s each = 1000s in a 3600s window → 27.8% → critical
        for i in range(5):
            base = float(i * 500)
            ledger.add(death_ts=base, recovery_ts=base + 200.0)
        r = ledger.report(window_start=0.0, window_end=3600.0)
        assert r.event_count == 5
        assert r.severity == SEVERITY_CRITICAL
        assert r.exit_code == EXIT_CRITICAL

    def test_recycling_rate_per_hour(self):
        ledger = RecyclingLedger()
        # 6 events in a 2-hour window → 3.0/hr
        for i in range(6):
            base = float(i * 1000)
            ledger.add(death_ts=base, recovery_ts=base + 10.0)
        r = ledger.report(window_start=0.0, window_end=7200.0)
        assert r.recycling_rate_per_hour == pytest.approx(3.0, abs=0.01)

    def test_mean_tax(self):
        ledger = RecyclingLedger()
        ledger.add(death_ts=0.0, recovery_ts=10.0)
        ledger.add(death_ts=100.0, recovery_ts=130.0)
        r = ledger.report(window_start=0.0, window_end=200.0)
        assert r.mean_tax_s == pytest.approx(20.0, abs=0.01)

    def test_tax_ratio_capped_at_one(self):
        """tax_ratio should not exceed 1.0 even with overlapping events."""
        ledger = RecyclingLedger()
        # 100 events of 100s each in a 100s window
        for i in range(100):
            ledger.add(death_ts=0.0, recovery_ts=100.0)
        r = ledger.report(window_start=0.0, window_end=100.0)
        assert r.tax_ratio == 1.0


# ---------------------------------------------------------------------------
# TaxReport
# ---------------------------------------------------------------------------


class TestTaxReport:
    def test_to_dict(self):
        r = TaxReport(
            window_start=0.0,
            window_end=3600.0,
            event_count=3,
            total_tax_s=45.0,
            window_s=3600.0,
            tax_ratio=0.0125,
            recycling_rate_per_hour=3.0,
            mean_tax_s=15.0,
            severity=SEVERITY_LOW,
            exit_code=EXIT_LOW,
        )
        d = r.to_dict()
        assert d["event_count"] == 3
        assert d["total_tax_s"] == 45.0
        assert d["tax_ratio"] == 0.0125
        assert d["severity"] == "low"
        assert d["exit_code"] == 1

    def test_summary_no_data(self):
        r = TaxReport(
            window_start=0.0,
            window_end=3600.0,
            event_count=0,
            total_tax_s=0.0,
            window_s=3600.0,
            tax_ratio=0.0,
            recycling_rate_per_hour=0.0,
            mean_tax_s=0.0,
            severity=SEVERITY_NO_DATA,
            exit_code=EXIT_NO_DATA,
        )
        assert "no recycling events" in r.summary()

    def test_summary_with_data(self):
        r = TaxReport(
            window_start=0.0,
            window_end=3600.0,
            event_count=5,
            total_tax_s=180.0,
            window_s=3600.0,
            tax_ratio=0.05,
            recycling_rate_per_hour=5.0,
            mean_tax_s=36.0,
            severity=SEVERITY_MODERATE,
            exit_code=EXIT_MODERATE,
        )
        s = r.summary()
        assert "moderate" in s
        assert "5 recycling events" in s
        assert "5.0%" in s

    def test_frozen(self):
        r = TaxReport(
            window_start=0.0,
            window_end=1.0,
            event_count=0,
            total_tax_s=0.0,
            window_s=1.0,
            tax_ratio=0.0,
            recycling_rate_per_hour=0.0,
            mean_tax_s=0.0,
            severity=SEVERITY_NEGLIGIBLE,
            exit_code=EXIT_NEGLIGIBLE,
        )
        with pytest.raises(AttributeError):
            r.severity = "hacked"  # type: ignore[misc]
