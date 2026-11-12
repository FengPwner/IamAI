#!/usr/bin/env python3
"""writer_temporal_orientation — measure where prose lives in time.

Temporal orientation is the *tense gravity* of a text: does it pull
toward the past (memoir, history, autopsy report), the present
(instruction, criticism, live narration), or the future (planning,
prophecy, proposal)?  Every piece of prose has a temporal center of
mass — a direction it leans — and that lean shapes how the reader
experiences the information.

This is not a quality metric.  A memoir *should* be past-oriented;
a project proposal *should* be future-oriented.  The measure exists
so the writer can *see* whether their temporal choices match their
intent — and whether unconscious tense drift is pulling the prose
away from where it should be anchored.

This module is orthogonal to the other writer metrics:

- **formality** tracks *register conventions*.  Formal prose can be
  past-oriented ("the defendant was observed entering the premises")
  or future-oriented ("the committee shall convene on the first
  Monday of each month").  Temporal orientation measures *when*,
  formality measures *how formally*.

- **pacing** tracks *narrative speed* — how fast events seem to
  unfold.  Pacing is about *rate of change*; temporal orientation
  is about *direction in time*.  A fast-paced text can be entirely
  past-tense (action sequence) or entirely present-tense (live
  commentary).

- **prose_rhythm** tracks *variation in sentence length and
  structure*.  Rhythm is syntactic patterning, independent of
  tense.  A text can have strong rhythm and any temporal
  orientation.

- **tension** tracks *anticipation and forward pull*.  Tension
  makes the reader want to know what happens next.  A past-tense
  thriller can have high tension; a future-tense plan can have
  none.  Tension is about *narrative pull*; temporal orientation
  is about *grammatical time*.

- **temporal_awareness** tracks whether the writer *acknowledges
  time passing* — timestamps, durations, deadlines.  Temporal
  awareness is meta-cognitive (does the writer *think* about
  time?); temporal orientation is grammatical (what tense does
  the writer *use*?).

- **linearity** tracks *sequential vs. non-sequential organization*.
  A linear text moves A → B → C regardless of tense.  Temporal
  orientation measures the *tense layer*, not the *structural
  layer*.  A flashback-heavy (non-linear) narrative can still be
  uniformly past-tense.

Temporal orientation asks: **where does this prose live in time —
looking back, looking around, or looking ahead?**

Dimensions
----------

============================  ============================================
metric                        meaning
============================  ============================================
past_tense_density            fraction of sentences containing past-tense
                              verb markers (simple past -ed forms, common
                              irregular past forms: went, saw, took, made,
                              came, gave, etc.)
present_tense_density         fraction of sentences containing present-tense
                              verb markers (third-person -s, base forms in
                              present context, present-time auxiliaries)
future_tense_density          fraction of sentences containing future-tense
                              markers (will, shall, going to, about to,
                              will be, will have)
temporal_adverbial_density    fraction of sentences containing time-
                              oriented adverbials and prepositional phrases
                              (yesterday, tomorrow, now, then, next week,
                              last year, in 2024, since then, etc.)
perfective_aspect_ratio       fraction of sentences containing perfect
                              aspect constructions (have/has/had + past
                              participle patterns)
progressive_aspect_ratio      fraction of sentences containing progressive
                              aspect constructions (am/is/are/was/were +
                              present participle -ing patterns)
============================  ============================================

From these six dimensions a composite **temporal_orientation_index**
is computed as a directional score from -1.0 (fully past) through
0.0 (balanced/present) to +1.0 (fully future), and classified:

==============  ============================================================
classification  meaning
==============  ============================================================
retrospective   <= -0.35; prose firmly anchored in the past — memoir,
                history, incident report, post-mortem, autobiography
immediate       between -0.35 and +0.35; prose centered on the present —
                instruction, criticism, live narration, technical
                documentation, philosophical argument
prospective     >= +0.35; prose oriented toward the future — planning,
                proposal, prophecy, roadmap, speculative fiction
==============  ============================================================

Composite score
---------------

The temporal_orientation_index is computed as::

    temporal_orientation_index = future_score - past_score

where::

    past_score = (
        past_tense_density        * 0.35 +
        perfective_aspect_ratio   * 0.25 +
        past_adverbial_fraction   * 0.20 +
        temporal_adverbial_density * 0.20  [past-weighted portion]
    )

    future_score = (
        future_tense_density      * 0.40 +
        progressive_aspect_ratio  * 0.15 +
        future_adverbial_fraction * 0.25 +
        temporal_adverbial_density * 0.20  [future-weighted portion]
    )

Present tense acts as the neutral center: high present_tense_density
pulls the index toward zero regardless of direction.

Usage
-----

    from iamai.writer_temporal_orientation import WriterTemporalOrientation

    wto = WriterTemporalOrientation()
    result = wto.measure(text)
    print(result["temporal_orientation_index"])  # -1.0 to +1.0
    print(result["classification"])               # retrospective|immediate|prospective
    print(result["past_tense_density"])           # 0.0–1.0
"""

