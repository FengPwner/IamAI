#!/usr/bin/env python3
"""CLI: tree_age — measure file-age distribution across the repository.

Usage:
    python3 tools/tree_age.py                  # human-readable summary
    python3 tools/tree_age.py --json           # machine-readable
    python3 tools/tree_age.py --trend 20       # show decay trend over 20 commits
    python3 tools/tree_age.py --stale-days 14  # custom stale threshold

Exit codes:
    0  always
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.tree_age import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
