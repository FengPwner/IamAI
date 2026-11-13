#!/usr/bin/env python3
"""writer_temporal_density — measure how much prose relies on temporal language.

Time is the invisible scaffolding of every sentence.  Every verb
tense, every temporal adverb ("now", "then", "later", "meanwhile"),
every sequencing word ("first", "next", "finally"), every duration
expression ("for hours", "since Monday", "over the years") is a
small act of temporal architecture — the writer telling the reader
where, when, and in what order things happen.

Temporal language is among the most fundamental devices in English
prose.  It lets a writer narrate sequences ("first the engine
started, then the wheels turned"), situate claims in time ("as
of 2024, the data suggests"), express duration ("the negotiations
lasted for three weeks"), and shift between past, present, and
future ("she had left before he arrived").  But like any device,
temporality has a density at which it stops serving clarity and
starts revealing something else — a writer who cannot describe
an event without excessive chronological scaffolding, or a text
that is so temporally disoriented that the reader loses all sense
of sequence.

Temporal density is not a quality metric.  Historical narrative
lives in past-tense anchoring — "in 1776, the delegates signed".
Scientific methodology thrives on temporal sequencing — "after
the solution was heated, the precipitate formed".  Journalism
depends on temporal markers — "yesterday", "earlier this week",
"in a statement released Monday".  But prose that cannot relate
two events without explicit temporal connectors may be missing
the harder work of implicit narrative logic.

This module measures **how frequently, how diversely, and in what
distribution a text uses temporal language** — tense markers,
temporal adverbs, sequencing expressions, duration phrases,
frequency expressions, and temporal orientation shifts.

Orthogonality to other metrics
-------------------------------

- **causal_density** tracks cause-and-effect language —
  "because", "therefore", "as a result".  Temporal sequence
  and causation are related but distinct: "A happened, then B
  happened" is temporal; "A happened, therefore B happened" is
  causal.  Temporal density measures chronological framing;
  causal density measures stated causation.

- **transitions** tracks transitional phrases broadly —
  "however", "moreover", "in addition".  Some transitions are
  temporal ("meanwhile", "subsequently"), but most are not.
  Transition density measures logical connective frequency;
  temporal density measures time-specific connectives.

- **conditionality_density** tracks conditional structures —
  "if", "unless", "provided that".  Temporal conditions
  ("when the bell rings, the class ends") bridge both categories,
  but pure temporals ("afterwards", "meanwhile") are not
  conditional.  Conditionality density measures contingent
  framing; temporal density measures chronological framing.

- **temporal_orientation** (if it exists) would measure *which*
  temporal direction dominates — past, present, or future.  This
  module measures *how much* temporal language is used regardless
  of direction.  A text can be heavily temporal and past-oriented
  (historical narrative), heavily temporal and future-oriented
  (planning document), or heavily temporal with frequent shifts
  (analytical prose).  Temporal density measures volume; temporal
  orientation measures direction.

- **concession_density** tracks concessive clauses —
  "although", "even though", "despite".  Concessive clauses
  occasionally embed temporal language ("although it had been
  raining for hours"), but the concessive frame is logically
  distinct from the temporal one.  Concession density measures
  acknowledgment of counter-evidence; temporal density measures
  chronological framing.

Temporal density asks: **how much of the prose is built on
temporal scaffolding, and what does the distribution of tense,
sequence, duration, and frequency expressions reveal about the
writer's relationship to time?**
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Set


# ── regex patterns ──────────────────────────────────────────────

# Sentence splitter (approximate)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Past tense markers — common regular and irregular past forms
# These are heuristic; a full POS tagger would be more precise
_PAST_MARKERS = re.compile(
    r"\b(?:was|were|had|did|went|came|saw|knew|thought|said|told|"
    r"made|took|gave|found|left|felt|became|began|started|ended|"
    r"stopped|continued|returned|appeared|seemed|happened|occurred|"
    r"arrived|departed|spoke|wrote|read|heard|learned|discovered|"
    r"realized|recognized|remembered|forgot|believed|considered|"
    r"decided|determined|concluded|observed|noted|reported|stated|"
    r"announced|declared|claimed|argued|maintained|insisted|"
    r"suggested|proposed|recommended|demanded|required|ordered|"
    r"walked|talked|worked|played|lived|moved|turned|opened|"
    r"closed|pulled|pushed|carried|brought|sent|received|"
    r"built|created|designed|developed|produced|established|"
    r"introduced|presented|offered|provided|achieved|completed|"
    r"finished|reached|entered|existed|remained|stayed|waited|"
    r"followed|led|held|included|involved|contained|consisted|"
    r"asked|answered|replied|explained|described|defined|"
    r"showed|demonstrated|illustrated|revealed|indicated)\b",
    re.IGNORECASE,
)

# Present tense markers — present progressive and habitual
_PRESENT_MARKERS = re.compile(
    r"\b(?:is|am|are|has|have|does|do|goes|comes|sees|knows|"
    r"thinks|says|tells|makes|takes|gives|finds|leaves|feels|"
    r"becomes|begins|starts|ends|stops|continues|returns|appears|"
    r"seems|happens|occurs|arrives|departs|speaks|writes|reads|"
    r"hears|learns|discovers|realizes|recognizes|remembers|"
    r"believes|considers|decides|determines|concludes|observes|"
    r"notes|reports|states|announces|declares|claims|argues|"
    r"maintains|insists|suggests|proposes|recommends|walks|"
    r"talks|works|plays|lives|moves|turns|opens|closes|pulls|"
    r"pushes|carries|brings|sends|receives|builds|creates|"
    r"designs|develops|produces|establishes|introduces|"
    r"presents|offers|provides|achieves|completes|finishes|"
    r"reaches|enters|exists|remains|stays|waits|follows|leads|"
    r"holds|includes|involves|contains|consists|asks|answers|"
    r"replies|explains|describes|defines|shows|demonstrates|"
    r"illustrates|reveals|indicates)\b",
    re.IGNORECASE,
)

# Future markers
_FUTURE_MARKERS = re.compile(
    r"\b(?:will|shall|going\s+to|about\s+to|due\s+to|"
    r"expected\s+to|set\s+to|scheduled\s+to|planned\s+to|"
    r"likely\s+to|bound\s+to|destined\s+to|slated\s+to|"
    r"predicted\s+to|projected\s+to|anticipated\s+to|"
    r"will\s+be|will\s+have|will\s+need|will\s+see|"
    r"will\s+become|will\s+continue|will\s+remain)\b",
    re.IGNORECASE,
)

# Temporal adverbs — words that locate events in time
_TEMPORAL_ADVERBS = re.compile(
    r"\b(?:now|then|today|yesterday|tomorrow|tonight|currently|"
    r"presently|recently|lately|already|yet|still|soon|later|"
    r"earlier|before|after|afterwards|subsequently|previously|"
    r"formerly|originally|initially|ultimately|finally|eventually|"
    r"meanwhile|simultaneously|concurrently|immediately|instantly|"
    r"shortly|promptly|gradually|slowly|quickly|suddenly|"
    r"abruptly|hastily|prematurely|belatedly|retroactively|"
    r"henceforth|hereafter|thenceforth|thereafter|whereupon|"
    r"always|never|ever|forever|perpetually|eternally|"
    r"constantly|continually|continuously|incessantly|"
    r"frequently|often|sometimes|occasionally|rarely|seldom|"
    r"hardly\s+ever|almost\s+never|once|twice|thrice|"
    r"daily|weekly|monthly|yearly|annually|periodically|"
    r"regularly|intermittently|sporadically|erratically)\b",
    re.IGNORECASE,
)

# Sequencing expressions — words that order events
_SEQUENCING_EXPRESSIONS = re.compile(
    r"\b(?:first(?:ly)?|second(?:ly)?|third(?:ly)?|fourth(?:ly)?|"
    r"fifth(?:ly)?|next|then|after\s+that|before\s+that|"
    r"following\s+that|subsequent\s+to|prior\s+to|"
    r"in\s+the\s+first\s+place|in\s+the\s+second\s+place|"
    r"to\s+begin\s+with|to\s+start\s+with|"
    r"last(?:ly)?|finally|in\s+conclusion|in\s+summary|"
    r"to\s+sum\s+up|in\s+the\s+end|at\s+last|"
    r"step\s+one|step\s+two|step\s+three|"
    r"phase\s+one|phase\s+two|phase\s+three|"
    r"stage\s+one|stage\s+two|stage\s+three|"
    r"chapter\s+one|chapter\s+two|part\s+one|part\s+two|"
    r"initially|subsequently|consecutively|successively|"
    r"in\s+sequence|in\s+order|in\s+turn|one\s+by\s+one|"
    r"bit\s+by\s+bit|little\s+by\s+little|step\s+by\s+step|"
    r"gradually|progressively|incrementally)\b",
    re.IGNORECASE,
)

# Duration expressions
_DURATION_EXPRESSIONS = re.compile(
    r"\b(?:for\s+\w+\s+(?:seconds?|minutes?|hours?|days?|weeks?|"
    r"months?|years?|decades?|centuries?|millennia?)|"
    r"since\s+\w+|"
    r"during\s+(?:the\s+)?\w+|"
    r"throughout\s+(?:the\s+)?\w+|"
    r"over\s+(?:the\s+)?(?:past|last|next|\w+)\s+"
    r"(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?|"
    r"decades?|centuries?)|"
    r"in\s+(?:the\s+)?(?:past|last|next|recent)\s+"
    r"(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?|"
    r"decades?|centuries?)|"
    r"from\s+\w+\s+to\s+\w+|"
    r"between\s+\w+\s+and\s+\w+|"
    r"until\s+\w+|till\s+\w+|up\s+to\s+\w+|"
    r"as\s+long\s+as|as\s+soon\s+as|as\s+far\s+back\s+as|"
    r"all\s+(?:day|night|week|month|year|along)|"
    r"the\s+whole\s+(?:time|day|night|week|month|year)|"
    r"(?:every|each)\s+(?:second|minute|hour|day|week|month|year))\b",
    re.IGNORECASE,
)

# Frequency expressions — how often things happen
_FREQUENCY_EXPRESSIONS = re.compile(
    r"\b(?:always|never|ever|constantly|continually|continuously|"
    r"frequently|often|sometimes|occasionally|rarely|seldom|"
    r"hardly\s+ever|almost\s+never|once\s+(?:a|per|every)|"
    r"twice\s+(?:a|per|every)|thrice\s+(?:a|per|every)|"
    r"(?:every|each)\s+(?:day|week|month|year|hour|minute)|"
    r"(?:daily|weekly|monthly|yearly|annually|hourly)|"
    r"from\s+time\s+to\s+time|now\s+and\s+then|"
    r"on\s+occasion|at\s+times|in\s+general|"
    r"as\s+a\s+rule|for\s+the\s+most\s+part|"
    r"more\s+often\s+than\s+not|"
    r"nine\s+times\s+out\s+of\s+ten|"
    r"without\s+fail|like\s+clockwork|"
    r"again\s+and\s+again|over\s+and\s+over|"
    r"repeatedly|habitually|routinely|customarily|"
    r"traditionally|historically|typically|usually|"
    r"normally|generally|ordinarily|commonly)\b",
    re.IGNORECASE,
)

# Temporal orientation shift markers — words indicating a shift
# in temporal frame
_TEMPORAL_SHIFT_MARKERS = re.compile(
    r"\b(?:but\s+then|and\s+then|yet|however|meanwhile|"
    r"in\s+the\s+meantime|at\s+the\s+same\s+time|"
    r"while\s+that\s+was\s+happening|"
    r"back\s+then|in\s+those\s+days|in\s+the\s+old\s+days|"
    r"looking\s+back|in\s+retrospect|with\s+the\s+benefit\s+of|"
    r"looking\s+ahead|going\s+forward|from\s+now\s+on|"
    r"in\s+the\s+future|in\s+years?\s+to\s+come|"
    r"flashback|flash\s+forward|cut\s+to|"
    r"fast\s+forward|rewind|backtrack|"
    r"returning\s+to|coming\s+back\s+to|"
    r"picking\s+up\s+where|resuming)\b",
    re.IGNORECASE,
)

# All temporal patterns combined for diversity calculation
_ALL_TEMPORAL = re.compile(
    r"\b(?:now|then|today|yesterday|tomorrow|was|were|will|shall|"
    r"has\s+been|had\s+been|is\s+being|was\s+being|"
    r"before|after|during|while|since|until|meanwhile|"
    r"first|next|last|finally|previously|subsequently|"
    r"always|never|often|rarely|sometimes|frequently|"
    r"gradually|suddenly|immediately|eventually|"
    r"for\s+\w+\s+(?:hours?|days?|years?)|"
    r"in\s+the\s+(?:past|future|present))\b",
    re.IGNORECASE,
)


# ── dataclass ───────────────────────────────────────────────────


@dataclass
class TemporalDensityResult:
    """Results of temporal density analysis."""

    # Raw counts
    past_marker_count: int = 0
    present_marker_count: int = 0
    future_marker_count: int = 0
    temporal_adverb_count: int = 0
    sequencing_expression_count: int = 0
    duration_expression_count: int = 0
    frequency_expression_count: int = 0
    temporal_shift_count: int = 0
    unique_temporal_forms: int = 0

    # Rates per 100 sentences
    past_marker_rate: float = 0.0
    present_marker_rate: float = 0.0
    future_marker_rate: float = 0.0
    temporal_adverb_rate: float = 0.0
    sequencing_expression_rate: float = 0.0
    duration_expression_rate: float = 0.0
    frequency_expression_rate: float = 0.0
    temporal_shift_rate: float = 0.0

    # Composite
    temporal_diversity_index: float = 0.0
    temporal_density_index: float = 0.0
    classification: str = "timeless"

    # Metadata
    total_sentences: int = 0
    details: dict = field(default_factory=dict)


# ── main function ───────────────────────────────────────────────


def _count_sentences(text: str) -> int:
    """Count sentences (approximate)."""
    stripped = text.strip()
    if not stripped:
        return 0
    sentences = [s for s in _SENTENCE_SPLIT.split(stripped) if s.strip()]
    return max(len(sentences), 1)


def _count_matches(pattern: re.Pattern, text: str) -> int:
    """Count non-overlapping regex matches."""
    return len(pattern.findall(text))


def measure_temporal_density(text: str) -> TemporalDensityResult:
    """Analyze temporal language density in text.

    Parameters
    ----------
    text : str
        The text to analyze.

    Returns
    -------
    TemporalDensityResult
        Analysis results with rates, composite index, and classification.
    """
    result = TemporalDensityResult()

    if not text or not text.strip():
        return result

    sentence_count = _count_sentences(text)
    result.total_sentences = sentence_count
    scale = 100.0 / max(sentence_count, 1)

    # ── Count each category ─────────────────────────────────
    past = _count_matches(_PAST_MARKERS, text)
    present = _count_matches(_PRESENT_MARKERS, text)
    future = _count_matches(_FUTURE_MARKERS, text)
    adverbs = _count_matches(_TEMPORAL_ADVERBS, text)
    sequencing = _count_matches(_SEQUENCING_EXPRESSIONS, text)
    duration = _count_matches(_DURATION_EXPRESSIONS, text)
    frequency = _count_matches(_FREQUENCY_EXPRESSIONS, text)
    shifts = _count_matches(_TEMPORAL_SHIFT_MARKERS, text)

    # Unique temporal forms
    all_forms = _ALL_TEMPORAL.findall(text)
    unique_forms: Set[str] = {f.lower().strip() for f in all_forms}

    # Store counts
    result.past_marker_count = past
    result.present_marker_count = present
    result.future_marker_count = future
    result.temporal_adverb_count = adverbs
    result.sequencing_expression_count = sequencing
    result.duration_expression_count = duration
    result.frequency_expression_count = frequency
    result.temporal_shift_count = shifts
    result.unique_temporal_forms = len(unique_forms)

    # Rates per 100 sentences
    result.past_marker_rate = round(past * scale, 3)
    result.present_marker_rate = round(present * scale, 3)
    result.future_marker_rate = round(future * scale, 3)
    result.temporal_adverb_rate = round(adverbs * scale, 3)
    result.sequencing_expression_rate = round(sequencing * scale, 3)
    result.duration_expression_rate = round(duration * scale, 3)
    result.frequency_expression_rate = round(frequency * scale, 3)
    result.temporal_shift_rate = round(shifts * scale, 3)

    # Diversity: ratio of unique forms to maximum possible (~30)
    max_possible_forms = 30
    result.temporal_diversity_index = round(
        min(1.0, len(unique_forms) / max_possible_forms), 3
    )

    # ── Composite index (0.0 – 1.0) ────────────────────────
    # Normalize each rate to roughly 0–1 via soft caps
    cap_past = min(1.0, result.past_marker_rate / 25.0)
    cap_present = min(1.0, result.present_marker_rate / 20.0)
    cap_future = min(1.0, result.future_marker_rate / 10.0)
    cap_adverbs = min(1.0, result.temporal_adverb_rate / 20.0)
    cap_sequencing = min(1.0, result.sequencing_expression_rate / 8.0)
    cap_duration = min(1.0, result.duration_expression_rate / 5.0)
    cap_frequency = min(1.0, result.frequency_expression_rate / 10.0)
    cap_shifts = min(1.0, result.temporal_shift_rate / 3.0)
    cap_diversity = result.temporal_diversity_index

    composite = (
        0.15 * cap_past
        + 0.10 * cap_present
        + 0.10 * cap_future
        + 0.15 * cap_adverbs
        + 0.10 * cap_sequencing
        + 0.08 * cap_duration
        + 0.08 * cap_frequency
        + 0.06 * cap_shifts
        + 0.08 * cap_diversity
    )
    result.temporal_density_index = round(min(1.0, composite), 4)

    # ── Classification ──────────────────────────────────────
    idx = result.temporal_density_index
    if idx < 0.05:
        result.classification = "timeless"
    elif idx < 0.15:
        result.classification = "lightly_temporal"
    elif idx < 0.35:
        result.classification = "moderately_temporal"
    elif idx < 0.60:
        result.classification = "heavily_temporal"
    else:
        result.classification = "time_saturated"

    result.details = {
        "past_marker_rate": result.past_marker_rate,
        "present_marker_rate": result.present_marker_rate,
        "future_marker_rate": result.future_marker_rate,
        "temporal_adverb_rate": result.temporal_adverb_rate,
        "sequencing_expression_rate": result.sequencing_expression_rate,
        "duration_expression_rate": result.duration_expression_rate,
        "frequency_expression_rate": result.frequency_expression_rate,
        "temporal_shift_rate": result.temporal_shift_rate,
        "temporal_diversity_index": result.temporal_diversity_index,
        "temporal_density_index": result.temporal_density_index,
        "classification": result.classification,
    }

    return result


# ── CLI convenience ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else None
    if path:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    r = measure_temporal_density(text)
    print(f"temporal_density_index   : {r.temporal_density_index:.4f}")
    print(f"classification           : {r.classification}")
    print(f"past_marker_rate         : {r.past_marker_rate}")
    print(f"present_marker_rate      : {r.present_marker_rate}")
    print(f"future_marker_rate       : {r.future_marker_rate}")
    print(f"temporal_adverb_rate     : {r.temporal_adverb_rate}")
    print(f"sequencing_expression_rate: {r.sequencing_expression_rate}")
    print(f"duration_expression_rate : {r.duration_expression_rate}")
    print(f"frequency_expression_rate: {r.frequency_expression_rate}")
    print(f"temporal_shift_rate      : {r.temporal_shift_rate}")
    print(f"temporal_diversity_index : {r.temporal_diversity_index}")
    print(f"total_sentences          : {r.total_sentences}")
