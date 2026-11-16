#!/usr/bin/env python3
"""writer_urgency_density — measure how much prose signals time pressure.

Urgency is the linguistic signal that something must happen *soon*
or an opportunity will be lost, a consequence will arrive, or a
window will close.  It is not volume and it is not emotion — a
calm sentence like "Applications close at midnight tonight" can
carry more urgency than a paragraph of exclamation marks.

Urgency manifests through six measurable channels.

**Temporal pressure markers** compress the timeline: *now,
immediately, urgently, at once, right away, without delay,
shortly, presently, forthwith, before long, any moment,
momentarily*.  They shrink the gap between reading and acting.

**Deadline and countdown language** sets explicit boundaries:
*deadline, expires, closes, ends, cutoff, final day, last chance,
last call, closing soon, ending soon, time running out, clock
ticking, window closing, hours left, days remaining*.  They turn
an open-ended choice into a bounded one.

**Scarcity signals** suggest limited availability: *limited,
exclusive, rare, fleeting, vanishing, finite, only a few,
once in a lifetime, never again, one time only, while supplies
last, first come first served*.  They trigger loss aversion by
implying that delay means disappearance.

**Consequence proximity** links inaction to near-term negative
outcomes: *otherwise, or else, unless, at risk, at stake,
failure to act, delay costs, the longer you wait, every day
without, procrastination, missed opportunity, falling behind,
left behind, too late*.  They make the cost of waiting concrete.

**Imperative urgency signals** combine command form with time
pressure: *act now, do not wait, hurry, rush, seize, grab,
jump on, take advantage, move quickly, get started, begin now,
start today, do not delay, do not miss*.  They pair instruction
with immediacy.

**Present-tense immediacy** uses grammatical aspect to signal
that events are unfolding right now: *is happening, are running,
has just, right now, at this moment, as we speak, even now,
already underway, currently in progress, as of today*.  They
collapse the distance between report and reality.

A text with high urgency density reads like an alert or a
closing pitch — every sentence pushes toward immediate action.
A text with low urgency density reads like a meditation or a
reference — there is no particular reason to act today rather
than tomorrow.  Neither is inherently better: emergency
communication earns its urgency through genuine stakes; marketing
copy borrows urgency from artificial scarcity.  Knowing where a
text sits on this spectrum helps calibrate it for its audience.

This module measures urgency density as a composite index
(0.0 – 1.0) across six independent channels, orthogonal to
pacing (which measures how quickly prose moves through ideas),
momentum (which measures argumentative force), certainty (which
measures commitment to claims), formality (which measures
register), and verbosity (which measures padding).

written by Qwen during manual caretaker visit 651, 2026-11-16
"""

import re
from dataclasses import dataclass, field
from typing import List


# ── regex patterns ──────────────────────────────────────────────

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_SPLIT = re.compile(r"[a-zA-Z'-]+")


# ── channel 1: temporal pressure markers ────────────────────────
# Single words that compress the timeline.

_TEMPORAL_SINGLE = set(
    w.lower()
    for w in [
        # Immediate-present adverbs
        "now", "immediately", "urgently", "instantly", "promptly",
        "forthwith", "presently", "shortly", "momentarily",
        "imminent", "imminently",
        # Compression phrases (single-word components)
        "today", "tonight", "nowadays",
        # Urgency adverbs
        "hastily", "hurriedly", "quickly", "swiftly", "rapidly",
        "speedily", "briskly",
    ]
)

_TEMPORAL_PHRASES = {
    "right away",
    "at once",
    "without delay",
    "without further delay",
    "before long",
    "any moment",
    "at any moment",
    "in a matter of moments",
    "in a matter of hours",
    "in a matter of days",
    "as soon as possible",
    "as quickly as possible",
    "as fast as possible",
    "with all due speed",
    "post haste",
    "without hesitation",
    "right now",
    "this instant",
    "this very moment",
    "no time to waste",
    "no time to lose",
    "there is no time",
    "time is short",
    "time is of the essence",
    "every second counts",
    "every moment counts",
    "every minute counts",
}


