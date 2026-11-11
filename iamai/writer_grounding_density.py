#!/usr/bin/env python3
"""writer_grounding_density — measure how well a writer anchors abstract
claims with concrete evidence, examples, and specific references.

Grounding is the ratio of concrete to abstract expression in a writing
session.  A well-grounded session backs up its assertions with numbers,
named entities, quoted passages, and specific references.  A poorly
grounded session floats in abstractions: everything is "significant",
"important", "complex", but nothing is pinned down enough to verify.

This module is orthogonal to the other writer metrics:

- **coherence** tracks whether consecutive ideas *connect*.  A session
  can be perfectly coherent (each stroke flows from the last) while
  being entirely abstract (every stroke is a generalization about the
  previous generalization).

- **signal_clarity** tracks whether strokes are *substantively unique*.
  A session can have high clarity (every stroke says something new)
  while being ungrounded (every new thing is an unsupported assertion).

- **synthesis_depth** tracks whether the writer *combines ideas* rather
  than listing them.  Synthesis can be deep but ungrounded — connecting
  abstractions without touching specifics.

- **exploration_exploitation** tracks whether the writer *ventures into
  new territory*.  Exploration can be grounded (venturing into new
  specifics) or ungrounded (venturing into new abstractions).

Grounding asks: **when the writer makes a claim, does it also provide
the evidence that supports the claim?**

Three signals are tracked:

1. **Concrete-abstract ratio** — the proportion of strokes that contain
   at least one concrete marker (number, named entity, file path, URL,
   code reference) relative to the total.  A stroke that says "commit
   587 touched 2099 files" is concrete; one that says "the system made
   significant progress" is abstract.

2. **Evidence pairing** — for strokes that contain a claim marker
   (opinion words, evaluative adjectives, causal assertions), does the
   same stroke or its immediate successor contain concrete support?
   High pairing means claims travel with their evidence.  Low pairing
   means claims are dropped without support.

3. **Specificity gradient** — a per-stroke score measuring the density
   of specific references (numbers per 100 words, distinct named
   entities per 100 words, code/path references per 100 words).  The
   session mean and trend reveal whether the writer is getting more or
   less specific over time.

From these signals a session-level **grounding_index** is computed and
classified:

==============  ============================================================
class           meaning
==============  ============================================================
anchored        grounding_index >= 0.55 — claims are densely supported
                with specific evidence; the writing reads as empirical
                and verifiable
substantiated   0.40 <= grounding_index < 0.55 — most claims have
                supporting evidence but some assertions float free;
                typical of good analytical writing
illustrated     0.25 <= grounding_index < 0.40 — occasional concrete
                examples punctuate an otherwise abstract discussion;
                the writer gestures at evidence without committing
unmoored        grounding_index < 0.25 — almost no concrete anchoring;
                the session is a stream of generalizations and opinions
                without specific support
==============  ============================================================

Session arc analysis
--------------------
The session is divided into quartiles and the grounding index is
computed for each.  A healthy analytical session shows a "deepening"
curve: moderate grounding in Q1 (the writer is framing the problem),
rising grounding in Q2-Q3 (evidence accumulates), stable or slightly
declining grounding in Q4 (synthesis and conclusions).

A falling arc means the writer started with specifics but drifted into
abstraction — possibly fatigue or running out of data.  A rising arc
means the writer started abstract and found the specifics later —
possibly a brainstorming-to-analysis transition.

Reference: Korzyński, P. & Kłopotek, M. "Grounding of Natural Language
in Embodied Experience" (2012) — on how language acquires meaning through
connection to observable reality.  Applied to autonomous writing: a
writer that cannot ground its claims in specifics is producing symbols
disconnected from referents — fluent but unverifiable.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Words that signal abstract / evaluative claims
_CLAIM_MARKERS: set[str] = {
    "important", "significant", "crucial", "essential", "critical",
    "interesting", "notable", "remarkable", "concerning", "alarming",
    "impressive", "promising", "problematic", "challenging", "difficult",
    "complex", "simple", "obvious", "clear", "evident", "apparent",
    "suggests", "indicates", "implies", "demonstrates", "shows",
    "proves", "confirms", "reveals", "highlights", "underscores",
    "should", "must", "need", "ought", "require",
    "better", "worse", "best", "worst", "optimal", "suboptimal",
    "effective", "ineffective", "efficient", "inefficient",
    "valuable", "useless", "helpful", "harmful", "beneficial",
}

# Patterns that count as concrete evidence
_NUMBER_RE = re.compile(
    r"\b\d+(?:\.\d+)?(?:%|ms|MB|GB|KB|TB|Hz|MHz|GHz|°C|°F)?\b"
)
_ENTITY_RE = re.compile(
    r"(?:https?://\S+|"               # URLs
    r"/[\w./\-]+|"                     # file paths
    r"\b[A-Z][a-z]+(?:\.[a-z]+){1,3}\b|"  # domain-like entities
    r"`[^`]+`|"                        # inline code
    r"\bpid\s*\d+|"                    # process IDs
    r"\bcommit\s+[0-9a-f]{7,40}\b|"   # git commit hashes
    r"\b(?:v\d+\.\d+(?:\.\d+)?)\b)"   # version numbers
)
_CODE_REF_RE = re.compile(
    r"(?:`[^`]+`|"                     # inline code
    r"\b\w+\.py\b|"                   # python files
    r"\b\w+\.md\b|"                   # markdown files
    r"\bdef\s+\w+|"                   # function definitions
    r"\bclass\s+\w+|"                 # class definitions
    r"test_\w+)"                       # test function names
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Lowercase word-level tokenization."""
    return re.findall(r"\w+", text.lower())


