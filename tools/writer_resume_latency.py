#!/usr/bin/env python3
"""
writer_resume_latency.py — Measure time between writer restart and first new stroke.

After a caretaker restarts the writer, the critical metric is:
how long until the writer produces its first new stroke?

This tool:
1. Records the restart timestamp (when run_both.sh was last invoked)
2. Watches writer_state.qwen.json for the next sequence increment
3. Reports latency in seconds

Usage:
    python3 tools/writer_resume_latency.py
    python3 tools/writer_resume_latency.py --timeout 120  # give up after 120s
    python3 tools/writer_resume_latency.py --record        # just record restart time

Exit codes:
    0 — latency measured successfully
    1 — timeout (writer didn't produce a stroke in time)
    2 — file errors
"""

import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parent.parent
STATE_FILE = REPO / "data" / "writer_state.qwen.json"
LATENCY_LOG = REPO / "data" / "resume_latencies.jsonl"
RESTART_MARKER = "/tmp/iamai-restart-epoch"

WRITER_ID = os.environ.get("IAMAII_WRITER", "qwen")


def read_state():
    """Read current writer state, return (seq, at) or (None, None)."""
    try:
        data = json.loads(STATE_FILE.read_text())
        history = data.get("history", [])
        if not history:
            return None, None
        latest = history[-1]
        return latest.get("seq"), latest.get("at")
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None, None


def record_restart():
    """Write restart epoch to marker file."""
    now = time.time()
    Path(RESTART_MARKER).write_text(f"{now}\n")
    return now


def read_restart_epoch():
    """Read recorded restart time, or None."""
    try:
        return float(Path(RESTART_MARKER).read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def append_latency(restart_epoch, first_stroke_at, latency_s, seq):
    """Append a latency record to the log file."""
    record = {
        "restart_at": datetime.fromtimestamp(restart_epoch, tz=timezone.utc).isoformat(),
        "first_stroke_at": first_stroke_at,
        "latency_seconds": round(latency_s, 2),
        "seq": seq,
        "writer_id": WRITER_ID,
    }
    with open(LATENCY_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")
    return record


def measure(timeout=90):
    """Wait for the writer to produce a new stroke after restart.

    Returns (latency_seconds, seq) or raises TimeoutError.
    """
    restart_epoch = read_restart_epoch()
    if restart_epoch is None:
        # Fall back: use file mtime of the pid file
        pid_file = Path(f"/tmp/iamai-writer-{WRITER_ID}.pid")
        if pid_file.exists():
            restart_epoch = pid_file.stat().st_mtime
        else:
            print("ERROR: No restart epoch recorded. Run with --record first.",
                  file=sys.stderr)
            sys.exit(2)

    baseline_seq, _ = read_state()
    deadline = time.time() + timeout

    while time.time() < deadline:
        current_seq, current_at = read_state()
        if current_seq is not None and current_seq > (baseline_seq or -1):
            latency = time.time() - restart_epoch
            return latency, current_seq, current_at
        time.sleep(2)

    raise TimeoutError(
        f"Writer did not produce a new stroke within {timeout}s "
        f"(baseline seq={baseline_seq})"
    )


def format_report(record):
    """Human-readable summary."""
    lines = [
        f"Writer resume latency: {record['latency_seconds']}s",
        f"  Restart at:    {record['restart_at']}",
        f"  First stroke:  {record['first_stroke_at']}",
        f"  Sequence:      {record['seq']}",
        f"  Writer ID:     {record['writer_id']}",
    ]
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Measure writer resume latency")
    parser.add_argument("--timeout", type=int, default=90,
                        help="Max seconds to wait for first stroke (default: 90)")
    parser.add_argument("--record", action="store_true",
                        help="Just record restart time, don't measure")
    parser.add_argument("--last", action="store_true",
                        help="Show last recorded latency from log")
    args = parser.parse_args()

    if args.record:
        epoch = record_restart()
        print(f"Restart recorded at {epoch:.3f}")
        return

    if args.last:
        if not LATENCY_LOG.exists():
            print("No latency records found.")
            return
        lines = LATENCY_LOG.read_text().strip().split("\n")
        if not lines or not lines[-1]:
            print("No latency records found.")
            return
        record = json.loads(lines[-1])
        print(format_report(record))
        return

    try:
        latency, seq, stroke_at = measure(timeout=args.timeout)
        restart_epoch = read_restart_epoch() or time.time() - latency
        record = append_latency(restart_epoch, stroke_at, latency, seq)
        print(format_report(record))
    except TimeoutError as e:
        print(f"TIMEOUT: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
