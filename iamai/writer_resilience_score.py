#!/usr/bin/env python3
"""writer_resilience_score — measure how robustly the writing system sustains output.

Resilience is the capacity to keep going through interruptions, recover
quickly from stalls, and maintain a steady rhythm over time.  A resilient
writer does not merely produce — it endures.  It bounces back from gaps,
resists burnout, and keeps its cadence even when the environment shifts.

This module analyses a sequence of timestamped writing events (strokes)
and computes five orthogonal resilience dimensions.

**Recovery speed** measures how quickly the writer resumes after a
significant gap (defined as any interval exceeding 2x the expected
cadence).  Fast recovery — minutes, not hours — signals a system
that treats interruptions as momentary, not existential.  The score
is computed as the inverse of the mean recovery time, normalised
against the expected cadence.

**Consistency** captures variance in output rate.  A perfectly
consistent writer produces one stroke per cadence interval with
zero jitter.  Real writers have jitter — what matters is whether
the jitter stays bounded.  We measure the coefficient of variation
of inter-stroke intervals; low CV means high consistency.

**Streak durability** records the longest unbroken writing streak —
a run of consecutive intervals all within 2x the cadence — and
expresses it as a fraction of total observation time.  Long streaks
relative to history indicate sustained momentum.

**Bounce-back rate** is the fraction of significant gaps that were
followed by a resumption within one cadence period.  A gap without
recovery is a stall; a gap followed by recovery is a pause.  High
bounce-back means the writer treats every interruption as a pause.

**Burnout resistance** detects declining output windows: consecutive
periods where the stroke rate drops below half the expected rate.
Frequent declines signal accumulating fatigue; rare or absent
declines signal sustainable pace.  The score is 1 minus the
fraction of time spent in declining windows.

These five dimensions combine into a composite **resilience_index**
(0.0 to 1.0) with configurable weights.  The default weighting
emphasises recovery and consistency:

    recovery_speed   0.25
    consistency      0.25
    streak_durability 0.20
    bounce_back_rate 0.15
    burnout_resistance 0.15

Classification thresholds:

    fragile      — resilience_index < 0.20
    recovering   — 0.20 <= resilience_index < 0.40
    stable       — 0.40 <= resilience_index < 0.65
    robust       — 0.65 <= resilience_index < 0.85
    antifragile  — resilience_index >= 0.85

Resilience is orthogonal to productivity (total output), quality
(content value), and rhythm (short-term cadence adherence).  A
writer can be highly productive but fragile — churning out work
until it collapses.  A resilient writer keeps going.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parent.parent
STROKES_FILE = REPO / "data" / "strokes.jsonl"
DEFAULT_CADENCE = 900.0  # 15 minutes in seconds
DEFAULT_GAP_MULTIPLIER = 2.0  # gap threshold = cadence × multiplier

DEFAULT_WEIGHTS = {
    "recovery_speed": 0.25,
    "consistency": 0.25,
    "streak_durability": 0.20,
    "bounce_back_rate": 0.15,
    "burnout_resistance": 0.15,
}


@dataclass
class ResilienceResult:
    """Complete resilience analysis result."""

    resilience_index: float
    classification: str
    recovery_speed: float
    consistency: float
    streak_durability: float
    bounce_back_rate: float
    burnout_resistance: float
    longest_streak_intervals: int
    total_gaps: int
    recovered_gaps: int
    declining_windows: int
    sample_count: int
    mean_gap_duration: float
    mean_interval: float
    interval_cv: float

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def _parse_timestamps(strokes: list) -> list[float]:
    """Extract unix timestamps from a list of stroke records or ISO strings."""
    timestamps: list[float] = []
    for item in strokes:
        if isinstance(item, (int, float)):
            timestamps.append(float(item))
            continue
        if isinstance(item, str):
            try:
                dt = datetime.fromisoformat(item.replace("Z", "+00:00"))
                timestamps.append(dt.timestamp())
            except ValueError:
                continue
        elif isinstance(item, dict):
            at = item.get("at") or item.get("at_ts") or item.get("timestamp")
            if at is None:
                continue
            if isinstance(at, (int, float)):
                timestamps.append(float(at))
            elif isinstance(at, str):
                try:
                    dt = datetime.fromisoformat(at.replace("Z", "+00:00"))
                    timestamps.append(dt.timestamp())
                except ValueError:
                    continue
    timestamps.sort()
    return timestamps


def _compute_intervals(timestamps: list[float], max_gap: float = 86400.0) -> list[float]:
    """Compute inter-stroke intervals, filtering absurd gaps (> 1 day)."""
    intervals: list[float] = []
    for i in range(1, len(timestamps)):
        gap = timestamps[i] - timestamps[i - 1]
        if 0 < gap <= max_gap:
            intervals.append(gap)
    return intervals


def _recovery_speed_score(
    intervals: list[float],
    cadence: float,
    gap_multiplier: float,
) -> tuple[float, int, int, float]:
    """Score recovery speed after significant gaps.

    Returns (score, total_gaps, recovered_gaps, mean_recovery_time).
    """
    if not intervals:
        return 0.0, 0, 0, 0.0

    threshold = cadence * gap_multiplier
    recovery_times: list[float] = []
    total_gaps = 0

    i = 0
    while i < len(intervals):
        if intervals[i] > threshold:
            total_gaps += 1
            # Find how quickly the next normal interval appears
            recovery_sum = 0.0
            recovered = False
            for j in range(i, min(i + 10, len(intervals))):
                recovery_sum += intervals[j]
                if intervals[j] <= threshold:
                    recovery_times.append(recovery_sum)
                    recovered = True
                    break
            if not recovered:
                # Use the full recovery window
                recovery_times.append(recovery_sum)
        i += 1

    if total_gaps == 0:
        # No gaps means perfect recovery score (nothing to recover from)
        return 1.0, 0, 0, 0.0

    recovered_gaps = sum(1 for rt in recovery_times if rt <= cadence * 3)
    mean_recovery = sum(recovery_times) / len(recovery_times) if recovery_times else 0.0

    # Score: fast recovery relative to cadence
    if mean_recovery <= cadence:
        score = 1.0
    elif mean_recovery <= cadence * 2:
        score = 0.8
    elif mean_recovery <= cadence * 4:
        score = 0.6
    elif mean_recovery <= cadence * 8:
        score = 0.4
    elif mean_recovery <= cadence * 16:
        score = 0.2
    else:
        score = 0.0

    # Boost if most gaps led to quick recovery
    bounce_fraction = recovered_gaps / total_gaps if total_gaps > 0 else 0.0
    score = score * 0.7 + bounce_fraction * 0.3

    return min(1.0, score), total_gaps, recovered_gaps, mean_recovery


def _consistency_score(intervals: list[float], cadence: float) -> tuple[float, float, float]:
    """Score output consistency via coefficient of variation.

    Returns (score, mean_interval, cv).
    """
    if len(intervals) < 2:
        return 0.0, 0.0, 0.0

    mean_iv = sum(intervals) / len(intervals)
    if mean_iv == 0:
        return 0.0, 0.0, 0.0

    variance = sum((x - mean_iv) ** 2 for x in intervals) / len(intervals)
    std_dev = variance ** 0.5
    cv = std_dev / mean_iv

    # Low CV = high consistency
    if cv <= 0.2:
        score = 1.0
    elif cv <= 0.5:
        score = 0.8
    elif cv <= 1.0:
        score = 0.6
    elif cv <= 1.5:
        score = 0.4
    elif cv <= 2.0:
        score = 0.2
    else:
        score = 0.0

    # Penalty if mean interval is far from expected cadence
    ratio = mean_iv / cadence if cadence > 0 else 1.0
    if ratio > 3.0 or ratio < 0.33:
        score *= 0.5
    elif ratio > 2.0 or ratio < 0.5:
        score *= 0.75

    return min(1.0, score), mean_iv, cv


def _streak_durability_score(
    intervals: list[float],
    cadence: float,
    gap_multiplier: float,
    total_time: float,
) -> tuple[float, int]:
    """Score streak durability — longest unbroken run as fraction of history.

    Returns (score, longest_streak_intervals).
    """
    if not intervals or total_time <= 0:
        return 0.0, 0

    threshold = cadence * gap_multiplier
    current_streak = 0
    longest_streak = 0

    for iv in intervals:
        if iv <= threshold:
            current_streak += 1
            longest_streak = max(longest_streak, current_streak)
        else:
            current_streak = 0

    # Express longest streak as fraction of total intervals
    streak_time = longest_streak * cadence  # approximate
    fraction = streak_time / total_time if total_time > 0 else 0.0

    if fraction >= 0.8:
        score = 1.0
    elif fraction >= 0.6:
        score = 0.8
    elif fraction >= 0.4:
        score = 0.6
    elif fraction >= 0.2:
        score = 0.4
    elif fraction >= 0.1:
        score = 0.2
    else:
        score = 0.0

    # Bonus for absolute streak length
    if longest_streak >= 100:
        score = min(1.0, score + 0.1)
    elif longest_streak >= 50:
        score = min(1.0, score + 0.05)

    return min(1.0, score), longest_streak


def _bounce_back_score(
    intervals: list[float],
    cadence: float,
    gap_multiplier: float,
    total_gaps: int,
    recovered_gaps: int,
) -> float:
    """Score bounce-back rate — fraction of gaps followed by recovery."""
    if total_gaps == 0:
        return 1.0  # nothing to bounce from = perfect

    rate = recovered_gaps / total_gaps

    if rate >= 0.9:
        return 1.0
    elif rate >= 0.75:
        return 0.8
    elif rate >= 0.6:
        return 0.6
    elif rate >= 0.4:
        return 0.4
    elif rate >= 0.2:
        return 0.2
    else:
        return 0.0


def _burnout_resistance_score(
    intervals: list[float],
    cadence: float,
    window_size: int = 10,
) -> tuple[float, int]:
    """Detect declining output windows and score burnout resistance.

    A declining window is a sequence of `window_size` consecutive intervals
    where the mean interval exceeds 2x the expected cadence.

    Returns (score, declining_windows_count).
    """
    if len(intervals) < window_size:
        return 1.0, 0  # not enough data to detect decline

    threshold = cadence * 2.0
    declining_count = 0
    declining_intervals = 0

    for i in range(len(intervals) - window_size + 1):
        window = intervals[i : i + window_size]
        window_mean = sum(window) / len(window)
        if window_mean > threshold:
            declining_count += 1
            declining_intervals += 1

    # Fraction of windows that are declining
    total_windows = len(intervals) - window_size + 1
    if total_windows <= 0:
        return 1.0, 0

    decline_fraction = declining_count / total_windows

    if decline_fraction <= 0.05:
        score = 1.0
    elif decline_fraction <= 0.10:
        score = 0.8
    elif decline_fraction <= 0.20:
        score = 0.6
    elif decline_fraction <= 0.35:
        score = 0.4
    elif decline_fraction <= 0.50:
        score = 0.2
    else:
        score = 0.0

    return score, declining_count


def _classify(index: float) -> str:
    """Map resilience_index to a classification label."""
    if index < 0.20:
        return "fragile"
    elif index < 0.40:
        return "recovering"
    elif index < 0.65:
        return "stable"
    elif index < 0.85:
        return "robust"
    else:
        return "antifragile"


def measure_resilience(
    strokes: list,
    cadence: float = DEFAULT_CADENCE,
    gap_multiplier: float = DEFAULT_GAP_MULTIPLIER,
    weights: Optional[dict] = None,
) -> ResilienceResult:
    """Analyse writing resilience from a sequence of strokes.

    Args:
        strokes: list of stroke records.  Each may be a dict with
                 an 'at' key (ISO timestamp or unix epoch), an ISO
                 string, or a numeric timestamp.
        cadence: expected inter-stroke interval in seconds.
        gap_multiplier: intervals exceeding cadence × multiplier
                       are considered significant gaps.
        weights: optional dict overriding default dimension weights.

    Returns:
        ResilienceResult with all metrics and classification.
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    timestamps = _parse_timestamps(strokes)

    if len(timestamps) < 3:
        return ResilienceResult(
            resilience_index=0.0,
            classification="fragile",
            recovery_speed=0.0,
            consistency=0.0,
            streak_durability=0.0,
            bounce_back_rate=0.0,
            burnout_resistance=0.0,
            longest_streak_intervals=0,
            total_gaps=0,
            recovered_gaps=0,
            declining_windows=0,
            sample_count=len(timestamps),
            mean_gap_duration=0.0,
            mean_interval=0.0,
            interval_cv=0.0,
        )

    intervals = _compute_intervals(timestamps)
    total_time = timestamps[-1] - timestamps[0] if len(timestamps) >= 2 else 0.0

    # Dimension 1: Recovery speed
    recovery, total_gaps, recovered_gaps, mean_gap = _recovery_speed_score(
        intervals, cadence, gap_multiplier
    )

    # Dimension 2: Consistency
    consistency, mean_iv, cv = _consistency_score(intervals, cadence)

    # Dimension 3: Streak durability
    streak_score, longest_streak = _streak_durability_score(
        intervals, cadence, gap_multiplier, total_time
    )

    # Dimension 4: Bounce-back rate
    bounce = _bounce_back_score(
        intervals, cadence, gap_multiplier, total_gaps, recovered_gaps
    )

    # Dimension 5: Burnout resistance
    burnout, declining_windows = _burnout_resistance_score(intervals, cadence)

    # Composite index
    index = (
        recovery * w["recovery_speed"]
        + consistency * w["consistency"]
        + streak_score * w["streak_durability"]
        + bounce * w["bounce_back_rate"]
        + burnout * w["burnout_resistance"]
    )
    index = round(min(1.0, max(0.0, index)), 4)

    return ResilienceResult(
        resilience_index=index,
        classification=_classify(index),
        recovery_speed=round(recovery, 4),
        consistency=round(consistency, 4),
        streak_durability=round(streak_score, 4),
        bounce_back_rate=round(bounce, 4),
        burnout_resistance=round(burnout, 4),
        longest_streak_intervals=longest_streak,
        total_gaps=total_gaps,
        recovered_gaps=recovered_gaps,
        declining_windows=declining_windows,
        sample_count=len(timestamps),
        mean_gap_duration=round(mean_gap, 1),
        mean_interval=round(mean_iv, 1),
        interval_cv=round(cv, 4),
    )


