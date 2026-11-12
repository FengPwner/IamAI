#!/usr/bin/env python3
"""writer_formality — measure the formality register of prose.

Formality tracks where prose falls on the spectrum from *casual,
conversational language* to *formal, academic, or professional
register*.  Formal prose follows conventions of written discourse:
complete sentences, Latinate vocabulary, passive constructions,
impersonal address.  Informal prose borrows from spoken language:
contractions, slang, personal pronouns, short sentences, colloquial
idioms.

This module is orthogonal to the other writer metrics:

- **concreteness** tracks *sensory grounding*.  Concrete prose can
  be formal ("the defendant sustained lacerations to the dorsal
  surface") or casual ("he cut his back real bad").  Formality
  measures *register*, not *sensory mode*.

- **elegance** tracks *aesthetic quality*.  Elegant prose can be
  conversational ("she was the kind of person who left better rooms
  than she entered") or stiff ("her departure was invariably
  accompanied by a discernible improvement in ambient conditions").
  Formality measures *convention adherence*, not *grace*.

- **conviction** tracks *assertiveness*.  Formal prose can hedge
  constantly ("it may perhaps be argued that...") or assert firmly
  ("the evidence demonstrates that...").  Formality measures
  *linguistic register*, not *rhetorical force*.

- **readability** tracks *comprehension difficulty*.  Readability
  correlates with formality but they are not identical: a casual
  text can be hard to read (slang, dialect) and a formal text can
  be crystal clear (well-structured legal brief).

- **vocabulary_richness** tracks *lexical diversity*.  A formal
  text may use the same Latinate words repeatedly; an informal
  text may code-switch through many registers.  Richness measures
  *variety*, formality measures *register level*.

Formality asks: **does the prose follow conventions of formal
written discourse, or does it borrow from casual spoken language?**

Dimensions
----------

===========================  ===========================================
metric                       meaning
===========================  ===========================================
contraction_rate             fraction of verb+negation or verb+pronoun
                             forms that use contracted spelling (don't,
                             can't, won't, I'm, you're, we've, it's,
                             they'd, she'll, that's, there's, who's,
                             what's, here's, how's, where's); the most
                             reliable single predictor of informal
                             register in English prose
informal_pronoun_rate        density of first- and second-person
                             pronouns (I, me, my, mine, myself, we, us,
                             our, ours, ourselves, you, your, yours,
                             yourself, yourselves) per sentence; formal
                             writing typically avoids direct personal
                             address and first-person narration
colloquial_density           fraction of tokens recognized as informal,
                             slang, or colloquial expressions from a
                             curated list of 200+ items: abbreviations
                             (gonna, wanna, gotta, kinda, sorta, dunno,
                             lemme, gimme, cuz, tho, prolly, def,
                             legit, sus), discourse markers (like,
                             basically, literally, actually, honestly,
                             seriously, whatever, anyway, anyways),
                             intensifiers (super, really, totally,
                             crazy, mad, hella, deadass, fr, ong),
                             evaluative terms (cool, awesome, neat,
                             neat-o, groovy, nifty, sick, dope, fire,
                             mid, sus, based, cringe, cringey)
passive_voice_ratio          fraction of verb phrases that use passive
                             construction (be + past participle: was
                             written, were observed, has been noted,
                             will be discussed); formal and academic
                             prose uses passive voice to shift focus
                             from agent to action
latinate_vocabulary_ratio    fraction of tokens with Latinate or
                             Greco-Latin morphological markers:
                             suffixes -tion/-sion/-ation/-ition,
                             -ment/-ence/-ance/-ency/-ancy,
                             -ity/-osity, -al/-ial, -ous/-ious/-eous,
                             -ive/-ative/-itive, -ize/-ise,
                             prefixes con-/com-/dis-/pre-/re-/pro-/
                             sub-/inter-/trans-/circum-; Latinate
                             vocabulary is the hallmark of formal
                             English register
formality_hedge_rate         fraction of sentences containing hedging
                             or qualification expressions common in
                             formal academic prose: approximately,
                             arguably, arguably, presumably,
                             ostensibly, ostensibly, purportedly,
                             seemingly, to some extent, it appears,
                             it seems, it could be argued, it may be,
                             it might be, it is possible, it is
                             likely, tends to, appears to; hedging
                             signals awareness of epistemic limits
                             and is more common in formal than
                             casual registers
===========================  ===========================================

Formality classes

====================  ==================================================
class                 meaning
====================  ==================================================
academic              >= 0.75 composite score; prose follows strict
                      conventions of academic or legal writing, with
                      Latinate vocabulary, passive constructions,
                      epistemic hedging, and no contractions or
                      colloquialisms; appropriate for journal articles,
                      legal briefs, and formal reports
formal                0.55–0.74 composite score; prose is professional
                      and polished, with elevated vocabulary and
                      complex sentence structure, but may include
                      occasional first-person reference or mild
                      informality; appropriate for business
                      communications, op-eds, and quality journalism
conversational        0.35–0.54 composite score; prose is accessible
                      and natural, mixing formal and informal elements;
                      appropriate for blog posts, personal essays,
                      and educational content that aims to be
                      approachable
casual                0.20–0.34 composite score; prose is relaxed and
                      colloquial, with contractions, personal pronouns,
                      and conversational idioms; appropriate for
                      social media, casual correspondence, and
                      dialogue in fiction
colloquial            < 0.20 composite score; prose heavily borrows
                      from spoken language, with slang, abbreviations,
                      and grammatical shortcuts; appropriate for
                      texting, chat, and stylized fiction dialogue
====================  ==================================================

Composite score
---------------

The composite formality_index is a weighted average::

    formality_index = (
        (1 - contraction_rate)       * 0.20 +
        (1 - informal_pronoun_rate)  * 0.15 +
        (1 - colloquial_density)     * 0.20 +
        passive_voice_ratio          * 0.15 +
        latinate_vocabulary_ratio    * 0.20 +
        formality_hedge_rate         * 0.10
    )

Note that contraction_rate, informal_pronoun_rate, and colloquial_density
are *inverted* (1 - x) because their presence signals informality, while
passive_voice_ratio, latinate_vocabulary_ratio, and formality_hedge_rate
signal formality directly.

Weights reflect diagnostic importance: contractions (0.20) and
colloquialisms (0.20) are the strongest informal signals, Latinate
vocabulary (0.20) is the strongest formal signal, pronoun usage (0.15)
and passive voice (0.15) are moderate signals, and hedging (0.10) is
a weaker but distinctive formal marker.

Usage
-----

    from iamai.writer_formality import WriterFormality

    wf = WriterFormality()
    result = wf.measure(text)
    print(result["formality_index"])       # 0.0–1.0
    print(result["classification"])         # academic|formal|conversational|casual|colloquial
    print(result["contraction_rate"])       # 0.0–1.0
"""

