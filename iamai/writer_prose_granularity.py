#!/usr/bin/env python3
"""writer_prose_granularity — measure the detail resolution of prose.

Prose granularity is the level of detail at which a text operates.
Fine-grained prose names specific people, exact numbers, particular
dates, concrete measurements, and individual instances.  Coarse-grained
prose speaks in generalities, abstractions, categories, and summaries.
Neither is inherently better — a lab notebook *should* be fine-grained;
a mission statement *should* be coarse-grained — but mismatched
granularity is a common failure mode: a technical document that says
"the process takes a while" when it should say "the build takes
47 seconds on an M2 MacBook Air," or a casual blog post that buries
its reader in decimal-point precision.

Granularity manifests through five measurable channels.

**Proper noun density** captures how often the text names specific
entities — people, places, organizations, products, technologies.
"Maria Rodriguez presented the Q3 results to the Apache Software
Foundation board in Portland, Oregon" is dense with proper nouns;
"someone presented some results to a group somewhere" has none.
Each proper noun pins the text to a particular real-world referent
rather than a general category.

**Numerical precision** measures how exact the numbers in the text
are.  "The temperature rose by 2.7 degrees Celsius over 48 hours"
is precise; "the temperature went up a bit over a couple of days"
is vague.  Precision is not just about decimal places — "47 seconds"
is more granular than "less than a minute" even without decimals.
The channel counts exact numbers, measurements with units, dates,
timestamps, and version numbers.

**Concrete noun ratio** distinguishes nouns that name tangible,
perceptible things from those that name abstractions.  "The server
rack," "the keyboard," "the coffee mug" are concrete — you can see
or touch them.  "Infrastructure," "communication," "methodology"
are abstract — they name categories, processes, or concepts.  A text
where most nouns are concrete reads as grounded and physical; one
where most nouns are abstract reads as conceptual and theoretical.

**Generalization markers** are words and phrases that signal the
writer is operating at a summary or category level rather than a
specific-instance level: *generally, typically, usually, often,
most, many, some, various, several, in general, as a rule, on the
whole, broadly speaking, for the most part, tends to, more often
than not, by and large*.  They lift the discourse from the particular
to the general — "Servers generally consume more power during peak
hours" versus "Server rack 7A drew 4.2 kW at 2:15 PM on Tuesday."

**Instance markers** are the inverse of generalization — they signal
that the writer is giving a specific example or case: *for example,
for instance, specifically, in particular, such as, like, namely,
to illustrate, as a case in point, consider, take the case of,
one example is, a specific case*.  They descend from the general
to the particular — "Large language models (for example, GPT-4,
Claude 3.5, and Llama 3.1) each handle context differently."

A text with high granularity reads as precise, detailed, and
grounded in specifics — you know exactly who, what, when, where,
and how much.  A text with low granularity reads as abstract,
general, and conceptual — you understand the category but not the
instance.  Granularity is orthogonal to verbosity (word count),
formality (register), causal density (cause-effect reasoning),
cognitive load (working memory burden), and hedging (uncertainty
expression).  A short sentence can be highly granular ("The 3.2mm
drill bit snapped at 14,700 RPM."); a long paragraph can be
completely abstract ("The fundamental paradigm underlying modern
computational approaches to complex systems involves iterative
refinement of approximate solutions.").

This module measures prose granularity as a composite index
(0.0 – 1.0) across five independent channels.

written by Qwen during manual caretaker visit 656, 2026-11-16
"""

import re
from dataclasses import dataclass
from typing import List


# ── regex primitives ────────────────────────────────────────────

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_SPLIT = re.compile(r"[a-zA-Z'-]+")


# ── channel 1: proper noun density ─────────────────────────────
# Detected heuristically: capitalized words not at sentence start
# and not common English sentence-openers.

