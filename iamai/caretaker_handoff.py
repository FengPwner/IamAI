"""Generate a structured handoff brief between caretaker visits.

``caretaker_briefing`` tells a visiting caretaker what happened *before*
they arrived.  ``caretaker_budget`` tracks how much a visit costs.
Neither produces a machine-readable snapshot of *what to pass to the
next caretaker* when this visit ends.

This module fills that gap.  It reads ``data/strokes.jsonl`` and recent
git log to produce a compact JSON-serialisable dict — the handoff — that
the departing caretaker can write to ``data/handoff.json`` for the next
arrival.

Design choices
--------------

- **Pure computation, no I/O side-effects.**  The caller decides where
  to persist the result.  ``build_handoff`` just returns a dict.
- **Sliding window.**  Only the last ``window`` strokes (default 50)
  are analysed — enough to show trend, not so many that a quiet period
  drowns the signal.
- **Kind distribution** is reported as a ``Counter`` so the next
  caretaker can spot imbalances at a glance.
- **Stall flag** mirrors ``stroke_freshness`` thresholds but is
  self-contained — no cross-module import.

Handoff fields
--------------

=================  ====================================================
field              meaning
=================  ====================================================
``generated_at``   ISO-8601 timestamp of handoff generation
``total_strokes``  total stroke count in the log
``window``         number of recent strokes analysed
``kind_dist``      ``{kind: count}`` over the window
``avg_length``     mean character length of window strokes
``max_gap_s``      longest gap (seconds) between consecutive window strokes
``stall``          ``True`` if the most recent stroke is older than
                   ``stall_threshold_s`` (default 300)
``last_stroke_at`` ISO-8601 timestamp of the most recent stroke
``commit_count``   number of commits since ``since_commit`` (or last 20)
=================  ====================================================

Usage::

    from iamai.caretaker_handoff import build_handoff

    ho = build_handoff(repo_root=".")
    print(ho["total_strokes"])   # 3014
    print(ho["stall"])           # False
    print(ho["kind_dist"])       # {"thought": 12, "devlog": 10, ...}
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_STROKES_PATH = "data/strokes.jsonl"
_DEFAULT_WINDOW = 50
_DEFAULT_STALL_THRESHOLD_S = 300  # 5 minutes


def _load_recent_strokes(
    repo_root: str | Path,
    strokes_rel: str = _DEFAULT_STROKES_PATH,
    window: int = _DEFAULT_WINDOW,
) -> list[dict[str, Any]]:
    """Read the last *window* lines from the strokes log.

    Seeks from the end for efficiency on large files.
    Returns an empty list if the file is missing or unreadable.
    """
    path = Path(repo_root) / strokes_rel
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return []
    tail = lines[-window:]
    result: list[dict[str, Any]] = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return result


def _count_total_strokes(repo_root: str | Path, strokes_rel: str = _DEFAULT_STROKES_PATH) -> int:
    """Count total lines in the strokes log (cheap: just counts newlines)."""
    path = Path(repo_root) / strokes_rel
    if not path.exists():
        return 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp string into a timezone-aware datetime."""
    # Handle the +00:00 suffix that Python < 3.11 struggles with
    ts = ts.replace("+00:00", "+0000").replace("Z", "+0000")
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    # Fallback: assume UTC
    return datetime.fromisoformat(ts.replace("+0000", "")).replace(tzinfo=timezone.utc)


def _recent_commit_count(
    repo_root: str | Path,
    since_commit: str | None = None,
    fallback_count: int = 20,
) -> int:
    """Count commits since a given commit, or the last *fallback_count* commits."""
    cwd = str(repo_root)
    try:
        if since_commit:
            result = subprocess.run(
                ["git", "rev-list", "--count", f"{since_commit}..HEAD"],
                capture_output=True, text=True, cwd=cwd, timeout=10,
            )
        else:
            result = subprocess.run(
                ["git", "rev-list", "--count", f"HEAD~{fallback_count}..HEAD"],
                capture_output=True, text=True, cwd=cwd, timeout=10,
            )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        pass
    # Fallback: count total commits
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, cwd=cwd, timeout=10,
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        pass
    return 0