# ── channel 2: deadline and countdown language ──────────────────

_DEADLINE_SINGLE = set(
    w.lower()
    for w in [
        "deadline", "deadlines",
        "expires", "expired", "expiring", "expiry", "expiration",
        "cutoff",
        "countdown",
        "final", "finale",
    ]
)

_DEADLINE_PHRASES = {
    "last chance",
    "last call",
    "last opportunity",
    "last day",
    "last hour",
    "last minute",
    "closing soon",
    "ending soon",
    "coming to an end",
    "drawing to a close",
    "time running out",
    "time is running out",
    "running out of time",
    "clock is ticking",
    "clock ticking",
    "ticking clock",
    "window closing",
    "window is closing",
    "closing window",
    "hours left",
    "days left",
    "days remaining",
    "hours remaining",
    "time left",
    "time remaining",
    "until midnight",
    "until noon",
    "before midnight",
    "end of day",
    "end of week",
    "end of month",
    "by tomorrow",
    "by tonight",
    "by the end of",
    "approaching deadline",
    "looming deadline",
    "hard deadline",
    "firm deadline",
    "strict deadline",
}


# ── channel 3: scarcity signals ─────────────────────────────────

_SCARCITY_SINGLE = set(
    w.lower()
    for w in [
        "limited", "scarce", "finite", "rare", "fleeting",
        "vanishing", "dwindling", "shrinking", "depleting",
        "exclusive", "irreplaceable",
    ]
)

_SCARCITY_PHRASES = {
    "once in a lifetime",
    "once-in-a-lifetime",
    "never again",
    "one time only",
    "one-time only",
    "while supplies last",
    "while stock lasts",
    "first come first served",
    "first-come first-served",
    "only a few",
    "only a handful",
    "only a limited number",
    "limited availability",
    "limited supply",
    "limited edition",
    "limited time",
    "limited offer",
    "limited spots",
    "limited seats",
    "few remaining",
    "very few left",
    "almost gone",
    "nearly gone",
    "selling out",
    "sold out",
    "going fast",
    "moving fast",
    "filling up",
    "capacity reached",
    "no longer available",
    "no more available",
    "discontinued",
    "final batch",
    "final run",
}


# ── channel 4: consequence proximity ────────────────────────────

_CONSEQUENCE_SINGLE = set(
    w.lower()
    for w in [
        "otherwise", "risk", "risks", "risky",
        "jeopardy", "peril", "stake", "stakes",
        "consequences", "repercussions", "fallout",
        "procrastination", "procrastinate", "procrastinating",
    ]
)

_CONSEQUENCE_PHRASES = {
    "or else",
    "at risk",
    "at stake",
    "at your peril",
    "failure to act",
    "fail to act",
    "delay costs",
    "cost of delay",
    "cost of waiting",
    "cost of inaction",
    "the longer you wait",
    "the longer we wait",
    "every day without",
    "every day that passes",
    "every moment without",
    "missed opportunity",
    "miss the opportunity",
    "missed chance",
    "miss this chance",
    "falling behind",
    "fall behind",
    "getting left behind",
    "left behind",
    "too late",
    "it will be too late",
    "before it is too late",
    "before it's too late",
    "regret it later",
    "you will regret",
    "miss out",
    "missing out",
    "lose the chance",
    "lost opportunity",
    "opportunity cost",
    "pay the price",
    "suffer the consequences",
    "face the consequences",
    "bear the consequences",
}


# ── channel 5: imperative urgency signals ───────────────────────