import re
from typing import Dict, List, Set


# Contractions: common English contracted forms
CONTRACTIONS: Set[str] = {
    "don't", "doesn't", "didn't", "won't", "wouldn't", "can't",
    "couldn't", "shouldn't", "isn't", "aren't", "wasn't", "weren't",
    "hasn't", "haven't", "hadn't", "mustn't", "needn't", "shan't",
    "i'm", "you're", "he's", "she's", "it's", "we're", "they're",
    "i've", "you've", "we've", "they've",
    "i'd", "you'd", "he'd", "she'd", "we'd", "they'd",
    "i'll", "you'll", "he'll", "she'll", "we'll", "they'll",
    "that's", "there's", "here's", "who's", "what's", "where's",
    "how's", "when's", "why's", "let's",
    "ain't", "y'all", "o'clock", "ma'am", "sir'",
}

# Informal pronouns: first and second person
INFORMAL_PRONOUNS: Set[str] = {
    "i", "me", "my", "mine", "myself",
    "we", "us", "our", "ours", "ourselves",
    "you", "your", "yours", "yourself", "yourselves",
}

# Colloquial / slang / informal expressions (200+ items)
COLLOQUIAL_EXPRESSIONS: Set[str] = {
    # Abbreviations and reductions
    "gonna", "wanna", "gotta", "kinda", "sorta", "dunno", "lemme",
    "gimme", "cuz", "cos", "coz", "tho", "thou", "prolly",
    "probly", "defo", "def", "legit", "sus", "tbh", "imo",
    "imho", "idk", "idc", "iykyk", "nvm", "rn", "fr", "ong",
    "istg", "ngl", "smh", "tfw", "mfw", "irl", "afk", "brb",
    "btw", "fyi", "lol", "lmao", "rofl", "omg", "wtf", "stfu",
    "jk", "np", "yw", "ty", "thx", "pls", "plz", "srsly",
    "obvs", "totes", "adorbs", "amazeballs",
    # Discourse markers
    "like", "basically", "literally", "actually", "honestly",
    "seriously", "whatever", "anyway", "anyways", "meanwhile",
    "obviously", "clearly", "apparently", "supposedly",
    # Intensifiers
    "super", "really", "totally", "crazy", "mad", "hella",
    "deadass", "lowkey", "highkey", "very", "soooo", "suuuper",
    "insanely", "wildly", "extremely",
    # Evaluative terms
    "cool", "awesome", "neat", "groovy", "nifty", "sick", "dope",
    "fire", "mid", "based", "cringe", "cringey", "cringy",
    "bussin", "noice", "yeet", "slaps", "hits", "vibes",
    "mood", "big", "huge", "massive", "tiny", "wee",
    # Informal verbs and expressions
    "chill", "hang", "vibe", "flex", "ghost", "stan", "ship",
    "spill", "shade", "clap", "slay", "snatch", "ate",
    "gagged", "shook", "dead", "deceased", "unwell",
    # Informal nouns
    "stuff", "things", "thingy", "whatchamacallit", "thingamajig",
    "doohickey", "whatsit", "gizmo", "doodad",
    "dude", "bro", "sis", "mate", "pal", "buddy", "homie",
    "bestie", "bff", "bae", "boo",
    # Fillers and hedging (informal)
    "um", "uh", "er", "hmm", "well", "okay", "ok", "alright",
    "right", "yeah", "yep", "yup", "nope", "nah", "meh",
}

