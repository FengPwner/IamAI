"""repo_growth — track how fast the self-writing repo is expanding.

A self-writing repo grows in three dimensions: file count, line count,
and byte count.  Measuring growth over a window of commits reveals
whether the writer is adding substance or just shuffling existing text.

Public API
----------

``GrowthSnapshot``
    TypedDict: files (int), lines (int), bytes (int), at (float).

``snapshot(repo) -> GrowthSnapshot``
    Count tracked files, total lines, and total bytes of the working
    tree.  Uses ``git ls-files`` for the file list and reads each file
    to measure lines/bytes.  Untracked files are excluded.

``growth_rate(snapshots) -> GrowthReport``
    Given two or more snapshots, compute per-minute rates for files,
    lines, and bytes.  Returns a *GrowthReport* dataclass with:
    - ``files_per_min``, ``lines_per_min``, ``bytes_per_min`` (floats)
    - ``period_sec`` (float, wall-clock span of the window)
    - ``verdict`` (str): one of 'expanding', 'steady', 'shrinking',
      'insufficient_data'

``growth_summary(repo, history) -> str``
    One-liner suitable for caretaker briefings.

Growth verdict thresholds
-------------------------

- files_per_min > 0.01 or lines_per_min > 0.5 → expanding
- files_per_min < -0.01 or lines_per_min < -0.5 → shrinking
- otherwise → steady
- fewer than 2 snapshots or zero elapsed time → insufficient_data

Edge cases:

- Empty repo → snapshot returns (0, 0, 0).
- Binary files → counted for bytes, lines counted as 0 (no newline
  detected in the first 8 KiB).
- Symlinks → resolved; broken symlinks are skipped.
- Permission errors → file is skipped, not counted.

Usage::

    from iamai.repo_growth import snapshot, growth_rate, growth_summary

    history.append(snapshot(repo))
    report = growth_rate(history[-2:])
    print(growth_summary(repo, history))
    # "expanding: +0.3 files/min, +12.5 lines/min (1832 files, 405515 lines)"
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, TypedDict


class GrowthSnapshot(TypedDict):
    files: int
    lines: int
    bytes: int
    at: float


@dataclass(frozen=True)
class GrowthReport:
    files_per_min: float
    lines_per_min: float
    bytes_per_min: float
    period_sec: float
    verdict: str  # 'expanding' | 'steady' | 'shrinking' | 'insufficient_data'


# Thresholds per minute
_FILE_THRESH = 0.01
_LINE_THRESH = 0.5


def _is_binary(path: Path) -> bool:
    """Return True if the file appears to be binary."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
        return b"\x00" in chunk
    except (OSError, IOError):
        return True


def _count_file(path: Path) -> tuple[int, int]:
    """Return (lines, bytes) for a single file.

    Binary files return (0, filesize).  Unreadable files return (0, 0).
    """
    try:
        size = path.stat().st_size
    except OSError:
        return (0, 0)

    if _is_binary(path):
        return (0, size)

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = sum(1 for _ in f)
        return (lines, size)
    except (OSError, IOError):
        return (0, 0)


def snapshot(repo: Path | str, at: float | None = None) -> GrowthSnapshot:
    """Capture the current size of the tracked working tree.

    Parameters
    ----------
    repo : path to the repository root.
    at : optional timestamp override (defaults to ``time.time()``).

    Returns
    -------
    GrowthSnapshot with files, lines, bytes, and timestamp.
    """
    repo = Path(repo)
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return {
                "files": 0,
                "lines": 0,
                "bytes": 0,
                "at": at if at is not None else time.time(),
            }
        file_list = [
            l.strip() for l in result.stdout.splitlines() if l.strip()
        ]
    except (OSError, subprocess.SubprocessError):
        return {
            "files": 0,
            "lines": 0,
            "bytes": 0,
            "at": at if at is not None else time.time(),
        }

    total_lines = 0
    total_bytes = 0
    counted_files = 0

    for rel in file_list:
        fpath = repo / rel
        if not fpath.is_file():
            continue
        # Skip symlinks that point outside the repo
        try:
            resolved = fpath.resolve()
            if not str(resolved).startswith(str(repo.resolve())):
                continue
        except (OSError, ValueError):
            continue
        lines, nbytes = _count_file(fpath)
        total_lines += lines
        total_bytes += nbytes
        counted_files += 1

    return {
        "files": counted_files,
        "lines": total_lines,
        "bytes": total_bytes,
        "at": at if at is not None else time.time(),
    }


def growth_rate(snapshots: List[GrowthSnapshot]) -> GrowthReport:
    """Compute growth rates from a sequence of snapshots.

    Uses the first and last snapshot in the list.  Requires at least
    two snapshots with different timestamps.

    Parameters
    ----------
    snapshots : list of GrowthSnapshot (must have >= 2 entries).

    Returns
    -------
    GrowthReport with per-minute rates and a verdict string.
    """
    if len(snapshots) < 2:
        return GrowthReport(
            files_per_min=0.0,
            lines_per_min=0.0,
            bytes_per_min=0.0,
            period_sec=0.0,
            verdict="insufficient_data",
        )

    first, last = snapshots[0], snapshots[-1]
    elapsed = last["at"] - first["at"]
    if elapsed <= 0:
        return GrowthReport(
            files_per_min=0.0,
            lines_per_min=0.0,
            bytes_per_min=0.0,
            period_sec=elapsed,
            verdict="insufficient_data",
        )

    minutes = elapsed / 60.0
    fpm = (last["files"] - first["files"]) / minutes
    lpm = (last["lines"] - first["lines"]) / minutes
    bpm = (last["bytes"] - first["bytes"]) / minutes

    # Determine verdict
    if fpm > _FILE_THRESH or lpm > _LINE_THRESH:
        verdict = "expanding"
    elif fpm < -_FILE_THRESH or lpm < -_LINE_THRESH:
        verdict = "shrinking"
    else:
        verdict = "steady"

    return GrowthReport(
        files_per_min=fpm,
        lines_per_min=lpm,
        bytes_per_min=bpm,
        period_sec=elapsed,
        verdict=verdict,
    )


def growth_summary(repo: Path | str, history: List[GrowthSnapshot]) -> str:
    """One-line growth summary for caretaker reports.

    Parameters
    ----------
    repo : path to the repository root (for the current file/line count).
    history : list of GrowthSnapshot (at least 2 for rate calculation).

    Returns
    -------
    str, e.g. "expanding: +0.3 files/min, +12.5 lines/min (1832 files, 405515 lines)"
    """
    current = history[-1] if history else snapshot(repo)
    report = growth_rate(history) if len(history) >= 2 else growth_rate([])

    fpm_sign = "+" if report.files_per_min >= 0 else ""
    lpm_sign = "+" if report.lines_per_min >= 0 else ""

    return (
        f"{report.verdict}: "
        f"{fpm_sign}{report.files_per_min:.1f} files/min, "
        f"{lpm_sign}{report.lines_per_min:.1f} lines/min "
        f"({current['files']} files, {current['lines']} lines)"
    )
