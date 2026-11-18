"""stroke_novelty_injector — defibrillate a stuck writer.

When the writer enters a degenerate loop (detected by ``stroke_dedup``,
``stroke_echo_detector``, or ``content_loop_detector``), simply knowing
about the problem is not enough.  The writer needs a *jolt* — something
that breaks the pattern and forces it onto a fresh track.

This module provides that jolt.  It maintains a curated pool of
**novelty prompts**: short, thought-provoking seeds designed to pull
the writer out of repetitive cycles.  When a stall is detected, the
injector selects a prompt that is maximally *dissimilar* to the
recent stroke history, injects it into the stroke stream, and logs
the intervention.

Architecture
------------

::

    strokes ──▶ [loop detector] ──▶ stalled?
                                      │ yes
                                      ▼
                            [novelty pool] ──▶ select
                                      │       (max-dissimilar)
                                      ▼
                              inject into stream
                                      │
                                      ▼
                              log intervention

Public API
----------

- ``NoveltyPrompt(text, category, used_count)`` — a single prompt
- ``NoveltyPool`` — manages the prompt collection and selection
- ``Intervention`` — record of a single defibrillation event
- ``should_inject(strokes, window, threshold)`` — decide if injection
  is needed based on recent stroke diversity
- ``inject(pool, recent_strokes, strokes)`` — pick a prompt and
  return the modified stroke list with the prompt injected
- ``intervention_log`` — append-only log of interventions

Design choices
--------------

- Prompts are hand-curated, not generated.  Generated prompts tend to
  echo the same patterns they're trying to break.
- Selection uses **max-min dissimilarity**: for each candidate prompt,
  compute its minimum Jaccard distance to the last *k* strokes; pick
  the candidate with the largest minimum distance.  This ensures the
  injected prompt is genuinely novel relative to recent output.
- Each prompt tracks its ``used_count`` so the pool can detect
  exhaustion (all prompts used recently) and signal that the pool
  needs human curation.
- Interventions are logged to ``data/interventions.jsonl`` for
  post-hoc analysis of effectiveness.

Usage::

    from iamai.stroke_novelty_injector import (
        NoveltyPool, should_inject, inject,
    )

    pool = NoveltyPool()
    strokes = ["retry.py is already in the pool"] * 20

    if should_inject(strokes, window=10, threshold=0.3):
        strokes = inject(pool, recent=strokes[-10:], strokes=strokes)

"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
INTERVENTION_LOG = DATA_DIR / "interventions.jsonl"


@dataclass
class NoveltyPrompt:
    """A single novelty prompt in the pool."""

    text: str
    category: str = "general"
    used_count: int = 0
    last_used: Optional[float] = None

    def word_set(self) -> Set[str]:
        """Lowercase word set for similarity computation."""
        return set(re.findall(r"\w+", self.text.lower()))


@dataclass
class Intervention:
    """Record of a single defibrillation event."""

    at: float
    prompt_text: str
    prompt_category: str
    pre_stall_ratio: float
    window_size: int
    stroke_index: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "at": self.at,
            "prompt": self.prompt_text,
            "category": self.prompt_category,
            "pre_stall_ratio": round(self.pre_stall_ratio, 4),
            "window": self.window_size,
            "stroke_index": self.stroke_index,
        }


# ---------------------------------------------------------------------------
# Default prompt pool
# ---------------------------------------------------------------------------

_DEFAULT_PROMPTS: List[Tuple[str, str]] = [
    ("what would this repo look like if it were a city?", "analogy"),
    ("the most interesting bug is the one nobody noticed", "observation"),
    ("delete the least useful file and see what happens", "action"),
    ("if you could only keep ten modules, which ten?", "constraint"),
    ("write a haiku about the last commit", "creative"),
    ("what is the repo trying to say that it hasn't said yet?", "reflection"),
    ("the gap between two commits is also a statement", "observation"),
    ("imagine explaining this project to a five-year-old", "analogy"),
    ("what would happen if the writer stopped for an hour?", "hypothetical"),
    ("name three things this repo does better than a human", "enumeration"),
    ("the best test is the one that fails unexpectedly", "testing"),
    ("every module is a bet on what matters", "philosophy"),
    ("what file would surprise you if it existed?", "creative"),
    ("the commit log is a diary that can't be edited", "observation"),
    ("if this repo were a book, what chapter are we in?", "analogy"),
    ("write about the space between automation and intention", "reflection"),
    ("what would a hostile code reviewer say about this?", "adversarial"),
    ("the simplest fix is usually the one nobody tried", "observation"),
    ("describe the repo's mood in one word", "creative"),
    ("what is the most surprising file in this tree?", "observation"),
    ("if you could merge with another repo, which one?", "hypothetical"),
    ("write a warning label for this codebase", "creative"),
    ("the best documentation is code that doesn't need it", "philosophy"),
    ("what would this project look like in five years?", "future"),
    ("name something this repo taught you about patience", "reflection"),
]


# ---------------------------------------------------------------------------
# Similarity helpers
# ---------------------------------------------------------------------------


def _word_set(text: str) -> Set[str]:
    """Extract lowercase word set from text."""
    return set(re.findall(r"\w+", text.lower()))


def _jaccard_distance(a: Set[str], b: Set[str]) -> float:
    """Jaccard distance between two sets.

    Returns 0.0 when both sets are empty (they are identical).
    Returns 1.0 when the sets are completely disjoint.
    """
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    intersection = a & b
    return 1.0 - len(intersection) / len(union)


def _min_distance_to_recent(
    prompt_words: Set[str], recent_word_sets: List[Set[str]]
) -> float:
    """Minimum Jaccard distance from prompt to any recent stroke."""
    if not recent_word_sets:
        return 1.0
    return min(_jaccard_distance(prompt_words, ws) for ws in recent_word_sets)


# ---------------------------------------------------------------------------
# Diversity measurement
# ---------------------------------------------------------------------------


def diversity_ratio(strokes: Sequence[str], window: int = 10) -> float:
    """Fraction of unique strokes in the last *window* entries.

    Returns 1.0 for an empty or single-stroke window (perfectly diverse).
    Returns values near 0.0 for highly repetitive windows.
    """
    if not strokes:
        return 1.0
    tail = list(strokes)[-window:]
    if len(tail) <= 1:
        return 1.0
    unique = len(set(tail))
    return unique / len(tail)


# ---------------------------------------------------------------------------
# Injection decision
# ---------------------------------------------------------------------------


def should_inject(
    strokes: Sequence[str],
    window: int = 10,
    threshold: float = 0.3,
) -> bool:
    """Decide if the writer needs a novelty injection.

    Returns True when the diversity ratio of the last *window* strokes
    falls below *threshold*.
    """
    return diversity_ratio(strokes, window) < threshold


# ---------------------------------------------------------------------------
# NoveltyPool
# ---------------------------------------------------------------------------


class NoveltyPool:
    """Manages the collection of novelty prompts."""

    def __init__(self, prompts: Optional[List[NoveltyPrompt]] = None):
        if prompts is not None:
            self.prompts = list(prompts)
        else:
            self.prompts = [
                NoveltyPrompt(text=t, category=c) for t, c in _DEFAULT_PROMPTS
            ]

    def __len__(self) -> int:
        return len(self.prompts)

    def select(self, recent_strokes: Sequence[str], top_k: int = 1) -> List[NoveltyPrompt]:
        """Select the *top_k* most dissimilar prompts relative to recent strokes.

        Uses max-min Jaccard distance: for each prompt, compute its
        minimum distance to any recent stroke's word set, then pick
        the prompt(s) with the largest such minimum.
        """
        if not self.prompts:
            return []

        recent_word_sets = [_word_set(s) for s in recent_strokes]

        scored: List[Tuple[float, int]] = []
        for i, prompt in enumerate(self.prompts):
            dist = _min_distance_to_recent(prompt.word_set(), recent_word_sets)
            scored.append((dist, i))

        scored.sort(key=lambda x: x[0], reverse=True)
        selected = [self.prompts[idx] for _, idx in scored[:top_k]]
        return selected

    def mark_used(self, prompt: NoveltyPrompt) -> None:
        """Increment the usage counter and timestamp for a prompt."""
        prompt.used_count += 1
        prompt.last_used = time.time()

    def exhaustion_ratio(self, recent_seconds: float = 3600.0) -> float:
        """Fraction of prompts used within *recent_seconds*.

        Returns 0.0 if no prompts have been used recently.
        A value above 0.8 signals the pool needs fresh curation.
        """
        if not self.prompts:
            return 0.0
        now = time.time()
        cutoff = now - recent_seconds
        recent_used = sum(
            1
            for p in self.prompts
            if p.last_used is not None and p.last_used >= cutoff
        )
        return recent_used / len(self.prompts)

    def reset_counts(self) -> None:
        """Reset all usage counters (e.g. after pool expansion)."""
        for p in self.prompts:
            p.used_count = 0
            p.last_used = None


# ---------------------------------------------------------------------------
# Injection
# ---------------------------------------------------------------------------


def inject(
    pool: NoveltyPool,
    recent: Sequence[str],
    strokes: List[str],
) -> List[str]:
    """Pick a novelty prompt and append it to the stroke list.

    Returns a new list (does not mutate the original).
    """
    selected = pool.select(recent, top_k=1)
    if not selected:
        return list(strokes)
    prompt = selected[0]
    pool.mark_used(prompt)
    result = list(strokes)
    result.append(prompt.text)
    return result


# ---------------------------------------------------------------------------
# Intervention logging
# ---------------------------------------------------------------------------


def log_intervention(intervention: Intervention) -> None:
    """Append an intervention record to the JSONL log."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(INTERVENTION_LOG, "a") as f:
        f.write(json.dumps(intervention.to_dict()) + "\n")


