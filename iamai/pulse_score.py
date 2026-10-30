"""pulse_score — composite health score for the writing pipeline.

Individual detectors tell you *what* is wrong: writer dead, backlog deep,
push lagging.  But a caretaker visiting the repo for the first time wants
one number: *how healthy is this thing right now?*

This module combines five signals into a single 0–100 score:

    ┌──────────────────┬────────┬─────────────────────────────────────┐
    │ Signal           │ Weight │ Source                              │
    ├──────────────────┼────────┼─────────────────────────────────────┤
    │ writer_alive     │   30   │ pidfile / process check             │
    │ batch_alive      │   20   │ pidfile / process check             │
    │ backlog_pressure │   25   │ git status --porcelain line count   │
    │ commit_freshness │   15   │ seconds since last commit           │
    │ push_lag         │   10   │ commits ahead of origin             │
    └──────────────────┴────────┴─────────────────────────────────────┘

Each signal is normalised to 0.0–1.0, then multiplied by its weight.
The sum is the pulse score.  A healthy pipeline scores 90+.  Anything
below 50 means something is visibly broken.

Design notes
------------
* Weights sum to 100 so the score is directly interpretable as a
  percentage of "everything is fine."
* A dead writer caps the score at 70 regardless of other signals —
  without a writer, nothing else matters for long.
* Backlog pressure uses a soft curve (1 / (1 + n/5)) so one or two
  dirty files barely register, but 20+ uncommitted files tanks the
  score.
* commit_freshness decays exponentially with a half-life of 600 s
  (10 min), matching the target commit cadence.

Usage
-----
    from iamai.pulse_score import PulseScore
    ps = PulseScore(repo_path)
    report = ps.score()
    print(report.total, report.grade)   # e.g. "82 B"
"""

from __future__ import annotations

import math
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Signal weights (must sum to 100)
# ---------------------------------------------------------------------------
W_WRITER = 30
W_BATCH = 20
W_BACKLOG = 25
W_FRESHNESS = 15
W_PUSH = 10

# Thresholds
BACKLOG_SOFT = 5          # files; half-score point
FRESHNESS_HALFLIFE = 600  # seconds
STALE_COMMIT_SECONDS = 3600  # >1 h → freshness ≈ 0


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class PulseReport:
    """Snapshot of pipeline health at one moment."""

    writer_alive: bool = False
    batch_alive: bool = False
    backlog_count: int = 0
    seconds_since_commit: float = 0.0
    push_lag_commits: int = 0

    # Normalised 0–1 scores
    writer_score: float = 0.0
    batch_score: float = 0.0
    backlog_score: float = 1.0
    freshness_score: float = 1.0
    push_score: float = 1.0

    # Weighted contributions
    writer_pts: float = 0.0
    batch_pts: float = 0.0
    backlog_pts: float = 0.0
    freshness_pts: float = 0.0
    push_pts: float = 0.0

    total: float = 0.0

    @property
    def grade(self) -> str:
        """Letter grade: A (90+), B (70+), C (50+), D (30+), F (<30)."""
        if self.total >= 90:
            return "A"
        if self.total >= 70:
            return "B"
        if self.total >= 50:
            return "C"
        if self.total >= 30:
            return "D"
        return "F"

    @property
    def summary(self) -> str:
        one_line = (
            f"pulse {self.total:.0f}/{100} ({self.grade}) | "
            f"writer={'✓' if self.writer_alive else '✗'} "
            f"batch={'✓' if self.batch_alive else '✗'} "
            f"backlog={self.backlog_count} "
            f"fresh={self.seconds_since_commit:.0f}s "
            f"push_lag={self.push_lag_commits}"
        )
        return one_line


