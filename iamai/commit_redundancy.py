"""commit_redundancy — measure content overlap between successive commits.

A productive automated writer should *evolve*, not loop.  When commit N
and commit N+1 touch the same files with largely overlapping diffs, the
writer is spinning its wheels — producing activity without progress.

This module fills the gap between:

- ``stroke_dedup``, which catches identical *seed phrases* in the
  append-only stroke log but says nothing about committed diffs;
- ``commit_substance``, which scores individual commit quality (bulk,
  lexical spread, structural depth, novelty) but compares each commit
  against a fixed reference window, not its immediate neighbour;
- ``commit_density``, which measures how much *change* each commit
  carries but not whether that change is *new*.

The redundancy analyser answers: *are successive commits rewriting the
same ground, and how severe is the repetition across a window?*

Metrics
-------

==================  ====================================================
metric              what it measures
==================  ====================================================
file_overlap        Jaccard similarity of changed-file sets between
                    consecutive commits
path_depth_delta    absolute difference in average path depth — did
                    the writer stay in the same area or move?
message_similarity  normalised Levenshtein similarity of commit
                    messages (quick proxy for intent repetition)
composite           weighted blend: 0 = completely fresh, 1 = clone
==================  ====================================================

Usage::

    from iamai.commit_redundancy import (
        analyse_pair, analyse_window, RedundancyReport,
    )

    # Compare two commits (each is a dict with 'files' and 'message')
    report = analyse_pair(commit_a, commit_b)
    print(report.composite)   # 0.0 .. 1.0

    # Sliding window over a list of commits
    window = analyse_window(commits, window_size=10)
    print(window.mean_redundancy)
    print(window.verdict)       # "healthy" / "mild" / "severe"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# defaults
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS: Dict[str, float] = {
    "file_overlap": 0.45,
    "path_depth_delta": 0.20,
    "message_similarity": 0.35,
}

VERDICT_THRESHOLDS: Dict[str, float] = {
    "severe": 0.65,
    "mild": 0.35,
    # below mild → "healthy"
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _normalise_path_set(files: Sequence[str]) -> set[str]:
    """Return a set of normalised file paths."""
    return {f.strip().lstrip("./") for f in files if f.strip()}


def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity of two sets; returns 0 when both are empty."""
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _avg_path_depth(files: Sequence[str]) -> float:
    """Mean directory depth of a file list."""
    if not files:
        return 0.0
    return sum(f.strip().count("/") for f in files) / len(files)