_COMMON_SENTENCE_STARTERS = set(
    w.lower()
    for w in [
        "the", "a", "an", "this", "that", "these", "those",
        "it", "he", "she", "they", "we", "i", "you",
        "in", "on", "at", "by", "for", "with", "from", "to",
        "as", "if", "when", "while", "after", "before", "since",
        "but", "and", "or", "so", "yet", "however", "although",
        "because", "since", "therefore", "thus", "hence",
        "moreover", "furthermore", "meanwhile", "also",
        "some", "many", "most", "each", "every", "no", "not",
        "what", "which", "who", "how", "why", "where",
        "here", "there", "now", "then", "one", "two", "first",
        "its", "his", "her", "their", "our", "my", "your",
        "all", "both", "neither", "either", "any", "such",
        "just", "only", "even", "still", "already", "yet",
        "very", "quite", "rather", "fairly", "somewhat",
        "let", "suppose", "consider", "assume", "imagine",
    ]
)

_PROPER_NOUN_EXEMPTIONS = set(
    w for w in [
        "I", "I'm", "I've", "I'll", "I'd",
        "The", "This", "That", "These", "Those",
        "It", "He", "She", "They", "We", "You",
        "In", "On", "At", "By", "For", "With", "From", "To",
        "As", "If", "When", "While", "After", "Before", "Since",
        "But", "And", "Or", "So", "Yet", "However", "Although",
        "Because", "Since", "Therefore", "Thus", "Hence",
        "Moreover", "Furthermore", "Meanwhile", "Also",
        "Some", "Many", "Most", "Each", "Every", "No", "Not",
        "What", "Which", "Who", "How", "Why", "Where",
        "Here", "There", "Now", "Then", "One", "Two", "First",
        "Its", "His", "Her", "Their", "Our", "My", "Your",
        "All", "Both", "Neither", "Either", "Any", "Such",
        "Just", "Only", "Even", "Still", "Already", "Yet",
        "Very", "Quite", "Rather", "Fairly", "Somewhat",
        "Let", "Suppose", "Consider", "Assume", "Imagine",
    ]
)


# ── channel 2: numerical precision ─────────────────────────────
# Exact numbers, measurements with units, dates, timestamps,
# version numbers.

# Numbers with decimal places
_DECIMAL_NUMBER = re.compile(r"\b\d+\.\d+\b")

# Numbers with measurement units
_MEASUREMENT = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:"
    r"mm|cm|m|km|inch|inches|ft|feet|yd|yards|mi|miles|"
    r"mg|g|kg|lb|lbs|oz|ounces|"
    r"ml|l|liters?|gallons?|"
    r"ms|s|sec|seconds?|min|minutes?|h|hr|hours?|"
    r"hz|khz|mhz|ghz|"
    r"kb|mb|gb|tb|pb|"
    r"bps|kbps|mbps|"
    r"rpm|mph|kph|"
    r"°[CF]|degrees?\s*(?:celsius|fahrenheit)|"
    r"px|em|rem|vh|vw|"
    r"w|kw|mw|"
    r"v|kv|"
    r"a|ma|"
    r"mol|ph|"
    r"%|percent"
    r")\b",
    re.IGNORECASE,
)

# Dates: 2024-01-15, January 15 2024, 15/01/2024, etc.
_DATE_PATTERN = re.compile(
    r"\b(?:"
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|"
    r"(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{1,2},?\s+\d{4}|"
    r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|"
    r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}"
    r")\b",
    re.IGNORECASE,
)

# Timestamps: 14:30, 14:30:22, 2:15 PM
_TIMESTAMP = re.compile(
    r"\b\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp][Mm])?\b"
)

# Version numbers: v2.1.3, 3.7.2, Python 3.12
_VERSION = re.compile(
    r"\b(?:v|version\s+)?\d+\.\d+(?:\.\d+)?(?:\.\d+)?\b",
    re.IGNORECASE,
)

# Plain integers (4+ digits are likely specific counts/IDs)
_LARGE_INTEGER = re.compile(r"\b\d{4,}\b")

# Any number at all (for ratio calculation)
_ANY_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")


# ── channel 3: concrete noun ratio ─────────────────────────────
# Heuristic: concrete nouns are physical objects detectable by
# senses; abstract nouns are concepts, processes, qualities.

