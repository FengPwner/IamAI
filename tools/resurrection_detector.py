"""resurrection_detector.py — detect writer restarts and backfill events.

when a writer process dies and is later restarted, the strokes written
immediately after restart may include backfilled content that was queued
during the outage. this module detects such resurrection events by
identifying:

1. stall gaps: periods where no strokes were written (exceeding a
   configurable threshold)
2. backfill bursts: clusters of strokes written in rapid succession
   immediately after a stall gap, with timestamps that predate the
   restart

detecting resurrections matters because:
- cadence metrics assume continuous operation
- sequence numbers may not reflect temporal ordering after backfill
- readers of the log deserve to know when continuity was broken

usage:
    from resurrection_detector import detect_resurrections, tag_strokes

    strokes = load_strokes("data/strokes.jsonl")
    events = detect_resurrections(strokes, stall_threshold_sec=300)
    tagged = tag_strokes(strokes, events)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def parse_timestamp(ts: str) -> datetime:
    """parse an ISO 8601 timestamp string into a timezone-aware datetime.

    handles both 'Z' suffix and '+HH:MM' offset formats.

    Args:
        ts: ISO 8601 timestamp string

    Returns:
        timezone-aware datetime object

    Raises:
        ValueError: if timestamp format is invalid
    """
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def compute_gaps(strokes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """compute time gaps between consecutive strokes.

    Args:
        strokes: list of stroke dicts, each with an 'at' timestamp field.
                 must be sorted by timestamp ascending.

    Returns:
        list of gap dicts, each containing:
            - gap_start: datetime of the earlier stroke
            - gap_end: datetime of the later stroke
            - gap_sec: gap duration in seconds
            - index: index of the later stroke in the input list
    """
    gaps = []
    for i in range(1, len(strokes)):
        prev_ts = parse_timestamp(strokes[i - 1]["at"])
        curr_ts = parse_timestamp(strokes[i]["at"])
        gap_sec = (curr_ts - prev_ts).total_seconds()
        gaps.append({
            "gap_start": prev_ts,
            "gap_end": curr_ts,
            "gap_sec": gap_sec,
            "index": i,
        })
    return gaps


def detect_stalls(
    gaps: list[dict[str, Any]],
    stall_threshold_sec: float = 300.0,
) -> list[dict[str, Any]]:
    """identify stall gaps that exceed the threshold.

    Args:
        gaps: output of compute_gaps()
        stall_threshold_sec: minimum gap duration (seconds) to classify
                             as a stall. default 300 (5 minutes).

    Returns:
        list of stall dicts (subset of input gaps where gap_sec >= threshold)
    """
    return [g for g in gaps if g["gap_sec"] >= stall_threshold_sec]


def detect_backfill_burst(
    strokes: list[dict[str, Any]],
    stall_end_index: int,
    burst_window_sec: float = 60.0,
    min_burst_size: int = 3,
) -> dict[str, Any] | None:
    """detect a backfill burst immediately after a stall.

    a backfill burst is a cluster of strokes written in rapid succession
    (within burst_window_sec of each other) starting at stall_end_index.

    Args:
        strokes: full stroke list
        stall_end_index: index of the first stroke after the stall
        burst_window_sec: max time between consecutive strokes to
                          consider them part of the same burst
        min_burst_size: minimum number of strokes to qualify as a burst

    Returns:
        burst dict with 'start_index', 'end_index', 'count', 'span_sec'
        or None if no burst detected
    """
    if stall_end_index >= len(strokes):
        return None

    burst_start = parse_timestamp(strokes[stall_end_index]["at"])
    end_index = stall_end_index

    for i in range(stall_end_index + 1, len(strokes)):
        curr_ts = parse_timestamp(strokes[i]["at"])
        prev_ts = parse_timestamp(strokes[i - 1]["at"])
        if (curr_ts - prev_ts).total_seconds() > burst_window_sec:
            break
        end_index = i

    count = end_index - stall_end_index + 1
    if count < min_burst_size:
        return None

    span_sec = (
        parse_timestamp(strokes[end_index]["at"]) - burst_start
    ).total_seconds()

    return {
        "start_index": stall_end_index,
        "end_index": end_index,
        "count": count,
        "span_sec": span_sec,
    }


def detect_resurrections(
    strokes: list[dict[str, Any]],
    stall_threshold_sec: float = 300.0,
    burst_window_sec: float = 60.0,
    min_burst_size: int = 3,
) -> list[dict[str, Any]]:
    """detect resurrection events: a stall followed by a backfill burst.

    Args:
        strokes: list of stroke dicts sorted by timestamp ascending
        stall_threshold_sec: gap duration to classify as a stall
        burst_window_sec: max inter-stroke gap within a burst
        min_burst_size: minimum strokes to qualify as a burst

    Returns:
        list of resurrection event dicts, each containing:
            - stall_gap_sec: duration of the stall
            - stall_start: timestamp of last stroke before stall
            - stall_end: timestamp of first stroke after stall
            - burst_start_index: index of first backfilled stroke
            - burst_end_index: index of last backfilled stroke
            - burst_count: number of strokes in the burst
            - burst_span_sec: time span of the burst
    """
    if len(strokes) < 2:
        return []

    gaps = compute_gaps(strokes)
    stalls = detect_stalls(gaps, stall_threshold_sec)

    events = []
    for stall in stalls:
        burst = detect_backfill_burst(
            strokes,
            stall["index"],
            burst_window_sec,
            min_burst_size,
        )
        if burst is not None:
            events.append({
                "stall_gap_sec": stall["gap_sec"],
                "stall_start": stall["gap_start"],
                "stall_end": stall["gap_end"],
                "burst_start_index": burst["start_index"],
                "burst_end_index": burst["end_index"],
                "burst_count": burst["count"],
                "burst_span_sec": burst["span_sec"],
            })

    return events


def tag_strokes(
    strokes: list[dict[str, Any]],
    events: list[dict[str, Any]],
    tag_field: str = "resurrection_tag",
) -> list[dict[str, Any]]:
    """annotate strokes that are part of a resurrection burst.

    adds a tag_field to each stroke that falls within a detected burst.
    the tag value is a dict with 'event_index' and 'position_in_burst'.

    Args:
        strokes: list of stroke dicts (will be shallow-copied)
        events: output of detect_resurrections()
        tag_field: name of the field to add

    Returns:
        new list of stroke dicts with tags applied
    """
    tagged = [dict(s) for s in strokes]

    for event_idx, event in enumerate(events):
        for pos, i in enumerate(
            range(event["burst_start_index"], event["burst_end_index"] + 1)
        ):
            if i < len(tagged):
                tagged[i][tag_field] = {
                    "event_index": event_idx,
                    "position_in_burst": pos,
                    "stall_gap_sec": event["stall_gap_sec"],
                }

    return tagged


def summarize_resurrections(events: list[dict[str, Any]]) -> str:
    """produce a human-readable summary of resurrection events.

    Args:
        events: output of detect_resurrections()

    Returns:
        multi-line summary string
    """
    if not events:
        return "no resurrection events detected."

    lines = [f"detected {len(events)} resurrection event(s):"]
    for i, e in enumerate(events):
        lines.append(
            f"  [{i}] stall: {e['stall_gap_sec']:.0f}s "
            f"({e['stall_gap_sec']/60:.1f}min), "
            f"burst: {e['burst_count']} strokes in {e['burst_span_sec']:.0f}s"
        )
    return "\n".join(lines)


def load_strokes(path: str) -> list[dict[str, Any]]:
    """load strokes from a JSONL file.

    Args:
        path: path to strokes.jsonl

    Returns:
        list of stroke dicts
    """
    strokes = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                strokes.append(json.loads(line))
    return strokes


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "data/strokes.jsonl"
    strokes = load_strokes(path)
    events = detect_resurrections(strokes)
    print(summarize_resurrections(events))
