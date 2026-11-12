#!/usr/bin/env python3
"""writer_metaphor_density — measure the figurative language density of prose.

Figurative language is the gap between what words *say* and what they
*mean*.  A literal sentence transmits information directly; a figurative
one routes meaning through analogy, comparison, exaggeration, or
substitution.  The density of figurative devices in a text determines how
much interpretive work the reader must do — and how much aesthetic
pleasure (or cognitive load) the prose generates.

This is not a quality metric.  High metaphor density is appropriate in
poetry, literary fiction, and persuasive essays; inappropriate in legal
contracts, API documentation, and emergency instructions.  The measure
exists so the writer can *see* whether their figurative choices match
their intent — not to maximize or minimize the score.

This module is orthogonal to the other writer metrics:

- **musicality** tracks *sound patterns* — alliteration, assonance,
  consonance.  Musicality is phonetic; metaphor density is semantic.
  A text can be highly musical yet entirely literal ("The report was
  filed at noon"), or acoustically flat yet dense with metaphor
  ("The quarterly numbers were a slow leak in the hull of investor
  confidence").

- **prose_rhythm** tracks *variation in sentence length and structure*.
  Rhythm is syntactic patterning.  Metaphor operates at the level of
  *word meaning*, not sentence shape.

- **sentence_variety** tracks *structural diversity of sentences* —
  length variance, opening diversity, clause complexity.  Metaphor
  density is independent: every sentence could be structurally
  different yet uniformly literal, or structurally identical yet each
  a different metaphor.

- **elegance** tracks *overall aesthetic quality*.  Metaphor density
  can *contribute* to elegance but does not determine it: clumsy
  metaphors lower elegance while raising density; absence of metaphor
  can be elegant (Hemingway) or inelegant (bureaucratese).

- **voice_consistency** tracks *stability of authorial voice*.  A
  writer can consistently use dense figurative language (Emily
  Dickinson) or consistently avoid it (Strunk & White).

- **concreteness** tracks *proportion of sensory-specific language*.
  Concrete writing names things you can see, touch, or smell.
  Metaphorical writing *maps* one domain onto another.  "The cold
  metal railing" is concrete but literal.  "The railing bit into
  her palm" is metaphorical (the railing does not literally bite).
  A text can be both concrete and metaphorical, neither, or one
  without the other.

Metaphor density asks: **how much of the meaning is carried by
figurative devices rather than literal denotation?**

Dimensions
----------

=========================  =============================================
metric                     meaning
=========================  =============================================
simile_rate                fraction of sentences containing explicit
                           comparison markers (like, as, as...as,
                           than, resembles, akin to, similar to)
metaphor_marker_rate       fraction of sentences containing copula
                           metaphors (is/was/were a/an/the NOUN) or
                           verb metaphors (non-literal verb use
                           detected via selectional preference violation)
personification_density    fraction of sentences where inanimate
                           subjects are paired with human-action verbs
hyperbole_rate             fraction of sentences containing extreme
                           amplification or minimization signals
idiom_density              fraction of sentences containing recognized
                           figurative expressions
=========================  =============================================

From these five dimensions a composite **figurative_index** is computed
as a weighted average and classified:

==============  ============================================================
class           meaning
==============  ============================================================
ornate          index >= 0.50 — figurative language dominates; nearly
                            every sentence carries a non-literal device
rich            0.35 <= index < 0.50 — frequent figurative texture;
                            literary or highly stylized prose
figurative      0.20 <= index < 0.35 — moderate metaphor use; common
                            in quality journalism and essays
literal         0.08 <= index < 0.20 — mostly denotative; occasional
                            figurative touches
denotative      index < 0.08 — no detectable figurative language;
                            typical of technical and legal writing
==============  ============================================================
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

# Simile patterns — explicit comparison markers
SIMILE_PATTERNS = [
    re.compile(r'\blike\b', re.IGNORECASE),
    re.compile(r'\bas\s+\w+\s+as\b', re.IGNORECASE),
    re.compile(r'\bthan\s+(?:a|an|the)\b', re.IGNORECASE),
    re.compile(r'\bresembles?\b', re.IGNORECASE),
    re.compile(r'\bakin\s+to\b', re.IGNORECASE),
    re.compile(r'\bsimilar\s+to\b', re.IGNORECASE),
    re.compile(r'\bcomparable\s+to\b', re.IGNORECASE),
    re.compile(r'\breminds?\s+(?:me|us|one)\s+of\b', re.IGNORECASE),
    re.compile(r'\bas\s+if\b', re.IGNORECASE),
    re.compile(r'\bas\s+though\b', re.IGNORECASE),
]

# Copula metaphor patterns — "X is/was/were a Y" where Y is figurative
COPULA_VERBS = re.compile(r'\b(?:is|are|was|were|became|become|seems?|feels?)\b', re.IGNORECASE)
ARTICLES = re.compile(r'\b(?:a|an|the)\b', re.IGNORECASE)

# Personification — inanimate subjects with human-action verbs
INANIMATE_SUBJECTS = re.compile(
    r'\b(?:the\s+)?(?:sun|moon|wind|rain|storm|cloud|sky|river|sea|ocean|'
    r'mountain|tree|flower|garden|forest|night|morning|evening|dawn|dusk|'
    r'time|memory|thought|idea|silence|darkness|light|shadow|fire|flame|'
    r'wall|door|window|house|building|city|street|road|path|bridge|'
    r'book|page|word|story|song|music|data|code|machine|engine|clock|'
    r'heart|mind|soul|fear|hope|anger|joy|love|hate|truth|lie|'
    r'government|economy|market|company|system|network|internet)\b',
    re.IGNORECASE,
)

HUMAN_ACTION_VERBS = {
    "whisper", "whispers", "whispered", "whispering",
    "sing", "sings", "sang", "sung", "singing",
    "dance", "dances", "danced", "dancing",
    "weep", "weeps", "wept", "weeping",
    "cry", "cries", "cried", "crying",
    "laugh", "laughs", "laughed", "laughing",
    "scream", "screams", "screamed", "screaming",
    "embrace", "embraces", "embraced", "embracing",
    "kiss", "kisses", "kissed", "kissing",
    "think", "thinks", "thought", "thinking",
    "know", "knows", "knew", "known", "knowing",
    "remember", "remembers", "remembered", "remembering",
    "forget", "forgets", "forgot", "forgotten", "forgetting",
    "dream", "dreams", "dreamed", "dreamt", "dreaming",
    "speak", "speaks", "spoke", "spoken", "speaking",
    "tell", "tells", "told", "telling",
    "call", "calls", "called", "calling",
    "reach", "reaches", "reached", "reaching",
    "grasp", "grasps", "grasped", "grasping",
    "hold", "holds", "held", "holding",
    "bite", "bites", "bit", "bitten", "biting",
    "swallow", "swallows", "swallowed", "swallowing",
    "breathe", "breathes", "breathed", "breathing",
    "sleep", "sleeps", "slept", "sleeping",
    "wake", "wakes", "woke", "woken", "waking",
    "die", "dies", "died", "dying",
    "live", "lives", "lived", "living",
    "grow", "grows", "grew", "grown", "growing",
    "bleed", "bleeds", "bled", "bleeding",
    "fly", "flies", "flew", "flown", "flying",
    "run", "runs", "ran", "running",
    "walk", "walks", "walked", "walking",
    "crawl", "crawls", "crawled", "crawling",
    "fight", "fights", "fought", "fighting",
    "protect", "protects", "protected", "protecting",
    "comfort", "comforts", "comforted", "comforting",
    "betray", "betrays", "betrayed", "betraying",
    "promise", "promises", "promised", "promising",
    "threaten", "threatens", "threatened", "threatening",
    "invite", "invites", "invited", "inviting",
    "refuse", "refuses", "refused", "refusing",
    "accept", "accepts", "accepted", "accepting",
    "reject", "rejects", "rejected", "rejecting",
    "offer", "offers", "offered", "offering",
    "steal", "steals", "stole", "stolen", "stealing",
    "devour", "devours", "devoured", "devouring",
    "consume", "consumes", "consumed", "consuming",
    "nurture", "nurtures", "nurtured", "nurturing",
    "cradle", "cradles", "cradled", "cradling",
    "caress", "caresses", "caressed", "caressing",
}

# Hyperbole patterns — extreme amplification or minimization
HYPERBOLE_PATTERNS = [
    re.compile(r'\b(?:never|always|forever|eternally|infinitely)\b', re.IGNORECASE),
    re.compile(r'\b(?:a\s+(?:million|billion|trillion|thousand|hundred))\b', re.IGNORECASE),
    re.compile(r'\b(?:the\s+)?(?:most|least|best|worst|greatest|smallest)\s+(?:\w+\s+)?(?:in|of)\s+(?:the\s+)?(?:world|universe|history|time|all)\b', re.IGNORECASE),
    re.compile(r'\b(?:everyone|nobody|nothing|everything|all\s+the\s+time)\b', re.IGNORECASE),
    re.compile(r'\b(?:literally)\b', re.IGNORECASE),
    re.compile(r'\b(?:absolutely|completely|totally|utterly|entirely)\s+(?:\w+)\b', re.IGNORECASE),
    re.compile(r'\b(?:not\s+a\s+single|without\s+a\s+single)\b', re.IGNORECASE),
    re.compile(r'\b(?:dying\s+to|would\s+die|could\s+die)\b', re.IGNORECASE),
    re.compile(r'\b(?:world\'?s?\s+end|end\s+of\s+the\s+world)\b', re.IGNORECASE),
    re.compile(r'\b(?:tons?\s+of|loads?\s+of|mountains?\s+of|oceans?\s+of)\b', re.IGNORECASE),
]

# Common figurative expressions / idioms
IDIOM_PHRASES: Set[str] = {
    "break the ice", "broke the ice", "breaking the ice", "breaks the ice",
    "hit the road", "spill the beans", "spilled the beans", "spilling the beans", "spilt the beans",
    "burn bridges", "burned bridges", "burning bridges",
    "kick the bucket", "bite the bullet", "break a leg", "cost an arm",
    "cost a fortune", "piece of cake", "once in a blue moon",
    "under the weather", "the ball is in your court", "hit the nail",
    "miss the boat", "let the cat out", "speak of the devil",
    "better late than never", "actions speak louder", "blessing in disguise",
    "blessing in disguise", "every cloud has a silver lining",
    "add fuel to the fire", "add fuel to", "fan the flames",
    "the tip of the iceberg", "tip of the iceberg", "elephant in the room",
    "skeleton in the closet", "storm in a teacup", "calm before the storm",
    "between a rock and a hard place", "out of the frying pan",
    "caught between two stools", "sit on the fence", "see eye to eye",
    "hear it on the grapevine", "kill two birds", "let sleeping dogs lie",
    "method to the madness", "take with a grain of salt",
    "the last straw", "last straw", "final straw",
    "throw in the towel", "throw in the sponge",
    "up in the air", "weather the storm", "bite off more than",
    "get cold feet", "give the benefit of the doubt",
    "in the same boat", "on the same page", "a different kettle of fish",
    "water under the bridge", "cross that bridge",
    "at the end of my rope", "at the end of the rope",
    "back against the wall", "against the wall",
    "pull the plug", "move the goalposts", "raise the bar",
    "low-hanging fruit", "thinking outside the box",
    "reinvent the wheel", "the elephant in the room",
    "connect the dots", "move the needle", "shift the paradigm",
    "open a can of worms", "play devil's advocate",
    "take a back seat", "turn a blind eye", "turn over a new leaf",
    "the writing on the wall", "writing on the wall",
    "a wolf in sheep's clothing", "wolf in sheep's clothing",
    "sour grapes", "the grass is greener", "grass is always greener",
    "a blessing in disguise", "a bitter pill", "cold shoulder",
    "give the cold shoulder", "turn a deaf ear", "bury the hatchet",
    "cry over spilt milk", "cry over spilled milk",
    "cut corners", "a dime a dozen", "the whole nine yards",
    "a fool's errand", "food for thought", "a grain of truth",
    "hit below the belt", "in hot water", "jump on the bandwagon",
    "keep at bay", "a leap in the dark", "a level playing field",
    "the lion's share", "no stone unturned", "on thin ice",
    "a pain in the neck", "painted into a corner",
    "a penny for your thoughts", "the pot calling the kettle black",
    "pull someone's leg", "put all eggs in one basket",
    "read between the lines", "a recipe for disaster",
    "the root of the problem", "salt of the earth",
    "a shot in the dark", "a slippery slope", "a sore point",
    "the spice of life", "a square peg in a round hole",
    "a stitch in time", "a straw that broke the camel's back",
    "sweep under the rug", "take the bull by the horns",
    "a thorn in the side", "through thick and thin",
    "under the radar", "uphill battle", "walk on eggshells",
    "a wolf at the door", "the acid test", "across the board",
    "at the drop of a hat", "bark up the wrong tree",
    "beat around the bush", "burn the midnight oil",
    "castles in the air", "caught red-handed",
    "change horses midstream", "come rain or shine",
    "cook the books", "crocodile tears", "cry wolf",
    "curiosity killed the cat", "dark horse", "day in the sun",
    "dead as a doornail", "devil's advocate",
    "dog eat dog", "don't count your chickens",
    "down to earth", "draw a line in the sand",
    "eat humble pie", "egg on the face", "elbow grease",
    "elephant memory", "feather in the cap", "fight fire with fire",
    "fish out of water", "flea market", "fly by the seat",
    "foot in the door", "from the horse's mouth",
    "full of hot air", "get a taste of your own medicine",
    "get wind of", "go the extra mile", "golden handcuffs",
    "golden parachute", "head in the clouds", "head over heels",
    "heart of gold", "hit the ground running",
    "hold your horses", "in a nutshell", "in the blink of an eye",
    "in the doghouse", "iron out", "ivory tower",
    "keep an eye on", "keep the wolf from the door",
    "kill the golden goose", "knife edge",
    "know the ropes", "larger than life", "learn the ropes",
    "let the genie out", "light at the end of the tunnel",
    "lion's den", "make a mountain out of a molehill",
    "middle of the road", "money to burn",
    "not my cup of tea", "not worth a hill of beans",
    "off the beaten path", "on cloud nine",
    "on the ball", "on the fence", "on the nose",
    "on the rocks", "on the same wavelength",
    "once bitten twice shy", "out of the blue",
    "over the hill", "over the moon", "paper tiger",
    "pass the buck", "pay through the nose",
    "peachy keen", "pig in a poke", "pill to swallow",
    "plant the seed", "poke fun at", "pour cold water on",
    "pull the wool over", "put the cart before the horse",
    "rain cats and dogs", "read the riot act",
    "red tape", "reinvent the wheel", "rest on laurels",
    "rude awakening", "run out of steam", "safe as houses",
    "save for a rainy day", "scrape the barrel",
    "second wind", "see the light", "shed light on",
    "shoot from the hip", "shot across the bow",
    "sick as a dog", "silk purse from a sow's ear",
    "silver bullet", "skeleton key", "skin deep",
    "sleep like a log", "small potatoes", "snake in the grass",
    "snowball's chance", "sow wild oats", "speak volumes",
    "spill the tea", "stake in the ground",
    "stand on ceremony", "steal someone's thunder",
    "stone cold", "storm is brewing", "straight from the horse's mouth",
    "swan song", "take it with a grain of salt",
    "take the cake", "taste of your own medicine",
    "the cream of the crop", "the last straw",
    "the real mccoy", "the whole enchilada",
    "the whole shebang", "thick as thieves",
    "thin end of the wedge", "third time's the charm",
    "tight-lipped", "tip of the tongue", "toe the line",
    "tongue in cheek", "too many cooks", "top dog",
    "touch and go", "under one's belt", "under the gun",
    "up the creek", "waiting in the wings",
    "wake-up call", "walk a tightrope", "wild goose chase",
    "with flying colors", "word of mouth", "zero hour",
}

# Verb metaphor patterns — verbs used outside their typical domain
# These are common metaphorical verb constructions
VERB_METAPHOR_PATTERNS = [
    re.compile(r'\b(?:time|hours?|days?|years?|moments?|minutes?)\s+(?:flew|flies|fly|slipped|slips|slip|raced?|crawled?|dragged?|marched?|crept|creeps)\b', re.IGNORECASE),
    re.compile(r'\b(?:idea|thought|concept|notion|question|fear|doubt|hope)\s+(?:planted|seeded|rooted|grew|grows|bloomed|blossomed|sprouted|germinated|withered|took\s+root)\b', re.IGNORECASE),
    re.compile(r'\b(?:words?|voice|silence|music|sound)\s+(?:cut|cuts|pierced|pierces|pierce|penetrated|penetrates|punched|slapped|hit|struck|landed)\b', re.IGNORECASE),
    re.compile(r'\b(?:heart|soul|spirit|mind)\s+(?:soared|soars|soar|sank|sinks|sink|crumbled|crumbles|shattered|shatters|melted|melts|thawed|thaws)\b', re.IGNORECASE),
    re.compile(r'\b(?:market|economy|prices?|stock|value)\s+(?:crashed?|plummeted?|soared?|climbed?|rose|rose|tumbled?|dove|dived?|skyrocketed?)\b', re.IGNORECASE),
    re.compile(r'\b(?:relationship|friendship|bond|connection)\s+(?:deepened|deepens|strengthened|strengthen|fractured|fractures|broke|breaks|blossomed|withered|grew|grows|flourished)\b', re.IGNORECASE),
    re.compile(r'\b(?:anger|rage|fury|jealousy|envy|guilt|shame|fear)\s+(?:burned|burns|burn|boiled|boils|simmered|simmers|seethed|seethes|consumed|consumes|gnawed|gnaws|ate|eats)\b', re.IGNORECASE),
    re.compile(r'\b(?:opportunity|chance|door|window)\s+(?:opened|opens|close[sd]?|slammed|shut|appeared|appears|vanished|vanishes|knocked|knocks)\b', re.IGNORECASE),
    re.compile(r'\b(?:argument|claim|point|thesis|position)\s+(?:crumbled|crumbles|collapsed|collapses|shattered|shatters|held|holds|stood|stands|fell|falls|weathered|weathers)\b', re.IGNORECASE),
    re.compile(r'\b(?:data|evidence|facts?|results?|findings?)\s+(?:paint|paints|paint|tell|tells|speak|speaks|point|points|suggest|suggests|whisper|whispers|shout|shouts)\b', re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Text processing helpers
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences on '.', '!', '?', preserving content."""
    parts = re.split(r'[.!?]+', text)
    return [p.strip() for p in parts if p.strip()]


