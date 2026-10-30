#!/usr/bin/env python3
"""cadence_stall_detector.py — detect writer stalls by measuring gap since last stroke.

Reads the last stroke timestamp from data/strokes.jsonl and the configured
cadence from data/writer_state.qwen.json, then computes how long the writer
has been silent relative to its expected cadence.

Exit codes:
    0 — no stall (gap < 2x cadence)
    1 — mild stall (2x–5x cadence gap)
    2 — severe stall (>5x cadence gap)
    3 — cannot determine (missing data files)

Usage:
    python3 tools/cadence_stall_detector.py
    python3 tools/cadence_stall_detector.py --repo /path/to/IamAI
    python3 tools/cadence_stall_detector.py --cadence 15   # override seconds
    python3 tools/cadence_stall_detector.py --json          # output JSON summary
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from start (or cwd) to find the repo root containing data/."""
    p = start or Path.cwd()
    for parent in [p, *p.parents]:
        if (parent / "data" / "strokes.jsonl").exists():
            return parent
    return p


def get_last_stroke_time(repo: Path) -> datetime | None:
    """Read the last line of strokes.jsonl and return its timestamp."""
    strokes_path = repo / "data" / "strokes.jsonl"
    if not strokes_path.exists():
        return None

    last_line = None
    # Read last line efficiently
    with open(strokes_path, "rb") as f:
        f.seek(0, 2)  # seek to end
        size = f.tell()
        if size == 0:
            return None
        # Read backwards to find the last complete line
        buf_size = 4096
        buf = b""
        while size > 0:
            read_size = min(buf_size, size)
            f.seek(size - read_size)
            buf = f.read(read_size) + buf
            size -= read_size
            lines = buf.split(b"\n")
            # Check if we have at least 2 lines (last might be empty)
            non_empty = [l for l in lines if l.strip()]
            if non_empty:
                last_line = non_empty[-1].decode("utf-8")
                break

    if not last_line:
        return None

    try:
        record = json.loads(last_line)
        ts = record.get("at")
        if ts:
            # Parse ISO format timestamp
            return datetime.fromisoformat(ts)
    except (json.JSONDecodeError, ValueError):
        return None
    return None


def get_configured_cadence(repo: Path) -> int | None:
    """Read the configured cadence from writer_state.qwen.json."""
    state_path = repo / "data" / "writer_state.qwen.json"
    if not state_path.exists():
        return None
    try:
        with open(state_path) as f:
            state = json.load(f)
        # Look for cadence in various possible locations
        if "cadence" in state:
            return int(state["cadence"])
        if "config" in state and "cadence" in state["config"]:
            return int(state["config"]["cadence"])
        # Check history for interval inference
        history = state.get("history", [])
        if len(history) >= 2:
            # Infer from last two entries
            t1 = datetime.fromisoformat(history[-2]["at"])
            t2 = datetime.fromisoformat(history[-1]["at"])
            return int((t2 - t1).total_seconds())
    except (json.JSONDecodeError, ValueError, KeyError):
        return None
    return None


def detect_stall(
    repo: Path | None = None,
    cadence_override: int | None = None,
    now: datetime | None = None,
) -> dict:
    """Detect writer stall and return a summary dict."""
    repo = repo or find_repo_root()
    now = now or datetime.now(timezone.utc)

    last_stroke = get_last_stroke_time(repo)
    if last_stroke is None:
        return {
            "status": "unknown",
            "exit_code": 3,
            "reason": "no stroke data found",
        }

    cadence = cadence_override or get_configured_cadence(repo) or 15

    # Ensure last_stroke is timezone-aware
    if last_stroke.tzinfo is None:
        last_stroke = last_stroke.replace(tzinfo=timezone.utc)

    gap_seconds = (now - last_stroke).total_seconds()
    gap_ratio = gap_seconds / cadence if cadence > 0 else float("inf")

    if gap_ratio >= 5:
        severity = "severe"
        exit_code = 2
    elif gap_ratio >= 2:
        severity = "mild"
        exit_code = 1
    else:
        severity = "none"
        exit_code = 0

    return {
        "status": severity,
        "exit_code": exit_code,
        "last_stroke": last_stroke.isoformat(),
        "gap_seconds": round(gap_seconds, 1),
        "cadence_seconds": cadence,
        "gap_ratio": round(gap_ratio, 2),
        "checked_at": now.isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect writer cadence stalls")
    parser.add_argument("--repo", type=Path, help="Path to repo root")
    parser.add_argument("--cadence", type=int, help="Override cadence in seconds")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output JSON summary")
    args = parser.parse_args()

    repo = args.repo or find_repo_root()
    result = detect_stall(repo=repo, cadence_override=args.cadence)

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        status = result["status"]
        if status == "unknown":
            print(f"cadence_stall_detector: UNKNOWN — {result.get('reason', '')}")
        else:
            gap = result["gap_seconds"]
            cad = result["cadence_seconds"]
            ratio = result["gap_ratio"]
            print(
                f"cadence_stall_detector: {status.upper()} — "
                f"gap {gap:.0f}s, cadence {cad}s, ratio {ratio:.1f}x"
            )

    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
