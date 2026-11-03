"""Tests for iamai/writer_exit_classifier.py — writer exit cause classification."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.writer_exit_classifier import (
    ExitReport,
    classify_exit,
    classify_from_log_file,
)


# ---------------------------------------------------------------------------
# classify_exit — line_budget
# ---------------------------------------------------------------------------

class TestLineBudget:
    def test_exit_code_3_alone(self):
        r = classify_exit(exit_code=3)
        assert r.cause == "line_budget"
        assert r.should_restart is False

    def test_exit_code_3_with_log_evidence(self):
        r = classify_exit(
            exit_code=3,
            log_tail="writer tree exceeded the line budget; refusing to keep padding it",
        )
        assert r.cause == "line_budget"
        assert "log mentions line budget" in r.evidence

    def test_line_count_over_budget_without_exit_code(self):
        r = classify_exit(line_count=400_001, line_budget=400_000)
        assert r.cause == "line_budget"
        assert r.should_restart is False

    def test_line_count_at_budget_is_not_triggered(self):
        r = classify_exit(line_count=400_000, line_budget=400_000)
        assert r.cause != "line_budget"

    def test_recovery_hint_mentions_raise(self):
        r = classify_exit(exit_code=3)
        assert "Raise" in r.recovery_hint or "raise" in r.recovery_hint.lower()

    def test_evidence_includes_line_counts(self):
        r = classify_exit(exit_code=3, line_count=500_000, line_budget=400_000)
        assert any("500000" in e or "500_000" in e for e in r.evidence)


# ---------------------------------------------------------------------------
# classify_exit — stop_requested
# ---------------------------------------------------------------------------

class TestStopRequested:
    def test_stop_file_present(self):
        r = classify_exit(stop_file_exists=True)
        assert r.cause == "stop_requested"
        assert r.should_restart is False

    def test_stop_in_log(self):
        r = classify_exit(log_tail="writer stop requested, exiting")
        assert r.cause == "stop_requested"
        assert "log mentions stop requested" in r.evidence

    def test_stop_file_and_exit_code_0(self):
        """Stop file takes priority over clean exit code."""
        r = classify_exit(exit_code=0, stop_file_exists=True)
        assert r.cause == "stop_requested"

    def test_recovery_hint_mentions_investigate(self):
        r = classify_exit(stop_file_exists=True)
        assert "nvestigate" in r.recovery_hint


# ---------------------------------------------------------------------------
# classify_exit — normal
# ---------------------------------------------------------------------------

class TestNormal:
    def test_exit_code_0(self):
        r = classify_exit(exit_code=0)
        assert r.cause == "normal"
        assert r.should_restart is True

    def test_exit_code_0_clean_evidence(self):
        r = classify_exit(exit_code=0)
        assert "exit_code=0" in r.evidence


# ---------------------------------------------------------------------------
# classify_exit — crash
# ---------------------------------------------------------------------------

class TestCrash:
    def test_nonzero_exit_no_pid(self):
        r = classify_exit(exit_code=1, pid_exists=False)
        assert r.cause == "crash"
        assert r.should_restart is True

    def test_signal_kill_no_pid(self):
        r = classify_exit(exit_code=137, pid_exists=False)
        assert r.cause == "crash"
        assert r.should_restart is True

    def test_no_pid_no_exit_code(self):
        r = classify_exit(exit_code=None, pid_exists=False)
        assert r.cause == "crash"
        assert r.should_restart is True
        assert "disappeared" in r.recovery_hint.lower() or "oom" in r.recovery_hint.lower()

    def test_recovery_hint_mentions_stderr(self):
        r = classify_exit(exit_code=1, pid_exists=False)
        assert "stderr" in r.recovery_hint


# ---------------------------------------------------------------------------
# classify_exit — unknown
# ---------------------------------------------------------------------------

class TestUnknown:
    def test_pid_exists_no_exit_code(self):
        r = classify_exit(exit_code=None, pid_exists=True)
        assert r.cause == "unknown"
        assert r.should_restart is False

    def test_pid_exists_exit_code_1(self):
        """PID still present with nonzero exit is ambiguous."""
        r = classify_exit(exit_code=1, pid_exists=True)
        assert r.cause == "unknown"


# ---------------------------------------------------------------------------
# ExitReport
# ---------------------------------------------------------------------------

class TestExitReport:
    def test_to_dict_keys(self):
        r = ExitReport(cause="test", exit_code=0)
        d = r.to_dict()
        assert set(d.keys()) == {"cause", "exit_code", "evidence", "should_restart", "recovery_hint"}

    def test_to_dict_evidence_is_copy(self):
        r = ExitReport(cause="test", exit_code=0, evidence=["a", "b"])
        d = r.to_dict()
        d["evidence"].append("c")
        assert len(r.evidence) == 2  # original not mutated

    def test_defaults(self):
        r = ExitReport(cause="normal", exit_code=0)
        assert r.evidence == []
        assert r.should_restart is False
        assert r.recovery_hint == ""


# ---------------------------------------------------------------------------
# classify_from_log_file
# ---------------------------------------------------------------------------

class TestClassifyFromLogFile:
    def test_missing_file(self, tmp_path):
        r = classify_from_log_file(
            log_path=str(tmp_path / "nonexistent.log"),
        )
        # Should not crash, returns unknown or similar
        assert r.cause in ("unknown", "crash", "normal", "line_budget", "stop_requested")

    def test_reads_last_lines(self, tmp_path):
        log = tmp_path / "writer.log"
        lines = [f"line {i}\n" for i in range(20)]
        lines[-1] = "writer tree exceeded the line budget; refusing to keep padding it\n"
        log.write_text("".join(lines))
        r = classify_from_log_file(
            log_path=str(log),
            tail_lines=5,
        )
        assert r.cause == "line_budget" or "budget" in r.cause

    def test_stop_in_log_file(self, tmp_path):
        log = tmp_path / "writer.log"
        log.write_text("some log\nwriter stop requested, exiting\n")
        r = classify_from_log_file(log_path=str(log), tail_lines=5)
        assert r.cause == "stop_requested"


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------

class TestPriority:
    def test_line_budget_beats_stop_file(self):
        """Exit code 3 is more specific than stop file presence."""
        r = classify_exit(exit_code=3, stop_file_exists=True)
        assert r.cause == "line_budget"

    def test_stop_file_beats_normal_exit(self):
        r = classify_exit(exit_code=0, stop_file_exists=True)
        assert r.cause == "stop_requested"

    def test_line_count_beats_normal_exit(self):
        r = classify_exit(exit_code=0, line_count=500_000, line_budget=400_000)
        assert r.cause == "line_budget"

    def test_zero_budget_disables_line_check(self):
        r = classify_exit(exit_code=0, line_count=100, line_budget=0)
        assert r.cause == "normal"
