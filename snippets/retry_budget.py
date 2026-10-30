"""Retry a callable with a total time budget — exponential backoff that stops when the clock runs out."""

import time
from typing import Callable, TypeVar

T = TypeVar("T")


def retry_with_budget(
    fn: Callable[[], T],
    *,
    budget: float = 30.0,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    exc: type[BaseException] = Exception,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> T:
    """Call `fn` repeatedly until it succeeds or `budget` seconds elapse.

    Unlike attempt-counted retry, this guarantees you stop trying after
    a wall-clock deadline — useful when the caller has its own timeout
    and needs to leave a margin for cleanup.

    >>> retry_with_budget(lambda: 42, budget=1.0)
    42
    >>> calls = []
    >>> def flaky():
    ...     calls.append(1)
    ...     if len(calls) < 3:
    ...         raise ValueError("not yet")
    ...     return "ok"
    >>> retry_with_budget(flaky, budget=5.0, base_delay=0.001, sleep=lambda _: None)
    'ok'
    >>> len(calls)
    3
    """
    if budget <= 0:
        raise ValueError("budget must be > 0")
    if base_delay <= 0:
        raise ValueError("base_delay must be > 0")

    start = now()
    last_err: BaseException | None = None
    attempt = 0

    while True:
        elapsed = now() - start
        if elapsed >= budget:
            break
        try:
            return fn()
        except exc as e:
            last_err = e
            delay = base_delay * (2 ** min(attempt, 60))
            delay = min(delay, max_delay)
            remaining = budget - (now() - start)
            if delay > remaining:
                # not enough budget left for another sleep — give up
                break
            sleep(delay)
            attempt += 1

    raise last_err  # type: ignore[misc]
