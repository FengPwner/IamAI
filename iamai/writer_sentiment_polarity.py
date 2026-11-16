#!/usr/bin/env python3
"""writer_sentiment_polarity — measure emotional valence of prose.

Every sentence carries an emotional charge.  "The deployment
succeeded" feels different from "the deployment failed."  "She
laughed" reads differently from "she wept."  Sentiment polarity
captures this: the net emotional direction of a text, computed
from the density and intensity of positive and negative words.

Sentiment analysis in NLP usually means machine-learning classifiers
trained on movie reviews or tweets.  This module takes a simpler,
transparent approach: a curated lexicon of positive and negative
words, weighted by intensity, applied token-by-token.  No black
box.  Every score can be traced back to the words that produced it.

**Why this matters for a writer:**

- A technical blog that reads as uniformly negative may alienate
  readers; one that is uniformly positive may feel dishonest.
- A personal essay that never dips below neutral probably avoids
  the hard parts.
- A status update that oscillates wildly between positive and
  negative may signal instability or emotional rawness.

**Polarity scale**:

| score range     | label              | description                      |
|-----------------|--------------------|----------------------------------|
| > +0.4          | strongly_positive  | unmistakably upbeat              |
| +0.15 to +0.4   | mildly_positive    | warm, optimistic, constructive   |
| -0.15 to +0.15  | neutral            | balanced, factual, restrained    |
| -0.4 to -0.15   | mildly_negative    | critical, cautious, dissatisfied |
| < -0.4          | strongly_negative  | bleak, angry, despairing         |

**Intensity** matters as much as direction.  "Good" and "excellent"
are both positive; "bad" and "catastrophic" are both negative.  The
lexicon assigns intensity weights (1–3) so that strong words pull
the score further than mild ones.

**Negation handling**: "not good" should not score as positive.
When a negation word (not, never, no, neither, nor, nothing,
nowhere, nobody, n't) appears within two tokens before a sentiment
word, its polarity is inverted.  "Not excellent" becomes mildly
negative rather than strongly positive.

**Sentiment shift detection**: A text that starts positive and
ends negative has a different character from one that is uniformly
neutral — even if the net polarity is the same.  This module
detects whether the text's sentiment is stable, rising, falling,
or oscillating.

This metric is orthogonal to passive voice (grammatical agency),
hedging (confidence language), formality (register), verbosity
(word count), and readability (sentence complexity).  A cheerful
text can be passive-dominant; a bleak text can be active and
direct.

written by Qwen during manual caretaker visit 665, 2026-11-17
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from collections import Counter


# ── sentiment lexicon ──────────────────────────────────────────
# Each word maps to (polarity, intensity) where:
#   polarity: +1 (positive) or -1 (negative)
#   intensity: 1 (mild), 2 (moderate), 3 (strong)

_POSITIVE_LEXICON: Dict[str, Tuple[int, int]] = {
    # intensity 1 — mild positive
    "okay": (1, 1), "ok": (1, 1), "fine": (1, 1), "decent": (1, 1),
    "nice": (1, 1), "pleasant": (1, 1), "adequate": (1, 1), "fair": (1, 1),
    "calm": (1, 1), "steady": (1, 1), "safe": (1, 1), "clean": (1, 1),
    "easy": (1, 1), "simple": (1, 1), "helpful": (1, 1), "useful": (1, 1),
    "glad": (1, 1), "keen": (1, 1), "warm": (1, 1), "kind": (1, 1),
    "hope": (1, 1), "trust": (1, 1), "agree": (1, 1), "accept": (1, 1),
    "support": (1, 1), "welcome": (1, 1), "comfort": (1, 1), "relief": (1, 1),
    "progress": (1, 1), "improve": (1, 1), "grow": (1, 1), "learn": (1, 1),
    "gain": (1, 1), "benefit": (1, 1), "achieve": (1, 1), "succeed": (1, 1),
    "enjoy": (1, 1), "appreciate": (1, 1), "like": (1, 1), "love": (1, 1),
    "smile": (1, 1), "laugh": (1, 1), "celebrate": (1, 1), "thank": (1, 1),
    "bright": (1, 1), "clear": (1, 1), "fresh": (1, 1), "open": (1, 1),
    "free": (1, 1), "alive": (1, 1), "strong": (1, 1), "healthy": (1, 1),

    # intensity 2 — moderate positive
    "good": (1, 2), "great": (1, 2), "happy": (1, 2), "joy": (1, 2),
    "pleased": (1, 2), "delighted": (1, 2), "satisfied": (1, 2),
    "impressive": (1, 2), "remarkable": (1, 2), "wonderful": (1, 2),
    "beautiful": (1, 2), "brilliant": (1, 2), "elegant": (1, 2),
    "grateful": (1, 2), "proud": (1, 2), "confident": (1, 2),
    "optimistic": (1, 2), "excited": (1, 2), "inspired": (1, 2),
    "triumph": (1, 2), "victory": (1, 2), "success": (1, 2),
    "breakthrough": (1, 2), "innovation": (1, 2), "excellence": (1, 2),
    "thrive": (1, 2), "flourish": (1, 2), "prosper": (1, 2),
    "heal": (1, 2), "recover": (1, 2), "restore": (1, 2),
    "delight": (1, 2), "bliss": (1, 2), "serene": (1, 2),
    "harmony": (1, 2), "peace": (1, 2), "courage": (1, 2),
    "wisdom": (1, 2), "generous": (1, 2), "compassion": (1, 2),
    "radiant": (1, 2), "vibrant": (1, 2), "robust": (1, 2),
    "efficient": (1, 2), "reliable": (1, 2), "resilient": (1, 2),

    # intensity 3 — strong positive
    "excellent": (1, 3), "outstanding": (1, 3), "extraordinary": (1, 3),
    "magnificent": (1, 3), "phenomenal": (1, 3), "spectacular": (1, 3),
    "sublime": (1, 3), "transcendent": (1, 3), "miraculous": (1, 3),
    "ecstatic": (1, 3), "euphoric": (1, 3), "elated": (1, 3),
    "glorious": (1, 3), "magnificent": (1, 3), "triumphant": (1, 3),
    "masterful": (1, 3), "perfect": (1, 3), "flawless": (1, 3),
    "awe": (1, 3), "wonder": (1, 3), "bliss": (1, 3),
}

_NEGATIVE_LEXICON: Dict[str, Tuple[int, int]] = {
    # intensity 1 — mild negative
    "bad": (-1, 1), "wrong": (-1, 1), "poor": (-1, 1), "weak": (-1, 1),
    "slow": (-1, 1), "hard": (-1, 1), "difficult": (-1, 1), "tough": (-1, 1),
    "boring": (-1, 1), "dull": (-1, 1), "tired": (-1, 1), "weary": (-1, 1),
    "sad": (-1, 1), "sorry": (-1, 1), "unhappy": (-1, 1), "upset": (-1, 1),
    "worry": (-1, 1), "concern": (-1, 1), "doubt": (-1, 1), "fear": (-1, 1),
    "risk": (-1, 1), "threat": (-1, 1), "danger": (-1, 1), "problem": (-1, 1),
    "issue": (-1, 1), "error": (-1, 1), "mistake": (-1, 1), "fault": (-1, 1),
    "fail": (-1, 1), "lose": (-1, 1), "miss": (-1, 1), "lack": (-1, 1),
    "hate": (-1, 1), "dislike": (-1, 1), "annoy": (-1, 1), "bother": (-1, 1),
    "hurt": (-1, 1), "pain": (-1, 1), "damage": (-1, 1), "harm": (-1, 1),
    "ugly": (-1, 1), "dirty": (-1, 1), "dark": (-1, 1), "cold": (-1, 1),
    "stuck": (-1, 1), "trapped": (-1, 1), "lost": (-1, 1), "broken": (-1, 1),

    # intensity 2 — moderate negative
    "terrible": (-1, 2), "awful": (-1, 2), "horrible": (-1, 2),
    "dreadful": (-1, 2), "miserable": (-1, 2), "wretched": (-1, 2),
    "angry": (-1, 2), "furious": (-1, 2), "enraged": (-1, 2),
    "disgusted": (-1, 2), "appalled": (-1, 2), "outraged": (-1, 2),
    "ashamed": (-1, 2), "guilty": (-1, 2), "embarrassed": (-1, 2),
    "anxious": (-1, 2), "nervous": (-1, 2), "stressed": (-1, 2),
    "overwhelmed": (-1, 2), "exhausted": (-1, 2), "burned": (-1, 2),
    "crash": (-1, 2), "collapse": (-1, 2), "destroy": (-1, 2),
    "ruin": (-1, 2), "disaster": (-1, 2), "catastrophe": (-1, 2),
    "crisis": (-1, 2), "emergency": (-1, 2), "plague": (-1, 2),
    "suffer": (-1, 2), "agony": (-1, 2), "torment": (-1, 2),
    "despair": (-1, 2), "hopeless": (-1, 2), "bleak": (-1, 2),
    "corrupt": (-1, 2), "toxic": (-1, 2), "poison": (-1, 2),
    "violent": (-1, 2), "cruel": (-1, 2), "brutal": (-1, 2),
    "bitter": (-1, 2), "hostile": (-1, 2), "vicious": (-1, 2),

    # intensity 3 — strong negative
    "atrocious": (-1, 3), "abysmal": (-1, 3), "horrific": (-1, 3),
    "devastating": (-1, 3), "annihilate": (-1, 3), "obliterate": (-1, 3),
    "apocalyptic": (-1, 3), "nightmarish": (-1, 3), "monstrous": (-1, 3),
    "unbearable": (-1, 3), "intolerable": (-1, 3), "unspeakable": (-1, 3),
    "horrifying": (-1, 3), "terrifying": (-1, 3), "petrifying": (-1, 3),
    "cataclysmic": (-1, 3), "calamitous": (-1, 3), "ruinous": (-1, 3),
}

# Merge into single lexicon
_LEXICON: Dict[str, Tuple[int, int]] = {}
_LEXICON.update(_POSITIVE_LEXICON)
_LEXICON.update(_NEGATIVE_LEXICON)


# ── negation words ─────────────────────────────────────────────

_NEGATION_WORDS = {
    "not", "no", "never", "neither", "nor", "nothing",
    "nowhere", "nobody", "none", "n't",
    "don't", "doesn't", "didn't", "won't", "wouldn't",
    "shouldn't", "couldn't", "can't", "cannot", "isn't",
    "aren't", "wasn't", "weren't", "hasn't", "haven't",
    "hadn't",
}


# ── data class ─────────────────────────────────────────────────


@dataclass
class SentimentPolarityResult:
    """Result of sentiment polarity analysis."""

    # raw counts
    positive_words: int = 0
    negative_words: int = 0
    neutral_words: int = 0
    total_sentiment_words: int = 0

    # weighted scores
    positive_score: float = 0.0
    negative_score: float = 0.0
    net_score: float = 0.0            # positive_score - negative_score (normalised)
    polarity: float = 0.0             # -1.0 to +1.0

    # rates
    sentiment_density: float = 0.0    # sentiment words per 100 words
    positive_ratio: float = 0.0       # fraction of sentiment words that are positive

    # per-sentence trajectory
    sentence_polarities: List[float] = field(default_factory=list)

    # top contributors
    top_positive: List[Tuple[str, int]] = field(default_factory=list)
    top_negative: List[Tuple[str, int]] = field(default_factory=list)

    # shift detection
    sentiment_shift: str = "stable"    # stable, rising, falling, oscillating

    # classification
    classification: str = "neutral"

    # metadata
    word_count: int = 0
    sentence_count: int = 0


# ── helpers ─────────────────────────────────────────────────────


def _tokenize(text: str) -> List[str]:
    """Split text into lowercased word tokens (letters/apostrophes only)."""
    return re.findall(r"[a-z']+", text.lower())


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences on . ! ? followed by space or end."""
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]


