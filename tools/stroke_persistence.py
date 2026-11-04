#!/usr/bin/env python3
"""CLI: stroke_persistence — measure continuous stroke production uptime.

Usage:
    python3 tools/stroke_persistence.py                  # human-readable
    python3 tools/stroke_persistence.py --json           # machine-readable
    python3 tools/stroke_persistence.py --threshold 300  # 5-min gap threshold
    python3 tools/stroke_persistence.py --all            # show all historical streaks

Exit codes:
    0  active streak (writer producing continuously)
    1  broken streak (gap exceeded threshold)
    2  dormant (no data available)
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_persistence import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
