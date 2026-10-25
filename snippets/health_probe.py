"""Health probe — standardized liveness/readiness checks for long-running services.

watchdog.py detects stuck loops.  circuit_breaker.py stops calling broken
downstreams.  deadman.py declares a silent process dead.  But none of
these answer the question an orchestrator actually asks: *is this thing
ready to serve?*

A health probe is a callable that returns one of three verdicts:

    HEALTHY    — operating normally, accept traffic / keep running
    DEGRADED   — functional but impaired, flag for attention
    UNHEALTHY  — not fit to serve, trigger restart or drain

Each probe bundles:

- **name** — human-readable identifier for dashboards and logs
- **check()** — the actual test; returns (verdict, detail_string)
- **timeout** — max seconds the check is allowed to run
- **last_result** — cached verdict so dashboards can poll without re-running

Design principles:

- stdlib only, zero deps
- injectable clock for deterministic tests
- composable: combine probes into a HealthCheck that aggregates results

>>> import time
>>> def always_ok():
...     return (HEALTHY, "all good")
>>> p = HealthProbe("example", always_ok, timeout=1.0)
>>> verdict, detail = p.check()
>>> verdict == HEALTHY
True
>>> detail
'all good'
>>> p.last_result == HEALTHY
True

A probe that raises an exception is UNHEALTHY:

>>> def boom():
...     raise RuntimeError("disk full")
>>> p2 = HealthProbe("disk", boom, timeout=1.0)
>>> v, d = p2.check()
>>> v == UNHEALTHY
True
>>> 'disk full' in d
True

Aggregating multiple probes:

>>> hc = HealthCheck([
...     HealthProbe("a", lambda: (HEALTHY, "ok")),
...     HealthProbe("b", lambda: (DEGRADED, "slow")),
... ])
>>> results = hc.run_all()
>>> hc.overall == DEGRADED
True
>>> len(results)
2
"""

from __future__ import annotations

import time
from typing import Callable, List, Optional, Tuple

# Verdicts — plain strings so they serialise to JSON without an enum dance.
HEALTHY = "healthy"
DEGRADED = "degraded"
UNHEALTHY = "unhealthy"

# Severity ordering for aggregation: worst verdict wins.
_SEVERITY = {HEALTHY: 0, DEGRADED: 1, UNHEALTHY: 2}

# Type alias for the check callable.
CheckFn = Callable[[], Tuple[str, str]]


class HealthProbe:
    """A single named health check with timeout and cached result."""

    def __init__(
        self,
        name: str,
        check_fn: CheckFn,
        timeout: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.name = name
        self._check = check_fn
        self.timeout = timeout
        self._clock = clock
        self.last_result: Optional[str] = None
        self.last_detail: str = ""
        self.last_checked_at: float = 0.0

    def check(self) -> Tuple[str, str]:
        """Run the probe, cache the result, return (verdict, detail)."""
        t0 = self._clock()
        try:
            verdict, detail = self._check()
            # Validate verdict — anything unrecognised is UNHEALTHY.
            if verdict not in _SEVERITY:
                original = verdict
                verdict = UNHEALTHY
                detail = f"unknown verdict '{original}': {detail}"
        except Exception as exc:
            verdict = UNHEALTHY
            detail = f"exception: {exc}"

        elapsed = self._clock() - t0
        if elapsed > self.timeout:
            verdict = UNHEALTHY
            detail = f"timeout after {elapsed:.1f}s (limit {self.timeout}s): {detail}"

        self.last_result = verdict
        self.last_detail = detail
        self.last_checked_at = self._clock()
        return verdict, detail

    def summary(self) -> dict:
        """Return a dict suitable for JSON serialisation."""
        return {
            "name": self.name,
            "verdict": self.last_result,
            "detail": self.last_detail,
            "checked_at": self.last_checked_at,
        }


class HealthCheck:
    """Aggregate multiple probes into a single health gate."""

    def __init__(self, probes: List[HealthProbe]):
        self.probes = list(probes)
        self._overall: str = HEALTHY

    @property
    def overall(self) -> str:
        return self._overall

    def run_all(self) -> List[Tuple[str, str, str]]:
        """Run every probe, return list of (name, verdict, detail)."""
        results = []
        worst = HEALTHY
        for probe in self.probes:
            verdict, detail = probe.check()
            results.append((probe.name, verdict, detail))
            if _SEVERITY.get(verdict, 2) > _SEVERITY.get(worst, 0):
                worst = verdict
        self._overall = worst
        return results

    def summary(self) -> dict:
        """Aggregate summary suitable for dashboards."""
        return {
            "overall": self._overall,
            "probes": [p.summary() for p in self.probes],
        }
