#!/usr/bin/env python3
"""Cadence watchdog — detects when the writer has gone silent.

The writer produces strokes at a configured interval (default 15s).
When the gap between the last stroke and now exceeds a configurable
threshold (default: 2× the stroke interval), the watchdog flags a stall.

This is distinct from cadence_stall_detector.py, which analyzes historical
stroke timestamps in data/strokes.jsonl. This module is a lightweight,
real-time health check designed to be called by:
  - the caretaker loop (pre-flight check)
  - the batch committer (post-commit sanity check)
  - external monitoring (cron, dashboard)

Usage:
    from cadence_watchdog import check_cadence, CadenceStatus
    status = check_cadence(writer="qwen", stroke_interval=15, threshold_factor=2.0)
    if status.stalled:
        print(f"writer stalled: {status.gap_seconds}s since last stroke")

CLI:
    python3 tools/cadence_watchdog.py --writer qwen
    python3 tools/cadence_watchdog.py --writer qwen --interval 15 --threshold 2.0 --json

Exit codes:
    0 - writer is healthy (within cadence)
    1 - writer is stalled (gap exceeds threshold)
    2 - unable to determine (no state file, no strokes, etc.)
"""

import json
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class CadenceStatus:
    """Result of a cadence health check."""
    writer: str
    healthy: bool
    stalled: bool
    gap_seconds: Optional[float]
    threshold_seconds: float
    stroke_interval: float
    last_stroke_time: Optional[float]
    reason: str
    strokes_count: Optional[int] = None
    source: str = ""  # how we determined the last stroke time

    @property
    def is_unknown(self) -> bool:
        return not self.healthy and not self.stalled


def _get_last_stroke_from_state(repo_path: str, writer: str) -> tuple[Optional[float], str]:
    """Try to get last stroke time from writer state file."""
    state_file = Path(repo_path) / "data" / f"writer_state.{writer}.json"
    if not state_file.exists():
        return None, "no state file"
    try:
        data = json.loads(state_file.read_text())
        ts = data.get("last_stroke_time") or data.get("last_write_time")
        if ts:
            return float(ts), f"state file ({state_file.name})"
        return None, "state file has no timestamp"
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        return None, f"state file parse error: {e}"


def _get_last_stroke_from_jsonl(repo_path: str) -> tuple[Optional[float], int, str]:
    """Try to get last stroke time from strokes.jsonl (append-only log)."""
    jsonl = Path(repo_path) / "data" / "strokes.jsonl"
    if not jsonl.exists():
        return None, 0, "no strokes.jsonl"
    try:
        lines = jsonl.read_text().strip().split("\n")
        count = len([l for l in lines if l.strip()])
        if count == 0:
            return None, 0, "empty strokes.jsonl"
        last_line = lines[-1]
        entry = json.loads(last_line)
        ts = entry.get("timestamp") or entry.get("time") or entry.get("ts")
        if ts:
            return float(ts), count, f"strokes.jsonl (last of {count} entries)"
        return None, count, "strokes.jsonl last entry has no timestamp"
    except (json.JSONDecodeError, ValueError, IndexError) as e:
        return None, 0, f"strokes.jsonl parse error: {e}"


