#!/usr/bin/env python3
"""writer_thematic_progression — analyse how themes develop across sentences.

*Thematic progression* describes how the "aboutness" of a text evolves
from one sentence to the next.  Drawing on Daneš's (1974) thematic
progression model and its computational adaptations, this module
identifies four basic patterns and quantifies six dimensions of
thematic development.

In every sentence the *theme* is the part that connects back to what
has already been said (roughly: the grammatical subject and its
modifiers), while the *rheme* carries new information (roughly: the
predicate and its complements).  How themes and rhemes chain together
determines whether a text reads as a coherent argument, a list of
disconnected facts, or something in between.

Thematic patterns
-----------------

================  =====================================================
pattern           description
================  =====================================================
linear            the rheme (new info) of sentence *N* becomes the
                  theme (topic) of sentence *N+1*; each sentence
                  advances the argument by one step
constant          the same theme word persists across consecutive
                  sentences; the text elaborates on a single subject
                  without shifting focus
derived           a hypertheme introduced early spawns sub-themes in
                  later sentences; the text develops facets of one
                  overarching topic
split-rheme       one sentence introduces multiple new concepts that
                  each become themes of subsequent sentences; the
                  text branches out from a single statement
================  =====================================================

Metrics
-------

========================  =============================================
metric                    meaning
========================  =============================================
total_sentences           number of sentences analysed
linear_ratio              fraction of adjacent sentence pairs
                          showing linear (rheme→theme) progression
constant_ratio            fraction of adjacent pairs sharing the
                          same theme word
derived_ratio             fraction of pairs where a later theme is
                          a morphological or substring variant of
                          an earlier rheme word
split_ratio               fraction of sentence pairs where one
                          rheme splits into ≥ 2 subsequent themes
theme_persistence         mean number of consecutive sentences a
                          theme word survives as theme (≥ 2)
rheme_novelty             mean fraction of rheme content words
                          that have not appeared in any prior
                          sentence
progression_index         composite score in [0, 1]; higher
                          means more deliberate and varied
                          thematic development
progression_label         human-readable classification
========================  =============================================

Progression labels
------------------

================  =====================================================
label             description
================  =====================================================
orchestrated      multiple progression patterns interleave with
                  high persistence and novelty; the text develops
                  ideas with deliberate structure
developing        clear progression with moderate persistence;
                  themes evolve steadily with occasional elaboration
focused           predominantly constant theme; the text stays
                  tightly on one subject with limited development
linear-drift      mostly linear progression with low persistence;
                  each sentence advances but never circles back
scattered         low ratios across all patterns; themes shift
                  without apparent logic
stagnant          near-zero progression of any kind; sentences
                  appear thematically independent
================  =====================================================

Usage::

    python3 -m iamai.writer_thematic_progression            # last 200 strokes
    python3 -m iamai.writer_thematic_progression -n 500     # last 500 strokes
    python3 -m iamai.writer_thematic_progression --json     # full JSON report
"""

from __future__ import annotations

