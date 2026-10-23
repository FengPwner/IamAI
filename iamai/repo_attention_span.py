"""repo_attention_span — how long does the repo stay on one topic?

``commit_file_overlap`` tells you whether two *adjacent* commits touch
the same files.  ``category_momentum`` tells you whether the overall
direction is shifting.  Neither answers the question: *when the repo
starts working on something, how long does it keep at it before
switching to something else?*

This module groups consecutive commits into **attention spans** — runs
where the dominant file-area stays the same — and reports their
lengths.

Algorithm
---------
1. For each commit, determine its *dominant area* by classifying every
   changed file into a top-level directory (``iamai/``, ``tests/``,
   ``tools/``, ``notes/``, ``docs/``, ``data/``, ``root``).
2. Walk commits oldest-first.  While the dominant area stays the same,
   extend the current span.  When it changes, close the span and start
   a new one.
3. Report span lengths (in commit count) and classify the overall
   attention pattern:

============  =====================================================
avg span       reading
============  =====================================================
≥ 8 commits    ``deep_focus`` — sustained work on one area
4 – 7          ``steady`` — normal focused sessions
2 – 3          ``restless`` — frequent context switches
< 2            ``scattered`` — no sustained attention
============  =====================================================

Edge cases
----------
- Fewer than 2 commits → empty report, avg_span 0.0.
- Merge commits (no changed files) inherit the previous span's area.
- A commit touching multiple areas equally is assigned to the
  alphabetically first area (deterministic tie-break).

Usage::

    from iamai.repo_attention_span import attention_span_report

    report = attention_span_report(repo_path=".", last=100)
    print(report.avg_span)     # e.g. 4.2
    print(report.reading)      # "steady"
    print(report.span_count)   # number of distinct spans
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


# ---------------------------------------------------------------------------
# Reading thresholds
# ---------------------------------------------------------------------------

_READINGS: list[tuple[float, str]] = [
    (8.0, "deep_focus"),
    (4.0, "steady"),
    (2.0, "restless"),
]
_READING_DEFAULT = "scattered"


def _classify(avg_span: float) -> str:
    """Return the reading label for an average span length."""
    for threshold, label in _READINGS:
        if avg_span >= threshold:
            return label
    return _READING_DEFAULT


# ---------------------------------------------------------------------------
# Area classification
# ---------------------------------------------------------------------------

_KNOWN_AREAS = ("iamai", "tests", "tools", "notes", "docs", "data")


def _classify_file(path: str) -> str:
    """Map a file path to its top-level area name."""
    parts = path.replace("\\", "/").split("/")
    if len(parts) == 1:
        return "root"
    top = parts[0]
    if top in _KNOWN_AREAS:
        return top
    return "other"


def _dominant_area(files: Sequence[str]) -> str:
    """Return the area with the most files in a commit.

    Ties broken alphabetically (deterministic).
    Returns ``"empty"`` when the file list is empty (merge commit).
    """
    if not files:
        return "empty"
    counts: dict[str, int] = {}
    for f in files:
        area = _classify_file(f)
        counts[area] = counts.get(area, 0) + 1
    max_count = max(counts.values())
    # Deterministic tie-break: alphabetically first area wins.
    candidates = sorted(a for a, c in counts.items() if c == max_count)
    return candidates[0]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SpanInfo:
    """A single attention span — a run of commits in the same area."""

    area: str
    start: str  # short SHA of first commit
    end: str  # short SHA of last commit
    length: int  # number of commits


@dataclass
class AttentionSpanReport:
    """Aggregate attention-span analysis."""

    span_count: int = 0
    avg_span: float = 0.0
    reading: str = _READING_DEFAULT
    spans: list[SpanInfo] = field(default_factory=list)
    total_commits: int = 0

    def to_dict(self) -> dict:
        return {
            "span_count": self.span_count,
            "avg_span": round(self.avg_span, 2),
            "reading": self.reading,
            "total_commits": self.total_commits,
            "spans": [
                {
                    "area": s.area,
                    "start": s.start,
                    "end": s.end,
                    "length": s.length,
                }
                for s in self.spans
            ],
        }


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _run_git(repo: Path, *args: str) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, result.args, result.stdout, result.stderr
        )
    return result.stdout.strip()


def _commit_files(repo: Path, sha: str) -> list[str]:
    """Return the list of files changed by a single commit."""
    output = _run_git(
        repo, "diff-tree", "--no-commit-id", "-r", "--name-only", sha
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def _recent_shas(repo: Path, n: int = 100) -> list[str]:
    """Return the *n* most recent commit SHAs (newest first)."""
    output = _run_git(repo, "log", "--format=%H", f"-{n}")
    return [line.strip() for line in output.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def attention_span_report(
    repo_path: str | Path = ".",
    last: int = 100,
) -> AttentionSpanReport:
    """Analyse attention spans across recent commit history.

    Parameters
    ----------
    repo_path : str or Path
        Path to the git repository.
    last : int
        Number of recent commits to analyse.

    Returns
    -------
    AttentionSpanReport
    """
    repo = Path(repo_path).resolve()
    shas = _recent_shas(repo, last)

    if len(shas) < 2:
        return AttentionSpanReport()

    # Pre-fetch file sets and dominant areas (oldest first).
    chronological = list(reversed(shas))
    areas: list[tuple[str, str]] = []  # (short_sha, area)
    for sha in chronological:
        files = _commit_files(repo, sha)
        area = _dominant_area(files)
        areas.append((sha[:8], area))

    # Build spans.
    spans: list[SpanInfo] = []
    current_area: str | None = None
    span_start = ""
    span_end = ""
    span_length = 0

    for short_sha, area in areas:
        # Merge commits (empty) inherit current area.
        if area == "empty" and current_area is not None:
            area = current_area

        if area == current_area:
            span_length += 1
            span_end = short_sha
        else:
            # Close previous span (if any).
            if current_area is not None and span_length > 0:
                spans.append(
                    SpanInfo(
                        area=current_area,
                        start=span_start,
                        end=span_end,
                        length=span_length,
                    )
                )
            # Start new span.
            current_area = area
            span_start = short_sha
            span_end = short_sha
            span_length = 1

    # Close final span.
    if current_area is not None and span_length > 0:
        spans.append(
            SpanInfo(
                area=current_area,
                start=span_start,
                end=span_end,
                length=span_length,
            )
        )

    if not spans:
        return AttentionSpanReport()

    avg = sum(s.length for s in spans) / len(spans)

    return AttentionSpanReport(
        span_count=len(spans),
        avg_span=avg,
        reading=_classify(avg),
        spans=spans,
        total_commits=len(chronological),
    )


# ---------------------------------------------------------------------------
# Summary formatter
# ---------------------------------------------------------------------------

def attention_summary(report: AttentionSpanReport) -> str:
    """Return a human-readable one-liner for the report."""
    if report.span_count == 0:
        return "repo_attention_span: no commits to analyse"
    return (
        f"repo_attention_span: avg {report.avg_span:.1f} commits/span "
        f"({report.reading}) across {report.span_count} spans, "
        f"{report.total_commits} commits total"
    )
