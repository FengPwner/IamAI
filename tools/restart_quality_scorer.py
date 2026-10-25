#!/usr/bin/env python3
"""restart_quality_scorer.py — score the quality of a process restart.

after a container recycle or manual restart, how well did the writer
recover? this tool answers that by measuring:

1. **gap_seconds**: time between the last stroke before restart and the
   first stroke after restart. shorter = better.
2. **recovery_latency**: time from restart (process start) to the first
   new stroke. if the writer takes 5 minutes to produce its first stroke
   after restart, something is wrong even if strokes are flowing now.
3. **cadence_ratio**: post-restart stroke rate divided by pre-restart
   stroke rate. 1.0 = perfect recovery, <0.5 = serious degradation.
4. **estimated_loss**: how many strokes were likely lost during the gap,
   based on the pre-restart cadence.

each metric is scored 0-100 and combined into a weighted composite.

usage:
    python3 tools/restart_quality_scorer.py
    python3 tools/restart_quality_scorer.py --writer qwen --window 20
    python3 tools/restart_quality_scorer.py --json

exit codes:
    0 — all recent restarts scored "good" (>=70)
    1 — at least one restart scored "degraded" (40-69)
    2 — at least one restart scored "poor" (<40) or error
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DEFAULT_STROKES = REPO / "data" / "strokes.jsonl"

# Thresholds (seconds)
GAP_GOOD = 300       # 5 min — container recycle is fast
GAP_BAD = 1800       # 30 min — something went wrong
RECOVERY_GOOD = 120  # 2 min — writer started producing quickly
RECOVERY_BAD = 600   # 10 min — writer struggled to start
CADENCE_GOOD = 0.8   # 80% of pre-restart rate
CADENCE_BAD = 0.3    # 30% of pre-restart rate


@dataclass
class RestartScore:
    """Score for a single restart event."""

    restart_index: int
    gap_seconds: float
    recovery_latency: float
    cadence_ratio: float
    estimated_loss: int
    pre_cadence_spm: float   # strokes per minute before restart
    post_cadence_spm: float  # strokes per minute after restart
    last_pre_seq: int
    first_post_seq: int
    seq_gap: int
    composite: float = 0.0
    grade: str = ""

    def __post_init__(self) -> None:
        self.composite = self._compute_composite()
        self.grade = self._compute_grade()

    def _compute_composite(self) -> float:
        gap_score = _score_linear(self.gap_seconds, GAP_GOOD, GAP_BAD)
        recovery_score = _score_linear(self.recovery_latency, RECOVERY_GOOD, RECOVERY_BAD)
        cadence_score = _score_linear_inv(self.cadence_ratio, CADENCE_BAD, CADENCE_GOOD)
        loss_penalty = min(self.estimated_loss / 50.0, 1.0) * 30  # up to -30

        raw = (gap_score * 0.25 + recovery_score * 0.25 + cadence_score * 0.50)
        return max(0.0, min(100.0, raw - loss_penalty))

    def _compute_grade(self) -> str:
        if self.composite >= 70:
            return "good"
        if self.composite >= 40:
            return "degraded"
        return "poor"


def _score_linear(value: float, good: float, bad: float) -> float:
    """100 when value <= good, 0 when value >= bad, linear between."""
    if value <= good:
        return 100.0
    if value >= bad:
        return 0.0
    return 100.0 * (bad - value) / (bad - good)


def _score_linear_inv(value: float, bad: float, good: float) -> float:
    """100 when value >= good, 0 when value <= bad, linear between.
    (higher is better, inverted from _score_linear)"""
    if value >= good:
        return 100.0
    if value <= bad:
        return 0.0
    return 100.0 * (value - bad) / (good - bad)


# ---------------------------------------------------------------------------
# Stroke loading
# ---------------------------------------------------------------------------


def load_strokes(path: Path) -> list[dict[str, Any]]:
    """Load strokes from JSONL, skipping malformed lines."""
    strokes: list[dict[str, Any]] = []
    if not path.exists():
        return strokes
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                strokes.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return strokes


def parse_ts(ts_str: str) -> datetime | None:
    """Parse an ISO timestamp, returning None on failure."""
    if ts_str is None:
        return None
    try:
        # Handle various ISO formats
        ts_str = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Restart detection
# ---------------------------------------------------------------------------


def detect_restarts(
    strokes: list[dict[str, Any]], *, gap_threshold: float = 300.0
) -> list[tuple[int, int]]:
    """Find restart boundaries: pairs of (last_pre_index, first_post_index).

    A restart is detected when the gap between consecutive strokes exceeds
    *gap_threshold* seconds (default 5 minutes — much larger than the normal
    15-second cadence).

    Returns list of (last_before_restart_idx, first_after_restart_idx).
    """
    restarts: list[tuple[int, int]] = []
    for i in range(1, len(strokes)):
        prev_ts = parse_ts(strokes[i - 1].get("at", ""))
        curr_ts = parse_ts(strokes[i].get("at", ""))
        if prev_ts is None or curr_ts is None:
            continue
        gap = (curr_ts - prev_ts).total_seconds()
        if gap > gap_threshold:
            restarts.append((i - 1, i))
    return restarts


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_restart(
    strokes: list[dict[str, Any]],
    last_pre: int,
    first_post: int,
    *,
    pre_window: int = 20,
    post_window: int = 20,
    index: int = 0,
) -> RestartScore:
    """Score a single restart event.

    Parameters
    ----------
    strokes : full stroke list
    last_pre : index of the last stroke before the restart
    first_post : index of the first stroke after the restart
    pre_window : how many strokes before restart to measure pre-cadence
    post_window : how many strokes after restart to measure post-cadence
    index : restart sequence number (for labeling)
    """
    # Gap between last pre and first post
    pre_ts = parse_ts(strokes[last_pre].get("at", ""))
    post_ts = parse_ts(strokes[first_post].get("at", ""))
    gap_seconds = (post_ts - pre_ts).total_seconds() if pre_ts and post_ts else 0.0

    # Recovery latency: approximate restart time as midpoint of the gap
    # (we don't know exact restart time, but the gap midpoint is a
    # reasonable estimate for automated container recycles)
    recovery_latency = gap_seconds / 2.0

    # Pre-restart cadence (strokes per minute)
    pre_start = max(0, last_pre - pre_window + 1)
    pre_slice = strokes[pre_start : last_pre + 1]
    pre_cadence_spm = _cadence_spm(pre_slice)

    # Post-restart cadence
    post_end = min(len(strokes), first_post + post_window)
    post_slice = strokes[first_post:post_end]
    post_cadence_spm = _cadence_spm(post_slice)

    # Cadence ratio
    cadence_ratio = (post_cadence_spm / pre_cadence_spm) if pre_cadence_spm > 0 else 1.0

    # Estimated loss: how many strokes should have been produced during gap
    estimated_loss = max(0, int(pre_cadence_spm * (gap_seconds / 60.0)))

    # Seq gap
    last_pre_seq = strokes[last_pre].get("seq", last_pre)
    first_post_seq = strokes[first_post].get("seq", first_post)
    seq_gap = max(0, first_post_seq - last_pre_seq - 1)

    return RestartScore(
        restart_index=index,
        gap_seconds=gap_seconds,
        recovery_latency=recovery_latency,
        cadence_ratio=min(cadence_ratio, 2.0),  # cap at 2x to avoid runaway
        estimated_loss=estimated_loss,
        pre_cadence_spm=pre_cadence_spm,
        post_cadence_spm=post_cadence_spm,
        last_pre_seq=last_pre_seq,
        first_post_seq=first_post_seq,
        seq_gap=seq_gap,
    )


def _cadence_spm(strokes_slice: list[dict[str, Any]]) -> float:
    """Calculate strokes per minute for a slice of strokes."""
    if len(strokes_slice) < 2:
        return 0.0
    first_ts = parse_ts(strokes_slice[0].get("at", ""))
    last_ts = parse_ts(strokes_slice[-1].get("at", ""))
    if first_ts is None or last_ts is None:
        return 0.0
    span_minutes = (last_ts - first_ts).total_seconds() / 60.0
    if span_minutes <= 0:
        return 0.0
    return len(strokes_slice) / span_minutes


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_text(scores: list[RestartScore], total_restarts: int) -> str:
    """Human-readable output."""
    if not scores:
        return "restart_quality_scorer: no restarts detected"
    lines = [
        f"restart_quality_scorer: {len(scores)} restart(s) scored "
        f"(showing last {min(len(scores), 5)})"
    ]
    for s in scores[-5:]:
        lines.append(
            f"  #{s.restart_index}: {s.grade} ({s.composite:.0f}/100)"
        )
        lines.append(
            f"    gap={s.gap_seconds:.0f}s  recovery={s.recovery_latency:.0f}s"
            f"  cadence_ratio={s.cadence_ratio:.2f}"
        )
        lines.append(
            f"    pre={s.pre_cadence_spm:.2f}spm  post={s.post_cadence_spm:.2f}spm"
            f"  est_loss={s.estimated_loss}  seq_gap={s.seq_gap}"
        )
        lines.append(
            f"    seqs: {s.last_pre_seq} → {s.first_post_seq}"
        )
    return "\n".join(lines)


def format_json(scores: list[RestartScore]) -> str:
    """Machine-readable JSON output."""
    payload = {
        "restart_count": len(scores),
        "restarts": [
            {
                "index": s.restart_index,
                "grade": s.grade,
                "composite": round(s.composite, 1),
                "gap_seconds": round(s.gap_seconds, 1),
                "recovery_latency": round(s.recovery_latency, 1),
                "cadence_ratio": round(s.cadence_ratio, 3),
                "estimated_loss": s.estimated_loss,
                "pre_cadence_spm": round(s.pre_cadence_spm, 3),
                "post_cadence_spm": round(s.post_cadence_spm, 3),
                "seq_gap": s.seq_gap,
                "last_pre_seq": s.last_pre_seq,
                "first_post_seq": s.first_post_seq,
            }
            for s in scores[-20:]
        ],
    }
    return json.dumps(payload, indent=2)


def worst_exit_code(scores: list[RestartScore]) -> int:
    """0 = all good, 1 = any degraded, 2 = any poor or empty."""
    if not scores:
        return 2
    grades = {s.grade for s in scores}
    if "poor" in grades:
        return 2
    if "degraded" in grades:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def run(
    strokes_path: Path = DEFAULT_STROKES,
    *,
    gap_threshold: float = 300.0,
    pre_window: int = 20,
    post_window: int = 20,
    as_json: bool = False,
) -> tuple[int, str]:
    """Main entry point. Returns (exit_code, output_text)."""
    strokes = load_strokes(strokes_path)
    if not strokes:
        return 2, "error: no strokes found"

    restarts = detect_restarts(strokes, gap_threshold=gap_threshold)
    if not restarts:
        return 0, "restart_quality_scorer: no restarts detected (continuous operation)"

    scores = [
        score_restart(
            strokes,
            last_pre,
            first_post,
            pre_window=pre_window,
            post_window=post_window,
            index=i,
        )
        for i, (last_pre, first_post) in enumerate(restarts)
    ]

    if as_json:
        return worst_exit_code(scores), format_json(scores)
    return worst_exit_code(scores), format_text(scores, len(restarts))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score the quality of process restarts"
    )
    parser.add_argument("--strokes", type=Path, default=DEFAULT_STROKES)
    parser.add_argument(
        "--gap-threshold",
        type=float,
        default=300.0,
        help="seconds between strokes to consider a restart (default 300)",
    )
    parser.add_argument("--pre-window", type=int, default=20)
    parser.add_argument("--post-window", type=int, default=20)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    code, output = run(
        args.strokes,
        gap_threshold=args.gap_threshold,
        pre_window=args.pre_window,
        post_window=args.post_window,
        as_json=args.as_json,
    )
    print(output)
    sys.exit(code)


if __name__ == "__main__":
    main()
