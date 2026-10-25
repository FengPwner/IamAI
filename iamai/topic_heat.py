"""Topic heat — track which themes are hot or cooling in recent notes.

The writer produces hundreds of notes, thoughts, and devlog entries.
A caretaker visiting the repo wants a quick answer to "what has the
writer been thinking about lately, and is it the same as before?"

``topic_heat`` answers this by:

1. **Extracting** topic keywords from note filenames and headings.
2. **Windowing** — splitting notes into a *recent* window and a
   *baseline* window for comparison.
3. **Scoring** each topic with a heat metric:

   - ``hot``     — appears significantly more in recent than baseline
   - ``warm``    — steady presence across both windows
   - ``cooling`` — was common in baseline, fading in recent
   - ``cold``    — absent or nearly absent from recent window

Usage::

    from iamai.topic_heat import topic_heatmap, TopicReport

    report = topic_heatmap(notes_dir="notes", recent_count=20)
    for topic, entry in report.topics.items():
        print(f"{topic}: {entry.heat} (recent={entry.recent_count}, "
              f"baseline={entry.baseline_count})")

    print(report.summary())
    # "8 topics tracked: 2 hot, 3 warm, 2 cooling, 1 cold"

Design choices
--------------

- **Filename-based extraction** — uses ``caretaker-visit-*``, ``stall-*``,
  ``push-*``, ``recovery-*`` etc. as topic signals.  This is cheap and
  avoids parsing full file bodies.
- **Configurable stop words** — generic terms like "visit", "note", and
  "log" are filtered out to avoid noise.
- **Pure function** — takes a list of filenames and returns a report.
  No subprocess calls, no filesystem access in the core logic.
- **Deterministic** — same inputs always produce the same output.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_STOP_WORDS = frozenset({
    "visit", "note", "log", "caretaker", "md", "the", "a", "an",
    "and", "or", "of", "to", "in", "for", "on", "with", "at",
    "is", "it", "my", "this", "that", "was", "are", "be",
})

# Minimum occurrences across both windows to track a topic
MIN_TOTAL_COUNT = 2

# Heat thresholds (ratio of recent_density / baseline_density)
HOT_RATIO = 2.0          # at least 2x denser in recent
COOLING_RATIO = 0.5      # less than half as dense in recent
COLD_THRESHOLD = 0.1     # nearly absent from recent (< 10% of baseline rate)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TopicEntry:
    """Heat status of a single topic."""

    topic: str
    heat: str              # "hot" | "warm" | "cooling" | "cold"
    recent_count: int
    baseline_count: int
    recent_density: float  # count / total_in_window
    baseline_density: float

    def as_dict(self) -> dict:
        return {
            "topic": self.topic,
            "heat": self.heat,
            "recent_count": self.recent_count,
            "baseline_count": self.baseline_count,
            "recent_density": round(self.recent_density, 4),
            "baseline_density": round(self.baseline_density, 4),
        }


@dataclass(frozen=True)
class TopicReport:
    """Aggregated topic heat analysis."""

    topics: Dict[str, TopicEntry]
    recent_window_size: int
    baseline_window_size: int

    def summary(self) -> str:
        """One-liner for caretaker logs."""
        counts: Counter = Counter()
        for entry in self.topics.values():
            counts[entry.heat] += 1
        total = len(self.topics)
        if total == 0:
            return "no topics tracked"
        parts = []
        for heat in ("hot", "warm", "cooling", "cold"):
            if counts[heat]:
                parts.append(f"{counts[heat]} {heat}")
        return f"{total} topics tracked: {', '.join(parts)}"

    def hot_topics(self) -> List[str]:
        """Return topic names sorted by heat descending, then by name."""
        order = {"hot": 0, "warm": 1, "cooling": 2, "cold": 3}
        return sorted(
            self.topics.keys(),
            key=lambda t: (order.get(self.topics[t].heat, 9), t),
        )

    def as_dict(self) -> dict:
        return {
            "topics": {k: v.as_dict() for k, v in self.topics.items()},
            "recent_window_size": self.recent_window_size,
            "baseline_window_size": self.baseline_window_size,
            "summary": self.summary(),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_topics_from_filename(filename: str, stop_words: frozenset) -> List[str]:
    """Extract meaningful topic tokens from a note filename.

    Examples:
        "caretaker-visit-212.md" → []  (all tokens are stop words or numbers)
        "push-race-recovery-2026-10-05.md" → ["push", "race", "recovery"]
        "stall-forecaster-added.md" → ["stall", "forecaster", "added"]
    """
    # Strip extension, split on non-alpha characters
    stem = re.sub(r"\.\w+$", "", filename)
    tokens = re.split(r"[^a-zA-Z]+", stem)
    return [t.lower() for t in tokens if t.lower() not in stop_words and len(t) > 1]


def _compute_density(count: int, window_size: int) -> float:
    """Occurrences per file in the window."""
    if window_size == 0:
        return 0.0
    return count / window_size


def _classify_heat(
    recent_density: float,
    baseline_density: float,
    recent_count: int,
) -> str:
    """Classify a topic's heat level."""
    if baseline_density == 0:
        # Topic only appears in recent window
        return "hot" if recent_count >= MIN_TOTAL_COUNT else "warm"

    ratio = recent_density / baseline_density

    if ratio >= HOT_RATIO:
        return "hot"
    elif ratio <= COLD_THRESHOLD:
        return "cold"
    elif ratio <= COOLING_RATIO:
        return "cooling"
    else:
        return "warm"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_topics(
    filenames: Sequence[str],
    *,
    stop_words: frozenset = DEFAULT_STOP_WORDS,
) -> List[List[str]]:
    """Extract topics from a list of filenames.

    Returns a list of topic-token lists, one per filename.
    Useful for testing and custom aggregation.
    """
    return [_extract_topics_from_filename(f, stop_words) for f in filenames]