def _tokenize_words(text: str) -> List[str]:
    """Split text into words, stripping punctuation."""
    return re.findall(r"[a-zA-Z']+", text)


def _get_subject(sentence: str) -> str:
    """Heuristically extract the grammatical subject of a sentence."""
    words = _tokenize_words(sentence)
    if not words:
        return ""
    # Skip leading articles and adverbs
    skip_words = {"the", "a", "an", "this", "that", "these", "those",
                  "very", "quite", "rather", "somewhat"}
    for w in words:
        if w.lower() not in skip_words:
            return w
    return words[0] if words else ""


def _get_main_verb(sentence: str) -> str:
    """Heuristically extract the main verb of a sentence."""
    words = _tokenize_words(sentence)
    if len(words) < 2:
        return ""
    # Skip leading articles/determiners, then skip the subject word,
    # then skip auxiliaries, then return the first remaining word.
    articles = {"the", "a", "an", "this", "that", "these", "those"}
    auxiliaries = {"is", "are", "was", "were", "has", "have", "had",
                   "will", "would", "shall", "should", "can", "could",
                   "may", "might", "must", "do", "does", "did",
                   "been", "being", "be", "am"}
    # Phase 1: skip leading articles
    idx = 0
    while idx < len(words) and words[idx].lower() in articles:
        idx += 1
    # Phase 2: skip the subject word
    if idx < len(words):
        idx += 1
    # Phase 3: skip auxiliaries, return first non-auxiliary
    while idx < len(words):
        if words[idx].lower() in auxiliaries:
            idx += 1
        else:
            return words[idx]
    return ""


