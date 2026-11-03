"""stroke_diversity — detect repetitive content in the stroke log.

The writer sometimes falls into a loop, emitting near-identical aphorisms
across many strokes.  This module scores how *diverse* the recent N strokes
are, using a simple token-overlap (Jaccard) similarity on the text body
(the part before " -- measured now:" if present).

Public API
----------
- ``strip_metric(text) -> str``
    Remove the trailing " -- measured now: ..." suffix so comparisons
    focus on the creative part of the stroke.
- ``pair_similarity(a, b) -> float``
    Jaccard similarity of two stripped texts on whitespace tokens.
- ``diversity_score(strokes, window=50) -> DiversityReport``
    Score from 0.0 (all identical) to 1.0 (all unique).
- ``find_duplicates(strokes, threshold=0.6) -> list[DuplicatePair]``
    Return pairs whose similarity >= threshold.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

_METRIC_RE = re.compile(r"\s*--\s*measured now[:].*$", re.DOTALL)


def strip_metric(text: str) -> str:
    """Strip the trailing metric suffix so only the creative body remains."""
    return _METRIC_RE.sub("", text).strip()


def _tokenize(text: str) -> frozenset[str]:
    return frozenset(text.lower().split())


def pair_similarity(a: str, b: str) -> float:
    """Jaccard similarity between two texts (token-level)."""
    ta, tb = _tokenize(strip_metric(a)), _tokenize(strip_metric(b))
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


@dataclass
class DuplicatePair:
    seq_a: int
    seq_b: int
    similarity: float
    snippet_a: str
    snippet_b: str


@dataclass
class DiversityReport:
    total: int
    unique_bodies: int
    diversity: float  # 0.0–1.0
    mean_similarity: float
    worst_pair: DuplicatePair | None = None

    @property
    def health(self) -> str:
        if self.diversity >= 0.7:
            return "healthy"
        if self.diversity >= 0.4:
            return "repetitive"
        return "looping"

    def summary(self) -> str:
        return (
            f"diversity={self.diversity:.2f} ({self.health}) "
            f"unique={self.unique_bodies}/{self.total} "
            f"mean_sim={self.mean_similarity:.3f}"
        )


def find_duplicates(
    strokes: Sequence[dict],
    threshold: float = 0.6,
    limit: int = 500,
) -> list[DuplicatePair]:
    """Return pairs with Jaccard similarity >= threshold in the last *limit* strokes."""
    sample = list(strokes)[-limit:]
    pairs: list[DuplicatePair] = []
    for i, sa in enumerate(sample):
        for sb in sample[i + 1 :]:
            sim = pair_similarity(sa.get("text", ""), sb.get("text", ""))
            if sim >= threshold:
                pairs.append(
                    DuplicatePair(
                        seq_a=sa.get("seq", 0),
                        seq_b=sb.get("seq", 0),
                        similarity=round(sim, 4),
                        snippet_a=sa.get("text", "")[:60],
                        snippet_b=sb.get("text", "")[:60],
                    )
                )
    return pairs


def diversity_score(
    strokes: Sequence[dict],
    window: int = 50,
) -> DiversityReport:
    """Score diversity over the last *window* strokes."""
    sample = list(strokes)[-window:]
    if not sample:
        return DiversityReport(total=0, unique_bodies=0, diversity=1.0, mean_similarity=0.0)

    bodies = [strip_metric(s.get("text", "")) for s in sample]
    unique = len(set(b.lower() for b in bodies))

    sims: list[float] = []
    worst: DuplicatePair | None = None
    worst_sim = -1.0
    for i, a in enumerate(bodies):
        for j in range(i + 1, len(bodies)):
            b = bodies[j]
            s = pair_similarity(a, b)
            sims.append(s)
            if s > worst_sim:
                worst_sim = s
                worst = DuplicatePair(
                    seq_a=sample[i].get("seq", 0),
                    seq_b=sample[j].get("seq", 0),
                    similarity=round(s, 4),
                    snippet_a=a[:60],
                    snippet_b=b[:60],
                )

    mean_sim = sum(sims) / len(sims) if sims else 0.0
    # diversity = 1 - mean_sim, clamped
    diversity = max(0.0, min(1.0, 1.0 - mean_sim))

    return DiversityReport(
        total=len(sample),
        unique_bodies=unique,
        diversity=round(diversity, 4),
        mean_similarity=round(mean_sim, 4),
        worst_pair=worst,
    )


def load_strokes(path: Path | str | None = None, tail: int = 500) -> list[dict]:
    """Load the last *tail* strokes from data/strokes.jsonl."""
    if path is None:
        path = Path(__file__).resolve().parent.parent / "data" / "strokes.jsonl"
    else:
        path = Path(path)
    if not path.exists():
        return []
    lines = path.read_text().strip().splitlines()
    result = []
    for line in lines[-tail:]:
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return result
