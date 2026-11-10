#!/usr/bin/env python3
"""commit_surface_area — measure how broadly each commit touches the repo.

A healthy autonomous writer does not just append to the same log file.
It creates new notes, writes new tools, updates documentation, and
occasionally restructures directories.  When every commit looks the
same — ``data/strokes.jsonl``, ``data/writer_state.qwen.json``,
``docs/DEVLOG.md``, ``docs/GARDEN.md``, ``docs/METRICS.md`` — the
writer has settled into a comfort zone: the stroke count grows but the
intellectual surface area shrinks.

This module scores each commit on several dimensions:

====================  =====================================================
metric                meaning
====================  =====================================================
file_count            total files touched
dir_count             distinct top-level directories touched
creation_ratio        new files / total files (creation vs modification)
maintenance_ratio     routine-append files / total files
creative_ratio        notes + docs + new tools / total files
depth_score           how deep into the tree the commit reaches (0-1)
surface_area          composite score 0-1 combining all signals
classification        narrow | moderate | broad | exploratory
====================  =====================================================

Classification thresholds
-------------------------

==================  ========  ============================================
classification      range     interpretation
==================  ========  ============================================
narrow              0.0–0.2   routine append only — log + state + docs
moderate            0.2–0.5   some variation — touches a few directories
broad               0.5–0.8   active creation — new files across areas
exploratory         0.8–1.0   restructuring or new module + tests + notes
==================  ========  ============================================

Usage::

    from iamai.commit_surface_area import analyse_commits

    results = analyse_commits(count=10)
    for r in results:
        print(f"{r['hash'][:8]}  {r['classification']:12s}  "
              f"surface={r['surface_area']:.2f}  files={r['file_count']}")

CLI::

    python3 -m iamai.commit_surface_area              # last 10 commits
    python3 -m iamai.commit_surface_area --count 20   # last 20
    python3 -m iamai.commit_surface_area --json       # machine-readable

Exit codes:
    0  all recent commits are moderate or broader
    1  at least one narrow commit in the window
    2  more than half the commits are narrow (comfort zone)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent

# ── File categories ──────────────────────────────────────────────────

# Files that the batch committer touches every cycle regardless of
# creativity.  A commit that ONLY modifies these is pure maintenance.
MAINTENANCE_PATTERNS = frozenset({
    "data/strokes.jsonl",
    "data/writer_state.qwen.json",
    "data/writer_state.guoban.json",
    "data/writer_state.kimi.json",
    "data/writer_state.doubao.json",
    "docs/DEVLOG.md",
    "docs/GARDEN.md",
    "docs/METRICS.md",
})

# Directories that signal creative work when touched.
CREATIVE_PREFIXES = (
    "notes/",
    "docs/",
    "iamai/",
    "tests/",
    "tools/",
)


def _is_maintenance(path: str) -> bool:
    """Return True if the file is a routine-append target."""
    return path in MAINTENANCE_PATTERNS


def _is_creative(path: str) -> bool:
    """Return True if the file lives in a creative directory."""
    return any(path.startswith(p) for p in CREATIVE_PREFIXES)


def _top_dir(path: str) -> str:
    """Extract the top-level directory from a file path."""
    parts = path.split("/")
    return parts[0] if len(parts) > 1 else "."


def _depth(path: str) -> int:
    """Count directory depth (number of '/' separators)."""
    return path.count("/")


# ── Core analysis ────────────────────────────────────────────────────


@dataclass(frozen=True)
class CommitSurface:
    """Surface-area analysis of a single commit."""

    hash: str
    message: str
    file_count: int
    dir_count: int
    files: list[str]
    new_files: list[str]
    modified_files: list[str]
    creation_ratio: float
    maintenance_ratio: float
    creative_ratio: float
    depth_score: float
    surface_area: float
    classification: str

    def summary(self) -> str:
        return (
            f"{self.hash[:8]}  "
            f"{self.classification:12s}  "
            f"surface={self.surface_area:.2f}  "
            f"files={self.file_count}  "
            f"dirs={self.dir_count}  "
            f"new={len(self.new_files)}  "
            f"maint={self.maintenance_ratio:.0%}"
        )


def _classify(score: float) -> str:
    """Map composite surface-area score to a classification label."""
    if score < 0.2:
        return "narrow"
    if score < 0.5:
        return "moderate"
    if score < 0.8:
        return "broad"
    return "exploratory"


def _compute_depth_score(files: list[str]) -> float:
    """Score how deep into the tree the commit reaches (0-1).

    A commit that only touches top-level files scores 0.
    A commit that reaches 3+ levels deep scores close to 1.
    """
    if not files:
        return 0.0
    depths = [_depth(f) for f in files]
    max_d = max(depths)
    avg_d = sum(depths) / len(depths)
    # normalise: depth 3+ → ~1.0, depth 1 → ~0.3
    return min(1.0, (max_d * 0.6 + avg_d * 0.4) / 3.0)


def analyse_commit(commit_hash: str) -> CommitSurface:
    """Analyse a single commit's surface area.

    Uses ``git diff-tree`` to get the list of files and their status
    (added, modified, deleted).
    """
    # Get commit message (first line)
    msg_out = subprocess.run(
        ["git", "log", "-1", "--format=%s", commit_hash],
        capture_output=True, text=True, cwd=str(REPO),
    )
    message = msg_out.stdout.strip()

    # Get file list with status: A=added, M=modified, D=deleted, R=renamed
    diff_out = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "-r", "--name-status",
         commit_hash],
        capture_output=True, text=True, cwd=str(REPO),
    )

    new_files: list[str] = []
    modified_files: list[str] = []
    all_files: list[str] = []

    for line in diff_out.stdout.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0][0]  # first char: A, M, D, R
        path = parts[-1]      # last field (handles renames)
        all_files.append(path)
        if status == "A":
            new_files.append(path)
        elif status in ("M", "D", "R"):
            modified_files.append(path)

    file_count = len(all_files)
    dirs = {_top_dir(f) for f in all_files}
    dir_count = len(dirs)

    # Ratios
    creation_ratio = len(new_files) / file_count if file_count else 0.0

    maint_count = sum(1 for f in all_files if _is_maintenance(f))
    maintenance_ratio = maint_count / file_count if file_count else 0.0

    creative_count = sum(1 for f in all_files if _is_creative(f) and not _is_maintenance(f))
    creative_ratio = creative_count / file_count if file_count else 0.0

    depth_score = _compute_depth_score(all_files)

    # Composite surface area score
    # Weighted combination:
    #   - directory spread (30%)
    #   - creation ratio (25%)
    #   - creative ratio (25%)
    #   - inverse maintenance (20%)
    dir_spread = min(1.0, dir_count / 6.0)  # 6+ dirs → 1.0
    inv_maintenance = 1.0 - maintenance_ratio

    surface_area = (
        dir_spread * 0.30
        + creation_ratio * 0.25
        + creative_ratio * 0.25
        + inv_maintenance * 0.20
    )
    surface_area = round(min(1.0, max(0.0, surface_area)), 4)

    classification = _classify(surface_area)

    return CommitSurface(
        hash=commit_hash,
        message=message,
        file_count=file_count,
        dir_count=dir_count,
        files=all_files,
        new_files=new_files,
        modified_files=modified_files,
        creation_ratio=round(creation_ratio, 4),
        maintenance_ratio=round(maintenance_ratio, 4),
        creative_ratio=round(creative_ratio, 4),
        depth_score=round(depth_score, 4),
        surface_area=surface_area,
        classification=classification,
    )


def analyse_commits(count: int = 10) -> list[CommitSurface]:
    """Analyse the last *count* commits, newest first."""
    log_out = subprocess.run(
        ["git", "log", f"-{count}", "--format=%H"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    hashes = [h.strip() for h in log_out.stdout.strip().splitlines() if h.strip()]
    return [analyse_commit(h) for h in hashes]


# ── Aggregate report ─────────────────────────────────────────────────


def surface_report(commits: list[CommitSurface]) -> dict:
    """Produce an aggregate report over a list of commit analyses.

    Returns a dict with:
    - total_commits
    - classification_counts: {narrow: N, moderate: N, ...}
    - narrow_ratio: fraction of commits classified as narrow
    - avg_surface_area: mean composite score
    - trend: "shrinking" | "stable" | "growing" (comparing first vs last half)
    - diagnosis: human-readable summary
    """
    if not commits:
        return {"total_commits": 0, "diagnosis": "no commits to analyse"}

    counts = {"narrow": 0, "moderate": 0, "broad": 0, "exploratory": 0}
    for c in commits:
        counts[c.classification] = counts.get(c.classification, 0) + 1

    narrow_ratio = counts["narrow"] / len(commits)
    avg_surface = sum(c.surface_area for c in commits) / len(commits)

    # Trend: compare first half (older) vs second half (newer)
    mid = len(commits) // 2
    if mid >= 2:
        older = commits[mid:]   # git log returns newest first
        newer = commits[:mid]
        older_avg = sum(c.surface_area for c in older) / len(older)
        newer_avg = sum(c.surface_area for c in newer) / len(newer)
        delta = newer_avg - older_avg
        if delta > 0.05:
            trend = "growing"
        elif delta < -0.05:
            trend = "shrinking"
        else:
            trend = "stable"
    else:
        older_avg = newer_avg = avg_surface
        trend = "insufficient data"

    # Diagnosis
    if narrow_ratio > 0.5:
        diagnosis = (
            f"comfort zone: {narrow_ratio:.0%} of recent commits are narrow. "
            f"the writer is appending to the same files without exploring."
        )
    elif narrow_ratio > 0.3:
        diagnosis = (
            f"mixed: {narrow_ratio:.0%} narrow commits. "
            f"some creative work but routine append still dominates."
        )
    else:
        diagnosis = (
            f"healthy exploration: only {narrow_ratio:.0%} narrow commits. "
            f"the writer is creating new content across the repo."
        )

    return {
        "total_commits": len(commits),
        "classification_counts": counts,
        "narrow_ratio": round(narrow_ratio, 4),
        "avg_surface_area": round(avg_surface, 4),
        "older_avg": round(older_avg, 4),
        "newer_avg": round(newer_avg, 4),
        "trend": trend,
        "diagnosis": diagnosis,
    }


# ── CLI ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Measure commit surface area — how broadly does "
                    "each commit touch the repo?",
    )
    p.add_argument("--count", type=int, default=10,
                   help="number of recent commits to analyse (default 10)")
    p.add_argument("--json", action="store_true",
                   help="output machine-readable JSON")
    args = p.parse_args(argv)

    commits = analyse_commits(args.count)

    if args.json:
        out = {
            "commits": [asdict(c) for c in commits],
            "report": surface_report(commits),
        }
        print(json.dumps(out, indent=2, default=str))
    else:
        for c in commits:
            print(c.summary())
        print()
        report = surface_report(commits)
        print(f"narrow ratio:    {report['narrow_ratio']:.0%}")
        print(f"avg surface:     {report['avg_surface_area']:.3f}")
        print(f"trend:           {report['trend']}")
        print(f"diagnosis:       {report['diagnosis']}")

    # Exit code logic
    report = surface_report(commits)
    narrow = report.get("narrow_ratio", 0)
    if narrow > 0.5:
        return 2  # comfort zone
    if any(c.classification == "narrow" for c in commits):
        return 1  # at least one narrow
    return 0


if __name__ == "__main__":
    sys.exit(main())
