#!/usr/bin/env python3
"""writer_concreteness — measure the sensory grounding of prose.

Concreteness tracks the balance between *concrete, sensory language* and
*abstract, conceptual language*.  Concrete prose anchors ideas in
physical reality — what can be seen, heard, touched, tasted, smelled.
Abstract prose deals with concepts, qualities, and relationships
without sensory reference.

This module is orthogonal to the other writer metrics:

- **specificity** tracks *precision of detail*.  Specific prose names
  the exact model, the exact number, the exact place.  Concreteness
  measures *sensory mode* — whether language invokes physical
  experience.  A text can be specific ("the 2023 Toyota Camry LE")
  but not concrete (no sensory qualities mentioned), or concrete
  ("the rough bark scraped her palm") but not specific (which tree?).

- **density** tracks *information per unit*.  Dense prose packs many
  ideas into few words.  Concreteness measures *type* of language,
  not *amount* of information.  A concrete sentence can be dense
  ("salt-stained boots, split soles, mud caked in the welts") or
  sparse ("she wore boots").

- **elegance** tracks *aesthetic quality*.  Elegant prose has rhythm,
  balance, and grace.  Concreteness measures *sensory grounding*,
  not beauty.  A text can be concrete and clumsy ("the big red ball
  rolled down the green hill slowly") or abstract and elegant
  ("justice requires patience").

- **vocabulary_richness** tracks *lexical diversity*.  Rich vocabulary
  uses many different words.  Concreteness measures *what kind* of
  words — sensory vs conceptual — not how varied they are.

Concreteness asks: **does the prose root ideas in physical experience,
or float in abstraction?**

Dimensions
----------

===========================  ===========================================
metric                       meaning
===========================  ===========================================
sensory_word_ratio           fraction of content words (nouns, verbs,
                             adjectives, adverbs) that invoke one of
                             the five senses: visual (red, bright,
                             shadow, gleam), auditory (crash, whisper,
                             rumble, shrill), tactile (rough, smooth,
                             hot, gritty), gustatory (sweet, bitter,
                             sour, salty), olfactory (fragrant, acrid,
                             musty, pungent); word list adapted from
                             Brysbaert et al. (2014) concreteness norms
concrete_noun_ratio          fraction of nouns that denote physical
                             objects (table, hand, tree, water) vs
                             abstract concepts (idea, justice, freedom,
                             democracy); uses a curated noun list with
                             manual review of ambiguous cases
action_verb_ratio            fraction of verbs that denote physical
                             actions (run, grab, throw, build) vs
                             stative/linking verbs (is, seem, become,
                             have) or mental verbs (think, believe,
                             consider); physical actions ground the
                             reader in embodied experience
spatial_marker_density       fraction of sentences containing spatial
                             prepositions or adverbs (above, beneath,
                             between, across, inside, beyond, nearby)
                             that locate entities in physical space;
                             spatial language creates mental models
embodied_language_rate       fraction of sentences containing body-
                             related expressions: body part nouns
                             (hand, eye, chest, shoulder), physical
                             sensation verbs (ache, shiver, tense,
                             relax), or proprioceptive terms (balance,
                             weight, pressure, grip); embodiment
                             creates visceral reader engagement
===========================  ===========================================

Concreteness classes

====================  ==================================================
class                 meaning
====================  ==================================================
vivid                 >= 0.60 composite score; prose is richly sensory,
                      grounded in physical experience, creates mental
                      images; appropriate for narrative, creative
                      nonfiction, and evocative description
concrete              0.45–0.59 composite score; prose balances sensory
                      language with conceptual content; ideas are
                      anchored in physical examples but not every
                      sentence invokes sensation
balanced              0.35–0.44 composite score; prose mixes concrete
                      and abstract language roughly equally; typical
                      of well-written expository prose that uses
                      examples to illustrate concepts
abstract              0.20–0.34 composite score; prose is primarily
                      conceptual, with minimal sensory grounding;
                      appropriate for philosophy, theory, and some
                      technical writing, but risks feeling detached
ethereal              < 0.20 composite score; prose is almost entirely
                      abstract, with no physical anchoring; may be
                      appropriate for pure mathematics or formal
                      logic, but feels disembodied elsewhere
====================  ==================================================

Composite score
---------------

The composite concreteness_index is a weighted average::

    concreteness_index = (
        sensory_word_ratio     * 0.30 +
        concrete_noun_ratio    * 0.25 +
        action_verb_ratio      * 0.20 +
        spatial_marker_density * 0.15 +
        embodied_language_rate * 0.10
    )

Weights reflect diagnostic importance: sensory language (0.30) is the
most direct measure of concreteness, concrete nouns (0.25) anchor
ideas in physical objects, action verbs (0.20) create dynamic rather
than static prose, spatial markers (0.15) locate ideas in physical
space, and embodied language (0.10) creates visceral engagement.

Usage
-----

    from iamai.writer_concreteness import WriterConcreteness

    wc = WriterConcreteness()
    result = wc.measure(text)
    print(result["concreteness_index"])   # 0.0–1.0
    print(result["classification"])        # vivid|concrete|balanced|abstract|ethereal
    print(result["sensory_word_ratio"])    # 0.0–1.0
"""

