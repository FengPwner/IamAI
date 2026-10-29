#!/usr/bin/env python3
"""key_age_monitor — check SSH deploy key age and warn before expiry.

The IamAI repo uses a deploy key pushed to GitHub for automated commits.
If the key is compromised or the machine is recycled, the key should be
rotated. This tool tracks how old the key file is and warns when it
exceeds a configurable threshold.

Usage:
    python3 tools/key_age_monitor.py                  # default thresholds
    python3 tools/key_age_monitor.py --warn 30 --critical 60
    python3 tools/key_age_monitor.py --json           # machine-readable

Exit codes:
    0 = key is fresh (under warn threshold)
    1 = key is aging (warn ≤ age < critical) or expired (age ≥ critical)
    2 = key file not found or unreadable
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import NamedTuple, Optional


REPO = Path(__file__).resolve().parent.parent

# Default key search order
KEY_CANDIDATES = [
    REPO / ".ssh" / "deploy_key",
    Path("/tmp/ssh_deploy_key"),
    REPO / ".ssh" / "id_ed25519",
    REPO / ".ssh" / "id_rsa",
]

DEFAULT_WARN_DAYS = 14
DEFAULT_CRITICAL_DAYS = 30


class KeyStatus(NamedTuple):
    path: str
    age_days: float
    mtime_epoch: float
    level: str  # "fresh" | "warn" | "critical" | "missing"
    detail: str


def find_key(paths=None) -> Optional[Path]:
    """Return the first existing key path, or None."""
    candidates = paths or KEY_CANDIDATES
    for p in candidates:
        if Path(p).is_file():
            return Path(p)
    return None


def check_key_age(
    key_path: Path,
    warn_days: int = DEFAULT_WARN_DAYS,
    critical_days: int = DEFAULT_CRITICAL_DAYS,
    now: float = None,
) -> KeyStatus:
    """Check how old a key file is and return a status."""
    if now is None:
        now = time.time()

    if not key_path.is_file():
        return KeyStatus(
            path=str(key_path),
            age_days=-1,
            mtime_epoch=0,
            level="missing",
            detail=f"key not found: {key_path}",
        )

    try:
        mtime = os.path.getmtime(key_path)
    except OSError as e:
        return KeyStatus(
            path=str(key_path),
            age_days=-1,
            mtime_epoch=0,
            level="missing",
            detail=f"cannot stat {key_path}: {e}",
        )

    age_seconds = now - mtime
    age_days = age_seconds / 86400

    if age_days >= critical_days:
        level = "critical"
        detail = (
            f"key is {age_days:.1f} days old (≥{critical_days}d critical); "
            "rotate immediately"
        )
    elif age_days >= warn_days:
        level = "warn"
        detail = (
            f"key is {age_days:.1f} days old (≥{warn_days}d warn); "
            "plan rotation soon"
        )
    else:
        level = "fresh"
        detail = f"key is {age_days:.1f} days old; no action needed"

    return KeyStatus(
        path=str(key_path),
        age_days=round(age_days, 2),
        mtime_epoch=mtime,
        level=level,
        detail=detail,
    )


def format_status(status: KeyStatus, as_json: bool = False) -> str:
    if as_json:
        return json.dumps(
            {
                "path": status.path,
                "age_days": status.age_days,
                "mtime_epoch": status.mtime_epoch,
                "level": status.level,
                "detail": status.detail,
            },
            indent=2,
        )
    return f"[{status.level.upper():>8}] {status.detail}"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check SSH deploy key age"
    )
    parser.add_argument(
        "--warn",
        type=int,
        default=DEFAULT_WARN_DAYS,
        help=f"warn threshold in days (default {DEFAULT_WARN_DAYS})",
    )
    parser.add_argument(
        "--critical",
        type=int,
        default=DEFAULT_CRITICAL_DAYS,
        help=f"critical threshold in days (default {DEFAULT_CRITICAL_DAYS})",
    )
    parser.add_argument(
        "--key",
        type=str,
        default=None,
        help="explicit key path (overrides search)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="machine-readable JSON output",
    )
    args = parser.parse_args(argv)

    if args.key:
        key_path = Path(args.key)
        if not key_path.is_file():
            msg = f"specified key not found: {key_path}"
            if args.json:
                print(json.dumps({"error": msg, "level": "missing"}))
            else:
                print(f"[MISSING] {msg}", file=sys.stderr)
            return 2
    else:
        key_path = find_key()
        if key_path is None:
            msg = "no deploy key found in search paths"
            if args.json:
                print(json.dumps({"error": msg, "level": "missing"}))
            else:
                print(f"[MISSING] {msg}", file=sys.stderr)
            return 2

    status = check_key_age(key_path, args.warn, args.critical)
    print(format_status(status, as_json=args.json))

    return 0 if status.level in ("fresh",) else 1


if __name__ == "__main__":
    sys.exit(main())