def _get_stroke_text(stroke: dict[str, Any]) -> str:
    """Extract text from a stroke dict."""
    text = stroke.get("text") or stroke.get("content") or ""
    return str(text) if text is not None else ""


def _count_numbers(text: str) -> int:
    """Count numeric values in the text."""
    return len(_NUMBER_RE.findall(text))


def _count_entities(text: str) -> int:
    """Count named entities, URLs, paths, and version strings."""
    return len(_ENTITY_RE.findall(text))


def _count_code_refs(text: str) -> int:
    """Count code-level references."""
    return len(_CODE_REF_RE.findall(text))


def _has_claim_marker(tokens: list[str]) -> bool:
    """Check whether any token is a claim/evaluative marker."""
    return bool(set(tokens) & _CLAIM_MARKERS)


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------

def analyze_concrete_markers(text: str) -> dict[str, int]:
    """Count concrete markers in a single stroke.

    Returns
    -------
    dict with keys: ``numbers``, ``entities``, ``code_refs``, ``total``
    """
    numbers = _count_numbers(text)
    entities = _count_entities(text)
    code_refs = _count_code_refs(text)
    return {
        "numbers": numbers,
        "entities": entities,
        "code_refs": code_refs,
        "total": numbers + entities + code_refs,
    }


def analyze_specificity(text: str) -> float:
    """Compute per-stroke specificity score (concrete markers per 100 words).

    Returns
    -------
    Float >= 0.0.  Higher means more specific.  Capped at 10.0 for
    sanity (extremely dense numeric tables can exceed this).
    """
    tokens = _tokenize(text)
    word_count = len(tokens)
    if word_count == 0:
        return 0.0

    markers = analyze_concrete_markers(text)
    raw = (markers["total"] / word_count) * 100.0
    return min(raw, 10.0)


def is_concrete_stroke(text: str, threshold: int = 1) -> bool:
    """Determine whether a stroke contains at least ``threshold``
    concrete markers."""
    markers = analyze_concrete_markers(text)
    return markers["total"] >= threshold


# ---------------------------------------------------------------------------
# Evidence pairing
# ---------------------------------------------------------------------------

def analyze_evidence_pairing(
    strokes: list[dict[str, Any]],
    pairing_window: int = 1,
) -> float:
    """Measure how often claims are paired with concrete evidence.

    For each stroke that contains a claim marker, check whether the
    same stroke or any of the next ``pairing_window`` strokes contain
    at least one concrete marker.

    Returns
    -------
    Fraction of claims that are paired with evidence (0.0–1.0).
    Returns 0.0 if there are no claim-bearing strokes.
    """
    if not strokes:
        return 0.0

    texts = [_get_stroke_text(s) for s in strokes]
    tokens_list = [_tokenize(t) for t in texts]
    concrete_flags = [analyze_concrete_markers(t)["total"] > 0 for t in texts]
    claim_flags = [_has_claim_marker(toks) for toks in tokens_list]

    claim_indices = [i for i, has_claim in enumerate(claim_flags) if has_claim]
    if not claim_indices:
        return 0.0

    paired = 0
    for idx in claim_indices:
        # Check same stroke
        if concrete_flags[idx]:
            paired += 1
            continue
        # Check next ``pairing_window`` strokes
        for offset in range(1, pairing_window + 1):
            next_idx = idx + offset
            if next_idx < len(concrete_flags) and concrete_flags[next_idx]:
                paired += 1
                break

    return paired / len(claim_indices)


