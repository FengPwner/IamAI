"""Tests for iamai.restart_budget — sliding-window restart rate limiter.

The budget answers "should we restart again?" based on recent history.
Tests cover: allow/deny transitions, window expiry, reset, and edge
cases around the boundary.
"""

from __future__ import annotations

import pytest

from iamai.restart_budget import RestartBudget


# --- basic allow/deny -------------------------------------------------------


def test_allow_when_empty():
    b = RestartBudget(max_restarts=3, window_seconds=60)
    assert b.allow(now=1000.0) is True


def test_allow_decrements_with_records():
    b = RestartBudget(max_restarts=3, window_seconds=60)
    b.record(timestamp=1000.0)
    b.record(timestamp=1001.0)
    b.record(timestamp=1002.0)
    assert b.allow(now=1003.0) is False


def test_allow_recovers_after_window_expires():
    b = RestartBudget(max_restarts=2, window_seconds=60)
    b.record(timestamp=1000.0)
    b.record(timestamp=1010.0)
    assert b.allow(now=1050.0) is False  # still in window
    assert b.allow(now=1071.0) is True   # first record expired


# --- remaining / count properties -------------------------------------------


def test_remaining_starts_at_max():
    b = RestartBudget(max_restarts=5, window_seconds=60)
    assert b.remaining(now=1000.0) == 5


def test_count_starts_at_zero():
    b = RestartBudget(max_restarts=5, window_seconds=60)
    assert b.count(now=1000.0) == 0


def test_remaining_and_count_after_records():
    b = RestartBudget(max_restarts=5, window_seconds=60)
    for i in range(3):
        b.record(timestamp=1000.0 + i)
    assert b.count(now=1005.0) == 3
    assert b.remaining(now=1005.0) == 2


# --- reset ------------------------------------------------------------------


def test_reset_clears_history():
    b = RestartBudget(max_restarts=2, window_seconds=60)
    b.record(timestamp=1000.0)
    b.record(timestamp=1001.0)
    assert b.allow(now=1002.0) is False
    b.reset()
    assert b.allow(now=1002.0) is True
    assert b.count(now=1002.0) == 0


# --- sliding window pruning -------------------------------------------------


def test_old_records_pruned_on_allow():
    b = RestartBudget(max_restarts=1, window_seconds=10)
    b.record(timestamp=1000.0)
    # 20 seconds later, the record is outside the window
    assert b.allow(now=1020.0) is True


def test_partial_pruning_keeps_recent():
    b = RestartBudget(max_restarts=3, window_seconds=60)
    b.record(timestamp=1000.0)  # expires at 1060
    b.record(timestamp=1040.0)  # expires at 1100
    b.record(timestamp=1050.0)  # expires at 1110
    # at 1070: only first record expired
    assert b.allow(now=1070.0) is True
    # but two records remain
    assert b.count(now=1070.0) == 2


# --- summary ----------------------------------------------------------------


def test_summary_healthy():
    b = RestartBudget(max_restarts=5, window_seconds=60)
    b.record(timestamp=1000.0)
    s = b.summary(now=1005.0)
    assert "4/5" in s
    assert "remaining" in s


def test_summary_exhausted():
    b = RestartBudget(max_restarts=2, window_seconds=60)
    b.record(timestamp=1000.0)
    b.record(timestamp=1001.0)
    s = b.summary(now=1002.0)
    assert "EXHAUSTED" in s
    assert "escalate" in s


# --- edge cases -------------------------------------------------------------


def test_single_restart_budget():
    b = RestartBudget(max_restarts=1, window_seconds=60)
    assert b.allow(now=1000.0) is True
    b.record(timestamp=1000.0)
    assert b.allow(now=1001.0) is False


def test_zero_window_always_allows():
    """With a zero-second window, records expire immediately."""
    b = RestartBudget(max_restarts=1, window_seconds=0)
    b.record(timestamp=1000.0)
    # prune removes records with ts <= now - 0 = now, so 1000 <= 1001
    assert b.allow(now=1001.0) is True


def test_defaults_are_reasonable():
    b = RestartBudget()
    assert b.max_restarts == 5
    assert b.window_seconds == 1800
    assert b.allow() is True
