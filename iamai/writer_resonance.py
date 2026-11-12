#!/usr/bin/env python3
"""writer_resonance — measure the associative and emotional depth of prose.

Resonance tracks *how much meaning vibrates beneath the surface of
the words*.  Resonant prose carries layers: a metaphor that unfolds
on re-reading, an allusion that opens a door to another world, a
word chosen not just for denotation but for its halo of connotation.
Flat prose communicates information but leaves no echo.

This module is orthogonal to the other writer metrics:

- **elegance** tracks *aesthetic quality* — rhythm, balance, grace.
  Elegant prose can be emotionally shallow; resonant prose can be
  structurally rough.  Elegance is surface polish; resonance is
  depth of meaning.

- **concreteness** tracks *sensory grounding*.  Concrete prose
  anchors ideas in physical sensation.  Resonance measures
  *associative richness* — whether language evokes more than it
  literally says.  A concrete sentence ("the red door") may lack
  resonance; an abstract one ("the doors we close behind us") may
  carry deep resonance.

- **subtext** tracks *implied meaning between lines*.  Subtext is
  about what is *not said* — the gap between stated and intended.
  Resonance is about what *echoes within what is said* — layers of
  association embedded in the language itself.

- **vocabulary_richness** tracks *lexical diversity*.  Rich vocabulary
  uses many different words.  Resonance measures not variety but
  *weight* — whether each word carries associative freight.  A text
  can use simple words and be deeply resonant ("and miles to go
  before I sleep").

- **tension** tracks *conflict and anticipation*.  Tension propels
  the reader forward.  Resonance makes the reader pause and feel
  depth.  They are complementary forces: tension accelerates,
  resonance deepens.

Resonance asks: **does the language carry layers of meaning, or
does it communicate only at face value?**

Dimensions
----------

===========================  ===========================================
metric                       meaning
===========================  ===========================================
metaphor_density             fraction of sentences containing figurative
                             language: similes (like, as, than), explicit
                             metaphors (is a, was a, became a linking
                             concrete to abstract), and implicit
                             metaphorical verbs (the idea blossomed, the
                             argument crumbled, time devoured); figurative
                             language creates resonance by mapping one
                             domain of experience onto another
allusion_rate                fraction of sentences referencing cultural,
                             literary, historical, or mythological
                             touchstones: named figures (Shakespeare,
                             Prometheus, Sisyphus), famous phrases
                             (to be or not to be, the road less taken),
                             biblical/classical allusions (a cross to
                             bear, a Trojan horse, Promethean fire);
                             allusions create resonance by connecting
                             the text to a web of shared cultural
                             knowledge
connotative_word_ratio         fraction of content words that carry
                             strong emotional or associative weight
                             beyond their literal meaning: words like
                             "haunt", "ache", "linger", "shatter",
                             "bloom", "wither", "echo", "drown" that
                             evoke feeling through their connotative
                             halo; contrasted with neutral synonyms
                             ("stay", "hurt", "remain", "break",
                             "grow", "die", "repeat", "submerge")
                             that communicate the same denotation
                             without associative depth
imagery_density               fraction of sentences that create vivid
                             mental images through specific, evocative
                             description: not just sensory words (that
                             is concreteness) but images that carry
                             symbolic or emotional weight — "a cracked
                             mirror reflecting the empty room" is both
                             concrete and resonant; "a red ball on the
                             floor" is concrete but may lack resonance;
                             imagery bridges the sensory and the
                             symbolic
echo_density                  fraction of consecutive sentence pairs
                             that share phonetic or lexical patterns
                             creating resonance: alliteration (repeated
                             initial consonants), assonance (repeated
                             vowel sounds), anaphora (repeated opening
                             phrases), epistrophe (repeated endings),
                             and deliberate word repetition used for
                             emphasis; these sonic patterns create a
                             feeling of depth and intentionality even
                             when the reader cannot name the device
===========================  ===========================================

Resonance classes

====================  ==================================================
class                 meaning
====================  ==================================================
profound              >= 0.55 composite score; prose is richly layered,
                      every sentence carries associative weight, the
                      text rewards re-reading and reflection; typical
                      of poetry, literary fiction, and the finest
                      essays
evocative             0.40–0.54 composite score; prose frequently
                      creates layers of meaning through figurative
                      language and evocative word choice; the reader
                      feels depth without being overwhelmed; typical
                      of good creative nonfiction and literary
                      journalism
textured              0.25–0.39 composite score; prose occasionally
                      achieves resonance through well-placed metaphors
                      or connotative language but mostly communicates
                      at face value; typical of competent popular
                      nonfiction
surface               0.10–0.24 composite score; prose communicates
                      primarily at the literal level with minimal
                      figurative language or associative depth;
                      typical of technical documentation, news
                      reporting, and straightforward instructional
                      writing
flat                  < 0.10 composite score; prose has no discernible
                      layers of meaning; language is purely functional
                      with no figurative, allusive, or connotative
                      dimension; typical of poorly written technical
                      text or machine-generated content
====================  ==================================================

Composite score
---------------

The composite resonance_index is a weighted average::

    resonance_index = (
        metaphor_density        * 0.25 +
        allusion_rate           * 0.15 +
        connotative_word_ratio  * 0.30 +
        imagery_density         * 0.20 +
        echo_density            * 0.10
    )

Weights reflect diagnostic importance: connotative word choice (0.30)
is the most pervasive source of resonance — it operates in every
sentence.  Metaphor (0.25) is the most powerful figurative device
for creating layers of meaning.  Imagery (0.20) bridges sensory
experience and symbolic depth.  Allusion (0.15) connects to cultural
knowledge but depends on reader familiarity.  Echo (0.10) operates
at the sonic level and is subtle but deliberate.

Usage
-----

    from iamai.writer_resonance import WriterResonance

    wr = WriterResonance()
    result = wr.measure(text)
    print(result["resonance_index"])   # 0.0–1.0
    print(result["classification"])    # profound|evocative|textured|surface|flat
    print(result["metaphor_density"])  # 0.0–1.0
"""