def topic_heatmap(
    filenames: Sequence[str],
    *,
    recent_count: int = 20,
    stop_words: frozenset = DEFAULT_STOP_WORDS,
    min_total_count: int = MIN_TOTAL_COUNT,
) -> TopicReport:
    """Analyse topic heat across recent vs baseline windows.

    Args:
        filenames: note filenames, ordered oldest-first.
        recent_count: how many of the most recent filenames form the
            "recent" window; the rest is baseline.
        stop_words: words to exclude from topic extraction.
        min_total_count: minimum total occurrences to track a topic.

    Returns:
        A ``TopicReport`` with per-topic heat classifications.
    """
    if not filenames:
        return TopicReport(topics={}, recent_window_size=0, baseline_window_size=0)

    n = len(filenames)
    split = max(0, n - recent_count)
    baseline_files = list(filenames[:split])
    recent_files = list(filenames[split:])

    # Count topics per window
    baseline_topics: Counter = Counter()
    recent_topics: Counter = Counter()

    for f in baseline_files:
        for token in _extract_topics_from_filename(f, stop_words):
            baseline_topics[token] += 1

    for f in recent_files:
        for token in _extract_topics_from_filename(f, stop_words):
            recent_topics[token] += 1

    # Union of all topics
    all_topics = set(baseline_topics.keys()) | set(recent_topics.keys())

    # Build entries
    entries: Dict[str, TopicEntry] = {}
    for topic in sorted(all_topics):
        rc = recent_topics.get(topic, 0)
        bc = baseline_topics.get(topic, 0)
        total = rc + bc
        if total < min_total_count:
            continue
        rd = _compute_density(rc, len(recent_files))
        bd = _compute_density(bc, len(baseline_files))
        heat = _classify_heat(rd, bd, rc)
        entries[topic] = TopicEntry(
            topic=topic,
            heat=heat,
            recent_count=rc,
            baseline_count=bc,
            recent_density=rd,
            baseline_density=bd,
        )

    return TopicReport(
        topics=entries,
        recent_window_size=len(recent_files),
        baseline_window_size=len(baseline_files),
    )


def topic_heatmap_from_dir(
    notes_dir: str = "notes",
    *,
    recent_count: int = 20,
    pattern: str = "*.md",
) -> TopicReport:
    """Convenience: read a directory and run topic_heatmap.

    Args:
        notes_dir: path to the notes directory.
        recent_count: size of the recent window.
        pattern: glob pattern for note files.

    Returns:
        A ``TopicReport``.
    """
    from pathlib import Path

    dir_path = Path(notes_dir)
    if not dir_path.is_dir():
        return TopicReport(topics={}, recent_window_size=0, baseline_window_size=0)

    filenames = sorted(f.name for f in dir_path.glob(pattern))
    return topic_heatmap(filenames, recent_count=recent_count)
