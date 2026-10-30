#!/usr/bin/env python3
"""Tests for push_retry_backoff.py"""

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from push_retry_backoff import (
    RetryState,
    load_state,
    save_state,
    compute_next_retry,
    record_failure,
    record_success,
    check_ready,
    classify_failure,
    format_human,
    CATEGORY_BASE_INTERVALS,
    BACKOFF_FACTOR,
    MAX_INTERVAL,
    JITTER_FRACTION,
)


# --- RetryState ---

class TestRetryState:
    def test_default_state(self):
        s = RetryState()
        assert s.consecutive_failures == 0
        assert s.last_failure_category == "unknown"
        assert s.last_failure_at is None
        assert s.next_retry_at is None
        assert s.total_failures == 0
        assert s.total_successes == 0
        assert s.history == []

    def test_to_dict(self):
        s = RetryState(consecutive_failures=3, last_failure_category="auth_failure")
        d = s.to_dict()
        assert d["consecutive_failures"] == 3
        assert d["last_failure_category"] == "auth_failure"

    def test_from_dict(self):
        d = {"consecutive_failures": 5, "last_failure_category": "network_error",
             "last_failure_at": "2026-10-27T12:00:00+00:00", "next_retry_at": 1730000000.0,
             "total_failures": 10, "total_retries": 8, "total_successes": 3,
             "history": [{"at": "test"}]}
        s = RetryState.from_dict(d)
        assert s.consecutive_failures == 5
        assert s.total_successes == 3
        assert len(s.history) == 1

    def test_from_dict_ignores_unknown_keys(self):
        d = {"consecutive_failures": 1, "bogus_key": "ignored"}
        s = RetryState.from_dict(d)
        assert s.consecutive_failures == 1
        assert not hasattr(s, "bogus_key")


# --- compute_next_retry ---

class TestComputeNextRetry:
    def test_first_failure_auth(self):
        now = 1000000.0
        with patch("push_retry_backoff.random.uniform", return_value=0):
            result = compute_next_retry(1, "auth_failure", now)
        assert result == now + 3600  # 1 hour base

    def test_first_failure_network(self):
        now = 1000000.0
        with patch("push_retry_backoff.random.uniform", return_value=0):
            result = compute_next_retry(1, "network_error", now)
        assert result == now + 300  # 5 minutes base

    def test_second_failure_doubles(self):
        now = 1000000.0
        with patch("push_retry_backoff.random.uniform", return_value=0):
            result = compute_next_retry(2, "auth_failure", now)
        assert result == now + 3600 * 2  # 2 hours

    def test_caps_at_max_interval(self):
        now = 1000000.0
        with patch("push_retry_backoff.random.uniform", return_value=0):
            result = compute_next_retry(20, "auth_failure", now)
        assert result == now + MAX_INTERVAL

    def test_jitter_adds_time(self):
        now = 1000000.0
        result = compute_next_retry(1, "network_error", now)
        # 300 base + up to 75 jitter = 300–375
        assert 300 <= result - now <= 375

    def test_unknown_category_uses_default(self):
        now = 1000000.0
        with patch("push_retry_backoff.random.uniform", return_value=0):
            result = compute_next_retry(1, "nonexistent_category", now)
        assert result == now + 900  # unknown default

    def test_backoff_progression(self):
        """Verify exponential growth: base, 2x, 4x, 8x..."""
        now = 0.0
        with patch("push_retry_backoff.random.uniform", return_value=0):
            intervals = [
                compute_next_retry(i, "network_error", now) - now
                for i in range(1, 8)
            ]
        # 300, 600, 1200, 2400, 4800, 9600, capped at 14400
        assert intervals[0] == 300
        assert intervals[1] == 600
        assert intervals[2] == 1200
        assert intervals[3] == 2400
        assert intervals[4] == 4800
        assert intervals[5] == 9600
        assert intervals[6] == MAX_INTERVAL  # 14400


# --- record_failure ---

class TestRecordFailure:
    def test_basic_failure(self):
        state = RetryState()
        now = 1730000000.0
        result = record_failure(state, "auth_failure", now)
        assert result.consecutive_failures == 1
        assert result.total_failures == 1
        assert result.last_failure_category == "auth_failure"
        assert result.last_failure_at is not None
        assert result.next_retry_at is not None
        assert result.next_retry_at > now

    def test_consecutive_increment(self):
        state = RetryState()
        now = 1730000000.0
        record_failure(state, "auth_failure", now)
        record_failure(state, "auth_failure", now + 3600)
        assert state.consecutive_failures == 2
        assert state.total_failures == 2

    def test_history_tracking(self):
        state = RetryState()
        now = 1730000000.0
        record_failure(state, "network_error", now)
        assert len(state.history) == 1
        assert state.history[0]["category"] == "network_error"

    def test_history_bounded(self):
        state = RetryState()
        now = 1730000000.0
        for i in range(120):
            record_failure(state, "unknown", now + i)
        assert len(state.history) == 100


# --- record_success ---

