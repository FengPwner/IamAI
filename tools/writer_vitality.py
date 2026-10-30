#!/usr/bin/env python3
"""CLI wrapper for iamai.writer_vitality — composite health index.

Reads live signals from the running system and produces a single
0–100 vitality score summarising writer health.

Usage:
    python3 tools/writer_vitality.py                # human-readable
    python3 tools/writer_vitality.py --json          # JSON output
    python3 tools/writer_vitality.py --cadence 15    # custom cadence

Exit codes:
    0  report generated
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Import from the library module — all logic lives there.
from iamai.writer_vitality import (  # noqa: E402
    DEFAULT_CADENCE,
    main as _lib_main,
    vitality,
    vitality_report,
)


def main() -> None:
    _lib_main()


if __name__ == "__main__":
    main()