import re
from typing import Dict, List, Set


# Sensory words adapted from Brysbaert et al. (2014) concreteness norms
# and expanded with domain-specific terms
SENSORY_WORDS: Set[str] = {
    # Visual
    "red", "blue", "green", "yellow", "black", "white", "gray", "grey",
    "bright", "dark", "dim", "bright", "shadow", "light", "gleam", "glint",
    "sparkle", "shimmer", "glow", "flash", "color", "colour", "hue", "tint",
    "shade", "pale", "vivid", "dull", "glossy", "matte", "translucent",
    "opaque", "transparent", "blurry", "sharp", "clear", "visible",
    # Auditory
    "loud", "quiet", "soft", "shrill", "deep", "high", "low", "crash",
    "bang", "whisper", "murmur", "rumble", "thunder", "click", "clack",
    "snap", "crackle", "hiss", "buzz", "hum", "ring", "chime", "echo",
    "sound", "noise", "silence", "voice", "shout", "scream", "cry",
    "laugh", "giggle", "sigh", "gasp", "breath",
    # Tactile
    "rough", "smooth", "soft", "hard", "hot", "cold", "warm", "cool",
    "wet", "dry", "gritty", "silky", "fuzzy", "prickly", "sharp", "dull",
    "sticky", "slippery", "greasy", "oily", "powdery", "crumbly", "solid",
    "liquid", "thick", "thin", "heavy", "light", "weight", "pressure",
    "texture", "surface", "touch", "feel", "stroke", "rub", "scratch",
    # Gustatory
    "sweet", "sour", "bitter", "salty", "savory", "bland", "spicy", "hot",
    "tangy", "tart", "sharp", "mild", "rich", "taste", "flavor", "flavour",
    "tongue", "mouth", "tongue", "palate",
    # Olfactory
    "fragrant", "aromatic", "pungent", "acrid", "musty", "stale", "fresh",
    "sweet", "sour", "sharp", "heavy", "light", "smell", "scent", "odor",
    "odour", "stink", "perfume", "aroma", "bouquet", "nose",
}

CONCRETE_NOUNS: Set[str] = {
    # Physical objects
    "table", "chair", "desk", "bed", "door", "window", "wall", "floor",
    "ceiling", "roof", "room", "house", "building", "street", "road",
    "car", "bus", "train", "plane", "boat", "ship", "bike", "bicycle",
    "tree", "flower", "grass", "leaf", "branch", "root", "seed", "fruit",
    "vegetable", "meat", "bread", "water", "milk", "coffee", "tea",
    "hand", "foot", "arm", "leg", "head", "eye", "ear", "nose", "mouth",
    "hair", "skin", "bone", "muscle", "heart", "brain", "lung",
    "book", "paper", "pen", "pencil", "phone", "computer", "screen",
    "cup", "glass", "plate", "bowl", "fork", "knife", "spoon",
    "shirt", "pants", "dress", "shoe", "hat", "coat", "jacket",
    "dog", "cat", "bird", "fish", "horse", "cow", "pig", "sheep",
    "rock", "stone", "sand", "dirt", "mud", "snow", "ice", "rain",
    "sun", "moon", "star", "cloud", "sky", "ocean", "sea", "river",
    "lake", "mountain", "hill", "valley", "forest", "field", "garden",
}