def _tokenise(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _bigram_similarity(a: str, b: str) -> float:
    """Character-bigram similarity between two strings.

    Uses a Jaccard-style comparison over character bigrams.  Returns 0
    when both strings are shorter than 2 characters.
    """
    tokens_a = _tokenise(a)
    tokens_b = _tokenise(b)
    if not tokens_a or not tokens_b:
        return 0.0

    def _bigrams(tokens: list[str]) -> list[str]:
        joined = " ".join(tokens)
        return [joined[i : i + 2] for i in range(len(joined) - 1)]

    ba = set(_bigrams(tokens_a))
    bb = set(_bigrams(tokens_b))
    return _jaccard(ba, bb)


# ---------------------------------------------------------------------------
# pair analysis
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RedundancyReport:
    """Result of comparing two consecutive commits."""

    file_overlap: float = 0.0
    path_depth_delta: float = 0.0
    message_similarity: float = 0.0
    composite: float = 0.0
    commit_a: str = ""
    commit_b: str = ""
    verdict: str = "healthy"

    def as_dict(self) -> dict:
        return {
            "commit_a": self.commit_a,
            "commit_b": self.commit_b,
            "file_overlap": round(self.file_overlap, 4),
            "path_depth_delta": round(self.path_depth_delta, 4),
            "message_similarity": round(self.message_similarity, 4),
            "composite": round(self.composite, 4),
            "verdict": self.verdict,
        }


def _verdict(score: float) -> str:
    if score >= VERDICT_THRESHOLDS["severe"]:
        return "severe"
    if score >= VERDICT_THRESHOLDS["mild"]:
        return "mild"
    return "healthy"


def analyse_pair(
    commit_a: Dict[str, Any],
    commit_b: Dict[str, Any],
    weights: Optional[Dict[str, float]] = None,
) -> RedundancyReport:
    """Compare two consecutive commits and return a redundancy report.

    Each commit dict should contain:
    - ``hash``    (str, optional): short sha for labelling
    - ``files``   (list[str]): paths changed
    - ``message`` (str): commit message

    Missing keys default to empty values.
    """
    w = weights or DEFAULT_WEIGHTS

    files_a = _normalise_path_set(commit_a.get("files", []))
    files_b = _normalise_path_set(commit_b.get("files", []))

    fo = _jaccard(files_a, files_b)
    depth_a = _avg_path_depth(commit_a.get("files", []))
    depth_b = _avg_path_depth(commit_b.get("files", []))
    # Normalise depth delta: max reasonable delta is ~5 levels
    pd = min(abs(depth_a - depth_b) / 5.0, 1.0)
    # Invert: small delta → high redundancy signal
    pd_score = 1.0 - pd

    ms = _bigram_similarity(
        commit_a.get("message", ""),
        commit_b.get("message", ""),
    )

    composite = (
        w.get("file_overlap", 0.45) * fo
        + w.get("path_depth_delta", 0.20) * pd_score
        + w.get("message_similarity", 0.35) * ms
    )
    composite = min(max(composite, 0.0), 1.0)

    return RedundancyReport(
        file_overlap=fo,
        path_depth_delta=pd_score,
        message_similarity=ms,
        composite=composite,
        commit_a=commit_a.get("hash", ""),
        commit_b=commit_b.get("hash", ""),
        verdict=_verdict(composite),
    )


# ---------------------------------------------------------------------------
# window analysis
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WindowReport:
    """Aggregated redundancy over a sliding window of commits."""

    pairs: list[RedundancyReport] = field(default_factory=list)
    mean_redundancy: float = 0.0
    max_redundancy: float = 0.0
    severe_count: int = 0
    mild_count: int = 0
    healthy_count: int = 0
    verdict: str = "healthy"
    window_size: int = 0

    def as_dict(self) -> dict:
        return {
            "window_size": self.window_size,
            "pair_count": len(self.pairs),
            "mean_redundancy": round(self.mean_redundancy, 4),
            "max_redundancy": round(self.max_redundancy, 4),
            "severe_count": self.severe_count,
            "mild_count": self.mild_count,
            "healthy_count": self.healthy_count,
            "verdict": self.verdict,
        }


def analyse_window(
    commits: Sequence[Dict[str, Any]],
    window_size: int = 10,
    weights: Optional[Dict[str, float]] = None,
) -> WindowReport:
    """Analyse redundancy across a sliding window of consecutive commits.

    Parameters
    ----------
    commits : sequence of commit dicts (oldest first)
    window_size : max number of commits to consider (default 10)
    weights : optional weight overrides

    Returns a ``WindowReport`` with aggregate statistics.
    """
    if len(commits) < 2:
        return WindowReport(verdict="healthy", window_size=len(commits))

    window = list(commits)[-window_size:]
    pairs: list[RedundancyReport] = []
    for i in range(len(window) - 1):
        pairs.append(analyse_pair(window[i], window[i + 1], weights))

    scores = [p.composite for p in pairs]
    mean_r = sum(scores) / len(scores) if scores else 0.0
    max_r = max(scores) if scores else 0.0

    severe = sum(1 for p in pairs if p.verdict == "severe")
    mild = sum(1 for p in pairs if p.verdict == "mild")
    healthy = sum(1 for p in pairs if p.verdict == "healthy")

    # Window verdict: severe if mean ≥ 0.5, mild if mean ≥ 0.3
    if mean_r >= 0.5:
        w_verdict = "severe"
    elif mean_r >= 0.3:
        w_verdict = "mild"
    else:
        w_verdict = "healthy"

    return WindowReport(
        pairs=pairs,
        mean_redundancy=mean_r,
        max_redundancy=max_r,
        severe_count=severe,
        mild_count=mild,
        healthy_count=healthy,
        verdict=w_verdict,
        window_size=len(window),
    )


# ---------------------------------------------------------------------------
# convenience: redundancy timeline
# ---------------------------------------------------------------------------

def redundancy_timeline(
    commits: Sequence[Dict[str, Any]],
    weights: Optional[Dict[str, float]] = None,
) -> list[Dict[str, Any]]:
    """Return a per-pair redundancy report for every consecutive pair.

    Each entry is a dict with ``commit_a``, ``commit_b``, ``composite``,
    and ``verdict`` keys — suitable for plotting or tabular display.
    """
    results: list[Dict[str, Any]] = []
    for i in range(len(commits) - 1):
        r = analyse_pair(commits[i], commits[i + 1], weights)
        results.append(r.as_dict())
    return results
