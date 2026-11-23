#!/usr/bin/env python3
"""writer_clause_connectivity — analyse how clauses are linked in text.

Clause connectivity describes *how* a text connects its propositions:
through explicit **coordination** (and, but, or, yet, so), explicit
**subordination** (because, although, if, when, while, since, unless,
after, before, until, whereas, though, whether), or **parataxis**
(juxtaposition without an overt connector — independent sentences or
semicolon-joined clauses).

A well-connected text uses a mix of all three strategies.  Too much
subordination produces labyrinthine sentences that tax working memory;
too much coordination yields a flat, list-like cadence; too much
parataxis forces the reader to infer logical relationships that the
writer left unstated.

========================  =============================================
metric                    meaning
========================  =============================================
total_clauses             total clause-like segments detected
coordination_ratio        fraction of clauses introduced by a
                          coordinating conjunction
subordination_ratio       fraction introduced by a subordinating
                          conjunction
parataxis_ratio           fraction with no explicit connector
                          (1 − coord − subord)
mean_nesting_depth        average subordinating-conjunction count
                          per sentence (proxy for embedding depth)
connectivity_index        Shannon entropy of the three ratios,
                          normalised to [0, 1]; 1 = perfectly
                          balanced mix
avg_clauses_per_sentence  mean clauses per sentence
connectivity_label      human-readable classification
========================  =============================================

Connectivity labels
-------------------

================  =====================================================
label             description
================  =====================================================
balanced          all three strategies contribute meaningfully;
                  connectivity index ≥ 0.85
telegraphic       very few conjunctions of any kind; short,
                  independent clauses dominate
coordinated       coordination dominates; the text reads like a
                  list joined by "and" / "but"
subordinated      subordination dominates; long, nested sentences
                  with heavy embedding
paratactic        parataxis dominates; the reader must infer
                  connections between juxtaposed sentences
mixed-shift       connectivity index is moderate but the dominant
                  strategy varies sentence by sentence
================  =====================================================

Usage::

    python3 -m iamai.writer_clause_connectivity              # last 200 strokes
    python3 -m iamai.writer_clause_connectivity -n 500       # last 500 strokes
    python3 -m iamai.writer_clause_connectivity --json       # full JSON report
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COORDINATING = frozenset({
    "and", "but", "or", "yet", "so", "nor", "for",
})

SUBORDINATING = frozenset({
    "because", "although", "if", "when", "while", "since", "unless",
    "after", "before", "until", "whereas", "though", "whether",
    "whenever", "wherever", "since", "provided", "once", "as",
    "inasmuch", "lest", "till",
})

# Words that may open a sentence but are not subordinating
_SENTENCE_OPENERS = frozenset({
    "however", "therefore", "moreover", "furthermore", "nevertheless",
    "consequently", "accordingly", "meanwhile", "indeed", "thus",
    "hence", "then", "also", "still", "otherwise", "instead",
})

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STROKES_FILE = DATA_DIR / "strokes.jsonl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Lowercase tokenise, stripping punctuation."""
    return re.findall(r"[a-zA-Z']+", text.lower())


def _split_sentences(text: str) -> list[str]:
    """Naive sentence splitting on terminal punctuation."""
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p for p in parts if p]


def _clause_segments(sentence: str) -> list[dict[str, Any]]:
    """Split a sentence into clause-like segments.

    A clause segment is either:
    - the text before the first conjunction (main clause), or
    - the text introduced by a conjunction.

    This is a heuristic splitter — it does not parse full syntax trees.
    """
    tokens = _tokenize(sentence)
    if not tokens:
        return []

    segments: list[dict[str, Any]] = []
    current_connector: str | None = None
    current_type: str = "main"
    current_words: list[str] = []

    for tok in tokens:
        if tok in COORDINATING and current_words:
            segments.append({
                "connector": current_connector,
                "type": current_type,
                "words": current_words,
            })
            current_connector = tok
            current_type = "coordinated"
            current_words = []
        elif tok in SUBORDINATING and current_words:
            segments.append({
                "connector": current_connector,
                "type": current_type,
                "words": current_words,
            })
            current_connector = tok
            current_type = "subordinated"
            current_words = []
        else:
            current_words.append(tok)

    if current_words:
        segments.append({
            "connector": current_connector,
            "type": current_type,
            "words": current_words,
        })

    return segments