ABSTRACT_NOUNS: Set[str] = {
    "idea", "concept", "notion", "thought", "belief", "opinion", "view",
    "freedom", "liberty", "justice", "equality", "democracy", "rights",
    "love", "hate", "anger", "fear", "joy", "sadness", "happiness",
    "truth", "falsehood", "lie", "honesty", "integrity", "virtue",
    "beauty", "ugliness", "goodness", "evil", "morality", "ethics",
    "knowledge", "wisdom", "intelligence", "understanding", "insight",
    "time", "space", "energy", "force", "power", "strength", "weakness",
    "success", "failure", "victory", "defeat", "progress", "decline",
    "change", "growth", "development", "evolution", "revolution",
    "problem", "solution", "question", "answer", "issue", "matter",
    "system", "process", "method", "approach", "strategy", "tactic",
    "quality", "quantity", "amount", "degree", "extent", "level",
    "relationship", "connection", "difference", "similarity", "contrast",
    "cause", "effect", "result", "outcome", "consequence", "impact",
}

ACTION_VERBS: Set[str] = {
    "run", "walk", "jump", "climb", "fall", "rise", "lift", "carry",
    "push", "pull", "throw", "catch", "grab", "hold", "drop", "release",
    "hit", "strike", "kick", "punch", "slap", "bite", "chew", "swallow",
    "eat", "drink", "cook", "bake", "boil", "fry", "cut", "slice",
    "write", "draw", "paint", "build", "construct", "create", "make",
    "break", "smash", "crack", "split", "tear", "rip", "shred",
    "open", "close", "lock", "unlock", "turn", "twist", "bend", "fold",
    "sit", "stand", "lie", "kneel", "crouch", "lean", "stretch", "reach",
    "look", "see", "watch", "stare", "glance", "peek", "blink",
    "listen", "hear", "speak", "talk", "say", "tell", "ask", "answer",
    "shout", "whisper", "murmur", "mutter", "call", "cry", "laugh",
}

STATIVE_VERBS: Set[str] = {
    "is", "am", "are", "was", "were", "be", "been", "being",
    "seem", "appear", "look", "sound", "feel", "taste", "smell",
    "become", "get", "grow", "turn", "go", "come",
    "have", "has", "had", "own", "possess", "hold", "contain",
    "know", "believe", "think", "understand", "remember", "forget",
    "want", "need", "desire", "wish", "hope", "expect",
    "like", "love", "hate", "dislike", "prefer", "enjoy",
    "mean", "signify", "represent", "stand", "equal",
}

SPATIAL_MARKERS: Set[str] = {
    "above", "below", "beneath", "under", "over", "across", "through",
    "between", "among", "around", "about", "near", "nearby", "far",
    "inside", "outside", "within", "without", "beside", "besides",
    "beyond", "behind", "before", "after", "front", "back", "side",
    "top", "bottom", "edge", "corner", "center", "centre", "middle",
    "left", "right", "up", "down", "here", "there", "everywhere",
    "nowhere", "somewhere", "anywhere", "inward", "outward", "onward",
}

BODY_PARTS: Set[str] = {
    "hand", "hands", "foot", "feet", "arm", "arms", "leg", "legs",
    "head", "face", "eye", "eyes", "ear", "ears", "nose", "mouth",
    "lip", "lips", "tooth", "teeth", "tongue", "throat", "neck",
    "shoulder", "shoulders", "chest", "back", "spine", "stomach",
    "heart", "lung", "lungs", "brain", "skull", "bone", "bones",
    "muscle", "muscles", "skin", "hair", "finger", "fingers",
    "thumb", "toe", "toes", "knee", "knees", "elbow", "elbows",
    "wrist", "wrists", "ankle", "ankles", "hip", "hips", "waist",
}

EMBODIED_VERBS: Set[str] = {
    "ache", "pain", "hurt", "throb", "sting", "burn", "itch", "tickle",
    "shiver", "tremble", "shake", "quake", "vibrate", "pulse", "beat",
    "tense", "relax", "tighten", "loosen", "stiffen", "soften",
    "breathe", "inhale", "exhale", "pant", "gasp", "choke", "cough",
    "sweat", "blush", "flush", "pale", "freeze", "melt", "boil",
}


