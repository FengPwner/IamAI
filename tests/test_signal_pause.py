"""Tests for signal-based pause/resume of writer processes.

A continuous writer touches tracked files every tick. When a supervisor
needs a clean tree (rebase, stash), it must freeze the writer without
killing it — losing the process means losing its stroke counter, its
seed position, and the PID the batch committer watches. SIGSTOP/SIGCONT
is the right primitive: kernel-enforced, immediate, no cleanup needed.

These tests spawn a real subprocess (not a mock) because signal delivery
semantics are exactly what we are testing, and a mock would only test
the mock.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from iamai.writer import signal_pause, signal_resume, is_process_running


@pytest.fixture
def sleepy_process():
    """A subprocess that writes a counter to a file every 100ms.

    Close enough to the writer loop's behavior for signal testing:
    if SIGSTOP works, the counter stops incrementing; if SIGCONT works,
    it resumes.
    """
    import tempfile
    fd, path = tempfile.mkstemp(prefix="iamai-test-")
    os.close(fd)

    proc = subprocess.Popen(
        ["python3", "-c", f"""
import time, os
path = {path!r}
n = 0
while True:
    n += 1
    with open(path, 'w') as f:
        f.write(str(n))
    time.sleep(0.1)
"""],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    yield proc, Path(path)

    proc.kill()
    proc.wait()
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _read_counter(path: Path) -> int:
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return 0


# --- signal_pause delivers SIGSTOP ---


def test_signal_pause_stops_the_process(sleepy_process):
    proc, counter_file = sleepy_process
    time.sleep(0.5)  # let it tick a few times

    before = _read_counter(counter_file)
    assert before > 0, "process should have ticked by now"

    assert signal_pause(proc.pid) is True

    frozen_at = _read_counter(counter_file)
    time.sleep(0.5)  # if pause works, counter should not advance
    after = _read_counter(counter_file)

    assert after == frozen_at, f"counter moved from {frozen_at} to {after} while paused"

    signal_resume(proc.pid)  # cleanup


def test_signal_resume_restores_the_process(sleepy_process):
    proc, counter_file = sleepy_process
    time.sleep(0.3)

    signal_pause(proc.pid)
    time.sleep(0.2)
    frozen_at = _read_counter(counter_file)

    signal_resume(proc.pid)
    time.sleep(0.5)
    resumed_at = _read_counter(counter_file)

    assert resumed_at > frozen_at, "process should tick again after SIGCONT"


# --- edge cases ---


def test_pause_nonexistent_pid_returns_false():
    # pid 999999 is very unlikely to exist in any test environment
    assert signal_pause(999999) is False


def test_resume_nonexistent_pid_returns_false():
    assert signal_resume(999999) is False


def test_is_process_running_for_live_process(sleepy_process):
    proc, _ = sleepy_process
    assert is_process_running(proc.pid) is True


def test_is_process_running_for_dead_process():
    assert is_process_running(999999) is False


def test_pause_is_idempotent(sleepy_process):
    """Sending SIGSTOP twice should not error."""
    proc, _ = sleepy_process
    time.sleep(0.2)
    assert signal_pause(proc.pid) is True
    assert signal_pause(proc.pid) is True  # already stopped, still succeeds
    signal_resume(proc.pid)


def test_resume_without_pause_is_harmless(sleepy_process):
    """SIGCONT on a running process is a no-op."""
    proc, counter_file = sleepy_process
    time.sleep(0.2)
    before = _read_counter(counter_file)
    assert signal_resume(proc.pid) is True
    time.sleep(0.3)
    after = _read_counter(counter_file)
    assert after > before, "process was never paused, should keep ticking"


def test_pause_resume_cycle_preserves_no_data(sleepy_process):
    """Multiple pause/resume cycles should not lose any ticks."""
    proc, counter_file = sleepy_process
    time.sleep(0.3)

    readings = []
    for _ in range(3):
        signal_pause(proc.pid)
        time.sleep(0.2)
        readings.append(_read_counter(counter_file))
        signal_resume(proc.pid)
        time.sleep(0.3)

    # each reading should be strictly increasing (we resumed between cycles)
    for i in range(1, len(readings)):
        assert readings[i] > readings[i - 1], (
            f"cycle {i}: counter did not advance ({readings})"
        )
