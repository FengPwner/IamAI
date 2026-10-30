"""commit_substance — measure whether committed content carries real weight.

An automated writer can keep the commit pipe hot with content that is
technically valid but semantically hollow: the same paragraph reshuffled,
single-line fillers, boilerplate copy-pasted from earlier strokes.
`commit_message_quality` scores the commit *message*; this module scores
the *diff content* itself.

Each batch of strokes (or a single stroke) is evaluated across four
independent dimensions, each normalised to [0, 1]:

==================  ====================================================
dimension           what it measures
==================  ====================================================
bulk                token count relative to a configurable target
lexical_spread      type-token ratio (vocabulary richness)
structural_depth    presence of paragraphs, lists, headings, code blocks
novelty             Jaccard distance from the preceding reference window
==================  ====================================================

Composite score::

    score = 0.20·bulk + 0.30·lexical_spread + 0.20·structural_depth + 0.30·novelty

Verdict thresholds:

============  ==========================================================
verdict       meaning
============  ==========================================================
substantial   score ≥ 0.65 — genuine creative output
adequate      score in [0.45, 0.65) — acceptable but not rich
thin          score in [0.25, 0.45) — borderline, worth watching
hollow        score < 0.25 — almost no new information committed
============  ==========================================================

Usage::

    from iamai.commit_substance import SubstanceScorer

    scorer = SubstanceScorer(target_tokens=80)
    result = scorer.evaluate(
        text="naming is hard because a bad name is cheap to type ...",
        reference_texts=[...previous strokes...],
    )
    print(result["score"])      # 0.72
    print(result["verdict"])    # "substantial"

    batch = scorer.evaluate_batch(strokes, reference_window=5)
    print(batch["thin_rate"])   # 0.12  (12% of strokes are thin)

Design choices:
- Pure Python, no external dependencies.
- All inputs are arguments (no file I/O in core functions).
- Tokenisation is intentionally simple (lowercase, split on whitespace,
  strip punctuation) — the goal is relative comparison, not NLP accuracy.
"""

from __future__ import annotations

import re
import string
from typing import Any


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------

_STRIP_PUNCT = str.maketrans("", "", string.punctuation)