class WriterConcreteness:
    """Measure the sensory grounding of prose."""

    def __init__(self):
        self.sensory_words = SENSORY_WORDS
        self.concrete_nouns = CONCRETE_NOUNS
        self.abstract_nouns = ABSTRACT_NOUNS
        self.action_verbs = ACTION_VERBS
        self.stative_verbs = STATIVE_VERBS
        self.spatial_markers = SPATIAL_MARKERS
        self.body_parts = BODY_PARTS
        self.embodied_verbs = EMBODIED_VERBS

    def _tokenize(self, text: str) -> List[str]:
        """Split text into lowercase word tokens."""
        return re.findall(r'\b[a-z]+\b', text.lower())

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        sentences = re.split(r'[.!?]+', text)
        return [s.strip() for s in sentences if s.strip()]

    def _get_pos_simple(self, token: str) -> str:
        """Simple POS tagger for demo purposes."""
        # This is a simplified heuristic; production code should use
        # spaCy or NLTK for accurate POS tagging
        # Check more specific endings first
        if token.endswith(('ful', 'less', 'ous', 'ive', 'able', 'ible')):
            return 'ADJ'
        if token.endswith(('ing', 'ed', 'es')) and len(token) > 4:
            return 'VERB'
        if token.endswith('s') and len(token) > 4 and not token.endswith(('ss', 'us', 'is')):
            return 'VERB'
        if token.endswith(('ly',)):
            return 'ADV'
        if token.endswith(('tion', 'ment', 'ness', 'ity', 'ence', 'ance')):
            return 'NOUN'
        return 'OTHER'

    def _count_content_words(self, tokens: List[str]) -> int:
        """Count content words (nouns, verbs, adjectives, adverbs)."""
        count = 0
        for token in tokens:
            pos = self._get_pos_simple(token)
            if pos in ('NOUN', 'VERB', 'ADJ', 'ADV'):
                count += 1
        # Fallback: if no POS detected, count all non-function words
        if count == 0:
            function_words = {
                'the', 'a', 'an', 'is', 'am', 'are', 'was', 'were', 'be',
                'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did',
                'will', 'would', 'shall', 'should', 'may', 'might', 'must',
                'can', 'could', 'i', 'you', 'he', 'she', 'it', 'we', 'they',
                'me', 'him', 'her', 'us', 'them', 'my', 'your', 'his', 'its',
                'our', 'their', 'this', 'that', 'these', 'those', 'and', 'or',
                'but', 'not', 'no', 'yes', 'if', 'then', 'else', 'when',
                'where', 'why', 'how', 'what', 'which', 'who', 'whom',
            }
            count = sum(1 for t in tokens if t not in function_words)
        return max(count, 1)

    def _count_nouns(self, tokens: List[str]) -> int:
        """Count nouns in token list."""
        count = 0
        for token in tokens:
            if token in self.concrete_nouns or token in self.abstract_nouns:
                count += 1
            elif self._get_pos_simple(token) == 'NOUN':
                count += 1
        return max(count, 1)

    def _count_verbs(self, tokens: List[str]) -> int:
        """Count verbs in token list."""
        count = 0
        for token in tokens:
            if token in self.action_verbs or token in self.stative_verbs:
                count += 1
            elif self._get_pos_simple(token) == 'VERB':
                count += 1
        return max(count, 1)

    def _stem_simple(self, word: str) -> str:
        """Simple stemming for verb form matching."""
        # Remove common suffixes to get base form
        if word.endswith('ed') and len(word) > 4:
            return word[:-2]
        if word.endswith('ing') and len(word) > 5:
            return word[:-3]
        if word.endswith('es') and len(word) > 4:
            return word[:-2]
        if word.endswith('s') and len(word) > 3 and not word.endswith(('ss', 'us', 'is')):
            return word[:-1]
        return word

    def measure_sensory_word_ratio(self, text: str) -> float:
        """Fraction of content words that invoke senses."""
        tokens = self._tokenize(text)
        if not tokens:
            return 0.0
        # Count content words (POS-based or known sensory/concrete/abstract/action words)
        content_count = 0
        sensory_count = 0
        for t in tokens:
            pos = self._get_pos_simple(t)
            is_content = (pos in ('NOUN', 'VERB', 'ADJ', 'ADV') or 
                         t in self.sensory_words or
                         t in self.concrete_nouns or
                         t in self.abstract_nouns or
                         t in self.action_verbs or
                         t in self.stative_verbs)
            if is_content:
                content_count += 1
                if t in self.sensory_words:
                    sensory_count += 1
        return min(sensory_count / content_count, 1.0) if content_count > 0 else 0.0

    def measure_concrete_noun_ratio(self, text: str) -> float:
        """Fraction of nouns that are concrete vs abstract."""
        tokens = self._tokenize(text)
        noun_count = self._count_nouns(tokens)
        concrete_count = sum(1 for t in tokens if t in self.concrete_nouns)
        return concrete_count / noun_count if noun_count > 0 else 0.0

    def measure_action_verb_ratio(self, text: str) -> float:
        """Fraction of verbs that are physical actions."""
        tokens = self._tokenize(text)
        if not tokens:
            return 0.0
        verb_count = self._count_verbs(tokens)
        action_count = 0
        for t in tokens:
            stem = self._stem_simple(t)
            if t in self.action_verbs or stem in self.action_verbs:
                action_count += 1
        return min(action_count / verb_count, 1.0) if verb_count > 0 else 0.0

    def measure_spatial_marker_density(self, text: str) -> float:
        """Fraction of sentences containing spatial markers."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        count = 0
        for sentence in sentences:
            tokens = set(self._tokenize(sentence))
            if tokens & self.spatial_markers:
                count += 1
        return count / len(sentences)

    def measure_embodied_language_rate(self, text: str) -> float:
        """Fraction of sentences containing body-related expressions."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        count = 0
        for sentence in sentences:
            tokens = self._tokenize(sentence)
            token_set = set(tokens)
            # Check both original and stemmed forms
            stemmed_set = set(self._stem_simple(t) for t in tokens)
            if (token_set & self.body_parts or 
                token_set & self.embodied_verbs or
                stemmed_set & self.embodied_verbs):
                count += 1
        return count / len(sentences)

    def compute_concreteness_index(
        self,
        sensory: float,
        concrete_noun: float,
        action_verb: float,
        spatial: float,
        embodied: float,
    ) -> float:
        """Compute weighted composite score."""
        return (
            sensory * 0.30
            + concrete_noun * 0.25
            + action_verb * 0.20
            + spatial * 0.15
            + embodied * 0.10
        )

    def classify(self, index: float) -> str:
        """Classify concreteness level."""
        if index >= 0.60:
            return "vivid"
        elif index >= 0.45:
            return "concrete"
        elif index >= 0.35:
            return "balanced"
        elif index >= 0.20:
            return "abstract"
        else:
            return "ethereal"

    def measure(self, text: str) -> Dict:
        """Measure all concreteness metrics for given text."""
        sensory = self.measure_sensory_word_ratio(text)
        concrete_noun = self.measure_concrete_noun_ratio(text)
        action_verb = self.measure_action_verb_ratio(text)
        spatial = self.measure_spatial_marker_density(text)
        embodied = self.measure_embodied_language_rate(text)
        index = self.compute_concreteness_index(
            sensory, concrete_noun, action_verb, spatial, embodied
        )
        classification = self.classify(index)

        return {
            "sensory_word_ratio": round(sensory, 4),
            "concrete_noun_ratio": round(concrete_noun, 4),
            "action_verb_ratio": round(action_verb, 4),
            "spatial_marker_density": round(spatial, 4),
            "embodied_language_rate": round(embodied, 4),
            "concreteness_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    # Demo
    vivid_text = """The rough bark scraped her palm as she climbed.
    Below, the river rushed over smooth stones, cold and clear.
    She could smell the pine needles, sharp and fragrant in the
    morning air. Her muscles ached, but the view from the ridge
    made her heart beat faster."""

    abstract_text = """The concept of freedom requires understanding
    of individual rights and social responsibility. Democracy
    depends on knowledge and participation. Justice must balance
    equality with liberty. Truth emerges through reason and
    evidence."""

    wc = WriterConcreteness()

    print("=== Vivid Text ===")
    result = wc.measure(vivid_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")

    print("\n=== Abstract Text ===")
    result = wc.measure(abstract_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")
