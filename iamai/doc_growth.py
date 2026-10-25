"""Track growth rate of key documentation files and predict compaction needs.

Several IamAI files grow monotonically — ``docs/DEVLOG.md``,
``docs/GARDEN.md``, ``data/strokes.jsonl`` and the notes files.
Eventually they become unwieldy (slow editor loads, large diffs,
cloned-repo bloat).  This module measures current size, recent growth
rate, and estimates when each file will cross a configurable threshold.

Usage::

    from iamai.doc_growth import scan_growth, growth_report

    results = scan_growth(repo)
    for r in results:
        print(r["path"], r["size_kb"], r["bytes_per_hour"])

    print(growth_report(repo))

Design choices
--------------

- **Two-sample rate estimation.**  Compares current file sizes against
  a recent ``git log`` snapshot to estimate bytes-per-hour without
  needing historical state files.
- **Configurable threshold.**  Default compaction threshold is 1 MB —
  large enough to avoid premature rotation, small enough to catch
  bloat before it impacts clone times.
- **Pure functions.**  All helpers accept paths and return dicts;
  no global state, no file writes.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Files tracked for growth monitoring.
TRACKED_FILES: list[str] = [
    "docs/DEVLOG.md",
    "docs/GARDEN.md",
    "docs/METRICS.md",
    "data/strokes.jsonl",
    "notes/conventions.md",
    "notes/history.md",
    "notes/limits.md",
    "notes/reading.md",
]

# Default compaction threshold in bytes (1 MB).
DEFAULT_THRESHOLD: int = 1_000_000

# Lookback window for growth-rate estimation (hours).
DEFAULT_LOOKBACK_HOURS: float = 6.0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _file_size(repo: Path, relpath: str) -> int:
    """Return current file size in bytes, or -1 if missing."""
    p = repo / relpath
    if p.is_file():
        return p.stat().st_size
    return -1


def _git_file_size_at(repo: Path, relpath: str, ref: str) -> int:
    """Return file size at a given git ref, or -1 if unavailable."""
    try:
        result = subprocess.run(
            ["git", "cat-file", "-s", f"{ref}:{relpath}"],
            capture_output=True,
            text=True,
            cwd=str(repo),
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip().isdigit():
            return int(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return -1


def _find_ref_at(repo: Path, hours_ago: float) -> str | None:
    """Find the git ref closest to *hours_ago* hours in the past."""
    since = (
        datetime.now(timezone.utc).timestamp() - hours_ago * 3600
    )
    try:
        result = subprocess.run(
            [
                "git", "log", "--format=%H %at",
                f"--since=@{int(since)}",
                "--reverse",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo),
            timeout=10,
        )
        lines = result.stdout.strip().splitlines()
        if lines:
            # First commit after the since cutoff
            return lines[0].split()[0]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


# ---------------------------------------------------------------------------
# core API
# ---------------------------------------------------------------------------

def scan_growth(
    repo: Path,
    *,
    threshold: int = DEFAULT_THRESHOLD,
    lookback_hours: float = DEFAULT_LOOKBACK_HOURS,
    files: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Scan tracked files and return growth info for each.

    Returns a list of dicts with keys:

    - ``path``: relative file path
    - ``size_bytes``: current size (-1 if missing)
    - ``size_kb``: current size in KB (rounded)
    - ``old_size_bytes``: size at lookback ref (-1 if unavailable)
    - ``growth_bytes``: bytes added during lookback window
    - ``bytes_per_hour``: estimated growth rate
    - ``pct_of_threshold``: current size as % of threshold
    - ``hours_to_threshold``: estimated hours until threshold (None if
      shrinking or missing data)
    - ``needs_compaction``: True if current size >= threshold
    """
    tracked = files or TRACKED_FILES
    ref = _find_ref_at(repo, lookback_hours)
    results: list[dict[str, Any]] = []

    for relpath in tracked:
        cur = _file_size(repo, relpath)
        old = _git_file_size_at(repo, relpath, ref) if ref else -1

        growth = cur - old if (cur >= 0 and old >= 0) else -1
        rate = growth / lookback_hours if growth >= 0 else -1.0

        pct = (cur / threshold * 100) if cur >= 0 else -1.0
        needs = cur >= threshold if cur >= 0 else False

        hours_to = None
        if rate > 0 and cur >= 0 and cur < threshold:
            hours_to = (threshold - cur) / rate

        results.append(
            {
                "path": relpath,
                "size_bytes": cur,
                "size_kb": round(cur / 1024, 1) if cur >= 0 else -1,
                "old_size_bytes": old,
                "growth_bytes": growth,
                "bytes_per_hour": round(rate, 1) if rate >= 0 else -1,
                "pct_of_threshold": round(pct, 1),
                "hours_to_threshold": (
                    round(hours_to, 1) if hours_to is not None else None
                ),
                "needs_compaction": needs,
            }
        )

    return results


