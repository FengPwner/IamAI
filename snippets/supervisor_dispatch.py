"""584 — supervisor_dispatch: map escalation levels to recovery strategies.

escalation_relay tells you *when* the severity changes. but what should
the supervisor actually *do* at each level? this module answers that.

it's a strategy dispatcher: given an escalation level, look up the
registered handler and execute it. different levels get different
responses — yellow might log a warning, red might restart the process,
critical might page a human.

    level        ──►  handler(level, context)
    ─────────────────────────────────────────
    "yellow"     ──►  log_warning(level, ctx)
    "red"        ──►  restart_writer(level, ctx)
    "critical"   ──►  page_oncall(level, ctx)

design decisions:

  1. **handlers are callables, not classes.** no reason to force a
     subclass hierarchy when a function will do. register any callable
     with signature (level: str, context: dict) -> DispatchResult.

  2. **fallthrough to default.** if no handler is registered for a
     level, the default handler fires. this prevents silent drops when
     a new escalation level is added but the dispatch table isn't
     updated.

  3. **context is a dict, not kwargs.** handlers receive a context bag
     that can carry anything: timestamps, process ids, memory stats,
     escalation history. handlers pick what they need. we don't
     validate the bag — that's the handler's job.

  4. **results are structured.** every handler returns a DispatchResult
     with action taken, success flag, and optional detail. this makes
     the dispatch auditable without parsing log output.

  5. **exception isolation.** a crashing handler is caught, counted,
     and reported as a failed dispatch. the dispatcher itself never
     crashes.

zero dependencies. stdlib only.

>>> d = SupervisorDispatch()
>>> d.register("yellow", lambda lvl, ctx: DispatchResult("logged", True, f"warned at {lvl}"))
>>> d.register("red", lambda lvl, ctx: DispatchResult("restarted", True, "writer pid 42"))
>>> result = d.dispatch("yellow", {"ts": 100.0})
>>> result.action
'logged'
>>> result.ok
True
>>> d.dispatch("red", {}).action
'restarted'
>>> d.dispatch("critical", {}).action   # no handler → default
'default'
>>> d.dispatch_count
3
>>> d.error_count
0
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """Outcome of a single dispatch call."""

    action: str
    ok: bool
    detail: str = ""

    def __bool__(self) -> bool:
        return self.ok


# ---------------------------------------------------------------------------
# handler type
# ---------------------------------------------------------------------------

DispatchHandler = Callable[[str, Dict[str, Any]], DispatchResult]


# ---------------------------------------------------------------------------
# default handler
# ---------------------------------------------------------------------------


def _default_handler(level: str, context: Dict[str, Any]) -> DispatchResult:
    """Fallback: acknowledge the event but take no action."""
    return DispatchResult(
        action="default",
        ok=True,
        detail=f"no handler registered for level={level!r}",
    )


# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------


class SupervisorDispatch:
    """Map escalation levels to recovery handlers and execute them."""

    __slots__ = (
        "_handlers",
        "_default",
        "_dispatch_count",
        "_error_count",
        "_history",
        "_clock",
    )

    def __init__(
        self,
        default: Optional[DispatchHandler] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._handlers: Dict[str, DispatchHandler] = {}
        self._default = default or _default_handler
        self._dispatch_count: int = 0
        self._error_count: int = 0
        self._history: List[tuple] = []  # (level, DispatchResult, timestamp)
        self._clock = clock or time.monotonic

    # -- registration -------------------------------------------------------

    def register(self, level: str, handler: DispatchHandler) -> None:
        """Register a handler for a specific escalation level.

        Replaces any previously registered handler for that level.
        """
        if handler is None:
            raise ValueError("handler must not be None")
        if not level:
            raise ValueError("level must be a non-empty string")
        self._handlers[level] = handler

    def unregister(self, level: str) -> bool:
        """Remove the handler for a level. Returns True if one existed."""
        return self._handlers.pop(level, None) is not None

    @property
    def registered_levels(self) -> List[str]:
        """Sorted list of levels with explicit handlers."""
        return sorted(self._handlers.keys())

    # -- dispatch -----------------------------------------------------------

    def dispatch(
        self,
        level: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> DispatchResult:
        """Look up the handler for *level*, execute it, return the result.

        If no handler is registered for *level*, the default handler fires.
        If the handler raises, the error is counted and a failed result
        is returned.
        """
        self._dispatch_count += 1
        ctx = context if context is not None else {}
        handler = self._handlers.get(level, self._default)
        now = self._clock()

        try:
            result = handler(level, ctx)
        except Exception as exc:
            self._error_count += 1
            result = DispatchResult(
                action="error",
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
            )

        self._history.append((level, result, now))
        return result

    def dispatch_many(
        self,
        levels: List[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[DispatchResult]:
        """Dispatch sequentially for a list of levels. Returns all results."""
        return [self.dispatch(lv, context) for lv in levels]

    # -- introspection ------------------------------------------------------

    @property
    def dispatch_count(self) -> int:
        """Total number of dispatch() calls."""
        return self._dispatch_count

    @property
    def error_count(self) -> int:
        """Number of dispatches where the handler raised an exception."""
        return self._error_count

    @property
    def history(self) -> List[tuple]:
        """Copy of (level, DispatchResult, timestamp) for all dispatches."""
        return list(self._history)

    def summary(self) -> Dict[str, Any]:
        """Compact summary for monitoring dashboards."""
        ok_count = sum(1 for _, r, _ in self._history if r.ok)
        return {
            "total": self._dispatch_count,
            "ok": ok_count,
            "errors": self._error_count,
            "levels": self.registered_levels,
        }

    def reset(self) -> None:
        """Clear counts and history. Handlers are preserved."""
        self._dispatch_count = 0
        self._error_count = 0
        self._history.clear()

    def __repr__(self) -> str:
        return (
            f"SupervisorDispatch(levels={self.registered_levels}, "
            f"dispatches={self._dispatch_count}, errors={self._error_count})"
        )