import re
from typing import Dict, List, Set, Tuple


# ---------------------------------------------------------------------------
# Past tense markers
# ---------------------------------------------------------------------------

# Common irregular past-tense verb forms (English top ~120)
IRREGULAR_PAST_FORMS: Set[str] = {
    # be / have / do
    "was", "were", "had", "did",
    # motion
    "went", "came", "ran", "walked", "drove", "flew", "rode",
    "swam", "fell", "rose", "grew", "threw", "drew", "blew",
    "knew", "flew", "slew",
    # perception
    "saw", "heard", "felt", "found", "caught", "taught",
    "brought", "bought", "thought", "sought",
    # communication
    "said", "told", "spoke", "wrote", "read", "meant",
    "swore", "wore", "tore", "bore",
    # action
    "took", "made", "gave", "got", "put", "set", "cut",
    "hit", "let", "shut", "split", "spread", "burst",
    "cost", "cast", "shed", "sped",
    # change
    "became", "began", "broke", "chose", "drew", "drank",
    "ate", "froze", "hid", "held", "kept", "laid", "led",
    "lent", "lost", "met", "paid", "quit", "rang",
    "sang", "sat", "shook", "shone", "shot", "showed",
    "slept", "sold", "spent", "spun", "stood", "stole",
    "stuck", "struck", "swung", "took", "tore", "told",
    "understood", "woke", "woke", "won", "wound", "withdrew",
    "wove", "wrung",
    # other common
    "built", "bent", "bound", "bit", "bled", "bred",
    "burnt", "burned", "crept", "dealt", "dug", "dreamt",
    "dreamed", "drew", "drunk", "fed", "fled", "forgave",
    "forgot", "forgotten", "fought", "ground", "hung",
    "hurt", "knelt", "knit", "laid", "leapt", "learnt",
    "learned", "left", "lit", "lay", "meant", "misled",
    "mistook", "overcame", "overtook", "partook", "pleaded",
    "proved", "rebound", "rebuilt", "redid", "remade",
    "repaid", "reran", "resold", "retook", "rewrote",
    "rode", "sank", "sent", "sewed", "shaved", "shrank",
    "slid", "smelt", "smelled", "snuck", "soothsaid",
    "sowed", "spat", "split", "spoilt", "spoiled",
    "sprang", "stank", "stove", "strewed", "strode",
    "strung", "strove", "swore", "swung", "took",
    "taught", "thought", "threw", "trod", "undid",
    "unwound", "upheld", "upset", "woke", "wore",
    "wove", "wed", "wept", "wet", "wrung",
}

# Past-tense adverbials (time-in-the-past markers)
PAST_ADVERBIALS: Set[str] = {
    "yesterday", "ago", "last", "previously", "formerly",
    "earlier", "once", "before", "already", "recently",
    "lately", "hitherto", "erstwhile", "back", "then",
    "afterward", "afterwards",
}

PAST_ADVERBIAL_PHRASES: List[str] = [
    "last week", "last month", "last year", "last night",
    "last summer", "last winter", "last spring", "last fall",
    "last century", "last decade",
    "the day before", "the night before", "the week before",
    "years ago", "months ago", "weeks ago", "days ago",
    "long ago", "not long ago", "a while ago",
    "in the past", "at that time", "by then",
    "in those days", "back then", "back in",
    "since then", "ever since",
    "one day", "that day", "that morning", "that evening",
    "that night", "that afternoon",
]


