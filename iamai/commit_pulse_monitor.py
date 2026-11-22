"""commit_pulse_monitor — is the repository's heartbeat steady?

The writer produces strokes; the batch process bundles them into commits.
``cadence_adherence`` measures stroke rhythm.  This module measures the
**commit** rhythm: are commits arriving at the expected interval (default
600 s / 10 min), or has the pulse gone erratic?

A healthy repo commits like a metronome.  A sick one has long silences
punctuated by bursts of catch-up commits.  The difference shows up in
gap statistics long before the stall detector fires.

Key metrics:

- **mean_gap_s**     — average seconds between consecutive commits
- **median_gap_s**   — robust middle value
- **jitter**         — coefficient of variation (std / mean); 0 = clockwork
- **pulse_score**    — 0–1 composite: 1.0 = perfect rhythm, 0.0 = chaos
- **missed_beats**   — count of gaps > 2× expected interval
- **burst_count**    — count of gaps < 0.3× expected (rapid-fire catch-up)

Usage::

    from iamai.commit_pulse_monitor import pulse_report, pulse_summary

    report = pulse_report(expected_interval=600, window_hours=2.0)
    print(report["mean_gap_s"])       # e.g. 620.5
    print(report["pulse_score"])      # e.g. 0.87
    print(report["missed_beats"])     # e.g. 2

    print(pulse_summary(expected_interval=600))
    # "commit pulse @600s: mean 620s, median 605s, score 0.87, 2 missed, 1 burst"

written by Qwen during caretaker visit 805, 2026-11-23
"""

from __future__ import annotations

import subprocess
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Git log parsing
# ---------------------------------------------------------------------------

