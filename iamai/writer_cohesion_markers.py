#!/usr/bin/env python3
"""writer_cohesion_markers — analyse discourse connective usage in text.

*Discourse markers* (also called *connectives* or *cohesion signals*)
are the words and phrases that explicitly signal how one clause
relates to the next: *however*, *therefore*, *in addition*, *meanwhile*.
They are the visible seams of an argument.

Too few markers and the reader must infer every relationship — the
text feels choppy or cryptic.  Too many and the prose reads like a
legal brief — laboured, over-signposted, patronising.  Skilled writers
vary their marker density and type to match the rhetorical situation.

This module counts and classifies discourse markers, computes density
and diversity metrics, and assigns a cohesion profile label.

Marker categories
-----------------

================  =====================================================
category          example markers
================  =====================================================
additive          also, furthermore, moreover, in addition, besides,
                  similarly, likewise, not only … but also
adversative       however, nevertheless, nonetheless, yet, still,
                  on the other hand, conversely, in contrast,
                  despite, although, whereas, while
causal            therefore, thus, hence, consequently, as a result,
                  because, since, so, accordingly, for this reason
temporal          then, next, meanwhile, subsequently, afterwards,
                  finally, eventually, previously, before, after,
                  first, second, lastly
conditional       if, unless, provided that, in case, whether,
                  assuming, given that, even if
================  =====================================================

Metrics
-------

========================  =============================================
metric                    meaning
========================  =============================================
total_sentences           sentences analysed
total_markers             raw marker count across all categories
marker_density            markers per sentence
additive_count            additive markers found
adversative_count         adversative markers found
causal_count              causal markers found
temporal_count            temporal markers found
conditional_count         conditional markers found
category_diversity        Shannon entropy of category distribution
                          in [0, log2(5)]; higher = more even use
                          across categories
dominant_category         the category with the most markers
                          (or ``"none"`` when total_markers == 0)
dominance_ratio           dominant category count / total_markers;
                          1.0 = all markers from one category
marker_richness           unique markers used / total marker
                          occurrences; higher = more varied vocabulary
cohesion_label            human-readable classification
========================  =============================================

Cohesion labels
---------------

================  =====================================================
label             description
================  =====================================================
balanced          moderate density with high category diversity;
                  the writer signals relationships explicitly and
                  varies the type of signal
dense             high density with moderate diversity; the text is
                  heavily signposted, which may feel laboured
sparse            low density; relationships are mostly implicit,
                  risking ambiguity or choppiness
monotone          moderate density but low diversity; the writer
                  over-relies on one category of connective
erratic           very uneven distribution across the text; some
                  paragraphs are over-signposted, others have none
absent            no markers detected at all
================  =====================================================
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Marker lexicon — compiled to regex at import time
# ---------------------------------------------------------------------------

_ADDITIVE: List[str] = [
    r"\balso\b", r"\bfurthermore\b", r"\bmoreover\b",
    r"\bin\s+addition\b", r"\bbesides\b", r"\bsimilarly\b",
    r"\blikewise\b", r"\bnot\s+only\b", r"\bas\s+well\s+as\b",
    r"\bwhat'?s\s+more\b",
]

_ADVERSATIVE: List[str] = [
    r"\bhowever\b", r"\bnevertheless\b", r"\bnonetheless\b",
    r"\byet\b", r"\bstill\b", r"\bon\s+the\s+other\s+hand\b",
    r"\bconversely\b", r"\bin\s+contrast\b", r"\bdespite\b",
    r"\balthough\b", r"\bwhereas\b", r"\bwhile\b",
    r"\beven\s+so\b", r"\brather\b",
]

_CAUSAL: List[str] = [
    r"\btherefore\b", r"\bthus\b", r"\bhence\b",
    r"\bconsequently\b", r"\bas\s+a\s+result\b",
    r"\bbecause\b", r"\bsince\b", r"\baccordingly\b",
    r"\bfor\s+this\s+reason\b", r"\bdue\s+to\b",
    r"\bleading\s+to\b",
]

_TEMPORAL: List[str] = [
    r"\bthen\b", r"\bnext\b", r"\bmeanwhile\b",
    r"\bsubsequently\b", r"\bafterwards\b", r"\bfinally\b",
    r"\beventually\b", r"\bpreviously\b", r"\bfirst\b",
    r"\bsecond\b", r"\blastly\b", r"\bbefore\b",
    r"\bafter\b", r"\bnow\b",
]

_CONDITIONAL: List[str] = [
    r"\bif\b", r"\bunless\b", r"\bprovided\s+that\b",
    r"\bin\s+case\b", r"\bwhether\b", r"\bassuming\b",
    r"\bgiven\s+that\b", r"\beven\s+if\b",
]

_CATEGORY_PATTERNS: Dict[str, List[re.Pattern]] = {
    "additive":    [re.compile(p, re.I) for p in _ADDITIVE],
    "adversative": [re.compile(p, re.I) for p in _ADVERSATIVE],
    "causal":      [re.compile(p, re.I) for p in _CAUSAL],
    "temporal":    [re.compile(p, re.I) for p in _TEMPORAL],
    "conditional": [re.compile(p, re.I) for p in _CONDITIONAL],
}

# For richness: map each pattern to a canonical name.
_CANONICAL: Dict[str, List[str]] = {
    "additive": [
        "also", "furthermore", "moreover", "in addition", "besides",
        "similarly", "likewise", "not only", "as well as", "what's more",
    ],
    "adversative": [
        "however", "nevertheless", "nonetheless", "yet", "still",
        "on the other hand", "conversely", "in contrast", "despite",
        "although", "whereas", "while", "even so", "rather",
    ],
    "causal": [
        "therefore", "thus", "hence", "consequently", "as a result",
        "because", "since", "accordingly", "for this reason", "due to",
        "leading to",
    ],
    "temporal": [
        "then", "next", "meanwhile", "subsequently", "afterwards",
        "finally", "eventually", "previously", "first", "second",
        "lastly", "before", "after", "now",
    ],
    "conditional": [
        "if", "unless", "provided that", "in case", "whether",
        "assuming", "given that", "even if",
    ],
}

# Sentence splitter — good enough for English prose.
_SENT_RE = re.compile(r"[^.!?\n]+[.!?]+|\S[^\n]*$")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> List[str]:
    """Split *text* into sentence-like spans."""
    if not text or not text.strip():
        return []
    spans = _SENT_RE.findall(text)
    return [s.strip() for s in spans if s.strip()]


def _find_markers(sentence: str) -> List[Tuple[str, str]]:
    """Return ``(category, canonical_name)`` for every marker in *sentence*."""
    found: List[Tuple[str, str]] = []
    for cat, patterns in _CATEGORY_PATTERNS.items():
        for i, pat in enumerate(patterns):
            if pat.search(sentence):
                found.append((cat, _CANONICAL[cat][i]))
    return found


def _shannon_entropy(counts: Dict[str, int]) -> float:
    """Shannon entropy of a discrete distribution (natural log)."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    h = 0.0
    for c in counts.values():
        if c > 0:
            p = c / total
            h -= p * math.log(p)
    return h


