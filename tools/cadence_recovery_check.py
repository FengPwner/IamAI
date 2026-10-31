#!/usr/bin/env python3
"""cadence_recovery_check.py — verify stroke cadence recovered after restart.

After a process restart, the writer should resume producing strokes at its
configured cadence (e.g., every 15 seconds). This tool checks whether the
post-restart cadence has recovered to within acceptable bounds, or whether
the writer is still struggling (long gaps, irregular timing).

Reads data/strokes.jsonl and compares:
  - Pre-restart cadence (last N strokes before the gap)
  - Post-restart cadence (first M strokes after the gap)
  - Current cadence (last K strokes up to now)

Reports:
  - pre_cadence_s: average seconds between strokes before restart
  - post_cadence_s: average seconds between strokes after restart
  - current_cadence_s: average seconds between recent strokes
  - recovery_ratio: post_cadence / pre_cadence (1.0 = perfect, <0.5 = degraded)
  - status: "recovered" | "degraded" | "stalled"

Usage:
    python3 tools/cadence_recovery_check.py
    python3 tools/cadence_recovery_check.py --writer qwen --threshold 0.5
    python3 tools/cadence_recovery_check.py --json
    python3 tools/cadence_recovery_check.py --strokes-file /path/to/strokes.jsonl

Exit codes:
    0 — cadence recovered (ratio >= threshold)
    1 — cadence degraded (ratio < threshold)
    2 — cadence stalled (no recent strokes)
    3 — parse error or missing data
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parent.parent
DEFAULT_STROKES = REPO / "data" / "strokes.jsonl"

# Thresholds
RECOVERED_RATIO = 0.7    # post/pre >= 0.7 → recovered
DEGRADED_RATIO = 0.3     # post/pre >= 0.3 → degraded, else stalled
MAX_GAP_SECONDS = 300    # gaps > 5 min considered restart points
MIN_STROKES_FOR_CADENCE = 5  # need at least 5 strokes to compute cadence


@dataclass
class CadenceReport:
    status: str              # "recovered" | "degraded" | "stalled" | "no_data"
    pre_cadence_s: float     # avg seconds between strokes before restart
    post_cadence_s: float    # avg seconds between strokes after restart
    current_cadence_s: float # avg seconds between recent strokes
    recovery_ratio: float    # post / pre (1.0 = perfect)
    gap_seconds: float       # detected restart gap
    strokes_analyzed: int
    last_stroke_age_s: float # seconds since last stroke
    message: str


def parse_timestamp(ts_str: str) -> datetime:
    """Parse ISO timestamp string to datetime."""
    # Handle various ISO formats
    ts_str = ts_str.strip()
    if ts_str.endswith('Z'):
        ts_str = ts_str[:-1] + '+00:00'
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        # Fallback for simpler formats
        for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f'):
            try:
                return datetime.strptime(ts_str, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        raise


def compute_cadence(strokes: List[dict], start_idx: int, end_idx: int) -> float:
    """Compute average seconds between strokes in range [start_idx, end_idx)."""
    if end_idx - start_idx < 2:
        return 0.0
    
    timestamps = []
    for i in range(start_idx, end_idx):
        try:
            timestamps.append(parse_timestamp(strokes[i]['at']))
        except (KeyError, ValueError):
            continue
    
    if len(timestamps) < 2:
        return 0.0
    
    timestamps.sort()
    intervals = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i-1]).total_seconds()
        intervals.append(delta)
    
    if not intervals:
        return 0.0
    
    # Filter out extreme outliers (> 1 hour)
    intervals = [x for x in intervals if x < 3600]
    
    if not intervals:
        return 0.0
    
    return sum(intervals) / len(intervals)


def find_restart_gap(strokes: List[dict], max_gap: float = MAX_GAP_SECONDS) -> Optional[int]:
    """Find the index of the largest gap (likely a restart point).
    
    Returns the index of the first stroke after the gap.
    """
    if len(strokes) < 2:
        return None
    
    max_gap_seconds = 0.0
    max_gap_idx = None
    
    for i in range(1, len(strokes)):
        try:
            t1 = parse_timestamp(strokes[i-1]['at'])
            t2 = parse_timestamp(strokes[i]['at'])
            gap = (t2 - t1).total_seconds()
            if gap > max_gap_seconds:
                max_gap_seconds = gap
                max_gap_idx = i
        except (KeyError, ValueError):
            continue
    
    if max_gap_seconds >= max_gap and max_gap_idx is not None:
        return max_gap_idx
    
    return None


def check_cadence_recovery(
    strokes_file: Path,
    threshold: float = RECOVERED_RATIO,
    window: int = 20,
) -> CadenceReport:
    """Check whether stroke cadence recovered after the last restart."""
    
    if not strokes_file.exists():
        return CadenceReport(
            status="no_data",
            pre_cadence_s=0.0,
            post_cadence_s=0.0,
            current_cadence_s=0.0,
            recovery_ratio=0.0,
            gap_seconds=0.0,
            strokes_analyzed=0,
            last_stroke_age_s=0.0,
            message=f"Strokes file not found: {strokes_file}"
        )
    
    # Read strokes
    strokes = []
    with open(strokes_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    strokes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    
    if len(strokes) < MIN_STROKES_FOR_CADENCE * 2:
        return CadenceReport(
            status="no_data",
            pre_cadence_s=0.0,
            post_cadence_s=0.0,
            current_cadence_s=0.0,
            recovery_ratio=0.0,
            gap_seconds=0.0,
            strokes_analyzed=len(strokes),
            last_stroke_age_s=0.0,
            message=f"Insufficient strokes: {len(strokes)} (need {MIN_STROKES_FOR_CADENCE * 2})"
        )
    
    # Find restart gap
    gap_idx = find_restart_gap(strokes)
    
    if gap_idx is None:
        # No significant gap found — use recent strokes as baseline
        pre_cadence = compute_cadence(strokes, max(0, len(strokes) - window * 2), 
                                      max(0, len(strokes) - window))
        current_cadence = compute_cadence(strokes, max(0, len(strokes) - window), len(strokes))
        
        ratio = current_cadence / pre_cadence if pre_cadence > 0 else 1.0
        
        return CadenceReport(
            status="recovered" if ratio >= threshold else "degraded",
            pre_cadence_s=pre_cadence,
            post_cadence_s=current_cadence,
            current_cadence_s=current_cadence,
            recovery_ratio=ratio,
            gap_seconds=0.0,
            strokes_analyzed=len(strokes),
            last_stroke_age_s=_last_stroke_age(strokes),
            message="No restart gap detected; comparing recent cadence segments"
        )
    
    # Compute pre-restart cadence
    pre_start = max(0, gap_idx - window)
    pre_cadence = compute_cadence(strokes, pre_start, gap_idx)
    
    # Compute post-restart cadence
    post_end = min(len(strokes), gap_idx + window)
    post_cadence = compute_cadence(strokes, gap_idx, post_end)
    
    # Compute current cadence (most recent strokes)
    current_start = max(0, len(strokes) - window)
    current_cadence = compute_cadence(strokes, current_start, len(strokes))
    
    # Compute gap size
    try:
        t_pre = parse_timestamp(strokes[gap_idx - 1]['at'])
        t_post = parse_timestamp(strokes[gap_idx]['at'])
        gap_seconds = (t_post - t_pre).total_seconds()
    except (KeyError, ValueError, IndexError):
        gap_seconds = 0.0
    
    # Determine status
    if pre_cadence == 0:
        status = "no_data"
        ratio = 0.0
        message = "Cannot compute pre-restart cadence"
    elif post_cadence == 0:
        # Not enough post-restart strokes to compute cadence
        status = "stalled"
        ratio = 0.0
        post_count = min(post_end, len(strokes)) - gap_idx
        message = f"Insufficient post-restart strokes ({post_count} < {MIN_STROKES_FOR_CADENCE})"
    else:
        # Use post-cadence as the primary measure; current-cadence as backup
        # only if post-window had enough strokes but produced no measurable cadence
        effective_cadence = post_cadence
        ratio = pre_cadence / effective_cadence if effective_cadence > 0 else 0.0
        
        if ratio >= threshold:
            status = "recovered"
            message = f"Cadence recovered: {effective_cadence:.1f}s (was {pre_cadence:.1f}s)"
        elif ratio >= DEGRADED_RATIO:
            status = "degraded"
            message = f"Cadence degraded: {effective_cadence:.1f}s (was {pre_cadence:.1f}s)"
        else:
            status = "stalled"
            message = f"Cadence stalled: {effective_cadence:.1f}s (was {pre_cadence:.1f}s)"
    
    return CadenceReport(
        status=status,
        pre_cadence_s=pre_cadence,
        post_cadence_s=post_cadence,
        current_cadence_s=current_cadence,
        recovery_ratio=ratio,
        gap_seconds=gap_seconds,
        strokes_analyzed=len(strokes),
        last_stroke_age_s=_last_stroke_age(strokes),
        message=message
    )


def _last_stroke_age(strokes: List[dict]) -> float:
    """Seconds since the last stroke."""
    if not strokes:
        return 0.0
    try:
        last_at = parse_timestamp(strokes[-1]['at'])
        return (datetime.now(timezone.utc) - last_at).total_seconds()
    except (KeyError, ValueError):
        return 0.0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--strokes-file', type=Path, default=DEFAULT_STROKES,
                       help='Path to strokes.jsonl')
    parser.add_argument('--threshold', type=float, default=RECOVERED_RATIO,
                       help=f'Recovery ratio threshold (default: {RECOVERED_RATIO})')
    parser.add_argument('--window', type=int, default=20,
                       help='Number of strokes to analyze in each segment')
    parser.add_argument('--json', action='store_true',
                       help='Output JSON instead of human-readable text')
    args = parser.parse_args()
    
    report = check_cadence_recovery(args.strokes_file, args.threshold, args.window)
    
    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(f"Status: {report.status}")
        print(f"Pre-restart cadence: {report.pre_cadence_s:.1f}s")
        print(f"Post-restart cadence: {report.post_cadence_s:.1f}s")
        print(f"Current cadence: {report.current_cadence_s:.1f}s")
        print(f"Recovery ratio: {report.recovery_ratio:.2f}")
        print(f"Restart gap: {report.gap_seconds:.0f}s")
        print(f"Strokes analyzed: {report.strokes_analyzed}")
        print(f"Last stroke age: {report.last_stroke_age_s:.0f}s")
        print(f"Message: {report.message}")
    
    # Exit codes
    if report.status == "recovered":
        sys.exit(0)
    elif report.status == "degraded":
        sys.exit(1)
    elif report.status == "stalled":
        sys.exit(2)
    else:
        sys.exit(3)


if __name__ == "__main__":
    main()