# ---------------------------------------------------------------------------
# Present tense markers
# ---------------------------------------------------------------------------

# Present-tense adverbials (time-in-the-now markers)
PRESENT_ADVERBIALS: Set[str] = {
    "now", "today", "currently", "presently", "nowadays",
    "these", "tonight", "meanwhile", "simultaneously",
    "henceforth",
}

PRESENT_ADVERBIAL_PHRASES: List[str] = [
    "right now", "at the moment", "at present",
    "this week", "this month", "this year", "this morning",
    "this afternoon", "this evening", "tonight",
    "in the present", "as of now", "as we speak",
    "day by day", "every day", "these days",
    "from time to time", "now and then",
    "in this day and age", "at this point",
    "for now", "as it stands",
]


# ---------------------------------------------------------------------------
# Future tense markers
# ---------------------------------------------------------------------------

# Future auxiliary forms
FUTURE_MARKERS: Set[str] = {
    "will", "shall",
}

FUTURE_PHRASES: List[str] = [
    "going to", "gonna",
    "about to", "due to", "set to", "bound to",
    "expected to", "likely to", "slated to",
    "planned to", "scheduled to", "meant to",
    "supposed to", "destined to", "fated to",
    "on the verge of", "on the brink of", "on the cusp of",
    "will be", "will have", "will have been",
    "shall be", "shall have",
]

# Future-tense adverbials
FUTURE_ADVERBIALS: Set[str] = {
    "tomorrow", "soon", "eventually", "someday", "hence",
    "hereafter", "forthwith", "shortly", "imminently",
    "ultimately", "prospectively", "henceforward",
}

FUTURE_ADVERBIAL_PHRASES: List[str] = [
    "next week", "next month", "next year", "next time",
    "next summer", "next winter", "next spring", "next fall",
    "next century", "next decade",
    "in the future", "in the coming", "in the near future",
    "down the road", "down the line",
    "sooner or later", "one day", "some day",
    "by then", "by that time",
    "in the long run", "in the short run",
    "going forward", "from now on", "from here on",
    "in years to come", "in times to come",
    "the day after", "the week after",
    "this coming", "the following",
]


# ---------------------------------------------------------------------------
# Aspect markers
# ---------------------------------------------------------------------------

# Perfect aspect: have/has/had + past participle
PERFECT_AUXILIARIES: Set[str] = {"have", "has", "had"}

# Progressive aspect: be + present participle (-ing)
PROGRESSIVE_AUXILIARIES: Set[str] = {
    "am", "is", "are", "was", "were", "be", "been", "being",
}


# ---------------------------------------------------------------------------
# Third-person present tense verb suffix
# ---------------------------------------------------------------------------

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
    "very", "just", "also", "too", "so", "than", "more",
    "most", "much", "many", "some", "any", "all", "each",
    "every", "both", "few", "several", "such", "other",
    "another", "own", "same",
}