_IMPERATIVE_PHRASES = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bact\s+now\b",
        r"\bdo\s+not\s+wait\b",
        r"\bdon'?t\s+wait\b",
        r"\bdo\s+not\s+delay\b",
        r"\bdon'?t\s+delay\b",
        r"\bdo\s+not\s+miss\b",
        r"\bdon'?t\s+miss\b",
        r"\bdo\s+not\s+hesitate\b",
        r"\bdon'?t\s+hesitate\b",
        r"\bhurry\s+up\b",
        r"\bseize\s+the\s+(moment|opportunity|day|chance)\b",
        r"\bgrab\s+(this|your|the)\b",
        r"\bjump\s+on\s+(this|it|the)\b",
        r"\btake\s+advantage\s+(of|now|before)\b",
        r"\bmove\s+quickly\b",
        r"\bact\s+fast\b",
        r"\bact\s+quickly\b",
        r"\bact\s+immediately\b",
        r"\bstart\s+(today|now|right\s+now|immediately)\b",
        r"\bbegin\s+(today|now|right\s+now|immediately)\b",
        r"\bget\s+started\s+(today|now|right\s+now)\b",
        r"\bsign\s+up\s+(today|now|right\s+now)\b",
        r"\bregister\s+(today|now|right\s+now|before)\b",
        r"\border\s+(today|now|right\s+now|before)\b",
        r"\bbuy\s+(today|now|right\s+now|before)\b",
        r"\bapply\s+(today|now|right\s+now|before)\b",
        r"\bjoin\s+(today|now|right\s+now|before)\b",
        r"\breserv(e|ing)\s+(your\s+spot|now|today)\b",
        r"\block\s+in\s+(your|this|the)\b",
    ]
]


# ── channel 6: present-tense immediacy ──────────────────────────

_IMMEDIACY_PHRASES = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bis\s+happening\b",
        r"\bare\s+happening\b",
        r"\bis\s+underway\b",
        r"\bare\s+underway\b",
        r"\balready\s+underway\b",
        r"\bcurrently\s+in\s+progress\b",
        r"\bin\s+progress\b",
        r"\bas\s+we\s+speak\b",
        r"\bas\s+of\s+today\b",
        r"\bas\s+of\s+now\b",
        r"\bat\s+this\s+(very\s+)?moment\b",
        r"\b(even|right)\s+now\b",
        r"\bhas\s+just\b",
        r"\bhave\s+just\b",
        r"\bjust\s+(announced|launched|released|opened|started|begun|confirmed|revealed|unveiled)\b",
        r"\bunfolding\s+(now|today|before)\b",
        r"\bhappening\s+(right\s+)?now\b",
        r"\bgoing\s+on\s+(right\s+)?now\b",
    ]
]


# ── helpers ─────────────────────────────────────────────────────


def _count_sentences(text: str) -> int:
    parts = _SENTENCE_SPLIT.split(text.strip())
    return len([p for p in parts if p.strip()])


def _count_words(text: str) -> int:
    return len(_WORD_SPLIT.findall(text))


def _extract_words(text: str) -> List[str]:
    return [w.lower() for w in _WORD_SPLIT.findall(text)]


def _count_phrase_hits(text: str, phrases: set) -> int:
    hits = 0
    for phrase in phrases:
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        hits += len(pattern.findall(text))
    return hits


def _count_regex_hits(text: str, patterns: list) -> int:
    return sum(len(p.findall(text)) for p in patterns)


# ── dataclass ───────────────────────────────────────────────────


@dataclass
class UrgencyDensityResult:
    """Result of urgency density measurement."""

    urgency_index: float = 0.0
    classification: str = "unhurried"

    # Channel counts
    temporal_marker_count: int = 0
    deadline_count: int = 0
    scarcity_count: int = 0
    consequence_count: int = 0
    imperative_count: int = 0
    immediacy_count: int = 0

    # Composite channel scores (0.0–1.0)
    temporal_score: float = 0.0
    deadline_score: float = 0.0
    scarcity_score: float = 0.0
    consequence_score: float = 0.0
    imperative_score: float = 0.0
    immediacy_score: float = 0.0

    # Metadata
    total_urgency_markers: int = 0
    total_sentences: int = 0
    total_words: int = 0


