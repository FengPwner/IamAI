"""Stall root-cause classifier — why did the writer stop writing?

When a writer stalls (silence past 2x its cadence), the next question
is *why*.  This module inspects a handful of cheap signals and returns
a structured verdict:

===============  =====================================================
cause            meaning
===============  =====================================================
``process_dead``   writer process is not running (PID gone or never started)
``pause_gate``     writer is paused via the pause-file gate
``network``        recent push failures visible in the log tail
``merge_conflict`` unmerged paths or conflict markers in the tree
``disk_full``      no space left on the partition holding the repo
``unknown``        none of the above; human investigation needed
===============  =====================================================

Usage::

    from iamai.stall_root_cause import classify_stall, StallVerdict

    verdict = classify_stall(repo_path="/path/to/IamAI")
    print(verdict.cause)       # "process_dead"
    print(verdict.confidence)  # 0.95
    print(verdict.evidence)    # ["pid file missing", "no qwen process in ps"]

Each signal probe is independent; the classifier picks the cause with
the highest confidence, or ``unknown`` when nothing crosses the threshold.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

CAUSES = (
    "process_dead",
    "pause_gate",
    "network",
    "merge_conflict",
    "disk_full",
    "unknown",
)


@dataclass(frozen=True)
class StallVerdict:
    """Immutable verdict produced by :func:`classify_stall`."""

    cause: str
    confidence: float
    evidence: List[str] = field(default_factory=list)
    writer_id: Optional[str] = None

    def is_clear(self) -> bool:
        """True when no stall was detected at all (cause == 'none')."""
        return self.cause == "none"

    def to_dict(self) -> dict:
        return {
            "cause": self.cause,
            "confidence": round(self.confidence, 4),
            "evidence": list(self.evidence),
            "writer_id": self.writer_id,
        }


# ---------------------------------------------------------------------------
# Signal probes — each returns (confidence, evidence_lines)
# ---------------------------------------------------------------------------


def _probe_process_alive(writer_id: str) -> tuple[float, List[str]]:
    """Check whether the writer process is alive via pid file and ps."""
    pid_file = Path(f"/tmp/iamai-writer-{writer_id}.pid")
    evidence: List[str] = []

    if not pid_file.exists():
        evidence.append(f"pid file {pid_file} missing")
        return (0.95, evidence)

    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError) as exc:
        evidence.append(f"pid file unreadable: {exc}")
        return (0.90, evidence)

    # Check /proc/<pid>
    if not Path(f"/proc/{pid}").exists():
        evidence.append(f"pid {pid} not in /proc — process dead")
        return (0.95, evidence)

    # Read cmdline to confirm it's the writer
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
        if "writer_loop" not in cmdline:
            evidence.append(f"pid {pid} exists but cmdline is not writer_loop")
            return (0.80, evidence)
    except OSError:
        pass

    evidence.append(f"writer pid {pid} alive")
    return (0.0, evidence)


def _probe_pause_gate(writer_id: str) -> tuple[float, List[str]]:
    """Check whether the pause file exists."""
    pause_file = Path(f"/tmp/iamai-writer-pause-{writer_id}")
    evidence: List[str] = []

    if pause_file.exists():
        evidence.append(f"pause gate active: {pause_file}")
        return (0.98, evidence)

    evidence.append("no pause gate")
    return (0.0, evidence)


def _probe_network(repo_path: Path, log_tail_lines: int = 50) -> tuple[float, List[str]]:
    """Scan recent log and git state for push failures."""
    evidence: List[str] = []

    # Check for unpushed commits piling up
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "log", "--oneline", "@{u}..HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            unpushed = [l for l in result.stdout.strip().splitlines() if l]
            if len(unpushed) >= 3:
                evidence.append(f"{len(unpushed)} unpushed commits piling up")
                return (0.70 + min(len(unpushed) * 0.03, 0.25), evidence)
    except (subprocess.TimeoutExpired, OSError):
        pass

    # Check log tail for push errors
    log_path = Path("/tmp/iamai-qwen.log")
    if log_path.exists():
        try:
            tail = log_path.read_text(errors="replace").splitlines()[-log_tail_lines:]
            push_errors = [
                l for l in tail
                if any(kw in l.lower() for kw in ("push failed", "connection refused", "fatal", "could not resolve"))
            ]
            if push_errors:
                evidence.append(f"{len(push_errors)} push error(s) in log tail")
                evidence.append(f"  latest: {push_errors[-1][:120]}")
                return (0.85, evidence)
        except OSError:
            pass

    evidence.append("no network errors detected")
    return (0.0, evidence)


def _probe_merge_conflict(repo_path: Path) -> tuple[float, List[str]]:
    """Check for unmerged paths in the working tree."""
    evidence: List[str] = []

    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "diff", "--name-only", "--diff-filter=U"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            unmerged = result.stdout.strip().splitlines()
            evidence.append(f"{len(unmerged)} unmerged path(s)")
            for p in unmerged[:5]:
                evidence.append(f"  {p}")
            return (0.95, evidence)
    except (subprocess.TimeoutExpired, OSError):
        pass

    evidence.append("no merge conflicts")
    return (0.0, evidence)


def _probe_disk_full(repo_path: Path) -> tuple[float, List[str]]:
    """Check whether the partition holding the repo is nearly full."""
    evidence: List[str] = []

    try:
        usage = shutil.disk_usage(str(repo_path))
        pct = usage.used / usage.total
        if pct > 0.98:
            evidence.append(f"disk {pct:.1%} full ({usage.free // (1024*1024)} MB free)")
            return (0.90, evidence)
        elif pct > 0.95:
            evidence.append(f"disk {pct:.1%} full — approaching capacity")
            return (0.40, evidence)
    except OSError as exc:
        evidence.append(f"disk check failed: {exc}")

    evidence.append("disk space ok")
    return (0.0, evidence)


# ---------------------------------------------------------------------------
# Public classifier
# ---------------------------------------------------------------------------

_PROBES = [
    ("process_dead", _probe_process_alive),
    ("pause_gate", _probe_pause_gate),
    ("network", lambda repo_path, **kw: _probe_network(repo_path, **kw)),
    ("merge_conflict", _probe_merge_conflict),
    ("disk_full", _probe_disk_full),
]


def classify_stall(
    repo_path: str | Path = ".",
    writer_id: str = "qwen",
    stall_threshold: float = 0.50,
) -> StallVerdict:
    """Run all probes and return the highest-confidence verdict.

    Parameters
    ----------
    repo_path : str or Path
        Path to the IamAI repository root.
    writer_id : str
        Writer identifier (default ``"qwen"``).
    stall_threshold : float
        Minimum confidence to declare a cause (default 0.50).
        Below this, the verdict is ``"unknown"``.

    Returns
    -------
    StallVerdict
    """
    repo = Path(repo_path).resolve()
    best_cause = "unknown"
    best_confidence = 0.0
    best_evidence: List[str] = []

    for cause_name, probe in _PROBES:
        if cause_name in ("process_dead", "pause_gate"):
            conf, ev = probe(writer_id)
        else:
            conf, ev = probe(repo)

        if conf > best_confidence:
            best_confidence = conf
            best_cause = cause_name
            best_evidence = ev

    if best_confidence < stall_threshold:
        return StallVerdict(
            cause="unknown",
            confidence=1.0 - best_confidence,
            evidence=[f"no probe exceeded threshold (best: {best_cause} @ {best_confidence:.2f})"],
            writer_id=writer_id,
        )

    return StallVerdict(
        cause=best_cause,
        confidence=best_confidence,
        evidence=best_evidence,
        writer_id=writer_id,
    )


def quick_diagnose(writer_id: str = "qwen") -> str:
    """One-liner for shell scripts and log lines."""
    v = classify_stall(writer_id=writer_id)
    return f"stall:{v.cause} conf={v.confidence:.2f} | {'; '.join(v.evidence[:3])}"
