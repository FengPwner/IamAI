#!/usr/bin/env python3
"""writer_temporal_awareness — measure how well writing handles time.

Temporal awareness is about *time consciousness in prose*.  Does the
writer know when things happened?  Does it tell the reader?  Does time
move forward consistently, or jump around without warning?  Are events
anchored to specific moments, or do they float in timeless abstraction?

This module is orthogonal to the other writer metrics:

- **readability** tracks whether prose is *easy to parse*.  A text can
  be readable while being temporally disorienting — each sentence is
  simple to read, but the reader cannot tell whether events happened
  yesterday or last year.  Readability is about effort per sentence;
  temporal awareness is about whether the reader knows *when*.

- **coherence** tracks whether ideas *connect*.  A text can be coherent
  (each sentence flows logically from the last) while being temporally
  confused — "The server crashed because the deploy key expired.  The
  deploy key will expire tomorrow." — logically connected, temporally
  contradictory.  Coherence is about logical linkage; temporal
  awareness is about temporal consistency and grounding.

- **specificity** tracks whether prose names *concrete things*.  A text
  can be specific ("Python 3.12", "port 8080") while being temporally
  vague ("recently", "at some point", "after a while").  Specificity
  is about precision of *what*; temporal awareness is about precision
  of *when*.

- **concision** tracks whether prose uses *more words than needed*.
  Concision is about economy; temporal awareness is about time
  anchoring.

- **signal_clarity** tracks whether strokes are *substantively unique*.
  A writer can produce unique, temporally-anchored strokes that use
  inconsistent tenses.  Clarity is about uniqueness; temporal
  awareness is about time handling.

- **vocabulary_richness** tracks *diversity* of word choice.  A text
  can use rich temporal vocabulary while being inconsistent (mixing
  past and future tense in the same paragraph).  Richness is about
  diversity; temporal awareness is about consistency and anchoring.

- **prose_rhythm** tracks *variation* in sentence length.  Rhythm is
  structural; temporal awareness is semantic and chronological.

- **grounding_density** tracks whether claims are *anchored in evidence*.
  Grounding asks "is there a source?"  Temporal awareness asks "is there
  a *when*?" — a timestamp, a date, a time reference.  Grounded but
  temporally-vague text cites a study without saying when it was
  conducted.

Temporal awareness asks: **does the reader know when this happened, how
long it took, and whether the next event came before or after?**

Five signals are tracked:

1. **Tense consistency** — whether the writer maintains consistent verb
   tense within a passage.  Measured as 1 minus the coefficient of
   variation of tense shifts per sentence.  A passage that stays in
   past tense throughout scores 1.0; one that flip-flops between past,
   present, and future scores lower.  Legitimate tense shifts (e.g.,
   "The server crashed.  It is now running.") are detected via temporal
   transition markers and excluded from penalty.

2. **Temporal anchoring** — fraction of sentences that contain at least
   one explicit time reference: an ISO date (2026-11-12), a clock time
   (14:32), a named period ("last week", "this morning", "in October"),
   or a relative temporal expression ("three days ago", "after the
   restart").  A text where every sentence is anchored scores 1.0; a
   text with no time references scores 0.0.

3. **Temporal progression** — whether explicit time references move
   forward through the text.  Each timestamped sentence is compared to
   the previous one; if the time moves forward, it scores 1; if backward
   (without a flashback marker like "earlier", "previously", "before"),
   it scores 0; if the same time, 0.5.  Final score is the fraction of
   forward-moving pairs.

4. **Duration awareness** — whether the writer marks how long things
   took or lasted.  Measured as the density of duration expressions
   per hundred words: "for 48 hours", "over three days", "in 2.5
   seconds", "a week later".  Higher density means the writer is
   aware of elapsed time, not just point-in-time.

5. **Temporal marker density** — frequency of temporal words and
   phrases per hundred words.  Includes: point-in-time markers
   ("now", "then", "today", "yesterday", "tomorrow", "currently",
   "recently", "previously"), sequence markers ("before", "after",
   "during", "while", "since", "until", "meanwhile", "subsequently"),
   and frequency markers ("always", "never", "often", "sometimes",
   "occasionally", "daily", "weekly").  Higher density means the
   writer is more time-conscious.

The **temporal_awareness_index** is computed as a weighted composite:

    index = tense_consistency     * 0.20
          + temporal_anchoring    * 0.30
          + temporal_progression  * 0.20
          + duration_awareness    * 0.15
          + temporal_marker_density * 0.15

Classified as:

- **chronological** (>= 0.80): time-aware writing; the reader always
  knows when things happened and how they relate chronologically.
- **grounded** (>= 0.60): mostly time-anchored with occasional gaps.
- **adequate** (>= 0.40): mixed — some temporal grounding but frequent
  timeless abstractions.
- **vague** (>= 0.20): time is mostly absent; the reader cannot tell
  when things happened or how long they took.
- **timeless** (< 0.20): no temporal awareness; the text exists outside
  of time entirely.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Point-in-time markers
TEMPORAL_POINT: list[str] = [
    "now", "then", "today", "yesterday", "tomorrow", "tonight",
    "currently", "recently", "previously", "lately", "already",
    "just", "immediately", "instantly", "shortly", "presently",
    "this morning", "this afternoon", "this evening", "last night",
    "last week", "last month", "last year", "this week", "this month",
    "this year", "next week", "next month", "next year",
]

# Sequence / ordering markers
TEMPORAL_SEQUENCE: list[str] = [
    "before", "after", "during", "while", "since", "until", "till",
    "meanwhile", "subsequently", "afterward", "afterwards", "then",
    "next", "finally", "first", "second", "third", "initially",
    "eventually", "ultimately", "henceforth", "thereafter",
    "from then on", "from now on", "at the same time", "in the meantime",
]

# Frequency markers
TEMPORAL_FREQUENCY: list[str] = [
    "always", "never", "often", "sometimes", "occasionally", "rarely",
    "seldom", "frequently", "usually", "generally", "normally",
    "regularly", "constantly", "continually", "periodically",
    "daily", "weekly", "monthly", "yearly", "annually",
    "once", "twice", "every day", "every week", "every month",
]

# Flashback markers (legitimate backward time jumps)
FLASHBACK_MARKERS: list[str] = [
    "earlier", "previously", "before", "prior to", "formerly",
    "originally", "initially", "at first", "in the beginning",
    "back then", "in those days", "once upon a time",
    "looking back", "retrospectively", "historically",
]

ALL_TEMPORAL_MARKERS: list[str] = list(dict.fromkeys(
    TEMPORAL_POINT + TEMPORAL_SEQUENCE + TEMPORAL_FREQUENCY
))

# Past tense indicators: common irregular past-tense verbs
PAST_TENSE_VERBS: list[str] = [
    "was", "were", "had", "did", "said", "went", "came", "made",
    "found", "gave", "told", "thought", "knew", "took", "saw",
    "got", "ran", "wrote", "read", "set", "put", "left", "held",
    "built", "sent", "brought", "began", "kept", "let", "seemed",
    "helped", "showed", "heard", "played", "moved", "lived",
    "believed", "started", "passed", "changed", "followed", "stopped",
    "created", "opened", "reached", "decided", "returned", "developed",
    "worked", "became", "grew", "turned", "fell", "led", "broke",
    "drove", "chose", "spoke", "stood", "lost", "paid", "met",
    "won", "rose", "drew", "wore", "hid", "ate", "drank", "swam",
    "flew", "threw", "blew", "knew", "shook", "froze", "woke",
    "spoke", "stole", "swore", "tore", "rode", "forgot", "forgave",
    "crashed", "failed", "expired", "deployed", "pushed", "pulled",
    "committed", "merged", "rebased", "cloned", "forked", "logged",
    "measured", "tracked", "counted", "recorded", "reported",
]

# Present tense indicators
PRESENT_TENSE_VERBS: list[str] = [
    "is", "are", "am", "has", "have", "does", "says", "goes", "comes",
    "makes", "finds", "gives", "tells", "thinks", "knows", "takes",
    "sees", "gets", "runs", "writes", "reads", "sets", "puts",
    "leaves", "holds", "builds", "sends", "brings", "begins", "keeps",
    "lets", "seems", "helps", "shows", "hears", "plays", "moves",
    "lives", "believes", "starts", "passes", "changes", "follows",
    "stops", "creates", "opens", "reaches", "decides", "returns",
    "develops", "works", "becomes", "grows", "turns", "falls", "leads",
    "breaks", "drives", "chooses", "speaks", "stands", "loses", "pays",
    "meets", "wins", "rises", "draws", "wears", "hides", "eats",
    "drinks", "measures", "tracks", "counts", "records", "reports",
]

# Future tense indicators
FUTURE_INDICATORS: list[str] = [
    "will", "shall", "going to", "about to", "plan to", "expect to",
    "intend to", "aim to", "scheduled to", "supposed to", "due to",
    "will be", "will have", "shall be", "shall have",
]

# Duration patterns
DURATION_PATTERNS: list[str] = [
    # "for X hours/days/weeks/months/years/minutes/seconds"
    r"for\s+\d+[\d,.]*\s+(?:hour|minute|second|day|week|month|year)s?",
    r"for\s+\w+\s+(?:hour|minute|second|day|week|month|year)s?",
    # "in X hours/days/weeks/months/years/minutes/seconds"
    r"in\s+\d+[\d,.]*\s+(?:hour|minute|second|day|week|month|year)s?",
    # "X hours/days/weeks/months/years later/ago"
    r"\d+[\d,.]*\s+(?:hour|minute|second|day|week|month|year)s?\s+(?:later|ago)",
    r"\w+\s+(?:hour|minute|second|day|week|month|year)s?\s+(?:later|ago)",
    # "over/past/last X hours/days/weeks/months/years"
    r"(?:over|past|last)\s+\d+[\d,.]*\s+(?:hour|minute|second|day|week|month|year)s?",
    r"(?:over|past|last)\s+\w+\s+(?:hour|minute|second|day|week|month|year)s?",
    # "X.X seconds/minutes/hours"
    r"\d+\.\d+\s+(?:second|minute|hour|millisecond)s?",
    # "a while", "a moment", "a bit"
    r"a\s+(?:while|moment|bit|second|minute|hour|day|week|month|year)",
]

# ISO date pattern: YYYY-MM-DD
ISO_DATE_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?\b"
)

# Clock time pattern: HH:MM or HH:MM:SS
CLOCK_TIME_RE = re.compile(
    r"\b(?:\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp][Mm])?)\b"
)

# Named month pattern
NAMED_MONTHS: list[str] = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
]

NAMED_PERIOD_RE = re.compile(
    r"\b(?:"
    r"(?:last|this|next)\s+(?:monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|week|month|year|quarter|spring|summer|autumn|fall|winter|"
    r"morning|afternoon|evening|night)"
    r"|in\s+(?:the\s+)?(?:morning|afternoon|evening|night)"
    r"|in\s+(?:january|february|march|april|may|june|july|august|"
    r"september|october|november|december)"
    r"|\d{1,2}(?:st|nd|rd|th)\s+of\s+(?:january|february|march|april|may|"
    r"june|july|august|september|october|november|december)"
    r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    # Handle common abbreviations
    text = re.sub(r"\b(?:Dr|Mr|Mrs|Ms|Sr|Jr|St|vs|etc|i\.e|e\.g)\.",
                  lambda m: m.group().replace(".", "@@"), text)
    sentences = re.split(r"[.!?]+", text)
    result = []
    for s in sentences:
        s = s.replace("@@", ".").strip()
        if s:
            result.append(s)
    return result


def _split_words(text: str) -> list[str]:
    """Split text into lowercase words, excluding pure numbers."""
    words = re.findall(r"[a-zA-Z][a-zA-Z']*", text.lower())
    return words


def _get_stroke_text(stroke: dict[str, Any]) -> str:
    """Extract text from a stroke dict."""
    if isinstance(stroke, dict):
        return stroke.get("text", "")
    return ""


def _word_count(text: str) -> int:
    """Count words in text."""
    return len(_split_words(text))


def _detect_tense(sentence: str) -> str:
    """Detect the dominant tense of a sentence.

    Returns 'past', 'present', 'future', or 'ambiguous'.
    """
    lower = sentence.lower()
    words = _split_words(lower)

    past_score = 0
    present_score = 0
    future_score = 0

    for w in words:
        if w in PAST_TENSE_VERBS:
            past_score += 1
        if w in PRESENT_TENSE_VERBS:
            present_score += 1

    # Check for future indicators (multi-word)
    for fi in FUTURE_INDICATORS:
        if fi in lower:
            future_score += 2

    # Check -ed suffix (weak past signal)
    ed_count = sum(1 for w in words if w.endswith("ed") and len(w) > 3
                   and w not in PAST_TENSE_VERBS and w not in PRESENT_TENSE_VERBS)
    past_score += ed_count * 0.5

    # Check -s suffix (weak present signal, excluding plurals — heuristic)
    s_count = sum(1 for w in words if w.endswith("s") and len(w) > 3
                  and w not in PAST_TENSE_VERBS and w not in PRESENT_TENSE_VERBS
                  and w[-2] not in "s'")
    present_score += s_count * 0.3

    max_score = max(past_score, present_score, future_score)
    if max_score == 0:
        return "ambiguous"

    if past_score == max_score and past_score > present_score:
        return "past"
    if future_score == max_score and future_score > present_score:
        return "future"
    if present_score == max_score and present_score > past_score:
        return "present"

    return "ambiguous"


def _has_temporal_anchor(sentence: str) -> bool:
    """Check if a sentence contains an explicit time reference."""
    lower = sentence.lower()

    # ISO date
    if ISO_DATE_RE.search(sentence):
        return True

    # Clock time
    if CLOCK_TIME_RE.search(sentence):
        return True

    # Named period (last week, this morning, etc.)
    if NAMED_PERIOD_RE.search(sentence):
        return True

    # Relative temporal expression with number (digit or word)
    if re.search(r"\d+\s+\w+\s+(?:ago|later|before|after|hence)", lower):
        return True
    if re.search(r"(?:ago|later|before|after|hence)\s+\d+", lower):
        return True
    # Word-number relative time: "three days ago", "two hours later"
    if re.search(
        r"(?:one|two|three|four|five|six|seven|eight|nine|ten|"
        r"eleven|twelve|a|an|half|quarter)\s+"
        r"(?:second|minute|hour|day|week|month|year)s?\s+"
        r"(?:ago|later|before|after|hence)",
        lower,
    ):
        return True

    # Named month + optional day/year
    for month in NAMED_MONTHS:
        if month in lower:
            return True

    return False


def _extract_timestamp(sentence: str) -> float | None:
    """Extract a sortable timestamp from a sentence, if present.

    Returns a float for comparison, or None if no timestamp found.
    Higher values = later in time.
    """
    # ISO date: most precise
    iso_match = ISO_DATE_RE.search(sentence)
    if iso_match:
        ts = iso_match.group()
        # Normalize to sortable number
        # 2026-11-12T14:32:07Z -> 20261112.143207
        clean = ts.replace("-", "").replace(":", "").replace("T", ".").replace("Z", "")
        if "+" in clean:
            clean = clean[:clean.index("+")]
        try:
            return float(clean)
        except ValueError:
            pass

    # Clock time (less precise, but sortable within a day)
    clock_match = CLOCK_TIME_RE.search(sentence)
    if clock_match:
        parts = clock_match.group().split(":")
        try:
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            s = int(parts[2].rstrip("APapm ").rstrip()) if len(parts) > 2 else 0
            return h * 3600 + m * 60 + s
        except (ValueError, IndexError):
            pass

    return None


def _has_flashback_marker(sentence: str) -> bool:
    """Check if a sentence contains a flashback indicator."""
    lower = sentence.lower()
    return any(m in lower for m in FLASHBACK_MARKERS)


def _has_duration(text: str) -> bool:
    """Check if text contains a duration expression."""
    lower = text.lower()
    for pattern in DURATION_PATTERNS:
        if re.search(pattern, lower):
            return True
    return False


def _count_temporal_markers(text: str) -> int:
    """Count temporal marker occurrences in text."""
    lower = text.lower()
    count = 0
    for marker in ALL_TEMPORAL_MARKERS:
        # Use word boundary matching to avoid partial matches
        pattern = r"\b" + re.escape(marker) + r"\b"
        count += len(re.findall(pattern, lower))
    return count


# ---------------------------------------------------------------------------
# Signal 1: Tense consistency
# ---------------------------------------------------------------------------


def compute_tense_consistency(text: str) -> float:
    """Compute tense consistency score (0-1).

    Measures whether the writer maintains consistent verb tense.
    A score of 1.0 means the tense never changes (or only changes
    at legitimate transition points).  A score of 0.0 means the
    tense changes at every sentence.
    """
    sentences = _split_sentences(text)
    if len(sentences) < 2:
        return 1.0

    tenses = [_detect_tense(s) for s in sentences]
    # Filter out ambiguous (tense-less) sentences
    clear_tenses = [(i, t) for i, t in enumerate(tenses) if t != "ambiguous"]

    if len(clear_tenses) < 2:
        return 1.0

    # Count legitimate vs illegitimate tense shifts
    shifts = 0
    legitimate_shifts = 0
    total_pairs = 0

    for idx in range(len(clear_tenses) - 1):
        i1, t1 = clear_tenses[idx]
        i2, t2 = clear_tenses[idx + 1]

        if t1 != t2:
            total_pairs += 1
            # Check if the second sentence has a temporal marker
            # that justifies the tense shift
            sentence2 = sentences[i2] if i2 < len(sentences) else ""
            if _has_temporal_anchor(sentence2) or _has_flashback_marker(sentence2):
                legitimate_shifts += 1
            else:
                shifts += 1

    if total_pairs == 0:
        return 1.0

    # Score: fraction of pairs that are either same-tense or legitimately shifted
    return 1.0 - (shifts / (total_pairs + legitimate_shifts))


# ---------------------------------------------------------------------------
# Signal 2: Temporal anchoring
# ---------------------------------------------------------------------------


def compute_temporal_anchoring(text: str) -> float:
    """Compute temporal anchoring score (0-1).

    Fraction of sentences containing at least one explicit time reference.
    """
    sentences = _split_sentences(text)
    if not sentences:
        return 0.0

    anchored = sum(1 for s in sentences if _has_temporal_anchor(s))
    return anchored / len(sentences)


# ---------------------------------------------------------------------------
# Signal 3: Temporal progression
# ---------------------------------------------------------------------------


def compute_temporal_progression(text: str) -> float:
    """Compute temporal progression score (0-1).

    Measures whether explicit time references move forward through text.
    A score of 1.0 means time always moves forward; 0.0 means it always
    jumps backward without flashback markers.
    """
    sentences = _split_sentences(text)
    if len(sentences) < 2:
        return 1.0

    # Extract timestamps from sentences
    timestamped = []
    for i, s in enumerate(sentences):
        ts = _extract_timestamp(s)
        if ts is not None:
            timestamped.append((i, ts, s))

    if len(timestamped) < 2:
        return 0.5  # Cannot assess without timestamps

    forward = 0
    backward = 0
    same = 0

    for idx in range(len(timestamped) - 1):
        i1, ts1, s1 = timestamped[idx]
        i2, ts2, s2 = timestamped[idx + 1]

        if ts2 > ts1:
            forward += 1
        elif ts2 < ts1:
            if _has_flashback_marker(s2):
                forward += 1  # Legitimate backward jump
            else:
                backward += 1
        else:
            same += 1

    total = forward + backward + same
    if total == 0:
        return 0.5

    # Forward and same-time are good; backward without marker is bad
    return (forward + same * 0.5) / total


# ---------------------------------------------------------------------------
# Signal 4: Duration awareness
# ---------------------------------------------------------------------------


def compute_duration_awareness(text: str) -> float:
    """Compute duration awareness score (0-1).

    Density of duration expressions per hundred words, capped at 1.0
    for 5+ durations per hundred words.
    """
    words = _split_words(text)
    if len(words) < 10:
        return 0.0

    sentences = _split_sentences(text)
    duration_count = sum(1 for s in sentences if _has_duration(s))

    # Normalize: per 100 words, capped at 5 per 100 = 1.0
    density = (duration_count / len(words)) * 100
    return min(density / 5.0, 1.0)


# ---------------------------------------------------------------------------
# Signal 5: Temporal marker density
# ---------------------------------------------------------------------------


def compute_temporal_marker_density(text: str) -> float:
    """Compute temporal marker density score (0-1).

    Frequency of temporal words/phrases per hundred words, capped at
    1.0 for 8+ markers per hundred words.
    """
    words = _split_words(text)
    if len(words) < 10:
        return 0.0

    marker_count = _count_temporal_markers(text)

    # Normalize: per 100 words, capped at 8 per 100 = 1.0
    density = (marker_count / len(words)) * 100
    return min(density / 8.0, 1.0)


# ---------------------------------------------------------------------------
# Composite index
# ---------------------------------------------------------------------------


def compute_temporal_awareness_index(
    tense_consistency: float,
    temporal_anchoring: float,
    temporal_progression: float,
    duration_awareness: float,
    temporal_marker_density: float,
) -> float:
    """Compute weighted composite temporal awareness index."""
    index = (
        tense_consistency * 0.20
        + temporal_anchoring * 0.30
        + temporal_progression * 0.20
        + duration_awareness * 0.15
        + temporal_marker_density * 0.15
    )
    return round(index, 4)


def classify_temporal_awareness(index: float) -> str:
    """Classify temporal awareness level from index value."""
    if index >= 0.80:
        return "chronological"
    if index >= 0.60:
        return "grounded"
    if index >= 0.40:
        return "adequate"
    if index >= 0.20:
        return "vague"
    return "timeless"


# ---------------------------------------------------------------------------
# Metrics aggregation
# ---------------------------------------------------------------------------


def compute_temporal_awareness_metrics(
    strokes: list[dict[str, Any]], window_size: int = 50
) -> dict[str, Any]:
    """Compute temporal awareness metrics from a list of strokes.

    Parameters
    ----------
    strokes : list
        List of stroke dicts with 'text' field.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict
        Temporal awareness metrics.
    """
    recent = strokes[-window_size:] if len(strokes) > window_size else strokes
    texts = [_get_stroke_text(s) for s in recent if _get_stroke_text(s)]

    if not texts:
        return _empty_metrics()

    combined = " ".join(texts)

    tc = compute_tense_consistency(combined)
    ta = compute_temporal_anchoring(combined)
    tp = compute_temporal_progression(combined)
    da = compute_duration_awareness(combined)
    tm = compute_temporal_marker_density(combined)
    idx = compute_temporal_awareness_index(tc, ta, tp, da, tm)

    return {
        "tense_consistency": round(tc, 4),
        "temporal_anchoring": round(ta, 4),
        "temporal_progression": round(tp, 4),
        "duration_awareness": round(da, 4),
        "temporal_marker_density": round(tm, 4),
        "temporal_awareness_index": idx,
        "classification": classify_temporal_awareness(idx),
        "strokes_analyzed": len(texts),
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "tense_consistency": 1.0,
        "temporal_anchoring": 0.0,
        "temporal_progression": 0.5,
        "duration_awareness": 0.0,
        "temporal_marker_density": 0.0,
        "temporal_awareness_index": 0.25,
        "classification": "vague",
        "strokes_analyzed": 0,
    }


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------


def compute_temporal_awareness_trend(
    strokes: list[dict[str, Any]], window_size: int = 50
) -> list[dict[str, Any]]:
    """Compute temporal awareness index over sliding windows.

    Returns a list of dicts with 'window_start', 'window_end',
    'temporal_awareness_index', 'classification'.
    """
    if len(strokes) < window_size:
        metrics = compute_temporal_awareness_metrics(strokes, window_size)
        return [
            {
                "window_start": 0,
                "window_end": len(strokes),
                "temporal_awareness_index": metrics["temporal_awareness_index"],
                "classification": metrics["classification"],
            }
        ]

    trends = []
    step = max(window_size // 2, 1)
    for start in range(0, len(strokes) - window_size + 1, step):
        window = strokes[start : start + window_size]
        metrics = compute_temporal_awareness_metrics(window, window_size)
        trends.append(
            {
                "window_start": start,
                "window_end": start + window_size,
                "temporal_awareness_index": metrics["temporal_awareness_index"],
                "classification": metrics["classification"],
            }
        )
    return trends


def classify_trend(trend: list[dict[str, Any]]) -> str:
    """Classify the overall trend direction.

    Returns 'improving', 'stable', or 'declining'.
    """
    if len(trend) < 2:
        return "stable"

    first_half = trend[: len(trend) // 2]
    second_half = trend[len(trend) // 2 :]

    avg_first = (
        sum(t["temporal_awareness_index"] for t in first_half) / len(first_half)
    )
    avg_second = (
        sum(t["temporal_awareness_index"] for t in second_half) / len(second_half)
    )

    delta = avg_second - avg_first
    if delta > 0.05:
        return "improving"
    if delta < -0.05:
        return "declining"
    return "stable"


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


def analyze_stroke_temporal_awareness(stroke: dict[str, Any]) -> dict[str, Any]:
    """Analyze temporal awareness for a single stroke."""
    text = _get_stroke_text(stroke)
    if not text:
        return _empty_metrics()

    tc = compute_tense_consistency(text)
    ta = compute_temporal_anchoring(text)
    tp = compute_temporal_progression(text)
    da = compute_duration_awareness(text)
    tm = compute_temporal_marker_density(text)
    idx = compute_temporal_awareness_index(tc, ta, tp, da, tm)

    return {
        "tense_consistency": round(tc, 4),
        "temporal_anchoring": round(ta, 4),
        "temporal_progression": round(tp, 4),
        "duration_awareness": round(da, 4),
        "temporal_marker_density": round(tm, 4),
        "temporal_awareness_index": idx,
        "classification": classify_temporal_awareness(idx),
        "strokes_analyzed": 1,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def format_temporal_awareness_report(metrics: dict[str, Any]) -> str:
    """Format temporal awareness metrics as a human-readable report."""
    if metrics["strokes_analyzed"] == 0:
        return "No strokes analyzed."

    lines = [
        f"Temporal Awareness Report ({metrics['strokes_analyzed']} strokes)",
        "=" * 60,
        f"  Temporal Awareness Index:  {metrics['temporal_awareness_index']:.4f}"
        f"  [{metrics['classification']}]",
        f"  Tense Consistency:         {metrics['tense_consistency']:.4f}"
        " (0-1, higher is better)",
        f"  Temporal Anchoring:        {metrics['temporal_anchoring']:.4f}"
        " (0-1, higher is better)",
        f"  Temporal Progression:      {metrics['temporal_progression']:.4f}"
        " (0-1, higher is better)",
        f"  Duration Awareness:        {metrics['duration_awareness']:.4f}"
        " (0-1, higher is better)",
        f"  Temporal Marker Density:   {metrics['temporal_marker_density']:.4f}"
        " (per 100 words, higher is better)",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def analyze_temporal_awareness(
    strokes_path: str | Path = "data/strokes.jsonl",
    window_size: int = 50,
) -> dict[str, Any]:
    """Analyze temporal awareness from a strokes JSONL file.

    Parameters
    ----------
    strokes_path : str
        Path to strokes JSONL file.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict
        Temporal awareness metrics.
    """
    path = Path(strokes_path)
    if not path.exists():
        return _empty_metrics()

    strokes: list[dict[str, Any]] = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    strokes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    return compute_temporal_awareness_metrics(strokes, window_size)


if __name__ == "__main__":
    metrics = analyze_temporal_awareness()
    print(format_temporal_awareness_report(metrics))
