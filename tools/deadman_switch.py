#!/usr/bin/env python3
"""deadman_switch.py — write a heartbeat timestamp every tick so that even
if the writer dies without cleanup, the next observer can tell exactly when.

The file /tmp/iamai-deadman-{writer}.json is updated atomically on each call.
An external observer (caretaker, cron, CI) reads it and compares the timestamp
against the current time to decide whether the writer is stale.

Usage (called from writer_loop.py on each tick, or standalone):
    python3 tools/deadman_switch.py --writer qwen
    python3 tools/deadman_switch.py --writer qwen --check --max-age 300

Exit codes:
    0  — heartbeat fresh (or successfully written)
    1  — heartbeat stale (check mode)
    2  — heartbeat file missing or corrupt (check mode)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path


def deadman_path(writer: str) -> Path:
    return Path(f"/tmp/iamai-deadman-{writer}.json")


def write_heartbeat(writer: str, extra: dict | None = None) -> Path:
    """Write an atomic heartbeat timestamp. Returns the path written to."""
    path = deadman_path(writer)
    payload = {
        "writer": writer,
        "pid": os.getpid(),
        "timestamp": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.gmtime()),
    }
    if extra:
        payload.update(extra)

    # Atomic write: write to temp file in same dir, then rename.
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def check_heartbeat(writer: str, max_age_seconds: int) -> int:
    """Check freshness of the dead man's switch. Returns exit code."""
    path = deadman_path(writer)
    if not path.exists():
        print(f"DEAD: no heartbeat file at {path}")
        return 2

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"DEAD: corrupt heartbeat file: {exc}")
        return 2

    ts = data.get("timestamp", 0)
    age = time.time() - ts
    iso = data.get("iso", "unknown")
    pid = data.get("pid", "?")

    if age > max_age_seconds:
        print(
            f"STALE: last heartbeat {age:.0f}s ago ({iso}, pid {pid}), "
            f"threshold {max_age_seconds}s"
        )
        return 1

    print(
        f"ALIVE: last heartbeat {age:.0f}s ago ({iso}, pid {pid}), "
        f"threshold {max_age_seconds}s"
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--writer", default=os.environ.get("IAMAII_WRITER", "qwen"))
    ap.add_argument(
        "--check",
        action="store_true",
        help="check freshness instead of writing",
    )
    ap.add_argument(
        "--max-age",
        type=int,
        default=300,
        help="max age in seconds before heartbeat is considered stale (default 300)",
    )
    args = ap.parse_args()

    if args.check:
        return check_heartbeat(args.writer, args.max_age)

    path = write_heartbeat(args.writer)
    print(f"heartbeat written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
