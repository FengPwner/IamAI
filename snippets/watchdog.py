"""Watchdog — a lightweight heartbeat monitor for detecting stuck loops.

When a long-running process goes silent (deadlock, infinite loop, network
hang), you want to know *fast*, not after some external timeout fires.

The Watchdog expects periodic ``pet()`` calls.  If the interval between
two consecutive pets exceeds ``timeout`` seconds, the registered ``on_bark``
callback fires.  A background thread does the checking; the caller just
needs to pet the dog on every healthy iteration.

Design choices:

- **Thread-based**: the watchdog runs in a daemon thread so it won't
  prevent interpreter exit.
- **No polling sleep**: uses an ``Event.wait()`` with the remaining
  budget, so ``stop()`` is near-instant.
- **Re-entrant pet**: safe to call from any thread.
- **Single-fire by default**: once the dog barks it stops watching.
  Pass ``repeat=True`` to keep barking on every subsequent timeout.

Zero external dependencies.  Works on Python 3.8+.

>>> import time
>>> barked = []
>>> wd = Watchdog(timeout=0.1, on_bark=lambda: barked.append(True))
>>> wd.start()
>>> wd.pet()
>>> time.sleep(0.25)
>>> bool(barked)
True
>>> wd.stop()
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional


class Watchdog:
    """Monitor periodic heartbeats; fire a callback on timeout."""

    def __init__(
        self,
        timeout: float,
        on_bark: Callable[[], None],
        *,
        repeat: bool = False,
        name: str = "watchdog",
    ) -> None:
        if timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")
        self._timeout = float(timeout)
        self._on_bark = on_bark
        self._repeat = repeat
        self._name = name

        self._lock = threading.Lock()
        self._last_pet: float = 0.0
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._barked = False

    # -- public API ----------------------------------------------------------

    def start(self) -> None:
        """Start the watchdog background thread.  Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._barked = False
        with self._lock:
            self._last_pet = time.monotonic()
        self._thread = threading.Thread(
            target=self._run, name=self._name, daemon=True
        )
        self._thread.start()

    def pet(self) -> None:
        """Record a heartbeat.  Safe to call from any thread."""
        with self._lock:
            self._last_pet = time.monotonic()

    def stop(self) -> None:
        """Stop the watchdog.  Blocks until the background thread exits."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._timeout + 1.0)
            self._thread = None

    @property
    def barked(self) -> bool:
        """Whether the watchdog has barked at least once."""
        return self._barked

    @property
    def elapsed(self) -> float:
        """Seconds since the last pet (or since start if never petted)."""
        with self._lock:
            return time.monotonic() - self._last_pet

    @property
    def is_alive(self) -> bool:
        """Whether the background thread is running."""
        return self._thread is not None and self._thread.is_alive()

    # -- internals -----------------------------------------------------------

    def _run(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                remaining = self._timeout - (time.monotonic() - self._last_pet)

            if remaining <= 0:
                self._barked = True
                try:
                    self._on_bark()
                except Exception:
                    pass  # watchdog must not crash on callback errors
                if not self._repeat:
                    return
                # Reset timer after bark so repeat mode waits a full interval
                with self._lock:
                    self._last_pet = time.monotonic()
                remaining = self._timeout

            self._stop_event.wait(timeout=remaining)


if __name__ == "__main__":
    import doctest

    doctest.testmod(verbose=True)
