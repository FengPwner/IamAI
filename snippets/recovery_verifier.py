"""586 — recovery_verifier: confirm that dispatched recovery actions took effect.

supervisor_dispatch fires the handler. dispatch_dampener prevents flapping.
but after a restart, a page, a config reload — who checks whether it
actually *worked*?

this module closes the loop:

    escalation ──► relay ──► dampener ──► dispatcher ──► handler
                                                        │
                                              recovery_verifier ◄──┘
                                                        │
                                          VerifyResult: recovered / failed / pending

it maintains a probe registry: for each action label, a callable that
returns True if the system is healthy post-recovery. after a dispatch,
schedule a delayed probe; the result feeds back into the escalation
pipeline so a failed recovery can trigger further escalation.

design decisions:

  1. **probes are callables, not subclasses.** register any
     `() -> bool` for a given action label. the recovery_verifier
     doesn't care *how* you check health — just that you return
     True (recovered) or False (still broken).

  2. **delayed verification.** recovery isn't instant. a restarted
     process needs warmup time. each probe is scheduled with a
     configurable delay (default 30s) before execution. results
     are pending until the probe fires.

  3. **retry with backoff.** a single probe failure shouldn't
     immediately escalate. `max_retries` (default 2) gives the
     system a few chances before declaring failure. retry delays
     double each attempt: 30s, 60s, 120s.

  4. **result is a dataclass, not a bool.** VerifyResult carries
     action_label, dispatch_id, status (pending/recovered/failed),
     attempts count, last_probe_at, and an optional detail string.
     consumers can log, alert, or feed it back into the relay.

  5. **injectable clock and scheduler.** same pattern as the rest
     of the project. pass clock= for deterministic tests; defaults
     to time.time.

  6. **bounded tracking.** pending_probes is capped at
     `max_pending` (default 500). oldest entries are evicted if
     the cap is hit — stale probes that never fired are less
     useful than fresh ones.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class VerifyResult:
    """outcome of a recovery verification probe."""
    action_label: str
    dispatch_id: str
    status: str  # "pending" | "recovered" | "failed"
    attempts: int = 0
    max_retries: int = 2
    last_probe_at: Optional[float] = None
    detail: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in ("recovered", "failed")

    def __repr__(self) -> str:
        return (
            f"VerifyResult({self.action_label!r}, "
            f"dispatch={self.dispatch_id!r}, "
            f"status={self.status!r}, "
            f"attempts={self.attempts})"
        )


@dataclass
class _PendingProbe:
    """internal: a scheduled probe waiting to fire."""
    action_label: str
    dispatch_id: str
    probe: Callable[[], bool]
    fire_at: float
    attempt: int
    max_retries: int
    base_delay: float
    result: VerifyResult


class RecoveryVerifier:
    """register probes, schedule verifications after dispatches, run them.

    usage:
        verifier = RecoveryVerifier()
        verifier.register_probe("restart_writer", lambda: is_writer_alive())
        verifier.register_probe("page_oncall", lambda: ack_received())

        # after dispatcher fires restart_writer:
        result = verifier.schedule("restart_writer", dispatch_id="d-42")

        # periodically:
        verifier.tick()  # fires due probes, updates results

        # check outcome:
        print(result.status)  # "recovered" or "failed" or "pending"
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        default_delay: float = 30.0,
        default_max_retries: int = 2,
        max_pending: int = 500,
    ):
        self._clock = clock
        self._default_delay = default_delay
        self._default_max_retries = default_max_retries
        self._max_pending = max_pending
        self._probes: Dict[str, Callable[[], bool]] = {}
        self._pending: OrderedDict[str, _PendingProbe] = OrderedDict()
        self._history: List[VerifyResult] = []

    # ── probe registry ──────────────────────────────────────────

    def register_probe(self, action_label: str, probe: Callable[[], bool]) -> None:
        """register a health probe for an action label.

        the probe must return True (healthy) or False (still broken).
        raises ValueError if a probe is already registered for this label.
        """
        if action_label in self._probes:
            raise ValueError(f"probe already registered for {action_label!r}")
        self._probes[action_label] = probe

    def unregister_probe(self, action_label: str) -> None:
        """remove the probe for an action label. raises KeyError if absent."""
        if action_label not in self._probes:
            raise KeyError(action_label)
        del self._probes[action_label]

    def has_probe(self, action_label: str) -> bool:
        return action_label in self._probes

    def registered_labels(self) -> List[str]:
        return list(self._probes.keys())

    # ── scheduling ──────────────────────────────────────────────

    def schedule(
        self,
        action_label: str,
        dispatch_id: str,
        delay: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> VerifyResult:
        """schedule a verification probe after a dispatch.

        returns a VerifyResult that starts as "pending" and is updated
        in-place by tick(). if no probe is registered for the label,
        the result is immediately "failed" with detail="no probe".
        """
        probe = self._probes.get(action_label)
        if probe is None:
            result = VerifyResult(
                action_label=action_label,
                dispatch_id=dispatch_id,
                status="failed",
                attempts=0,
                detail="no probe registered",
            )
            self._history.append(result)
            return result

        d = delay if delay is not None else self._default_delay
        mr = max_retries if max_retries is not None else self._default_max_retries
        now = self._clock()

        result = VerifyResult(
            action_label=action_label,
            dispatch_id=dispatch_id,
            status="pending",
            attempts=0,
            max_retries=mr,
        )

        pending = _PendingProbe(
            action_label=action_label,
            dispatch_id=dispatch_id,
            probe=probe,
            fire_at=now + d,
            attempt=0,
            max_retries=mr,
            base_delay=d,
            result=result,
        )

        key = f"{action_label}:{dispatch_id}"
        self._pending[key] = pending
        self._evict_if_needed()

        return result

    # ── execution ───────────────────────────────────────────────

    def tick(self) -> List[VerifyResult]:
        """fire all due probes and return results that transitioned this tick."""
        now = self._clock()
        fired: List[VerifyResult] = []
        to_remove: List[str] = []

        for key, pp in self._pending.items():
            if now < pp.fire_at:
                continue

            pp.attempt += 1
            pp.result.attempts = pp.attempt
            pp.result.last_probe_at = now

            try:
                ok = pp.probe()
            except Exception as exc:
                ok = False
                pp.result.detail = f"probe raised: {exc!r}"

            if ok:
                pp.result.status = "recovered"
                pp.result.detail = ""
                fired.append(pp.result)
                to_remove.append(key)
            elif pp.attempt >= pp.max_retries + 1:
                pp.result.status = "failed"
                if not pp.result.detail:
                    pp.result.detail = f"failed after {pp.attempt} attempts"
                fired.append(pp.result)
                to_remove.append(key)
            else:
                # schedule retry with exponential backoff
                retry_delay = pp.base_delay * (2 ** pp.attempt)
                pp.fire_at = now + retry_delay

        for key in to_remove:
            pp = self._pending.pop(key)
            self._history.append(pp.result)

        return fired

    # ── introspection ───────────────────────────────────────────

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def history(self) -> List[VerifyResult]:
        return list(self._history)

    def pending_results(self) -> List[VerifyResult]:
        return [pp.result for pp in self._pending.values()]

    def summary(self) -> Dict[str, int]:
        """counts by status across pending + history."""
        counts = {"pending": 0, "recovered": 0, "failed": 0}
        for pp in self._pending.values():
            counts[pp.result.status] = counts.get(pp.result.status, 0) + 1
        for r in self._history:
            counts[r.status] = counts.get(r.status, 0) + 1
        return counts

    # ── internal ────────────────────────────────────────────────

    def _evict_if_needed(self) -> None:
        while len(self._pending) > self._max_pending:
            key, pp = self._pending.popitem(last=False)
            pp.result.status = "failed"
            pp.result.detail = "evicted (max_pending exceeded)"
            self._history.append(pp.result)