# Latinate suffixes indicating formal register
LATINATE_SUFFIXES: List[str] = [
    "tion", "sion", "ation", "ition",
    "ment", "ence", "ance", "ency", "ancy",
    "ity", "osity",
    "ism", "ist",
    "ure", "ture",
]

# Latinate prefixes indicating formal register  
LATINATE_PREFIXES: List[str] = [
    "con", "com", "col", "cor", "co",
    "dis", "pre", "re", "pro", "sub",
    "inter", "trans", "circum", "contra",
    "de", "ex", "in", "ob", "per", "post",
]

# Formal hedging expressions
FORMAL_HEDGES: Set[str] = {
    "approximately", "arguably", "presumably", "ostensibly",
    "purportedly", "seemingly", "reportedly", "allegedly",
    "conceivably", "plausibly", "tentatively",
    "apparently", "evidently",
}

# Formal hedge phrases (multi-word)
FORMAL_HEDGE_PHRASES: List[str] = [
    "to some extent", "to a certain extent", "in some respects",
    "it appears that", "it seems that", "it could be argued",
    "it may be", "it might be", "it is possible that",
    "it is likely that", "it is conceivable that",
    "it is plausible that", "it is reasonable to",
    "one might argue", "one could argue", "one may observe",
    "it should be noted", "it is worth noting",
    "it bears mentioning", "it is pertinent to note",
    "tends to", "appears to", "seems to",
    "is said to", "is believed to", "is thought to",
    "has been suggested", "has been proposed",
    "may perhaps", "might possibly", "could potentially",
]

# Common function words to exclude from morphological analysis
FUNCTION_WORDS: Set[str] = {
    "the", "a", "an", "is", "am", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "shall", "should", "may", "might", "must",
    "can", "could", "i", "you", "he", "she", "it", "we", "they",
    "me", "him", "her", "us", "them", "my", "your", "his", "its",
    "our", "their", "this", "that", "these", "those", "and", "or",
    "but", "not", "no", "yes", "if", "then", "else", "when",
    "where", "why", "how", "what", "which", "who", "whom",
    "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "as", "into", "through", "during", "before", "after",
    "above", "below", "between", "under", "over", "out", "off",
    "up", "down", "about", "against", "along", "among",
}


