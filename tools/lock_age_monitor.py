#!/usr/bin/env python3
"""lock_age_monitor.py — detect stale .git/index.lock files.

When a git operation crashes mid-flight it can leave .git/index.lock
behind, blocking every subsequent git command.  This tool measures the
lock's age and tells you whether it's safe to remove.

Wraps iamai.lock_age_monitor.scan_lock().  See that module for full
documentation.

Exit codes:
    0 — lock found, report printed
    1 — repo not found
    2 — no lock file (clean)

Usage:
    python3 tools/lock_age_monitor.py
    python3 tools/lock_age_monitor.py --stale 60 --json
"""

import sys
from pathlib import Path

# Allow running from repo root without install
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.lock_age_monitor import main

if __name__ == "__main__":
    raise SystemExit(main())
