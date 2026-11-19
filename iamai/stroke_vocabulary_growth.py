"""stroke_vocabulary_growth — model vocabulary expansion via Heap's Law.

While ``stroke_novelty`` scores each stroke against a sliding window and
``stroke_thematic_coherence`` measures batch-level topical concentration,
neither answers the macro question: *is the writer's vocabulary expanding
or saturating?*

This module applies **Heap's Law** from information retrieval:

    V(n) = alpha * n^beta

where *V(n)* is the unique vocabulary size after *n* total tokens, *alpha*
controls the initial growth rate, and *beta* (0 < beta < 1) governs how
fast new words are discovered.  In a self-writing repo this becomes a
proxy for **creative exploration vs. repetitive recycling**.

Algorithm
---------
1. Tokenise each stroke (lowercase, strip punctuation/whitespace).
2. Walk the sequence cumulatively; at each stroke record the running
   total-token count and unique-vocabulary size.
3. Fit log(V) = log(alpha) + beta*log(n) via ordinary least squares on
   the log-log curve (no numpy required).
4. Classify the growth regime:

   =================  ==================================================
   beta range         regime
   =================  ==================================================
   beta >= 0.70       **exploring** — rapidly discovering new terms
   0.40 <= beta < 0.70 **growing** — healthy logarithmic expansion
   0.20 <= beta < 0.40 **consolidating** — reusing established terms
   beta < 0.20        **saturated** — heavily recycling the same pool
   =================  ==================================================

5. Optionally estimate how many additional tokens are needed to add
   a given number of new unique words (saturation forecasting).

Edge cases
----------
* Empty input -> zeroed report.
* Single stroke -> beta = 0, alpha = unique count (no curve to fit).
* All strokes identical tokens -> beta = 0, alpha = 1.
* Negative beta from a poor fit -> clamped to 0.

Dependencies
------------
Pure Python — no numpy/scipy required.

Written by Qwen during caretaker visit 726, 2026-11-19.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

__all__ = [
    "VocabularyGrowthReport",
    "analyse_vocabulary_growth",
    "analyse_vocabulary_growth_batch",
    "analyse_vocabulary_growth_windows",
    "tokenize_stroke",
]

# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize_stroke(text: str) -> List[str]:
    """Lowercase tokenise; keep alphanumerics, discard punctuation."""
    if not isinstance(text, str):
        return []
    return _TOKEN_RE.findall(text.lower())


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------

@dataclass
class VocabularyGrowthReport:
    """Summary of vocabulary growth over a sequence of strokes."""

    alpha: float = 0.0
    beta: float = 0.0
    total_tokens: int = 0
    unique_tokens: int = 0
    growth_curve: List[Tuple[int, int]] = field(default_factory=list)
    regime: str = "saturated"
    strokes_analysed: int = 0

    # ---- helpers ----------------------------------------------------------

    def predicted_unique(self, total_tokens: int) -> float:
        """Predict unique vocabulary for a given total-token count."""
        if total_tokens <= 0 or self.alpha <= 0:
            return 0.0
        return self.alpha * (total_tokens ** self.beta)

    def tokens_for_new_words(self, current_total: int, new_words: int) -> Optional[int]:
        """Estimate extra tokens needed to discover *new_words* more unique terms.

        Returns None if the target is unreachable (alpha = 0 or beta = 0).
        """
        if self.alpha <= 0 or self.beta <= 0 or new_words <= 0:
            return None
        target_v = self.unique_tokens + new_words
        try:
            needed_total = (target_v / self.alpha) ** (1.0 / self.beta)
        except (ZeroDivisionError, OverflowError, ValueError):
            return None
        extra = needed_total - current_total
        return max(0, int(math.ceil(extra)))

    def to_dict(self) -> dict:
        return {
            "alpha": round(self.alpha, 4),
            "beta": round(self.beta, 4),
            "total_tokens": self.total_tokens,
            "unique_tokens": self.unique_tokens,
            "regime": self.regime,
            "strokes_analysed": self.strokes_analysed,
            "growth_curve_length": len(self.growth_curve),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _log_log_fit(
    xs: List[int], ys: List[int]
) -> Tuple[float, float]:
    """Ordinary least squares on log(x) vs log(y).

    Returns (alpha, beta) where V = alpha * n^beta.
    If the fit is degenerate, returns (0.0, 0.0).
    """
    valid: List[Tuple[float, float]] = []
    for x, y in zip(xs, ys):
        if x > 0 and y > 0:
            valid.append((math.log(x), math.log(y)))

    n = len(valid)
    if n < 2:
        return (0.0, 0.0)

    sum_lx = sum(lx for lx, _ in valid)
    sum_ly = sum(ly for _, ly in valid)
    sum_lxly = sum(lx * ly for lx, ly in valid)
    sum_lx2 = sum(lx * lx for lx, _ in valid)

    denom = n * sum_lx2 - sum_lx * sum_lx
    if abs(denom) < 1e-15:
        return (0.0, 0.0)

    beta = (n * sum_lxly - sum_lx * sum_ly) / denom
    log_alpha = (sum_ly - beta * sum_lx) / n
    alpha = math.exp(log_alpha)

    # Clamp degenerate fits
    if beta < 0:
        beta = 0.0
    if alpha < 0:
        alpha = 0.0

    return (alpha, beta)


def _classify(beta: float) -> str:
    """Map beta to a growth-regime label."""
    if beta >= 0.70:
        return "exploring"
    if beta >= 0.40:
        return "growing"
    if beta >= 0.20:
        return "consolidating"
    return "saturated"


def _zero_report() -> VocabularyGrowthReport:
    return VocabularyGrowthReport()


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyse_vocabulary_growth(
    token_lists: Sequence[Sequence[str]],
) -> VocabularyGrowthReport:
    """Analyse vocabulary growth over a sequence of tokenised strokes.

    Parameters
    ----------
    token_lists : sequence of token sequences
        Each element is a list of tokens for one stroke.

    Returns
    -------
    VocabularyGrowthReport
    """
    curve_x: List[int] = []
    curve_y: List[int] = []
    seen: set = set()
    running_total = 0
    strokes_counted = 0

    for tokens in token_lists:
        if not tokens:
            continue
        strokes_counted += 1
        for tok in tokens:
            seen.add(tok)
            running_total += 1
        curve_x.append(running_total)
        curve_y.append(len(seen))

    if running_total == 0:
        return _zero_report()

    if len(curve_x) < 2:
        # Single data point — no curve to fit
        alpha = float(curve_y[0]) if curve_x[0] == 1 else curve_y[0] / max(curve_x[0], 1)
        return VocabularyGrowthReport(
            alpha=alpha,
            beta=0.0,
            total_tokens=running_total,
            unique_tokens=len(seen),
            growth_curve=list(zip(curve_x, curve_y)),
            regime="saturated",
            strokes_analysed=strokes_counted,
        )

    alpha, beta = _log_log_fit(curve_x, curve_y)

    return VocabularyGrowthReport(
        alpha=alpha,
        beta=beta,
        total_tokens=running_total,
        unique_tokens=len(seen),
        growth_curve=list(zip(curve_x, curve_y)),
        regime=_classify(beta),
        strokes_analysed=strokes_counted,
    )


def analyse_vocabulary_growth_batch(
    texts: Sequence[str],
) -> VocabularyGrowthReport:
    """Convenience: tokenise raw texts then analyse."""
    token_lists = [tokenize_stroke(t) for t in texts if isinstance(t, str)]
    return analyse_vocabulary_growth(token_lists)


def analyse_vocabulary_growth_windows(
    texts: Sequence[str],
    window_size: int = 10,
    step: int = 5,
) -> List[VocabularyGrowthReport]:
    """Sliding-window analysis of vocabulary growth regime evolution.

    Parameters
    ----------
    texts : sequence of raw stroke texts
    window_size : int
        Number of strokes per window.
    step : int
        Stride between consecutive windows.

    Returns
    -------
    List of VocabularyGrowthReport, one per window.
    """
    if window_size < 1 or step < 1:
        raise ValueError("window_size and step must be >= 1")

    reports: List[VocabularyGrowthReport] = []
    for start in range(0, len(texts) - window_size + 1, step):
        window = texts[start : start + window_size]
        reports.append(analyse_vocabulary_growth_batch(window))
    return reports
