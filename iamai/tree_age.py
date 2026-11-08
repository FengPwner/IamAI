"""tree_age — measure file-age distribution across the repository.

A repo that only adds new files without touching old ones accumulates
rot. This module answers: *how fresh is the tree?*

Public API::

    from iamai.tree_age import TreeAge, age_report

    ta = TreeAge(repo_path)
    summary = ta.summary()
    # {"median_age_days": 14.2, "stale_pct": 23.5, "decay_score": 0.31,
    #  "total_files": 1917, "stale_files": 451, "oldest": [...]}

    print(age_report(repo_path))
    # "tree age: median 14d, 23.5% stale (>30d), decay 0.31 — healthy"

Decay score model:

    decay = 0.6 * stale_fraction + 0.4 * cold_fraction

    stale  = files untouched longer than stale_threshold (default 30d)
    cold   = files untouched longer than cold_threshold (default 7d)

    Score range: 0.0 (everything touched today) → 1.0 (everything ancient)

Health classification:

============  ==========  ============================================
range         label       meaning
============  ==========  ============================================
0.0 – 0.2    fresh       actively maintained, low rot
0.2 – 0.4    healthy     normal for an active project
0.4 – 0.6    aging       significant untouched surface
0.6 – 0.8    stale       most files are cold
0.8 – 1.0    rotting     near-total neglect
============  ==========  ============================================
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_STALE_DAYS: float = 30.0
DEFAULT_COLD_DAYS: float = 7.0


@dataclass
class FileAge:
    """Age record for a single tracked file."""
    path: str
    last_modified: float   # epoch seconds
    age_days: float
    lines: int = 0         # current line count (best-effort)


@dataclass
class TreeAgeSummary:
    """Aggregate age statistics for the whole tree."""
    total_files: int
    median_age_days: float
    mean_age_days: float
    stale_count: int       # files older than stale_threshold
    cold_count: int        # files older than cold_threshold
    stale_pct: float
    cold_pct: float
    decay_score: float
    health: str            # fresh / healthy / aging / stale / rotting
    oldest: List[FileAge]  # top-N oldest files
    newest: List[FileAge]  # top-N newest files


class TreeAge:
    """Measure file-age distribution across a git repository."""

    def __init__(
        self,
        repo_path: Path,
        stale_days: float = DEFAULT_STALE_DAYS,
        cold_days: float = DEFAULT_COLD_DAYS,
    ):
        self.repo_path = repo_path.resolve()
        self.stale_threshold = stale_days * 86400
        self.cold_threshold = cold_days * 86400
        self._file_ages: Optional[List[FileAge]] = None

    def _git_log_last_modified(self) -> Dict[str, float]:
        """Get last-modified epoch for every tracked file via git log.

        Uses a single `git log` pass with --diff-filter and --format
        to extract the most recent commit timestamp per file.
        """
        try:
            result = subprocess.run(
                [
                    "git", "log", "--name-only",
                    "--format=COMMIT:%ct",
                    "--diff-filter=ACMR",
                    "--", ".",
                ],
                capture_output=True, text=True,
                cwd=str(self.repo_path),
                timeout=120,
            )
            if result.returncode != 0:
                return {}
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return {}

        last_mod: Dict[str, float] = {}
        current_ts: Optional[float] = None

        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("COMMIT:"):
                try:
                    current_ts = float(line[7:])
                except ValueError:
                    current_ts = None
            elif line and current_ts is not None:
                # First occurrence per file is the most recent commit
                if line not in last_mod:
                    last_mod[line] = current_ts

        return last_mod

    def _count_lines(self, path: str) -> int:
        """Best-effort line count; returns 0 on failure."""
        full = self.repo_path / path
        if not full.is_file():
            return 0
        try:
            return sum(1 for _ in full.open(errors="replace"))
        except (OSError, UnicodeDecodeError):
            return 0

    def load(self, top_n: int = 10) -> List[FileAge]:
        """Load file ages. Cached after first call."""
        if self._file_ages is not None:
            return self._file_ages

        last_mod = self._git_log_last_modified()
        now = time.time()

        ages: List[FileAge] = []
        for path, ts in last_mod.items():
            age_sec = max(0.0, now - ts)
            ages.append(FileAge(
                path=path,
                last_modified=ts,
                age_days=age_sec / 86400,
            ))

        # Sort oldest first for easy slicing
        ages.sort(key=lambda f: -f.age_days)
        self._file_ages = ages
        return ages

    def summary(self, top_n: int = 10) -> TreeAgeSummary:
        """Compute aggregate tree-age statistics.

        Args:
            top_n: Number of oldest/newest files to include.

        Returns:
            TreeAgeSummary with median, mean, decay score, etc.
        """
        ages = self.load(top_n)
        n = len(ages)

        if n == 0:
            return TreeAgeSummary(
                total_files=0,
                median_age_days=0.0,
                mean_age_days=0.0,
                stale_count=0,
                cold_count=0,
                stale_pct=0.0,
                cold_pct=0.0,
                decay_score=0.0,
                health="fresh",
                oldest=[],
                newest=[],
            )

        sorted_by_age = sorted(ages, key=lambda f: f.age_days)
        age_days = [f.age_days for f in sorted_by_age]

        median = age_days[n // 2] if n % 2 else (age_days[n // 2 - 1] + age_days[n // 2]) / 2
        mean = sum(age_days) / n

        now = time.time()
        stale_count = sum(1 for f in ages if (now - f.last_modified) > self.stale_threshold)
        cold_count = sum(1 for f in ages if (now - f.last_modified) > self.cold_threshold)

        stale_frac = stale_count / n
        cold_frac = cold_count / n
        decay = 0.6 * stale_frac + 0.4 * cold_frac

        health = _classify(decay)

        # Line counts for oldest files (expensive — only for top_n)
        oldest = []
        for f in ages[:top_n]:
            f.lines = self._count_lines(f.path)
            oldest.append(f)

        newest = []
        for f in sorted_by_age[:top_n]:
            f.lines = self._count_lines(f.path)
            newest.append(f)

        return TreeAgeSummary(
            total_files=n,
            median_age_days=round(median, 1),
            mean_age_days=round(mean, 1),
            stale_count=stale_count,
            cold_count=cold_count,
            stale_pct=round(stale_frac * 100, 1),
            cold_pct=round(cold_frac * 100, 1),
            decay_score=round(decay, 3),
            health=health,
            oldest=oldest,
            newest=newest,
        )

    def decay_trend(self, commits: int = 10) -> List[Tuple[str, float]]:
        """Approximate decay_score at each of the last N commit points.

        Uses git log to walk backwards and re-computes file ages as if
        'now' were that commit's timestamp.  Cheap approximation — does
        not rebuild the tree, just shifts the reference clock.

        Returns:
            List of (commit_hash, decay_score) pairs, newest first.
        """
        try:
            result = subprocess.run(
                ["git", "log", f"-{commits}", "--format=%H %ct"],
                capture_output=True, text=True,
                cwd=str(self.repo_path),
                timeout=30,
            )
            if result.returncode != 0:
                return []
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

        ages = self.load()
        if not ages:
            return []

        trend: List[Tuple[str, float]] = []
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            commit_hash, ts_str = parts[0], parts[1]
            try:
                ref_now = float(ts_str)
            except ValueError:
                continue

            n = len(ages)
            stale = sum(1 for f in ages if (ref_now - f.last_modified) > self.stale_threshold)
            cold = sum(1 for f in ages if (ref_now - f.last_modified) > self.cold_threshold)
            decay = 0.6 * (stale / n) + 0.4 * (cold / n)
            trend.append((commit_hash[:8], round(decay, 3)))

        return trend


def _classify(decay: float) -> str:
    """Classify a decay score into a health label."""
    if decay < 0.2:
        return "fresh"
    elif decay < 0.4:
        return "healthy"
    elif decay < 0.6:
        return "aging"
    elif decay < 0.8:
        return "stale"
    else:
        return "rotting"


def age_report(
    repo_path: Path,
    stale_days: float = DEFAULT_STALE_DAYS,
    cold_days: float = DEFAULT_COLD_DAYS,
    top_n: int = 10,
) -> str:
    """One-line human-readable tree-age report."""
    ta = TreeAge(repo_path, stale_days=stale_days, cold_days=cold_days)
    s = ta.summary(top_n=top_n)

    return (
        f"tree age: median {s.median_age_days}d, "
        f"{s.stale_pct}% stale (>{stale_days:.0f}d), "
        f"decay {s.decay_score} — {s.health}"
    )


def main() -> int:
    """CLI entry point."""
    import argparse
    import sys

    ap = argparse.ArgumentParser(
        description="Measure file-age distribution across the repository"
    )
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument(
        "--stale-days", type=float, default=DEFAULT_STALE_DAYS,
        help=f"Stale threshold in days (default {DEFAULT_STALE_DAYS})"
    )
    ap.add_argument(
        "--cold-days", type=float, default=DEFAULT_COLD_DAYS,
        help=f"Cold threshold in days (default {DEFAULT_COLD_DAYS})"
    )
    ap.add_argument(
        "--top", type=int, default=10,
        help="Show top-N oldest/newest files (default 10)"
    )
    ap.add_argument(
        "--trend", type=int, default=0, metavar="N",
        help="Show decay trend over last N commits"
    )
    ap.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parent.parent,
        help="Repository root path"
    )
    args = ap.parse_args()

    ta = TreeAge(args.repo, stale_days=args.stale_days, cold_days=args.cold_days)
    s = ta.summary(top_n=args.top)

    if args.trend > 0:
        trend = ta.decay_trend(commits=args.trend)
        if args.json:
            import dataclasses
            print(json.dumps({
                "summary": _summary_to_dict(s),
                "trend": trend,
            }, indent=2))
        else:
            print(age_report(args.repo, args.stale_days, args.cold_days, args.top))
            print(f"\ndecay trend (last {len(trend)} commits):")
            for h, d in trend:
                bar = "█" * int(d * 20)
                print(f"  {h}  {d:.3f}  {bar}")
    elif args.json:
        print(json.dumps(_summary_to_dict(s), indent=2))
    else:
        print(age_report(args.repo, args.stale_days, args.cold_days, args.top))
        print(f"\n{s.total_files} tracked files  |  "
              f"stale: {s.stale_count}  cold: {s.cold_count}")
        print(f"\noldest {min(args.top, len(s.oldest))}:")
        for f in s.oldest:
            print(f"  {f.age_days:>7.1f}d  {f.lines:>6} lines  {f.path}")
        print(f"\nnewest {min(args.top, len(s.newest))}:")
        for f in s.newest:
            print(f"  {f.age_days:>7.1f}d  {f.lines:>6} lines  {f.path}")

    return 0


def _summary_to_dict(s: TreeAgeSummary) -> dict:
    """Convert summary to a JSON-serializable dict."""
    import dataclasses
    d = dataclasses.asdict(s)
    # FileAge objects are already dicts via asdict
    return d


if __name__ == "__main__":
    raise SystemExit(main())
