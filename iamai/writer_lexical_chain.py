#!/usr/bin/env python3
"""writer_lexical_chain — track how concepts propagate through text.

A *lexical chain* is a sequence of semantically related words that
appear across consecutive or nearby sentences, forming a thread of
meaning that runs through the text.  Where anchor words (see
``writer_anchor_words``) identify recurring concepts at the text
level, lexical chains follow the *evolution* of specific concepts
from sentence to sentence, measuring how smoothly ideas propagate.

A text with strong lexical chains reads as a continuous argument or
narrative: each sentence picks up a concept from the previous one
and develops it further.  A text with weak chains feels
disconnected — ideas appear, vanish, and reappear without apparent
logic.

This module identifies lexical chains using word-form overlap
(exact match and morphological variants sharing a stem prefix)
between adjacent sentences, and quantifies six dimensions of
chain behaviour.

========================  =============================================
metric                    meaning
========================  =============================================
total_sentences           number of sentences analysed
total_chains              number of distinct lexical chains
                          detected (a chain is a run of ≥ 2
                          consecutive sentences sharing at
                          least one content word)
mean_chain_length         mean sentences per chain
max_chain_length          longest chain detected
chain_coverage            fraction of sentences that belong
                          to at least one chain
chain_density             mean number of linking words per
                          chain-connected sentence pair
chain_continuity          1 − normalised gap count; measures
                          how often chains bridge across
                          paragraph boundaries without
                          breaking
propagation_index         composite score in [0, 1]; higher
                          means ideas flow more smoothly
                          through the text
chain_label               human-readable classification
========================  =============================================

Chain labels
------------

================  =====================================================
label             description
================  =====================================================
flowing           long chains with high coverage and continuity;
                  ideas propagate seamlessly sentence to sentence
coherent          moderate chains with good coverage; the text
                  maintains clear thematic threads with occasional
                  topic shifts
threaded          several shorter chains running in parallel; the
                  text weaves multiple ideas without fully
                  developing any single one
episodic          chains cluster within paragraphs but rarely
                  cross boundaries; each paragraph is self-
                  contained with weak inter-paragraph flow
scattered         very short chains with low coverage; ideas
                  appear and disappear without sustained
                  development
disconnected      almost no chains detected; sentences read as
                  independent propositions with no lexical
                  continuity
================  =====================================================

Usage::

    python3 -m iamai.writer_lexical_chain              # last 200 strokes
    python3 -m iamai.writer_lexical_chain -n 500       # last 500 strokes
    python3 -m iamai.writer_lexical_chain --json       # full JSON report
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

STOP_WORDS = frozenset({
    "a", "an", "the", "and", "but", "or", "nor", "for", "yet", "so",
    "in", "on", "at", "to", "from", "by", "of", "with", "as", "into",
    "through", "during", "before", "after", "above", "below", "between",
    "under", "over", "out", "off", "up", "down", "is", "am", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "may", "might",
    "shall", "can", "need", "dare", "ought", "used", "it", "its",
    "this", "that", "these", "those", "i", "me", "my", "we", "our",
    "you", "your", "he", "him", "his", "she", "her", "they", "them",
    "their", "what", "which", "who", "whom", "when", "where", "why",
    "how", "not", "no", "nor", "if", "then", "than", "too", "very",
    "just", "about", "also", "more", "most", "some", "any", "all",
    "each", "every", "both", "few", "many", "much", "other", "another",
    "such", "only", "own", "same", "so", "here", "there", "now",
    "once", "again", "further", "because", "until", "while", "since",
    "although", "though", "however", "therefore", "moreover",
    "furthermore", "nevertheless", "nonetheless", "accordingly",
    "consequently", "meanwhile", "otherwise", "instead", "indeed",
    "thus", "hence", "still", "already", "even", "also", "well",
    "back", "like", "make", "made", "get", "got", "go", "went",
    "gone", "come", "came", "take", "took", "give", "gave", "know",
    "knew", "think", "thought", "say", "said", "let", "see", "saw",
    "want", "look", "put", "keep", "begin", "seem", "help", "show",
    "hear", "play", "run", "move", "live", "believe", "bring",
    "happen", "write", "provide", "sit", "stand", "lose", "pay",
    "meet", "include", "continue", "set", "learn", "change", "lead",
    "understand", "watch", "follow", "stop", "create", "speak",
    "read", "allow", "add", "spend", "grow", "open", "walk", "win",
    "offer", "remember", "love", "consider", "appear", "buy", "wait",
    "serve", "die", "send", "expect", "build", "stay", "fall", "cut",
    "reach", "kill", "remain", "suggest", "raise", "pass", "sell",
    "require", "report", "decide", "pull", "develop",
})

_MIN_WORD_LEN = 3
_MIN_CHAIN_LEN = 2  # A chain must span at least 2 sentences.

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STROKES_FILE = DATA_DIR / "strokes.jsonl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Lowercase tokenise, stripping punctuation and short words."""
    tokens = re.findall(r"[a-zA-Z']+", text.lower())
    return [t for t in tokens if len(t) >= _MIN_WORD_LEN]


