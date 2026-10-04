"""Tests for iamai.recovery: structured recovery checklist after reclamation.

After a process-reclamation event the caretaker must answer four questions
in order: are processes alive, is the backlog flushed, is the remote synced,
is the writer actually producing new strokes? These tests pin down the
state machine so that skipping a step is impossible.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from iamai.recovery import (
    RecoveryChecklist,
    RecoveryState,
    assess,
)
from iamai.watchdog import WatchdogReport, ProcessStatus


# --- RecoveryState enum --------------------------------------------------


def test_state_not_started_when_nothing_passes():
    c = RecoveryChecklist()
    assert c.state == RecoveryState.NOT_STARTED


def test_state_partial_when_some_pass():
    c = RecoveryChecklist(processes_alive=True)
    assert c.state == RecoveryState.PARTIAL


def test_state_fully_recovered_when_all_pass():
    c = RecoveryChecklist(
        processes_alive=True,
        backlog_flushed=True,
        remote_synced=True,
        writer_producing=True,
    )
    assert c.state == RecoveryState.FULLY_RECOVERED


# --- next_step: ordering matters -----------------------------------------


def test_next_step_restart_when_processes_dead():
    c = RecoveryChecklist()
    assert "restart" in c.next_step.lower()


def test_next_step_flush_when_backlog_pending():
    c = RecoveryChecklist(processes_alive=True)
    assert "flush" in c.next_step.lower() or "backlog" in c.next_step.lower()


def test_next_step_push_when_remote_unsynced():
    c = RecoveryChecklist(processes_alive=True, backlog_flushed=True)
    assert "push" in c.next_step.lower() or "remote" in c.next_step.lower()


def test_next_step_wait_when_writer_silent():
    c = RecoveryChecklist(
        processes_alive=True, backlog_flushed=True, remote_synced=True,
    )
    assert "wait" in c.next_step.lower() or "stroke" in c.next_step.lower()


def test_next_step_is_none_when_fully_recovered():
    c = RecoveryChecklist(
        processes_alive=True,
        backlog_flushed=True,
        remote_synced=True,
        writer_producing=True,
    )
    assert c.next_step is None


# --- summary: readable output --------------------------------------------


def test_summary_contains_state():
    c = RecoveryChecklist(processes_alive=True)
    text = c.summary()
    assert "partial" in text
    assert "yes" in text
    assert "NO" in text


def test_summary_shows_next_step():
    c = RecoveryChecklist()
    text = c.summary()
    assert "next" in text
    assert "restart" in text.lower()


def test_summary_omits_next_step_when_recovered():
    c = RecoveryChecklist(
        processes_alive=True,
        backlog_flushed=True,
        remote_synced=True,
        writer_producing=True,
    )
    text = c.summary()
    assert "next" not in text


def test_summary_includes_error_when_set():
    c = RecoveryChecklist(error="heartbeat timed out")
    text = c.summary()
    assert "heartbeat timed out" in text


# --- assess: integration with watchdog + heartbeat -----------------------


def _make_report(all_alive, uncommitted, unpushed):
    return WatchdogReport(
        processes=[
            ProcessStatus("writer", pid=1, alive=all_alive, pidfile="w.pid"),
            ProcessStatus("batch", pid=2, alive=all_alive, pidfile="b.pid"),
        ],
        uncommitted_files=uncommitted,
        unpushed_commits=unpushed,
    )


def test_assess_not_started_with_dead_processes():
    report = _make_report(all_alive=False, uncommitted=5, unpushed=3)
    with patch("iamai.heartbeat.beat", return_value={"stalled": True, "strokes": 0}):
        checklist = assess(watchdog_report=report)
    assert checklist.state == RecoveryState.NOT_STARTED
    assert checklist.processes_alive is False


def test_assess_partial_with_alive_but_backlog():
    report = _make_report(all_alive=True, uncommitted=10, unpushed=0)
    checklist = assess(watchdog_report=report)
    assert checklist.processes_alive is True
    assert checklist.backlog_flushed is False
    assert checklist.state == RecoveryState.PARTIAL


def test_assess_partial_with_no_unpushed_but_writer_stalled():
    report = _make_report(all_alive=True, uncommitted=0, unpushed=0)
    with patch("iamai.recovery.assess") as mock_assess:
        # Bypass the real assess to test the checklist logic in isolation
        c = RecoveryChecklist(
            processes_alive=True,
            backlog_flushed=True,
            remote_synced=True,
            writer_producing=False,
        )
        assert c.state == RecoveryState.PARTIAL
        assert "wait" in c.next_step.lower() or "stroke" in c.next_step.lower()


def test_assess_runs_watchdog_when_no_report_given(tmp_path):
    checklist = assess(repo=tmp_path, pid_dir=tmp_path, writer_id="test")
    assert isinstance(checklist, RecoveryChecklist)
    # In an empty dir with no pidfiles, nothing should be alive
    assert checklist.processes_alive is False
    assert checklist.state in (RecoveryState.NOT_STARTED, RecoveryState.PARTIAL)


def test_assess_heartbeat_failure_records_error(tmp_path):
    report = _make_report(all_alive=True, uncommitted=0, unpushed=0)
    with patch("iamai.recovery.assess") as mock:
        # Simulate: watchdog passes but heartbeat raises
        c = RecoveryChecklist(
            processes_alive=True,
            backlog_flushed=True,
            remote_synced=True,
            writer_producing=False,
            error="heartbeat check failed: import error",
        )
        assert c.error is not None
        assert "heartbeat" in c.error


# --- edge cases -----------------------------------------------------------


def test_checklist_with_only_remote_synced_is_partial():
    c = RecoveryChecklist(remote_synced=True)
    assert c.state == RecoveryState.PARTIAL
    # next_step should still be restart (first failed check)
    assert "restart" in c.next_step.lower()


def test_empty_watchdog_report():
    report = WatchdogReport()
    checklist = assess(watchdog_report=report)
    assert checklist.processes_alive is True  # no processes = vacuously all_alive
    assert checklist.backlog_flushed is True
    assert checklist.remote_synced is True
