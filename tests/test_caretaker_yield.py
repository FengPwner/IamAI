"""Tests for iamai.caretaker_yield — visit productivity classification."""

from __future__ import annotations

import pytest

from iamai.caretaker_yield import (
    VisitLedger,
    VisitRecord,
    YIELD_CLEAN,
    YIELD_COMPOUND,
    YIELD_INTERVENTION,
    YIELD_PRODUCTIVE,
    YIELD_RECOVERY,
    classify_visit,
    yield_label,
    yield_report,
    yield_score,
)


# ── classify_visit ────────────────────────────────────────────────────

class TestClassifyVisit:
    """Each visit type is determined by the combination of signals."""

    def test_clean_visit(self):
        r = VisitRecord(visit_id=1, processes_alive=True,
                        backlog_committed=False, new_content_written=False)
        assert classify_visit(r) == YIELD_CLEAN

    def test_recovery_only(self):
        r = VisitRecord(visit_id=2, processes_alive=True,
                        backlog_committed=True, new_content_written=False)
        assert classify_visit(r) == YIELD_RECOVERY

    def test_intervention_restart(self):
        r = VisitRecord(visit_id=3, processes_alive=False,
                        backlog_committed=False, new_content_written=False)
        assert classify_visit(r) == YIELD_INTERVENTION

    def test_intervention_restart_and_backlog(self):
        """restart + backlog but no new content = intervention (not compound)."""
        r = VisitRecord(visit_id=4, processes_alive=False,
                        backlog_committed=True, new_content_written=False)
        assert classify_visit(r) == YIELD_INTERVENTION

    def test_productive_no_restart(self):
        r = VisitRecord(visit_id=5, processes_alive=True,
                        backlog_committed=False, new_content_written=True)
        assert classify_visit(r) == YIELD_PRODUCTIVE

    def test_compound_restart_and_content(self):
        """restart + new content = compound."""
        r = VisitRecord(visit_id=6, processes_alive=False,
                        backlog_committed=False, new_content_written=True)
        assert classify_visit(r) == YIELD_COMPOUND

    def test_compound_backlog_and_content(self):
        """backlog + new content = compound."""
        r = VisitRecord(visit_id=7, processes_alive=True,
                        backlog_committed=True, new_content_written=True)
        assert classify_visit(r) == YIELD_COMPOUND

    def test_compound_all_three(self):
        """restart + backlog + new content = compound."""
        r = VisitRecord(visit_id=8, processes_alive=False,
                        backlog_committed=True, new_content_written=True)
        assert classify_visit(r) == YIELD_COMPOUND


# ── yield_score ───────────────────────────────────────────────────────

class TestYieldScore:
    def test_clean_is_highest(self):
        assert yield_score(YIELD_CLEAN) == 4

    def test_productive_is_high(self):
        assert yield_score(YIELD_PRODUCTIVE) == 3

    def test_recovery_is_mid(self):
        assert yield_score(YIELD_RECOVERY) == 2

    def test_intervention_is_low(self):
        assert yield_score(YIELD_INTERVENTION) == 1

    def test_unknown_returns_zero(self):
        assert yield_score("bogus") == 0


# ── yield_label ───────────────────────────────────────────────────────

class TestYieldLabel:
    def test_known_types(self):
        for t in (YIELD_CLEAN, YIELD_RECOVERY, YIELD_INTERVENTION,
                  YIELD_PRODUCTIVE, YIELD_COMPOUND):
            label = yield_label(t)
            assert isinstance(label, str)
            assert len(label) > 0

    def test_unknown_returns_unknown(self):
        assert yield_label("bogus") == "unknown"


# ── VisitRecord.action_count ──────────────────────────────────────────

class TestActionCount:
    def test_clean_has_zero(self):
        r = VisitRecord(visit_id=1)
        assert r.action_count() == 0

    def test_one_action(self):
        r = VisitRecord(visit_id=2, processes_alive=False)
        assert r.action_count() == 1

    def test_two_actions(self):
        r = VisitRecord(visit_id=3, processes_alive=False,
                        backlog_committed=True)
        assert r.action_count() == 2

    def test_three_actions(self):
        r = VisitRecord(visit_id=4, processes_alive=False,
                        backlog_committed=True, new_content_written=True)
        assert r.action_count() == 3


# ── VisitLedger ───────────────────────────────────────────────────────