def _content_words(tokens: list[str]) -> list[str]:
    """Filter tokens to content words only (not stop words)."""
    return [t for t in tokens if t not in STOP_WORDS]


def _word_set(text: str) -> set[str]:
    """Return set of content words in text."""
    return set(_content_words(_tokenize(text)))


def _split_paragraphs(text: str) -> list[str]:
    """Split text on blank lines."""
    paras = re.split(r"\n\s*\n", text.strip())
    return [p.strip() for p in paras if p.strip()]


def _split_sentences(text: str) -> list[str]:
    """Naive sentence splitting on terminal punctuation."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


def _stem(word: str) -> str:
    """Very simple suffix-stripping stemmer.

    Not linguistically rigorous — good enough to link obvious
    morphological variants (running → run, servers → server,
    analysed → analys).
    """
    if len(word) <= 4:
        return word
    for suffix in ("ing", "tion", "sion", "ness", "ment", "able",
                   "ible", "ful", "less", "ous", "ive", "aly",
                   "ly", "ed", "er", "es", "al", "en", "ty", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _stem_set(words: set[str]) -> set[str]:
    """Return set of stems for a word set."""
    return {_stem(w) for w in words}


def _linking_words(words_a: set[str], words_b: set[str]) -> set[str]:
    """Content words that link two sentences via stem overlap.

    A word in sentence A links to sentence B if its stem matches
    the stem of any content word in B.  We return the union of
    matching original words from both sides.
    """
    stems_a = {(_stem(w), w) for w in words_a}
    stems_b = {(_stem(w), w) for w in words_b}
    stem_set_a = {s for s, _ in stems_a}
    stem_set_b = {s for s, _ in stems_b}
    shared_stems = stem_set_a & stem_set_b
    links = set()
    for s, w in stems_a:
        if s in shared_stems:
            links.add(w)
    for s, w in stems_b:
        if s in shared_stems:
            links.add(w)
    return links


# ---------------------------------------------------------------------------
# Chain detection
# ---------------------------------------------------------------------------

def _detect_chains(
    sentence_words: list[set[str]],
    paragraph_breaks: list[int],
) -> list[dict[str, Any]]:
    """Detect lexical chains across a sequence of sentences.

    A chain is a maximal run of consecutive sentences where each
    adjacent pair shares at least one content word (by stem).

    Parameters
    ----------
    sentence_words:
        List of content-word sets, one per sentence.
    paragraph_breaks:
        Sorted list of sentence indices where a paragraph boundary
        precedes the sentence (i.e. there is a blank line between
        sentence i−1 and sentence i).

    Returns
    -------
    List of chain dicts with keys: start, end, length, links,
    crosses_paragraph.
    """
    if len(sentence_words) < 2:
        return []

    chains: list[dict[str, Any]] = []
    break_set = set(paragraph_breaks)

    # Walk through sentences; track current chain.
    chain_start = 0
    chain_links: list[set[str]] = []
    in_chain = False

    for i in range(1, len(sentence_words)):
        links = _linking_words(sentence_words[i - 1], sentence_words[i])
        if links:
            if not in_chain:
                chain_start = i - 1
                chain_links = []
                in_chain = True
            chain_links.append(links)
        else:
            if in_chain:
                chain_end = i - 1
                chain_length = chain_end - chain_start + 1
                if chain_length >= _MIN_CHAIN_LEN:
                    crosses = any(
                        chain_start < b <= chain_end for b in break_set
                    )
                    chains.append({
                        "start": chain_start,
                        "end": chain_end,
                        "length": chain_length,
                        "links": chain_links,
                        "crosses_paragraph": crosses,
                    })
                in_chain = False

    # Flush final chain.
    if in_chain:
        chain_end = len(sentence_words) - 1
        chain_length = chain_end - chain_start + 1
        if chain_length >= _MIN_CHAIN_LEN:
            crosses = any(
                chain_start < b <= chain_end for b in break_set
            )
            chains.append({
                "start": chain_start,
                "end": chain_end,
                "length": chain_length,
                "links": chain_links,
                "crosses_paragraph": crosses,
            })

    return chains


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_lexical_chains(
    texts: list[str],
) -> dict[str, Any]:
    """Compute lexical chain metrics for a list of stroke texts.

    Parameters
    ----------
    texts:
        List of text strings (one per stroke).

    Returns
    -------
    dict with all lexical chain metrics.
    """
    if not texts:
        return _empty_result()

    combined = "\n\n".join(texts)
    paragraphs = _split_paragraphs(combined)

    if not paragraphs:
        return _empty_result()

    # Build flat sentence list and record paragraph boundaries.
    all_sentences: list[str] = []
    sentence_words: list[set[str]] = []
    paragraph_breaks: list[int] = []

    for p_idx, para in enumerate(paragraphs):
        sentences = _split_sentences(para)
        for s_idx, sent in enumerate(sentences):
            if p_idx > 0 and s_idx == 0:
                paragraph_breaks.append(len(all_sentences))
            all_sentences.append(sent)
            sentence_words.append(_word_set(sent))

    total_sentences = len(all_sentences)
    if total_sentences < 2:
        return _empty_result()

    # Detect chains.
    chains = _detect_chains(sentence_words, paragraph_breaks)
    total_chains = len(chains)

    if total_chains == 0:
        return _no_chain_result(total_sentences)

    # Chain lengths.
    chain_lengths = [c["length"] for c in chains]
    mean_chain_length = sum(chain_lengths) / total_chains
    max_chain_length = max(chain_lengths)

    # Chain coverage: fraction of sentences in at least one chain.
    covered = set()
    for c in chains:
        for idx in range(c["start"], c["end"] + 1):
            covered.add(idx)
    chain_coverage = len(covered) / total_sentences

    # Chain density: mean linking words per connected pair.
    all_link_counts = [len(lk) for c in chains for lk in c["links"]]
    chain_density = (
        sum(all_link_counts) / len(all_link_counts)
        if all_link_counts else 0.0
    )

    # Chain continuity: fraction of chain connections that cross
    # paragraph boundaries.  Higher means chains bridge paragraphs.
    cross_count = sum(1 for c in chains if c["crosses_paragraph"])
    cross_fraction = cross_count / total_chains if total_chains else 0.0

    # Gaps: number of sentence pairs NOT linked within the span of
    # all chains.  A chain of length L has L−1 linked pairs; the
    # total possible pairs in the span is L−1, so intra-chain gaps
    # are zero by definition.  But we also count inter-chain gaps.
    # Continuity = 1 − (unlinked adjacent pairs / total adjacent pairs).
    linked_pairs = set()
    for c in chains:
        for idx in range(c["start"], c["end"]):
            linked_pairs.add(idx)
    total_pairs = total_sentences - 1
    unlinked_pairs = total_pairs - len(linked_pairs)
    chain_continuity = 1.0 - (unlinked_pairs / total_pairs) if total_pairs else 0.0

    # Propagation index: weighted composite in [0, 1].
    #   coverage (0.30) — more sentences in chains = better
    #   mean_length_norm (0.25) — longer chains = better, capped at 8
    #   density_norm (0.20) — more linking words = richer connections
    #   continuity (0.15) — fewer gaps = smoother flow
    #   cross_fraction (0.10) — cross-paragraph chains = deeper flow

    mean_length_norm = min(mean_chain_length / 8.0, 1.0)
    density_norm = min(chain_density / 3.0, 1.0)

    propagation_index = (
        0.30 * chain_coverage
        + 0.25 * mean_length_norm
        + 0.20 * density_norm
        + 0.15 * chain_continuity
        + 0.10 * cross_fraction
    )
    propagation_index = round(max(0.0, min(1.0, propagation_index)), 4)

    chain_label = _classify(
        propagation_index, chain_coverage, mean_chain_length,
        max_chain_length, chain_density, chain_continuity,
        total_chains, total_sentences,
    )

    return {
        "total_sentences": total_sentences,
        "total_chains": total_chains,
        "mean_chain_length": round(mean_chain_length, 2),
        "max_chain_length": max_chain_length,
        "chain_coverage": round(chain_coverage, 4),
        "chain_density": round(chain_density, 4),
        "chain_continuity": round(chain_continuity, 4),
        "cross_paragraph_fraction": round(cross_fraction, 4),
        "propagation_index": propagation_index,
        "chain_label": chain_label,
    }


def _empty_result() -> dict[str, Any]:
    """Return a zeroed-out result when there is no text to analyse."""
    return {
        "total_sentences": 0,
        "total_chains": 0,
        "mean_chain_length": 0.0,
        "max_chain_length": 0,
        "chain_coverage": 0.0,
        "chain_density": 0.0,
        "chain_continuity": 0.0,
        "cross_paragraph_fraction": 0.0,
        "propagation_index": 0.0,
        "chain_label": "disconnected",
    }


def _no_chain_result(total_sentences: int) -> dict[str, Any]:
    """Return result when sentences exist but no chains detected."""
    return {
        "total_sentences": total_sentences,
        "total_chains": 0,
        "mean_chain_length": 0.0,
        "max_chain_length": 0,
        "chain_coverage": 0.0,
        "chain_density": 0.0,
        "chain_continuity": 0.0,
        "cross_paragraph_fraction": 0.0,
        "propagation_index": 0.0,
        "chain_label": "disconnected",
    }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _classify(
    propagation_index: float,
    coverage: float,
    mean_length: float,
    max_length: int,
    density: float,
    continuity: float,
    total_chains: int,
    total_sentences: int,
) -> str:
    """Classify the text's lexical chain profile."""
    # Disconnected: no or near-zero propagation.
    if propagation_index < 0.15:
        return "disconnected"

    # Scattered: low coverage, short chains.
    if coverage < 0.40 and mean_length < 3.0:
        return "scattered"

    # Episodic: decent within-paragraph chains but poor cross-paragraph.
    if continuity >= 0.50 and propagation_index < 0.55:
        # Check if cross-paragraph fraction is low relative to coverage.
        return "episodic"

    # Threaded: many short chains, moderate coverage.
    if total_chains >= 5 and mean_length < 4.0 and coverage >= 0.40:
        return "threaded"

    # Coherent: moderate-to-good propagation.
    if 0.45 <= propagation_index < 0.70:
        return "coherent"

    # Flowing: high propagation with good coverage and length.
    if propagation_index >= 0.70:
        return "flowing"

    # Default fallback.
    return "coherent"