_ABSTRACT_NOUNS = set(
    w.lower()
    for w in [
        # General abstractions
        "idea", "concept", "notion", "theory", "principle", "law",
        "method", "approach", "strategy", "tactic", "technique",
        "process", "procedure", "system", "framework", "paradigm",
        "model", "pattern", "structure", "architecture", "design",
        "problem", "solution", "challenge", "issue", "concern",
        "question", "answer", "response", "reaction",
        "information", "data", "knowledge", "wisdom", "insight",
        "understanding", "awareness", "perception", "cognition",
        "communication", "conversation", "dialogue", "discussion",
        "relationship", "connection", "association", "correlation",
        "development", "evolution", "growth", "progress", "change",
        "situation", "condition", "state", "status", "circumstance",
        "aspect", "feature", "characteristic", "property", "quality",
        "ability", "capability", "capacity", "potential", "possibility",
        "opportunity", "necessity", "requirement", "obligation",
        "experience", "observation", "evidence", "proof",
        "importance", "significance", "relevance", "value", "worth",
        "effect", "impact", "influence", "consequence", "result",
        "performance", "efficiency", "effectiveness", "productivity",
        "behavior", "conduct", "action", "activity", "operation",
        "management", "administration", "organization", "coordination",
        "implementation", "execution", "deployment", "integration",
        "optimization", "improvement", "enhancement", "refinement",
        "analysis", "evaluation", "assessment", "measurement",
        "consideration", "investigation", "examination", "review",
        "infrastructure", "environment", "context", "landscape",
        "complexity", "difficulty", "simplicity", "clarity",
        "security", "reliability", "availability", "scalability",
        "sustainability", "maintainability", "usability", "accessibility",
        "functionality", "compatibility", "interoperability",
        "methodology", "philosophy", "psychology", "sociology",
        "technology", "innovation", "creativity", "productivity",
        "diversity", "equality", "equity", "inclusion", "belonging",
        "health", "wellness", "wellbeing", "fitness", "vitality",
    ]
)

_CONCRETE_NOUNS = set(
    w.lower()
    for w in [
        # Physical objects
        "table", "chair", "desk", "door", "window", "wall", "floor",
        "screen", "keyboard", "mouse", "monitor", "laptop", "phone",
        "book", "paper", "pen", "pencil", "notebook", "folder",
        "car", "truck", "bus", "train", "plane", "bicycle", "boat",
        "house", "building", "room", "kitchen", "bathroom", "office",
        "tree", "flower", "grass", "leaf", "branch", "root", "seed",
        "water", "coffee", "tea", "milk", "juice", "wine", "beer",
        "bread", "cheese", "meat", "fish", "rice", "egg", "eggs",
        "apple", "butter", "salt", "sugar", "flour", "oil",
        "oven", "stove", "fridge", "sink", "faucet",
        "hand", "foot", "head", "eye", "ear", "nose", "mouth",
        "finger", "thumb", "arm", "leg", "shoulder", "knee",
        "dog", "cat", "bird", "fish", "horse", "cow", "pig",
        "server", "disk", "cable", "wire", "chip", "board", "rack",
        "cup", "mug", "glass", "plate", "bowl", "pot", "pan",
        "shirt", "shoes", "hat", "coat", "dress", "pants", "jacket",
        "tool", "hammer", "screwdriver", "wrench", "drill", "saw",
        "machine", "engine", "motor", "pump", "valve", "pipe",
        "rock", "stone", "sand", "dirt", "soil", "mud", "clay",
        "light", "lamp", "bulb", "candle", "flashlight", "torch",
    ]
)


# ── channel 4: generalization markers ──────────────────────────
# Words and phrases signaling category-level discourse.

_GENERALIZATION_SINGLE = set(
    w.lower()
    for w in [
        "generally", "typically", "usually", "often", "frequently",
        "commonly", "normally", "regularly", "ordinarily",
        "mostly", "largely", "mainly", "primarily", "predominantly",
        "broadly", "roughly", "approximately",
        "many", "most", "several", "various", "numerous",
    ]
)

_GENERALIZATION_PHRASES = [
    "in general",
    "as a rule",
    "on the whole",
    "by and large",
    "for the most part",
    "more often than not",
    "tends to",
    "tend to",
    "tended to",
    "in most cases",
    "in many cases",
    "in some cases",
    "as a general rule",
    "generally speaking",
    "broadly speaking",
    "strictly speaking",
    "in the main",
    "to a large extent",
    "to a great extent",
    "more or less",
    "by default",
    "on average",
    "statistically speaking",
    "all else being equal",
    "all things considered",
    "in the abstract",
    "in principle",
]