# ---------------------------------------------------------------------------
# Session-level metrics
# ---------------------------------------------------------------------------

def compute_grounding_metrics(
    strokes: list[dict[str, Any]],
    pairing_window: int = 1,
) -> dict[str, Any]:
    """Compute session-level grounding density metrics.

    Parameters
    ----------
    strokes : list[dict]
        Ordered list of stroke records.
    pairing_window : int
        How many subsequent strokes to check for evidence pairing.

    Returns
    -------
    dict with keys:
        ``strokes_analyzed`` — number of strokes processed
        ``concrete_ratio`` — fraction of strokes with concrete markers
        ``evidence_pairing`` — fraction of claims paired with evidence
        ``specificity_mean`` — mean per-stroke specificity score
        ``specificity_trend`` — linear regression slope of specificity
        ``grounding_index`` — composite score (0.0–1.0)
        ``grounding_class`` — anchored | substantiated | illustrated | unmoored
        ``phase_scores`` — list of 4 floats (quartile scores)
        ``phase_arc`` — deepening | stable | rising | falling
    """
    empty = {
        "strokes_analyzed": 0,
        "concrete_ratio": 0.0,
        "evidence_pairing": 0.0,
        "specificity_mean": 0.0,
        "specificity_trend": 0.0,
        "grounding_index": 0.0,
        "grounding_class": "unmoored",
        "phase_scores": [0.0, 0.0, 0.0, 0.0],
        "phase_arc": "stable",
    }

    if not strokes:
        return empty

    if len(strokes) == 1:
        text = _get_stroke_text(strokes[0])
        concrete = is_concrete_stroke(text)
        spec = analyze_specificity(text)
        tokens = _tokenize(text)
        has_claim = _has_claim_marker(tokens)
        pairing = 1.0 if (has_claim and concrete) else (0.0 if has_claim else 0.5)
        gi = _compute_index(1.0 if concrete else 0.0, pairing, spec)
        return {
            "strokes_analyzed": 1,
            "concrete_ratio": 1.0 if concrete else 0.0,
            "evidence_pairing": pairing,
            "specificity_mean": round(spec, 4),
            "specificity_trend": 0.0,
            "grounding_index": round(gi, 4),
            "grounding_class": _classify_grounding(gi),
            "phase_scores": [round(gi, 4), 0.0, 0.0, 0.0],
            "phase_arc": "stable",
        }

    texts = [_get_stroke_text(s) for s in strokes]
    concrete_flags = [is_concrete_stroke(t) for t in texts]
    specificity_scores = [analyze_specificity(t) for t in texts]

    concrete_ratio = sum(concrete_flags) / len(concrete_flags)
    evidence_pairing = analyze_evidence_pairing(strokes, pairing_window)
    specificity_mean = sum(specificity_scores) / len(specificity_scores)

    # Trend via simple linear regression
    specificity_trend = _linear_slope(specificity_scores)

    # Composite
    grounding_index = _compute_index(
        concrete_ratio, evidence_pairing, specificity_mean,
    )

    # Phase analysis
    phase_scores = _compute_phase_scores(texts)
    phase_arc = _classify_phase_arc(phase_scores)

    return {
        "strokes_analyzed": len(strokes),
        "concrete_ratio": round(concrete_ratio, 4),
        "evidence_pairing": round(evidence_pairing, 4),
        "specificity_mean": round(specificity_mean, 4),
        "specificity_trend": round(specificity_trend, 4),
        "grounding_index": round(grounding_index, 4),
        "grounding_class": _classify_grounding(grounding_index),
        "phase_scores": [round(s, 4) for s in phase_scores],
        "phase_arc": phase_arc,
    }


def _compute_index(
    concrete_ratio: float,
    evidence_pairing: float,
    specificity_mean: float,
) -> float:
    """Compute the composite grounding index.

    Weights: concrete_ratio 40%, evidence_pairing 35%,
    normalized specificity 25%.

    Specificity is normalized: scores above 2.0 per 100 words are
    considered fully specific (score 1.0).
    """
    norm_spec = min(specificity_mean / 2.0, 1.0)
    return (
        0.40 * concrete_ratio
        + 0.35 * evidence_pairing
        + 0.25 * norm_spec
    )


def _classify_grounding(grounding_index: float) -> str:
    """Map grounding_index to a class label."""
    if grounding_index >= 0.55:
        return "anchored"
    elif grounding_index >= 0.40:
        return "substantiated"
    elif grounding_index >= 0.25:
        return "illustrated"
    else:
        return "unmoored"