# ---------------------------------------------------------------------------
# Summary & report
# ---------------------------------------------------------------------------

def _summary(result: dict[str, Any]) -> str:
    """One-line human-readable summary."""
    label = result["chain_label"]
    pi = result["propagation_index"]
    tc = result["total_chains"]
    mc = result["mean_chain_length"]
    cov = result["chain_coverage"]
    return (
        f"lexical chains: {label} (index={pi:.2f}, "
        f"{tc} chains, mean_len={mc:.1f}, coverage={cov:.0%})"
    )


def _load_strokes(n: int = 200) -> list[str]:
    """Load the last *n* stroke texts from the JSONL file."""
    if not STROKES_FILE.exists():
        return []
    lines = STROKES_FILE.read_text(encoding="utf-8").strip().splitlines()
    recent = lines[-n:] if len(lines) >= n else lines
    texts = []
    for line in recent:
        try:
            obj = json.loads(line)
            text = obj.get("text", "")
            if text:
                texts.append(text)
        except json.JSONDecodeError:
            continue
    return texts


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Analyse lexical chains in recent writer strokes."
    )
    parser.add_argument(
        "-n", "--num-strokes", type=int, default=200,
        help="Number of recent strokes to analyse (default: 200).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output full JSON report.",
    )
    args = parser.parse_args(argv)

    strokes = _load_strokes(args.num_strokes)
    result = compute_lexical_chains(strokes)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(_summary(result))
        print(f"  total sentences: {result['total_sentences']}")
        print(f"  total chains:    {result['total_chains']}")
        print(f"  mean chain len:  {result['mean_chain_length']:.1f}")
        print(f"  max chain len:   {result['max_chain_length']}")
        print(f"  coverage:        {result['chain_coverage']:.1%}")
        print(f"  density:         {result['chain_density']:.2f}")
        print(f"  continuity:      {result['chain_continuity']:.1%}")
        print(f"  cross-para:      {result['cross_paragraph_fraction']:.1%}")
        print(f"  propagation:     {result['propagation_index']:.4f}")


if __name__ == "__main__":
    main()