def load_interventions() -> List[Dict[str, Any]]:
    """Load all intervention records from the JSONL log."""
    if not INTERVENTION_LOG.exists():
        return []
    records = []
    with open(INTERVENTION_LOG) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# High-level orchestration
# ---------------------------------------------------------------------------


def maybe_inject(
    strokes: List[str],
    pool: Optional[NoveltyPool] = None,
    window: int = 10,
    threshold: float = 0.3,
    log: bool = True,
) -> Tuple[List[str], Optional[Intervention]]:
    """Check if injection is needed; if so, inject and optionally log.

    Returns:
        (modified_strokes, intervention_or_None)
    """
    if pool is None:
        pool = NoveltyPool()

    if not should_inject(strokes, window, threshold):
        return strokes, None

    recent = strokes[-window:] if len(strokes) >= window else list(strokes)
    pre_ratio = diversity_ratio(strokes, window)

    new_strokes = inject(pool, recent, strokes)

    intervention = Intervention(
        at=time.time(),
        prompt_text=new_strokes[-1],
        prompt_category=pool.prompts[0].category if pool.prompts else "unknown",
        pre_stall_ratio=pre_ratio,
        window_size=window,
        stroke_index=len(strokes),
    )

    if log:
        log_intervention(intervention)

    return new_strokes, intervention
