"""pre_push_gate — automatic divergence resolution before push.

Motivation
----------
Visits 534–540 share one failure mode: the push is rejected because the
remote branch advanced while the local writer was accumulating commits.
``push_divergence_monitor`` (visit 539) *measures* the divergence; this
module goes one step further and *resolves* it automatically when safe,
falling back to a clear signal when human intervention is needed.

The gate runs three phases:

1. **measure**  — how far ahead/behind are we?
2. **resolve**  — if remote_ahead > 0, attempt ``pull --rebase``;
   if that fails, classify the conflict severity.
3. **push**     — if resolution succeeded (or was unnecessary), push.

Each phase is a pure function that takes a ``GateContext`` and returns a
``GateResult``.  The ``run_gate`` orchestrator chains them and short-
circuits on failure.

Usage::

    from iamai.pre_push_gate import run_gate, GateConfig
    result = run_gate(GateConfig(repo="/path/to/repo"))
    print(result.outcome)  # "pushed" | "resolved_and_pushed" | "blocked"

Design choices
~~~~~~~~~~~~~~
- All git interactions are injected as callables (``count_fn``,
  ``rebase_fn``, ``push_fn``) so the entire gate is unit-testable
  without a real repo.
- Rebase is attempted only when divergence is ``nominal`` or ``growing``
  (<= 10 remote-ahead commits); ``critical`` divergence (11+) is flagged
  for manual merge to avoid silent history rewrites.
- The gate never force-pushes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, Tuple


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Outcome(str, Enum):
    PUSHED = "pushed"
    RESOLVED_AND_PUSHED = "resolved_and_pushed"
    BLOCKED_CONFLICT = "blocked_conflict"
    BLOCKED_CRITICAL = "blocked_critical"
    BLOCKED_NO_REMOTE = "blocked_no_remote"


class Severity(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DivergenceInfo:
    local_ahead: int
    remote_ahead: int

    @property
    def total(self) -> int:
        return self.local_ahead + self.remote_ahead

    @property
    def severity(self) -> Severity:
        if self.remote_ahead == 0:
            return Severity.NONE
        if self.remote_ahead <= 3:
            return Severity.LOW
        if self.remote_ahead <= 10:
            return Severity.MEDIUM
        return Severity.CRITICAL


@dataclass(frozen=True)
class GateConfig:
    """Everything the gate needs — paths, limits, injected git functions."""
    repo: str = "."
    remote: str = "origin"
    branch: str = "main"
    max_remote_ahead: int = 10
    count_fn: Optional[Callable[[str, str, str], Tuple[int, int]]] = None
    rebase_fn: Optional[Callable[[str, str, str], Tuple[bool, str]]] = None
    push_fn: Optional[Callable[[str, str, str], Tuple[bool, str]]] = None


@dataclass
class GateResult:
    outcome: Outcome
    divergence: Optional[DivergenceInfo] = None
    detail: str = ""
    rebased: bool = False
    pushed: bool = False


# ---------------------------------------------------------------------------
# Phase functions
# ---------------------------------------------------------------------------

def _default_count(repo: str, remote: str, branch: str) -> Tuple[int, int]:
    raise NotImplementedError("inject a count_fn for real usage")


def _default_rebase(repo: str, remote: str, branch: str) -> Tuple[bool, str]:
    raise NotImplementedError("inject a rebase_fn for real usage")


def _default_push(repo: str, remote: str, branch: str) -> Tuple[bool, str]:
    raise NotImplementedError("inject a push_fn for real usage")


def measure(cfg: GateConfig) -> GateResult:
    """Phase 1: measure local-vs-remote divergence."""
    count = cfg.count_fn or _default_count
    try:
        local_ahead, remote_ahead = count(cfg.repo, cfg.remote, cfg.branch)
    except Exception as exc:
        return GateResult(
            outcome=Outcome.BLOCKED_NO_REMOTE,
            detail=f"count failed: {exc}",
        )
    div = DivergenceInfo(local_ahead=local_ahead, remote_ahead=remote_ahead)
    return GateResult(
        outcome=Outcome.PUSHED,  # provisional
        divergence=div,
        detail=f"local={local_ahead} remote={remote_ahead} severity={div.severity.value}",
    )


def resolve(cfg: GateConfig, m: GateResult) -> GateResult:
    """Phase 2: attempt rebase if divergence is resolvable."""
    if m.outcome == Outcome.BLOCKED_NO_REMOTE:
        return m

    div = m.divergence
    assert div is not None

    if div.remote_ahead == 0:
        return m

    if div.severity == Severity.CRITICAL:
        return GateResult(
            outcome=Outcome.BLOCKED_CRITICAL,
            divergence=div,
            detail=f"remote_ahead={div.remote_ahead} exceeds max={cfg.max_remote_ahead}",
        )

    rebase = cfg.rebase_fn or _default_rebase
    ok, output = rebase(cfg.repo, cfg.remote, cfg.branch)
    if ok:
        return GateResult(
            outcome=Outcome.RESOLVED_AND_PUSHED,
            divergence=div,
            detail=f"rebase ok: {output}",
            rebased=True,
        )
    return GateResult(
        outcome=Outcome.BLOCKED_CONFLICT,
        divergence=div,
        detail=f"rebase failed: {output}",
    )


def push_phase(cfg: GateConfig, r: GateResult) -> GateResult:
    """Phase 3: push if resolution succeeded or was unnecessary."""
    if r.outcome in (Outcome.BLOCKED_CONFLICT, Outcome.BLOCKED_CRITICAL,
                     Outcome.BLOCKED_NO_REMOTE):
        return r

    push = cfg.push_fn or _default_push
    ok, output = push(cfg.repo, cfg.remote, cfg.branch)
    r.pushed = ok
    if not ok:
        r.detail += f" | push failed: {output}"
    else:
        r.detail += f" | push ok: {output}"
    return r


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_gate(cfg: GateConfig) -> GateResult:
    """Run the full pre-push gate: measure -> resolve -> push."""
    m = measure(cfg)
    r = resolve(cfg, m)
    return push_phase(cfg, r)


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------

def real_gate_config(repo: str = ".", remote: str = "origin",
                     branch: str = "main") -> GateConfig:
    """Build a GateConfig wired to actual git subprocess calls."""
    import subprocess

    def _count(r: str, rem: str, br: str) -> Tuple[int, int]:
        out = subprocess.check_output(
            ["git", "rev-list", "--left-right", "--count",
             f"{br}...{rem}/{br}"],
            cwd=r, text=True,
        ).strip()
        parts = out.split()
        return int(parts[0]), int(parts[1])

    def _rebase(r: str, rem: str, br: str) -> Tuple[bool, str]:
        proc = subprocess.run(
            ["git", "pull", "--rebase", rem, br],
            cwd=r, capture_output=True, text=True,
        )
        return proc.returncode == 0, (proc.stdout + proc.stderr).strip()

    def _push(r: str, rem: str, br: str) -> Tuple[bool, str]:
        proc = subprocess.run(
            ["git", "push", rem, br],
            cwd=r, capture_output=True, text=True,
        )
        return proc.returncode == 0, (proc.stdout + proc.stderr).strip()

    return GateConfig(
        repo=repo, remote=remote, branch=branch,
        count_fn=_count, rebase_fn=_rebase, push_fn=_push,
    )


if __name__ == "__main__":
    import sys
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    result = run_gate(real_gate_config(repo))
    print(f"outcome: {result.outcome.value}")
    print(f"detail:  {result.detail}")
    if result.divergence:
        d = result.divergence
        print(f"diverge: local={d.local_ahead} remote={d.remote_ahead} "
              f"severity={d.severity.value}")
