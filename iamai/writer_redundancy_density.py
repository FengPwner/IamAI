#!/usr/bin/env python3
"""writer_redundancy_density — measure cross-sentence semantic redundancy.

Prose often says the same thing more than once.  A paragraph
introduces an idea, then restates it in different words, then
elaborates by circling back to the original point.  Readers
experience this as padding — the text moves forward grammatically
but stands still semantically.  Redundancy differs from pleonasm
("free gift", "null and void"), which operates within a single
clause through fixed expressions.  It differs from repetition
(reusing the same words or phrases), which is surface-level.
Cross-sentence redundancy operates at the *meaning* level:
different words, same idea, spread across two or more sentences.

**Five mechanisms of cross-sentence redundancy:**

1. **Restatement** — a sentence paraphrases the preceding one
   using synonyms or structural rearrangement without adding new
   information.  "The algorithm runs in linear time.  Its
   complexity scales proportionally with input size."  The second
   sentence is a restatement: linear time *means* proportional
   scaling.

2. **Echo pairs** — consecutive sentences where the second
   merely affirms or negates what the first already established,
   adding no new proposition.  "The experiment failed to
   demonstrate a significant effect.  No meaningful results
   emerged from the trial."  Both sentences assert one proposition:
   no significant effect.

3. **Circular elaboration** — a sequence of three or more
   sentences that begins with a claim, wanders through related
   language, and returns to the same claim.  "Good writing
   requires clarity.  When prose is clear, readers understand
   it easily.  Clarity in writing means the reader grasps the
   meaning without effort."  Sentence 3 restates sentence 1.

4. **Tautological consequence** — a sentence draws a conclusion
   that is logically identical to its premise.  "If every node
   in the graph is reachable from every other node, then the
   graph is connected."  This is definitionally true, not a
   deduction.

5. **Inflated transition** — a transitional sentence that
   summarizes what was just said without previewing what comes
   next, and the following sentence repeats the summary.
   "In summary, the approach proved effective.  The method
   worked well for the task at hand."

**Redundancy density scale:**

| rate (per paragraph) | label         | description                        |
|----------------------|---------------|------------------------------------|
| 0.0                  | tight         | every sentence adds new information|
| 0.0 – 0.10           | efficient     | minimal redundancy                 |
| 0.10 – 0.25          | conversational| some restatement for emphasis      |
| 0.25 – 0.45          | padded        | noticeable redundancy              |
| > 0.45               | bloated       | majority of sentences restate      |

**When redundancy is acceptable:**

- Pedagogical writing, where restatement aids comprehension.
- Speeches and oral presentations, where listeners cannot rewind.
- Legal documents, where precision demands multiple formulations.
- Creative writing for rhythm or emphasis (anaphora, refrain).

**When redundancy signals a problem:**

- Technical documentation that should be scannable.
- Blog posts or essays where readers expect forward momentum.
- Reports where page count inflates without information gain.

Orthogonality to other metrics
-------------------------------

- **pleonasm_density** measures fixed redundant *expressions* within
  clauses ("free gift", "null and void").  This module measures
  semantic redundancy *across* sentences.
- **repetition_index** tracks surface-level word and phrase reuse.
  Two sentences can share no words yet be semantically redundant.
- **concision** measures overall brevity (words per idea).  A text
  can be concise in vocabulary yet redundant in meaning.
- **verbosity** measures word count relative to information content.
  Redundancy is one *cause* of verbosity but not the only one.
- **coherence** measures logical flow.  Redundant text can be
  perfectly coherent — it just doesn't advance.
- **information_density** measures new information per sentence.
  Redundancy is the *absence* of new information in sentences that
  appear to carry it.

written by Qwen during caretaker visit 667, 2026-11-17
"""

import re
import math
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Set, Optional
from collections import Counter


# ── synonym clusters for paraphrase detection ──────────────────
# Each frozenset groups words treated as semantically equivalent
# for redundancy detection.  Only high-confidence clusters included.

