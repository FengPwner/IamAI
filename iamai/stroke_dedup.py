"""Detect duplicate strokes in the append-only log.

The writer picks a seed phrase, appends a live measurement, and writes
the result to ``data/strokes.jsonl``.  Two strokes are *duplicates* when
their seed phrases match — the trailing measurement is just decoration
on the same thought.

This matters because a writer that repeats itself is not growing; it is
looping.  The content_diversity module catches lopsided *kinds*; this
catches lopsided *ideas*.

Duplicate detection is deliberately conservative:

- Seed phrases shorter than ``MIN_SEED_LEN`` (default 12) characters are
  ignored — short phrases collide by chance, not by repetition.
- Comparison is case-insensitive and strips trailing whitespace.
- The measurement suffix (everything after ``-- measured now:``) is
  discarded before comparison.

Usage::

    from iamai.stroke_dedup import find_duplicates, duplicate_summary

    dupes = find_duplicates()
    for seed, entries in dupes.items():
        print(f"{seed!r} appears {len(entries)} times")

    print(duplicate_summary())
    # "3 duplicate seeds across 1713 strokes (0.17%)"
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_DEFAULT_STROKES_PATH = Path("data/strokes.jsonl")
MIN_SEED_LEN = 12

# The measurement suffix the writer appends.  Everything from the first
# occurrence of this marker onward is stripped before comparison.
_MEASUREMENT_MARKER = "-- measured now:"


def extract_seed(text: str) -> str:
    """Strip the measurement suffix and normalise for comparison.

    Args:
        text: full stroke text, possibly including a measurement suffix.

    Returns:
        The seed phrase, lowercased and stripped.

    Examples:
        >>> extract_seed("hello world -- measured now: 42 things")
        'hello world'
        >>> extract_seed("just a thought, no measurement")
        'just a thought, no measurement'
        >>> extract_seed("  Spaced Out  -- measured now: xyz")
        'spaced out'
    """
    idx = text.find(_MEASUREMENT_MARKER)
    if idx != -1:
        text = text[:idx]
    return text.strip().lower()


def _load_strokes(path: Path) -> list[dict[str, Any]]:
    """Read strokes.jsonl, skipping malformed lines."""
    strokes: list[dict[str, Any]] = []
    if not path.exists():
        return strokes
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                strokes.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return strokes


def find_duplicates(
    path: Path | str | None = None,
    min_seed_len: int = MIN_SEED_LEN,
) -> dict[str, list[dict[str, Any]]]:
    """Return a mapping of seed phrase → list of strokes that share it.

    Only seeds that appear more than once are included.

    Args:
        path: path to strokes.jsonl (default: ``data/strokes.jsonl``).
        min_seed_len: ignore seeds shorter than this (default 12).

    Returns:
        Dict mapping seed → list of stroke dicts.
    """
    path = Path(path) if path else _DEFAULT_STROKES_PATH
    strokes = _load_strokes(path)

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for stroke in strokes:
        text = stroke.get("text", "")
        seed = extract_seed(text)
        if len(seed) < min_seed_len:
            continue
        buckets[seed].append(stroke)

    return {seed: entries for seed, entries in buckets.items() if len(entries) > 1}


def duplicate_count(path: Path | str | None = None, min_seed_len: int = MIN_SEED_LEN) -> int:
    """Return the number of distinct seeds that appear more than once."""
    return len(find_duplicates(path, min_seed_len))


def duplicate_stroke_count(path: Path | str | None = None, min_seed_len: int = MIN_SEED_LEN) -> int:
    """Return the total number of strokes involved in duplication."""
    dupes = find_duplicates(path, min_seed_len)
    return sum(len(entries) for entries in dupes.values())


def duplicate_ratio(path: Path | str | None = None, min_seed_len: int = MIN_SEED_LEN) -> float:
    """Return the fraction of all strokes that are involved in duplication.

    Returns 0.0 when the log is empty.
    """
    path = Path(path) if path else _DEFAULT_STROKES_PATH
    strokes = _load_strokes(path)
    if not strokes:
        return 0.0
    involved = duplicate_stroke_count(path, min_seed_len)
    return involved / len(strokes)


def top_duplicates(
    path: Path | str | None = None,
    min_seed_len: int = MIN_SEED_LEN,
    limit: int = 5,
) -> list[tuple[str, int]]:
    """Return the most-duplicated seeds, sorted by occurrence count descending.

    Args:
        path: path to strokes.jsonl.
        min_seed_len: ignore seeds shorter than this.
        limit: max results to return.

    Returns:
        List of (seed, count) tuples.
    """
    dupes = find_duplicates(path, min_seed_len)
    ranked = sorted(dupes.items(), key=lambda item: len(item[1]), reverse=True)
    return [(seed, len(entries)) for seed, entries in ranked[:limit]]


def duplicate_summary(path: Path | str | None = None, min_seed_len: int = MIN_SEED_LEN) -> str:
    """One-line human-readable summary of duplication status.

    Examples:
        >>> duplicate_summary()
        '0 duplicate seeds across 1713 strokes (0.00%)'
    """
    path = Path(path) if path else _DEFAULT_STROKES_PATH
    strokes = _load_strokes(path)
    dupes = find_duplicates(path, min_seed_len)
    n_dupes = len(dupes)
    n_strokes = len(strokes)
    n_involved = sum(len(e) for e in dupes.values())
    pct = (n_involved / n_strokes * 100) if n_strokes else 0.0
    return f"{n_dupes} duplicate seeds across {n_strokes} strokes ({pct:.2f}%)"


def health_grade(path: Path | str | None = None, min_seed_len: int = MIN_SEED_LEN) -> str:
    """Letter grade for duplication health.

    - A: < 1% of strokes are duplicates
    - B: 1-5%
    - C: 5-15%
    - F: > 15%

    Returns:
        One of "A", "B", "C", "F".
    """
    ratio = duplicate_ratio(path, min_seed_len)
    pct = ratio * 100
    if pct < 1:
        return "A"
    if pct < 5:
        return "B"
    if pct < 15:
        return "C"
    return "F"
