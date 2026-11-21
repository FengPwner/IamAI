#!/usr/bin/env python3
"""stroke_persistence.py — verify the writer's output is reaching disk.

the writer process can be "running" (PID alive, CPU cycling) without
actually appending to strokes.jsonl. causes include:

  - stdout/stderr captured but never flushed
  - file handle open in a stale working directory after container recycle
  - permission denied on the data directory, silently swallowed
  - the writer entered a spin loop that doesn't call the append function

this tool builds a short observation window by sampling the file's
line count and mtime twice, then classifies the result:

  - active:   line count increased and mtime changed
  - idle:     line count unchanged but mtime recent (flush happened)
  - stale:    no change at all within the observation window
  - missing:  strokes.jsonl does not exist

it also supports a single-shot --snapshot mode that reports the current
file size, line count, mtime age, and estimated stroke rate from the
last N lines without waiting for a second sample.

usage:
    python3 tools/stroke_persistence.py --writer qwen
    python3 tools/stroke_persistence.py --writer qwen --wait 30
    python3 tools/stroke_persistence.py --writer qwen --snapshot
    python3 tools/stroke_persistence.py --writer qwen --json

exit codes:
    0 — active or idle (writer output reaching disk)
    1 — stale (no evidence of writes in observation window)
    2 — missing (data file not found)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class Sample:
    line_count: int
    mtime: float
    size_bytes: int


@dataclass
class Verdict:
    status: str          # active | idle | stale | missing
    lines_delta: int
    seconds_elapsed: float
    last_stroke_age_s: Optional[float]
    current_rate_per_hour: Optional[float]
    file_path: str
    detail: str


def sample_file(path: Path) -> Optional[Sample]:
    """Take a point-in-time sample of the strokes file."""
    if not path.exists():
        return None
    stat = path.stat()
    line_count = 0
    with open(path, "r", encoding="utf-8") as f:
        for _ in f:
            line_count += 1
    return Sample(
        line_count=line_count,
        mtime=stat.st_mtime,
        size_bytes=stat.st_size,
    )


def last_stroke_timestamp(path: Path) -> Optional[float]:
    """Read the 'at' field from the last line of strokes.jsonl."""
    if not path.exists():
        return None
    last_line = ""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                last_line = line
    if not last_line:
        return None
    try:
        obj = json.loads(last_line)
        at_str = obj.get("at", "")
        dt = datetime.fromisoformat(at_str)
        return dt.timestamp()
    except (json.JSONDecodeError, ValueError, KeyError):
        return None


def estimate_rate(path: Path, tail_n: int = 20) -> Optional[float]:
    """Estimate strokes per hour from the last N lines."""
    if not path.exists():
        return None
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            lines.append(line.strip())
    tail = [l for l in lines[-tail_n:] if l]
    if len(tail) < 2:
        return None
    timestamps = []
    for l in tail:
        try:
            obj = json.loads(l)
            dt = datetime.fromisoformat(obj["at"])
            timestamps.append(dt.timestamp())
        except (json.JSONDecodeError, ValueError, KeyError):
            continue
    if len(timestamps) < 2:
        return None
    span = timestamps[-1] - timestamps[0]
    if span <= 0:
        return None
    count = len(timestamps) - 1
    return (count / span) * 3600.0


def classify(before: Sample, after: Sample, elapsed: float, path: Path) -> Verdict:
    """Compare two samples and produce a verdict."""
    lines_delta = after.line_count - before.line_count
    mtime_changed = after.mtime > before.mtime

    last_ts = last_stroke_timestamp(path)
    now = time.time()
    last_age = (now - last_ts) if last_ts else None
    rate = estimate_rate(path)

    if lines_delta > 0 and mtime_changed:
        status = "active"
        detail = (
            f"{lines_delta} new line(s) in {elapsed:.1f}s, "
            f"file grew from {before.size_bytes} to {after.size_bytes} bytes"
        )
    elif mtime_changed:
        status = "idle"
        detail = (
            f"mtime updated but no new lines; "
            f"file may have been touched by another process"
        )
    else:
        status = "stale"
        age_str = f"{last_age:.0f}s ago" if last_age else "unknown"
        detail = (
            f"no change in {elapsed:.1f}s; "
            f"last stroke was {age_str}, "
            f"file has {after.line_count} lines ({after.size_bytes} bytes)"
        )

    return Verdict(
        status=status,
        lines_delta=lines_delta,
        seconds_elapsed=round(elapsed, 2),
        last_stroke_age_s=round(last_age, 1) if last_age else None,
        current_rate_per_hour=round(rate, 2) if rate else None,
        file_path=str(path),
        detail=detail,
    )


def snapshot(path: Path) -> Verdict:
    """Single-shot report without waiting for a second sample."""
    if not path.exists():
        return Verdict(
            status="missing",
            lines_delta=0,
            seconds_elapsed=0,
            last_stroke_age_s=None,
            current_rate_per_hour=None,
            file_path=str(path),
            detail=f"{path} does not exist",
        )

    s = sample_file(path)
    last_ts = last_stroke_timestamp(path)
    now = time.time()
    last_age = (now - last_ts) if last_ts else None
    rate = estimate_rate(path)

    age_str = f"{last_age:.0f}s" if last_age else "unknown"
    return Verdict(
        status="snapshot",
        lines_delta=0,
        seconds_elapsed=0,
        last_stroke_age_s=round(last_age, 1) if last_age else None,
        current_rate_per_hour=round(rate, 2) if rate else None,
        file_path=str(path),
        detail=(
            f"{s.line_count} lines, {s.size_bytes} bytes, "
            f"last stroke {age_str} ago, "
            f"rate ~{rate:.1f}/hr" if rate else "rate unknown"
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--writer", default="qwen", help="writer id (default: qwen)")
    parser.add_argument("--wait", type=int, default=15, help="seconds between samples (default: 15)")
    parser.add_argument("--snapshot", action="store_true", help="single-shot report, no wait")
    parser.add_argument("--json", action="store_true", dest="as_json", help="output JSON")
    parser.add_argument("--data-dir", default=None, help="override data directory")
    args = parser.parse_args()

    if args.data_dir:
        data_dir = Path(args.data_dir)
    else:
        repo_root = Path(__file__).resolve().parent.parent
        data_dir = repo_root / "data"

    path = data_dir / "strokes.jsonl"

    if args.snapshot:
        v = snapshot(path)
    else:
        before = sample_file(path)
        if before is None:
            v = Verdict(
                status="missing",
                lines_delta=0,
                seconds_elapsed=0,
                last_stroke_age_s=None,
                current_rate_per_hour=None,
                file_path=str(path),
                detail=f"{path} does not exist",
            )
        else:
            time.sleep(args.wait)
            after = sample_file(path)
            if after is None:
                v = Verdict(
                    status="missing",
                    lines_delta=0,
                    seconds_elapsed=args.wait,
                    last_stroke_age_s=None,
                    current_rate_per_hour=None,
                    file_path=str(path),
                    detail=f"{path} disappeared during observation",
                )
            else:
                elapsed = args.wait  # approximate; close enough
                v = classify(before, after, elapsed, path)

    if args.as_json:
        print(json.dumps(asdict(v), indent=2))
    else:
        print(f"[{v.status.upper()}] {v.detail}")
        if v.current_rate_per_hour:
            print(f"  rate: ~{v.current_rate_per_hour:.1f} strokes/hr")
        if v.last_stroke_age_s:
            print(f"  last stroke: {v.last_stroke_age_s:.0f}s ago")

    # exit code
    if v.status in ("active", "idle", "snapshot"):
        sys.exit(0)
    elif v.status == "stale":
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
