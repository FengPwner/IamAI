#!/usr/bin/env python3
"""Classify commit gaps into health categories.

Reads git log timestamps and classifies each gap between consecutive
commits as:
  - normal: gap <= 2x median
  - stretched: gap <= 5x median  
  - stalled: gap > 5x median
  - overnight: gap > 1 hour and occurred between 00:00-06:00

Usage:
    python3 tools/commit_gap_classifier.py [--limit N] [--json]
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from statistics import median
from typing import List, Dict, Tuple


def get_commit_timestamps(limit: int = 50) -> List[datetime]:
    """Get commit timestamps from git log."""
    cmd = [
        "git", "log", "--format=%aI", f"-{limit}", "--reverse"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"git log failed: {result.stderr}", file=sys.stderr)
        return []
    
    timestamps = []
    for line in result.stdout.strip().split("\n"):
        if line:
            # Parse ISO 8601 timestamp
            try:
                dt = datetime.fromisoformat(line.strip())
                timestamps.append(dt)
            except ValueError:
                continue
    return timestamps


def classify_gap(gap_seconds: float, median_gap: float, 
                 timestamp: datetime) -> str:
    """Classify a single gap between commits."""
    hour = timestamp.hour
    
    # Overnight stall: >1 hour gap during early morning
    if gap_seconds > 3600 and 0 <= hour < 6:
        return "overnight"
    
    # Stalled: >5x median
    if gap_seconds > 5 * median_gap:
        return "stalled"
    
    # Stretched: >2x median
    if gap_seconds > 2 * median_gap:
        return "stretched"
    
    # Normal
    return "normal"


def analyze_gaps(limit: int = 50) -> Tuple[List[Dict], float, float]:
    """Analyze commit gaps and return classifications."""
    timestamps = get_commit_timestamps(limit)
    
    if len(timestamps) < 2:
        return [], 0.0, 0.0
    
    gaps = []
    for i in range(1, len(timestamps)):
        gap = (timestamps[i] - timestamps[i-1]).total_seconds()
        gaps.append(gap)
    
    if not gaps:
        return [], 0.0, 0.0
    
    median_gap = median(gaps)
    max_gap = max(gaps)
    
    classifications = []
    for i, gap in enumerate(gaps):
        classification = classify_gap(
            gap, median_gap, timestamps[i+1]
        )
        classifications.append({
            "gap_seconds": gap,
            "classification": classification,
            "timestamp": timestamps[i+1].isoformat(),
            "hour": timestamps[i+1].hour
        })
    
    return classifications, median_gap, max_gap


def main():
    parser = argparse.ArgumentParser(
        description="Classify commit gaps into health categories"
    )
    parser.add_argument(
        "--limit", type=int, default=50,
        help="Number of recent commits to analyze (default: 50)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON instead of table"
    )
    args = parser.parse_args()
    
    classifications, median_gap, max_gap = analyze_gaps(args.limit)
    
    if not classifications:
        print("No commits found or insufficient data.", file=sys.stderr)
        sys.exit(1)
    
    if args.json:
        output = {
            "median_gap_seconds": median_gap,
            "max_gap_seconds": max_gap,
            "total_gaps": len(classifications),
            "classifications": classifications
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"Commit gap analysis (last {args.limit} commits)")
        print(f"Median gap: {median_gap:.0f}s  Max gap: {max_gap:.0f}s")
        print()
        print(f"{'Timestamp':<25} {'Gap':>8} {'Hour':>5} {'Classification':<15}")
        print("-" * 60)
        for c in classifications:
            print(
                f"{c['timestamp']:<25} "
                f"{c['gap_seconds']:>7.0f}s "
                f"{c['hour']:>4}h "
                f"{c['classification']:<15}"
            )
        
        # Summary
        counts = {}
        for c in classifications:
            cls = c["classification"]
            counts[cls] = counts.get(cls, 0) + 1
        
        print()
        print("Summary:")
        for cls in ["normal", "stretched", "stalled", "overnight"]:
            count = counts.get(cls, 0)
            pct = 100 * count / len(classifications)
            print(f"  {cls:<15} {count:>3} ({pct:5.1f}%)")


if __name__ == "__main__":
    main()