# ---------------------------------------------------------------------------
# Threshold constants for export / testing
# ---------------------------------------------------------------------------

SIMILE_MIN_WORDS = 2
HYPERBOLE_MIN_WORDS = 2
IDIOM_MIN_WORDS = 3


# ---------------------------------------------------------------------------
# WriterMetaphorDensity class
# ---------------------------------------------------------------------------


class WriterMetaphorDensity:
    """Measure the figurative language density of prose."""

    def __init__(self):
        self.simile_patterns = list(SIMILE_PATTERNS)
        self.hyperbole_patterns = list(HYPERBOLE_PATTERNS)
        self.idiom_phrases = set(IDIOM_PHRASES)
        self.verb_metaphor_patterns = list(VERB_METAPHOR_PATTERNS)
        self.human_action_verbs = set(HUMAN_ACTION_VERBS)

    def _split_sentences(self, text: str) -> List[str]:
        return _split_sentences(text)

    def _tokenize(self, text: str) -> List[str]:
        return _tokenize_words(text)

    def measure_simile_rate(self, text: str) -> float:
        """Fraction of sentences containing explicit simile markers."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        simile_count = 0
        for sent in sentences:
            words = self._tokenize(sent)
            if len(words) < SIMILE_MIN_WORDS:
                continue
            for pattern in self.simile_patterns:
                if pattern.search(sent):
                    simile_count += 1
                    break
        return simile_count / len(sentences)

    def measure_metaphor_marker_rate(self, text: str) -> float:
        """Fraction of sentences containing copula or verb metaphors."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        metaphor_count = 0
        for sent in sentences:
            words = self._tokenize(sent)
            if len(words) < 3:
                continue
            # Check copula metaphor: X is/was/were a Y
            if COPULA_VERBS.search(sent) and ARTICLES.search(sent):
                # Look for abstract-to-concrete or concrete-to-abstract mapping
                if self._has_copula_metaphor(sent):
                    metaphor_count += 1
                    continue
            # Check verb metaphor patterns
            for pattern in self.verb_metaphor_patterns:
                if pattern.search(sent):
                    metaphor_count += 1
                    break
        return metaphor_count / len(sentences)

    def _has_copula_metaphor(self, sentence: str) -> bool:
        """Detect copula metaphors — 'X is a Y' where Y is figurative."""
        # Look for patterns like "is/was/were a/an/the NOUN"
        # where the noun is abstract or the mapping is non-literal
        copula_metaphor_patterns = [
            re.compile(r'\b(?:is|are|was|were)\s+(?:a|an)\s+\w+', re.IGNORECASE),
            re.compile(r'\b(?:is|are|was|were)\s+the\s+\w+', re.IGNORECASE),
        ]
        # Count as metaphor if the sentence has a copula + article + noun
        # AND the subject is different domain from the predicate noun
        # Heuristic: flag any copula + article construction as potential metaphor
        for pattern in copula_metaphor_patterns:
            match = pattern.search(sentence)
            if match:
                # Exclude common literal constructions
                literal_exclusions = re.compile(
                    r'\b(?:is|are|was|were)\s+(?:a|an|the)\s+'
                    r'(?:member|part|type|kind|sort|form|example|'
                    r'result|product|feature|aspect|element|component|'
                    r'number|amount|case|instance|fact|question|issue|'
                    r'person|man|woman|child|thing|object|item|one|'
                    r'bit|lot|few|many|couple|dozen|group|set|list|'
                    r'problem|solution|answer|reason|cause|effect)\b',
                    re.IGNORECASE,
                )
                if not literal_exclusions.search(sentence):
                    return True
        return False

    def measure_personification_density(self, text: str) -> float:
        """Fraction of sentences where inanimate subjects get human verbs."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        personification_count = 0
        for sent in sentences:
            if self._is_personification(sent):
                personification_count += 1
        return personification_count / len(sentences)

    def _is_personification(self, sentence: str) -> bool:
        """Check if a sentence contains personification."""
        subject = _get_subject(sentence)
        if not subject:
            return False
        # Check if the subject matches inanimate subjects
        if not INANIMATE_SUBJECTS.search(sentence):
            return False
        # Check if the sentence contains a human-action verb
        words = self._tokenize(sentence)
        for word in words:
            if word.lower() in self.human_action_verbs:
                # Make sure the verb isn't in a subordinate clause
                # about a human — simple heuristic: the verb appears
                # within the first 10 words
                verb_idx = None
                for i, w in enumerate(words):
                    if w.lower() == word.lower():
                        verb_idx = i
                        break
                if verb_idx is not None and verb_idx < 10:
                    return True
        return False

    def measure_hyperbole_rate(self, text: str) -> float:
        """Fraction of sentences containing hyperbolic expressions."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        hyperbole_count = 0
        for sent in sentences:
            words = self._tokenize(sent)
            if len(words) < HYPERBOLE_MIN_WORDS:
                continue
            for pattern in self.hyperbole_patterns:
                if pattern.search(sent):
                    hyperbole_count += 1
                    break
        return hyperbole_count / len(sentences)

    def measure_idiom_density(self, text: str) -> float:
        """Fraction of sentences containing recognized idiomatic expressions."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        idiom_count = 0
        for sent in sentences:
            sent_lower = sent.lower()
            for idiom in self.idiom_phrases:
                if idiom in sent_lower:
                    idiom_count += 1
                    break
        return idiom_count / len(sentences)

    def compute_figurative_index(
        self,
        simile: float,
        metaphor: float,
        personification: float,
        hyperbole: float,
        idiom: float,
    ) -> float:
        """Weighted composite of the five sub-metrics."""
        return (
            simile * 0.20
            + metaphor * 0.30
            + personification * 0.20
            + hyperbole * 0.15
            + idiom * 0.15
        )

    def classify(self, index: float) -> str:
        """Classify the figurative index into a named category."""
        if index >= 0.50:
            return "ornate"
        elif index >= 0.35:
            return "rich"
        elif index >= 0.20:
            return "figurative"
        elif index >= 0.08:
            return "literal"
        else:
            return "denotative"

    def measure(self, text: str) -> Dict[str, Any]:
        """Compute all metrics and return a summary dict."""
        simile = self.measure_simile_rate(text)
        metaphor = self.measure_metaphor_marker_rate(text)
        personification = self.measure_personification_density(text)
        hyperbole = self.measure_hyperbole_rate(text)
        idiom = self.measure_idiom_density(text)
        index = self.compute_figurative_index(
            simile, metaphor, personification, hyperbole, idiom
        )
        classification = self.classify(index)

        return {
            "simile_rate": round(simile, 4),
            "metaphor_marker_rate": round(metaphor, 4),
            "personification_density": round(personification, 4),
            "hyperbole_rate": round(hyperbole, 4),
            "idiom_density": round(idiom, 4),
            "figurative_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    ornate_text = """Time flew like an arrow through the heart of the
    afternoon. The wind whispered secrets to the trembling leaves while
    the sun danced across the meadow like a golden child at play. Her
    words were a dagger, each syllable a shard of glass cutting deeper
    than the last. The city was a beast that never slept, its streets
    veins pumping millions of souls through concrete arteries. Hope was
    a fragile seed planted in the cracked earth of despair, and love was
    the rain that coaxed it into bloom. The market crashed like a wave
    against the cliffs of investor confidence, and fear consumed everything
    in its path. It was literally the end of the world as they knew it,
    and nothing would ever be the same."""

    denotative_text = """The quarterly report was submitted on March
    fifteenth. Revenue increased by twelve percent compared to the
    previous quarter. The team completed all assigned tasks within
    the allocated budget. Customer satisfaction scores remained stable
    at four point two out of five. The next review meeting is scheduled
    for April third at ten in the morning. Please submit your agenda
    items by March twenty eighth."""

    wmd = WriterMetaphorDensity()

    print("=== Ornate Text ===")
    result = wmd.measure(ornate_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")

    print("\n=== Denotative Text ===")
    result = wmd.measure(denotative_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")
