"""063 — state_machine: a finite-state machine with guarded transitions.

state machines show up everywhere in systems code but rarely get their
own abstraction.  developers encode states as string constants and
transitions as if/elif chains scattered across three files.  the result
works but is fragile: adding a state means hunting for every branch, and
a typo in a string silently creates a new state instead of crashing.

this module gives you a small, explicit FSM:

    sm = StateMachine("idle", transitions={
        ("idle",   "start"):  "running",
        ("running","pause"):  "paused",
        ("paused", "resume"): "running",
        ("running","stop"):   "stopped",
        ("paused", "stop"):   "stopped",
    })

    sm.state            # "idle"
    sm.fire("start")    # "running"
    sm.fire("pause")    # "paused"
    sm.fire("resume")   # "running"
    sm.fire("stop")     # "stopped"

invalid transitions raise ``InvalidTransition`` — no silent corruption,
no falling through to a default branch.  you can query allowed events
from the current state with ``sm.allowed`` and check reachability with
``sm.can_reach(target)``.

callbacks are supported but optional: register an ``on_enter`` or
``on_exit`` handler per state, and they fire on every transition that
enters or leaves that state.  handlers receive the event name and the
source/target states, so one handler can cover many transitions.

    sm = StateMachine("idle", transitions={...},
        on_enter={"running": lambda ev, src, tgt: log("started")},
        on_exit= {"running": lambda ev, src, tgt: log("left running")},
    )

why not use an existing library?  because the point of a snippet is
zero-dependency readability.  this fits in one file, has no magic, and
the entire contract is visible in the constructor call.

zero external dependencies.  stdlib only.

>>> sm = StateMachine("idle", transitions={
...     ("idle", "start"): "running",
...     ("running", "stop"): "stopped",
... })
>>> sm.state
'idle'
>>> sm.fire("start")
'running'
>>> sm.fire("stop")
'stopped'
>>> sm.fire("start")  # doctest: +IGNORE_EXCEPTION_DETAIL
Traceback (most recent call last):
    ...
InvalidTransition: no transition from 'stopped' on event 'start'
"""

from __future__ import annotations

from typing import Callable, Dict, Optional, Set, Tuple


class InvalidTransition(Exception):
    """Raised when an event has no defined transition from the current state."""

    def __init__(self, state: str, event: str) -> None:
        self.state = state
        self.event = event
        super().__init__(f"no transition from {state!r} on event {event!r}")


# Type aliases for readability.
_Transitions = Dict[Tuple[str, str], str]
_Callbacks = Dict[str, Callable[[str, str, str], None]]


class StateMachine:
    """Explicit finite-state machine with optional enter/exit callbacks."""

    def __init__(
        self,
        initial: str,
        *,
        transitions: _Transitions,
        on_enter: Optional[_Callbacks] = None,
        on_exit: Optional[_Callbacks] = None,
    ) -> None:
        self._state = initial
        self._transitions = dict(transitions)
        self._on_enter = dict(on_enter or {})
        self._on_exit = dict(on_exit or {})

        # Collect the universe of known states from the transition table.
        states: Set[str] = {initial}
        for (src, _ev), tgt in self._transitions.items():
            states.add(src)
            states.add(tgt)
        self._states = frozenset(states)

    # -- query ---------------------------------------------------------------

    @property
    def state(self) -> str:
        """The current state."""
        return self._state

    @property
    def states(self) -> frozenset:
        """All states reachable via the transition table (plus initial)."""
        return self._states

    @property
    def allowed(self) -> Set[str]:
        """Events that have a defined transition from the current state."""
        return {
            ev for (src, ev), _tgt in self._transitions.items() if src == self._state
        }

    def can_reach(self, target: str) -> bool:
        """True if *target* is reachable from the current state in any steps.

        Uses a simple BFS over the transition graph.  Does not fire any
        callbacks or mutate state.
        """
        visited: Set[str] = set()
        queue = [self._state]
        while queue:
            node = queue.pop(0)
            if node == target:
                return True
            if node in visited:
                continue
            visited.add(node)
            for (src, _ev), tgt in self._transitions.items():
                if src == node and tgt not in visited:
                    queue.append(tgt)
        return False

    # -- mutate --------------------------------------------------------------

    def fire(self, event: str) -> str:
        """Apply *event*, transitioning to the target state.

        Raises ``InvalidTransition`` if no transition is defined for this
        event from the current state.  Fires on_exit (old state) then
        on_enter (new state) callbacks if registered.

        Returns the new state.
        """
        key = (self._state, event)
        if key not in self._transitions:
            raise InvalidTransition(self._state, event)

        old = self._state
        new = self._transitions[key]

        # Exit callback for the old state.
        exit_cb = self._on_exit.get(old)
        if exit_cb is not None:
            exit_cb(event, old, new)

        self._state = new

        # Enter callback for the new state.
        enter_cb = self._on_enter.get(new)
        if enter_cb is not None:
            enter_cb(event, old, new)

        return new

    # -- dunder --------------------------------------------------------------

    def __repr__(self) -> str:
        return f"StateMachine(state={self._state!r}, states={len(self._states)})"
