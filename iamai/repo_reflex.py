"""repo_reflex — measure the repository's reflex arc.

A healthy organism reacts quickly to stimuli.  A healthy repository
reacts quickly to *work*: content is created, committed, and pushed
in a tight loop.  When any segment of that loop stretches, the repo
develops a sluggish reflex — a sign that something in the pipeline
(writer, committer, pusher, network) is impaired.

The reflex-arc metaphor
------------------------

========================  =====================================================
concept                   what it maps to
========================  =====================================================
**stimulus**              a file is created or modified on disk
**sensory latency**       time from file mtime to ``git add`` (index staging)
**motor latency**         time from staging to ``git commit``
**effector latency**      time from commit to ``git push`` reaching remote
**total reflex time**     stimulus → remote-visible commit
**areflexia**             a segment that never completes (infinite latency)
========================  =====================================================

Scoring
-------

Each latency segment is scored 0–100 (higher = faster = better)::

    sensory   <  30 s   → 100
    sensory   < 300 s   →  80
    sensory   < 900 s   →  50
    sensory   < 3600 s  →  20
    sensory  >= 3600 s  →   0

    motor     <  60 s   → 100
    motor     < 600 s   →  70
    motor     < 1800 s  →  30
    motor    >= 1800 s  →   0

    effector  < 120 s   → 100
    effector  < 600 s   →  75
    effector  < 3600 s  →  30
    effector >= 3600 s  →   0

The composite reflex score is a weighted average::

    reflex_score = 0.3 * sensory + 0.3 * motor + 0.4 * effector

Effector (push) gets the heaviest weight because unpushed work is the
most dangerous: it can be lost if the machine dies.

Diagnosis
---------

================  ========  =============================================
classification    score     meaning
================  ========  =============================================
``sharp``         80–100    pipeline is responsive, all segments healthy
``adequate``      50–79     minor sluggishness, probably batch cadence
``sluggish``      20–49     one or more segments are significantly delayed
``areflexic``      0–19     pipeline is broken; work is not reaching remote
================  ========  =============================================

CLI
---

::

    python -m iamai.repo_reflex [--repo PATH]

Prints the current reflex arc measurements, scores, and diagnosis.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SegmentScore:
    """One segment of the reflex arc."""

    name: str
    latency_s: float
    score: float  # 0–100, higher is better
    detail: str = ""

    @property
    def is_areflexic(self) -> bool:
        return self.score <= 5.0


@dataclass
class ReflexResult:
    """Full reflex-arc measurement."""

    segments: List[SegmentScore] = field(default_factory=list)
    composite_score: float = 0.0
    classification: str = "unknown"
    recommendation: str = ""
    measured_at: float = field(default_factory=time.time)

    @property
    def total_latency_s(self) -> float:
        return sum(s.latency_s for s in self.segments)

    @property
    def weakest_segment(self) -> Optional[SegmentScore]:
        if not self.segments:
            return None
        return min(self.segments, key=lambda s: s.score)

    def to_dict(self) -> dict:
        return {
            "segments": [
                {
                    "name": s.name,
                    "latency_s": round(s.latency_s, 1),
                    "score": round(s.score, 1),
                    "detail": s.detail,
                }
                for s in self.segments
            ],
            "composite_score": round(self.composite_score, 1),
            "classification": self.classification,
            "recommendation": self.recommendation,
            "total_latency_s": round(self.total_latency_s, 1),
            "weakest_segment": (
                self.weakest_segment.name if self.weakest_segment else None
            ),
        }


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _score_sensory(latency_s: float) -> float:
    """Score the sensory (file-modification → staging) segment."""
    if latency_s < 30:
        return 100.0
    if latency_s < 300:
        return 80.0
    if latency_s < 900:
        return 50.0
    if latency_s < 3600:
        return 20.0
    return 0.0


def _score_motor(latency_s: float) -> float:
    """Score the motor (staging → commit) segment."""
    if latency_s < 60:
        return 100.0
    if latency_s < 600:
        return 70.0
    if latency_s < 1800:
        return 30.0
    return 0.0


def _score_effector(latency_s: float) -> float:
    """Score the effector (commit → push) segment."""
    if latency_s < 120:
        return 100.0
    if latency_s < 600:
        return 75.0
    if latency_s < 3600:
        return 30.0
    return 0.0


def _classify(score: float) -> str:
    if score >= 80:
        return "sharp"
    if score >= 50:
        return "adequate"
    if score >= 20:
        return "sluggish"
    return "areflexic"


def _recommend(classification: str, weakest: Optional[SegmentScore]) -> str:
    if classification == "sharp":
        return "All segments healthy. Pipeline is responsive."
    if classification == "adequate":
        if weakest and weakest.name == "effector":
            return "Push latency is elevated. Check network or credential configuration."
        return "Minor sluggishness in the pipeline. Monitor for degradation."
    if classification == "sluggish":
        if weakest and weakest.name == "sensory":
            return "Files are sitting unmodified for long periods before staging. Writer may be stalled."
        if weakest and weakest.name == "motor":
            return "Staged files are waiting too long before commit. Check batch committer cadence."
        if weakest and weakest.name == "effector":
            return "Commits are not reaching the remote. Push may be failing — check credentials and network."
        return "Multiple segments are slow. Run a full pipeline health check."
    # areflexic
    if weakest and weakest.name == "effector":
        return "AREFLEXIA: commits are not being pushed. Pipeline is effectively broken."
    return "AREFLEXIA: pipeline is non-functional. Immediate intervention required."


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _newest_uncommitted_mtime(repo: Path) -> Optional[float]:
    """Return the most recent mtime among modified tracked files."""
    result = _run_git(repo, "diff", "--name-only")
    if result.returncode != 0 or not result.stdout.strip():
        return None
    files = result.stdout.strip().splitlines()
    newest = 0.0
    for f in files:
        p = repo / f
        if p.exists():
            mt = p.stat().st_mtime
            if mt > newest:
                newest = mt
    return newest if newest > 0 else None


def _latest_commit_time(repo: Path) -> Optional[float]:
    """Return the author-date of HEAD as a Unix timestamp."""
    result = _run_git(repo, "log", "-1", "--format=%at")
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def _latest_commit_push_time(repo: Path) -> Optional[float]:
    """Estimate when the latest commit was pushed.

    Uses the reflog timestamp of ``origin/main`` as a proxy.  If the
    remote-tracking ref is absent, returns ``None`` (unmeasurable).
    """
    result = _run_git(repo, "log", "-1", "--format=%at", "origin/main")
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def _has_unpushed_commits(repo: Path) -> bool:
    """Check whether local main has commits not on origin/main."""
    result = _run_git(repo, "log", "origin/main..main", "--oneline")
    return bool(result.stdout.strip())


# ---------------------------------------------------------------------------
# Core measurement
# ---------------------------------------------------------------------------

def measure_reflex(repo: Optional[Path] = None, now: Optional[float] = None) -> ReflexResult:
    """Measure the full reflex arc of the repository.

    Parameters
    ----------
    repo : Path, optional
        Repository root.  Defaults to the current working directory.
    now : float, optional
        Override the current time (useful for testing).

    Returns
    -------
    ReflexResult
        Measurements, scores, and diagnosis.
    """
    if repo is None:
        repo = Path.cwd()
    repo = repo.resolve()
    if now is None:
        now = time.time()

    result = ReflexResult(measured_at=now)

    # --- sensory: newest file mtime → now ---
    newest_mtime = _newest_uncommitted_mtime(repo)
    if newest_mtime is not None:
        sensory_lat = max(0.0, now - newest_mtime)
    else:
        # No uncommitted changes → sensory latency is 0 (nothing to sense)
        sensory_lat = 0.0
    sensory = SegmentScore(
        name="sensory",
        latency_s=sensory_lat,
        score=_score_sensory(sensory_lat),
        detail=f"newest modified file mtime {sensory_lat:.0f}s ago" if newest_mtime else "clean tree",
    )
    result.segments.append(sensory)

    # --- motor: latest commit time → now (proxy for staging → commit gap) ---
    commit_time = _latest_commit_time(repo)
    if commit_time is not None:
        motor_lat = max(0.0, now - commit_time)
    else:
        motor_lat = 0.0
    motor = SegmentScore(
        name="motor",
        latency_s=motor_lat,
        score=_score_motor(motor_lat),
        detail=f"last commit {motor_lat:.0f}s ago" if commit_time else "no commits",
    )
    result.segments.append(motor)

    # --- effector: local HEAD vs origin/main ---
    if _has_unpushed_commits(repo):
        local_head = _latest_commit_time(repo)
        remote_head = _latest_commit_push_time(repo)
        if local_head is not None and remote_head is not None:
            effector_lat = max(0.0, local_head - remote_head)
        elif local_head is not None:
            # Can't read remote ref; use commit age as lower bound
            effector_lat = max(0.0, now - local_head)
        else:
            effector_lat = 0.0
    else:
        # No unpushed commits → push is current
        effector_lat = 0.0
    effector = SegmentScore(
        name="effector",
        latency_s=effector_lat,
        score=_score_effector(effector_lat),
        detail=f"push lag {effector_lat:.0f}s" if effector_lat > 0 else "remote is current",
    )
    result.segments.append(effector)

    # --- composite ---
    result.composite_score = (
        0.3 * sensory.score + 0.3 * motor.score + 0.4 * effector.score
    )
    result.classification = _classify(result.composite_score)
    result.recommendation = _recommend(result.classification, result.weakest_segment)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Measure repo reflex arc")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repo root")
    args = parser.parse_args(argv)

    result = measure_reflex(args.repo)
    print(json.dumps(result.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
