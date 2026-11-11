#!/usr/bin/env python3
"""writer_revision_depth — measure how deeply a writer revises existing work.

Not all strokes are created equal.  Some create new files from scratch;
others polish, refactor, or restructure text that already exists.  The
ratio and pattern of these two modes reveals a writer's editing philosophy:

- **Architects** write once and move on — low revision depth, high churn.
- **Sculptors** iterate relentlessly — high revision depth, few new files.
- **Gardeners** balance both — moderate depth with steady growth.

This module quantifies revision depth by classifying each stroke as either
*generative* (mostly new content) or *revisory* (mostly edits to existing
content) and computing a family of metrics over a configurable window.

Revision-depth dimensions
-------------------------

========================  ================================================
metric                    meaning
========================  ================================================
revision_ratio            fraction of strokes classified as revisions
                          (modifying existing files rather than creating
                          new ones)
generation_ratio          complement: fraction of generative strokes
avg_revision_rounds        mean number of times each file is revised after
                          its creation; higher = more iterative polishing
revision_intensity        for files that ARE revised, the average number
                          of revision strokes per file; ignores files
                          never revised
churn_index               fraction of strokes that touch a file and then
                          touch it again within the next 5 strokes;
                          high churn = lots of immediate fix-ups
depth_score               composite 0.0–1.0: 0 = pure architect (write
                          once, move on); 1 = pure sculptor (endless
                          revision); ~0.3–0.5 = healthy gardener
depth_class               architect | light-editor | gardener | polisher |
                          sculptor
========================  ================================================

Depth classes
-------------

==============  ============================================================
class           meaning
==============  ============================================================
architect       score < 0.15 — almost no revisions; writes new files and
                moves on; risk of technical debt from unpolished drafts
light-editor    0.15 ≤ score < 0.30 — occasional revisions but mostly
                generative; good for rapid prototyping
gardener        0.30 ≤ score < 0.50 — balanced mix of new work and
                tending existing files; sustainable long-term pace
polisher        0.50 ≤ score < 0.70 — more revising than generating;
                high quality but slower output
sculptor        score ≥ 0.70 — predominantly revision; risk of
                diminishing returns and perfectionism loops
==============  ============================================================

Usage
-----

::

    from iamai.writer_revision_depth import compute_depth, StrokeRecord

    strokes = [StrokeRecord(timestamp=..., files=[...], is_new_file=[...]), ...]
    result = compute_depth(strokes, lookback=50)
    print(depth_report(result))
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class StrokeRecord:
    """A single writing event.

    ``files`` lists all files touched; ``is_new_file`` is a parallel list
    of booleans indicating whether each file was *created* (True) or
    *modified* (False) by this stroke.
    """

    timestamp: datetime
    files: List[str] = field(default_factory=list)
    is_new_file: List[bool] = field(default_factory=list)
    message: str = ""

    def __post_init__(self):
        # Default: if is_new_file is shorter than files, assume all existing
        if len(self.is_new_file) < len(self.files):
            self.is_new_file.extend(
                [False] * (len(self.files) - len(self.is_new_file))
            )


@dataclass
class DepthResult:
    """Results of a revision-depth analysis."""

    window_strokes: int
    revision_ratio: float
    generation_ratio: float
    avg_revision_rounds: float
    revision_intensity: float
    churn_index: float
    depth_score: float
    depth_class: str
    file_revision_counts: Dict[str, int] = field(default_factory=dict)
    new_file_count: int = 0
    revised_file_count: int = 0


@dataclass
class DepthTrend:
    """How depth scores change across successive windows."""

    direction: str  # increasing | stable | decreasing
    score_delta: float
    earliest_score: float
    latest_score: float
    sample_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classify_stroke(stroke: StrokeRecord) -> str:
    """Classify a single stroke as 'generative' or 'revisory'.

    A stroke is generative if more than half of its file touches create
    new files; revisory otherwise.  A stroke with no files is revisory
    (it probably modified existing content we can't see).
    """
    if not stroke.files:
        return "revisory"
    new_count = sum(1 for n in stroke.is_new_file if n)
    return "generative" if new_count > len(stroke.files) / 2 else "revisory"


def _file_creation_map(strokes: Sequence[StrokeRecord]) -> Dict[str, int]:
    """Map each file to the stroke index where it was first created."""
    created: Dict[str, int] = {}
    for i, s in enumerate(strokes):
        for j, f in enumerate(s.files):
            if j < len(s.is_new_file) and s.is_new_file[j]:
                if f not in created:
                    created[f] = i
    return created


def _file_revision_counts(strokes: Sequence[StrokeRecord]) -> Dict[str, int]:
    """Count how many times each file is touched as a modification (not creation)."""
    counts: Dict[str, int] = defaultdict(int)
    for s in strokes:
        for j, f in enumerate(s.files):
            is_new = j < len(s.is_new_file) and s.is_new_file[j]
            if not is_new:
                counts[f] += 1
    return dict(counts)


# ---------------------------------------------------------------------------
# Core metrics
# ---------------------------------------------------------------------------

def revision_ratio(strokes: Sequence[StrokeRecord]) -> float:
    """Fraction of strokes classified as revisions."""
    if not strokes:
        return 0.0
    revisory = sum(1 for s in strokes if _classify_stroke(s) == "revisory")
    return round(revisory / len(strokes), 4)


def generation_ratio(strokes: Sequence[StrokeRecord]) -> float:
    """Complement of revision_ratio: fraction of generative strokes."""
    return round(1.0 - revision_ratio(strokes), 4)


def avg_revision_rounds(strokes: Sequence[StrokeRecord]) -> float:
    """Mean number of revision strokes per file that has been revised at least once.

    Files only created and never modified are excluded.  Returns 0.0 when
    no file has been revised.
    """
    counts = _file_revision_counts(strokes)
    if not counts:
        return 0.0
    values = list(counts.values())
    return round(sum(values) / len(values), 4)


def revision_intensity(strokes: Sequence[StrokeRecord]) -> float:
    """For files that ARE revised, the average revision count.

    Unlike avg_revision_rounds, this only considers files with at least
    one revision.  When no file has been revised, returns 0.0.

    (In practice revision_intensity == avg_revision_rounds when both
    consider only revised files.  The distinction matters when we later
    weight by file size or time between revisions.)
    """
    counts = _file_revision_counts(strokes)
    revised = [v for v in counts.values() if v > 0]
    if not revised:
        return 0.0
    return round(sum(revised) / len(revised), 4)


def churn_index(strokes: Sequence[StrokeRecord], gap: int = 5) -> float:
    """Fraction of strokes where a touched file is touched again within ``gap`` strokes.

    High churn means the writer frequently makes immediate fix-ups — a sign
    of drafting-then-patching rather than getting it right the first time.
    """
    if len(strokes) < 2:
        return 0.0

    churn_strokes = 0
    for i, s in enumerate(strokes):
        if not s.files:
            continue
        # Collect files touched in the next `gap` strokes
        future_files: set = set()
        for j in range(i + 1, min(i + 1 + gap, len(strokes))):
            future_files.update(strokes[j].files)

        if any(f in future_files for f in s.files):
            churn_strokes += 1

    total_with_files = sum(1 for s in strokes if s.files)
    if total_with_files == 0:
        return 0.0
    return round(churn_strokes / total_with_files, 4)


def classify_depth(score: float) -> str:
    """Classify revision depth from a composite score."""
    if score < 0.15:
        return "architect"
    elif score < 0.30:
        return "light-editor"
    elif score < 0.50:
        return "gardener"
    elif score < 0.70:
        return "polisher"
    else:
        return "sculptor"


def compute_depth(strokes: Sequence[StrokeRecord],
                  lookback: int = 50) -> DepthResult:
    """Compute revision-depth metrics for a sequence of strokes.

    Parameters
    ----------
    strokes : sequence of StrokeRecord
        Strokes ordered oldest-first.
    lookback : int
        Number of most-recent strokes to analyse.

    Returns
    -------
    DepthResult
    """
    n = len(strokes)
    if n == 0:
        return DepthResult(
            window_strokes=0,
            revision_ratio=0.0,
            generation_ratio=0.0,
            avg_revision_rounds=0.0,
            revision_intensity=0.0,
            churn_index=0.0,
            depth_score=0.3,
            depth_class="gardener",
            file_revision_counts={},
            new_file_count=0,
            revised_file_count=0,
        )

    window = strokes[-lookback:] if n > lookback else list(strokes)

    rev_ratio = revision_ratio(window)
    gen_ratio = round(1.0 - rev_ratio, 4)
    avg_rounds = avg_revision_rounds(window)
    intensity = revision_intensity(window)
    churn = churn_index(window)

    # Count new vs revised files
    rev_counts = _file_revision_counts(window)
    created = _file_creation_map(window)
    new_count = len(created)
    revised_count = len(rev_counts)

    # Normalize avg_revision_rounds to 0–1 range (cap at 10 rounds)
    rounds_norm = min(avg_rounds / 10.0, 1.0)

    # Composite score:
    #   revision_ratio     → more revisions     (weight 0.40)
    #   churn_index        → more fix-ups        (weight 0.25)
    #   rounds_norm        → deeper iteration    (weight 0.20)
    #   intensity_norm     → concentrated edits  (weight 0.15)
    intensity_norm = min(intensity / 10.0, 1.0)
    depth_score = round(
        0.40 * rev_ratio
        + 0.25 * churn
        + 0.20 * rounds_norm
        + 0.15 * intensity_norm,
        4,
    )

    depth_class = classify_depth(depth_score)

    return DepthResult(
        window_strokes=len(window),
        revision_ratio=rev_ratio,
        generation_ratio=gen_ratio,
        avg_revision_rounds=avg_rounds,
        revision_intensity=intensity,
        churn_index=churn,
        depth_score=depth_score,
        depth_class=depth_class,
        file_revision_counts=dict(
            sorted(rev_counts.items(), key=lambda x: -x[1])[:20]
        ),
        new_file_count=new_count,
        revised_file_count=revised_count,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def depth_report(result: DepthResult) -> str:
    """Human-readable summary of a revision-depth analysis."""
    lines = [
        f"Revision depth ({result.window_strokes} strokes)",
        f"  class:                {result.depth_class}",
        f"  depth score:          {result.depth_score:.2f}",
        f"  revision ratio:       {result.revision_ratio:.2%}",
        f"  generation ratio:     {result.generation_ratio:.2%}",
        f"  avg revision rounds:  {result.avg_revision_rounds:.2f}",
        f"  revision intensity:   {result.revision_intensity:.2f}",
        f"  churn index:          {result.churn_index:.2%}",
        f"  new files:            {result.new_file_count}",
        f"  revised files:        {result.revised_file_count}",
    ]
    if result.file_revision_counts:
        lines.append("  most-revised files:")
        for fname, count in list(result.file_revision_counts.items())[:10]:
            lines.append(f"    {fname:40s} x{count}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def depth_trend(results: Sequence[DepthResult]) -> DepthTrend:
    """Classify how depth scores evolve across a series of measurements."""
    if not results:
        return DepthTrend(
            direction="stable",
            score_delta=0.0,
            earliest_score=0.3,
            latest_score=0.3,
            sample_count=0,
        )

    scores = [r.depth_score for r in results]
    earliest = scores[0]
    latest = scores[-1]
    delta = round(latest - earliest, 4)

    if len(scores) < 2:
        direction = "stable"
    elif delta > 0.05:
        direction = "increasing"
    elif delta < -0.05:
        direction = "decreasing"
    else:
        direction = "stable"

    return DepthTrend(
        direction=direction,
        score_delta=delta,
        earliest_score=earliest,
        latest_score=latest,
        sample_count=len(results),
    )
