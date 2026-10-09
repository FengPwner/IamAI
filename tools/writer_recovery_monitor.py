#!/usr/bin/env python3
"""writer_recovery_monitor.py — verify writer recovery after restart gaps.

The writer dies and gets restarted. The heartbeat probe says "it's running"
and the stroke_gap_monitor says "it's writing again." But is it writing
at full speed? A degraded writer that strokes once a minute instead of
every 15 seconds is technically alive but producing at 25% capacity.

This tool analyzes the stroke history around restart events (large gaps)
and classifies each recovery:

    recovered  — post-gap cadence within tolerance of pre-gap cadence
    degraded   — post-gap cadence is slower but still producing
    failed     — no strokes after the gap, or cadence below threshold

This matters because the recurring 8-hour silence pattern in this repo
wasn't just about the writer dying — it was about the writer coming back
in a degraded state and nobody noticing for hours.

Usage:
    python3 tools/writer_recovery_monitor.py
    python3 tools/writer_recovery_monitor.py --writer qwen --cadence 15
    python3 tools/writer_recovery_monitor.py --json

Exit codes:
    0  — all recoveries healthy (or no restarts detected)
    1  — at least one degraded or failed recovery
    2  — state file missing or unreadable
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
DEFAULT_WRITER = "qwen"
DEFAULT_CADENCE = 15       # expected seconds between strokes
DEFAULT_GAP_THRESHOLD = 150  # seconds — 10× cadence = restart gap
DEFAULT_SAMPLE = 20        # strokes to sample before/after gap
DEFAULT_TOLERANCE = 0.30   # 30% slower is still "recovered"
DEGRADED_FLOOR = 0.10      # below 10% of expected cadence = "failed"


def state_path(writer_id: str) -> Path:
    """Return the writer state file path for a given writer id."""
    return REPO / "data" / f"writer_state.{writer_id}.json"


def parse_iso(ts: str) -> float:
    """Parse an ISO 8601 timestamp to epoch seconds.

    Handles '+00:00', 'Z' suffixes, and naive timestamps (assumed UTC).
    """
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    if "+" not in ts and "-" not in ts[10:]:
        ts += "+00:00"
    dt = datetime.fromisoformat(ts)
    return dt.timestamp()


def load_history(writer_id: str) -> list[dict]:
    """Load stroke history from the writer state file.

    Returns the history list. Raises FileNotFoundError if the state
    file does not exist, or ValueError if it's not valid JSON.
    """
    path = state_path(writer_id)
    if not path.exists():
        raise FileNotFoundError(f"state file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    history = data.get("history", [])
    if not isinstance(history, list):
        raise ValueError(f"history is not a list in {path}")
    return history


@dataclass
class RecoveryEvent:
    """Analysis of a single restart gap and its recovery."""
    gap_index: int            # index in history where the gap ends
    gap_start_iso: str        # last stroke before the gap
    gap_end_iso: str          # first stroke after the gap
    gap_seconds: float        # duration of the gap
    pre_cadence: float | None  # avg seconds/stroke before gap
    post_cadence: float | None  # avg seconds/stroke after gap
    recovery_ratio: float | None  # pre/post — 1.0 = perfect recovery
    status: str               # "recovered" | "degraded" | "failed"
    sample_pre: int           # strokes sampled before gap
    sample_post: int          # strokes sampled after gap

    @property
    def gap_human(self) -> str:
        s = self.gap_seconds
        if s >= 3600:
            return f"{s / 3600:.1f}h"
        if s >= 60:
            return f"{s / 60:.1f}m"
        return f"{s:.0f}s"


@dataclass
class RecoveryReport:
    """Full recovery analysis for a writer."""
    writer_id: str
    total_strokes: int
    restarts_found: int
    events: list[RecoveryEvent] = field(default_factory=list)
    overall_status: str = "healthy"  # worst status across all events

    @property
    def failed_count(self) -> int:
        return sum(1 for e in self.events if e.status == "failed")

    @property
    def degraded_count(self) -> int:
        return sum(1 for e in self.events if e.status == "degraded")

    @property
    def recovered_count(self) -> int:
        return sum(1 for e in self.events if e.status == "recovered")


def compute_cadence(history: list[dict], center: int,
                    direction: str, sample: int) -> tuple[float | None, int]:
    """Compute average cadence from a window of strokes.

    Args:
        history: full stroke history
        center: index of the reference stroke
        direction: "before" (look backward from center) or "after" (forward)
        sample: how many strokes to sample

    Returns:
        (avg_seconds_per_stroke, actual_sample_size)
        Returns (None, 0) if not enough data.
    """
    if direction == "before":
        start = max(0, center - sample)
        end = center
    else:
        start = center
        end = min(len(history), center + sample + 1)

    if end - start < 2:
        return None, max(0, end - start)

    first_ts = parse_iso(history[start]["at"])
    last_ts = parse_iso(history[end - 1]["at"])
    span = last_ts - first_ts
    count = end - start - 1

    if count <= 0 or span <= 0:
        return None, end - start

    return span / count, count


def find_restart_gaps(history: list[dict],
                      gap_threshold: float) -> list[int]:
    """Find indices where a restart gap occurs.

    Returns the index of the first stroke after each gap.
    """
    gaps = []
    for i in range(1, len(history)):
        prev_ts = parse_iso(history[i - 1]["at"])
        curr_ts = parse_iso(history[i]["at"])
        if curr_ts - prev_ts > gap_threshold:
            gaps.append(i)
    return gaps


def classify_recovery(pre_cadence: float | None,
                      post_cadence: float | None,
                      tolerance: float) -> str:
    """Classify a recovery based on pre/post cadence ratio.

    Returns one of: "recovered", "degraded", "failed".
    """
    if post_cadence is None or post_cadence <= 0:
        return "failed"
    if pre_cadence is None or pre_cadence <= 0:
        # No pre-gap data — if post is reasonable, call it recovered
        return "recovered" if post_cadence < 120 else "degraded"

    ratio = pre_cadence / post_cadence
    if ratio < DEGRADED_FLOOR:
        return "failed"
    if ratio < (1.0 - tolerance):
        return "degraded"
    return "recovered"


def analyze(writer_id: str = DEFAULT_WRITER,
            cadence: int = DEFAULT_CADENCE,
            gap_threshold: float = DEFAULT_GAP_THRESHOLD,
            sample: int = DEFAULT_SAMPLE,
            tolerance: float = DEFAULT_TOLERANCE) -> RecoveryReport:
    """Analyze writer recovery events.

    Returns a RecoveryReport with details on each restart gap
    and whether the writer recovered to full cadence.
    """
    try:
        history = load_history(writer_id)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return RecoveryReport(
            writer_id=writer_id,
            total_strokes=0,
            restarts_found=0,
            overall_status="unknown",
        )

    if len(history) < 2:
        return RecoveryReport(
            writer_id=writer_id,
            total_strokes=len(history),
            restarts_found=0,
            overall_status="insufficient_data",
        )

    gap_indices = find_restart_gaps(history, gap_threshold)

    report = RecoveryReport(
        writer_id=writer_id,
        total_strokes=len(history),
        restarts_found=len(gap_indices),
    )

    worst = "healthy"
    status_rank = {"healthy": 0, "recovered": 0, "degraded": 1, "failed": 2}

    for idx in gap_indices:
        pre_cad, pre_n = compute_cadence(history, idx, "before", sample)
        post_cad, post_n = compute_cadence(history, idx, "after", sample)
        ratio = (pre_cad / post_cad) if (pre_cad and post_cad and post_cad > 0) else None

        status = classify_recovery(pre_cad, post_cad, tolerance)
        if status_rank.get(status, 0) > status_rank.get(worst, 0):
            worst = status

        event = RecoveryEvent(
            gap_index=idx,
            gap_start_iso=history[idx - 1]["at"],
            gap_end_iso=history[idx]["at"],
            gap_seconds=parse_iso(history[idx]["at"]) - parse_iso(history[idx - 1]["at"]),
            pre_cadence=round(pre_cad, 2) if pre_cad else None,
            post_cadence=round(post_cad, 2) if post_cad else None,
            recovery_ratio=round(ratio, 3) if ratio else None,
            status=status,
            sample_pre=pre_n,
            sample_post=post_n,
        )
        report.events.append(event)

    report.overall_status = worst
    return report


def as_markdown(report: RecoveryReport) -> str:
    """Format a RecoveryReport as human-readable markdown."""
    lines = [
        f"# writer recovery report — {report.writer_id}",
        f"",
        f"strokes: {report.total_strokes} | restarts: {report.restarts_found} | "
        f"status: **{report.overall_status}**",
    ]

    if not report.events:
        lines.append("")
        lines.append("no restart gaps detected — writer has been stable.")
        return "\n".join(lines)

    for i, ev in enumerate(report.events, 1):
        lines.append("")
        lines.append(f"## restart {i} — gap {ev.gap_human}")
        lines.append(f"")
        lines.append(f"- **before:** {ev.gap_start_iso}")
        lines.append(f"- **after:**  {ev.gap_end_iso}")
        lines.append(f"- **pre cadence:**  {ev.pre_cadence or '?'}s/stroke (n={ev.sample_pre})")
        lines.append(f"- **post cadence:** {ev.post_cadence or '?'}s/stroke (n={ev.sample_post})")
        if ev.recovery_ratio is not None:
            lines.append(f"- **recovery ratio:** {ev.recovery_ratio:.2f} (1.0 = perfect)")
        lines.append(f"- **verdict:** {ev.status}")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--writer", default=DEFAULT_WRITER, help="writer id")
    ap.add_argument("--cadence", type=int, default=DEFAULT_CADENCE,
                    help="expected seconds between strokes")
    ap.add_argument("--gap-threshold", type=float, default=DEFAULT_GAP_THRESHOLD,
                    help="seconds — gaps larger than this are restarts")
    ap.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                    help="strokes to sample before/after each gap")
    ap.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE,
                    help="fraction slower than pre-gap that still counts as recovered")
    ap.add_argument("--json", action="store_true", help="emit JSON output")
    args = ap.parse_args()

    report = analyze(
        writer_id=args.writer,
        cadence=args.cadence,
        gap_threshold=args.gap_threshold,
        sample=args.sample,
        tolerance=args.tolerance,
    )

    if args.json:
        out = asdict(report)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(as_markdown(report))

    if report.overall_status in ("failed", "degraded"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
