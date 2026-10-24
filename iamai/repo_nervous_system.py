"""repo_nervous_system — measure signal propagation and reflex integrity.

A living repository has a nervous system: monitoring tools that detect
problems (stalls, lock corruption, push races) and trigger responses
(restarts, lock cleaning, catch-up commits).  Like a biological reflex
arc, the value lies not in the detection alone but in the *latency*
between stimulus and response.

The nervous-system metaphor
----------------------------

=========================  ===================================================
concept                    what it maps to
=========================  ===================================================
**sensory nerve**          a detection tool (stall_classifier, stale_lock,
                           deadman_switch, push_race_counter)
**motor nerve**            a response tool (run_both.sh restart, auto_lock,
                           catch-up commit, push_gate)
**reflex arc**             paired detection → response within one batch cycle
**nerve damage**           a detection tool that fires but has no paired
                           response, or a response with no detector
**propagation latency**    time from problem occurrence to detection
**reflex latency**         time from detection to response completion
=========================  ===================================================

Metrics
-------

============================  ================================================
metric                        description
============================  ================================================
``detector_count``            number of distinct detection tools found
``responder_count``           number of distinct response tools found
``paired_reflexes``           detectors with a known paired responder
``orphan_detectors``          detectors without a paired responder
``orphan_responders``         responders without a paired detector
``mean_reflex_latency_s``     average seconds from detection to response
``reflex_integrity``          0-100 score; higher = better coverage
``nerve_health``              one of: sharp, responsive, dulled, neuropathic
============================  ================================================

Reflex pairs
-------------

The module maintains a curated mapping of known detection → response
pairs.  Each pair specifies:

- **detector**: tool name that identifies the problem
- **responder**: tool name that resolves it
- **expected_latency_s**: maximum healthy reflex time in seconds
- **severity**: how damaging an unpaired detection is (low/medium/high)

Unpaired detectors signal *nerve damage* — the repo can feel pain but
cannot move away from it.

Edge cases
----------

- Empty commit log: returns zeroed metrics with ``nerve_health='dormant'``.
- Tools referenced but missing from ``tools/``: counted as *lesions*.
- Duplicate detections in one batch window: deduplicated to one reflex.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Reflex-pair registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReflexPair:
    """A known detection → response coupling."""

    detector: str
    responder: str
    expected_latency_s: float = 600.0
    severity: str = "medium"  # low, medium, high


# Curated reflex pairs.  Each entry maps a detection pattern to its
# expected responder.  The patterns match against tool filenames
# (without .py) or commit-message keywords.

REFLEX_PAIRS: Tuple[ReflexPair, ...] = (
    # Stall detection → process restart
    ReflexPair(
        detector="stall_classifier",
        responder="run_both",
        expected_latency_s=900.0,
        severity="high",
    ),
    ReflexPair(
        detector="stall_cluster_detector",
        responder="run_both",
        expected_latency_s=900.0,
        severity="high",
    ),
    ReflexPair(
        detector="stall_probe",
        responder="run_both",
        expected_latency_s=600.0,
        severity="high",
    ),
    # Deadman → restart
    ReflexPair(
        detector="deadman_switch",
        responder="run_both",
        expected_latency_s=600.0,
        severity="high",
    ),
    # Stale lock → auto clean
    ReflexPair(
        detector="stale_lock_detector",
        responder="auto_lock_clean",
        expected_latency_s=300.0,
        severity="medium",
    ),
    ReflexPair(
        detector="stale_pid_detector",
        responder="auto_lock_clean",
        expected_latency_s=300.0,
        severity="medium",
    ),
    # Push race → push recovery
    ReflexPair(
        detector="push_race_counter",
        responder="push_gate",
        expected_latency_s=300.0,
        severity="high",
    ),
    ReflexPair(
        detector="push_lag",
        responder="push_gate",
        expected_latency_s=600.0,
        severity="medium",
    ),
    # Writer silence → writer restart
    ReflexPair(
        detector="writer_silence_detector",
        responder="run_both",
        expected_latency_s=900.0,
        severity="high",
    ),
    ReflexPair(
        detector="writer_recovery_monitor",
        responder="run_both",
        expected_latency_s=600.0,
        severity="medium",
    ),
    # Stale strokes → stroke cleanup
    ReflexPair(
        detector="stale_stroke_detector",
        responder="stroke_loss_tracker",
        expected_latency_s=600.0,
        severity="low",
    ),
    # Backlog pressure → commit flush
    ReflexPair(
        detector="backlog_monitor",
        responder="commit_batch",
        expected_latency_s=600.0,
        severity="medium",
    ),
    ReflexPair(
        detector="backlog_half_life",
        responder="commit_batch",
        expected_latency_s=600.0,
        severity="low",
    ),
    # Uncommitted bytes → pre-push sync
    ReflexPair(
        detector="uncommitted_bytes",
        responder="pre_push_sync",
        expected_latency_s=300.0,
        severity="medium",
    ),
    # Restart quality → restart audit feedback
    ReflexPair(
        detector="restart_quality_scorer",
        responder="restart_audit",
        expected_latency_s=900.0,
        severity="low",
    ),
    # Resurrection tracking → process lifecycle
    ReflexPair(
        detector="resurrection_tracker",
        responder="process_reclaim_detector",
        expected_latency_s=600.0,
        severity="low",
    ),
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class NerveReport:
    """Complete nervous-system health report."""

    detector_count: int = 0
    responder_count: int = 0
    paired_reflexes: int = 0
    orphan_detectors: List[str] = field(default_factory=list)
    orphan_responders: List[str] = field(default_factory=list)
    lesions: List[str] = field(default_factory=list)
    mean_reflex_latency_s: float = 0.0
    reflex_integrity: float = 0.0
    nerve_health: str = "dormant"
    window_seconds: float = 0.0
    commit_count: int = 0


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git_log(repo_path: str, last: int = 50) -> List[Tuple[str, str]]:
    """Return list of (commit_hash, message) for the last N commits."""
    try:
        result = subprocess.run(
            [
                "git", "log", f"--max-count={last}",
                "--format=%H %s",
            ],
            capture_output=True, text=True, timeout=30,
            cwd=repo_path,
        )
        entries = []
        for line in result.stdout.strip().splitlines():
            parts = line.split(" ", 1)
            if len(parts) == 2:
                entries.append((parts[0], parts[1]))
        return entries
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def _tools_present(repo_path: str) -> List[str]:
    """Return basenames (no extension) of all tools in tools/."""
    tools_dir = Path(repo_path) / "tools"
    if not tools_dir.is_dir():
        return []
    names = set()
    for pattern in ("*.py", "*.sh"):
        for p in tools_dir.glob(pattern):
            if p.name != "__init__.py":
                names.add(p.stem)
    return sorted(names)


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def _find_paired(
    tool_names: List[str],
    pairs: Tuple[ReflexPair, ...],
) -> Tuple[List[ReflexPair], List[str], List[str]]:
    """Identify which reflex pairs have both sides present.

    Returns (matched_pairs, orphan_detectors, orphan_responders).
    """
    tool_set = set(tool_names)

    matched: List[ReflexPair] = []
    orphan_d: List[str] = []
    orphan_r: List[str] = []

    for pair in pairs:
        d_present = pair.detector in tool_set
        r_present = pair.responder in tool_set
        if d_present and r_present:
            matched.append(pair)
        elif d_present and not r_present:
            orphan_d.append(pair.detector)
        elif not d_present and r_present:
            orphan_r.append(pair.responder)

    return matched, orphan_d, orphan_r


def _extract_reflex_events(
    log_entries: List[Tuple[str, str]],
) -> List[float]:
    """Extract observed reflex latencies from commit messages.

    Scans for paired patterns like:
      "stall detected" followed within N commits by "restart"
    Returns list of estimated latencies in seconds.

    Uses commit spacing as a proxy for wall-clock time:
    each commit gap is treated as one "nerve impulse interval".
    """
    # Patterns that indicate detection
    detect_re = re.compile(
        r"(stall|deadman|silence|stale.lock|push.race|backlog|uncommitted)",
        re.IGNORECASE,
    )
    # Patterns that indicate response
    respond_re = re.compile(
        r"(restart|recovery|lock.clean|catch.up|flush|push.gate|sync)",
        re.IGNORECASE,
    )

    latencies: List[float] = []
    pending_detection_idx: Optional[int] = None

    for idx, (_, msg) in enumerate(log_entries):
        if detect_re.search(msg) and pending_detection_idx is None:
            pending_detection_idx = idx
        elif respond_re.search(msg) and pending_detection_idx is not None:
            gap_commits = idx - pending_detection_idx
            # Estimate: each commit gap ≈ batch interval / commit_density.
            # Conservative estimate: 600s per gap (the batch interval).
            estimated_latency = gap_commits * 600.0
            latencies.append(estimated_latency)
            pending_detection_idx = None

    return latencies


def _classify_health(integrity: float, orphan_count: int) -> str:
    """Classify nerve health from integrity score and orphan count."""
    if integrity >= 80 and orphan_count == 0:
        return "sharp"
    elif integrity >= 60 and orphan_count <= 2:
        return "responsive"
    elif integrity >= 40:
        return "dulled"
    else:
        return "neuropathic"


def nerve_report(
    repo_path: str = ".",
    last: int = 50,
) -> NerveReport:
    """Produce a complete nervous-system health report."""
    tool_names = _tools_present(repo_path)
    log_entries = _git_log(repo_path, last=last)

    if not log_entries:
        return NerveReport(nerve_health="dormant")

    matched, orphan_d, orphan_r = _find_paired(tool_names, REFLEX_PAIRS)

    # Count distinct detectors and responders present
    all_detectors = {p.detector for p in REFLEX_PAIRS}
    all_responders = {p.responder for p in REFLEX_PAIRS}
    tool_set = set(tool_names)
    det_count = len(all_detectors & tool_set)
    resp_count = len(all_responders & tool_set)

    # Lesions: detectors referenced in pairs but missing entirely
    lesions = sorted(all_detectors - tool_set)

    # Reflex latencies from commit history
    latencies = _extract_reflex_events(log_entries)
    mean_latency = sum(latencies) / len(latencies) if latencies else 0.0

    # Integrity: fraction of pairs that are fully coupled
    total_pairs = len(REFLEX_PAIRS)
    integrity = (len(matched) / total_pairs * 100.0) if total_pairs else 0.0

    orphan_count = len(orphan_d) + len(orphan_r)
    health = _classify_health(integrity, orphan_count)

    # Time window from commit log
    # (Not available from --format=%H %s alone; left as commit count.)

    return NerveReport(
        detector_count=det_count,
        responder_count=resp_count,
        paired_reflexes=len(matched),
        orphan_detectors=orphan_d,
        orphan_responders=orphan_r,
        lesions=lesions,
        mean_reflex_latency_s=mean_latency,
        reflex_integrity=round(integrity, 1),
        nerve_health=health,
        commit_count=len(log_entries),
    )


def nerve_summary(report: NerveReport) -> str:
    """One-line human-readable summary."""
    if report.nerve_health == "dormant":
        return "nervous system dormant: no commit history to analyse"

    parts = [
        f"nerve health: {report.nerve_health}",
        f"integrity {report.reflex_integrity:.0f}%",
        f"{report.paired_reflexes}/{report.paired_reflexes + len(report.orphan_detectors) + len(report.lesions)} reflex arcs intact",
    ]

    if report.mean_reflex_latency_s > 0:
        parts.append(f"mean reflex {report.mean_reflex_latency_s:.0f}s")

    if report.orphan_detectors:
        parts.append(f"orphan detectors: {', '.join(report.orphan_detectors)}")

    return " | ".join(parts)