def _git_commit_timestamps(repo: Path, max_count: int = 500) -> list[datetime]:
    """Return commit timestamps (newest first) from the repo's git log."""
    try:
        result = subprocess.run(
            [
                "git", "-C", str(repo), "log",
                f"--max-count={max_count}",
                "--format=%aI",
                "--no-merges",
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    timestamps: list[datetime] = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ts = line
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            timestamps.append(dt)
        except (ValueError, OverflowError):
            continue
    return timestamps


def _filter_window(timestamps: list[datetime], window_hours: float) -> list[datetime]:
    """Keep only timestamps within the given window from the newest."""
    if not timestamps:
        return []
    cutoff = timestamps[0] - __import__("datetime").timedelta(hours=window_hours)
    return [t for t in timestamps if t >= cutoff]


def _compute_gaps(timestamps: list[datetime]) -> list[float]:
    """Compute inter-commit gaps in seconds (positive values).

    timestamps should be newest-first; gaps are computed from consecutive pairs.
    """
    if len(timestamps) < 2:
        return []
    gaps: list[float] = []
    for i in range(len(timestamps) - 1):
        gap = abs((timestamps[i] - timestamps[i + 1]).total_seconds())
        gaps.append(gap)
    return gaps


# ---------------------------------------------------------------------------
# Pulse scoring
# ---------------------------------------------------------------------------

def compute_pulse_score(
    gaps: list[float],
    expected_interval: float,
) -> float:
    """Compute a 0–1 pulse score.

    1.0 = every gap is exactly the expected interval.
    0.0 = all gaps are wildly off (>3× or <0.1× expected).

    The score is the fraction of gaps that fall within [0.5×, 1.5×]
    the expected interval, weighted by how close they are to 1.0×.
    """
    if not gaps:
        return 1.0  # no gaps = no evidence of irregularity

    lo = expected_interval * 0.5
    hi = expected_interval * 1.5
    in_band = 0
    total_weight = 0.0

    for g in gaps:
        # proximity weight: 1.0 at exact expected, 0.0 at lo or hi boundary
        if lo <= g <= hi:
            deviation = abs(g - expected_interval) / (expected_interval * 0.5)
            weight = max(0.0, 1.0 - deviation)
            total_weight += weight
            in_band += 1
        # out-of-band gaps contribute 0

    if not gaps:
        return 1.0
    # blend: fraction in-band × mean weight of in-band gaps
    fraction_in_band = in_band / len(gaps)
    mean_weight = total_weight / in_band if in_band else 0.0
    return round(fraction_in_band * mean_weight, 4)


def count_missed_beats(gaps: list[float], expected_interval: float) -> int:
    """Count gaps exceeding 2× the expected interval (silence / stall)."""
    threshold = expected_interval * 2.0
    return sum(1 for g in gaps if g > threshold)


def count_bursts(gaps: list[float], expected_interval: float) -> int:
    """Count gaps below 0.3× the expected interval (rapid-fire catch-up)."""
    threshold = expected_interval * 0.3
    return sum(1 for g in gaps if g < threshold)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def pulse_report(
    expected_interval: float = 600.0,
    window_hours: float = 2.0,
    repo: Path | None = None,
) -> dict[str, Any]:
    """Generate a full pulse report for the repository.

    Args:
        expected_interval: target commit interval in seconds (default 600 = 10 min)
        window_hours: how many hours of history to analyse
        repo: path to repo root (defaults to cwd)

    Returns:
        dict with keys: mean_gap_s, median_gap_s, jitter, pulse_score,
        missed_beats, burst_count, n_commits, window_hours, healthy
    """
    repo_path = repo or Path.cwd()
    timestamps = _git_commit_timestamps(repo_path)
    timestamps = _filter_window(timestamps, window_hours)
    gaps = _compute_gaps(timestamps)

    n_commits = len(timestamps)

    if not gaps:
        return {
            "mean_gap_s": None,
            "median_gap_s": None,
            "jitter": None,
            "pulse_score": 1.0,
            "missed_beats": 0,
            "burst_count": 0,
            "n_commits": n_commits,
            "window_hours": window_hours,
            "healthy": True,
        }

    mean_gap = statistics.mean(gaps)
    median_gap = statistics.median(gaps)
    std_gap = statistics.stdev(gaps) if len(gaps) > 1 else 0.0
    jitter = (std_gap / mean_gap) if mean_gap > 0 else 0.0

    missed = count_missed_beats(gaps, expected_interval)
    bursts = count_bursts(gaps, expected_interval)
    score = compute_pulse_score(gaps, expected_interval)

    # healthy if score >= 0.5 and no more than 3 missed beats
    healthy = score >= 0.5 and missed <= 3

    return {
        "mean_gap_s": round(mean_gap, 1),
        "median_gap_s": round(median_gap, 1),
        "jitter": round(jitter, 4),
        "pulse_score": score,
        "missed_beats": missed,
        "burst_count": bursts,
        "n_commits": n_commits,
        "window_hours": window_hours,
        "healthy": healthy,
    }


def pulse_summary(
    expected_interval: float = 600.0,
    window_hours: float = 2.0,
    repo: Path | None = None,
) -> str:
    """One-line human-readable pulse summary."""
    r = pulse_report(expected_interval, window_hours, repo)

    if r["mean_gap_s"] is None:
        return f"commit pulse @{expected_interval:.0f}s: no data in {window_hours}h window ({r['n_commits']} commits)"

    status = "healthy" if r["healthy"] else "irregular"
    return (
        f"commit pulse @{expected_interval:.0f}s: "
        f"mean {r['mean_gap_s']:.0f}s, median {r['median_gap_s']:.0f}s, "
        f"score {r['pulse_score']:.2f}, "
        f"{r['missed_beats']} missed, {r['burst_count']} burst — "
        f"{status}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Check repository commit pulse")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Repo root")
    parser.add_argument("--interval", type=float, default=600, help="Expected interval (seconds)")
    parser.add_argument("--window", type=float, default=2.0, help="Window (hours)")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    report = pulse_report(args.interval, args.window, args.repo)

    if args.json:
        import json as _json
        print(_json.dumps(report, indent=2))
    else:
        print(pulse_summary(args.interval, args.window, args.repo))

    # exit code: 0 = healthy, 1 = irregular
    import sys
    sys.exit(0 if report["healthy"] else 1)