def growth_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate summary from scan_growth results."""
    total_kb = sum(
        r.get("size_kb", -1) for r in results if r.get("size_kb", -1) >= 0
    )
    needs_compaction = [
        r.get("path", "?") for r in results if r.get("needs_compaction")
    ]
    fastest = max(
        (r for r in results if r.get("bytes_per_hour", -1) >= 0),
        key=lambda r: r.get("bytes_per_hour", -1),
        default=None,
    )
    soonest = min(
        (
            r
            for r in results
            if r.get("hours_to_threshold") is not None
        ),
        key=lambda r: r["hours_to_threshold"],
        default=None,
    )

    return {
        "total_tracked_kb": round(total_kb, 1),
        "files_needing_compaction": needs_compaction,
        "fastest_growing": (
            fastest["path"] if fastest else None
        ),
        "fastest_rate_bph": (
            fastest["bytes_per_hour"] if fastest else -1
        ),
        "soonest_to_threshold": (
            soonest["path"] if soonest else None
        ),
        "soonest_hours": (
            soonest["hours_to_threshold"] if soonest else None
        ),
    }


def growth_report(
    repo: Path,
    *,
    threshold: int = DEFAULT_THRESHOLD,
    lookback_hours: float = DEFAULT_LOOKBACK_HOURS,
    files: list[str] | None = None,
) -> str:
    """Return a human-readable multi-line growth report."""
    results = scan_growth(
        repo,
        threshold=threshold,
        lookback_hours=lookback_hours,
        files=files,
    )
    summary = growth_summary(results)
    lines: list[str] = []

    lines.append(
        f"doc growth report (threshold {threshold // 1000}KB, "
        f"lookback {lookback_hours:.0f}h)"
    )
    lines.append("=" * 60)

    for r in results:
        if r["size_bytes"] < 0:
            lines.append(f"  {r['path']:<30s}  MISSING")
            continue

        rate_str = (
            f"{r['bytes_per_hour']:.0f} B/h"
            if r["bytes_per_hour"] >= 0
            else "n/a"
        )
        eta_str = (
            f"eta {r['hours_to_threshold']:.0f}h"
            if r["hours_to_threshold"] is not None
            else (
                "OVER THRESHOLD" if r["needs_compaction"] else "n/a"
            )
        )
        lines.append(
            f"  {r['path']:<30s}  "
            f"{r['size_kb']:>8.1f} KB  "
            f"{rate_str:>10s}  "
            f"{eta_str}"
        )

    lines.append("-" * 60)
    lines.append(
        f"  total: {summary['total_tracked_kb']:.1f} KB across "
        f"{len(results)} files"
    )
    if summary["files_needing_compaction"]:
        lines.append(
            f"  NEEDS COMPACTION: "
            f"{', '.join(summary['files_needing_compaction'])}"
        )
    if summary["soonest_to_threshold"]:
        lines.append(
            f"  soonest to threshold: {summary['soonest_to_threshold']} "
            f"in {summary['soonest_hours']:.0f}h"
        )

    return "\n".join(lines)
