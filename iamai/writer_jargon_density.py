#!/usr/bin/env python3
"""writer_jargon_density — measure domain-specific jargon and buzzword usage.

Every field develops its own shorthand.  Engineers say "refactor the
pipeline" instead of "restructure the data-processing sequence."
Marketers say "leverage synergies" instead of "work together better."
Doctors say "idiopathic" instead of "we don't know why."

Jargon is not inherently bad.  Among specialists, it compresses
complex ideas into efficient tokens — "idempotent" conveys more than
"produces the same result when called multiple times" in a single
word.  But jargon becomes a barrier when the audience does not share
the vocabulary, or when it substitutes for clear thinking.

**Three categories of jargon:**

1. **Technical jargon** — field-specific terms that are precise among
   experts but opaque to outsiders: "polymorphism", "amortization",
   "pharmacokinetics", "stochastic gradient descent."

2. **Corporate buzzwords** — vague, aspirational language that sounds
   productive but says little: "leverage", "synergize", "circle back",
   "move the needle", "low-hanging fruit", "pivot", "disrupt."

3. **Academic jargon** — unnecessarily complex alternatives to plain
   words: "utilize" (use), "facilitate" (help), "methodology" (method),
   "paradigm" (model), "discourse" (discussion).

**When jargon is appropriate:**

- Writing for domain experts who share the vocabulary.
- Technical specifications where precision matters.
- Documentation that will be referenced, not read once.

**When jargon is a problem:**

- Writing for a general or mixed audience.
- Blog posts, tutorials for beginners, public communications.
- When a simpler word conveys the same meaning.

**Jargon density scale:**

| rate (per 100 words) | label           | description                      |
|----------------------|-----------------|----------------------------------|
| < 1.0                | plain           | accessible to general readers    |
| 1.0 – 3.0            | light_jargon    | occasional specialist terms      |
| 3.0 – 6.0            | moderate_jargon | domain-appropriate for experts   |
| 6.0 – 10.0           | heavy_jargon    | dense, may exclude non-specialists|
| > 10.0               | impenetrable    | wall of jargon, very exclusive   |

**Buzzword ratio** is tracked separately: the fraction of jargon hits
that are corporate buzzwords rather than legitimate technical terms.
A text can have high jargon density (technical blog) with low buzzword
ratio, or low jargon density with high buzzword ratio (executive memo
full of "synergies" and "leverage").

**Explanation ratio** measures how often jargon is accompanied by
definitions or context clues within a nearby window.  "The idempotent
operation — one that produces the same result each time — simplifies
retry logic" has explanation ratio 1.0 for that term.  "The
idempotent operation simplifies retry logic" has ratio 0.0.

This metric is orthogonal to formality (register level), verbosity
(word count), hedging (confidence language), sentiment (emotional
valence), and readability (sentence complexity).  A text can be
informal yet jargon-heavy (developer chat), or formal yet plain
(well-written legal summary for laypeople).

written by Qwen during manual caretaker visit 666, 2026-11-17
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Set, Optional
from collections import Counter


# ── jargon lexicons ──────────────────────────────────────────────
# Three tiers, each mapping word/phrase → category weight.
# Weight reflects how opaque the term is to a general reader:
#   1 = mildly specialized, 2 = clearly specialized, 3 = very opaque

_TECHNICAL_JARGON: Dict[str, int] = {
    # software engineering
    "polymorphism": 3, "idempotent": 2, "heuristic": 2, "stochastic": 3,
    "deterministic": 2, "asymptotic": 3, "recursive": 2, "orthogonal": 2,
    "isomorphic": 3, "homomorphic": 3, "idempotency": 3,
    "refactor": 1, "middleware": 2, "serialization": 2, "deserialization": 2,
    "memoization": 3, "memoize": 3, "transpile": 2, "transpilation": 2,
    "monad": 3, "functor": 3, "monoid": 3, "applicative": 3,
    "covariance": 3, "contravariance": 3, "bifunctor": 3,
    "microservice": 2, "orchestration": 2, "containerization": 2,
    "kubernetes": 2, "docker": 1, "kafka": 2, "grpc": 2,
    "eventual consistency": 3, "strong consistency": 3,
    "sharding": 2, "partitioning": 2, "replication": 2,
    "backpressure": 3, "circuit breaker": 2, "bulkhead": 2,
    # data science / ML
    "gradient descent": 2, "backpropagation": 3, "regularization": 2,
    "overfitting": 2, "underfitting": 2, "hyperparameter": 2,
    "epoch": 2, "batch size": 2, "learning rate": 2,
    "feature engineering": 2, "dimensionality reduction": 3,
    "convolutional": 3, "recurrent neural": 3, "transformer": 1,
    "attention mechanism": 2, "embedding": 2, "tokenizer": 2,
    "fine-tuning": 1, "inference": 2, "quantization": 2,
    # mathematics
    "eigenvalue": 3, "eigenvector": 3, "manifold": 3,
    "bijection": 3, "surjection": 3, "injection": 2,
    "topology": 3, "homeomorphism": 3, "diffeomorphism": 3,
    "isomorphism": 3, "automorphism": 3,
    # finance
    "amortization": 2, "securitization": 3, "derivatives": 2,
    "counterparty": 2, "leverage": 2, "liquidity": 2,
    "arbitrage": 2, "hedging": 2, "collateralization": 3,
    # medicine / biology
    "pharmacokinetics": 3, "pharmacodynamics": 3,
    "pathogenesis": 3, "etiology": 3, "prognosis": 2,
    "prophylactic": 3, "contraindication": 3,
    "bioavailability": 3, "metabolite": 2, "cytokine": 3,
    # general technical
    "taxonomy": 2, "ontology": 3, "schema": 2,
    "heuristic": 2, "empirical": 1, "theoretical": 1,
    "canonical": 2, "deterministic": 2, "probabilistic": 2,
    "stochastic": 3, "ergodic": 3, "markov": 3,
}

_CORPORATE_BUZZWORDS: Dict[str, int] = {
    # verbs
    "leverage": 2, "synergize": 3, "operationalize": 3, "monetize": 2,
    "incentivize": 2, "optimize": 1, "streamline": 2, "disrupt": 2,
    "pivot": 2, "iterate": 1, "scale": 1, "onboard": 1,
    "offboard": 1, "upskill": 2, "reskill": 2, "empower": 1,
    "enable": 1, "sunset": 2, "socialize": 2, "ideate": 3,
    # phrases
    "circle back": 2, "move the needle": 3, "low-hanging fruit": 3,
    "think outside the box": 3, "paradigm shift": 3,
    "deep dive": 2, "double click": 3, "boil the ocean": 3,
    "peel the onion": 3, "net net": 3, "at the end of the day": 2,
    "going forward": 1, "best practice": 2, "value add": 2,
    "action item": 2, "deliverable": 2, "bandwidth": 2,
    "take offline": 2, "touch base": 2, "ping me": 2,
    "reach out": 1, "circle up": 3, "runway": 2,
    "north star": 2, "flywheel": 2, "growth hacking": 3,
    "10x": 2, "moonshot": 2, "unicorn": 2,
    # nouns
    "synergy": 3, "alignment": 1, "stakeholder": 2,
    "ecosystem": 2, "vertical": 2, "horizontal": 1,
    "bleeding edge": 2, "state of the art": 2, "best of breed": 3,
    "thought leader": 3, "guru": 2, "ninja": 2, "rockstar": 2,
    # adjectives
    "agile": 1, "holistic": 2, "robust": 1, "scalable": 1,
    "seamless": 2, "frictionless": 2, "end-to-end": 1,
    "turnkey": 2, "plug-and-play": 2, "mission-critical": 2,
    "game-changing": 3, "next-generation": 2, "cutting-edge": 2,
    "world-class": 2, "industry-leading": 2, "best-in-class": 2,
}

_ACADEMIC_JARGON: Dict[str, int] = {
    # unnecessarily complex alternatives
    "utilize": 1, "utilise": 1, "facilitate": 1, "methodology": 2,
    "paradigm": 2, "discourse": 2, "praxis": 3, "praxis": 3,
    "juxtaposition": 2, "dichotomy": 2, "juxtapose": 2,
    "substantiate": 2, "corroborate": 2, "extrapolate": 2,
    "elucidate": 2, "delineate": 2, "explicate": 2,
    "problematic": 1, "problematize": 3, "problematise": 3,
    "contextualize": 2, "contextualise": 2, "operationalize": 3,
    "operationalise": 3, "theorize": 2, "theorise": 2,
    "reify": 3, "reification": 3, "signifier": 3, "signified": 3,
    "hermeneutic": 3, "hermeneutics": 3, "epistemological": 3,
    "epistemology": 3, "ontological": 3, "phenomenological": 3,
    "phenomenology": 3, "teleological": 3, "teleology": 3,
    "normative": 2, "positive": 1, "descriptive": 1,
    "prescriptive": 2, "proscriptive": 2,
    "interrogate": 2, "problematize": 3,
    "deconstruct": 2, "deconstruction": 3,
    "discursive": 3, "hegemony": 3, "hegemonic": 3,
    "liminal": 3, "liminality": 3, "intersectionality": 3,
    "positionality": 3, "reflexivity": 3,
    # Latin/Greek phrases used as jargon
    "a priori": 2, "a posteriori": 2, "in vitro": 2,
    "in vivo": 2, "in silico": 3, "ad hoc": 1,
    "per se": 1, "ipso facto": 3, "mutatis mutandis": 3,
    "ceteris paribus": 3, "sui generis": 3,
}

# Combine all lexicons with category tags
_ALL_JARGON: Dict[str, Tuple[str, int]] = {}
for _word, _weight in _TECHNICAL_JARGON.items():
    _ALL_JARGON[_word] = ("technical", _weight)
for _word, _weight in _CORPORATE_BUZZWORDS.items():
    _ALL_JARGON[_word] = ("buzzword", _weight)
for _word, _weight in _ACADEMIC_JARGON.items():
    _ALL_JARGON[_word] = ("academic", _weight)


# ── explanation patterns ─────────────────────────────────────────
# These patterns detect when a jargon term is being explained nearby.

_EXPLANATION_PATTERNS = [
    re.compile(r",?\s*(?:which|that|meaning|i\.e\.|e\.g\.)\s+", re.IGNORECASE),
    re.compile(r"\s*[-–—]\s+(?:that is|in other words|meaning)"),
    re.compile(r"\s*\(\s*(?:that is|in other words|i\.e\.)", re.IGNORECASE),
    re.compile(r",?\s*(?:in other words|that is to say|put simply|simply put)\s*,?"),
    re.compile(r"\s*:\s*(?:a|an|the)\s+\w+\s+(?:that|which|is|are)\s+"),
]


@dataclass
class JargonHit:
    """A single jargon term found in text."""
    term: str
    category: str  # "technical", "buzzword", "academic"
    weight: int    # 1-3 opacity weight
    position: int  # character offset in text
    explained: bool = False  # True if explanation detected nearby


@dataclass
class JargonDensityResult:
    """Complete jargon density analysis of a text."""
    total_jargon: int = 0
    technical_count: int = 0
    buzzword_count: int = 0
    academic_count: int = 0
    jargon_words: List[str] = field(default_factory=list)
    jargon_hits: List[JargonHit] = field(default_factory=list)
    jargon_rate: float = 0.0          # jargon terms per 100 words
    weighted_jargon_rate: float = 0.0  # weight-adjusted rate per 100 words
    buzzword_ratio: float = 0.0       # fraction of hits that are buzzwords
    explanation_ratio: float = 0.0    # fraction of hits with nearby explanation
    top_jargon: List[Tuple[str, int]] = field(default_factory=list)
    classification: str = "unknown"
    word_count: int = 0
    sentence_count: int = 0


def _tokenize(text: str) -> List[str]:
    """Split text into lowercase word tokens."""
    return re.findall(r"[a-z']+", text.lower())


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences on terminal punctuation."""
    parts = re.split(r'[.!?]+', text)
    return [s.strip() for s in parts if s.strip()]


