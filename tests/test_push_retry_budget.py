"""Tests for iamai.push_retry_budget module.

Covers initialization edge cases, sliding window expiry, retry counting,
severity classification, serialization, and reset behavior.
"""

import unittest
from datetime import datetime, timedelta, timezone

from iamai.push_retry_budget import PushRetryBudget


def _now():
    return datetime(2026, 10, 15, 3, 0, 0, tzinfo=timezone.utc)


def _ago(minutes: float, ref=None):
    ref = ref or _now()
    return ref - timedelta(minutes=minutes)


class TestInit(unittest.TestCase):
    def test_defaults(self):
        b = PushRetryBudget()
        self.assertEqual(b.window_minutes, 60)
        self.assertEqual(b.max_retries, 5)

    def test_custom(self):
        b = PushRetryBudget(window_minutes=30, max_retries=10)
        self.assertEqual(b.window_minutes, 30)
        self.assertEqual(b.max_retries, 10)

    def test_zero_window_raises(self):
        with self.assertRaises(ValueError):
            PushRetryBudget(window_minutes=0)

    def test_negative_window_raises(self):
        with self.assertRaises(ValueError):
            PushRetryBudget(window_minutes=-5)

    def test_zero_retries_raises(self):
        with self.assertRaises(ValueError):
            PushRetryBudget(max_retries=0)


class TestRecordAndCount(unittest.TestCase):
    def test_empty_budget(self):
        b = PushRetryBudget()
        self.assertEqual(b.failures_in_window(), 0)
        self.assertEqual(b.successes_in_window(), 0)
        self.assertEqual(b.remaining(), 5)
        self.assertTrue(b.can_retry())

    def test_single_failure(self):
        b = PushRetryBudget(max_retries=3)
        b.record_attempt(success=False, error="timeout", now=_now())
        self.assertEqual(b.failures_in_window(), 1)
        self.assertEqual(b.remaining(), 2)
        self.assertTrue(b.can_retry())

    def test_exhausted(self):
        b = PushRetryBudget(max_retries=2)
        b.record_attempt(success=False, error="e1", now=_now())
        b.record_attempt(success=False, error="e2", now=_now())
        self.assertEqual(b.failures_in_window(), 2)
        self.assertEqual(b.remaining(), 0)
        self.assertFalse(b.can_retry())

    def test_success_does_not_count_against_budget(self):
        b = PushRetryBudget(max_retries=2)
        b.record_attempt(success=True, now=_now())
        b.record_attempt(success=True, now=_now())
        b.record_attempt(success=True, now=_now())
        self.assertEqual(b.failures_in_window(), 0)
        self.assertEqual(b.successes_in_window(), 3)
        self.assertEqual(b.remaining(), 2)
        self.assertTrue(b.can_retry())

    def test_mixed_attempts(self):
        b = PushRetryBudget(max_retries=5)
        b.record_attempt(success=False, error="e1", now=_now())
        b.record_attempt(success=True, now=_now())
        b.record_attempt(success=False, error="e2", now=_now())
        self.assertEqual(b.failures_in_window(), 2)
        self.assertEqual(b.successes_in_window(), 1)
        self.assertEqual(b.remaining(), 3)


class TestSlidingWindow(unittest.TestCase):
    def test_old_failures_expire(self):
        b = PushRetryBudget(window_minutes=60, max_retries=3)
        old = _ago(90)  # 90 minutes ago, outside the 60min window
        b.record_attempt(success=False, error="old", now=old)
        # From the perspective of _now(), the old attempt is outside the window
        self.assertEqual(b.failures_in_window(now=_now()), 0)
        self.assertEqual(b.remaining(now=_now()), 3)
        self.assertTrue(b.can_retry(now=_now()))

    def test_recent_failures_count(self):
        b = PushRetryBudget(window_minutes=60, max_retries=3)
        recent = _ago(30)  # 30 minutes ago, inside the 60min window
        b.record_attempt(success=False, error="recent", now=recent)
        self.assertEqual(b.failures_in_window(now=_now()), 1)
        self.assertEqual(b.remaining(now=_now()), 2)

    def test_boundary_attempt(self):
        """Attempt exactly at the window edge should be excluded."""
        b = PushRetryBudget(window_minutes=60, max_retries=3)
        edge = _ago(60)  # exactly 60 minutes ago
        b.record_attempt(success=False, error="edge", now=edge)
        # The prune uses > cutoff (strict), so exactly-at-cutoff is excluded
        self.assertEqual(b.failures_in_window(now=_now()), 0)

    def test_just_inside_boundary(self):
        b = PushRetryBudget(window_minutes=60, max_retries=3)
        inside = _ago(59.9)  # 59.9 minutes ago
        b.record_attempt(success=False, error="inside", now=inside)
        self.assertEqual(b.failures_in_window(now=_now()), 1)

    def test_window_slides_forward(self):
        b = PushRetryBudget(window_minutes=30, max_retries=2)
        t0 = _ago(40)
        t1 = _ago(20)
        b.record_attempt(success=False, error="old", now=t0)
        b.record_attempt(success=False, error="recent", now=t1)

        # At t0+40min (now), the first attempt (40min ago) is outside 30min window
        self.assertEqual(b.failures_in_window(now=_now()), 1)
        self.assertTrue(b.can_retry(now=_now()))