def _is_negated(tokens: List[str], idx: int, window: int = 2) -> bool:
    """Check whether the token at idx is preceded by a negation within window."""
    start = max(0, idx - window)
    for j in range(start, idx):
        if tokens[j] in _NEGATION_WORDS:
            return True
    return False


def _score_sentence(tokens: List[str]) -> Tuple[float, int, int, Counter, Counter]:
    """Score a single sentence's sentiment.

    Returns (net_score, pos_count, neg_count, pos_counter, neg_counter).
    """
    pos_count = 0
    neg_count = 0
    pos_weighted = 0.0
    neg_weighted = 0.0
    pos_counter: Counter = Counter()
    neg_counter: Counter = Counter()

    for i, tok in enumerate(tokens):
        if tok not in _LEXICON:
            continue

        polarity, intensity = _LEXICON[tok]
        negated = _is_negated(tokens, i)

        # Negation inverts polarity
        if negated:
            polarity = -polarity

        weighted_value = polarity * intensity

        if weighted_value > 0:
            pos_count += 1
            pos_weighted += abs(weighted_value)
            pos_counter[tok] += 1
        elif weighted_value < 0:
            neg_count += 1
            neg_weighted += abs(weighted_value)
            neg_counter[tok] += 1
        # weighted_value == 0 only if polarity == 0, which doesn't happen

    net = pos_weighted - neg_weighted
    return net, pos_count, neg_count, pos_counter, neg_counter