def _classify(
    density: float,
    diversity: float,
    dominance_ratio: float,
    total_markers: int,
    per_sentence_counts: List[int],
) -> str:
    """Assign a cohesion profile label."""
    if total_markers == 0:
        return "absent"

    # Erratic: high variance in per-sentence marker counts.
    if len(per_sentence_counts) >= 4:
        mean_c = sum(per_sentence_counts) / len(per_sentence_counts)
        if mean_c > 0:
            var_c = sum((c - mean_c) ** 2 for c in per_sentence_counts) / len(per_sentence_counts)
            cv = math.sqrt(var_c) / mean_c
            if cv > 1.5:
                return "erratic"

    # Monotone: one category dominates (> 70 %).
    if dominance_ratio > 0.70 and total_markers >= 3:
        return "monotone"

    # Sparse: low density.
    if density < 0.25:
        return "sparse"

    # Dense: high density.
    if density > 1.0:
        return "dense"

    # Balanced: moderate density with decent diversity.
    if diversity > 0.8:
        return "balanced"

    # Fall-through for moderate density but low diversity.
    if dominance_ratio > 0.55:
        return "monotone"

    return "balanced"


def _empty_result() -> Dict[str, Any]:
    """Zeroed-out result for empty input."""
    return {
        "total_sentences": 0,
        "total_markers": 0,
        "marker_density": 0.0,
        "additive_count": 0,
        "adversative_count": 0,
        "causal_count": 0,
        "temporal_count": 0,
        "conditional_count": 0,
        "category_diversity": 0.0,
        "dominant_category": "none",
        "dominance_ratio": 0.0,
        "marker_richness": 0.0,
        "cohesion_label": "absent",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_cohesion(text: str) -> Dict[str, Any]:
    """Analyse discourse marker usage in *text*.

    Returns a dict with all metrics listed in the module docstring.
    """
    sentences = _split_sentences(text)
    if not sentences:
        return _empty_result()

    cat_counts: Dict[str, int] = {c: 0 for c in _CATEGORY_PATTERNS}
    unique_markers: set = set()
    per_sentence_counts: List[int] = []

    for sent in sentences:
        markers = _find_markers(sent)
        per_sentence_counts.append(len(markers))
        for cat, name in markers:
            cat_counts[cat] += 1
            unique_markers.add(name)

    total_markers = sum(cat_counts.values())
    total_sentences = len(sentences)
    density = total_markers / total_sentences if total_sentences else 0.0
    diversity = _shannon_entropy(cat_counts)
    dominant = max(cat_counts, key=cat_counts.get)  # type: ignore[arg-type]
    dom_ratio = cat_counts[dominant] / total_markers if total_markers else 0.0
    richness = len(unique_markers) / total_markers if total_markers else 0.0

    label = _classify(density, diversity, dom_ratio, total_markers, per_sentence_counts)

    return {
        "total_sentences": total_sentences,
        "total_markers": total_markers,
        "marker_density": round(density, 4),
        "additive_count": cat_counts["additive"],
        "adversative_count": cat_counts["adversative"],
        "causal_count": cat_counts["causal"],
        "temporal_count": cat_counts["temporal"],
        "conditional_count": cat_counts["conditional"],
        "category_diversity": round(diversity, 4),
        "dominant_category": dominant if total_markers else "none",
        "dominance_ratio": round(dom_ratio, 4),
        "marker_richness": round(richness, 4),
        "cohesion_label": label,
    }


def cohesion_report(strokes_path: str = "data/strokes.jsonl") -> Dict[str, Any]:
    """On-disk wrapper: read strokes and analyse concatenated text."""
    path = Path(strokes_path)
    if not path.exists():
        return _empty_result()

    texts: List[str] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            body = rec.get("text", "") or rec.get("body", "") or ""
            if body.strip():
                texts.append(body)

    if not texts:
        return _empty_result()
    return compute_cohesion("\n\n".join(texts))


def cohesion_summary(result: Dict[str, Any]) -> str:
    """Human-readable summary of cohesion analysis."""
    lines = [
        f"sentences:       {result['total_sentences']}",
        f"total markers:   {result['total_markers']}",
        f"density:         {result['marker_density']:.4f} per sentence",
        f"additive:        {result['additive_count']}",
        f"adversative:     {result['adversative_count']}",
        f"causal:          {result['causal_count']}",
        f"temporal:        {result['temporal_count']}",
        f"conditional:     {result['conditional_count']}",
        f"diversity (H):   {result['category_diversity']:.4f}",
        f"dominant:        {result['dominant_category']} ({result['dominance_ratio']:.2f})",
        f"richness:        {result['marker_richness']:.4f}",
        f"label:           {result['cohesion_label']}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyse discourse cohesion markers in strokes."
    )
    parser.add_argument(
        "--strokes", default="data/strokes.jsonl",
        help="Path to strokes JSONL (default: data/strokes.jsonl)",
    )
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args(argv)

    result = cohesion_report(args.strokes)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(cohesion_summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
