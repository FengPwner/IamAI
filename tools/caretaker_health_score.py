#!/usr/bin/env python3
"""CLI: caretaker_health_score — composite health metric for IamAI system.

Usage:
    python3 tools/caretaker_health_score.py           # human-readable
    python3 tools/caretaker_health_score.py --json   # machine-readable

Exit codes:
    0  healthy (score >= 80)
    1  degraded (score 60-79)
    2  critical (score < 60)
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.caretaker_health_score import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