# ---------------------------------------------------------------------------
# Main scorer
# ---------------------------------------------------------------------------
class PulseScore:
    """Compute the composite health score for a writing-pipeline repo."""

    def __init__(self, repo_path: str | Path | None = None):
        self.repo = Path(repo_path) if repo_path else Path(__file__).resolve().parent.parent

    # -- individual signal probes -------------------------------------------

    def _check_process(self, name: str) -> bool:
        """Return True if a process whose cmdline contains *name* is alive."""
        try:
            out = subprocess.run(
                ["pgrep", "-f", name],
                capture_output=True, text=True, timeout=5,
            )
            return out.returncode == 0 and out.stdout.strip() != ""
        except Exception:
            return False

    def writer_alive(self) -> bool:
        return self._check_process("writer_loop")

    def batch_alive(self) -> bool:
        return self._check_process("commit_batch")

    def backlog_count(self) -> int:
        """Number of modified/untracked files (git status --porcelain)."""
        try:
            out = subprocess.run(
                ["git", "-C", str(self.repo), "status", "--porcelain"],
                capture_output=True, text=True, timeout=10,
            )
            lines = [l for l in out.stdout.splitlines() if l.strip()]
            return len(lines)
        except Exception:
            return -1  # unknown → treat as bad

    def seconds_since_commit(self) -> float:
        """Seconds elapsed since the most recent commit."""
        try:
            out = subprocess.run(
                ["git", "-C", str(self.repo), "log", "-1", "--format=%at"],
                capture_output=True, text=True, timeout=10,
            )
            ts = int(out.stdout.strip())
            return max(0.0, time.time() - ts)
        except Exception:
            return STALE_COMMIT_SECONDS  # assume stale

    def push_lag(self) -> int:
        """Number of local commits not yet on origin."""
        try:
            out = subprocess.run(
                ["git", "-C", str(self.repo), "rev-list",
                 "--count", "origin/main..HEAD"],
                capture_output=True, text=True, timeout=10,
            )
            return int(out.stdout.strip())
        except Exception:
            return -1  # unknown

    # -- normalisers --------------------------------------------------------

    @staticmethod
    def _norm_alive(alive: bool) -> float:
        return 1.0 if alive else 0.0

    @staticmethod
    def _norm_backlog(n: int) -> float:
        """Soft curve: 1/(1 + n/BACKLOG_SOFT).  0 files → 1.0, 5 → 0.5."""
        if n < 0:
            return 0.2  # unknown
        return 1.0 / (1.0 + n / BACKLOG_SOFT)

    @staticmethod
    def _norm_freshness(seconds: float) -> float:
        """Exponential decay with half-life = FRESHNESS_HALFLIFE."""
        if seconds <= 0:
            return 1.0
        return math.exp(-0.693 * seconds / FRESHNESS_HALFLIFE)

    @staticmethod
    def _norm_push(lag: int) -> float:
        """1.0 for 0 lag, decays as lag grows."""
        if lag < 0:
            return 0.5  # unknown
        if lag == 0:
            return 1.0
        return 1.0 / (1.0 + lag * 0.3)

    # -- composite ----------------------------------------------------------

    def score(self) -> PulseReport:
        """Probe all signals and return a PulseReport."""
        w_alive = self.writer_alive()
        b_alive = self.batch_alive()
        backlog = self.backlog_count()
        freshness = self.seconds_since_commit()
        push = self.push_lag()

        w_s = self._norm_alive(w_alive)
        b_s = self._norm_alive(b_alive)
        bl_s = self._norm_backlog(backlog)
        fr_s = self._norm_freshness(freshness)
        pu_s = self._norm_push(push)

        w_pts = w_s * W_WRITER
        b_pts = b_s * W_BATCH
        bl_pts = bl_s * W_BACKLOG
        fr_pts = fr_s * W_FRESHNESS
        pu_pts = pu_s * W_PUSH

        total = w_pts + b_pts + bl_pts + fr_pts + pu_pts

        # Dead-writer cap: without a writer the pipeline is terminal
        if not w_alive:
            total = min(total, 70.0)

        return PulseReport(
            writer_alive=w_alive,
            batch_alive=b_alive,
            backlog_count=backlog,
            seconds_since_commit=freshness,
            push_lag_commits=push,
            writer_score=w_s,
            batch_score=b_s,
            backlog_score=bl_s,
            freshness_score=fr_s,
            push_score=pu_s,
            writer_pts=w_pts,
            batch_pts=b_pts,
            backlog_pts=bl_pts,
            freshness_pts=fr_pts,
            push_pts=pu_pts,
            total=total,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    import argparse
    p = argparse.ArgumentParser(description="Pipeline pulse score")
    p.add_argument("--repo", default=None, help="repo path (default: auto)")
    p.add_argument("--json", action="store_true", help="output as JSON")
    args = p.parse_args()

    ps = PulseScore(args.repo)
    report = ps.score()

    if args.json:
        import json
        print(json.dumps({
            "total": round(report.total, 1),
            "grade": report.grade,
            "writer_alive": report.writer_alive,
            "batch_alive": report.batch_alive,
            "backlog": report.backlog_count,
            "seconds_since_commit": round(report.seconds_since_commit, 1),
            "push_lag": report.push_lag_commits,
        }))
    else:
        print(report.summary)


if __name__ == "__main__":
    main()