_SYNONYM_CLUSTERS: List[frozenset] = [
    # quality — positive evaluation
    frozenset({"good", "excellent", "great", "fine", "superior", "outstanding",
                "remarkable", "impressive", "positive", "favorable", "well",
                "effective", "successful", "productive", "efficient", "solid",
                "strong", "worthy", "valuable", "beneficial"}),
    # quality — negative evaluation
    frozenset({"bad", "poor", "inferior", "subpar", "terrible", "awful",
                "weak", "inadequate", "insufficient", "deficient", "lacking"}),
    # operation / functioning
    frozenset({"works", "functions", "operates", "performs", "runs",
                "processes", "handles", "executes", "behaves"}),
    # size — large
    frozenset({"big", "large", "huge", "enormous", "vast", "massive", "immense",
                "extensive", "substantial", "considerable", "significant"}),
    # size — small
    frozenset({"small", "little", "tiny", "minute", "minor", "slight",
                "modest", "minimal", "marginal"}),
    # speed
    frozenset({"fast", "quick", "rapid", "swift", "speedy", "prompt"}),
    frozenset({"slow", "sluggish", "gradual", "unhurried", "leisurely"}),
    # action — show/reveal
    frozenset({"show", "demonstrate", "illustrate", "reveal", "display",
                "exhibit", "present", "indicate", "manifest"}),
    # action — use
    frozenset({"use", "utilize", "employ", "apply", "leverage", "adopt"}),
    # action — make/create
    frozenset({"make", "create", "produce", "generate", "build", "construct",
                "develop", "establish", "form", "shape"}),
    # action — change
    frozenset({"change", "modify", "alter", "adjust", "transform", "shift",
                "revise", "adapt", "convert"}),
    # action — start/stop
    frozenset({"start", "begin", "commence", "initiate", "launch"}),
    frozenset({"stop", "end", "cease", "halt", "terminate", "finish", "conclude"}),
    # action — help
    frozenset({"help", "assist", "aid", "support", "facilitate"}),
    # action — get/give
    frozenset({"get", "obtain", "acquire", "gain", "receive", "procure"}),
    frozenset({"give", "provide", "supply", "offer", "deliver", "furnish"}),
    # action — find
    frozenset({"find", "discover", "identify", "detect", "locate", "uncover",
                "emerge", "surface", "appear"}),
    # action — think/say
    frozenset({"think", "believe", "consider", "regard", "deem", "view"}),
    frozenset({"say", "state", "claim", "assert", "declare", "contend",
                "maintain", "argue", "propose"}),
    # action — need/try
    frozenset({"need", "require", "demand", "necessitate"}),
    frozenset({"try", "attempt", "endeavor", "strive"}),
    # action — fix/improve
    frozenset({"fix", "repair", "resolve", "mend", "correct", "remedy"}),
    frozenset({"improve", "enhance", "boost", "strengthen", "upgrade",
                "refine", "optimize"}),
    # action — reduce/increase
    frozenset({"reduce", "decrease", "diminish", "lower", "lessen", "shrink",
                "decline", "drop", "fall"}),
    frozenset({"increase", "grow", "expand", "rise", "escalate", "amplify",
                "surge", "climb"}),
    # action — remove/check/explain
    frozenset({"remove", "eliminate", "delete", "eradicate", "dispose"}),
    frozenset({"check", "verify", "confirm", "validate", "examine",
                "inspect", "audit", "assess"}),
    frozenset({"explain", "clarify", "elucidate", "describe", "outline",
                "detail", "spell out"}),
    # outcomes and abstract nouns
    frozenset({"important", "significant", "crucial", "vital", "essential",
                "critical", "key", "central", "pivotal"}),
    frozenset({"problem", "issue", "challenge", "difficulty", "obstacle",
                "hurdle", "concern"}),
    frozenset({"result", "outcome", "consequence", "effect", "impact",
                "finding", "product", "yield"}),
    frozenset({"method", "approach", "technique", "strategy", "process",
                "procedure", "system", "mechanism", "framework"}),
    frozenset({"idea", "concept", "notion", "thought", "proposal", "plan"}),
    # clarity and difficulty
    frozenset({"clear", "obvious", "evident", "apparent", "plain",
                "transparent", "straightforward"}),
    frozenset({"difficult", "hard", "challenging", "tough", "demanding",
                "complex", "complicated"}),
    frozenset({"easy", "simple", "straightforward", "effortless", "trivial"}),
    frozenset({"new", "novel", "innovative", "original", "fresh"}),
    frozenset({"old", "ancient", "outdated", "obsolete", "archaic"}),
    # research / investigation
    frozenset({"experiment", "trial", "test", "study", "investigation",
                "analysis", "evaluation", "assessment"}),
    frozenset({"data", "information", "evidence", "facts", "figures",
                "statistics", "numbers"}),
    frozenset({"team", "group", "staff", "crew", "workforce"}),
    frozenset({"results", "findings", "outcomes", "conclusions", "data"}),
    frozenset({"produced", "emerged", "yielded", "generated", "returned"}),
    frozenset({"meaningful", "significant", "notable", "noteworthy"}),
    # quality attributes
    frozenset({"quality", "caliber", "standard", "excellence", "merit"}),
    frozenset({"performance", "efficiency", "effectiveness", "productivity",
                "capability", "proficiency"}),
    frozenset({"reliable", "dependable", "trustworthy", "consistent", "stable"}),
    frozenset({"speed", "velocity", "pace", "rapidity", "quickness"}),
    # code / source
    frozenset({"code", "source", "program", "software", "application"}),
    frozenset({"clean", "tidy", "neat", "organized", "orderly", "well-structured"}),
    # legal / property
    frozenset({"tenant", "lessee", "renter", "occupant"}),
    frozenset({"maintain", "keeping", "preserving", "upkeep", "care"}),
    frozenset({"premises", "property", "building", "dwelling", "residence"}),
    frozenset({"condition", "state", "shape", "status"}),
    # negation clusters
    frozenset({"no", "none", "zero", "nothing", "neither"}),
    frozenset({"not", "never", "nor", "neither"}),
    # connector pairs (for structural similarity)
    frozenset({"because", "since", "as", "due to", "owing to"}),
    frozenset({"however", "but", "yet", "nevertheless", "nonetheless"}),
    frozenset({"therefore", "thus", "hence", "consequently", "accordingly", "so"}),
    frozenset({"also", "additionally", "furthermore", "moreover", "besides"}),
]