def _find_jargon(text: str) -> List[JargonHit]:
    """Find all jargon terms in text, checking both single words and phrases."""
    hits: List[JargonHit] = []
    lower = text.lower()

    # Check multi-word phrases first (to avoid double-counting)
    matched_spans: List[Tuple[int, int]] = []
    for term, (category, weight) in _ALL_JARGON.items():
        if " " not in term and "-" not in term:
            continue
        for m in re.finditer(re.escape(term), lower):
            start, end = m.start(), m.end()
            # Ensure word boundaries
            if start > 0 and lower[start - 1].isalpha():
                continue
            if end < len(lower) and lower[end].isalpha():
                continue
            hits.append(JargonHit(
                term=term,
                category=category,
                weight=weight,
                position=start,
            ))
            matched_spans.append((start, end))

    # Check single words
    for m in re.finditer(r"[a-z]+", lower):
        word = m.group()
        start, end = m.start(), m.end()
        # Skip if inside a multi-word match
        if any(s <= start and end <= e for s, e in matched_spans):
            continue
        if word in _ALL_JARGON:
            category, weight = _ALL_JARGON[word]
            # Skip single-word entries that are also part of a matched phrase
            hits.append(JargonHit(
                term=word,
                category=category,
                weight=weight,
                position=start,
            ))

    return sorted(hits, key=lambda h: h.position)


