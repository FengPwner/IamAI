"""Caretaker briefing — quick status summary when a caretaker arrives.

Generates a structured report covering:

- strokes written since last visit
- commits landed since last visit
- process liveness (writer + batch)
- uncommitted file count
- push lag (commits ahead of origin)
- stall indicator (longest stroke gap vs cadence)

Usage
-----
    from iamai.caretaker_briefing import brief, Briefing
    b = brief(repo_path, since_commit="abc1234")
    print(b.summary())

Or from the CLI wrapper (tools/caretaker_briefing.py)::

    python3 tools/caretaker_briefing.py --since abc1234
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class Briefing:
    """Structured caretaker arrival briefing."""

    strokes_since_visit: int = 0
    commits_since_visit: int = 0
    writer_alive: bool = False
    batch_alive: bool = False
    uncommitted_files: int = 0
    push_lag: int = 0
    longest_gap_seconds: float = 0.0
    cadence_seconds: float = 15.0
    stall_detected: bool = False
    warnings: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def healthy(self) -> bool:
        """True when everything looks nominal."""
        return (
            self.writer_alive
            and self.batch_alive
            and self.uncommitted_files == 0
            and not self.stall_detected
            and self.push_lag == 0
        )

    def summary(self) -> str:
        """Human-readable one-paragraph briefing."""
        parts: List[str] = []

        # liveness
        alive = []
        if self.writer_alive:
            alive.append("writer up")
        else:
            alive.append("writer DOWN")
        if self.batch_alive:
            alive.append("batch up")
        else:
            alive.append("batch DOWN")
        parts.append(", ".join(alive) + ".")

        # activity
        parts.append(
            f"{self.strokes_since_visit} strokes and "
            f"{self.commits_since_visit} commits since last visit."
        )

        # tree hygiene
        if self.uncommitted_files:
            parts.append(f"{self.uncommitted_files} uncommitted files.")
        else:
            parts.append("tree clean.")

        # push
        if self.push_lag:
            parts.append(f"{self.push_lag} commits ahead of origin.")
        else:
            parts.append("push current.")

        # stall
        if self.stall_detected:
            parts.append(
                f"STALL: longest gap {self.longest_gap_seconds:.0f}s "
                f"(>{2 * self.cadence_seconds:.0f}s threshold)."
            )

        # warnings
        for w in self.warnings:
            parts.append(f"WARNING: {w}")

        verdict = "HEALTHY" if self.healthy else "NEEDS ATTENTION"
        parts.append(f"[{verdict}]")

        return " ".join(parts)


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run a git command in *repo*, returning CompletedProcess."""
    return subprocess.run(
        ["git"] + list(args),
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _count_commits_since(repo: Path, since_commit: Optional[str]) -> int:
    """Count commits on HEAD after *since_commit* (exclusive).

    If *since_commit* is None or not found, returns total commit count.
    """
    if since_commit:
        result = _git(repo, "rev-list", "--count", f"{since_commit}..HEAD")
        if result.returncode == 0:
            return int(result.stdout.strip())
    # fallback: total count
    result = _git(repo, "rev-list", "--count", "HEAD")
    if result.returncode == 0:
        return int(result.stdout.strip())
    return 0


def _count_uncommitted(repo: Path) -> int:
    """Count files with uncommitted changes (staged or unstaged)."""
    result = _git(repo, "status", "--porcelain")
    if result.returncode != 0:
        return 0
    return len([line for line in result.stdout.splitlines() if line.strip()])


def _push_lag(repo: Path) -> int:
    """Count local commits ahead of origin/main."""
    result = _git(repo, "rev-list", "--count", "origin/main..HEAD")
    if result.returncode == 0:
        return int(result.stdout.strip())
    return 0


def _process_alive(pidfile_pattern: str, process_name: str) -> bool:
    """Check if a process is alive by scanning /proc or pgrep."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", process_name],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _longest_gap_from_state(repo: Path, writer_id: str) -> float:
    """Read writer state file and find the longest gap between strokes."""
    state_path = repo / "data" / f"writer_state.{writer_id}.json"
    if not state_path.exists():
        return 0.0
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0.0

    history = data.get("history", [])
    if len(history) < 2:
        return 0.0

    max_gap = 0.0
    for i in range(1, len(history)):
        t_prev = history[i - 1].get("timestamp", 0)
        t_curr = history[i].get("timestamp", 0)
        if t_prev and t_curr:
            gap = abs(t_curr - t_prev)
            max_gap = max(max_gap, gap)
    return max_gap


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def brief(
    repo_path: str | Path = ".",
    since_commit: Optional[str] = None,
    writer_id: str = "qwen",
    cadence: float = 15.0,
) -> Briefing:
    """Generate a caretaker arrival briefing.

    Parameters
    ----------
    repo_path : path to the git repo root (default: cwd).
    since_commit : commit hash of the last caretaker visit.
        If provided, strokes/commits are counted relative to this.
    writer_id : writer identifier (default ``"qwen"``).
    cadence : expected seconds between strokes (default 15).

    Returns
    -------
    Briefing with all fields populated.
    """
    t0 = time.monotonic()
    repo = Path(repo_path).resolve()
    stall_threshold = 2 * cadence

    b = Briefing(cadence_seconds=cadence)

    # commits since last visit
    b.commits_since_visit = _count_commits_since(repo, since_commit)

    # tree hygiene
    b.uncommitted_files = _count_uncommitted(repo)

    # push lag
    b.push_lag = _push_lag(repo)

    # process liveness
    b.writer_alive = _process_alive("", f"writer_loop.*{writer_id}")
    b.batch_alive = _process_alive("", f"commit_batch.*{writer_id}")

    # stall detection from writer state
    b.longest_gap_seconds = _longest_gap_from_state(repo, writer_id)
    b.stall_detected = b.longest_gap_seconds > stall_threshold

    # warnings
    if not b.writer_alive:
        b.warnings.append("writer process not found")
    if not b.batch_alive:
        b.warnings.append("batch committer not found")
    if b.push_lag > 3:
        b.warnings.append(f"push lag {b.push_lag} — risk of divergent history")

    b.duration_seconds = round(time.monotonic() - t0, 3)
    return b