import re
from typing import Dict, List, Set, Tuple


# --- Figurative language patterns ---

SIMILE_PATTERNS: List[str] = [
    r'\b(?:like|as|than)\s+(?:a|an|the)\b',
    r'\b(?:as|so)\s+\w+\s+as\b',
    r'\b(?:like|as)\s+(?:if|though)\b',
]

METAPHOR_LINKING: List[str] = [
    r'\b(?:is|are|was|were|become|became|becomes)\s+(?:a|an|the)\b',
]

METAPHORICAL_VERBS: Set[str] = {
    # Verbs that create figurative mappings when applied to
    # non-literal subjects/objects
    "blossom", "bloom", "wither", "wilt", "flourish", "thrive",
    "crumble", "collapse", "shatter", "fracture", "splinter",
    "ignite", "kindle", "spark", "smolder", "smoulder", "extinguish",
    "devour", "consume", "swallow", "engulf", "drown", "flood",
    "echo", "resonate", "reverberate", "haunt", "linger", "hover",
    "weave", "spin", "unravel", "untangle", "tangle", "knit",
    "anchor", "ground", "root", "plant", "seed", "harvest",
    "bridge", "span", "connect", "sever", "cut", "cleave",
    "sculpt", "carve", "chisel", "mold", "mould", "forge", "cast",
    "illuminate", "shine", "radiate", "glow", "beam", "flicker",
    "freeze", "thaw", "melt", "solidify", "crystallize",
    "erupt", "explode", "implode", "surge", "swell", "crest",
    "dance", "sing", "whisper", "roar", "scream", "weep",
    "navigate", "chart", "sail", "drift", "anchor",
    "nourish", "starve", "feed", "sustain", "drain",
}

# --- Connotative words (strong associative weight) ---

CONNOTATIVE_WORDS: Set[str] = {
    # Emotion-laden verbs
    "ache", "yearn", "long", "grieve", "mourn", "lament", "rejoice",
    "cherish", "treasure", "adore", "despise", "loathe", "abhor",
    "haunt", "torment", "plague", "afflict", "console", "soothe",
    "crave", "hunger", "thirst", "pine", "sigh", "weep",
    # Evocative adjectives
    "haunting", "poignant", "wistful", "melancholy", "somber",
    "sombre", "luminous", "radiant", "ethereal", "sublime",
    "bleak", "stark", "barren", "desolate", "forlorn", "lonely",
    "tender", "fragile", "delicate", "brittle", "weathered", "worn",
    "fierce", "ferocious", "relentless", "merciless", "gentle",
    # Resonant nouns (symbolic weight)
    "shadow", "echo", "whisper", "ghost", "memory", "dream",
    "silence", "darkness", "light", "dawn", "dusk", "twilight",
    "journey", "path", "road", "crossroads", "threshold", "horizon",
    "mirror", "reflection", "veil", "mask", "window", "door",
    "flame", "ember", "ash", "dust", "ruin", "wreckage",
    "tide", "current", "wave", "storm", "tempest", "calm",
    "wound", "scar", "mark", "stain", "trace", "remnant",
    # Atmospheric/evocative adverbs
    "softly", "gently", "slowly", "quietly", "silently",
    "fiercely", "desperately", "tenderly", "bitterly", "wildly",
}

