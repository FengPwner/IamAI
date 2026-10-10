"""062 — event_bus: a minimal synchronous pub/sub dispatcher.

when two parts of a system need to talk but shouldn't know each other's
names, an event bus sits between them.  publishers fire events into the
void; subscribers register interest in event types and get called when
something matches.  no coupling, no imports, no circular dependencies.

use cases from this codebase:

- writer emits "stroke_written" → committer, metrics, and devlog all react
- caretaker emits "restart" → deadman, watchdog, and push_guard all reset
- tests emit "fixture_ready" → multiple test helpers coordinate setup

the bus is deliberately synchronous: publish() blocks until every handler
returns.  this keeps the mental model simple and makes ordering predictable.
if you need async, wrap the handler body in a thread or coroutine — the
bus doesn't care what your handler does, only that it's callable.

    bus = EventBus()
    bus.on("stroke", lambda e: print(e.data))
    bus.emit("stroke", data={"path": "notes/foo.md"})
    # → prints {'path': 'notes/foo.md'}

handlers are called in registration order.  if a handler raises, the
exception propagates to the caller and remaining handlers are skipped —
fail-fast, same as a function call chain.  use `emit_safe()` to catch
exceptions per-handler and collect them instead.

wildcard subscriptions are supported: a handler registered on "*" receives
every event, with the event type available as `event.kind`.

zero external dependencies.  stdlib only.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class Event:
    """An immutable envelope carrying one event through the bus."""

    kind: str
    data: Any = None
    source: Optional[str] = None


class EventBus:
    """Synchronous publish/subscribe event dispatcher.

    Thread-safe for concurrent emit/on/off calls.  Handlers are called
    in registration order on the emitting thread.
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, List[Callable[[Event], Any]]] = {}
        self._lock = threading.Lock()
        self._event_count: int = 0

    # -- subscribe -------------------------------------------------------

    def on(self, kind: str, handler: Callable[[Event], Any]) -> Callable[[], None]:
        """Register *handler* for events of *kind*.

        Use ``"*"`` to receive every event.  Returns an unsubscribe
        callable — invoke it to remove this handler.

            unsub = bus.on("stroke", my_handler)
            ...
            unsub()  # handler removed
        """
        with self._lock:
            self._handlers.setdefault(kind, []).append(handler)

        def unsubscribe() -> None:
            with self._lock:
                handlers = self._handlers.get(kind, [])
                if handler in handlers:
                    handlers.remove(handler)

        return unsubscribe

    def off(self, kind: str, handler: Callable[[Event], Any]) -> bool:
        """Remove *handler* from *kind*.  Returns True if it was registered."""
        with self._lock:
            handlers = self._handlers.get(kind, [])
            if handler in handlers:
                handlers.remove(handler)
                return True
        return False

    # -- publish ---------------------------------------------------------

    def emit(self, kind: str, data: Any = None, source: Optional[str] = None) -> int:
        """Fire an event.  Returns the number of handlers invoked.

        Handlers are called in registration order.  If any handler raises,
        the exception propagates immediately; remaining handlers (for this
        kind and for ``"*"``) are skipped.
        """
        event = Event(kind=kind, data=data, source=source)
        count = 0
        for handler in self._snapshot(kind):
            handler(event)
            count += 1
        for handler in self._snapshot("*"):
            if kind == "*":
                continue  # avoid double-dispatch for wildcard subscribers
            handler(event)
            count += 1
        with self._lock:
            self._event_count += 1
        return count

    def emit_safe(
        self, kind: str, data: Any = None, source: Optional[str] = None
    ) -> tuple[int, list[BaseException]]:
        """Like emit(), but catches per-handler exceptions.

        Returns ``(count_called, errors)`` where *errors* is a list of
        exceptions raised by individual handlers.  All handlers run even
        if some fail.
        """
        event = Event(kind=kind, data=data, source=source)
        count = 0
        errors: list[BaseException] = []
        for handler in self._snapshot(kind):
            try:
                handler(event)
                count += 1
            except BaseException as exc:
                errors.append(exc)
        for handler in self._snapshot("*"):
            if kind == "*":
                continue
            try:
                handler(event)
                count += 1
            except BaseException as exc:
                errors.append(exc)
        with self._lock:
            self._event_count += 1
        return count, errors

    # -- introspection ---------------------------------------------------

    @property
    def event_count(self) -> int:
        """Total number of events emitted since construction."""
        with self._lock:
            return self._event_count

    def handler_count(self, kind: Optional[str] = None) -> int:
        """Number of registered handlers.  If *kind* is given, count only
        that kind (plus wildcard).  Omit for total across all kinds."""
        with self._lock:
            if kind is None:
                return sum(len(v) for v in self._handlers.values())
            specific = len(self._handlers.get(kind, []))
            wildcard = len(self._handlers.get("*", [])) if kind != "*" else 0
            return specific + wildcard

    def kinds(self) -> list[str]:
        """Return all event kinds that have at least one handler."""
        with self._lock:
            return [k for k, v in self._handlers.items() if v]

    # -- internal --------------------------------------------------------

    def _snapshot(self, kind: str) -> list[Callable[[Event], Any]]:
        """Thread-safe copy of the handler list for *kind*."""
        with self._lock:
            return list(self._handlers.get(kind, []))

    def __repr__(self) -> str:
        with self._lock:
            n_kinds = len([k for k, v in self._handlers.items() if v])
            n_handlers = sum(len(v) for v in self._handlers.values())
        return f"EventBus(kinds={n_kinds}, handlers={n_handlers}, events={self._event_count})"
