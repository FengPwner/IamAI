#!/usr/bin/env python3
"""writer_health.py — composite health score for the automated writer.

Combines three signals into one 0-100 score:

    process_alive  (40 pts)  — is the writer process running?
    cadence_score  (30 pts)  — how close is the last-stroke gap to expected cadence?
    throughput     (30 pts)  — strokes produced in the last hour vs target

Scoring:
    90-100  healthy
    70-89   degraded (process up but cadence drifting)
    40-69   stalled  (long gap, low throughput)
    0-39    dead     (process gone or no recent activity)

Exit codes:
    0 — healthy (score >= 70)
    1 — degraded or worse (score < 70)
    2 — cannot determine (missing data)

Usage:
    python3 tools/writer_health.py
    python3 tools/writer_health.py --repo /path/to/IamAI
    python3 tools/writer_health.py --cadence 15 --window 3600
    python3 tools/writer_health.py --json
"""

from __future__ import annotations

import argparse
import json
import subprocess
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


def is_writer_alive(writer_name: str = "qwen") -> bool:
    """Check if a writer_loop process is running for the given writer."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"writer_loop.*--writer.*{writer_name}"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0 and result.stdout.strip() != ""
    except FileNotFoundError:
        return False


def get_last_stroke_time(repo: Path) -> datetime | None:
    """Read the last line of strokes.jsonl and return its timestamp."""
    strokes_path = repo / "data" / "strokes.jsonl"
    if not strokes_path.exists():
        return None

    last_line = None
    with open(strokes_path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        if size == 0:
            return None
        pos = size
        buf = b""
        while pos > 0:
            chunk = min(1024, pos)
            pos -= chunk
            f.seek(pos)
            buf = f.read(chunk) + buf
            if b"\n" in buf[:-1]:
                break
        text = buf.decode("utf-8", errors="replace")
        for line in reversed(text.strip().split("\n")):
            line = line.strip()
            if line:
                last_line = line
                break

    if not last_line:
        return None

    try:
        entry = json.loads(last_line)
        ts = entry.get("at") or entry.get("timestamp")
        if ts:
            return datetime.fromisoformat(ts)
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def count_strokes_in_window(repo: Path, window_seconds: int = 3600) -> int:
    """Count strokes in the last N seconds."""
    strokes_path = repo / "data" / "strokes.jsonl"
    if not strokes_path.exists():
        return 0

    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() - window_seconds
    count = 0

    with open(strokes_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = entry.get("at") or entry.get("timestamp")
                if ts:
                    dt = datetime.fromisoformat(ts)
                    if dt.timestamp() >= cutoff:
                        count += 1
            except (json.JSONDecodeError, ValueError):
                continue
    return count


def compute_health(
    repo: Path | None = None,
    writer_name: str = "qwen",
    cadence_seconds: int = 15,
    window_seconds: int = 3600,
) -> dict:
    """Compute the composite health score.

    Returns a dict with:
        score: int 0-100
        process_alive: bool
        last_stroke_gap: float | None  (seconds since last stroke)
        strokes_in_window: int
        cadence_score: float  (0-30)
        throughput_score: float  (0-30)
        process_score: float  (0-40)
        verdict: str  (healthy / degraded / stalled / dead)
    """
    if repo is None:
        repo = find_repo_root()

    # --- process liveness (40 pts) ---
    alive = is_writer_alive(writer_name)
    process_score = 40.0 if alive else 0.0

    # --- cadence adherence (30 pts) ---
    last_stroke = get_last_stroke_time(repo)
    now = datetime.now(timezone.utc)

    if last_stroke is not None:
        # Ensure both datetimes are timezone-aware
        if last_stroke.tzinfo is None:
            last_stroke = last_stroke.replace(tzinfo=timezone.utc)
        gap = (now - last_stroke).total_seconds()
    else:
        gap = None

    if gap is None:
        cadence_score = 0.0
    elif gap <= cadence_seconds:
        cadence_score = 30.0
    elif gap <= 2 * cadence_seconds:
        # Linear decay from 30 to 15 between 1x and 2x cadence
        ratio = (gap - cadence_seconds) / cadence_seconds
        cadence_score = 30.0 - (15.0 * ratio)
    elif gap <= 10 * cadence_seconds:
        # Linear decay from 15 to 0 between 2x and 10x cadence
        ratio = (gap - 2 * cadence_seconds) / (8 * cadence_seconds)
        cadence_score = 15.0 * (1.0 - ratio)
    else:
        cadence_score = 0.0

    # --- throughput (30 pts) ---
    strokes_in_window = count_strokes_in_window(repo, window_seconds)
    # Target: window_seconds / cadence_seconds strokes (one per cadence)
    target = window_seconds / max(cadence_seconds, 1)
    if target > 0:
        ratio = min(strokes_in_window / target, 1.0)
        throughput_score = 30.0 * ratio
    else:
        throughput_score = 0.0

    # --- composite ---
    score = int(process_score + cadence_score + throughput_score)
    score = max(0, min(100, score))

    if score >= 90:
        verdict = "healthy"
    elif score >= 70:
        verdict = "degraded"
    elif score >= 40:
        verdict = "stalled"
    else:
        verdict = "dead"

    return {
        "score": score,
        "process_alive": alive,
        "last_stroke_gap": round(gap, 1) if gap is not None else None,
        "strokes_in_window": strokes_in_window,
        "process_score": round(process_score, 1),
        "cadence_score": round(cadence_score, 1),
        "throughput_score": round(throughput_score, 1),
        "verdict": verdict,
        "cadence_seconds": cadence_seconds,
        "window_seconds": window_seconds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Writer health score")
    parser.add_argument("--repo", type=Path, default=None, help="repo root")
    parser.add_argument("--writer", default="qwen", help="writer name")
    parser.add_argument("--cadence", type=int, default=15, help="expected cadence (seconds)")
    parser.add_argument("--window", type=int, default=3600, help="throughput window (seconds)")
    parser.add_argument("--json", action="store_true", help="output JSON")
    args = parser.parse_args()

    repo = args.repo or find_repo_root()
    if not (repo / "data" / "strokes.jsonl").exists():
        if args.json:
            print(json.dumps({"error": "no strokes.jsonl", "score": 0}))
        else:
            print("ERROR: cannot find data/strokes.jsonl", file=sys.stderr)
        return 2

    result = compute_health(
        repo=repo,
        writer_name=args.writer,
        cadence_seconds=args.cadence,
        window_seconds=args.window,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"writer health: {result['score']}/100  [{result['verdict']}]")
        print(f"  process:     {'alive' if result['process_alive'] else 'DEAD'}  ({result['process_score']}/40)")
        gap_str = f"{result['last_stroke_gap']}s" if result['last_stroke_gap'] is not None else "unknown"
        print(f"  cadence:     gap={gap_str}  ({result['cadence_score']}/30)")
        print(f"  throughput:  {result['strokes_in_window']} strokes/{args.window}s  ({result['throughput_score']}/30)")

    return 0 if result["score"] >= 70 else 1


if __name__ == "__main__":
    sys.exit(main())
