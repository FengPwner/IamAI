"""Retry a callable with exponential backoff — no deps, no threads, no magic."""

import time
from typing import Callable, TypeVar

T = TypeVar("T")


def retry(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exc: type[BaseException] = Exception,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call `fn` up to `attempts` times, sleeping with exponential backoff.

    >>> retry(lambda: 42, attempts=1)
    42
    >>> calls = []
    >>> def flaky():
    ...     calls.append(1)
    ...     if len(calls) < 3:
    ...         raise ValueError("not yet")
    ...     return "ok"
    >>> retry(flaky, attempts=5, base_delay=0.001, sleep=lambda _: None)
    'ok'
    >>> len(calls)
    3
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last_err: BaseException | None = None
    for i in range(attempts):
        try:
            return fn()
        except exc as e:
            last_err = e
            if i == attempts - 1:
                break
            delay = min(base_delay * (2 ** i), max_delay)
            sleep(delay)
    raise last_err  # type: ignore[misc]
