#!/usr/bin/env python3
"""Check whether a writer's pause gate has been closed too long.

The writer_loop respects a pause file (the "red gate"). The committer touches it
when tests fail, and clears it when they pass again. If the gate stays closed
past a threshold, the writer is effectively stalled even though the process is
alive — a silent failure mode worth surfacing.

Exit codes:
    0 — gate open (no pause file) or younger than threshold
    1 — gate closed longer than threshold (stale pause)
    2 — usage / environment error
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai import writer  # noqa: E402

DEFAULT_THRESHOLD_S = 600  # ten minutes


def pause_age(writer_id: str | None = None) -> float | None:
    """Return seconds since the pause file was last modified, or None if absent."""
    pf = writer.pause_file(writer_id)
    if not pf.exists():
        return None
    try:
        return time.time() - pf.stat().st_mtime
    except OSError:
        return None


def classify(age_s: float | None, threshold_s: float) -> str:
    """Return a one-word status label."""
    if age_s is None:
        return "open"
    if age_s > threshold_s:
        return "stale"
    return "paused"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--writer", default=None, help="writer id, e.g. qwen / kimi")
    ap.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD_S,
                    help="seconds before a closed gate counts as stale (default 600)")
    ap.add_argument("--json", action="store_true", help="emit a JSON line on stdout")
    args = ap.parse_args(argv)

    age = pause_age(args.writer)
    status = classify(age, args.threshold)

    if args.json:
        import json
        print(json.dumps({
            "writer": args.writer,
            "gate": status,
            "age_seconds": round(age, 1) if age is not None else None,
            "threshold_seconds": args.threshold,
        }))
    else:
        if status == "open":
            print(f"pause gate: open (no pause file)")
        elif status == "paused":
            print(f"pause gate: closed {age:.0f}s ago (within {args.threshold}s threshold)")
        else:
            print(f"pause gate: STALE — closed {age:.0f}s ago (threshold {args.threshold}s)")

    return 1 if status == "stale" else 0


if __name__ == "__main__":
    raise SystemExit(main())