# ── channel 5: instance markers ────────────────────────────────
# Words and phrases signaling specific examples or cases.

_INSTANCE_PHRASES = [
    "for example",
    "for instance",
    "specifically",
    "in particular",
    "such as",
    "namely",
    "to illustrate",
    "as a case in point",
    "consider the case",
    "take the case",
    "one example is",
    "a specific case",
    "a concrete example",
    "to give an example",
    "by way of example",
    "to cite an example",
    "as an illustration",
    "in one instance",
    "in a specific instance",
    "looking at",
    "take for example",
    "consider for example",
    "to take one example",
    "a case in point",
    "as evidenced by",
    "to be specific",
]

_INSTANCE_SINGLE = set(
    w.lower()
    for w in [
        "specifically", "particularly", "especially",
        "notably", "viz",
    ]
)


# ── helper functions ────────────────────────────────────────────


def _count_sentences(text: str) -> int:
    """Count sentences by splitting on sentence-ending punctuation."""
    parts = _SENTENCE_SPLIT.split(text.strip())
    return len([p for p in parts if p.strip()])


def _count_words(text: str) -> int:
    """Count words in the text."""
    return len(_WORD_SPLIT.findall(text))


def _extract_words(text: str) -> List[str]:
    """Extract all words as lowercase strings."""
    return [w.lower() for w in _WORD_SPLIT.findall(text)]


def _count_phrase_hits(text: str, phrases: List[str]) -> int:
    """Count how many times phrases appear in text (case-insensitive)."""
    lower = text.lower()
    total = 0
    for phrase in phrases:
        total += lower.count(phrase.lower())
    return total


def _count_proper_nouns(text: str) -> int:
    """Count proper nouns heuristically: capitalized words not at
    sentence starts and not common function words."""
    count = 0
    sentences = _SENTENCE_SPLIT.split(text.strip())
    for sentence in sentences:
        tokens = sentence.strip().split()
        for i, token in enumerate(tokens):
            # Skip first word of sentence (always capitalized)
            if i == 0:
                continue
            # Strip punctuation from edges
            clean = token.strip(".,;:!?\"'()[]{}")
            if not clean:
                continue
            # Must start with uppercase and have at least 2 chars
            if len(clean) < 2:
                continue
            if not clean[0].isupper():
                continue
            # Skip if it's in the exemptions list
            if clean in _PROPER_NOUN_EXEMPTIONS:
                continue
            # Skip all-caps abbreviations shorter than 3 chars
            if clean.isupper() and len(clean) <= 2:
                continue
            count += 1
    return count


def _count_numerical_precision(text: str) -> int:
    """Count numerically precise expressions."""
    count = 0
    count += len(_DECIMAL_NUMBER.findall(text))
    count += len(_MEASUREMENT.findall(text))
    count += len(_DATE_PATTERN.findall(text))
    count += len(_TIMESTAMP.findall(text))
    count += len(_VERSION.findall(text))
    count += len(_LARGE_INTEGER.findall(text))
    return count


def _count_concrete_nouns(text: str) -> int:
    """Count concrete noun occurrences."""
    words = _extract_words(text)
    return sum(1 for w in words if w in _CONCRETE_NOUNS)


def _count_abstract_nouns(text: str) -> int:
    """Count abstract noun occurrences."""
    words = _extract_words(text)
    return sum(1 for w in words if w in _ABSTRACT_NOUNS)


# ── result dataclass ────────────────────────────────────────────


@dataclass
class ProseGranularityResult:
    """Result of prose granularity measurement."""

    # Composite
    granularity_index: float = 0.0
    classification: str = "abstract"

    # Per-channel raw counts
    proper_noun_count: int = 0
    numerical_precision_count: int = 0
    concrete_noun_count: int = 0
    abstract_noun_count: int = 0
    generalization_count: int = 0
    instance_count: int = 0

    # Per-channel scores (0.0–1.0)
    proper_noun_score: float = 0.0
    numerical_precision_score: float = 0.0
    concreteness_score: float = 0.0
    generalization_score: float = 0.0
    instance_score: float = 0.0

    # Metadata
    total_granularity_markers: int = 0
    total_sentences: int = 0
    total_words: int = 0
    concrete_abstract_ratio: float = 0.0