def _sentence_nesting_depth(sentence: str) -> int:
    """Count subordinating conjunctions as a proxy for embedding depth."""
    tokens = _tokenize(sentence)
    return sum(1 for t in tokens if t in SUBORDINATING)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_connectivity(texts: list[str]) -> dict[str, Any]:
    """Compute clause-connectivity metrics from a list of text strings.

    Returns a dict with all metrics listed in the module docstring.
    """
    total_clauses = 0
    coord_count = 0
    subord_count = 0
    total_sentences = 0
    depth_sum = 0
    per_sentence_dominant: list[str] = []

    for text in texts:
        sentences = _split_sentences(text)
        for sent in sentences:
            total_sentences += 1
            depth_sum += _sentence_nesting_depth(sent)
            segments = _clause_segments(sent)
            dominant = "paratactic"
            max_count = 0
            for seg in segments:
                total_clauses += 1
                if seg["type"] == "coordinated":
                    coord_count += 1
                    if 1 > max_count:
                        dominant = "coordinated"
                        max_count = 1
                elif seg["type"] == "subordinated":
                    subord_count += 1
                    if 1 > max_count:
                        dominant = "subordinated"
                        max_count = 1
            per_sentence_dominant.append(dominant)

    if total_clauses == 0:
        return {
            "total_clauses": 0,
            "coordination_ratio": 0.0,
            "subordination_ratio": 0.0,
            "parataxis_ratio": 1.0,
            "mean_nesting_depth": 0.0,
            "connectivity_index": 0.0,
            "avg_clauses_per_sentence": 0.0,
            "connectivity_label": "telegraphic",
        }

    coord_r = coord_count / total_clauses
    subord_r = subord_count / total_clauses
    parataxis_r = max(0.0, 1.0 - coord_r - subord_r)

    # Shannon entropy of the three-way split, normalised to [0, 1]
    ratios = [coord_r, subord_r, parataxis_r]
    entropy = -sum(r * math.log2(r) for r in ratios if r > 0)
    max_entropy = math.log2(3)
    conn_index = entropy / max_entropy if max_entropy > 0 else 0.0

    mean_depth = depth_sum / total_sentences if total_sentences else 0.0
    avg_cps = total_clauses / total_sentences if total_sentences else 0.0

    label = _classify(
        coord_r, subord_r, parataxis_r, conn_index,
        per_sentence_dominant, mean_depth,
    )

    return {
        "total_clauses": total_clauses,
        "coordination_ratio": round(coord_r, 4),
        "subordination_ratio": round(subord_r, 4),
        "parataxis_ratio": round(parataxis_r, 4),
        "mean_nesting_depth": round(mean_depth, 4),
        "connectivity_index": round(conn_index, 4),
        "avg_clauses_per_sentence": round(avg_cps, 4),
        "connectivity_label": label,
    }


def _classify(
    coord_r: float,
    subord_r: float,
    parataxis_r: float,
    conn_index: float,
    per_sentence_dominant: list[str],
    mean_depth: float,
) -> str:
    """Classify the connectivity pattern into one of 6 labels."""

    # Very few clauses overall → telegraphic
    if len(per_sentence_dominant) < 3:
        return "telegraphic"

    # Balanced: all three strategies present with high entropy
    if conn_index >= 0.85:
        return "balanced"

    # Check for shifting dominance across sentences
    if len(per_sentence_dominant) >= 6:
        shifts = sum(
            1 for i in range(1, len(per_sentence_dominant))
            if per_sentence_dominant[i] != per_sentence_dominant[i - 1]
        )
        shift_rate = shifts / (len(per_sentence_dominant) - 1)
        if shift_rate > 0.6 and conn_index >= 0.5:
            return "mixed-shift"

    # Single-strategy dominance
    if coord_r >= 0.45:
        return "coordinated"
    if subord_r >= 0.45:
        return "subordinated"
    if parataxis_r >= 0.6:
        return "paratactic"

    # Moderate subordination with depth
    if mean_depth >= 1.5:
        return "subordinated"

    # Fallback: paratactic if nothing else matches
    if parataxis_r >= 0.4:
        return "paratactic"

    return "mixed-shift"


# ---------------------------------------------------------------------------
# On-disk integration
# ---------------------------------------------------------------------------

def _load_strokes(n: int = 200) -> list[str]:
    """Load the last *n* stroke texts from the JSONL file."""
    if not STROKES_FILE.exists():
        return []
    lines = STROKES_FILE.read_text(encoding="utf-8").strip().splitlines()
    texts: list[str] = []
    for line in lines[-n:]:
        try:
            obj = json.loads(line)
            t = obj.get("text", "")
            if t:
                texts.append(t)
        except json.JSONDecodeError:
            continue
    return texts


def connectivity_report(n: int = 200) -> dict[str, Any]:
    """Compute connectivity metrics from the on-disk strokes file."""
    texts = _load_strokes(n)
    metrics = compute_connectivity(texts)
    metrics["strokes_analysed"] = len(texts)
    return metrics


def connectivity_summary(metrics: dict[str, Any]) -> str:
    """Human-readable summary of connectivity metrics."""
    lines = [
        f"Clauses analysed : {metrics['total_clauses']}",
        f"Coordination     : {metrics['coordination_ratio']:.2%}",
        f"Subordination    : {metrics['subordination_ratio']:.2%}",
        f"Parataxis        : {metrics['parataxis_ratio']:.2%}",
        f"Nesting depth    : {metrics['mean_nesting_depth']:.2f}",
        f"Connectivity idx : {metrics['connectivity_index']:.3f}",
        f"Clauses/sentence : {metrics['avg_clauses_per_sentence']:.2f}",
        f"Label            : {metrics['connectivity_label']}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Analyse clause connectivity in recent strokes.",
    )
    ap.add_argument(
        "-n", "--strokes", type=int, default=200,
        help="number of recent strokes to analyse (default: 200)",
    )
    ap.add_argument(
        "--json", action="store_true",
        help="output full JSON report",
    )
    args = ap.parse_args(argv)

    metrics = connectivity_report(args.strokes)

    if args.json:
        print(json.dumps(metrics, indent=2, ensure_ascii=False))
    else:
        print(connectivity_summary(metrics))

    return 0


if __name__ == "__main__":
    sys.exit(main())