def _compute_phase_scores(texts: list[str]) -> list[float]:
    """Divide strokes into quartiles and compute grounding per quartile."""
    n = len(texts)
    if n == 0:
        return [0.0, 0.0, 0.0, 0.0]

    if n < 4:
        scores = [0.0, 0.0, 0.0, 0.0]
        for i, text in enumerate(texts):
            q = min(i, 3)
            concrete = 1.0 if is_concrete_stroke(text) else 0.0
            spec = min(analyze_specificity(text) / 2.0, 1.0)
            scores[q] = 0.5 * concrete + 0.5 * spec
        return scores

    q_size = n / 4.0
    quartile_values: list[list[float]] = [[], [], [], []]

    for i, text in enumerate(texts):
        q = min(int(i / q_size), 3)
        concrete = 1.0 if is_concrete_stroke(text) else 0.0
        spec = min(analyze_specificity(text) / 2.0, 1.0)
        score = 0.5 * concrete + 0.5 * spec
        quartile_values[q].append(score)

    return [
        sum(qv) / len(qv) if qv else 0.0
        for qv in quartile_values
    ]


def _classify_phase_arc(phase_scores: list[float]) -> str:
    """Classify the session's grounding trajectory across quartiles."""
    q1, q2, q3, q4 = phase_scores

    # Check for deepening: Q2 or Q3 > Q1 and Q4 >= Q3 (roughly)
    if (q2 > q1 + 0.03 or q3 > q1 + 0.03) and q4 >= q3 - 0.05:
        return "deepening"

    # Rising: Q4 > Q1 significantly
    if q4 > q1 + 0.08:
        return "rising"

    # Falling: Q1 > Q4 significantly
    if q1 > q4 + 0.08:
        return "falling"

    return "stable"


def _linear_slope(values: list[float]) -> float:
    """Compute the slope of a simple linear regression on values."""
    n = len(values)
    if n < 2:
        return 0.0

    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n

    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))

    if denominator == 0:
        return 0.0

    return numerator / denominator


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def format_grounding_report(metrics: dict[str, Any]) -> str:
    """Format grounding metrics as a readable report."""
    lines = [
        "## writer grounding density",
        "",
        f"strokes analyzed: {metrics['strokes_analyzed']}",
        f"grounding index: {metrics['grounding_index']}",
        f"grounding class: {metrics['grounding_class']}",
        "",
        "### signals",
        f"  concrete ratio: {metrics['concrete_ratio']}",
        f"  evidence pairing: {metrics['evidence_pairing']}",
        f"  specificity mean: {metrics['specificity_mean']}",
        f"  specificity trend: {metrics['specificity_trend']}",
        "",
        "### phase analysis",
    ]
    labels = ["Q1 (early)", "Q2", "Q3", "Q4 (late)"]
    for label, score in zip(labels, metrics["phase_scores"]):
        lines.append(f"  {label}: {score}")
    lines.append(f"  arc: {metrics['phase_arc']}")
    lines.append("")

    interp = _interpret(metrics)
    lines.append("### interpretation")
    lines.append(interp)
    lines.append("")

    return "\n".join(lines)


def _interpret(metrics: dict[str, Any]) -> str:
    """Generate a plain-language interpretation of the metrics."""
    gc = metrics["grounding_class"]
    pa = metrics["phase_arc"]

    parts = []

    if gc == "anchored":
        parts.append(
            "claims are densely supported with specific evidence — "
            "the writing reads as empirical and verifiable"
        )
    elif gc == "substantiated":
        parts.append(
            "most claims have supporting evidence but some assertions "
            "float free — typical of good analytical writing"
        )
    elif gc == "illustrated":
        parts.append(
            "occasional concrete examples punctuate an otherwise "
            "abstract discussion — evidence is gestured at, not committed"
        )
    else:
        parts.append(
            "almost no concrete anchoring — the session is a stream "
            "of generalizations without specific support"
        )

    if pa == "deepening":
        parts.append(
            "grounding deepens over the session: early framing gives "
            "way to accumulated evidence"
        )
    elif pa == "rising":
        parts.append(
            "the writer started abstract and found specifics later — "
            "a brainstorming-to-analysis transition"
        )
    elif pa == "falling":
        parts.append(
            "the writer started with specifics but drifted into "
            "abstraction — possibly fatigue or running out of data"
        )

    trend = metrics["specificity_trend"]
    if trend > 0.01:
        parts.append(
            "specificity is trending upward — strokes are getting "
            "more concrete over time"
        )
    elif trend < -0.01:
        parts.append(
            "specificity is trending downward — strokes are becoming "
            "more abstract over time"
        )

    return ". ".join(parts) + "."
