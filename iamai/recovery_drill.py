"""recovery_drill — self-test the recovery pipeline end-to-end.

Runs a simulated stall-and-recovery scenario through a fresh
RecoveryCoordinator and verifies that the full lifecycle produces
the expected sequence of actions:

    CONTINUE (healthy) → PAUSE (breaker trips) → WAIT (cooldown)
    → PROBE (half-open) → CONTINUE (recovered)

This is a *pure decision-logic* test: no processes, no git, no
files are touched.  It only verifies that the coordinator brain
works correctly given a known input sequence.

Intended to be called by caretaker visits as a smoke test before
and after any changes to the recovery stack.

Usage::

    from iamai.recovery_drill import run_drill

    result = run_drill()
    if result.passed:
        print("recovery pipeline healthy")
    else:
        print(f"DRILL FAILED: {result.failures}")
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from iamai.recovery_coordinator import (
    RecoveryAction,
    RecoveryCoordinator,
    RecoveryEvent,
    default_coordinator,
)


# ---------------------------------------------------------------------------
# Drill result
# ---------------------------------------------------------------------------

@dataclass
class DrillStep:
    """A single step in the drill scenario."""
    tick_index: int
    health: float
    strokes: List[str]
    expected_action: Optional[RecoveryAction] = None
    actual_action: Optional[RecoveryAction] = None
    breaker_state: str = ""
    passed: bool = True
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tick_index": self.tick_index,
            "health": self.health,
            "strokes": self.strokes,
            "expected_action": (
                self.expected_action.value if self.expected_action else None
            ),
            "actual_action": (
                self.actual_action.value if self.actual_action else None
            ),
            "breaker_state": self.breaker_state,
            "passed": self.passed,
            "note": self.note,
        }


@dataclass
class DrillResult:
    """Outcome of a full drill run."""
    passed: bool
    steps: List[DrillStep]
    failures: List[str] = field(default_factory=list)
    total_ticks: int = 0
    actions_seen: List[str] = field(default_factory=list)
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "steps": [s.to_dict() for s in self.steps],
            "failures": self.failures,
            "total_ticks": self.total_ticks,
            "actions_seen": self.actions_seen,
            "duration_ms": self.duration_ms,
        }

    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        fail_info = (
            f" ({len(self.failures)} failure(s))" if self.failures else ""
        )
        actions = " → ".join(self.actions_seen) if self.actions_seen else "none"
        return (
            f"drill {status}{fail_info}: "
            f"{self.total_ticks} ticks, actions=[{actions}], "
            f"{self.duration_ms:.0f}ms"
        )


# ---------------------------------------------------------------------------
# Scenario builder
# ---------------------------------------------------------------------------

@dataclass
class ScenarioTick:
    """One tick in the drill scenario."""
    health: float
    strokes: List[str] = field(default_factory=list)
    expect_action: Optional[RecoveryAction] = None
    expect_state: Optional[str] = None
    note: str = ""


def default_scenario() -> List[ScenarioTick]:
    """Build the standard drill scenario.

    With default coordinator params (trip_after=3, cooldown_ticks=5,
    probe_window=2, health_threshold=0.5):

    Sequence (16 ticks):
    - 3 healthy ticks → CONTINUE × 3 (CLOSED)
    - 3 bad ticks    → CONTINUE × 2 + PAUSE (breaker trips at 3rd)
    - 4 bad ticks    → WAIT × 4 (OPEN cooldown)
    - 1 bad + 1 good → PROBE × 2 (HALF_OPEN, probe_window=2)
    - 4 healthy ticks → CONTINUE × 4 (CLOSED, recovered)
    """
    good_strokes = [
        "wrote a thoughtful note about dependency injection",
        "added 12 tests for the batch committer",
        "refactored the caretaker intake module",
    ]
    bad_strokes = ["wrote something", "wrote something", "wrote something"]

    scenario: List[ScenarioTick] = []

    # Phase 1: healthy operation (3 ticks)
    for i in range(3):
        scenario.append(ScenarioTick(
            health=0.9,
            strokes=good_strokes,
            expect_action=RecoveryAction.CONTINUE,
            expect_state="closed",
            note=f"healthy tick {i}",
        ))

    # Phase 2: degradation (3 ticks — trip_after=3)
    # Ticks 0-1: still counting → CONTINUE
    # Tick 2: breaker trips → PAUSE
    for i in range(3):
        scenario.append(ScenarioTick(
            health=0.1,
            strokes=bad_strokes,
            expect_action=(
                RecoveryAction.PAUSE if i == 2 else RecoveryAction.CONTINUE
            ),
            expect_state="open" if i == 2 else "closed",
            note=f"degradation tick {i}",
        ))

    # Phase 3: cooldown (4 ticks in OPEN after the PAUSE tick)
    # PAUSE consumed tick 0 in OPEN; ticks 1-4 are WAIT
    for i in range(4):
        scenario.append(ScenarioTick(
            health=0.1,
            strokes=bad_strokes,
            expect_action=RecoveryAction.WAIT,
            expect_state="open",
            note=f"cooldown tick {i}",
        ))

    # Phase 4: half-open (2 ticks — probe_window=2)
    # First probe with bad health, second with good
    scenario.append(ScenarioTick(
        health=0.1,
        strokes=bad_strokes,
        expect_action=RecoveryAction.PROBE,
        expect_state="half_open",
        note="probe tick 0 (bad health)",
    ))
    scenario.append(ScenarioTick(
        health=0.9,
        strokes=good_strokes,
        expect_action=RecoveryAction.PROBE,
        expect_state="half_open",
        note="probe tick 1 (good health)",
    ))

    # Phase 5: recovered (4 ticks)
    for i in range(4):
        scenario.append(ScenarioTick(
            health=0.9,
            strokes=good_strokes,
            expect_action=RecoveryAction.CONTINUE,
            expect_state="closed",
            note=f"recovered tick {i}",
        ))

    return scenario


# ---------------------------------------------------------------------------
# Drill runner
# ---------------------------------------------------------------------------

def run_drill(
    scenario: Optional[List[ScenarioTick]] = None,
    coordinator: Optional[RecoveryCoordinator] = None,
    trip_after: int = 3,
    cooldown_ticks: int = 5,
    health_threshold: float = 0.5,
) -> DrillResult:
    """Run the drill scenario and return the result.

    Parameters
    ----------
    scenario : list of ScenarioTick, optional
        The scenario to run.  Defaults to ``default_scenario()``.
    coordinator : RecoveryCoordinator, optional
        Use a specific coordinator.  If None, a fresh one is created
        with the given parameters.
    trip_after : int
        Consecutive bad windows before the breaker trips.
    cooldown_ticks : int
        Ticks to wait in OPEN before entering HALF_OPEN.
    health_threshold : float
        Health below which a tick is considered "bad".

    Returns
    -------
    DrillResult
    """
    if scenario is None:
        scenario = default_scenario()

    if coordinator is None:
        coordinator = default_coordinator(
            trip_after=trip_after,
            cooldown_ticks=cooldown_ticks,
            health_threshold=health_threshold,
        )

    t0 = time.monotonic()
    steps: List[DrillStep] = []
    failures: List[str] = []
    actions_seen: List[str] = []

    for idx, tick in enumerate(scenario):
        event = coordinator.tick(tick.health, tick.strokes)

        step = DrillStep(
            tick_index=idx,
            health=tick.health,
            strokes=tick.strokes,
            expected_action=tick.expect_action,
            actual_action=event.action,
            breaker_state=event.breaker_state,
            note=tick.note,
        )

        # Check action expectation
        if tick.expect_action is not None and event.action != tick.expect_action:
            step.passed = False
            msg = (
                f"tick {idx} ({tick.note}): "
                f"expected {tick.expect_action.value}, "
                f"got {event.action.value}"
            )
            failures.append(msg)

        # Check state expectation
        if tick.expect_state is not None and event.breaker_state != tick.expect_state:
            step.passed = False
            msg = (
                f"tick {idx} ({tick.note}): "
                f"expected state={tick.expect_state}, "
                f"got state={event.breaker_state}"
            )
            failures.append(msg)

        actions_seen.append(event.action.value)
        steps.append(step)

    duration_ms = (time.monotonic() - t0) * 1000

    return DrillResult(
        passed=len(failures) == 0,
        steps=steps,
        failures=failures,
        total_ticks=len(steps),
        actions_seen=actions_seen,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the drill and print results."""
    result = run_drill()
    print(result.summary())
    if not result.passed:
        for f in result.failures:
            print(f"  FAIL: {f}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
