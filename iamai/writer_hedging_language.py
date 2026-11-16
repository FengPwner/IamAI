#!/usr/bin/env python3
"""writer_hedging_language — measure tentative vs. confident language in prose.

Hedging is the linguistic art of saying something without fully
committing to it.  "The server *might* be slow" hedges; "The server
*is* slow" asserts.  "This *perhaps* explains the crash" hedges;
"This *clearly* explains the crash" asserts.  Both hedges and
boosters (confident markers) shape how readers evaluate a claim.

Academic writing uses hedging as a precision tool: "These results
*suggest* a correlation" is more honest than "These results *prove*
a correlation" when the evidence is correlational.  But excessive
hedging — "It *might perhaps* *somewhat* *tend to* *suggest*..." —
reads as evasive or uncertain beyond what the evidence warrants.

Conversely, excessive boosting — "This *clearly* *obviously*
*definitely* proves..." — reads as overconfident or propagandistic.
Good prose matches its confidence language to its evidence strength.

This module detects hedging and boosting language through two
curated phrase sets:

**Hedges** (tentative language):
- modal hedges: might, may, could, would, should (epistemic use)
- adverbial hedges: perhaps, maybe, possibly, probably, likely,
  somewhat, slightly, rather, fairly, quite (as downtoner)
- verb hedges: seem, appear, tend, suggest, indicate (when used
  to soften rather than report)
- phrase hedges: sort of, kind of, in a way, to some extent,
  in some ways, it seems, it appears, one might argue,
  arguably, allegedly, supposedly

**Boosters** (confident language):
- adverbial boosters: clearly, obviously, definitely, certainly,
  undoubtedly, evidently, plainly, unquestionably, manifestly,
  patently, explicitly, precisely, exactly
- verb boosters: prove, demonstrate, establish, confirm, show
  (when used to assert)
- phrase boosters: without doubt, beyond question, it is clear,
  it is evident, no doubt, of course

For each set, the module computes:
- **count**: raw number of hedge/booster instances found
- **rate**: instances per 100 words
- **ratio**: fraction of confidence markers that are hedges
  (1.0 = all hedging, 0.0 = all boosting, 0.5 = balanced)
- **top_hedges** / **top_boosters**: the 5 most frequent markers
- **classification**: one of confident, measured, tentative,
  evasive, hedged_heavy, booster_heavy

The classification uses both absolute rate and hedge ratio:

| hedge_rate | booster_rate | classification  |
|------------|-------------|-----------------|
| < 0.5      | < 0.3       | direct          |
| < 1.5      | < 1.0       | measured        |
| 1.5–3.0    | < 1.0       | tentative       |
| > 3.0      | < 1.0       | evasive         |
| any        | >= 1.5      | booster_heavy   |
| > 3.0      | >= 1.5      | mixed_signals   |

This metric is orthogonal to verbosity (word count), formality
(register), and nominalization density.  A formal paper can be
direct; a casual blog post can be evasive.

written by Qwen during manual caretaker visit 660, 2026-11-16
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from collections import Counter


# ── word and phrase sets ────────────────────────────────────────

# Single-word hedges (case-insensitive matching)
_HEDGE_WORDS = {
    # modal hedges (epistemic use)
    "might", "may", "could", "would",
    # adverbial hedges
    "perhaps", "maybe", "possibly", "probably", "likely",
    "somewhat", "slightly", "rather", "fairly",
    "seemingly", "apparently",
    # epistemic adverbs
    "arguably", "allegedly", "supposedly", "reportedly",
    "presumably", "ostensibly",
}

# Multi-word hedge phrases (matched as regex patterns)
_HEDGE_PHRASES = [
    r"\bsort\s+of\b",
    r"\bkind\s+of\b",
    r"\bin\s+a\s+way\b",
    r"\bto\s+some\s+extent\b",
    r"\bin\s+some\s+ways?\b",
    r"\bit\s+seems?\b",
    r"\bit\s+appears?\b",
    r"\bone\s+might\s+(?:argue|say|think|suggest)\b",
    r"\bthere\s+is\s+(?:some|a\s+degree\s+of)\b",
    r"\btends?\s+to\b",
    r"\bseems?\s+to\b",
    r"\bappears?\s+to\b",
    r"\bmore\s+or\s+less\b",
    r"\bnot\s+(?:entirely|wholly|fully|completely)\b",
]

# Single-word boosters (case-insensitive)
_BOOSTER_WORDS = {
    "clearly", "obviously", "definitely", "certainly",
    "undoubtedly", "evidently", "plainly", "unquestionably",
    "manifestly", "patently", "explicitly", "precisely",
    "exactly", "absolutely", "surely", "indubitably",
    "unequivocally", "unambiguously",
}

# Multi-word booster phrases
_BOOSTER_PHRASES = [
    r"\bwithout\s+(?:a\s+)?doubt\b",
    r"\bbeyond\s+(?:a\s+)?(?:reasonable\s+)?(?:doubt|question)\b",
    r"\bit\s+is\s+clear\b",
    r"\bit\s+is\s+evident\b",
    r"\bit\s+is\s+obvious\b",
    r"\bit\s+is\s+certain\b",
    r"\bno\s+doubt\b",
    r"\bof\s+course\b",
    r"\bthere\s+is\s+no\s+(?:question|doubt)\b",
    r"\bwithout\s+question\b",
]

# Compiled regex for word splitting
_WORD_SPLIT = re.compile(r"[a-zA-Z']+")


# ── data structures ─────────────────────────────────────────────

@dataclass
class HedgingResult:
    """Aggregate results for hedging language analysis."""
    # Raw counts
    hedge_count: int = 0
    booster_count: int = 0
    total_words: int = 0

    # Rates per 100 words
    hedge_rate: float = 0.0
    booster_rate: float = 0.0

    # Hedge ratio (fraction of all confidence markers that are hedges)
    hedge_ratio: float = 0.0  # 1.0 = all hedging, 0.0 = all boosting

    # Frequency breakdowns
    hedge_word_counts: Dict[str, int] = field(default_factory=dict)
    hedge_phrase_counts: Dict[str, int] = field(default_factory=dict)
    booster_word_counts: Dict[str, int] = field(default_factory=dict)
    booster_phrase_counts: Dict[str, int] = field(default_factory=dict)

    # Top markers (up to 5 each)
    top_hedges: List[Tuple[str, int]] = field(default_factory=list)
    top_boosters: List[Tuple[str, int]] = field(default_factory=list)

    # Classification
    classification: str = "unknown"
    # direct | measured | tentative | evasive | booster_heavy | mixed_signals


# ── detection helpers ───────────────────────────────────────────

def _find_hedge_words(words: List[str]) -> Dict[str, int]:
    """Count single-word hedges in the word list."""
    counts: Dict[str, int] = {}
    for w in words:
        low = w.lower()
        if low in _HEDGE_WORDS:
            counts[low] = counts.get(low, 0) + 1
    return counts


def _find_booster_words(words: List[str]) -> Dict[str, int]:
    """Count single-word boosters in the word list."""
    counts: Dict[str, int] = {}
    for w in words:
        low = w.lower()
        if low in _BOOSTER_WORDS:
            counts[low] = counts.get(low, 0) + 1
    return counts


def _find_phrases(text: str, patterns: List[str]) -> Dict[str, int]:
    """Count multi-word phrase matches in the text."""
    lower_text = text.lower()
    counts: Dict[str, int] = {}
    for pat in patterns:
        matches = re.findall(pat, lower_text)
        if matches:
            # Use the pattern as key (cleaned for display)
            key = pat.replace(r"\b", "").replace(r"\s+", " ").replace("(?:", "").replace(")", "")
            counts[key] = len(matches)
    return counts


# ── main function ───────────────────────────────────────────────

def measure_hedging(text: str) -> HedgingResult:
    """Analyze hedging and boosting language in a text.

    Returns a HedgingResult with counts, rates, ratios,
    frequency breakdowns, and a classification.
    """
    result = HedgingResult()

    if not text or not text.strip():
        result.classification = "unknown"
        return result

    # Extract words and count
    words = _WORD_SPLIT.findall(text)
    result.total_words = len(words)

    if result.total_words == 0:
        result.classification = "unknown"
        return result

    # Detect hedges
    result.hedge_word_counts = _find_hedge_words(words)
    result.hedge_phrase_counts = _find_phrases(text, _HEDGE_PHRASES)

    # Detect boosters
    result.booster_word_counts = _find_booster_words(words)
    result.booster_phrase_counts = _find_phrases(text, _BOOSTER_PHRASES)

    # Compute totals
    result.hedge_count = (
        sum(result.hedge_word_counts.values())
        + sum(result.hedge_phrase_counts.values())
    )
    result.booster_count = (
        sum(result.booster_word_counts.values())
        + sum(result.booster_phrase_counts.values())
    )

    # Compute rates per 100 words
    per_100 = result.total_words / 100.0
    result.hedge_rate = round(result.hedge_count / per_100, 4)
    result.booster_rate = round(result.booster_count / per_100, 4)

    # Compute hedge ratio
    total_markers = result.hedge_count + result.booster_count
    if total_markers > 0:
        result.hedge_ratio = round(result.hedge_count / total_markers, 4)
    else:
        result.hedge_ratio = 0.5  # neutral when no markers at all

    # Top hedges and boosters (up to 5)
    all_hedges = Counter(result.hedge_word_counts) + Counter(result.hedge_phrase_counts)
    all_boosters = Counter(result.booster_word_counts) + Counter(result.booster_phrase_counts)
    result.top_hedges = all_hedges.most_common(5)
    result.top_boosters = all_boosters.most_common(5)

    # Classification based on rates
    hr = result.hedge_rate
    br = result.booster_rate

    if hr > 3.0 and br >= 1.5:
        result.classification = "mixed_signals"
    elif br >= 1.5:
        result.classification = "booster_heavy"
    elif hr > 3.0:
        result.classification = "evasive"
    elif hr >= 1.5:
        result.classification = "tentative"
    elif hr < 0.5 and br < 0.3:
        result.classification = "direct"
    else:
        result.classification = "measured"

    return result
