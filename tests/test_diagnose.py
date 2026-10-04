"""Tests for iamai.watchdog.diagnose: the four failure modes.

The diagnose function cross-references two signals (pidfile liveness
and heartbeat stall) to classify the system state. Each combination
maps to exactly one diagnosis, and the tests pin down that mapping so
a future refactor can't silently merge two distinct failure modes.

The matrix:

    all_alive=True  + stalled=False  -> "healthy"
    all_alive=True  + stalled=True   -> "hung-process"
    all_alive=False + stalled=True   -> "reclaimed"
    all_alive=False + stalled=False  -> "just-died"
"""

from __future__ import annotations

from iamai.watchdog import ProcessStatus, WatchdogReport, diagnose


def _report(*alive_flags: bool) -> WatchdogReport:
    """Build a WatchdogReport with the given process alive flags."""
    names = ["writer", "batch", "committer", "watcher"]
    procs = [
        ProcessStatus(
            name=names[i] if i < len(names) else f"proc-{i}",
            pid=1000 + i if alive else None,
            alive=alive,
            pidfile=f"/tmp/test-{i}.pid",
        )
        for i, alive in enumerate(alive_flags)
    ]
    return WatchdogReport(processes=procs, uncommitted_files=0, unpushed_commits=0)


# --- the four quadrants --------------------------------------------------


def test_healthy():
    """All processes alive and strokes flowing: nothing wrong."""
    assert diagnose(_report(True, True), stalled=False) == "healthy"


def test_healthy_single_process():
    """Healthy even with only one process tracked."""
    assert diagnose(_report(True), stalled=False) == "healthy"


def test_hung_process():
    """Process claims alive but writer has stalled — stuck loop."""
    assert diagnose(_report(True, True), stalled=True) == "hung-process"


def test_partial_dead_with_stall_is_reclaimed():
    """One process dead + stall -> reclaimed, not hung: something was killed."""
    assert diagnose(_report(True, False), stalled=True) == "reclaimed"


def test_reclaimed():
    """Process gone and writer stalled — container was killed."""
    assert diagnose(_report(False, False), stalled=True) == "reclaimed"


def test_reclaimed_partial_dead():
    """Reclaimed when any process is dead and writer has stalled."""
    assert diagnose(_report(False, True), stalled=True) == "reclaimed"


def test_just_died():
    """Process just died but heartbeat window hasn't expired yet."""
    assert diagnose(_report(False, False), stalled=False) == "just-died"


def test_just_died_partial():
    """Just-died when one process died and strokes are still fresh."""
    assert diagnose(_report(False, True), stalled=False) == "just-died"


# --- edge cases ----------------------------------------------------------


def test_no_processes_tracked():
    """Empty process list: all_alive is vacuously True."""
    report = WatchdogReport(processes=[], uncommitted_files=0, unpushed_commits=0)
    # vacuous all_alive + no stall -> healthy (no processes to fail)
    assert diagnose(report, stalled=False) == "healthy"
    # vacuous all_alive + stall -> hung (something else is wrong)
    assert diagnose(report, stalled=True) == "hung-process"