# --- Neutral counterparts (denotation without resonance) ---
NEUTRAL_COUNTERPARTS: Set[str] = {
    "stay", "remain", "hurt", "pain", "break", "damage",
    "big", "small", "good", "bad", "happy", "sad",
    "walk", "go", "come", "leave", "stop", "start",
    "hot", "cold", "fast", "slow", "hard", "easy",
    "old", "new", "young", "rich", "poor", "strong",
}

# --- Allusion touchstones ---

ALLUSION_PATTERNS: List[str] = [
    # Literary/cultural figures
    r'\b(?:Shakespeare|Homer|Dante|Milton|Joyce|Woolf|Kafka|Borges|'
    r'Faulkner|Morrison|Austen|Dickens|Tolstoy|Dostoevsky|'
    r'Cervantes|Goethe|Poe|Twain|Melville|Conrad)\b',
    # Mythological/classical
    r'\b(?:Prometheus|Sisyphus|Icarus|Odysseus|Achilles|Pandora|'
    r'Cassandra|Narcissus|Oedipus|Atlas|Orpheus|Eurydice|'
    r'Medusa|Minotaur|Sphinx|Phoenix|Chimera|Hydra|Cerberus)\b',
    # Biblical/religious
    r'\b(?:Eden|Babel|Noah|Job|Lazarus|Golgotha|Jericho|'
    r'forbidden fruit|original sin|Tower of Babel|prodigal|'
    r'good Samaritan|David and Goliath|cross to bear)\b',
    # Famous phrases and cultural references
    r'\b(?:road less taken|to be or not to be|sound and fury|'
    r'catch.?22|big brother|brave new world|glass ceiling|'
    r'Pandora.?s box|Trojan horse|Achilles.? heel|Midas touch|'
    r'Sword of Damocles|slippery slope|ivory tower|'
    r'Promethean fire|Sisyphean task)\b',
    # Historical/cultural events
    r'\b(?:Waterloo|Rubicon|Alamo|Dunkirk|Hiroshima|Chernobyl|'
    r'Berlin Wall|iron curtain|holocaust|renaissance)\b',
]

# --- Phonetic patterns for echo detection ---

CONSONANT_GROUPS: Dict[str, str] = {
    # Map initial consonant sounds to groups for alliteration
    'b': 'plosive_labial', 'p': 'plosive_labial',
    'd': 'plosive_alveolar', 't': 'plosive_alveolar',
    'g': 'plosive_velar', 'k': 'plosive_velar', 'c': 'plosive_velar',
    'f': 'fricative_labial', 'v': 'fricative_labial',
    's': 'fricative_alveolar', 'z': 'fricative_alveolar',
    'sh': 'fricative_postalveolar', 'ch': 'fricative_postalveolar',
    'm': 'nasal_labial', 'n': 'nasal_alveolar',
    'l': 'lateral', 'r': 'liquid', 'w': 'glide', 'y': 'glide',
}

VOWEL_GROUPS: Dict[str, str] = {
    'a': 'open', 'e': 'mid_front', 'i': 'high_front',
    'o': 'mid_back', 'u': 'high_back',
}