def build_handoff(
    repo_root: str | Path = ".",
    window: int = _DEFAULT_WINDOW,
    stall_threshold_s: float = _DEFAULT_STALL_THRESHOLD_S,
    strokes_rel: str = _DEFAULT_STROKES_PATH,
    since_commit: str | None = None,
) -> dict[str, Any]:
    """Build a handoff dict for the next caretaker.

    Parameters
    ----------
    repo_root : str or Path
        Path to the repository root.
    window : int
        Number of recent strokes to analyse (default 50).
    stall_threshold_s : float
        Seconds since the last stroke before ``stall`` is flagged.
    strokes_rel : str
        Relative path to the strokes log within the repo.
    since_commit : str or None
        Git commit hash to count from.  If ``None``, uses the last 20 commits.

    Returns
    -------
    dict
        Handoff payload (JSON-serialisable).
    """
    now = datetime.now(timezone.utc)
    total = _count_total_strokes(repo_root, strokes_rel)
    recent = _load_recent_strokes(repo_root, strokes_rel, window)

    # Kind distribution
    kind_counter: Counter[str] = Counter()
    lengths: list[int] = []
    timestamps: list[datetime] = []
    last_at: str | None = None

    for entry in recent:
        kind = entry.get("kind", "unknown")
        kind_counter[kind] += 1
        text = entry.get("text", "")
        lengths.append(len(text))
        ts_str = entry.get("at", "")
        if ts_str:
            try:
                timestamps.append(_parse_iso(ts_str))
            except (ValueError, TypeError):
                pass
        last_at = ts_str or last_at

    # Average length
    avg_len = sum(lengths) / len(lengths) if lengths else 0.0

    # Max gap between consecutive strokes
    max_gap_s = 0.0
    if len(timestamps) >= 2:
        sorted_ts = sorted(timestamps)
        for i in range(1, len(sorted_ts)):
            gap = (sorted_ts[i] - sorted_ts[i - 1]).total_seconds()
            if gap > max_gap_s:
                max_gap_s = gap

    # Stall detection
    stall = False
    if timestamps:
        latest = max(timestamps)
        stall = (now - latest).total_seconds() > stall_threshold_s

    # Commit count
    commit_count = _recent_commit_count(repo_root, since_commit)

    return {
        "generated_at": now.isoformat(),
        "total_strokes": total,
        "window": len(recent),
        "kind_dist": dict(kind_counter),
        "avg_length": round(avg_len, 1),
        "max_gap_s": round(max_gap_s, 1),
        "stall": stall,
        "last_stroke_at": last_at,
        "commit_count": commit_count,
    }


def handoff_summary(handoff: dict[str, Any]) -> str:
    """One-line human-readable summary of a handoff dict.

    >>> ho = {"total_strokes": 3014, "window": 50, "stall": False,
    ...       "kind_dist": {"thought": 12, "devlog": 10},
    ...       "avg_length": 95.3, "max_gap_s": 120.0,
    ...       "last_stroke_at": "2026-10-16T06:16:44+00:00",
    ...       "commit_count": 5, "generated_at": "2026-10-16T07:00:00+00:00"}
    >>> handoff_summary(ho)
    '3014 strokes (50 in window), 5 commits, no stall — kinds: thought=12 devlog=10'
    """
    kinds = " ".join(f"{k}={v}" for k, v in sorted(handoff.get("kind_dist", {}).items(), key=lambda x: -x[1]))
    stall_text = "STALL" if handoff.get("stall") else "no stall"
    return (
        f"{handoff.get('total_strokes', 0)} strokes "
        f"({handoff.get('window', 0)} in window), "
        f"{handoff.get('commit_count', 0)} commits, "
        f"{stall_text}"
        f" — kinds: {kinds}"
    )