def load_strokes_file(path: Path = STROKES_FILE) -> list:
    """Load strokes from a JSONL file."""
    if not path.exists():
        return []
    records: list = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                try:
                    records.append(json.loads(stripped))
                except json.JSONDecodeError:
                    continue
    return records


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure writer resilience from stroke history.",
    )
    parser.add_argument(
        "--file", "-f",
        default=str(STROKES_FILE),
        help="Path to strokes JSONL file.",
    )
    parser.add_argument(
        "--cadence", "-c", type=float, default=DEFAULT_CADENCE,
        help="Expected inter-stroke interval in seconds (default: 900).",
    )
    parser.add_argument(
        "--gap-multiplier", "-g", type=float, default=DEFAULT_GAP_MULTIPLIER,
        help="Gap threshold multiplier (default: 2.0).",
    )
    parser.add_argument(
        "--json", "-j", action="store_true",
        help="Output JSON instead of human-readable text.",
    )
    args = parser.parse_args()

    strokes = load_strokes_file(Path(args.file))
    result = measure_resilience(strokes, args.cadence, args.gap_multiplier)

    if args.json:
        print(result.to_json())
    else:
        print(f"resilience index: {result.resilience_index:.2f}  [{result.classification}]")
        print(f"  recovery speed:      {result.recovery_speed:.2f}")
        print(f"  consistency:         {result.consistency:.2f}")
        print(f"  streak durability:   {result.streak_durability:.2f}")
        print(f"  bounce-back rate:    {result.bounce_back_rate:.2f}")
        print(f"  burnout resistance:  {result.burnout_resistance:.2f}")
        print(f"  longest streak:      {result.longest_streak_intervals} intervals")
        print(f"  total gaps:          {result.total_gaps}")
        print(f"  recovered gaps:      {result.recovered_gaps}")
        print(f"  declining windows:   {result.declining_windows}")
        print(f"  samples:             {result.sample_count}")
        print(f"  mean interval:       {result.mean_interval}s")
        print(f"  interval CV:         {result.interval_cv:.2f}")

    classification_exit = {
        "antifragile": 0,
        "robust": 0,
        "stable": 0,
        "recovering": 1,
        "fragile": 2,
    }
    return classification_exit.get(result.classification, 2)


if __name__ == "__main__":
    raise SystemExit(main())
