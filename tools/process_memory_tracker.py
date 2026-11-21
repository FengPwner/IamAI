#!/usr/bin/env python3
"""process_memory_tracker.py — track RSS of writer/batch processes over time.

Memory leaks in long-running daemon processes are the silent killer:
the process stays "running" (liveness checks pass), the PID file is
fresh (uptime looks fine), but RSS creeps upward until the container
OOM-killer intervenes.  By the time that happens, the evidence is gone.

This tool reads /proc/<pid>/status to capture current RSS, appends a
timestamped row to a JSONL history file, and classifies the trend:

  - **stable:**   RSS change < 5% over the observation window
  - **growing:**  monotonic increase across ≥ 3 consecutive samples
  - **leaking:**  growth > 50% from the first sample AND trend is
                  consistently upward
  - **shrinking:** RSS is decreasing (GC kicked in, or pages reclaimed)

The history file lives at  ``data/memory_history.<writer>.jsonl``
(one JSON object per line:  ``{"ts", "role", "pid", "rss_kb"}``).

When called with ``--check``, the tool exits non-zero if either
process is classified as *leaking* — suitable for use as a pre-commit
gate or watchdog probe.

Usage:
    python3 tools/process_memory_tracker.py
    python3 tools/process_memory_tracker.py --writer qwen --check
    python3 tools/process_memory_tracker.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai import writer  # noqa: E402

# Classification thresholds
GROWTH_CONSECUTIVE_MIN = 3          # samples needed to call "growing"
LEAK_PCT = 0.50                     # 50 % growth from first sample
STABLE_PCT = 0.05                   # 5 % band for "stable"

# Status labels
STABLE = "stable"
GROWING = "growing"
LEAKING = "leaking"
SHRINKING = "shrinking"
UNKNOWN = "unknown"


def read_pid(writer_id: str | None, role: str) -> int | None:
    """Read PID from the pidfile for the given writer and role."""
    if role == "writer":
        pf = writer.pid_file(writer_id)
    elif role == "batch":
        pf = writer.batch_pid_file(writer_id)
    else:
        return None
    if not pf.exists():
        return None
    try:
        return int(pf.read_text().strip())
    except (ValueError, OSError):
        return None


def read_rss_kb(pid: int) -> int | None:
    """Read VmRSS from /proc/<pid>/status.  Returns kilobytes or None."""
    status = Path(f"/proc/{pid}/status")
    if not status.exists():
        return None
    try:
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                # Format: "VmRSS:    12345 kB"
                parts = line.split()
                return int(parts[1])
    except (IndexError, ValueError, OSError):
        pass
    return None


def history_path(writer_id: str | None) -> Path:
    """Return the JSONL history file path for a writer."""
    suffix = writer_id or "default"
    return REPO / "data" / f"memory_history.{suffix}.jsonl"


def load_history(writer_id: str | None, role: str, limit: int = 0) -> list[dict]:
    """Load history rows for `role` from the JSONL file.

    If `limit` > 0, return only the last `limit` rows.
    """
    hp = history_path(writer_id)
    if not hp.exists():
        return []
    rows = []
    for line in hp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if obj.get("role") == role:
                rows.append(obj)
        except json.JSONDecodeError:
            continue
    if limit > 0:
        rows = rows[-limit:]
    return rows


def append_sample(writer_id: str | None, role: str, pid: int, rss_kb: int) -> dict:
    """Append one sample to the history file and return the row."""
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "role": role,
        "pid": pid,
        "rss_kb": rss_kb,
    }
    hp = history_path(writer_id)
    hp.parent.mkdir(parents=True, exist_ok=True)
    with open(hp, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row


def classify_trend(samples: list[dict]) -> dict:
    """Classify the memory trend from a list of samples.

    Returns a dict with keys: status, first_kb, last_kb, pct_change,
    sample_count.
    """
    n = len(samples)
    if n < 2:
        return {
            "status": UNKNOWN,
            "first_kb": samples[0]["rss_kb"] if samples else None,
            "last_kb": samples[-1]["rss_kb"] if samples else None,
            "pct_change": 0.0,
            "sample_count": n,
        }

    first_kb = samples[0]["rss_kb"]
    last_kb = samples[-1]["rss_kb"]

    if first_kb == 0:
        pct_change = 0.0
    else:
        pct_change = (last_kb - first_kb) / first_kb

    # Check for consecutive increases
    consecutive_up = 0
    max_consecutive_up = 0
    for i in range(1, n):
        if samples[i]["rss_kb"] > samples[i - 1]["rss_kb"]:
            consecutive_up += 1
            max_consecutive_up = max(max_consecutive_up, consecutive_up)
        else:
            consecutive_up = 0

    # Shrinking
    if pct_change < -STABLE_PCT:
        status = SHRINKING
    # Leaking: large growth AND sustained monotonic increase
    elif pct_change > LEAK_PCT and max_consecutive_up >= GROWTH_CONSECUTIVE_MIN:
        status = LEAKING
    # Growing: any monotonic run of GROWTH_CONSECUTIVE_MIN+
    elif max_consecutive_up >= GROWTH_CONSECUTIVE_MIN:
        status = GROWING
    # Stable
    elif abs(pct_change) <= STABLE_PCT:
        status = STABLE
    else:
        status = STABLE  # moderate change without sustained trend

    return {
        "status": status,
        "first_kb": first_kb,
        "last_kb": last_kb,
        "pct_change": round(pct_change * 100, 2),
        "sample_count": n,
    }


def format_kb(kb: int) -> str:
    """Format kilobytes as a human-readable string."""
    if kb is None:
        return "?"
    if kb < 1024:
        return f"{kb} KB"
    mb = kb / 1024
    if mb < 1024:
        return f"{mb:.1f} MB"
    return f"{mb / 1024:.1f} GB"


def sample_process(writer_id: str | None, role: str) -> dict:
    """Read current RSS and append to history.  Returns a status dict."""
    pid = read_pid(writer_id, role)
    if pid is None:
        return {"role": role, "running": False, "pid": None,
                "rss_kb": None, "rss_str": "not running",
                "trend": {"status": UNKNOWN, "sample_count": 0}}

    rss = read_rss_kb(pid)
    if rss is None:
        return {"role": role, "running": False, "pid": pid,
                "rss_kb": None, "rss_str": "stale pid",
                "trend": {"status": UNKNOWN, "sample_count": 0}}

    append_sample(writer_id, role, pid, rss)
    history = load_history(writer_id, role, limit=50)
    trend = classify_trend(history)

    return {
        "role": role,
        "running": True,
        "pid": pid,
        "rss_kb": rss,
        "rss_str": format_kb(rss),
        "trend": trend,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--writer", default=None,
                    help="writer id, e.g. qwen / kimi (or env IAMAI_WRITER)")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if any process is classified as leaking")
    ap.add_argument("--json", action="store_true", help="emit JSON output")
    args = ap.parse_args()

    wid = args.writer or os.environ.get("IAMAI_WRITER")
    results = [
        sample_process(wid, "writer"),
        sample_process(wid, "batch"),
    ]

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            if not r["running"]:
                print(f"  {r['role']:>8}: {r['rss_str']}")
                continue
            t = r["trend"]
            trend_str = (
                f"{t['status']}  "
                f"({t['sample_count']} samples, "
                f"{t['pct_change']:+.1f}% from {format_kb(t['first_kb'])})"
            )
            print(f"  {r['role']:>8}: pid={r['pid']}  "
                  f"RSS={r['rss_str']}  [{trend_str}]")

    if args.check:
        leaking = [r for r in results
                   if r.get("trend", {}).get("status") == LEAKING]
        if leaking:
            roles = ", ".join(r["role"] for r in leaking)
            print(f"\n  LEAK DETECTED: {roles}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