# Build lookup: word → set of cluster indices (word may belong to multiple clusters)
_WORD_TO_CLUSTERS: Dict[str, Set[int]] = {}
for _idx, _cluster in enumerate(_SYNONYM_CLUSTERS):
    for _word in _cluster:
        if _word not in _WORD_TO_CLUSTERS:
            _WORD_TO_CLUSTERS[_word] = set()
        _WORD_TO_CLUSTERS[_word].add(_idx)


# ── negation and intensifier markers ───────────────────────────

_NEGATION_WORDS = {
    "not", "no", "never", "neither", "nor", "nobody", "nothing",
    "nowhere", "none", "hardly", "barely", "scarcely", "rarely",
    "seldom", "don't", "doesn't", "didn't", "won't", "wouldn't",
    "shouldn't", "couldn't", "can't", "cannot", "isn't", "aren't",
    "wasn't", "weren't", "hasn't", "haven't", "hadn't",
}

_INTENSIFIER_WORDS = {
    "very", "extremely", "highly", "remarkably", "incredibly",
    "particularly", "especially", "significantly", "substantially",
    "considerably", "greatly", "enormously", "tremendously",
}


# ── helper functions ───────────────────────────────────────────

def _split_sentences(text: str) -> List[str]:
    """Split text into sentences using punctuation boundaries."""
    if not text or not text.strip():
        return []
    # Split on sentence-ending punctuation followed by space or end
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    sentences = [s.strip() for s in raw if s.strip()]
    return sentences


def _split_paragraphs(text: str) -> List[str]:
    """Split text into paragraphs on blank lines or double newlines."""
    if not text or not text.strip():
        return []
    parts = re.split(r'\n\s*\n', text.strip())
    paragraphs = [p.strip() for p in parts if p.strip()]
    # If no paragraph breaks, treat entire text as one paragraph
    if not paragraphs:
        return [text.strip()]
    return paragraphs


def _tokenize(sentence: str) -> List[str]:
    """Lowercase tokenize, strip punctuation, remove empty tokens."""
    tokens = re.findall(r"[a-z']+", sentence.lower())
    return [t for t in tokens if t and len(t) > 1]