def _check_explained(text: str, hit: JargonHit, window: int = 80) -> bool:
    """Check if a jargon term has an explanation within a nearby window."""
    start = max(0, hit.position)
    end = min(len(text), hit.position + len(hit.term) + window)
    context = text[start:end]

    for pattern in _EXPLANATION_PATTERNS:
        if pattern.search(context):
            return True
    return False


def _classify(rate: float, word_count: int) -> str:
    """Classify jargon density level."""
    if word_count < 10:
        return "unknown"
    if rate < 1.0:
        return "plain"
    elif rate < 3.0:
        return "light_jargon"
    elif rate < 6.0:
        return "moderate_jargon"
    elif rate < 10.0:
        return "heavy_jargon"
    else:
        return "impenetrable"


def measure_jargon_density(text: str) -> JargonDensityResult:
    """Measure jargon density in a text.

    Returns a JargonDensityResult with counts, rates, classification,
    and per-term details.
    """
    if not text or not text.strip():
        return JargonDensityResult()

    tokens = _tokenize(text)
    word_count = len(tokens)
    sentences = _split_sentences(text)
    sentence_count = len(sentences)

    if word_count == 0:
        return JargonDensityResult()

    # Find all jargon hits
    hits = _find_jargon(text)

    # Check explanations
    for hit in hits:
        hit.explained = _check_explained(text, hit)

    # Count by category
    technical = sum(1 for h in hits if h.category == "technical")
    buzzword = sum(1 for h in hits if h.category == "buzzword")
    academic = sum(1 for h in hits if h.category == "academic")
    total = len(hits)

    # Rates
    jargon_rate = round((total / word_count) * 100, 2)
    weighted_sum = sum(h.weight for h in hits)
    weighted_jargon_rate = round((weighted_sum / word_count) * 100, 2)

    # Buzzword ratio
    buzzword_ratio = round(buzzword / total, 3) if total > 0 else 0.0

    # Explanation ratio
    explained_count = sum(1 for h in hits if h.explained)
    explanation_ratio = round(explained_count / total, 3) if total > 0 else 0.0

    # Top jargon terms (by frequency)
    term_counter = Counter(h.term for h in hits)
    top_jargon = term_counter.most_common(10)

    # Classification
    classification = _classify(jargon_rate, word_count)

    # Distinct terms list
    jargon_words = list(dict.fromkeys(h.term for h in hits))

    return JargonDensityResult(
        total_jargon=total,
        technical_count=technical,
        buzzword_count=buzzword,
        academic_count=academic,
        jargon_words=jargon_words,
        jargon_hits=hits,
        jargon_rate=jargon_rate,
        weighted_jargon_rate=weighted_jargon_rate,
        buzzword_ratio=buzzword_ratio,
        explanation_ratio=explanation_ratio,
        top_jargon=top_jargon,
        classification=classification,
        word_count=word_count,
        sentence_count=sentence_count,
    )