def _tokenise(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace."""
    return text.lower().translate(_STRIP_PUNCT).split()


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------


def _score_bulk(tokens: list[str], target_tokens: int) -> float:
    """How close the token count is to the target.

    Saturates at 1.0 when tokens ≥ target.
    Linear ramp from 0 → 1 for [0, target].
    """
    if target_tokens <= 0:
        return 1.0
    return min(len(tokens) / target_tokens, 1.0)


def _score_lexical_spread(tokens: list[str]) -> float:
    """Type-token ratio.  Empty input → 0."""
    if not tokens:
        return 0.0
    return len(set(tokens)) / len(tokens)


_HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)
_LIST_RE = re.compile(r"^\s*[-*+]\s", re.MULTILINE)
_CODE_BLOCK_RE = re.compile(r"```", re.MULTILINE)
_PARAGRAPH_RE = re.compile(r"\n\s*\n")


def _score_structural_depth(text: str) -> float:
    """Count structural markers, saturate at 4 signals.

    Each of the following counts as one signal:
    - At least one heading (``#``)
    - At least one list item (``- * +``)
    - At least one code block (````` ``)
    - At least two paragraphs (blank-line separated)
    - At least one table row (``|``)

    Score = min(signals, 4) / 4.
    """
    signals = 0
    if _HEADING_RE.search(text):
        signals += 1
    if _LIST_RE.search(text):
        signals += 1
    if _CODE_BLOCK_RE.search(text):
        signals += 1
    if len(_PARAGRAPH_RE.split(text)) >= 2:
        signals += 1
    if "|" in text:
        signals += 1
    return min(signals, 4) / 4.0


def _score_novelty(tokens: list[str], reference_tokens: set[str]) -> float:
    """Jaccard-style: fraction of tokens NOT in the reference set.

    If the text has no tokens, return 0.
    If the reference set is empty (nothing to compare against), return 1.
    """
    if not tokens:
        return 0.0
    if not reference_tokens:
        return 1.0
    token_set = set(tokens)
    new_tokens = token_set - reference_tokens
    return len(new_tokens) / len(token_set)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Default weights summing to 1.0.
DEFAULT_WEIGHTS: dict[str, float] = {
    "bulk": 0.20,
    "lexical_spread": 0.30,
    "structural_depth": 0.20,
    "novelty": 0.30,
}


def _verdict(score: float) -> str:
    if score >= 0.65:
        return "substantial"
    if score >= 0.45:
        return "adequate"
    if score >= 0.25:
        return "thin"
    return "hollow"


class SubstanceScorer:
    """Evaluate the substantive weight of committed text.

    Parameters
    ----------
    target_tokens : int
        Token count that saturates the *bulk* dimension (default 80).
    weights : dict | None
        Override default dimension weights. Keys must be a subset of
        ``{"bulk", "lexical_spread", "structural_depth", "novelty"}``.
    """

    def __init__(
        self,
        target_tokens: int = 80,
        weights: dict[str, float] | None = None,
    ) -> None:
        self.target_tokens = target_tokens
        self.weights = {**DEFAULT_WEIGHTS}
        if weights:
            for k, v in weights.items():
                if k in self.weights:
                    self.weights[k] = v
        # Normalise weights so they sum to 1.
        total = sum(self.weights.values())
        if total > 0:
            for k in self.weights:
                self.weights[k] /= total

    def evaluate(
        self,
        text: str,
        reference_texts: list[str] | None = None,
    ) -> dict[str, Any]:
        """Score a single piece of text.

        Parameters
        ----------
        text : str
            The committed content to evaluate.
        reference_texts : list[str] | None
            Previous texts used to compute the novelty dimension.
            If ``None`` or empty, novelty defaults to 1.0 (assumed novel).

        Returns
        -------
        dict with keys: ``score``, ``verdict``, ``dimensions``, ``token_count``.
        """
        tokens = _tokenise(text)

        # Build reference token set.
        ref_tokens: set[str] = set()
        if reference_texts:
            for rt in reference_texts:
                ref_tokens.update(_tokenise(rt))

        dims = {
            "bulk": _score_bulk(tokens, self.target_tokens),
            "lexical_spread": _score_lexical_spread(tokens),
            "structural_depth": _score_structural_depth(text),
            "novelty": _score_novelty(tokens, ref_tokens),
        }

        score = sum(self.weights[k] * dims[k] for k in dims)

        return {
            "score": round(score, 3),
            "verdict": _verdict(score),
            "dimensions": {k: round(v, 3) for k, v in dims.items()},
            "token_count": len(tokens),
        }

    def evaluate_batch(
        self,
        texts: list[str],
        reference_window: int = 5,
    ) -> dict[str, Any]:
        """Score a batch of texts with a sliding reference window.

        Each text is compared against the preceding *reference_window*
        texts for the novelty dimension.

        Returns
        -------
        dict with keys: ``results`` (list of per-text dicts),
        ``substantial_rate``, ``adequate_rate``, ``thin_rate``,
        ``hollow_rate``, ``mean_score``.
        """
        results: list[dict[str, Any]] = []
        for i, text in enumerate(texts):
            start = max(0, i - reference_window)
            refs = texts[start:i] if i > 0 else []
            results.append(self.evaluate(text, reference_texts=refs))

        n = len(results) or 1
        verdicts = [r["verdict"] for r in results]

        return {
            "results": results,
            "substantial_rate": round(
                verdicts.count("substantial") / n, 3
            ),
            "adequate_rate": round(
                verdicts.count("adequate") / n, 3
            ),
            "thin_rate": round(verdicts.count("thin") / n, 3),
            "hollow_rate": round(verdicts.count("hollow") / n, 3),
            "mean_score": round(
                sum(r["score"] for r in results) / n, 3
            ),
        }
