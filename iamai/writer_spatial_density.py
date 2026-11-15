#!/usr/bin/env python3
"""writer_spatial_density — measure how much prose relies on spatial language.

Every sentence situates its reader somewhere.  "The cat sat on
the mat" is a spatial act — a creature, a surface, a preposition
binding them.  "She walked toward the light at the end of the
corridor" layers direction, proximity, and containment into a
single image.  Even abstract prose cannot escape space: "the
argument falls short", "she rose above the criticism", "he was
trapped in a cycle" — each one a spatial metaphor pressed into
service for something that has no literal location at all.

Spatial language is among the earliest and most pervasive
devices in English.  Children learn "in", "on", "under" before
they learn tense.  Navigational instructions depend on it —
"turn left at the second light, the building is on your right".
Architecture descriptions require it — "the hallway opens into
a vaulted atrium, flanked by two staircases".  Fiction breathes
through it — "he stood behind the curtain, watching".  But
like any device, spatial language has a saturation point: prose
that cannot describe an idea without locating it, a feeling
without placing it, an event without mapping it, may be
confusing spatial metaphor for clarity.

Spatial density is not a quality metric.  Travel writing lives
on spatial description — every landmark, every turn, every
vista rendered in prepositional detail.  Technical documentation
requires it — "insert the cable into port B, route it behind
the chassis".  Fiction builds worlds through spatial immersion.
But a policy memo that describes every recommendation "on one
hand... on the other hand... at the top of the list... at the
bottom of the priority" may be leaning on spatial scaffolding
when direct assertion would serve better.

This module measures **how frequently, how diversely, and through
what mechanisms a text uses spatial language** — locative
prepositions, directional markers, proximity expressions,
orientation phrases, dimensional adjectives, containment
constructions, and spatial metaphors.

Orthogonality to other metrics
-------------------------------

- **temporal_density** tracks time-based language — tense,
  temporal adverbs, sequencing, duration.  Space and time are
  the two fundamental axes of narrative, but they are distinct:
  "she arrived at noon" is temporal; "she arrived at the
  station" is spatial.  Some expressions bridge both ("she
  walked through the afternoon") but most are unambiguous.
  Temporal density measures when; spatial density measures where.

- **deixis_density** tracks context-dependent references —
  "here", "there", "this", "that".  Spatial deictics ("here",
  "over there") overlap with spatial density, but deixis
  also covers temporal ("now", "then") and discourse ("this
  argument") reference.  Deixis measures context-dependence;
  spatial density measures location-language regardless of
  whether it requires context.

- **concreteness** tracks how much prose refers to tangible,
  sensorily available things.  Spatial language often appears
  in concrete prose (describing physical arrangements), but
  also appears in abstract prose through metaphor ("the
  foundation of the argument", "a hollow victory").
  Concreteness measures tangibility; spatial density measures
  location-language regardless of what it describes.

- **metaphor_density** tracks figurative language broadly.
  Spatial metaphors ("a deep insight", "shallow reasoning",
  "the heart of the matter") are one *type* of metaphor.
  Metaphor density measures all figurative language; spatial
  density measures spatial language whether literal or
  metaphorical.

- **sensory_density** tracks appeals to the five senses.
  Spatial language is related to but distinct from sensory
  description: "the red door on the left" is both sensory
  (color) and spatial (location), but "the door to the left
  of the filing cabinet" is spatial without being particularly
  sensory.  Sensory density measures perceptual detail; spatial
  density measures positional and directional language.

- **grounding_density** tracks how well claims are anchored
  in evidence.  Spatial grounding ("in the 2023 report",
  "on page 47") is one form of grounding, but grounding also
  includes data references, citations, and examples that are
  not spatially framed.  Grounding density measures evidential
  anchoring; spatial density measures location-language
  regardless of evidential function.

Spatial density asks: **how much of the prose is built on
spatial scaffolding, and what does the distribution of locative,
directional, dimensional, and containment language reveal about
the writer's relationship to physical and metaphorical space?**
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Set


# ── regex patterns ──────────────────────────────────────────────

# Sentence splitter (approximate)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# ── locative prepositions and phrases ───────────────────────────
# Core spatial prepositions and multi-word locatives
_LOCATIVE_PREPOSITIONS = re.compile(
    r"\b(?:in|on|at|under|above|below|beneath|underneath|"
    r"beside|besides|between|among|amongst|"
    r"near|nearby|next to|adjacent to|"
    r"across from|opposite to|opposite|"
    r"in front of|behind|at the back of|"
    r"to the left of|to the right of|"
    r"on top of|at the bottom of|"
    r"in the middle of|in the center of|"
    r"along|alongside|around|round about|"
    r"throughout|within|beyond|outside)\b",
    re.IGNORECASE,
)

# ── directional markers ─────────────────────────────────────────
_DIRECTION_MARKERS = re.compile(
    r"\b(?:toward|towards|away from|into|out of|out from|"
    r"through|across|along|around|past|over|under|"
    r"upward|upwards|downward|downwards|"
    r"forward|forwards|backward|backwards|"
    r"inward|inwards|outward|outwards|"
    r"leftward|leftwards|rightward|rightwards|"
    r"sideways|headlong|headfirst|"
    r"north|south|east|west|"
    r"northward|southward|eastward|westward|"
    r"uphill|downhill|upstream|downstream|"
    r"to and fro|back and forth|"
    r"this way|that way|the other way)\b",
    re.IGNORECASE,
)

# ── proximity expressions ───────────────────────────────────────
_PROXIMITY_EXPRESSIONIONS = re.compile(
    r"\b(?:near|nearby|close to|close by|"
    r"far from|far away|far off|"
    r"in the vicinity of|in the vicinity|"
    r"within reach|within range|within sight|"
    r"at arm'?s length|at close range|"
    r"in proximity to|in close proximity|"
    r"a stone'?s throw from|"
    r"just around the corner|"
    r"within walking distance|"
    r"not far from|no distance from|"
    r"handy to|handy by|"
    r"right next to|right beside|"
    r"steps away|a few steps from|"
    r"in spitting distance|"
    r"under one'?s nose|"
    r"at one'?s fingertips)\b",
    re.IGNORECASE,
)

# ── orientation markers ─────────────────────────────────────────
_ORIENTATION_MARKERS = re.compile(
    r"\b(?:facing|faced|face to face|"
    r"parallel to|perpendicular to|"
    r"aligned with|at an angle to|"
    r"diagonal to|at right angles to|"
    r"opposite|opposing|"
    r"leaning against|leaning on|"
    r"propped against|resting against|"
    r"oriented toward|oriented towards|"
    r"pointing at|pointing toward|pointing towards|"
    r"back to back|side by side|"
    r"head to head|face to face|"
    r"end to end|tip to tip)\b",
    re.IGNORECASE,
)

# ── dimensional and size adjectives ─────────────────────────────
_DIMENSION_EXPRESSIONS = re.compile(
    r"\b(?:tall|taller|tallest|"
    r"short|shorter|shortest|"
    r"wide|wider|widest|"
    r"narrow|narrower|narrowest|"
    r"deep|deeper|deepest|"
    r"shallow|shallower|shallowest|"
    r"long|longer|longest|"
    r"high|higher|highest|"
    r"low|lower|lowest|"
    r"thick|thicker|thickest|"
    r"thin|thinner|thinnest|"
    r"vast|vaster|vastest|"
    r"tiny|tinier|tiniest|"
    r"enormous|enormously|"
    r"massive|massively|"
    r"minute|minutely|"
    r"huge|hugely|"
    r"immense|immensely|"
    r"colossal|colossally|"
    r"microscopic|microscopically|"
    r"expansive|expansively|"
    r"compact|compactly|"
    r"spacious|spaciously|"
    r"cramped|crampedly|"
    r"voluminous|voluminously|"
    r"sprawling|sprawlingly|"
    r"lofty|loftier|loftiest)\b",
    re.IGNORECASE,
)

# ── containment constructions ───────────────────────────────────
_CONTAINMENT_MARKERS = re.compile(
    r"\b(?:inside|outside|within|without|"
    r"enclosed by|enclosed in|enclosed within|"
    r"surrounded by|surrounded with|"
    r"contained in|contained within|"
    r"bounded by|bounded on|"
    r"hemmed in|boxed in|walled in|"
    r"locked in|locked out|"
    r"sealed in|sealed off|"
    r"wrapped in|wrapped around|"
    r"immersed in|submerged in|"
    r"embedded in|embedded within|"
    r"ensconced in|ensconced within|"
    r"nestled in|nestled among|"
    r"couched in|framed in|"
    r"trapped in|trapped inside|"
    r"stuck in|stuck inside|"
    r"lost in|lost inside|"
    r"buried in|buried under|"
    r"hidden in|hidden behind|"
    r"concealed in|concealed behind)\b",
    re.IGNORECASE,
)

# ── spatial metaphors (abstract use of spatial language) ────────
_SPATIAL_METAPHORS = re.compile(
    r"\b(?:in trouble|in love|in danger|in pain|in debt|"
    r"in charge|in control|in command|in power|"
    r"in depth|in detail|in full|in brief|"
    r"in shape|in form|in spirit|in essence|"
    r"in theory|in practice|in principle|in effect|"
    r"on track|on board|on edge|on guard|on hold|"
    r"on fire|on ice|on tap|on trial|on duty|"
    r"under pressure|under stress|under control|"
    r"under attack|under fire|under siege|"
    r"under review|under consideration|under discussion|"
    r"over the hill|over the top|over the limit|"
    r"behind schedule|behind the scenes|behind bars|"
    r"ahead of the curve|ahead of time|ahead of schedule|"
    r"above reproach|above average|above par|"
    r"below average|below par|below the belt|"
    r"out of touch|out of line|out of order|"
    r"out of bounds|out of reach|out of sight|"
    r"the heart of the matter|the core of|"
    r"the foundation of|the bedrock of|"
    r"a deep insight|a shallow argument|"
    r"a hollow victory|an empty promise|"
    r"a solid case|a shaky premise|"
    r"level with me|on the level|"
    r"high standards|low standards|"
    r"far-fetched|far-reaching|"
    r"close-minded|open-minded|"
    r"short-sighted|long-sighted|"
    r"broad view|narrow view)"
    r"(?:\s|$|[.,;:!?])",
    re.IGNORECASE,
)

# ── combined pattern for unique form counting ───────────────────
_ALL_SPATIAL = re.compile(
    r"\b(?:"
    # locative prepositions
    r"in|on|at|under|above|below|beneath|underneath|"
    r"beside|besides|between|among|amongst|"
    r"near|nearby|next to|adjacent to|"
    r"across from|opposite to|opposite|"
    r"in front of|behind|at the back of|"
    r"to the left of|to the right of|"
    r"on top of|at the bottom of|"
    r"in the middle of|in the center of|"
    r"along|alongside|around|round about|"
    r"throughout|within|beyond|outside|"
    # directional
    r"toward|towards|away from|into|out of|out from|"
    r"through|across|along|around|past|over|under|"
    r"upward|upwards|downward|downwards|"
    r"forward|forwards|backward|backwards|"
    r"inward|inwards|outward|outwards|"
    r"leftward|leftwards|rightward|rightwards|"
    r"sideways|headlong|headfirst|"
    r"north|south|east|west|"
    r"northward|southward|eastward|westward|"
    r"uphill|downhill|upstream|downstream|"
    # proximity
    r"nearby|close to|close by|"
    r"far from|far away|far off|"
    r"in the vicinity of|within reach|within range|"
    r"at arm'?s length|in close proximity|"
    # orientation
    r"facing|faced|parallel to|perpendicular to|"
    r"aligned with|at an angle to|"
    r"side by side|back to back|"
    # containment
    r"inside|outside|within|without|"
    r"enclosed by|surrounded by|contained in|"
    r"bounded by|hemmed in|boxed in|"
    r"immersed in|embedded in|ensconced in|"
    r"nestled in|trapped in|buried in|hidden in"
    r")\b",
    re.IGNORECASE,
)


# ── dataclass ───────────────────────────────────────────────────


@dataclass
class SpatialDensityResult:
    """Results of spatial density analysis."""

    # Raw counts
    locative_preposition_count: int = 0
    direction_marker_count: int = 0
    proximity_expression_count: int = 0
    orientation_marker_count: int = 0
    dimension_expression_count: int = 0
    containment_count: int = 0
    spatial_metaphor_count: int = 0
    unique_spatial_forms: int = 0

    # Rates per 100 sentences
    locative_preposition_rate: float = 0.0
    direction_marker_rate: float = 0.0
    proximity_expression_rate: float = 0.0
    orientation_marker_rate: float = 0.0
    dimension_expression_rate: float = 0.0
    containment_rate: float = 0.0
    spatial_metaphor_rate: float = 0.0

    # Composite
    spatial_diversity_index: float = 0.0
    spatial_density_index: float = 0.0
    classification: str = "placeless"

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


def measure_spatial_density(text: str) -> SpatialDensityResult:
    """Analyze spatial language density in text.

    Parameters
    ----------
    text : str
        The text to analyze.

    Returns
    -------
    SpatialDensityResult
        Analysis results with rates, composite index, and classification.
    """
    result = SpatialDensityResult()

    if not text or not text.strip():
        return result

    sentence_count = _count_sentences(text)
    result.total_sentences = sentence_count
    scale = 100.0 / max(sentence_count, 1)

    # ── Count each category ─────────────────────────────────
    locative = _count_matches(_LOCATIVE_PREPOSITIONS, text)
    direction = _count_matches(_DIRECTION_MARKERS, text)
    proximity = _count_matches(_PROXIMITY_EXPRESSIONIONS, text)
    orientation = _count_matches(_ORIENTATION_MARKERS, text)
    dimension = _count_matches(_DIMENSION_EXPRESSIONS, text)
    containment = _count_matches(_CONTAINMENT_MARKERS, text)
    metaphor = _count_matches(_SPATIAL_METAPHORS, text)

    # Unique spatial forms
    all_forms = _ALL_SPATIAL.findall(text)
    unique_forms: Set[str] = {f.lower().strip() for f in all_forms}

    # Store counts
    result.locative_preposition_count = locative
    result.direction_marker_count = direction
    result.proximity_expression_count = proximity
    result.orientation_marker_count = orientation
    result.dimension_expression_count = dimension
    result.containment_count = containment
    result.spatial_metaphor_count = metaphor
    result.unique_spatial_forms = len(unique_forms)

    # Rates per 100 sentences
    result.locative_preposition_rate = round(locative * scale, 3)
    result.direction_marker_rate = round(direction * scale, 3)
    result.proximity_expression_rate = round(proximity * scale, 3)
    result.orientation_marker_rate = round(orientation * scale, 3)
    result.dimension_expression_rate = round(dimension * scale, 3)
    result.containment_rate = round(containment * scale, 3)
    result.spatial_metaphor_rate = round(metaphor * scale, 3)

    # Diversity: ratio of unique forms to maximum possible (~35)
    max_possible_forms = 35
    result.spatial_diversity_index = round(
        min(1.0, len(unique_forms) / max_possible_forms), 3
    )

    # ── Composite index (0.0 – 1.0) ────────────────────────
    # Normalize each rate to roughly 0–1 via soft caps
    cap_locative = min(1.0, result.locative_preposition_rate / 40.0)
    cap_direction = min(1.0, result.direction_marker_rate / 15.0)
    cap_proximity = min(1.0, result.proximity_expression_rate / 5.0)
    cap_orientation = min(1.0, result.orientation_marker_rate / 3.0)
    cap_dimension = min(1.0, result.dimension_expression_rate / 10.0)
    cap_containment = min(1.0, result.containment_rate / 8.0)
    cap_metaphor = min(1.0, result.spatial_metaphor_rate / 5.0)
    cap_diversity = result.spatial_diversity_index

    composite = (
        0.25 * cap_locative
        + 0.15 * cap_direction
        + 0.08 * cap_proximity
        + 0.05 * cap_orientation
        + 0.12 * cap_dimension
        + 0.10 * cap_containment
        + 0.10 * cap_metaphor
        + 0.15 * cap_diversity
    )
    result.spatial_density_index = round(min(1.0, composite), 4)

    # ── Classification ──────────────────────────────────────
    idx = result.spatial_density_index
    if idx < 0.05:
        result.classification = "placeless"
    elif idx < 0.15:
        result.classification = "lightly_spatial"
    elif idx < 0.35:
        result.classification = "moderately_spatial"
    elif idx < 0.60:
        result.classification = "heavily_spatial"
    else:
        result.classification = "space_saturated"

    result.details = {
        "locative_preposition_rate": result.locative_preposition_rate,
        "direction_marker_rate": result.direction_marker_rate,
        "proximity_expression_rate": result.proximity_expression_rate,
        "orientation_marker_rate": result.orientation_marker_rate,
        "dimension_expression_rate": result.dimension_expression_rate,
        "containment_rate": result.containment_rate,
        "spatial_metaphor_rate": result.spatial_metaphor_rate,
        "spatial_diversity_index": result.spatial_diversity_index,
        "spatial_density_index": result.spatial_density_index,
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

    r = measure_spatial_density(text)
    print(f"spatial_density_index      : {r.spatial_density_index:.4f}")
    print(f"classification             : {r.classification}")
    print(f"locative_preposition_rate  : {r.locative_preposition_rate}")
    print(f"direction_marker_rate      : {r.direction_marker_rate}")
    print(f"proximity_expression_rate  : {r.proximity_expression_rate}")
    print(f"orientation_marker_rate    : {r.orientation_marker_rate}")
    print(f"dimension_expression_rate  : {r.dimension_expression_rate}")
    print(f"containment_rate           : {r.containment_rate}")
    print(f"spatial_metaphor_rate      : {r.spatial_metaphor_rate}")
    print(f"spatial_diversity_index    : {r.spatial_diversity_index}")
    print(f"total_sentences            : {r.total_sentences}")
