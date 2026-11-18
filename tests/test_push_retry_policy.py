"""Tests for iamai.push_retry_policy — retry logic with exponential backoff.

Covers:
  - RetryPolicy.compute_delay: exponential growth, cap, jitter bounds
  - RetryPolicy.is_retryable: retryable vs non-retryable patterns
  - execute_with_retry: success on first try, retry then success,
    exhaustion, non-retryable immediate failure, jitter disabled
  - summarize_events: formatting for success, failure, and retry paths

Written by Qwen during caretaker visit 702, 2026-11-18.
"""

import pytest
from unittest.mock import MagicMock

from iamai.push_retry_policy import (
    RetryPolicy,
    execute_with_retry,
    summarize_events,
)


# ── RetryPolicy.compute_delay ────────────────────────────────────────────


class TestComputeDelay:
    def test_attempt_zero_no_jitter(self):
        p = RetryPolicy(base_delay=2.0, backoff_factor=2.0, jitter=False)
        assert p.compute_delay(0) == 2.0

    def test_exponential_growth_no_jitter(self):
        p = RetryPolicy(base_delay=1.0, backoff_factor=3.0, jitter=False)
        assert p.compute_delay(0) == 1.0
        assert p.compute_delay(1) == 3.0
        assert p.compute_delay(2) == 9.0
        assert p.compute_delay(3) == 27.0

    def test_max_delay_cap(self):
        p = RetryPolicy(base_delay=1.0, backoff_factor=10.0, max_delay=5.0, jitter=False)
        assert p.compute_delay(0) == 1.0
        assert p.compute_delay(1) == 5.0  # capped from 10
        assert p.compute_delay(2) == 5.0  # capped from 100

    def test_jitter_within_bounds(self):
        p = RetryPolicy(base_delay=10.0, backoff_factor=2.0, jitter=True)
        for _ in range(100):
            d = p.compute_delay(0)
            assert 0 <= d <= 10.0

    def test_jitter_zero_attempt(self):
        p = RetryPolicy(base_delay=5.0, jitter=True)
        results = {p.compute_delay(0) for _ in range(50)}
        # With jitter we should get multiple distinct values
        assert len(results) > 1

    def test_negative_attempt_raises(self):
        p = RetryPolicy()
        with pytest.raises(ValueError, match="attempt must be >= 0"):
            p.compute_delay(-1)


# ── RetryPolicy.is_retryable ─────────────────────────────────────────────


class TestIsRetryable:
    def test_fetch_first_is_retryable(self):
        p = RetryPolicy()
        assert p.is_retryable("rejected (fetch first)") is True

    def test_network_timeout_is_retryable(self):
        p = RetryPolicy()
        assert p.is_retryable("Connection timed out") is True

    def test_dns_failure_is_retryable(self):
        p = RetryPolicy()
        assert p.is_retryable("Could not resolve host: github.com") is True

    def test_permission_denied_not_retryable(self):
        p = RetryPolicy()
        assert p.is_retryable("Permission denied (publickey)") is False

    def test_repo_not_found_not_retryable(self):
        p = RetryPolicy()
        assert p.is_retryable("Repository not found") is False

    def test_auth_failure_not_retryable(self):
        p = RetryPolicy()
        assert p.is_retryable("Authentication failed") is False

    def test_unknown_error_not_retryable(self):
        p = RetryPolicy()
        assert p.is_retryable("something completely unexpected") is False

    def test_case_insensitive(self):
        p = RetryPolicy()
        assert p.is_retryable("FETCH FIRST") is True
        assert p.is_retryable("PERMISSION DENIED") is False

    def test_non_retryable_takes_priority(self):
        """If error matches both retryable and non-retryable, non-retryable wins."""
        p = RetryPolicy(
            retryable_patterns=("error",),
            non_retryable_patterns=("permission",),
        )
        assert p.is_retryable("permission error") is False

    def test_custom_retryable_patterns(self):
        p = RetryPolicy(retryable_patterns=("custom error code 42",))
        assert p.is_retryable("got custom error code 42 from server") is True
        assert p.is_retryable("fetch first") is False  # default patterns gone


# ── execute_with_retry ───────────────────────────────────────────────────