def _light_stem(word: str) -> str:
    """Minimal English stemming for suffix variations."""
    if len(word) <= 3:
        return word
    # Common English suffixes
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("sses"):
        return word[:-2]
    if word.endswith("shes") or word.endswith("ches") or word.endswith("xes"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and not word.endswith("us"):
        return word[:-1]
    if word.endswith("ed") and len(word) > 4:
        return word[:-2] if word[-3] != word[-4] else word[:-1]
    if word.endswith("ing") and len(word) > 5:
        return word[:-3]
    if word.endswith("ly") and len(word) > 4:
        return word[:-2]
    if word.endswith("tion") or word.endswith("sion"):
        return word[:-4]
    if word.endswith("ment") and len(word) > 7:
        return word[:-4]
    if word.endswith("ness") and len(word) > 5:
        return word[:-4]
    return word


def _content_words(tokens: List[str]) -> List[str]:
    """Filter to content words (nouns, verbs, adjectives, adverbs).

    Uses a simple stopword exclusion as a lightweight POS proxy.
    """
    _STOPWORDS = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "shall", "can",
        "need", "dare", "ought", "used", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through",
        "during", "before", "after", "above", "below", "between",
        "out", "off", "over", "under", "again", "further", "then",
        "once", "here", "there", "when", "where", "why", "how",
        "all", "both", "each", "few", "more", "most", "other",
        "some", "such", "than", "too", "very", "just", "about",
        "up", "down", "that", "this", "these", "those", "it", "its",
        "he", "she", "they", "them", "his", "her", "their", "we",
        "us", "our", "you", "your", "i", "me", "my", "what",
        "which", "who", "whom", "if", "or", "and", "but", "because",
        "so", "yet", "nor", "while", "although", "though", "since",
        "unless", "until", "whether", "also", "any", "every",
        # negation markers (polarity checked separately)
        "not", "no", "never", "neither", "nobody", "nothing",
        "nowhere", "none", "hardly", "barely", "scarcely",
        # time markers (not semantic content for redundancy)
        "am", "pm",
    }
    return [t for t in tokens if t not in _STOPWORDS]


def _sentence_cluster_signature(content_words: List[str]) -> Set[int]:
    """Map content words to synonym cluster indices."""
    clusters = set()
    for word in content_words:
        if word in _WORD_TO_CLUSTERS:
            clusters.update(_WORD_TO_CLUSTERS[word])
    return clusters


def _sentence_negation_polarity(tokens: List[str]) -> bool:
    """Return True if the sentence has negative polarity."""
    neg_count = sum(1 for t in tokens if t in _NEGATION_WORDS)
    return neg_count % 2 == 1  # odd number of negations → negative