# ── main measurement function ──────────────────────────────────


def measure_urgency_density(text: str) -> UrgencyDensityResult:
    """Measure urgency density of a text.

    Returns an UrgencyDensityResult with urgency_index (0.0–1.0)
    and classification.
    """
    result = UrgencyDensityResult()

    stripped = text.strip()
    if not stripped:
        result.classification = "unhurried"
        return result

    sentences = _count_sentences(text)
    words = _count_words(text)
    result.total_sentences = sentences
    result.total_words = words

    denom = max(sentences, 1)
    all_words = _extract_words(text)

    # ── count each channel ───────────────────────────────────

    # 1. Temporal pressure markers (cap: 2 per sentence)
    temporal_hits = sum(1 for w in all_words if w in _TEMPORAL_SINGLE)
    temporal_hits += _count_phrase_hits(text, _TEMPORAL_PHRASES)
    result.temporal_marker_count = temporal_hits
    result.temporal_score = min(1.0, (temporal_hits / denom) / 2.0)

    # 2. Deadline / countdown language (cap: 1.5 per sentence)
    deadline_hits = sum(1 for w in all_words if w in _DEADLINE_SINGLE)
    deadline_hits += _count_phrase_hits(text, _DEADLINE_PHRASES)
    result.deadline_count = deadline_hits
    result.deadline_score = min(1.0, (deadline_hits / denom) / 1.5)

    # 3. Scarcity signals (cap: 1.5 per sentence)
    scarcity_hits = sum(1 for w in all_words if w in _SCARCITY_SINGLE)
    scarcity_hits += _count_phrase_hits(text, _SCARCITY_PHRASES)
    result.scarcity_count = scarcity_hits
    result.scarcity_score = min(1.0, (scarcity_hits / denom) / 1.5)

    # 4. Consequence proximity (cap: 1 per sentence)
    consequence_hits = sum(1 for w in all_words if w in _CONSEQUENCE_SINGLE)
    consequence_hits += _count_phrase_hits(text, _CONSEQUENCE_PHRASES)
    result.consequence_count = consequence_hits
    result.consequence_score = min(1.0, (consequence_hits / denom) / 1.0)

    # 5. Imperative urgency signals (cap: 1 per sentence)
    imperative_hits = _count_regex_hits(text, _IMPERATIVE_PHRASES)
    result.imperative_count = imperative_hits
    result.imperative_score = min(1.0, (imperative_hits / denom) / 1.0)

    # 6. Present-tense immediacy (cap: 1 per sentence)
    immediacy_hits = _count_regex_hits(text, _IMMEDIACY_PHRASES)
    result.immediacy_count = immediacy_hits
    result.immediacy_score = min(1.0, (immediacy_hits / denom) / 1.0)

    # ── composite index ──────────────────────────────────────
    # Weights: temporal 0.20, deadline 0.20, scarcity 0.15,
    # consequence 0.20, imperative 0.15, immediacy 0.10
    result.urgency_index = round(
        0.20 * result.temporal_score
        + 0.20 * result.deadline_score
        + 0.15 * result.scarcity_score
        + 0.20 * result.consequence_score
        + 0.15 * result.imperative_score
        + 0.10 * result.immediacy_score,
        4,
    )

    result.urgency_index = min(1.0, max(0.0, result.urgency_index))

    result.total_urgency_markers = (
        temporal_hits
        + deadline_hits
        + scarcity_hits
        + consequence_hits
        + imperative_hits
        + immediacy_hits
    )

    # ── classification ───────────────────────────────────────
    idx = result.urgency_index
    if idx < 0.10:
        result.classification = "unhurried"
    elif idx < 0.25:
        result.classification = "prompting"
    elif idx < 0.45:
        result.classification = "pressing"
    elif idx < 0.65:
        result.classification = "urgent"
    else:
        result.classification = "alarm"

    return result