# ── main measurement function ──────────────────────────────────


def measure_prose_granularity(text: str) -> ProseGranularityResult:
    """Measure prose granularity of a text.

    Returns a ProseGranularityResult with granularity_index
    (0.0–1.0) and classification.
    """
    result = ProseGranularityResult()

    stripped = text.strip()
    if not stripped:
        result.classification = "abstract"
        return result

    sentences = _count_sentences(text)
    words = _count_words(text)
    result.total_sentences = sentences
    result.total_words = words

    denom = max(sentences, 1)

    # ── channel 1: proper noun density (cap: 3 per sentence) ──
    proper_hits = _count_proper_nouns(text)
    result.proper_noun_count = proper_hits
    result.proper_noun_score = min(1.0, (proper_hits / denom) / 3.0)

    # ── channel 2: numerical precision (cap: 2 per sentence) ──
    numerical_hits = _count_numerical_precision(text)
    result.numerical_precision_count = numerical_hits
    result.numerical_precision_score = min(1.0, (numerical_hits / denom) / 2.0)

    # ── channel 3: concrete vs abstract nouns ──────────────────
    concrete_hits = _count_concrete_nouns(text)
    abstract_hits = _count_abstract_nouns(text)
    result.concrete_noun_count = concrete_hits
    result.abstract_noun_count = abstract_hits
    total_nouns = concrete_hits + abstract_hits
    if total_nouns > 0:
        result.concrete_abstract_ratio = round(
            concrete_hits / total_nouns, 4
        )
        result.concreteness_score = result.concrete_abstract_ratio
    else:
        result.concrete_abstract_ratio = 0.0
        result.concreteness_score = 0.0

    # ── channel 4: generalization markers (cap: 1.5 per sentence) ─
    all_words = _extract_words(text)
    generalization_hits = sum(
        1 for w in all_words if w in _GENERALIZATION_SINGLE
    )
    generalization_hits += _count_phrase_hits(text, _GENERALIZATION_PHRASES)
    result.generalization_count = generalization_hits
    # Inverted: more generalization → lower granularity
    generalization_raw = min(1.0, (generalization_hits / denom) / 1.5)
    result.generalization_score = generalization_raw

    # ── channel 5: instance markers (cap: 1.5 per sentence) ────
    instance_hits = sum(1 for w in all_words if w in _INSTANCE_SINGLE)
    instance_hits += _count_phrase_hits(text, _INSTANCE_PHRASES)
    result.instance_count = instance_hits
    result.instance_score = min(1.0, (instance_hits / denom) / 1.5)

    # ── composite index ──────────────────────────────────────
    # Weights: proper_noun 0.25, numerical_precision 0.25,
    # concreteness 0.20, instance_markers 0.15,
    # generalization_inverted 0.15
    #
    # Generalization is inverted: more generalization = lower
    # granularity, so we use (1 - generalization_score) as the
    # contribution, scaled to the weight.
    inv_gen = 1.0 - result.generalization_score

    result.granularity_index = round(
        0.25 * result.proper_noun_score
        + 0.25 * result.numerical_precision_score
        + 0.20 * result.concreteness_score
        + 0.15 * result.instance_score
        + 0.15 * inv_gen,
        4,
    )

    result.granularity_index = min(1.0, max(0.0, result.granularity_index))

    result.total_granularity_markers = (
        proper_hits
        + numerical_hits
        + concrete_hits
        + abstract_hits
        + generalization_hits
        + instance_hits
    )

    # ── classification ───────────────────────────────────────
    idx = result.granularity_index
    if idx < 0.15:
        result.classification = "abstract"
    elif idx < 0.30:
        result.classification = "general"
    elif idx < 0.50:
        result.classification = "mixed"
    elif idx < 0.70:
        result.classification = "specific"
    else:
        result.classification = "granular"

    return result