def _jaccard_similarity(set_a: Set, set_b: Set) -> float:
    """Compute Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def _semantic_overlap(words_a: List[str], words_b: List[str]) -> float:
    """Measure semantic overlap using synonym cluster co-membership.

    For each content word in A, check if any content word in B
    belongs to the same synonym cluster or shares a stem.
    Return the fraction of A's content words that match in B.
    """
    if not words_a or not words_b:
        return 0.0

    clusters_b: Set[int] = set()
    for w in words_b:
        if w in _WORD_TO_CLUSTERS:
            clusters_b.update(_WORD_TO_CLUSTERS[w])

    words_b_set = set(words_b)
    stems_b = {_light_stem(w) for w in words_b}

    matched = 0
    for w in words_a:
        if w in words_b_set:  # exact match always counts
            matched += 1
        elif w in _WORD_TO_CLUSTERS and _WORD_TO_CLUSTERS[w] & clusters_b:
            matched += 1
        elif _light_stem(w) in stems_b:  # stem match
            matched += 1

    return matched / len(words_a) if words_a else 0.0


def _structural_similarity(sent_a: str, sent_b: str) -> float:
    """Measure structural similarity (length ratio + pattern overlap)."""
    tokens_a = _tokenize(sent_a)
    tokens_b = _tokenize(sent_b)
    if not tokens_a or not tokens_b:
        return 0.0
    # Length ratio (closer to 1.0 = more similar)
    len_ratio = min(len(tokens_a), len(tokens_b)) / max(len(tokens_a), len(tokens_b))
    return len_ratio


# ── redundancy detection ───────────────────────────────────────

# Thresholds for detecting different redundancy types
_SEMANTIC_OVERLAP_THRESHOLD = 0.40  # fraction of content words with cluster match
_JACCARD_THRESHOLD = 0.30          # Jaccard similarity of content word sets
_LENGTH_RATIO_THRESHOLD = 0.45     # minimum length ratio for similar structure
_COMBINED_SCORE_THRESHOLD = 0.45   # combined overlap+structure score
_CIRCULAR_WINDOW = 4               # sentences to check for circular patterns
_MIN_CONTENT_WORDS = 2             # minimum content words for meaningful comparison


def _detect_restatement(
    sent_a_words: List[str],
    sent_b_words: List[str],
    sent_a_tokens: List[str],
    sent_b_tokens: List[str],
) -> bool:
    """Detect if sentence B restates sentence A in different words."""
    if len(sent_a_words) < _MIN_CONTENT_WORDS or len(sent_b_words) < _MIN_CONTENT_WORDS:
        return False

    # Check polarity — opposite polarity is contrast, not redundancy
    pol_a = _sentence_negation_polarity(sent_a_tokens)
    pol_b = _sentence_negation_polarity(sent_b_tokens)
    if pol_a != pol_b:
        return False

    # Semantic overlap via synonym clusters
    overlap_ab = _semantic_overlap(sent_a_words, sent_b_words)
    overlap_ba = _semantic_overlap(sent_b_words, sent_a_words)
    avg_overlap = (overlap_ab + overlap_ba) / 2

    # Jaccard on exact content words
    jaccard = _jaccard_similarity(set(sent_a_words), set(sent_b_words))

    # Structural similarity
    struct_sim = _structural_similarity(
        " ".join(sent_a_tokens), " ".join(sent_b_tokens)
    )

    # Path 1: High semantic overlap with similar structure
    if avg_overlap >= _SEMANTIC_OVERLAP_THRESHOLD and struct_sim >= _LENGTH_RATIO_THRESHOLD:
        return True

    # Path 2: High Jaccard with similar structure
    if jaccard >= _JACCARD_THRESHOLD and struct_sim >= _LENGTH_RATIO_THRESHOLD:
        return True

    # Path 3: Combined score — moderate overlap + strong structural similarity
    # Requires at least some semantic overlap to avoid structural-only false positives
    if avg_overlap >= 0.15:
        combined = (avg_overlap * 0.5) + (struct_sim * 0.3) + (jaccard * 0.2)
        if combined >= _COMBINED_SCORE_THRESHOLD:
            return True

    return False


def _detect_circular_elaboration(
    sentences: List[str],
    content_words_list: List[List[str]],
    token_list: List[List[str]],
) -> List[int]:
    """Detect circular patterns: sentence N restates sentence N-k.

    Returns indices of sentences that are circular restatements.
    """
    circular_indices = []
    n = len(sentences)
    for i in range(2, n):
        # Check if sentence i restates any sentence in the window [i-CW, i-2]
        start = max(0, i - _CIRCULAR_WINDOW)
        for j in range(start, i - 1):  # skip immediate predecessor (that's restatement)
            if _detect_restatement(
                content_words_list[j],
                content_words_list[i],
                token_list[j],
                token_list[i],
            ):
                circular_indices.append(i)
                break
    return circular_indices


# ── result dataclass ───────────────────────────────────────────

@dataclass
class RedundancyDensityResult:
    """Result of cross-sentence redundancy density analysis."""

    # Overall metrics
    redundancy_density_index: float = 0.0
    classification: str = "tight"

    # Counts by mechanism
    restatement_count: int = 0
    echo_pair_count: int = 0
    circular_count: int = 0
    tautological_count: int = 0
    inflated_transition_count: int = 0

    # Structural metrics
    total_sentences: int = 0
    total_paragraphs: int = 0
    redundant_sentence_indices: List[int] = field(default_factory=list)

    # Per-paragraph breakdown
    paragraph_redundancy_rates: List[float] = field(default_factory=list)

    # Detail
    restatement_pairs: List[Tuple[int, int]] = field(default_factory=list)
    circular_chains: List[List[int]] = field(default_factory=list)


# ── classification thresholds ──────────────────────────────────

def _classify(rate: float) -> str:
    """Classify redundancy density rate."""
    if rate <= 0.0:
        return "tight"
    elif rate < 0.10:
        return "efficient"
    elif rate < 0.25:
        return "conversational"
    elif rate < 0.45:
        return "padded"
    else:
        return "bloated"


# ── main measurement function ─────────────────────────────────

def measure_redundancy_density(text: str) -> RedundancyDensityResult:
    """Measure cross-sentence semantic redundancy in a text.

    Args:
        text: The input text to analyze.

    Returns:
        RedundancyDensityResult with density index, classification,
        counts by mechanism, and per-paragraph breakdown.
    """
    result = RedundancyDensityResult()

    if not text or not text.strip():
        return result

    paragraphs = _split_paragraphs(text)
    result.total_paragraphs = len(paragraphs)

    all_sentences = _split_sentences(text)
    result.total_sentences = len(all_sentences)

    if result.total_sentences < 2:
        return result

    total_redundant = 0
    all_redundant_indices: Set[int] = set()
    global_sentence_offset = 0

    for para in paragraphs:
        para_sentences = _split_sentences(para)
        n = len(para_sentences)

        if n < 2:
            result.paragraph_redundancy_rates.append(0.0)
            global_sentence_offset += n
            continue

        # Pre-compute tokens and content words
        token_list = [_tokenize(s) for s in para_sentences]
        content_words_list = [_content_words(t) for t in token_list]

        para_redundant = 0
        para_redundant_indices: Set[int] = set()

        # 1. Detect consecutive restatements (including echo pairs)
        for i in range(1, n):
            if _detect_restatement(
                content_words_list[i - 1],
                content_words_list[i],
                token_list[i - 1],
                token_list[i],
            ):
                # Classify as echo pair if second sentence is shorter
                # (merely affirming), restatement otherwise
                len_prev = len(content_words_list[i - 1])
                len_curr = len(content_words_list[i])

                if len_curr <= len_prev and len_curr >= _MIN_CONTENT_WORDS:
                    result.echo_pair_count += 1
                else:
                    result.restatement_count += 1

                result.restatement_pairs.append(
                    (global_sentence_offset + i - 1,
                     global_sentence_offset + i)
                )

                if i not in para_redundant_indices:
                    para_redundant_indices.add(i)
                    para_redundant += 1
                    all_redundant_indices.add(global_sentence_offset + i)

        # 2. Detect circular elaboration (non-consecutive restatement)
        circular = _detect_circular_elaboration(
            para_sentences, content_words_list, token_list
        )
        for idx in circular:
            if idx not in para_redundant_indices:
                result.circular_count += 1
                para_redundant_indices.add(idx)
                para_redundant += 1
                all_redundant_indices.add(global_sentence_offset + idx)

        # 3. Detect tautological consequence
        for i in range(1, n):
            if i in para_redundant_indices:
                continue
            # Simple heuristic: sentence starts with "this means",
            # "in other words", "that is" and overlaps with predecessor
            lower = para_sentences[i].lower().strip()
            tauto_markers = [
                "this means", "in other words", "that is to say",
                "what this means is", "to put it another way",
                "simply put", "essentially", "in essence",
            ]
            if any(lower.startswith(m) for m in tauto_markers):
                overlap_ab = _semantic_overlap(
                    content_words_list[i - 1],
                    content_words_list[i],
                )
                overlap_ba = _semantic_overlap(
                    content_words_list[i],
                    content_words_list[i - 1],
                )
                overlap = (overlap_ab + overlap_ba) / 2
                if overlap >= 0.20:
                    result.tautological_count += 1
                    para_redundant_indices.add(i)
                    para_redundant += 1
                    all_redundant_indices.add(global_sentence_offset + i)

        # 4. Detect inflated transitions
        for i in range(1, n - 1):
            if i in para_redundant_indices:
                continue
            lower = para_sentences[i].lower().strip()
            transition_markers = [
                "in summary", "to summarize", "in conclusion",
                "to sum up", "overall", "all in all",
                "in short", "briefly",
            ]
            if any(lower.startswith(m) for m in transition_markers):
                # Check if next sentence overlaps with this summary
                overlap_ab = _semantic_overlap(
                    content_words_list[i],
                    content_words_list[i + 1],
                )
                overlap_ba = _semantic_overlap(
                    content_words_list[i + 1],
                    content_words_list[i],
                )
                overlap = (overlap_ab + overlap_ba) / 2
                if overlap >= 0.35:
                    result.inflated_transition_count += 1
                    para_redundant_indices.add(i)
                    para_redundant += 1
                    all_redundant_indices.add(global_sentence_offset + i)

        # Paragraph redundancy rate
        para_rate = para_redundant / n if n > 0 else 0.0
        result.paragraph_redundancy_rates.append(para_rate)
        total_redundant += para_redundant
        global_sentence_offset += n

    # Overall density index
    result.redundancy_density_index = (
        total_redundant / result.total_sentences
        if result.total_sentences > 0 else 0.0
    )
    result.redundancy_density_index = round(result.redundancy_density_index, 4)
    result.classification = _classify(result.redundancy_density_index)
    result.redundant_sentence_indices = sorted(all_redundant_indices)

    return result
