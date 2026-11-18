"""push_retry_policy — exponential backoff for git push retries.

When a push is rejected (fetch first, transient network error, or
rate limit), blindly retrying in a tight loop wastes resources and
can trigger further rejections. This module provides a configurable
retry policy with exponential backoff and jitter, designed to sit
between the batch committer and the actual git push call.

Design:
  - RetryPolicy dataclass: max_retries, base_delay, max_delay, jitter
  - compute_delay(attempt): returns the delay for a given attempt number
  - should_retry(attempt, error): decides if an error is retryable
  - execute_with_retry(fn, policy): runs fn with retry, yields events

Retryable errors (by default):
  - "rejected (fetch first)" → needs rebase then retry
  - "unable to access" → transient network
  - "connection timed out" → transient network
  - "could not resolve host" → DNS blip

Non-retryable errors:
  - "rejected" without "fetch first" → diverged, needs human
  - "permission denied" → auth issue
  - "repository not found" → wrong remote

Usage::

    from iamai.push_retry_policy import RetryPolicy, execute_with_retry

    policy = RetryPolicy(max_retries=3, base_delay=2.0, max_delay=30.0)

    def push_fn():
        return subprocess.run(["git", "push"], capture_output=True, text=True)

    for event in execute_with_retry(push_fn, policy):
        if event["type"] == "success":
            print("pushed!")
        elif event["type"] == "retry":
            print(f"retry {event['attempt']}/{policy.max_retries} in {event['delay']:.1f}s")
        elif event["type"] == "failure":
            print(f"gave up: {event['error']}")

Written by Qwen during caretaker visit 702, 2026-11-18.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List, Optional, Set


@dataclass(frozen=True)
class RetryPolicy:
    """Configuration for push retry behaviour."""

    max_retries: int = 3
    base_delay: float = 2.0
    max_delay: float = 30.0
    jitter: bool = True
    backoff_factor: float = 2.0
    retryable_patterns: tuple = (
        "fetch first",
        "unable to access",
        "connection timed out",
        "could not resolve host",
        "early eof",
        "the remote end hung up unexpectedly",
    )
    non_retryable_patterns: tuple = (
        "permission denied",
        "repository not found",
        "authentication failed",
    )

    def compute_delay(self, attempt: int) -> float:
        """Return the delay in seconds for a given attempt (0-indexed).

        Uses exponential backoff: base_delay * backoff_factor^attempt,
        capped at max_delay. When jitter is enabled, the actual delay
        is uniform in [0, computed_delay] to prevent thundering herd.
        """
        if attempt < 0:
            raise ValueError(f"attempt must be >= 0, got {attempt}")
        raw = self.base_delay * (self.backoff_factor ** attempt)
        capped = min(raw, self.max_delay)
        if self.jitter:
            return random.uniform(0, capped)
        return capped

    def is_retryable(self, error: str) -> bool:
        """Check whether an error message indicates a retryable condition.

        Non-retryable patterns take priority over retryable ones.
        All matching is case-insensitive.
        """
        lower = error.lower()
        for pattern in self.non_retryable_patterns:
            if pattern.lower() in lower:
                return False
        for pattern in self.retryable_patterns:
            if pattern.lower() in lower:
                return True
        return False


def execute_with_retry(
    fn: Callable[[], Any],
    policy: RetryPolicy | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> Generator[Dict[str, Any], None, None]:
    """Execute fn with retry according to policy, yielding event dicts.

    Events:
      - {"type": "attempt", "attempt": int} — about to try
      - {"type": "retry", "attempt": int, "delay": float, "error": str}
      - {"type": "success", "attempt": int, "result": Any}
      - {"type": "failure", "attempt": int, "error": str, "retryable": bool}

    Args:
        fn: callable that performs the push. Should raise on failure.
            If it returns a result with a .returncode attribute, non-zero
            is treated as failure (with stderr as the error message).
        policy: retry configuration; defaults to RetryPolicy().
        sleep_fn: override for time.sleep (useful in tests).
    """
    if policy is None:
        policy = RetryPolicy()
    if sleep_fn is None:
        sleep_fn = time.sleep

    for attempt in range(policy.max_retries + 1):
        yield {"type": "attempt", "attempt": attempt}

        try:
            result = fn()
            # Handle subprocess-style results
            if hasattr(result, "returncode") and result.returncode != 0:
                stderr = ""
                if hasattr(result, "stderr"):
                    stderr = result.stderr if isinstance(result.stderr, str) else result.stderr.decode("utf-8", errors="replace")
                raise RuntimeError(stderr.strip() or f"exit code {result.returncode}")
            yield {"type": "success", "attempt": attempt, "result": result}
            return
        except Exception as exc:
            error_msg = str(exc)
            retryable = policy.is_retryable(error_msg)

            if not retryable or attempt >= policy.max_retries:
                yield {
                    "type": "failure",
                    "attempt": attempt,
                    "error": error_msg,
                    "retryable": retryable,
                }
                return

            delay = policy.compute_delay(attempt)
            yield {
                "type": "retry",
                "attempt": attempt,
                "delay": delay,
                "error": error_msg,
            }
            sleep_fn(delay)


def summarize_events(events: List[Dict[str, Any]]) -> str:
    """Produce a human-readable summary from a list of retry events.

    Useful for logging after execute_with_retry completes.
    """
    if not events:
        return "no events recorded"

    attempts = [e for e in events if e["type"] == "attempt"]
    retries = [e for e in events if e["type"] == "retry"]
    successes = [e for e in events if e["type"] == "success"]
    failures = [e for e in events if e["type"] == "failure"]

    parts: List[str] = []
    parts.append(f"{len(attempts)} attempt(s)")

    if successes:
        s = successes[0]
        parts.append(f"succeeded on attempt {s['attempt']}")
    elif failures:
        f = failures[0]
        parts.append(f"failed on attempt {f['attempt']}")
        parts.append(f"retryable={f['retryable']}")
        parts.append(f"error: {f['error'][:80]}")

    if retries:
        total_delay = sum(r["delay"] for r in retries)
        parts.append(f"{len(retries)} retries, {total_delay:.1f}s total backoff")

    return " | ".join(parts)
