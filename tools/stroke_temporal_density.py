#!/usr/bin/env python3
"""
stroke_temporal_density.py — Measure writer output density across time windows.

The writer produces strokes at a nominal cadence (one every 15s).
But "cadence" only measures gaps between consecutive strokes — it
misses longer-term density changes. A writer producing 4 strokes/min
for an hour then 1 stroke/min for the next hour has the same average
cadence but very different density profiles.

This tool:
1. Reads strokes.jsonl and segments strokes into configurable windows
2. Computes strokes-per-minute for each window
3. Calculates density trend (linear regression slope over recent windows)
4. Classifies the writer's current state:
   - prolific:  density > 80% of historical peak
   - steady:    density within 40-80% of peak
   - thinning:  density 10-40% of peak
   - silent:    density < 10% of peak or no strokes in window
5. Detects density cliff: a drop of >50% between consecutive windows

Usage:
    python3 tools/stroke_temporal_density.py
    python3 tools/stroke_temporal_density.py --window 300   # 5-minute windows
    python3 tools/stroke_temporal_density.py --tail 20     # last 20 windows only

Exit codes:
    0 — analysis complete
    2 — data file missing or unreadable
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parent.parent
STROKES_FILE = REPO / "data" / "strokes.jsonl"

DEFAULT_WINDOW_SECONDS = 600  # 10 minutes
DEFAULT_TAIL = 0  # 0 = all windows


def load_strokes(path=STROKES_FILE):
    """Load strokes from JSONL file. Returns list of (timestamp_epoch, kind, text)."""
    strokes = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = obj.get("at", "")
                kind = obj.get("kind", "")
                text = obj.get("text", "")
                seq = obj.get("seq", 0)
                # Parse ISO timestamp to epoch
                epoch = parse_iso(ts)
                if epoch is not None:
                    strokes.append((epoch, kind, text, seq))
    except FileNotFoundError:
        return None
    strokes.sort(key=lambda s: s[0])
    return strokes


def parse_iso(ts_str):
    """Parse ISO 8601 timestamp string to epoch seconds. Returns None on failure."""
    if not ts_str:
        return None
    try:
        # Handle various ISO formats
        ts_str = ts_str.replace("Z", "+00:00")
        if "+" not in ts_str and ts_str.count("-") == 2:
            # Naive timestamp, assume UTC
            dt = datetime.fromisoformat(ts_str)
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(ts_str)
        return dt.timestamp()
    except (ValueError, AttributeError):
        return None


def segment_windows(strokes, window_seconds):
    """
    Segment strokes into fixed-width time windows.
    Returns list of (window_start, window_end, count, strokes_in_window).
    """
    if not strokes:
        return []

    first_ts = strokes[0][0]
    last_ts = strokes[-1][0]

    windows = []
    w_start = first_ts
    while w_start <= last_ts:
        w_end = w_start + window_seconds
        in_window = [s for s in strokes if w_start <= s[0] < w_end]
        windows.append((w_start, w_end, len(in_window), in_window))
        w_start = w_end

    return windows


def compute_density(windows, window_seconds):
    """
    Compute strokes-per-minute for each window.
    Returns list of (window_start, spm, count).
    """
    densities = []
    window_minutes = window_seconds / 60.0
    for w_start, w_end, count, _ in windows:
        spm = count / window_minutes if window_minutes > 0 else 0
        densities.append((w_start, spm, count))
    return densities


def find_peak_density(densities):
    """Return the highest strokes-per-minute value across all windows."""
    if not densities:
        return 0.0
    return max(d[1] for d in densities)


def classify_density(current_spm, peak_spm):
    """
    Classify writer state based on current density vs historical peak.
    Returns one of: prolific, steady, thinning, silent.
    """
    if peak_spm <= 0:
        return "silent"
    ratio = current_spm / peak_spm
    if ratio > 0.8:
        return "prolific"
    elif ratio > 0.4:
        return "steady"
    elif ratio > 0.1:
        return "thinning"
    else:
        return "silent"


def detect_cliff(densities, threshold=0.5):
    """
    Detect density cliffs: consecutive windows where density drops
    by more than `threshold` (default 50%).
    Returns list of (window_index, from_spm, to_spm, drop_ratio).
    """
    cliffs = []
    for i in range(1, len(densities)):
        prev_spm = densities[i - 1][1]
        curr_spm = densities[i][1]
        if prev_spm > 0:
            drop = (prev_spm - curr_spm) / prev_spm
            if drop > threshold:
                cliffs.append((i, prev_spm, curr_spm, drop))
    return cliffs


def density_trend(densities):
    """
    Compute linear trend (slope) of density over recent windows.
    Uses simple linear regression on the last N windows.
    Returns (slope, r_squared) or (0, 0) if insufficient data.
    """
    n = len(densities)
    if n < 3:
        return 0.0, 0.0

    x = list(range(n))
    y = [d[1] for d in densities]

    x_mean = sum(x) / n
    y_mean = sum(y) / n

    ss_xy = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
    ss_xx = sum((x[i] - x_mean) ** 2 for i in range(n))
    ss_yy = sum((y[i] - y_mean) ** 2 for i in range(n))

    if ss_xx == 0:
        return 0.0, 0.0

    slope = ss_xy / ss_xx
    r_squared = (ss_xy ** 2) / (ss_xx * ss_yy) if ss_yy > 0 else 0.0

    return slope, r_squared


def kind_distribution(strokes_in_window):
    """Count stroke kinds in a window. Returns dict of {kind: count}."""
    dist = {}
    for _, kind, _, _ in strokes_in_window:
        dist[kind] = dist.get(kind, 0) + 1
    return dist


def format_report(densities, peak_spm, cliffs, slope, r_sq, tail, window_seconds):
    """Format a human-readable density report."""
    if not densities:
        return "No stroke data available."

    display = densities[-tail:] if tail > 0 else densities
    current = display[-1] if display else None

    lines = []
    lines.append(f"Stroke Temporal Density Report")
    lines.append(f"=" * 40)
    lines.append(f"Window size: {window_seconds}s ({window_seconds / 60:.1f} min)")
    lines.append(f"Total windows: {len(densities)}")
    lines.append(f"Peak density: {peak_spm:.3f} strokes/min")
    lines.append(f"Trend slope: {slope:.4f} spm/window (r²={r_sq:.3f})")

    if current:
        state = classify_density(current[1], peak_spm)
        lines.append(f"Current density: {current[1]:.3f} strokes/min [{state}]")

    if cliffs:
        lines.append(f"Density cliffs detected: {len(cliffs)}")
        for idx, from_spm, to_spm, drop in cliffs[-5:]:
            ts = datetime.fromtimestamp(densities[idx][0], tz=timezone.utc)
            lines.append(f"  window {idx}: {from_spm:.3f} → {to_spm:.3f} "
                        f"(-{drop * 100:.0f}%) at {ts.strftime('%H:%M')}")
    else:
        lines.append("No density cliffs detected.")

    lines.append(f"")
    lines.append(f"Recent windows (last {len(display)}):")
    for w_start, spm, count in display[-10:]:
        ts = datetime.fromtimestamp(w_start, tz=timezone.utc)
        state = classify_density(spm, peak_spm)
        lines.append(f"  {ts.strftime('%Y-%m-%d %H:%M')}  "
                    f"{count:3d} strokes  {spm:.3f} spm  [{state}]")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Measure writer output density across time windows."
    )
    parser.add_argument(
        "--window", type=int, default=DEFAULT_WINDOW_SECONDS,
        help=f"Window size in seconds (default: {DEFAULT_WINDOW_SECONDS})"
    )
    parser.add_argument(
        "--tail", type=int, default=DEFAULT_TAIL,
        help="Show only the last N windows (default: all)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON instead of human-readable report"
    )
    args = parser.parse_args()

    strokes = load_strokes()
    if strokes is None:
        print(f"ERROR: cannot read {STROKES_FILE}", file=sys.stderr)
        sys.exit(2)

    if not strokes:
        print("No strokes found.")
        sys.exit(0)

    windows = segment_windows(strokes, args.window)
    densities = compute_density(windows, args.window)
    peak = find_peak_density(densities)
    cliffs = detect_cliff(densities)
    slope, r_sq = density_trend(densities)

    if args.json:
        current = densities[-1] if densities else None
        state = classify_density(current[1], peak) if current else "silent"
        result = {
            "window_seconds": args.window,
            "total_windows": len(densities),
            "peak_spm": round(peak, 4),
            "current_spm": round(current[1], 4) if current else 0,
            "current_state": state,
            "trend_slope": round(slope, 6),
            "trend_r_squared": round(r_sq, 4),
            "cliff_count": len(cliffs),
            "cliffs": [
                {"window": idx, "from": round(f, 4), "to": round(t, 4), "drop": round(d, 4)}
                for idx, f, t, d in cliffs[-10:]
            ],
            "recent": [
                {"at": datetime.fromtimestamp(w, tz=timezone.utc).isoformat(),
                 "spm": round(s, 4), "count": c}
                for w, s, c in densities[-10:]
            ]
        }
        print(json.dumps(result, indent=2))
    else:
        report = format_report(densities, peak, cliffs, slope, r_sq, args.tail, args.window)
        print(report)


if __name__ == "__main__":
    main()