class WriterResonance:
    """Measure the associative and emotional depth of prose."""

    def __init__(self):
        self.simile_patterns = [re.compile(p, re.IGNORECASE) for p in SIMILE_PATTERNS]
        self.metaphor_linking = [re.compile(p, re.IGNORECASE) for p in METAPHOR_LINKING]
        self.metaphorical_verbs = METAPHORICAL_VERBS
        self.connotative_words = CONNOTATIVE_WORDS
        self.neutral_counterparts = NEUTRAL_COUNTERPARTS
        self.allusion_patterns = [re.compile(p, re.IGNORECASE) for p in ALLUSION_PATTERNS]
        self.consonant_groups = CONSONANT_GROUPS
        self.vowel_groups = VOWEL_GROUPS

    def _tokenize(self, text: str) -> List[str]:
        """Split text into lowercase word tokens."""
        return re.findall(r'\b[a-z]+\b', text.lower())

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        sentences = re.split(r'[.!?]+', text)
        return [s.strip() for s in sentences if s.strip()]

    def _stem_simple(self, word: str) -> str:
        """Simple stemming for verb form matching."""
        if word.endswith('ed') and len(word) > 4:
            return word[:-2]
        if word.endswith('ing') and len(word) > 5:
            return word[:-3]
        if word.endswith('es') and len(word) > 4:
            return word[:-2]
        if word.endswith('s') and len(word) > 3 and not word.endswith(('ss', 'us', 'is')):
            return word[:-1]
        return word

    def _count_content_words(self, tokens: List[str]) -> int:
        """Count content words (nouns, verbs, adjectives, adverbs)."""
        function_words = {
            'the', 'a', 'an', 'is', 'am', 'are', 'was', 'were', 'be',
            'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did',
            'will', 'would', 'shall', 'should', 'may', 'might', 'must',
            'can', 'could', 'i', 'you', 'he', 'she', 'it', 'we', 'they',
            'me', 'him', 'her', 'us', 'them', 'my', 'your', 'his', 'its',
            'our', 'their', 'this', 'that', 'these', 'those', 'and', 'or',
            'but', 'not', 'no', 'yes', 'if', 'then', 'else', 'when',
            'where', 'why', 'how', 'what', 'which', 'who', 'whom',
            'of', 'in', 'on', 'at', 'to', 'for', 'with', 'by', 'from',
            'up', 'out', 'so', 'too', 'very', 'just', 'also', 'even',
        }
        count = sum(1 for t in tokens if t not in function_words and len(t) > 1)
        return max(count, 1)

    def _sentence_has_simile(self, sentence: str) -> bool:
        """Check if sentence contains a simile pattern."""
        for pattern in self.simile_patterns:
            if pattern.search(sentence):
                return True
        return False

    def _sentence_has_metaphor_linking(self, sentence: str) -> bool:
        """Check if sentence contains linking-verb metaphor."""
        for pattern in self.metaphor_linking:
            if pattern.search(sentence):
                return True
        return False

    def _sentence_has_metaphorical_verb(self, sentence: str) -> bool:
        """Check if sentence uses metaphorical verbs."""
        tokens = self._tokenize(sentence)
        for token in tokens:
            stem = self._stem_simple(token)
            if token in self.metaphorical_verbs or stem in self.metaphorical_verbs:
                return True
        return False

    def measure_metaphor_density(self, text: str) -> float:
        """Fraction of sentences containing figurative language."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        count = 0
        for sentence in sentences:
            if (self._sentence_has_simile(sentence) or
                    self._sentence_has_metaphor_linking(sentence) or
                    self._sentence_has_metaphorical_verb(sentence)):
                count += 1
        return count / len(sentences)

    def measure_allusion_rate(self, text: str) -> float:
        """Fraction of sentences referencing cultural touchstones."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        count = 0
        for sentence in sentences:
            for pattern in self.allusion_patterns:
                if pattern.search(sentence):
                    count += 1
                    break
        return count / len(sentences)

    def measure_connotative_word_ratio(self, text: str) -> float:
        """Fraction of content words carrying strong associative weight."""
        tokens = self._tokenize(text)
        if not tokens:
            return 0.0
        content_count = self._count_content_words(tokens)
        connotative_count = 0
        for token in tokens:
            stem = self._stem_simple(token)
            if token in self.connotative_words or stem in self.connotative_words:
                connotative_count += 1
        return min(connotative_count / content_count, 1.0)

    def measure_imagery_density(self, text: str) -> float:
        """Fraction of sentences creating evocative mental images.

        Imagery requires both sensory specificity AND associative/
        symbolic weight. A bare factual statement lacks imagery even
        if it uses concrete nouns.
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        count = 0
        for sentence in sentences:
            tokens = self._tokenize(sentence)
            stemmed = [self._stem_simple(t) for t in tokens]
            has_connotative = any(
                t in self.connotative_words or s in self.connotative_words
                for t, s in zip(tokens, stemmed)
            )
            has_metaphorical = any(
                t in self.metaphorical_verbs or s in self.metaphorical_verbs
                for t, s in zip(tokens, stemmed)
            )
            # Imagery = connotative + metaphorical intersection
            # or presence of both figurative and sensory language
            has_simile = self._sentence_has_simile(sentence)
            if has_connotative and (has_metaphorical or has_simile):
                count += 1
            elif has_connotative and len(tokens) >= 5:
                # Long sentences with connotative words likely create imagery
                count += 1
        return min(count / len(sentences), 1.0)

    def measure_echo_density(self, text: str) -> float:
        """Fraction of consecutive sentence pairs with phonetic/lexical echoes."""
        sentences = self._split_sentences(text)
        if len(sentences) < 2:
            return 0.0
        echo_count = 0
        pair_count = len(sentences) - 1
        for i in range(pair_count):
            tokens_a = self._tokenize(sentences[i])
            tokens_b = self._tokenize(sentences[i + 1])
            if self._has_echo(tokens_a, tokens_b):
                echo_count += 1
        return echo_count / pair_count

    def _has_echo(self, tokens_a: List[str], tokens_b: List[str]) -> bool:
        """Check if two consecutive sentences share phonetic/lexical patterns."""
        if not tokens_a or not tokens_b:
            return False

        # Check alliteration: shared initial consonant groups in content words
        initials_a = self._get_initial_consonants(tokens_a)
        initials_b = self._get_initial_consonants(tokens_b)
        if initials_a and initials_b:
            shared_groups = initials_a & initials_b
            if len(shared_groups) >= 2:
                return True

        # Check repeated content words (deliberate repetition for emphasis)
        content_a = set(t for t in tokens_a if len(t) > 3)
        content_b = set(t for t in tokens_b if len(t) > 3)
        shared = content_a & content_b
        if len(shared) >= 2:
            return True

        # Check anaphora: same opening words
        if len(tokens_a) >= 2 and len(tokens_b) >= 2:
            if tokens_a[0] == tokens_b[0] and tokens_a[1] == tokens_b[1]:
                return True

        return False

    def _get_initial_consonants(self, tokens: List[str]) -> Set[str]:
        """Get set of initial consonant groups for content words."""
        groups = set()
        for token in tokens:
            if len(token) < 2:
                continue
            first = token[0]
            first_two = token[:2]
            if first_two in self.consonant_groups:
                groups.add(self.consonant_groups[first_two])
            elif first in self.consonant_groups:
                groups.add(self.consonant_groups[first])
        return groups

    def compute_resonance_index(
        self,
        metaphor: float,
        allusion: float,
        connotative: float,
        imagery: float,
        echo: float,
    ) -> float:
        """Compute weighted composite score."""
        return (
            metaphor * 0.25
            + allusion * 0.15
            + connotative * 0.30
            + imagery * 0.20
            + echo * 0.10
        )

    def classify(self, index: float) -> str:
        """Classify resonance level."""
        if index >= 0.55:
            return "profound"
        elif index >= 0.40:
            return "evocative"
        elif index >= 0.25:
            return "textured"
        elif index >= 0.10:
            return "surface"
        else:
            return "flat"

    def measure(self, text: str) -> Dict:
        """Measure all resonance metrics for given text."""
        metaphor = self.measure_metaphor_density(text)
        allusion = self.measure_allusion_rate(text)
        connotative = self.measure_connotative_word_ratio(text)
        imagery = self.measure_imagery_density(text)
        echo = self.measure_echo_density(text)
        index = self.compute_resonance_index(
            metaphor, allusion, connotative, imagery, echo
        )
        classification = self.classify(index)

        return {
            "metaphor_density": round(metaphor, 4),
            "allusion_rate": round(allusion, 4),
            "connotative_word_ratio": round(connotative, 4),
            "imagery_density": round(imagery, 4),
            "echo_density": round(echo, 4),
            "resonance_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    # Demo
    profound_text = """The memory haunted her like a ghost she could not
    exorcise. Each morning she crossed the threshold of the old house,
    its shadow stretching toward her like Sisyphus pushing his boulder.
    Time had devoured the garden, leaving only ash and silence. The
    silence echoed, and the echo whispered of doors she had closed
    behind her — doors that would never open again."""

    flat_text = """The meeting started at nine o'clock. There were five
    people in the room. The manager talked about the budget. The numbers
    were presented on a screen. Everyone took notes. The meeting ended
    at ten thirty. They went back to their desks."""

    wr = WriterResonance()

    print("=== Profound Text ===")
    result = wr.measure(profound_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")

    print("\n=== Flat Text ===")
    result = wr.measure(flat_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")