import argparse
import json
import re
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


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences on '.', '!', '?', or newlines."""
    parts = re.split(r'[.!?]+|\n', text)
    sentences = []
    for p in parts:
        s = p.strip()
        if s:
            sentences.append(s)
    return sentences


def _theme_words(sentence: str) -> list[str]:
    """Extract approximate theme words from a sentence.

    Heuristic: the theme is approximated by the content words that
    appear in the first half of the sentence (by token count).
    For very short sentences (≤ 3 tokens), all content words are
    treated as theme.
    """
    tokens = _tokenize(sentence)
    content = _content_words(tokens)
    if len(tokens) <= 3:
        return content
    mid = max(1, len(content) // 2)
    return content[:mid]


def _rheme_words(sentence: str) -> list[str]:
    """Extract approximate rheme words from a sentence.

    Heuristic: the rheme is approximated by the content words that
    appear in the second half of the sentence (by token count).
    For very short sentences (≤ 3 tokens), all content words are
    treated as rheme.
    """
    tokens = _tokenize(sentence)
    content = _content_words(tokens)
    if len(tokens) <= 3:
        return content
    mid = max(1, len(content) // 2)
    return content[mid:]


def _stem(word: str) -> str:
    """Naïve stemmer: strip common English suffixes."""
    w = word.lower()
    for suffix in ("tion", "sion", "ment", "ness", "able", "ible",
                   "ing", "ity", "ous", "ive", "ful", "less", "ent",
                   "ant", "ism", "ist", "ed", "ly", "er", "es", "s"):
        if len(w) > len(suffix) + 2 and w.endswith(suffix):
            return w[:-len(suffix)]
    return w


def _stem_set(words: list[str]) -> set[str]:
    """Return set of stems for a word list."""
    return {_stem(w) for w in words}


def _has_linear(prev_rheme_stems: set[str], curr_theme_stems: set[str]) -> bool:
    """True if the current theme picks up a previous rheme stem."""
    return bool(prev_rheme_stems & curr_theme_stems)


def _has_constant(prev_theme_stems: set[str], curr_theme_stems: set[str]) -> bool:
    """True if the same theme stem persists."""
    return bool(prev_theme_stems & curr_theme_stems)


def _has_derived(
    all_prior_rheme_stems: set[str],
    curr_theme_stems: set[str],
    prev_theme_stems: set[str],
) -> bool:
    """True if current theme is a morphological variant of an earlier rheme.

    'Derived' means a stem from a prior rheme reappears as a theme,
    but not in the immediately preceding theme (which would be
    constant).  This captures sub-theme development.
    """
    overlap = all_prior_rheme_stems & curr_theme_stems
    # Exclude if it's just constant (present in prev theme too).
    return bool(overlap - prev_theme_stems)


def _has_split(
    prev_rheme_stems: set[str],
    curr_theme_stems: set[str],
    next_theme_stems: set[str],
) -> bool:
    """True if prev rheme splits into multiple subsequent themes.

    At least 2 distinct stems from prev rheme must appear in the
    combined themes of the next two sentences.
    """
    combined = curr_theme_stems | next_theme_stems
    hits = prev_rheme_stems & combined
    return len(hits) >= 2


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def compute_thematic_progression(texts: list[str]) -> dict[str, Any]:
    """Analyse thematic progression across a list of text strings.

    Parameters
    ----------
    texts : list[str]
        Each element is one stroke / paragraph / document.

    Returns
    -------
    dict with all metrics described in the module docstring.
    """
    # Flatten all texts into a single sentence list.
    all_sentences: list[str] = []
    for t in texts:
        all_sentences.extend(_split_sentences(t))

    total = len(all_sentences)
    if total < 2:
        return _empty_result() if total == 0 else _no_progression_result(total)

    # Pre-compute theme and rheme stems for each sentence.
    themes: list[set[str]] = []
    rhemes: list[set[str]] = []
    for s in all_sentences:
        themes.append(_stem_set(_theme_words(s)))
        rhemes.append(_stem_set(_rheme_words(s)))

    # Count pattern hits across adjacent pairs.
    linear_hits = 0
    constant_hits = 0
    derived_hits = 0
    split_hits = 0
    total_pairs = total - 1

    # For theme persistence: track how long each theme stem survives.
    persistence_runs: list[int] = []
    current_run = 1
    current_stem_set = themes[0]

    # For rheme novelty: track cumulative seen stems.
    seen_stems: set[str] = set()
    novelty_scores: list[float] = []

    for idx in range(total):
        # Rheme novelty.
        r_stems = rhemes[idx]
        if r_stems:
            new_stems = r_stems - seen_stems
            novelty_scores.append(len(new_stems) / len(r_stems))
        seen_stems |= r_stems
        seen_stems |= themes[idx]

    for idx in range(total_pairs):
        prev_t = themes[idx]
        prev_r = rhemes[idx]
        curr_t = themes[idx + 1]

        # Constant theme.
        if _has_constant(prev_t, curr_t):
            constant_hits += 1

        # Linear progression (rheme → theme).
        if _has_linear(prev_r, curr_t):
            linear_hits += 1

        # Derived theme: stem from any earlier rheme, but not in prev theme.
        all_prior_rhemes: set[str] = set()
        for j in range(idx):
            all_prior_rhemes |= rhemes[j]
        if _has_derived(all_prior_rhemes, curr_t, prev_t):
            derived_hits += 1

        # Split rheme (look ahead).
        if idx + 2 < total:
            next_t = themes[idx + 2]
            if _has_split(prev_r, curr_t, next_t):
                split_hits += 1

        # Theme persistence tracking.
        overlap = prev_t & curr_t
        if overlap:
            current_run += 1
        else:
            if current_run >= 2:
                persistence_runs.append(current_run)
            current_run = 1
            current_stem_set = curr_t

    # Finalise persistence.
    if current_run >= 2:
        persistence_runs.append(current_run)

    # Compute ratios.
    linear_ratio = linear_hits / total_pairs if total_pairs else 0.0
    constant_ratio = constant_hits / total_pairs if total_pairs else 0.0
    derived_ratio = derived_hits / total_pairs if total_pairs else 0.0
    split_ratio = split_hits / total_pairs if total_pairs else 0.0

    # Theme persistence: mean run length (≥ 2 runs).
    theme_persistence = (
        round(sum(persistence_runs) / len(persistence_runs), 2)
        if persistence_runs else 0.0
    )

    # Rheme novelty.
    rheme_novelty = (
        round(sum(novelty_scores) / len(novelty_scores), 4)
        if novelty_scores else 0.0
    )

    # Progression index: weighted composite in [0, 1].
    #   linear_ratio   (0.20) — step-by-step development
    #   constant_ratio (0.15) — focus maintenance
    #   derived_ratio  (0.15) — sub-theme development
    #   split_ratio    (0.10) — branching
    #   persistence    (0.20) — theme survival, normalised to max 8
    #   novelty        (0.20) — fresh information injection
    persistence_norm = min(theme_persistence / 8.0, 1.0)

    progression_index = (
        0.20 * linear_ratio
        + 0.15 * constant_ratio
        + 0.15 * derived_ratio
        + 0.10 * split_ratio
        + 0.20 * persistence_norm
        + 0.20 * rheme_novelty
    )
    progression_index = round(max(0.0, min(1.0, progression_index)), 4)

    progression_label = _classify(
        progression_index,
        linear_ratio,
        constant_ratio,
        derived_ratio,
        split_ratio,
        theme_persistence,
        rheme_novelty,
        total,
    )

    return {
        "total_sentences": total,
        "linear_ratio": round(linear_ratio, 4),
        "constant_ratio": round(constant_ratio, 4),
        "derived_ratio": round(derived_ratio, 4),
        "split_ratio": round(split_ratio, 4),
        "theme_persistence": theme_persistence,
        "rheme_novelty": round(rheme_novelty, 4),
        "progression_index": progression_index,
        "progression_label": progression_label,
    }


def _empty_result() -> dict[str, Any]:
    """Return a zeroed-out result when there is no text to analyse."""
    return {
        "total_sentences": 0,
        "linear_ratio": 0.0,
        "constant_ratio": 0.0,
        "derived_ratio": 0.0,
        "split_ratio": 0.0,
        "theme_persistence": 0.0,
        "rheme_novelty": 0.0,
        "progression_index": 0.0,
        "progression_label": "stagnant",
    }


def _no_progression_result(total_sentences: int) -> dict[str, Any]:
    """Return result when sentences exist but pairs are too few."""
    return {
        "total_sentences": total_sentences,
        "linear_ratio": 0.0,
        "constant_ratio": 0.0,
        "derived_ratio": 0.0,
        "split_ratio": 0.0,
        "theme_persistence": 0.0,
        "rheme_novelty": 0.0,
        "progression_index": 0.0,
        "progression_label": "stagnant",
    }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _classify(
    progression_index: float,
    linear_ratio: float,
    constant_ratio: float,
    derived_ratio: float,
    split_ratio: float,
    persistence: float,
    novelty: float,
    total_sentences: int,
) -> str:
    """Classify the text's thematic progression profile."""
    # Stagnant: near-zero everything.
    if progression_index < 0.10:
        return "stagnant"

    # Scattered: low ratios across all patterns.
    if (linear_ratio < 0.15 and constant_ratio < 0.15
            and derived_ratio < 0.10 and persistence < 2.5):
        return "scattered"

    # Linear-drift: mostly linear, low persistence.
    if linear_ratio >= 0.30 and persistence < 3.0:
        return "linear-drift"

    # Focused: predominantly constant theme.
    if constant_ratio >= 0.35 and persistence >= 3.0:
        return "focused"

    # Orchestrated: high composite with diverse patterns.
    if progression_index >= 0.55 and (derived_ratio + split_ratio) >= 0.15:
        return "orchestrated"

    # Developing: moderate progression.
    if 0.30 <= progression_index < 0.55:
        return "developing"

    # Default fallback.
    return "developing"


# ---------------------------------------------------------------------------
# Summary & report
# ---------------------------------------------------------------------------

def _summary(result: dict[str, Any]) -> str:
    """One-line human-readable summary."""
    label = result["progression_label"]
    pi = result["progression_index"]
    lr = result["linear_ratio"]
    cr = result["constant_ratio"]
    tp = result["theme_persistence"]
    return (
        f"thematic progression: {label} (index={pi:.2f}, "
        f"linear={lr:.0%}, constant={cr:.0%}, persistence={tp:.1f})"
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
        description="Analyse thematic progression in recent writer strokes."
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
    result = compute_thematic_progression(strokes)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(_summary(result))
        print(f"  total sentences:  {result['total_sentences']}")
        print(f"  linear ratio:     {result['linear_ratio']:.1%}")
        print(f"  constant ratio:   {result['constant_ratio']:.1%}")
        print(f"  derived ratio:    {result['derived_ratio']:.1%}")
        print(f"  split ratio:      {result['split_ratio']:.1%}")
        print(f"  persistence:      {result['theme_persistence']:.1f}")
        print(f"  rheme novelty:    {result['rheme_novelty']:.2f}")
        print(f"  progression:      {result['progression_index']:.4f}")


if __name__ == "__main__":
    main()