class TestExecuteWithRetry:
    def test_success_first_try(self):
        fn = MagicMock(return_value="ok")
        events = list(execute_with_retry(fn, RetryPolicy(), sleep_fn=MagicMock()))
        types = [e["type"] for e in events]
        assert types == ["attempt", "success"]
        assert events[1]["attempt"] == 0
        assert events[1]["result"] == "ok"

    def test_retry_then_success(self):
        call_count = [0]

        def flaky():
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("rejected (fetch first)")
            return "pushed"

        events = list(execute_with_retry(flaky, RetryPolicy(max_retries=3), sleep_fn=MagicMock()))
        types = [e["type"] for e in events]
        assert types == ["attempt", "retry", "attempt", "success"]
        assert events[1]["attempt"] == 0
        assert events[3]["attempt"] == 1

    def test_exhaustion(self):
        fn = MagicMock(side_effect=RuntimeError("rejected (fetch first)"))
        policy = RetryPolicy(max_retries=2)
        events = list(execute_with_retry(fn, policy, sleep_fn=MagicMock()))
        types = [e["type"] for e in events]
        # attempt, retry, attempt, retry, attempt, failure
        assert types == ["attempt", "retry", "attempt", "retry", "attempt", "failure"]
        assert events[-1]["retryable"] is True
        assert events[-1]["attempt"] == 2
        assert fn.call_count == 3

    def test_non_retryable_fails_immediately(self):
        fn = MagicMock(side_effect=RuntimeError("Permission denied"))
        events = list(execute_with_retry(fn, RetryPolicy(max_retries=5), sleep_fn=MagicMock()))
        types = [e["type"] for e in events]
        assert types == ["attempt", "failure"]
        assert events[-1]["retryable"] is False
        assert fn.call_count == 1

    def test_sleep_called_with_delay(self):
        call_count = [0]

        def flaky():
            call_count[0] += 1
            if call_count[0] <= 2:
                raise RuntimeError("connection timed out")
            return "ok"

        policy = RetryPolicy(max_retries=3, jitter=False, base_delay=1.0, backoff_factor=2.0)
        sleep = MagicMock()
        events = list(execute_with_retry(flaky, policy, sleep_fn=sleep))

        assert sleep.call_count == 2
        # First retry: delay = 1.0 * 2^0 = 1.0
        assert sleep.call_args_list[0].args[0] == pytest.approx(1.0)
        # Second retry: delay = 1.0 * 2^1 = 2.0
        assert sleep.call_args_list[1].args[0] == pytest.approx(2.0)

    def test_subprocess_style_result(self):
        """Result with .returncode non-zero is treated as failure."""

        class FakeResult:
            returncode = 128
            stderr = "error: failed to push some refs"

        fn = MagicMock(return_value=FakeResult())
        events = list(execute_with_retry(fn, RetryPolicy(max_retries=1), sleep_fn=MagicMock()))
        types = [e["type"] for e in events]
        # "failed to push some refs" is not in retryable patterns → immediate failure
        assert "failure" in types

    def test_subprocess_style_success(self):
        class FakeResult:
            returncode = 0
            stdout = "done"

        fn = MagicMock(return_value=FakeResult())
        events = list(execute_with_retry(fn, RetryPolicy(), sleep_fn=MagicMock()))
        assert events[-1]["type"] == "success"

    def test_max_retries_zero(self):
        fn = MagicMock(side_effect=RuntimeError("fetch first"))
        events = list(execute_with_retry(fn, RetryPolicy(max_retries=0), sleep_fn=MagicMock()))
        types = [e["type"] for e in events]
        assert types == ["attempt", "failure"]

    def test_default_policy(self):
        fn = MagicMock(return_value="ok")
        events = list(execute_with_retry(fn, sleep_fn=MagicMock()))
        assert events[-1]["type"] == "success"


# ── summarize_events ─────────────────────────────────────────────────────


class TestSummarizeEvents:
    def test_empty(self):
        assert summarize_events([]) == "no events recorded"

    def test_success_summary(self):
        events = [
            {"type": "attempt", "attempt": 0},
            {"type": "success", "attempt": 0, "result": "ok"},
        ]
        s = summarize_events(events)
        assert "1 attempt(s)" in s
        assert "succeeded on attempt 0" in s

    def test_failure_summary(self):
        events = [
            {"type": "attempt", "attempt": 0},
            {"type": "failure", "attempt": 0, "error": "Permission denied", "retryable": False},
        ]
        s = summarize_events(events)
        assert "failed on attempt 0" in s
        assert "retryable=False" in s

    def test_retry_summary(self):
        events = [
            {"type": "attempt", "attempt": 0},
            {"type": "retry", "attempt": 0, "delay": 2.5, "error": "fetch first"},
            {"type": "attempt", "attempt": 1},
            {"type": "success", "attempt": 1, "result": "ok"},
        ]
        s = summarize_events(events)
        assert "2 attempt(s)" in s
        assert "1 retries" in s
        assert "2.5s total backoff" in s

    def test_long_error_truncated(self):
        long_error = "x" * 200
        events = [
            {"type": "attempt", "attempt": 0},
            {"type": "failure", "attempt": 0, "error": long_error, "retryable": True},
        ]
        s = summarize_events(events)
        # Error should be truncated to 80 chars
        assert "x" * 80 in s
        assert "x" * 81 not in s


# ── integration-style ────────────────────────────────────────────────────


class TestIntegration:
    def test_full_retry_cycle(self):
        """Simulate: fail → retry → fail → retry → success."""
        calls = [0]

        def push():
            calls[0] += 1
            if calls[0] <= 2:
                raise RuntimeError("rejected (fetch first)")
            return "pushed successfully"

        policy = RetryPolicy(
            max_retries=3,
            base_delay=0.1,
            backoff_factor=2.0,
            jitter=False,
        )
        sleep = MagicMock()
        events = list(execute_with_retry(push, policy, sleep_fn=sleep))

        # Verify the full event sequence
        assert events[0] == {"type": "attempt", "attempt": 0}
        assert events[1]["type"] == "retry"
        assert events[1]["delay"] == pytest.approx(0.1)
        assert events[2] == {"type": "attempt", "attempt": 1}
        assert events[3]["type"] == "retry"
        assert events[3]["delay"] == pytest.approx(0.2)
        assert events[4] == {"type": "attempt", "attempt": 2}
        assert events[5]["type"] == "success"
        assert events[5]["result"] == "pushed successfully"
        assert calls[0] == 3