class TestSeverity(unittest.TestCase):
    def test_ok_when_empty(self):
        b = PushRetryBudget(max_retries=4)
        self.assertEqual(b.severity(), "ok")

    def test_ok_under_half(self):
        b = PushRetryBudget(max_retries=6)
        b.record_attempt(success=False, error="e", now=_now())
        b.record_attempt(success=False, error="e", now=_now())
        # 2/6 = under half (3), so ok
        self.assertEqual(b.severity(now=_now()), "ok")

    def test_warn_over_half(self):
        b = PushRetryBudget(max_retries=4)
        b.record_attempt(success=False, error="e", now=_now())
        b.record_attempt(success=False, error="e", now=_now())
        b.record_attempt(success=False, error="e", now=_now())
        # 3/4 > 2 (half), so warn
        self.assertEqual(b.severity(now=_now()), "warn")

    def test_exhausted_at_limit(self):
        b = PushRetryBudget(max_retries=2)
        b.record_attempt(success=False, error="e", now=_now())
        b.record_attempt(success=False, error="e", now=_now())
        self.assertEqual(b.severity(now=_now()), "exhausted")

    def test_exactly_half_is_ok(self):
        b = PushRetryBudget(max_retries=4)
        b.record_attempt(success=False, error="e", now=_now())
        b.record_attempt(success=False, error="e", now=_now())
        # 2/4 = exactly half, not over, so ok
        self.assertEqual(b.severity(now=_now()), "ok")


class TestStatus(unittest.TestCase):
    def test_empty_status(self):
        b = PushRetryBudget(max_retries=5, window_minutes=60)
        s = b.status()
        self.assertIn("0/5", s)
        self.assertIn("60min", s)
        self.assertIn("5 remaining", s)

    def test_partial_status(self):
        b = PushRetryBudget(max_retries=5, window_minutes=30)
        b.record_attempt(success=False, error="nf", now=_now())
        b.record_attempt(success=False, error="nf", now=_now())
        s = b.status(now=_now())
        self.assertIn("2/5", s)
        self.assertIn("30min", s)
        self.assertIn("3 remaining", s)


class TestLastError(unittest.TestCase):
    def test_no_error(self):
        b = PushRetryBudget()
        self.assertEqual(b.last_error(), "")

    def test_single_error(self):
        b = PushRetryBudget()
        b.record_attempt(success=False, error="non-fast-forward", now=_now())
        self.assertEqual(b.last_error(), "non-fast-forward")

    def test_last_error_wins(self):
        b = PushRetryBudget()
        b.record_attempt(success=False, error="first", now=_now())
        b.record_attempt(success=False, error="second", now=_now())
        self.assertEqual(b.last_error(), "second")

    def test_success_does_not_clear_error(self):
        b = PushRetryBudget()
        b.record_attempt(success=False, error="timeout", now=_now())
        b.record_attempt(success=True, now=_now())
        self.assertEqual(b.last_error(), "timeout")


class TestReset(unittest.TestCase):
    def test_reset_clears(self):
        b = PushRetryBudget(max_retries=2)
        b.record_attempt(success=False, error="e", now=_now())
        b.record_attempt(success=False, error="e", now=_now())
        self.assertFalse(b.can_retry(now=_now()))
        b.reset()
        self.assertTrue(b.can_retry(now=_now()))
        self.assertEqual(b.failures_in_window(now=_now()), 0)


class TestToDict(unittest.TestCase):
    def test_empty_dict(self):
        b = PushRetryBudget(max_retries=3, window_minutes=15)
        d = b.to_dict(now=_now())
        self.assertEqual(d["max_retries"], 3)
        self.assertEqual(d["window_minutes"], 15)
        self.assertEqual(d["used"], 0)
        self.assertEqual(d["remaining"], 3)
        self.assertEqual(d["severity"], "ok")
        self.assertEqual(d["last_error"], "")
        self.assertEqual(d["attempts"], [])

    def test_dict_with_attempts(self):
        b = PushRetryBudget(max_retries=5, window_minutes=60)
        b.record_attempt(success=False, error="nf", now=_now())
        b.record_attempt(success=True, now=_now())
        d = b.to_dict(now=_now())
        self.assertEqual(d["used"], 1)
        self.assertEqual(d["remaining"], 4)
        self.assertEqual(len(d["attempts"]), 2)
        self.assertFalse(d["attempts"][0]["success"])
        self.assertTrue(d["attempts"][1]["success"])


if __name__ == "__main__":
    unittest.main()