class TestRecordSuccess:
    def test_resets_consecutive(self):
        state = RetryState(consecutive_failures=5, next_retry_at=999999999.0)
        result = record_success(state)
        assert result.consecutive_failures == 0
        assert result.next_retry_at is None
        assert result.total_successes == 1

    def test_preserves_totals(self):
        state = RetryState(total_failures=10, total_successes=5)
        record_success(state)
        assert state.total_failures == 10
        assert state.total_successes == 6


# --- check_ready ---

class TestCheckReady:
    def test_no_failures_is_ready(self):
        state = RetryState()
        ready, remaining = check_ready(state)
        assert ready is True
        assert remaining == 0.0

    def test_not_ready_before_retry_time(self):
        state = RetryState(consecutive_failures=1, next_retry_at=time.time() + 600)
        ready, remaining = check_ready(state)
        assert ready is False
        assert remaining > 0

    def test_ready_after_retry_time(self):
        state = RetryState(consecutive_failures=1, next_retry_at=time.time() - 1)
        ready, remaining = check_ready(state)
        assert ready is True
        assert remaining == 0.0

    def test_none_next_retry_is_ready(self):
        state = RetryState(consecutive_failures=1, next_retry_at=None)
        ready, _ = check_ready(state)
        assert ready is True


# --- classify_failure ---

class TestClassifyFailure:
    def test_auth_failure_permission_denied(self):
        assert classify_failure("git@github.com: Permission denied (publickey).") == "auth_failure"

    def test_auth_failure_deploy_key(self):
        assert classify_failure("deploy key is not registered") == "auth_failure"

    def test_auth_failure_identity_file(self):
        assert classify_failure("Identity file /root/.ssh/id_ed25519 not accessible: No such file") == "auth_failure"

    def test_auth_failure_could_not_read(self):
        assert classify_failure("fatal: Could not read from remote repository.") == "auth_failure"

    def test_conflict_non_fast_forward(self):
        assert classify_failure("! [rejected] main -> main (non-fast-forward)") == "conflict"

    def test_conflict_fetch_first(self):
        assert classify_failure("Updates were rejected; fetch first") == "conflict"

    def test_network_timeout(self):
        assert classify_failure("ssh: connect to host github.com port 22: Connection timed out") == "network_error"

    def test_network_broken_pipe(self):
        assert classify_failure("fatal: the remote end hung up unexpectedly, broken pipe") == "network_error"

    def test_network_dns(self):
        assert classify_failure("ssh: Could not resolve hostname github.com") == "network_error"

    def test_unknown_fallback(self):
        assert classify_failure("something completely unexpected happened") == "unknown"

    def test_case_insensitive(self):
        assert classify_failure("PERMISSION DENIED (publickey)") == "auth_failure"


# --- load/save state ---

class TestPersistence:
    def test_save_and_load(self, tmp_path):
        state = RetryState(consecutive_failures=3, total_failures=5)
        path = tmp_path / "test_state.json"
        save_state(state, path)
        loaded = load_state(path)
        assert loaded.consecutive_failures == 3
        assert loaded.total_failures == 5

    def test_load_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        state = load_state(path)
        assert state.consecutive_failures == 0

    def test_load_corrupt_file(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("not valid json {{{")
        state = load_state(path)
        assert state.consecutive_failures == 0


# --- format_human ---

class TestFormatHuman:
    def test_clean_state(self):
        state = RetryState()
        output = format_human(state)
        assert "Consecutive failures: 0" in output
        assert "immediate" in output

    def test_with_failures(self):
        state = RetryState(
            consecutive_failures=3,
            last_failure_category="auth_failure",
            last_failure_at="2026-10-27T12:00:00+00:00",
            next_retry_at=time.time() + 300,
        )
        output = format_human(state)
        assert "Consecutive failures: 3" in output
        assert "auth_failure" in output
        assert "minutes" in output

    def test_overdue_retry(self):
        state = RetryState(
            consecutive_failures=1,
            next_retry_at=time.time() - 60,
        )
        output = format_human(state)
        assert "NOW (overdue)" in output


# --- Integration scenario ---

class TestScenario:
    def test_full_lifecycle(self, tmp_path):
        """Simulate: fail → fail → fail → succeed → fail again."""
        path = tmp_path / "state.json"
        state = RetryState()
        now = 1730000000.0

        # Three consecutive auth failures
        for i in range(3):
            state = record_failure(state, "auth_failure", now + i * 3600)
        assert state.consecutive_failures == 3
        assert state.total_failures == 3

        # Not ready yet
        ready, _ = check_ready(state, now + 3 * 3600 + 100)
        assert ready is False

        # Eventually ready
        ready, _ = check_ready(state, now + 3 * 3600 + 99999)
        assert ready is True

        # Success resets backoff
        state = record_success(state)
        assert state.consecutive_failures == 0
        assert state.next_retry_at is None
        assert state.total_successes == 1

        # New failure starts fresh backoff
        state = record_failure(state, "network_error", now + 999999)
        assert state.consecutive_failures == 1
        assert state.total_failures == 4  # cumulative

        save_state(state, path)
        loaded = load_state(path)
        assert loaded.total_failures == 4
