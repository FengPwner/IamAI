#!/usr/bin/env python3
"""Measure the repo's "graft health" — how well multiple writers coexist
and integrate into a single coherent tree.

Biological metaphor:
    A graft is the horticultural technique of joining two plants so they
    grow as one.  A successful graft means both scions share nutrients,
    neither starves the other, and the cambium layers fuse cleanly.

    In this repo, multiple AI writers (qwen, kimi, doubao, guoban) take
    turns contributing strokes.  A healthy graft means:
      - No single writer dominates to the point of starving others
      - Commits are interleaved, not clumped by author
      - The tree stays coherent despite multiple hands

Four metrics, each scored 0–25, summed to 0–100:

    1. balance         — Gini-based equity of stroke distribution
    2. interleaving    — how often consecutive commits switch authors
    3. coverage        — fraction of stroke categories touched by ≥2 writers
    4. conflict_rate   — merge-conflict frequency (inverted, lower is better)

Grading:
    fused       80–100   writers seamlessly integrated, tree is coherent
    healing     50–79    some imbalance but integration progressing
    scarred     20–49    visible seams, one writer dominates or isolation
    rejected     0–19    graft failed, writers operating in parallel worlds

Usage:
    python3 tools/repo_graft.py              # human-readable
    python3 tools/repo_graft.py --json       # machine-readable
    python3 tools/repo_graft.py --commits 200  # scan more history

Exit codes:
    0  grade fused or healing
    1  grade scarred
    2  grade rejected
    3  error
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
DEFAULT_COMMITS = 200


# ── Data ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GraftMetric:
    name: str
    value: float          # 0–25
    max: float = 25.0
    detail: str = ""


@dataclass(frozen=True)
class GraftReport:
    score: float
    grade: str            # fused / healing / scarred / rejected
    metrics: List[GraftMetric]
    writers: List[str]
    writer_strokes: dict
    total_commits_scanned: int
    interleaving_ratio: float
    multi_writer_categories: int
    total_categories: int
    conflict_count: int
    timestamp: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["metrics"] = [asdict(m) for m in self.metrics]
        return d


# ── Helpers ───────────────────────────────────────────────────────────


def _git(*args: str) -> str:
    """Run a git command in the repo, return stdout."""
    result = subprocess.run(
        ["git", "-C", str(REPO)] + list(args),
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def gini_coefficient(values: List[float]) -> float:
    """Compute normalised Gini coefficient (0 = perfect equality, 1 = total
    inequality).

    Uses the mean-absolute-difference formula, then normalises by the
    theoretical maximum (n−1)/n so the result always spans [0, 1]
    regardless of sample size:

        G_raw = Σᵢ Σⱼ |xᵢ − xⱼ| / (2 n² x̄)
        G     = G_raw / ((n−1)/n)   = n·G_raw / (n−1)

    A single writer gets gini=0 (trivially equal).
    Two writers at 50/50 get gini=0.
    Two writers at 100/0 get gini=1.
    """
    n = len(values)
    if n <= 1:
        return 0.0
    mean = sum(values) / n
    if mean == 0:
        return 0.0
    abs_diff_sum = sum(
        abs(values[i] - values[j]) for i in range(n) for j in range(n)
    )
    g_raw = abs_diff_sum / (2 * n * n * mean)
    # Normalise so the theoretical maximum is 1.0 for any n
    return g_raw * n / (n - 1)


def parse_commit_authors(n: int) -> List[str]:
    """Get author email for the last n commits."""
    raw = _git("log", f"--max-count={n}", "--format=%ae")
    return [line.strip() for line in raw.splitlines() if line.strip()]


def parse_commit_categories(n: int) -> List[Tuple[str, str]]:
    """Get (author_email, summary) for the last n commits.

    Extracts the stroke category from commit messages like:
      'stroke 4783: thought — if a number in a diary...'
      'caretaker visit 334: add repo_metabolism.py...'
    Returns list of (author, category) tuples.
    """
    raw = _git("log", f"--max-count={n}", "--format=%ae|%s")
    results = []
    for line in raw.splitlines():
        if "|" not in line:
            continue
        author, subject = line.split("|", 1)
        # Try to extract category from commit subject
        category = "other"
        if "stroke" in subject.lower():
            for kind in ("devlog", "garden", "metrics", "note", "snippet", "thought"):
                if kind in subject.lower():
                    category = kind
                    break
        elif "caretaker visit" in subject.lower():
            category = "visit"
        elif "catch-up" in subject.lower() or "recovery" in subject.lower():
            category = "recovery"
        elif "add " in subject.lower() or "new " in subject.lower():
            category = "feature"
        results.append((author.strip(), category))
    return results


def count_strokes_per_writer() -> dict:
    """Count strokes from data/strokes.jsonl by writer field."""
    strokes_file = REPO / "data" / "strokes.jsonl"
    if not strokes_file.exists():
        return {}
    writers: dict = {}
    try:
        with open(strokes_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    w = obj.get("writer", "unknown")
                    writers[w] = writers.get(w, 0) + 1
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return writers


def count_merge_conflicts_recent(n: int) -> int:
    """Count merge conflicts in the last n commits.

    Uses a lightweight approach: scan commit subjects for "merge conflict"
    or "resolve conflict" keywords rather than expensive diff filtering.
    """
    try:
        raw = _git("log", f"--max-count={n}", "--format=%s")
        count = 0
        for line in raw.splitlines():
            lower = line.strip().lower()
            if "conflict" in lower or "merge" in lower:
                count += 1
        return count
    except RuntimeError:
        return 0


# ── Scoring ───────────────────────────────────────────────────────────


def score_balance(writer_strokes: dict) -> GraftMetric:
    """Score writer balance using Gini coefficient.

    Perfect equity (gini=0) → 25.  Total inequality (gini=1) → 0.
    Single writer is trivially balanced → 25.
    """
    if not writer_strokes:
        return GraftMetric("balance", 0.0, detail="no writer data")

    writers = list(writer_strokes.keys())
    counts = list(writer_strokes.values())

    if len(writers) <= 1:
        return GraftMetric(
            "balance", 25.0,
            detail=f"single writer ({writers[0] if writers else 'none'}), trivially balanced"
        )

    gini = gini_coefficient([float(c) for c in counts])
    # Invert: gini=0 → 25, gini=1 → 0
    value = max(0.0, min(25.0, 25.0 * (1.0 - gini)))

    top_writer = max(writer_strokes, key=writer_strokes.get)
    top_count = writer_strokes[top_writer]
    total = sum(counts)
    top_pct = (top_count / total * 100) if total else 0

    return GraftMetric(
        "balance", round(value, 1),
        detail=f"gini={gini:.3f}, {len(writers)} writers, "
               f"top={top_writer} ({top_pct:.0f}%, {top_count} strokes)"
    )


def score_interleaving(authors: List[str]) -> GraftMetric:
    """Score how often consecutive commits switch authors.

    If all commits are by one author → 0 (no interleaving to score).
    If authors alternate every commit → 25 (perfect interleaving).
    """
    if len(authors) < 2:
        return GraftMetric("interleaving", 0.0, detail="not enough commits")

    unique_authors = set(authors)
    if len(unique_authors) <= 1:
        return GraftMetric(
            "interleaving", 0.0,
            detail=f"single author ({list(unique_authors)[0]}), no interleaving"
        )

    transitions = 0
    for i in range(1, len(authors)):
        if authors[i] != authors[i - 1]:
            transitions += 1

    max_possible = len(authors) - 1
    ratio = transitions / max_possible if max_possible > 0 else 0.0
    value = max(0.0, min(25.0, 25.0 * ratio))

    return GraftMetric(
        "interleaving", round(value, 1),
        detail=f"{transitions}/{max_possible} author transitions "
               f"({ratio:.1%}), {len(unique_authors)} distinct authors"
    )


def score_coverage(commit_cats: List[Tuple[str, str]]) -> GraftMetric:
    """Score what fraction of stroke categories are touched by ≥2 writers.

    If every category has contributions from multiple writers → 25.
    If each category is siloed to one writer → 0.
    """
    if not commit_cats:
        return GraftMetric("coverage", 0.0, detail="no commit data")

    # Group: category → set of writers
    cat_writers: dict = {}
    for author, cat in commit_cats:
        if cat not in cat_writers:
            cat_writers[cat] = set()
        cat_writers[cat].add(author)

    total_cats = len(cat_writers)
    multi_writer = sum(1 for ws in cat_writers.values() if len(ws) >= 2)

    if total_cats == 0:
        return GraftMetric("coverage", 0.0, detail="no categories found")

    ratio = multi_writer / total_cats
    value = max(0.0, min(25.0, 25.0 * ratio))

    return GraftMetric(
        "coverage", round(value, 1),
        detail=f"{multi_writer}/{total_cats} categories touched by ≥2 writers "
               f"({ratio:.0%})"
    )


def score_conflict_rate(conflict_count: int, total_commits: int) -> GraftMetric:
    """Score conflict rate (inverted — fewer conflicts is better).

    0% conflicts → 25.  >5% conflicts → 0.
    """
    if total_commits == 0:
        return GraftMetric("conflict_rate", 25.0, detail="no commits scanned")

    rate = conflict_count / total_commits
    # 0% → 25, 5%+ → 0
    value = max(0.0, min(25.0, 25.0 * (1.0 - rate / 0.05)))

    return GraftMetric(
        "conflict_rate", round(value, 1),
        detail=f"{conflict_count} conflicts in {total_commits} commits "
               f"({rate:.1%})"
    )


# ── Grading ───────────────────────────────────────────────────────────


def grade(score: float) -> str:
    if score >= 80:
        return "fused"
    if score >= 50:
        return "healing"
    if score >= 20:
        return "scarred"
    return "rejected"


def exit_code_for_grade(g: str) -> int:
    return {"fused": 0, "healing": 0, "scarred": 1, "rejected": 2}.get(g, 3)


# ── Main ──────────────────────────────────────────────────────────────


def assess(commits: int = DEFAULT_COMMITS) -> GraftReport:
    """Run the full graft health assessment."""
    now = datetime.now(timezone.utc).isoformat()

    # Gather data
    writer_strokes = count_strokes_per_writer()
    authors = parse_commit_authors(commits)
    commit_cats = parse_commit_categories(commits)
    conflicts = count_merge_conflicts_recent(commits)

    # Score each metric
    m_balance = score_balance(writer_strokes)
    m_interleave = score_interleaving(authors)
    m_coverage = score_coverage(commit_cats)
    m_conflict = score_conflict_rate(conflicts, len(authors))

    metrics = [m_balance, m_interleave, m_coverage, m_conflict]
    total = sum(m.value for m in metrics)
    g = grade(total)

    # Compute summary stats
    cat_writers: dict = {}
    for author, cat in commit_cats:
        if cat not in cat_writers:
            cat_writers[cat] = set()
        cat_writers[cat].add(author)
    multi_writer_cats = sum(1 for ws in cat_writers.values() if len(ws) >= 2)

    return GraftReport(
        score=round(total, 1),
        grade=g,
        metrics=metrics,
        writers=sorted(writer_strokes.keys()),
        writer_strokes=writer_strokes,
        total_commits_scanned=len(authors),
        interleaving_ratio=m_interleave.value / 25.0 if m_interleave.value > 0 else 0.0,
        multi_writer_categories=multi_writer_cats,
        total_categories=len(cat_writers),
        conflict_count=conflicts,
        timestamp=now,
    )


def as_text(report: GraftReport) -> str:
    """Human-readable output."""
    lines = [
        f"🌱 Repo Graft Health",
        f"{'─' * 50}",
        f"Score:  {report.score}/100",
        f"Grade:  {report.grade.upper()}",
        f"Writers: {', '.join(report.writers) if report.writers else 'none'}",
        f"Commits scanned: {report.total_commits_scanned}",
        f"Conflicts: {report.conflict_count}",
        f"",
        f"Metrics:",
    ]
    for m in report.metrics:
        bar = "█" * int(m.value) + "░" * (25 - int(m.value))
        lines.append(f"  {m.name:16s} {bar} {m.value:5.1f}/25  {m.detail}")

    lines.append("")
    if report.grade == "fused":
        lines.append("✓ Graft is fused — writers are well integrated.")
    elif report.grade == "healing":
        lines.append("⚠ Graft is healing — integration progressing but uneven.")
    elif report.grade == "scarred":
        lines.append("⚠ Graft is scarred — visible seams between writers.")
    else:
        lines.append("✗ Graft rejected — writers operating in isolation.")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Measure repo graft health (multi-writer integration).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--commits", type=int, default=DEFAULT_COMMITS,
                     help="number of recent commits to scan")
    args = ap.parse_args()

    try:
        report = assess(commits=args.commits)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(as_text(report))

    return exit_code_for_grade(report.grade)


if __name__ == "__main__":
    sys.exit(main())
