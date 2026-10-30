#!/usr/bin/env python3
"""CLI wrapper for iamai.stall_classifier — diagnose writer stalls.

Reads writer state and stroke data to classify the current/recent stall.

Usage:
    python3 tools/stall_classifier.py                    # classify current state
    python3 tools/stall_classifier.py --json             # JSON output
    python3 tools/stall_classifier.py --history 10       # last 10 gaps

Exit codes:
    0  classification complete
    1  insufficient data
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stall_classifier import classify_stall, classify_stalls_batch, summarise  # noqa: E402

GMT8 = timezone(timedelta(hours=8))


def _gather_evidence(writer: str = "qwen") -> dict:
    """Gather observable signals from the running system."""
    evidence: dict = {}

    # --- stroke gap ---
    strokes_path = REPO / "data" / "strokes.jsonl"
    last_ts: float | None = None
    prev_ts: float | None = None
    stroke_count = 0
    intervals: list[float] = []

    if strokes_path.exists():
        lines = strokes_path.read_text().strip().splitlines()
        for line in lines[-50:]:
            try:
                rec = json.loads(line)
                ts = rec.get("at_ts") or rec.get("ts")
                if ts:
                    if prev_ts:
                        intervals.append(ts - prev_ts)
                    prev_ts = last_ts
                    last_ts = ts
                    stroke_count += 1
            except (json.JSONDecodeError, KeyError):
                continue

    if intervals:
        sorted_iv = sorted(intervals)
        modal = sorted_iv[len(sorted_iv) // 2]  # rough median as modal proxy
    else:
        modal = 400.0  # default cadence ~15 strokes / 100 min

    now_ts = datetime.now(timezone.utc).timestamp()
    gap = (now_ts - last_ts) if last_ts else 0
    evidence["gap_seconds"] = gap
    evidence["modal_interval"] = modal

    # --- process alive ---
    def _proc_running(name: str) -> bool:
        try:
            out = subprocess.check_output(
                ["pgrep", "-f", name], stderr=subprocess.DEVNULL
            )
            return len(out.strip()) > 0
        except subprocess.CalledProcessError:
            return False

    evidence["process_alive"] = _proc_running(f"writer_loop.*--writer {writer}")
    evidence["batch_alive"] = _proc_running(f"commit_batch.*--writer {writer}")

    # --- lock file ---
    lock_path = REPO / ".git" / "index.lock"
    evidence["lock_present"] = lock_path.exists()

    # --- hour in GMT+8 ---
    evidence["hour_gmt8"] = datetime.now(GMT8).hour

    # --- disk usage ---
    try:
        st = os.statvfs(str(REPO))
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        used_pct = ((total - free) / total * 100) if total else 0
        evidence["disk_usage_pct"] = round(used_pct, 1)
    except OSError:
        evidence["disk_usage_pct"] = 0

    # --- dmesg OOM (best-effort) ---
    try:
        dmesg = subprocess.check_output(
            ["dmesg", "--time-format=iso", "-T"],
            stderr=subprocess.DEVNULL, timeout=3
        ).decode(errors="replace")
        evidence["dmesg_oom"] = "oom-killer" in dmesg.lower()[-2000:]
    except Exception:
        evidence["dmesg_oom"] = False

    evidence["io_errors"] = False
    evidence["abrupt_last_stroke"] = gap > 3 * modal
    evidence["commit_gap_exceeds_stroke_gap"] = False  # needs git log parsing

    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify writer stalls")
    parser.add_argument("--writer", default="qwen", help="writer name")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument(
        "--history", type=int, default=0,
        help="show last N gap classifications (requires stroke log)"
    )
    args = parser.parse_args()

    evidence = _gather_evidence(args.writer)

    if args.json:
        result = classify_stall(evidence)
        result["evidence"] = evidence
        print(json.dumps(result, indent=2))
        return 0

    result = classify_stall(evidence)

    print("=== Stall Classification ===")
    print(f"  label:      {result['label']}")
    print(f"  confidence: {result['confidence']:.2f}")
    print(f"  reasons:    {', '.join(result['reasons']) or 'none'}")
    print()
    print("  evidence:")
    for k, v in sorted(evidence.items()):
        print(f"    {k}: {v}")
    print()
    print("  all scores:")
    for cat, score in sorted(result["scores"].items(), key=lambda x: -x[1]):
        marker = " ←" if cat == result["label"] else ""
        print(f"    {cat}: {score:.2f}{marker}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
