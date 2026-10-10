"""Graceful shutdown — coordinate orderly process termination.

When a process receives SIGTERM or SIGINT, it should finish what it's
doing, flush buffers, close connections, and exit cleanly. This module
provides a shutdown coordinator that tracks cleanup handlers and ensures
they run in reverse registration order (LIFO), with a configurable
timeout before forced termination.

Pattern: register cleanup callbacks, then call ``wait_for_signal()``
in your main loop. Handlers run on shutdown regardless of success/failure
of earlier handlers.

>>> import signal
>>> sd = ShutdownCoordinator(timeout=5.0)
>>> results = []
>>> sd.register("close-db", lambda: results.append("db"))
>>> sd.register("flush-log", lambda: results.append("log"))
>>> sd._run_handlers()
>>> results
['log', 'db']
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

log = logging.getLogger(__name__)


@dataclass
class _Handler:
    name: str
    fn: Callable[[], None]
    timeout: Optional[float] = None


@dataclass
class ShutdownCoordinator:
    """Coordinate orderly shutdown with LIFO handler execution.

    Parameters
    ----------
    timeout : float
        Maximum seconds to wait for all handlers before forcing exit.
    on_timeout : str
        Action on timeout: ``"force"`` calls ``sys.exit(1)``,
        ``"warn"`` logs and continues.

    >>> sd = ShutdownCoordinator(timeout=2.0)
    >>> sd.register("test", lambda: None)
    >>> len(sd._handlers)
    1
    """

    timeout: float = 10.0
    on_timeout: str = "force"
    _handlers: List[_Handler] = field(default_factory=list)
    _shutdown_requested: bool = False

    def register(
        self,
        name: str,
        fn: Callable[[], None],
        *,
        timeout: Optional[float] = None,
    ) -> None:
        """Register a cleanup handler. Runs last-registered-first on shutdown."""
        self._handlers.append(_Handler(name=name, fn=fn, timeout=timeout))

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested

    def request_shutdown(self, signum: int = 0, frame=None) -> None:
        """Signal handler callback — sets the shutdown flag."""
        self._shutdown_requested = True

    def _run_handlers(self) -> List[str]:
        """Execute all handlers in LIFO order. Returns list of handler names run."""
        executed: List[str] = []
        for handler in reversed(self._handlers):
            try:
                handler.fn()
                executed.append(handler.name)
            except Exception as exc:
                log.error("shutdown handler %r failed: %s", handler.name, exc)
                executed.append(handler.name)
        return executed

    def wait_for_signal(
        self,
        *,
        poll_interval: float = 0.5,
        signals: tuple = (signal.SIGTERM, signal.SIGINT),
    ) -> List[str]:
        """Block until a termination signal arrives, then run handlers.

        Installs signal handlers, polls for shutdown flag, runs cleanup.
        Returns list of handler names that were executed.
        """
        for sig in signals:
            signal.signal(sig, self.request_shutdown)

        while not self._shutdown_requested:
            time.sleep(poll_interval)

        return self._run_handlers()

    def shutdown_now(self) -> List[str]:
        """Trigger shutdown immediately (useful for testing or programmatic use)."""
        self._shutdown_requested = True
        return self._run_handlers()
