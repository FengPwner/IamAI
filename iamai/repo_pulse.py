"""repo_pulse.py — single-number health score for the self-writing repo.

A self-writing repository has three vital signs:

  1. **Writer pulse** — is the writer producing strokes on schedule?
  2. **Commit freshness** — how recently was the last commit made?
  3. **Push health** — did the last push succeed, and how long ago?

Each sign is scored 0.0–1.0 (1.0 = perfect) and combined into a weighted
``RepoPulse`` score.  A score below the ``SICK_THRESHOLD`` means something
is wrong and a caretaker should investigate.

Usage::

    python3 -c "from iamai.repo_pulse import pulse; print(pulse())"
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent

# Defaults — overridable via constructor or env.
WRITER_CADENCE_S = 15          # expected seconds between strokes
COMMIT_INTERVAL_S = 600        # expected seconds between commits
STALL_MULT = 2.0               # >2× cadence without a stroke → stall
SICK_THRESHOLD = 0.4           # below this, the repo is "sick"
WEIGHTS = (0.5, 0.3, 0.2)     # writer, commit, push


@dataclass
class Pulse:
    """Snapshot of repo health at one moment."""

    writer_score: float = 0.0
    commit_score: float = 0.0
    push_score: float = 0.0
    writer_gap_s: float = 0.0
    commit_gap_s: float = 0.0
    push_gap_s: float = 0.0
    push_ok: bool = True
    detail: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        """Weighted composite score in [0, 1]."""
        w_w, w_c, w_p = WEIGHTS
        return (
            w_w * self.writer_score
            + w_c * self.commit_score
            + w_p * self.push_score
        )

    @property
    def healthy(self) -> bool:
        return self.score >= SICK_THRESHOLD

    def summary(self) -> str:
        status = "healthy" if self.healthy else "SICK"
        parts = [
            f"pulse={self.score:.2f} ({status})",
            f"writer={self.writer_score:.1f} (gap {self.writer_gap_s:.0f}s)",
            f"commit={self.commit_score:.1f} (gap {self.commit_gap_s:.0f}s)",
            f"push={self.push_score:.1f} (gap {self.push_gap_s:.0f}s, ok={self.push_ok})",
        ]
        if self.detail:
            parts.append("; ".join(self.detail))
        return "  ".join(parts)


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _clamp01(value: float) -> float:
    """Clamp *value* to [0.0, 1.0]."""
    return max(0.0, min(1.0, value))


def score_writer_gap(gap_s: float, cadence_s: float = WRITER_CADENCE_S) -> float:
    """Score writer health from seconds since last stroke.

    - gap ≤ cadence → 1.0
    - gap = 2× cadence → 0.5
    - gap ≥ 4× cadence → 0.0
    """
    if gap_s <= 0:
        return 1.0
    ratio = gap_s / cadence_s
    if ratio <= 1.0:
        return 1.0
    # linear decay from 1.0 at ratio=1 to 0.0 at ratio=4
    return _clamp01(1.0 - (ratio - 1.0) / 3.0)


def score_commit_gap(gap_s: float, interval_s: float = COMMIT_INTERVAL_S) -> float:
    """Score commit freshness.

    - gap ≤ interval → 1.0
    - gap = 2× interval → 0.5
    - gap ≥ 3× interval → 0.0
    """
    if gap_s <= 0:
        return 1.0
    ratio = gap_s / interval_s
    if ratio <= 1.0:
        return 1.0
    return _clamp01(1.0 - (ratio - 1.0) / 2.0)


def score_push(gap_s: float, ok: bool, interval_s: float = COMMIT_INTERVAL_S) -> float:
    """Score push health.

    Failed push → 0.0 regardless of recency.
    Otherwise same curve as commit freshness.
    """
    if not ok:
        return 0.0
    return score_commit_gap(gap_s, interval_s)


# ---------------------------------------------------------------------------
# Data gathering
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd or REPO,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _last_commit_epoch(cwd: Optional[Path] = None) -> Optional[float]:
    """Unix timestamp of the most recent commit, or None."""
    r = _git(["log", "-1", "--format=%ct"], cwd=cwd)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def _last_push_ok(cwd: Optional[Path] = None) -> bool:
    """True if the last ``git push`` reflog entry shows success."""
    r = _git(["reflog", "show", "origin/main", "--format=%H", "-1"], cwd=cwd)
    if r.returncode != 0 or not r.stdout.strip():
        # No remote tracking ref — treat as "never pushed" → not ok
        return False
    remote_head = r.stdout.strip()
    r2 = _git(["rev-parse", "HEAD"], cwd=cwd)
    if r2.returncode != 0:
        return False
    return remote_head == r2.stdout.strip()


def _writer_last_stroke_epoch(writer_id: str = "qwen") -> Optional[float]:
    """Epoch of the most recent stroke in writer_state, or None."""
    state_file = REPO / "data" / f"writer_state.{writer_id}.json"
    if not state_file.exists():
        return None
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        history = data.get("history", [])
        if not history:
            return None
        last = history[-1]["at"]
        # ISO 8601 with timezone
        from datetime import datetime
        dt = datetime.fromisoformat(last)
        return dt.timestamp()
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def pulse(
    now: Optional[float] = None,
    writer_id: str = "qwen",
    cadence_s: float = WRITER_CADENCE_S,
    interval_s: float = COMMIT_INTERVAL_S,
    repo: Optional[Path] = None,
) -> Pulse:
    """Measure the repo's pulse right now.

    Args:
        now: Override current time (for testing).
        writer_id: Which writer to check.
        cadence_s: Expected writer cadence in seconds.
        interval_s: Expected commit interval in seconds.
        repo: Override repo root (for testing).

    Returns:
        A ``Pulse`` dataclass with scores and diagnostics.
    """
    _now = now or time.time()
    _repo = repo or REPO
    p = Pulse()

    # Writer gap
    last_stroke = _writer_last_stroke_epoch(writer_id)
    if last_stroke is not None:
        p.writer_gap_s = max(0.0, _now - last_stroke)
    else:
        p.writer_gap_s = float("inf")
        p.detail.append("no writer state found")
    p.writer_score = score_writer_gap(p.writer_gap_s, cadence_s)

    # Commit gap
    last_commit = _last_commit_epoch(_repo)
    if last_commit is not None:
        p.commit_gap_s = max(0.0, _now - last_commit)
    else:
        p.commit_gap_s = float("inf")
        p.detail.append("no commits found")
    p.commit_score = score_commit_gap(p.commit_gap_s, interval_s)

    # Push health
    p.push_ok = _last_push_ok(_repo)
    # Use commit gap as proxy for push gap (reflog timestamps are unreliable)
    p.push_gap_s = p.commit_gap_s
    p.push_score = score_push(p.push_gap_s, p.push_ok, interval_s)

    return p


if __name__ == "__main__":
    print(pulse().summary())