class TestVisitLedger:
    def test_empty_ledger(self):
        ledger = VisitLedger()
        assert ledger.count == 0
        assert ledger.mean_score() == 0.0
        assert ledger.clean_rate() == 0.0
        assert ledger.total_strokes_lost() == 0
        assert ledger.total_files_committed() == 0

    def test_add_and_count(self):
        ledger = VisitLedger()
        ledger.add(VisitRecord(visit_id=1))
        ledger.add(VisitRecord(visit_id=2))
        assert ledger.count == 2

    def test_reject_out_of_order(self):
        ledger = VisitLedger()
        ledger.add(VisitRecord(visit_id=5))
        with pytest.raises(ValueError, match="must be >"):
            ledger.add(VisitRecord(visit_id=3))

    def test_reject_duplicate_id(self):
        ledger = VisitLedger()
        ledger.add(VisitRecord(visit_id=1))
        with pytest.raises(ValueError, match="must be >"):
            ledger.add(VisitRecord(visit_id=1))

    def test_type_counts(self):
        ledger = VisitLedger()
        ledger.add(VisitRecord(visit_id=1))  # clean
        ledger.add(VisitRecord(visit_id=2))  # clean
        ledger.add(VisitRecord(visit_id=3, processes_alive=False))  # intervention
        counts = ledger.type_counts()
        assert counts[YIELD_CLEAN] == 2
        assert counts[YIELD_INTERVENTION] == 1

    def test_mean_score(self):
        ledger = VisitLedger()
        ledger.add(VisitRecord(visit_id=1))  # clean → 4
        ledger.add(VisitRecord(visit_id=2, processes_alive=False))  # intervention → 1
        assert ledger.mean_score() == 2.5

    def test_clean_rate(self):
        ledger = VisitLedger()
        ledger.add(VisitRecord(visit_id=1))  # clean
        ledger.add(VisitRecord(visit_id=2))  # clean
        ledger.add(VisitRecord(visit_id=3, processes_alive=False))  # intervention
        assert ledger.clean_rate() == pytest.approx(2 / 3)

    def test_total_strokes_lost(self):
        ledger = VisitLedger()
        ledger.add(VisitRecord(visit_id=1, strokes_lost=5))
        ledger.add(VisitRecord(visit_id=2, strokes_lost=3))
        assert ledger.total_strokes_lost() == 8

    def test_total_files_committed(self):
        ledger = VisitLedger()
        ledger.add(VisitRecord(visit_id=1, files_committed=9))
        ledger.add(VisitRecord(visit_id=2, files_committed=3))
        assert ledger.total_files_committed() == 12

    def test_recent(self):
        ledger = VisitLedger()
        for i in range(1, 16):
            ledger.add(VisitRecord(visit_id=i))
        recent = ledger.recent(5)
        assert len(recent) == 5
        assert recent[0].visit_id == 11
        assert recent[-1].visit_id == 15

    def test_recent_types(self):
        ledger = VisitLedger()
        ledger.add(VisitRecord(visit_id=1))  # clean
        ledger.add(VisitRecord(visit_id=2, processes_alive=False))  # intervention
        ledger.add(VisitRecord(visit_id=3, new_content_written=True))  # productive
        types = ledger.recent_types(3)
        assert types == [YIELD_CLEAN, YIELD_INTERVENTION, YIELD_PRODUCTIVE]


# ── yield_report ──────────────────────────────────────────────────────

class TestYieldReport:
    def test_empty_report(self):
        ledger = VisitLedger()
        report = yield_report(ledger)
        assert report["total_visits"] == 0
        assert report["mean_score"] == 0.0
        assert report["clean_rate"] == 0.0

    def test_basic_report(self):
        ledger = VisitLedger()
        ledger.add(VisitRecord(visit_id=1))  # clean
        ledger.add(VisitRecord(visit_id=2))  # clean
        ledger.add(VisitRecord(visit_id=3, processes_alive=False,
                               new_content_written=True))  # compound
        report = yield_report(ledger)
        assert report["total_visits"] == 3
        assert report["mean_score"] > 0
        assert report["dominant_type"] == YIELD_CLEAN
        assert len(report["recent_5"]) == 3
        assert "type_counts" in report

    def test_report_keys(self):
        ledger = VisitLedger()
        ledger.add(VisitRecord(visit_id=1))
        report = yield_report(ledger)
        expected_keys = {"total_visits", "mean_score", "clean_rate",
                         "total_strokes_lost", "total_files_committed",
                         "type_counts", "dominant_type", "recent_5"}
        assert set(report.keys()) == expected_keys

    def test_report_rounds(self):
        ledger = VisitLedger()
        ledger.add(VisitRecord(visit_id=1, strokes_lost=7, files_committed=3))
        report = yield_report(ledger)
        # mean_score should be rounded to 2 decimals
        assert isinstance(report["mean_score"], float)
        assert report["total_strokes_lost"] == 7
        assert report["total_files_committed"] == 3