# ── shift detection ─────────────────────────────────────────────


def _detect_shift(sentence_polarities: List[float]) -> str:
    """Detect the sentiment trajectory across sentences.

    Returns one of: stable, rising, falling, oscillating.
    """
    if len(sentence_polarities) < 3:
        return "stable"

    # Divide into thirds
    n = len(sentence_polarities)
    third = max(1, n // 3)
    first_third = sentence_polarities[:third]
    last_third = sentence_polarities[-third:]

    avg_first = sum(first_third) / len(first_third)
    avg_last = sum(last_third) / len(last_third)

    delta = avg_last - avg_first

    # Check for oscillation: count sign changes
    sign_changes = 0
    for i in range(1, len(sentence_polarities)):
        if (sentence_polarities[i] > 0) != (sentence_polarities[i - 1] > 0):
            if sentence_polarities[i] != 0 and sentence_polarities[i - 1] != 0:
                sign_changes += 1

    oscillation_rate = sign_changes / max(1, len(sentence_polarities) - 1)

    if oscillation_rate > 0.5:
        return "oscillating"
    elif delta > 0.15:
        return "rising"
    elif delta < -0.15:
        return "falling"
    else:
        return "stable"


# ── main analysis ───────────────────────────────────────────────


def measure_sentiment_polarity(text: str) -> SentimentPolarityResult:
    """Analyse sentiment polarity of a text.

    Args:
        text: The prose to analyse.

    Returns:
        SentimentPolarityResult with scores, trajectory, and classification.
    """
    if not text or not text.strip():
        return SentimentPolarityResult(classification="unknown")

    sentences = _split_sentences(text)
    if not sentences:
        return SentimentPolarityResult(classification="unknown")

    all_tokens = _tokenize(text)
    word_count = len(all_tokens)
    if word_count == 0:
        return SentimentPolarityResult(classification="unknown")

    sentence_count = len(sentences)

    total_pos = 0
    total_neg = 0
    total_pos_weighted = 0.0
    total_neg_weighted = 0.0
    global_pos_counter: Counter = Counter()
    global_neg_counter: Counter = Counter()
    sentence_polarities: List[float] = []

    for sent in sentences:
        tokens = _tokenize(sent)
        net, pos_c, neg_c, pos_cnt, neg_cnt = _score_sentence(tokens)

        total_pos += pos_c
        total_neg += neg_c

        # Accumulate weighted scores
        for tok, count in pos_cnt.items():
            polarity, intensity = _LEXICON.get(tok, (0, 0))
            # Check if negated in context — but we already handled in _score_sentence
            # We need raw weights here
            global_pos_counter[tok] += count
            total_pos_weighted += intensity * count

        for tok, count in neg_cnt.items():
            polarity, intensity = _LEXICON.get(tok, (0, 0))
            global_neg_counter[tok] += count
            total_neg_weighted += intensity * count

        # Sentence polarity: normalise by sentence token count
        sent_tokens = len(tokens) if tokens else 1
        sentence_polarities.append(net / sent_tokens)

    total_sentiment = total_pos + total_neg

    # Normalised polarity: -1 to +1
    max_possible = total_sentiment * 3  # max intensity is 3
    if max_possible > 0:
        polarity = (total_pos_weighted - total_neg_weighted) / max_possible
    else:
        polarity = 0.0

    polarity = max(-1.0, min(1.0, polarity))

    # Net score (raw weighted difference, normalised by word count)
    net_score = (total_pos_weighted - total_neg_weighted) / word_count

    # Sentiment density: sentiment words per 100 words
    sentiment_density = (total_sentiment / word_count * 100) if word_count > 0 else 0.0

    # Positive ratio
    positive_ratio = (total_pos / total_sentiment) if total_sentiment > 0 else 0.5

    # Top contributors
    top_pos = global_pos_counter.most_common(5)
    top_neg = global_neg_counter.most_common(5)

    # Shift detection
    shift = _detect_shift(sentence_polarities)

    # Classification
    if polarity > 0.4:
        classification = "strongly_positive"
    elif polarity > 0.15:
        classification = "mildly_positive"
    elif polarity < -0.4:
        classification = "strongly_negative"
    elif polarity < -0.15:
        classification = "mildly_negative"
    else:
        classification = "neutral"

    return SentimentPolarityResult(
        positive_words=total_pos,
        negative_words=total_neg,
        neutral_words=word_count - total_sentiment,
        total_sentiment_words=total_sentiment,
        positive_score=round(total_pos_weighted, 2),
        negative_score=round(total_neg_weighted, 2),
        net_score=round(net_score, 4),
        polarity=round(polarity, 4),
        sentiment_density=round(sentiment_density, 2),
        positive_ratio=round(positive_ratio, 3),
        sentence_polarities=sentence_polarities,
        top_positive=top_pos,
        top_negative=top_neg,
        sentiment_shift=shift,
        classification=classification,
        word_count=word_count,
        sentence_count=sentence_count,
    )
