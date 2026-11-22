#!/usr/bin/env python3
"""stroke_novelty_decay — measure how fast the writer's vocabulary shrinks.

the repo produces hundreds of strokes per day.  when the writer is
healthy, each stroke brings *some* new words; when it degenerates,
strokes become near-verbatim copies of earlier ones.  this module
slides a window over the stroke sequence and computes the ratio of
*novel* tokens (tokens not seen in the preceding window) to total
tokens.  a declining novelty curve is a leading indicator of
content-mode collapse — the writer is still typing, but it has
nothing new to say.

public API
----------
- ``NoveltyPoint``   – one window's result (index, ratio, novel/total).
- ``NoveltyDecay``   – analyzer: takes a list[str], window size, step.
- ``novelty_report`` – one-line human-readable summary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-zA-Z0-9\u4e00-\u9fff]+")


def _tokenize(text: str) -> list[str]:
    """lowercase tokenization; splits on non-alnum (CJK-safe)."""
    return [t.lower() for t in _TOKEN_RE.findall(text)]


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NoveltyPoint:
    """one sliding-window novelty measurement."""

    index: int
    ratio: float
    novel_count: int
    total_count: int

    def band(self) -> str:
        """classify novelty level.

        | band     | range     | meaning                        |
        |----------|-----------|--------------------------------|
        | fresh    | >= 0.40   | lots of new vocabulary         |
        | stable   | 0.25-0.40 | normal repetition + novelty    |
        | stale    | 0.10-0.25 | vocabulary shrinking           |
        | decayed  | 0.03-0.10 | almost no new words            |
        | frozen   | < 0.03    | near-verbatim repetition       |
        """
        if self.ratio >= 0.40:
            return "fresh"
        if self.ratio >= 0.25:
            return "stable"
        if self.ratio >= 0.10:
            return "stale"
        if self.ratio >= 0.03:
            return "decayed"
        return "frozen"


# ---------------------------------------------------------------------------
# analyzer
# ---------------------------------------------------------------------------

class NoveltyDecay:
    """sliding-window vocabulary novelty analyzer.

    Parameters
    ----------
    texts : sequence of str
        ordered stroke texts.
    window : int
        number of strokes per analysis window (default 50).
    step : int
        step between successive windows (default 10).
    """

    def __init__(
        self,
        texts: Sequence[str],
        window: int = 50,
        step: int = 10,
    ) -> None:
        self.texts = list(texts)
        self.window = max(1, window)
        self.step = max(1, step)
        self._points: Optional[List[NoveltyPoint]] = None

    # ------------------------------------------------------------------
    def _compute(self) -> List[NoveltyPoint]:
        if self._points is not None:
            return self._points

        points: list[NoveltyPoint] = []
        n = len(self.texts)
        if n < 2:
            self._points = points
            return points

        # build per-stroke token sets
        token_sets = [_tokenize(t) for t in self.texts]

        idx = self.window
        while idx <= n:
            win_start = idx - self.window
            current_tokens: list[str] = []
            for row in token_sets[win_start:idx]:
                current_tokens.extend(row)

            # build "prior vocabulary" from everything before the window
            prior_vocab: set[str] = set()
            for row in token_sets[:win_start]:
                prior_vocab.update(row)

            total = len(current_tokens)
            if total == 0:
                novel = 0
            else:
                novel = sum(1 for tok in current_tokens if tok not in prior_vocab)

            ratio = novel / total if total > 0 else 0.0
            points.append(NoveltyPoint(index=idx, ratio=ratio,
                                       novel_count=novel,
                                       total_count=total))
            idx += self.step

        self._points = points
        return points

    # ------------------------------------------------------------------
    def points(self) -> List[NoveltyPoint]:
        """all computed novelty points."""
        return list(self._compute())

    def latest(self) -> Optional[NoveltyPoint]:
        """most recent novelty point, or None if too few strokes."""
        pts = self._compute()
        return pts[-1] if pts else None

    def trend(self) -> str:
        """classify the novelty trajectory.

        compares the mean ratio of the first third of points against
        the last third.  the very first point is excluded because it
        always has ratio=1.0 (no prior vocabulary exists), which would
        skew every trend toward "declining".

        | result     | meaning                              |
        |------------|--------------------------------------|
        | improving  | novelty is increasing                |
        | steady     | roughly unchanged (delta < 0.05)     |
        | declining  | vocabulary is shrinking              |
        | collapsed  | severe drop (delta >= 0.20)          |
        | insufficient_data | fewer than 4 points          |
        """
        pts = self._compute()
        if len(pts) < 4:
            return "insufficient_data"

        # skip the first point (always 1.0 — artefact of empty prior)
        body = pts[1:]
        third = max(1, len(body) // 3)
        early_mean = sum(p.ratio for p in body[:third]) / third
        late_mean = sum(p.ratio for p in body[-third:]) / third
        delta = early_mean - late_mean  # positive = decline

        if delta < -0.05:
            return "improving"
        if delta < 0.05:
            return "steady"
        if delta < 0.20:
            return "declining"
        return "collapsed"

    def summary(self) -> dict:
        """complete summary dict for JSON/CLI output."""
        pts = self._compute()
        lat = self.latest()
        return {
            "total_strokes": len(self.texts),
            "window": self.window,
            "step": self.step,
            "num_points": len(pts),
            "latest_ratio": lat.ratio if lat else None,
            "latest_band": lat.band() if lat else None,
            "trend": self.trend(),
        }


# ---------------------------------------------------------------------------
# convenience
# ---------------------------------------------------------------------------

def novelty_report(texts: Sequence[str], window: int = 50, step: int = 10) -> str:
    """one-line human-readable novelty summary."""
    nd = NoveltyDecay(texts, window=window, step=step)
    s = nd.summary()
    if s["latest_ratio"] is None:
        return "novelty: insufficient data (< 2 strokes)"
    return (
        f"novelty: {s['latest_ratio']:.1%} ({s['latest_band']}), "
        f"trend={s['trend']}, "
        f"{s['num_points']} windows over {s['total_strokes']} strokes"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "data/strokes.jsonl"
    texts: list[str] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            texts.append(obj.get("text", ""))

    print(novelty_report(texts))
