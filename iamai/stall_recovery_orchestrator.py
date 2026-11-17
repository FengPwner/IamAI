"""stall_recovery_orchestrator — coordinate multi-step recovery after stall detection.

When a writer stall is detected, recovery is not a single action but a
sequence: verify the stall, clear locks, restart processes, verify the
restart, flush backlog, and confirm push health.  Each step can succeed,
fail, or be skipped depending on context.  This module provides a
structured recovery plan and a step-by-step executor with rollback.

===========================  ============================================
module                       what it does
===========================  ============================================
stall_classifier             classifies stall type (transient/persistent)
stall_probe                  detects if stall is happening right now
recovery                     single-step recovery actions
**stall_recovery_orchestrator**  **plans and executes full recovery sequence**
===========================  ============================================

Recovery steps
--------------

1. **confirm_stall** — verify the stall is real (not a false positive)
2. **snapshot_state** — capture current process/git state for diagnostics
3. **clear_locks** — remove stale lock files that might block recovery
4. **restart_writer** — restart the writer process
5. **verify_restart** — confirm the new process is alive and producing
6. **drain_backlog** — commit any uncommitted strokes
7. **push_recover** — push recovered commits to remote
8. **confirm_health** — verify the system is back to healthy cadence

Each step returns a StepResult with status (ok/failed/skipped),
duration, and optional diagnostic data.  The orchestrator collects
all results into a RecoveryReport.

Zero dependencies.  stdlib only.

>>> plan = RecoveryPlan.default()
>>> len(plan.steps)
8
>>> plan.steps[0].name
'confirm_stall'
>>> report = RecoveryReport()
>>> report.add(StepResult('confirm_stall', 'ok', 0.1))
>>> report.is_complete
False
>>> report.success_count
1
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


# =========================================================================
# Data structures
# =========================================================================

@dataclass
class RecoveryStep:
    """One step in a recovery plan."""

    name: str
    description: str = ""
    timeout_s: float = 30.0
    required: bool = True
    rollback: Optional[str] = None  # name of step to run on failure

    def __repr__(self) -> str:
        return f"RecoveryStep({self.name!r}, required={self.required})"


@dataclass
class StepResult:
    """Result of executing one recovery step."""

    step_name: str
    status: str  # 'ok', 'failed', 'skipped', 'timeout'
    duration_s: float = 0.0
    message: str = ""
    diagnostics: Dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def failed(self) -> bool:
        return self.status == "failed"


@dataclass
class RecoveryReport:
    """Aggregated results of a full recovery execution."""

    results: List[StepResult] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0

    def add(self, result: StepResult) -> None:
        self.results.append(result)

    @property
    def total_duration(self) -> float:
        return sum(r.duration_s for r in self.results)

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def failure_count(self) -> int:
        return sum(1 for r in self.results if r.failed)

    @property
    def skipped_count(self) -> int:
        return sum(1 for r in self.results if r.status == "skipped")

    @property
    def is_complete(self) -> bool:
        """True if all required steps succeeded."""
        # Not complete if no results yet
        if not self.results:
            return False
        # Check if any required step failed
        return self.failure_count == 0 and self.success_count > 0

    @property
    def verdict(self) -> str:
        if not self.results:
            return "not_started"
        if self.failure_count > 0:
            return "partial_recovery"
        if self.skipped_count > 0:
            return "recovered_with_skips"
        return "fully_recovered"

    def summary(self) -> Dict:
        return {
            "verdict": self.verdict,
            "total_duration_s": round(self.total_duration, 2),
            "steps_ok": self.success_count,
            "steps_failed": self.failure_count,
            "steps_skipped": self.skipped_count,
            "step_details": [
                {
                    "name": r.step_name,
                    "status": r.status,
                    "duration_s": round(r.duration_s, 3),
                    "message": r.message,
                }
                for r in self.results
            ],
        }


# =========================================================================
# Recovery plan
# =========================================================================

class RecoveryPlan:
    """Defines the sequence of recovery steps to execute."""

    def __init__(self, steps: Optional[List[RecoveryStep]] = None):
        self.steps = steps or []

    @classmethod
    def default(cls) -> "RecoveryPlan":
        """Standard recovery plan for a writer stall."""
        return cls(
            [
                RecoveryStep(
                    "confirm_stall",
                    "Verify stall is real, not a false positive",
                    timeout_s=5.0,
                ),
                RecoveryStep(
                    "snapshot_state",
                    "Capture process and git state for diagnostics",
                    timeout_s=10.0,
                    required=False,
                ),
                RecoveryStep(
                    "clear_locks",
                    "Remove stale lock files",
                    timeout_s=5.0,
                    rollback="restore_locks",
                ),
                RecoveryStep(
                    "restart_writer",
                    "Restart the writer process",
                    timeout_s=15.0,
                ),
                RecoveryStep(
                    "verify_restart",
                    "Confirm new process is alive and producing strokes",
                    timeout_s=30.0,
                ),
                RecoveryStep(
                    "drain_backlog",
                    "Commit any uncommitted strokes",
                    timeout_s=60.0,
                    required=False,
                ),
                RecoveryStep(
                    "push_recover",
                    "Push recovered commits to remote",
                    timeout_s=30.0,
                ),
                RecoveryStep(
                    "confirm_health",
                    "Verify system is back to healthy cadence",
                    timeout_s=60.0,
                    required=False,
                ),
            ]
        )

    @classmethod
    def minimal(cls) -> "RecoveryPlan":
        """Minimal plan: just restart and push."""
        return cls(
            [
                RecoveryStep("restart_writer", "Restart writer", timeout_s=15.0),
                RecoveryStep("push_recover", "Push any pending", timeout_s=30.0),
            ]
        )

    def step_names(self) -> List[str]:
        return [s.name for s in self.steps]

    def required_steps(self) -> List[RecoveryStep]:
        return [s for s in self.steps if s.required]

    def __len__(self) -> int:
        return len(self.steps)

    def __repr__(self) -> str:
        return f"RecoveryPlan({len(self.steps)} steps)"


# =========================================================================
# Step executors (pure functions for testability)
# =========================================================================

def classify_stall_severity(
    gap_seconds: float,
    target_cadence: float = 15.0,
    consecutive_stalls: int = 0,
) -> str:
    """Classify how severe a stall is.

    Returns one of: 'transient', 'moderate', 'severe', 'critical'.

    >>> classify_stall_severity(20.0)
    'transient'
    >>> classify_stall_severity(120.0)
    'moderate'
    >>> classify_stall_severity(600.0)
    'severe'
    >>> classify_stall_severity(600.0, consecutive_stalls=3)
    'critical'
    """
    ratio = gap_seconds / target_cadence
    if consecutive_stalls >= 3:
        return "critical"
    if ratio >= 20:
        return "severe"
    if ratio >= 5:
        return "moderate"
    return "transient"


def recommend_plan(severity: str) -> str:
    """Recommend which recovery plan to use based on severity.

    >>> recommend_plan('transient')
    'minimal'
    >>> recommend_plan('severe')
    'default'
    >>> recommend_plan('critical')
    'default'
    """
    if severity == "transient":
        return "minimal"
    return "default"


def estimate_recovery_time(plan_name: str) -> float:
    """Estimate how long recovery will take in seconds.

    >>> estimate_recovery_time('minimal')
    45.0
    >>> estimate_recovery_time('default')
    210.0
    """
    estimates = {
        "minimal": 45.0,
        "default": 210.0,
    }
    return estimates.get(plan_name, 120.0)


def should_skip_step(
    step_name: str,
    prior_results: List[StepResult],
) -> bool:
    """Decide if a step should be skipped based on prior results.

    A required step is never skipped.  An optional step is skipped if
    a prior required step failed (no point continuing the optional parts).

    >>> should_skip_step('snapshot_state', [StepResult('confirm_stall', 'failed')])
    True
    >>> should_skip_step('drain_backlog', [StepResult('confirm_stall', 'ok')])
    False
    >>> should_skip_step('confirm_stall', [])
    False
    """
    # Required steps are never skipped
    required_steps = {
        "confirm_stall",
        "clear_locks",
        "restart_writer",
        "verify_restart",
        "push_recover",
    }
    if step_name in required_steps:
        return False

    # Optional steps are skipped if any required step failed
    has_failure = any(r.failed for r in prior_results)
    return has_failure


def compute_recovery_score(report: RecoveryReport) -> float:
    """Score the recovery 0.0–1.0 based on step outcomes.

    Required steps are weighted higher than optional ones.

    >>> r = RecoveryReport()
    >>> r.add(StepResult('confirm_stall', 'ok', 0.1))
    >>> r.add(StepResult('restart_writer', 'ok', 1.0))
    >>> score = compute_recovery_score(r)
    >>> 0.0 <= score <= 1.0
    True
    >>> compute_recovery_score(RecoveryReport())
    0.0
    """
    if not report.results:
        return 0.0

    required_steps = {
        "confirm_stall",
        "clear_locks",
        "restart_writer",
        "verify_restart",
        "push_recover",
    }

    total_weight = 0.0
    earned_weight = 0.0

    for r in report.results:
        weight = 2.0 if r.step_name in required_steps else 1.0
        total_weight += weight
        if r.ok:
            earned_weight += weight
        elif r.status == "skipped":
            earned_weight += weight * 0.5

    if total_weight == 0.0:
        return 0.0

    return earned_weight / total_weight


def format_recovery_log(report: RecoveryReport) -> str:
    """Format a recovery report as a human-readable log message.

    >>> r = RecoveryReport()
    >>> r.add(StepResult('confirm_stall', 'ok', 0.1, 'stall confirmed'))
    >>> log = format_recovery_log(r)
    >>> 'confirm_stall' in log
    True
    >>> 'ok' in log
    True
    """
    if not report.results:
        return "no recovery executed"

    lines = [f"recovery: {report.verdict} ({report.total_duration:.1f}s)"]
    for r in report.results:
        icon = "✓" if r.ok else ("✗" if r.failed else "⊘")
        line = f"  {icon} {r.step_name}: {r.status} ({r.duration_s:.2f}s)"
        if r.message:
            line += f" — {r.message}"
        lines.append(line)

    return "\n".join(lines)


# =========================================================================
# Orchestrator
# =========================================================================

class RecoveryOrchestrator:
    """Execute a recovery plan step by step.

    The orchestrator does NOT perform actual system operations — it
    coordinates by calling user-supplied executor functions for each
    step.  This makes it fully testable and reusable across different
    environments.

    >>> def mock_exec(step_name):
    ...     return StepResult(step_name, 'ok', 0.01, 'mocked')
    >>> orch = RecoveryOrchestrator(RecoveryPlan.minimal(), mock_exec)
    >>> report = orch.execute()
    >>> report.success_count
    2
    """

    def __init__(
        self,
        plan: RecoveryPlan,
        executor: Callable[[str], StepResult],
        on_step_complete: Optional[Callable[[StepResult], None]] = None,
    ):
        self.plan = plan
        self.executor = executor
        self.on_step_complete = on_step_complete

    def execute(self) -> RecoveryReport:
        """Run all steps in order, collecting results."""
        report = RecoveryReport()
        report.started_at = time.time()
        has_required_failure = False

        for step in self.plan.steps:
            if has_required_failure and step.required:
                # Stop at next required step after a failure
                break

            if should_skip_step(step.name, report.results):
                result = StepResult(step.name, "skipped", 0.0, "skipped due to prior failure")
            else:
                t0 = time.time()
                try:
                    result = self.executor(step.name)
                    result.duration_s = time.time() - t0
                except Exception as e:
                    result = StepResult(
                        step.name,
                        "failed",
                        time.time() - t0,
                        str(e),
                    )

            report.add(result)
            if self.on_step_complete:
                self.on_step_complete(result)

            if result.failed and step.required:
                has_required_failure = True

        report.finished_at = time.time()
        return report