class WriterTemporalOrientation:
    """Measure the temporal orientation of prose."""

    def __init__(self):
        self.irregular_past = IRREGULAR_PAST_FORMS
        self.past_adverbials = PAST_ADVERBIALS
        self.past_adverbial_phrases = PAST_ADVERBIAL_PHRASES
        self.present_adverbials = PRESENT_ADVERBIALS
        self.present_adverbial_phrases = PRESENT_ADVERBIAL_PHRASES
        self.future_markers = FUTURE_MARKERS
        self.future_phrases = FUTURE_PHRASES
        self.future_adverbials = FUTURE_ADVERBIALS
        self.future_adverbial_phrases = FUTURE_ADVERBIAL_PHRASES
        self.perfect_auxiliaries = PERFECT_AUXILIARIES
        self.progressive_auxiliaries = PROGRESSIVE_AUXILIARIES
        self.function_words = FUNCTION_WORDS

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """Split text into sentences using punctuation boundaries."""
        if not text or not text.strip():
            return []
        # Split on sentence-ending punctuation
        raw = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in raw if s.strip()]
        return sentences

    @staticmethod
    def _tokenize(sentence: str) -> List[str]:
        """Tokenize a sentence into lowercase words without punctuation."""
        if not sentence:
            return []
        return [
            w.lower()
            for w in re.findall(r"[a-zA-Z']+", sentence)
            if w.strip("'")
        ]

    def _has_irregular_past(self, tokens: List[str]) -> bool:
        """Check if any token is an irregular past-tense form."""
        for token in tokens:
            cleaned = token.strip("'")
            if cleaned in self.irregular_past and cleaned not in self.function_words:
                return True
        return False

    def _has_regular_past(self, tokens: List[str]) -> bool:
        """Check if any token ends in -ed (regular past tense).

        Excludes short words and known non-past -ed forms.
        """
        for token in tokens:
            if token in self.function_words:
                continue
            if len(token) >= 4 and token.endswith("ed"):
                # Exclude known non-past forms
                if token in {"need", "seed", "feed", "weed", "deed",
                             "heed", "speed", "breed", "creed", "greed",
                             "freed", "agreed", "proceed", "succeed",
                             "exceed", "indeed", "unneeded"}:
                    continue
                return True
        return False

    def _has_present_third_person(self, tokens: List[str]) -> bool:
        """Check for third-person singular present tense (-s/-es verbs).

        This is a heuristic: many -s words are plurals or possessives.
        We look for -s words that are NOT in common noun plural patterns.
        """
        for token in tokens:
            if token in self.function_words or len(token) < 3:
                continue
            # Skip obvious plurals and possessives
            if token.endswith("'s") or token.endswith("s'"):
                continue
            # -es endings that are verb-like
            if token.endswith("es") and len(token) >= 5:
                # Check if it looks like a verb (crude heuristic)
                stem = token[:-2]
                if stem.endswith(("sh", "ch", "x", "z", "s", "ss")):
                    return True
            # -s endings (not -ss, -us, -is which are nouns)
            if (token.endswith("s") and not token.endswith("ss")
                    and not token.endswith("us")
                    and not token.endswith("is")
                    and not token.endswith("'s")
                    and len(token) >= 4):
                # Exclude common noun plurals
                if token not in {
                    "things", "years", "days", "ways", "words",
                    "times", "people", "children", "women", "men",
                    "these", "those", "yes", "thus", "his", "its",
                    "this", "was", "has", "does", "as", "us",
                    "always", "sometimes", "perhaps", "less", "more",
                    "because", "unless", "whereas", "towards",
                    "sometimes", "besides", "otherwise",
                }:
                    return True
        return False

    def _has_future_marker(self, tokens: List[str], sentence: str) -> bool:
        """Check for future tense markers in the sentence."""
        sentence_lower = sentence.lower()
        # Check single-word markers
        for token in tokens:
            if token in self.future_markers:
                return True
        # Check multi-word phrases
        for phrase in self.future_phrases:
            if phrase in sentence_lower:
                return True
        return False

    def _count_past_adverbials(self, sentence: str) -> int:
        """Count past-time adverbials in a sentence."""
        sentence_lower = sentence.lower()
        count = 0
        # Single-word adverbials
        tokens = self._tokenize(sentence)
        for token in tokens:
            if token in self.past_adverbials:
                count += 1
        # Multi-word phrases
        for phrase in self.past_adverbial_phrases:
            if phrase in sentence_lower:
                count += 1
        return count

    def _count_present_adverbials(self, sentence: str) -> int:
        """Count present-time adverbials in a sentence."""
        sentence_lower = sentence.lower()
        count = 0
        tokens = self._tokenize(sentence)
        for token in tokens:
            if token in self.present_adverbials:
                count += 1
        for phrase in self.present_adverbial_phrases:
            if phrase in sentence_lower:
                count += 1
        return count

    def _count_future_adverbials(self, sentence: str) -> int:
        """Count future-time adverbials in a sentence."""
        sentence_lower = sentence.lower()
        count = 0
        tokens = self._tokenize(sentence)
        for token in tokens:
            if token in self.future_adverbials:
                count += 1
        for phrase in self.future_adverbial_phrases:
            if phrase in sentence_lower:
                count += 1
        return count

    def _has_perfect_aspect(self, tokens: List[str]) -> bool:
        """Check for perfect aspect (have/has/had + past participle)."""
        for i, token in enumerate(tokens):
            if token in self.perfect_auxiliaries:
                # Look ahead for past participle marker (-ed, -en, or irregular)
                if i + 1 < len(tokens):
                    next_token = tokens[i + 1]
                    # Check for -ed or -en ending, or common irregulars
                    if (next_token.endswith("ed") or next_token.endswith("en")
                            or next_token in self.irregular_past
                            or next_token in {
                                "been", "done", "gone", "seen", "known",
                                "shown", "thrown", "blown", "grown",
                                "drawn", "broken", "spoken", "stolen",
                                "frozen", "chosen", "written", "driven",
                                "risen", "fallen", "taken", "given",
                                "forgiven", "hidden", "bitten", "eaten",
                                "worn", "torn", "sworn", "born",
                                "borne", "shorn", "sworn",
                            }):
                        return True
        return False

    def _has_progressive_aspect(self, tokens: List[str]) -> bool:
        """Check for progressive aspect (be + present participle -ing)."""
        for i, token in enumerate(tokens):
            if token in self.progressive_auxiliaries:
                # Look ahead for -ing form
                if i + 1 < len(tokens):
                    next_token = tokens[i + 1]
                    if (len(next_token) >= 4 and next_token.endswith("ing")
                            and next_token not in {
                                "thing", "things", "king", "kings",
                                "ring", "rings", "sing", "sings",
                                "wing", "wings", "bring", "brings",
                                "spring", "springs", "string", "strings",
                                "during", "morning", "evening", "nothing",
                                "something", "anything", "everything",
                                "ceiling", "building", "meaning",
                                "being",  # "being" itself is aux not participle in most cases
                            }):
                        return True
        return False

    def measure_past_tense_density(self, text: str) -> float:
        """Measure fraction of sentences with past-tense markers."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        past_count = 0
        for sentence in sentences:
            tokens = self._tokenize(sentence)
            if self._has_irregular_past(tokens) or self._has_regular_past(tokens):
                past_count += 1
        return past_count / len(sentences)

    def measure_present_tense_density(self, text: str) -> float:
        """Measure fraction of sentences with present-tense markers."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        present_count = 0
        for sentence in sentences:
            tokens = self._tokenize(sentence)
            if self._has_present_third_person(tokens):
                present_count += 1
        return present_count / len(sentences)

    def measure_future_tense_density(self, text: str) -> float:
        """Measure fraction of sentences with future-tense markers."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        future_count = 0
        for sentence in sentences:
            tokens = self._tokenize(sentence)
            if self._has_future_marker(tokens, sentence):
                future_count += 1
        return future_count / len(sentences)

    def measure_temporal_adverbial_density(self, text: str) -> float:
        """Measure fraction of sentences containing temporal adverbials."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        adverbial_count = 0
        for sentence in sentences:
            total = (
                self._count_past_adverbials(sentence)
                + self._count_present_adverbials(sentence)
                + self._count_future_adverbials(sentence)
            )
            if total > 0:
                adverbial_count += 1
        return adverbial_count / len(sentences)

    def measure_perfective_aspect_ratio(self, text: str) -> float:
        """Measure fraction of sentences with perfect aspect."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        perfect_count = 0
        for sentence in sentences:
            tokens = self._tokenize(sentence)
            if self._has_perfect_aspect(tokens):
                perfect_count += 1
        return perfect_count / len(sentences)

    def measure_progressive_aspect_ratio(self, text: str) -> float:
        """Measure fraction of sentences with progressive aspect."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        progressive_count = 0
        for sentence in sentences:
            tokens = self._tokenize(sentence)
            if self._has_progressive_aspect(tokens):
                progressive_count += 1
        return progressive_count / len(sentences)

    def _compute_directional_adverbial_fractions(
        self, text: str
    ) -> Tuple[float, float]:
        """Compute past-weighted and future-weighted adverbial fractions."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0, 0.0
        past_adv = 0
        future_adv = 0
        for sentence in sentences:
            if self._count_past_adverbials(sentence) > 0:
                past_adv += 1
            if self._count_future_adverbials(sentence) > 0:
                future_adv += 1
        n = len(sentences)
        return past_adv / n, future_adv / n

    def compute_temporal_orientation_index(
        self,
        past_density: float,
        future_density: float,
        perfective: float,
        progressive: float,
        past_adverbial_frac: float,
        future_adverbial_frac: float,
        temporal_adverbial: float,
    ) -> float:
        """Compute directional temporal orientation index.

        Returns a value from -1.0 (fully past) to +1.0 (fully future).
        """
        past_score = (
            past_density * 0.35
            + perfective * 0.25
            + past_adverbial_frac * 0.20
            + temporal_adverbial * 0.20 * (past_adverbial_frac / max(past_adverbial_frac + future_adverbial_frac, 0.01))
        )
        future_score = (
            future_density * 0.40
            + progressive * 0.15
            + future_adverbial_frac * 0.25
            + temporal_adverbial * 0.20 * (future_adverbial_frac / max(past_adverbial_frac + future_adverbial_frac, 0.01))
        )
        index = future_score - past_score
        # Clamp to [-1.0, 1.0]
        return max(-1.0, min(1.0, index))

    def classify(self, index: float) -> str:
        """Classify temporal orientation."""
        if index <= -0.35:
            return "retrospective"
        elif index >= 0.35:
            return "prospective"
        else:
            return "immediate"

    def measure(self, text: str) -> Dict:
        """Measure all temporal orientation metrics for given text."""
        if not text or not text.strip():
            return {
                "past_tense_density": 0.0,
                "present_tense_density": 0.0,
                "future_tense_density": 0.0,
                "temporal_adverbial_density": 0.0,
                "perfective_aspect_ratio": 0.0,
                "progressive_aspect_ratio": 0.0,
                "temporal_orientation_index": 0.0,
                "classification": "immediate",
            }

        past = self.measure_past_tense_density(text)
        present = self.measure_present_tense_density(text)
        future = self.measure_future_tense_density(text)
        temporal_adv = self.measure_temporal_adverbial_density(text)
        perfective = self.measure_perfective_aspect_ratio(text)
        progressive = self.measure_progressive_aspect_ratio(text)
        past_adv_frac, future_adv_frac = self._compute_directional_adverbial_fractions(text)

        index = self.compute_temporal_orientation_index(
            past, future, perfective, progressive,
            past_adv_frac, future_adv_frac, temporal_adv,
        )
        classification = self.classify(index)

        return {
            "past_tense_density": round(past, 4),
            "present_tense_density": round(present, 4),
            "future_tense_density": round(future, 4),
            "temporal_adverbial_density": round(temporal_adv, 4),
            "perfective_aspect_ratio": round(perfective, 4),
            "progressive_aspect_ratio": round(progressive, 4),
            "temporal_orientation_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    # Demo
    past_text = """She walked through the old neighborhood yesterday.
    The house where she grew up had been painted blue, but someone
    had since repainted it yellow. She remembered the garden her
    mother tended every summer. The oak tree that her father planted
    the year she was born stood taller than she remembered. Everything
    felt smaller than it had seemed in childhood."""

    present_text = """The algorithm processes each token sequentially.
    It checks the token against a dictionary of known forms. When it
    finds a match, it assigns the corresponding part-of-speech tag.
    The system handles ambiguous cases by selecting the most frequent
    tag from the training corpus. This approach works well for
    standard English text."""

    future_text = """The committee will review the proposals next month.
    We are going to announce the winners at the annual conference.
    The new system will be deployed in phases, starting with a pilot
    program. By next year, the platform will have processed millions
    of transactions. Eventually, the team will expand the service to
    cover additional regions. The roadmap outlines milestones through
    the coming decade."""

    wto = WriterTemporalOrientation()

    print("=== Past-oriented Text ===")
    result = wto.measure(past_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")

    print("\n=== Present-oriented Text ===")
    result = wto.measure(present_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")

    print("\n=== Future-oriented Text ===")
    result = wto.measure(future_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")