class WriterFormality:
    """Measure the formality register of prose."""

    def __init__(self):
        self.contractions = CONTRACTIONS
        self.informal_pronouns = INFORMAL_PRONOUNS
        self.colloquial_expressions = COLLOQUIAL_EXPRESSIONS
        self.latinate_suffixes = LATINATE_SUFFIXES
        self.latinate_prefixes = LATINATE_PREFIXES
        self.formal_hedges = FORMAL_HEDGES
        self.formal_hedge_phrases = FORMAL_HEDGE_PHRASES
        self.function_words = FUNCTION_WORDS

    def _tokenize(self, text: str) -> List[str]:
        """Split text into lowercase word tokens."""
        return re.findall(r'\b[a-z]+\b', text.lower())

    def _tokenize_with_contractions(self, text: str) -> List[str]:
        """Split text preserving contractions as single tokens."""
        # First, find all contractions
        pattern = r"\b[a-z]+(?:'[a-z]+)\b"
        contractions_found = re.findall(pattern, text.lower())
        # Then find all regular words
        tokens = re.findall(r"\b[a-z']+\b", text.lower())
        return tokens

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        sentences = re.split(r'[.!?]+', text)
        return [s.strip() for s in sentences if s.strip()]

    def _has_latinate_morphology(self, word: str) -> bool:
        """Check if word has Latinate morphological markers."""
        if word in self.function_words:
            return False
        if len(word) < 4:
            return False
        # Check suffixes
        for suffix in self.latinate_suffixes:
            if word.endswith(suffix) and len(word) > len(suffix) + 2:
                return True
        # Check prefixes (only if word is long enough)
        for prefix in self.latinate_prefixes:
            if word.startswith(prefix) and len(word) > len(prefix) + 3:
                # Also check for a second morphological marker
                for suffix in self.latinate_suffixes:
                    if word.endswith(suffix):
                        return True
        return False

    def _count_passive_constructions(self, text: str) -> int:
        """Count passive voice constructions (be + past participle)."""
        # Pattern: form of be + past participle (-ed or irregular)
        # This is a simplified heuristic; production code should use
        # a proper POS tagger and dependency parser
        passive_patterns = [
            r'\b(?:is|are|was|were|be|been|being)\s+\w+ed\b',
            r'\b(?:is|are|was|were|be|been|being)\s+\w+en\b',
            r'\b(?:has|have|had)\s+been\s+\w+ed\b',
            r'\b(?:has|have|had)\s+been\s+\w+en\b',
            r'\b(?:will|shall)\s+be\s+\w+ed\b',
            r'\b(?:will|shall)\s+be\s+\w+en\b',
        ]
        count = 0
        text_lower = text.lower()
        for pattern in passive_patterns:
            matches = re.findall(pattern, text_lower)
            count += len(matches)
        return count

    def measure_contraction_rate(self, text: str) -> float:
        """Fraction of verb forms that use contracted spelling."""
        tokens = self._tokenize_with_contractions(text)
        if not tokens:
            return 0.0
        contraction_count = sum(1 for t in tokens if t in self.contractions)
        # Count verb-like tokens (including contractions)
        verb_tokens = sum(
            1 for t in tokens
            if t in self.contractions
            or t in {"is", "are", "was", "were", "have", "has", "had",
                     "will", "would", "shall", "should", "do", "does",
                     "did", "can", "could", "may", "might", "must",
                     "am", "be", "been", "being"}
        )
        if verb_tokens == 0:
            return 0.0
        return min(contraction_count / verb_tokens, 1.0)

    def measure_informal_pronoun_rate(self, text: str) -> float:
        """Density of first- and second-person pronouns per sentence."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        total_pronouns = 0
        for sentence in sentences:
            tokens = self._tokenize(sentence)
            total_pronouns += sum(1 for t in tokens if t in self.informal_pronouns)
        # Normalize: pronouns per sentence, capped at 1.0
        rate = total_pronouns / len(sentences)
        # Typical formal prose has < 0.5 per sentence; casual has 2+
        return min(rate / 3.0, 1.0)

    def measure_colloquial_density(self, text: str) -> float:
        """Fraction of tokens that are colloquial/slang expressions."""
        tokens = self._tokenize(text)
        if not tokens:
            return 0.0
        colloquial_count = sum(1 for t in tokens if t in self.colloquial_expressions)
        return min(colloquial_count / len(tokens), 1.0)

    def measure_passive_voice_ratio(self, text: str) -> float:
        """Fraction of verb phrases using passive construction."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        passive_count = self._count_passive_constructions(text)
        # Estimate total verb phrases: at least one per sentence
        # This is a rough heuristic
        verb_count = max(len(sentences), passive_count)
        return min(passive_count / verb_count, 1.0)

    def measure_latinate_vocabulary_ratio(self, text: str) -> float:
        """Fraction of content tokens with Latinate morphology."""
        tokens = self._tokenize(text)
        if not tokens:
            return 0.0
        content_tokens = [t for t in tokens if t not in self.function_words]
        if not content_tokens:
            return 0.0
        latinate_count = sum(1 for t in content_tokens if self._has_latinate_morphology(t))
        return min(latinate_count / len(content_tokens), 1.0)

    def measure_formality_hedge_rate(self, text: str) -> float:
        """Fraction of sentences containing formal hedging expressions."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        hedge_count = 0
        text_lower = text.lower()
        for sentence in sentences:
            sentence_lower = sentence.lower()
            tokens = self._tokenize(sentence)
            # Check single-word hedges
            has_hedge = any(t in self.formal_hedges for t in tokens)
            # Check multi-word hedge phrases
            if not has_hedge:
                has_hedge = any(phrase in sentence_lower for phrase in self.formal_hedge_phrases)
            if has_hedge:
                hedge_count += 1
        return hedge_count / len(sentences)

    def compute_formality_index(
        self,
        contraction: float,
        informal_pronoun: float,
        colloquial: float,
        passive: float,
        latinate: float,
        hedge: float,
    ) -> float:
        """Compute weighted composite score."""
        return (
            (1.0 - contraction) * 0.20
            + (1.0 - informal_pronoun) * 0.15
            + (1.0 - colloquial) * 0.20
            + passive * 0.15
            + latinate * 0.20
            + hedge * 0.10
        )

    def classify(self, index: float) -> str:
        """Classify formality level."""
        if index >= 0.75:
            return "academic"
        elif index >= 0.55:
            return "formal"
        elif index >= 0.35:
            return "conversational"
        elif index >= 0.20:
            return "casual"
        else:
            return "colloquial"

    def measure(self, text: str) -> Dict:
        """Measure all formality metrics for given text."""
        tokens = self._tokenize(text)
        if not tokens:
            return {
                "contraction_rate": 0.0,
                "informal_pronoun_rate": 0.0,
                "colloquial_density": 0.0,
                "passive_voice_ratio": 0.0,
                "latinate_vocabulary_ratio": 0.0,
                "formality_hedge_rate": 0.0,
                "formality_index": 0.0,
                "classification": "colloquial",
            }
        contraction = self.measure_contraction_rate(text)
        informal_pronoun = self.measure_informal_pronoun_rate(text)
        colloquial = self.measure_colloquial_density(text)
        passive = self.measure_passive_voice_ratio(text)
        latinate = self.measure_latinate_vocabulary_ratio(text)
        hedge = self.measure_formality_hedge_rate(text)
        index = self.compute_formality_index(
            contraction, informal_pronoun, colloquial, passive, latinate, hedge
        )
        classification = self.classify(index)

        return {
            "contraction_rate": round(contraction, 4),
            "informal_pronoun_rate": round(informal_pronoun, 4),
            "colloquial_density": round(colloquial, 4),
            "passive_voice_ratio": round(passive, 4),
            "latinate_vocabulary_ratio": round(latinate, 4),
            "formality_hedge_rate": round(hedge, 4),
            "formality_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    # Demo
    academic_text = """The utilization of computational methodologies
    in the analysis of linguistic phenomena has been extensively
    documented in contemporary scholarship. It should be noted that
    the implementation of automated text classification systems
    necessitates careful consideration of methodological limitations."""

    casual_text = """So I was like, totally gonna go to the store but
    then my friend texted me and we ended up just chilling at home.
    It was super cool though, we watched this really awesome movie
    and stuff. Honestly, it was the best night ever."""

    wf = WriterFormality()

    print("=== Academic Text ===")
    result = wf.measure(academic_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")

    print("\n=== Casual Text ===")
    result = wf.measure(casual_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")