def _get_last_stroke_from_git(repo_path: str) -> tuple[Optional[float], str]:
    """Fallback: use git log to find the most recent stroke-related commit."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", "data/strokes.jsonl"],
            capture_output=True, text=True, timeout=10, cwd=repo_path,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip()), "git log (strokes.jsonl)"
        return None, "git log returned nothing"
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError, OSError) as e:
        return None, f"git log error: {e}"


def check_cadence(
    writer: str = "qwen",
    stroke_interval: float = 15.0,
    threshold_factor: float = 2.0,
    repo_path: str = ".",
    now: Optional[float] = None,
) -> CadenceStatus:
    """Check whether the writer is producing strokes within expected cadence.

    Args:
        writer: writer id (used to locate state file)
        stroke_interval: expected seconds between strokes
        threshold_factor: multiplier on interval to define a stall
        repo_path: path to the IamAI repository root
        now: override for current time (for testing)

    Returns:
        CadenceStatus with healthy/stalled/unknown determination
    """
    if now is None:
        now = time.time()

    threshold = stroke_interval * threshold_factor

    # Try sources in priority order
    last_ts, source = _get_last_stroke_from_state(repo_path, writer)
    strokes_count = None

    if last_ts is None:
        last_ts, strokes_count, source = _get_last_stroke_from_jsonl(repo_path)

    if last_ts is None:
        last_ts, source = _get_last_stroke_from_git(repo_path)

    if last_ts is None:
        return CadenceStatus(
            writer=writer,
            healthy=False,
            stalled=False,
            gap_seconds=None,
            threshold_seconds=threshold,
            stroke_interval=stroke_interval,
            last_stroke_time=None,
            reason=f"cannot determine last stroke time: {source}",
            strokes_count=strokes_count,
            source=source,
        )

    gap = now - last_ts

    if gap <= threshold:
        return CadenceStatus(
            writer=writer,
            healthy=True,
            stalled=False,
            gap_seconds=round(gap, 1),
            threshold_seconds=threshold,
            stroke_interval=stroke_interval,
            last_stroke_time=last_ts,
            reason=f"writer active, last stroke {gap:.0f}s ago (threshold {threshold:.0f}s)",
            strokes_count=strokes_count,
            source=source,
        )
    else:
        return CadenceStatus(
            writer=writer,
            healthy=False,
            stalled=True,
            gap_seconds=round(gap, 1),
            threshold_seconds=threshold,
            stroke_interval=stroke_interval,
            last_stroke_time=last_ts,
            reason=f"writer stalled: {gap:.0f}s since last stroke (threshold {threshold:.0f}s)",
            strokes_count=strokes_count,
            source=source,
        )


def check_process_alive(writer: str = "qwen") -> dict:
    """Check if writer and batch processes are running via pid files."""
    result = {"writer_alive": False, "batch_alive": False, "writer_pid": None, "batch_pid": None}

    for role in ("writer", "batch"):
        pid_file = Path(f"/tmp/iamai-{role}-{writer}.pid")
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                result[f"{role}_pid"] = pid
                # signal 0 tests existence without killing
                import os
                os.kill(pid, 0)
                result[f"{role}_alive"] = True
            except (ValueError, ProcessLookupError, PermissionError):
                pass

    return result


def full_health_check(
    writer: str = "qwen",
    stroke_interval: float = 15.0,
    threshold_factor: float = 2.0,
    repo_path: str = ".",
    now: Optional[float] = None,
) -> dict:
    """Combined health check: cadence + process status.

    Returns a dict with:
      - cadence: CadenceStatus as dict
      - process: process alive status
      - overall: 'healthy' | 'stalled' | 'unknown'
      - recommendation: what to do next
    """
    cadence = check_cadence(writer, stroke_interval, threshold_factor, repo_path, now)
    process = check_process_alive(writer)

    if cadence.healthy and process["writer_alive"] and process["batch_alive"]:
        overall = "healthy"
        recommendation = "no action needed"
    elif cadence.stalled and not process["writer_alive"]:
        overall = "stalled"
        recommendation = "restart writer and batch via run_both.sh"
    elif cadence.stalled and process["writer_alive"]:
        overall = "stalled"
        recommendation = "writer process alive but not producing — check logs, possible deadlock"
    elif cadence.is_unknown:
        overall = "unknown"
        recommendation = "cannot assess health — verify state files exist"
    else:
        # healthy cadence but process not detected (pid file missing/stale)
        overall = "healthy"
        recommendation = "writer producing strokes but pid file missing — stale pid, process may have restarted outside pid tracking"

    return {
        "cadence": asdict(cadence),
        "process": process,
        "overall": overall,
        "recommendation": recommendation,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="IamAI cadence watchdog")
    parser.add_argument("--writer", default="qwen", help="writer id")
    parser.add_argument("--interval", type=float, default=15.0, help="expected stroke interval in seconds")
    parser.add_argument("--threshold", type=float, default=2.0, help="stall threshold as multiplier of interval")
    parser.add_argument("--repo", default=".", help="path to IamAI repo root")
    parser.add_argument("--json", action="store_true", help="output as JSON")
    parser.add_argument("--full", action="store_true", help="include process status")
    args = parser.parse_args()

    if args.full:
        result = full_health_check(args.writer, args.interval, args.threshold, args.repo)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            c = result["cadence"]
            print(f"cadence:  {c['reason']}")
            print(f"process:  writer={'alive' if result['process']['writer_alive'] else 'dead'}  batch={'alive' if result['process']['batch_alive'] else 'dead'}")
            print(f"overall:  {result['overall']}")
            print(f"action:   {result['recommendation']}")
        sys.exit(0 if result["overall"] == "healthy" else 1)
    else:
        status = check_cadence(args.writer, args.interval, args.threshold, args.repo)
        if args.json:
            print(json.dumps(asdict(status), indent=2))
        else:
            print(status.reason)
        sys.exit(0 if status.healthy else (1 if status.stalled else 2))


if __name__ == "__main__":
    main()
