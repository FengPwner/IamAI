#!/usr/bin/env python3
"""writer_humor_density — measure how much prose relies on comedic devices.

Humor is the rhetorical art of provoking amusement through language.
A text rich in humor constantly reaches for laughs — puns, exaggeration,
absurdity, self-mockery, well-timed punchlines.  A text poor in
humor presents information without any comedic intent: every
sentence means exactly what it says, and nothing is designed to
make the reader smile.

Humor density is not a quality metric.  Comedy scripts and personal
essays *must* be humor-dense — the point is to entertain.  Legal
contracts and medical reports should have near-zero humor density.
Technical writing occasionally uses humor to maintain reader
engagement ("the function name is left as an exercise for the reader").
The right density depends on genre, audience, and the writer's
relationship with their reader.

This module measures **how much of a text is spent on comedic
devices** — wordplay and puns, hyperbolic exaggeration, absurdist
language, self-deprecating remarks, and comedic timing structures.

Orthogonality to other metrics
-------------------------------

- **irony_density** tracks the gap between literal and intended
  meaning.  Irony can *produce* humor (saying "great job" when
  something failed is both ironic and funny), but irony can also
  be tragic or bitter.  Humor uses irony as one tool among many;
  irony does not require humor.  A dry, ironic observation may
  never intend to amuse; a pun has no ironic gap at all.

- **contrast_density** tracks oppositional structures.  Comedy
  often uses contrast (setup vs. punchline), but contrast is
  structural while humor is intentional.  A scientific comparison
  is contrast-dense but humor-free; a self-deprecating joke may
  have no explicit contrast at all.

- **tension** tracks anticipation and forward pull.  Comedic
  timing exploits tension (building expectation, then subverting
  it), but tension also operates in thrillers and arguments
  without any comedic intent.  Tension measures the pull; humor
  measures whether the release is meant to be funny.

- **formality** tracks register conventions.  Humor can appear
  in any register — from bathroom jokes to dry academic wit —
  but formal writing typically suppresses it.  Humor and formality
  are correlated but not inverses: casual writing can be
  humorless, and formal writing can contain devastating wit.

- **subtext** tracks implied meaning.  Some humor relies on
  subtext (the reader "gets" the joke without it being explained),
  but slapstick and puns operate entirely on the surface.
  Subtext hides meaning; humor reveals it through a comedic lens.

- **ellipsis_density** tracks what is left unsaid.  Comedic
  timing sometimes uses ellipsis (the pregnant pause before a
  punchline), but ellipsis can also signal uncertainty or
  trailing thought.  Ellipsis measures omission; comedic timing
  measures *rhythmic placement* of humor.

Humor asks: **is the text trying to make the reader laugh, and
how much of its language is spent on that effort?**

Dimensions
----------

=============================  =============================================
metric                         meaning
=============================  =============================================
wordplay_rate                  frequency of puns, double meanings, and
                               homophonic wordplay per sentence: deliberate
                               puns, spoonerisms, malapropisms, double
                               entendres, portmanteau humor, "no pun
                               intended" disclaimers, quotation-marked
                               wordplay
hyperbole_rate                 frequency of comedic exaggeration per
                               sentence: superlative inflation (literally
                               the best/worst ever), impossible scale
                               (a million times, infinity plus one),
                               dramatic overstatement (I would rather die,
                               the longest day in history), catastrophic
                               framing of minor events
absurdist_language_rate        frequency of absurd or surreal comedic
                               expressions per sentence: non-sequitur
                               humor, surreal comparisons, nonsense
                               logic, deadpan absurdity, Monty Python-style
                               escalation, Douglas Adams-style bathos
self_deprecation_rate          frequency of self-mocking or self-
                               depreciating humor per sentence: self-
                               insult, humble-brag patterns, comedic
                               confession of inadequacy, "I'm not saying
                               I'm X but..." patterns, self-roast
comedic_timing_rate            frequency of comedic timing structures per
                               sentence: rule-of-three (X, Y, and Z where
                               Z is the punchline), dash-punchline
                               (setup — punchline), ellipsis-punchline
                               (setup... punchline), parenthetical
                               asides for comedic effect, "and then..."
                               escalation, "plot twist" markers
=============================  =============================================

From these five dimensions a composite **humor_density_index** is
computed as a weighted average and classified:

========================  =================================================
class                     meaning
========================  =================================================
humor_free                index < 0.05 — no detectable comedic intent
deadpan                   0.05 <= index < 0.15 — rare, dry humor
witty                     0.15 <= index < 0.30 — regular comedic touches
comedic                   0.30 <= index < 0.50 — humor is a major mode
laugh_out_loud            index >= 0.50 — text is primarily comedic
========================  =================================================
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Pattern libraries
# ---------------------------------------------------------------------------

WORDPLAY_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bno\s+pun\s+intended\b", re.IGNORECASE),
    re.compile(r"\bpun\s+(?:absolutely\s+)?intended\b", re.IGNORECASE),
    re.compile(r"\b(?:that'?s?\s+(?:a\s+)?)?(?:good|bad|terrible|awful|dad)\s+pun\b", re.IGNORECASE),
    re.compile(r"\bplay\s+on\s+words?\b", re.IGNORECASE),
    re.compile(r"\bdouble\s+entendre\b", re.IGNORECASE),
    re.compile(r"\bdouble\s+meaning\b", re.IGNORECASE),
    re.compile(r"\bspoonerism\b", re.IGNORECASE),
    re.compile(r"\bmalapropism\b", re.IGNORECASE),
    re.compile(r"\bportmanteau\b", re.IGNORECASE),
    re.compile(r"\bif\s+you\s+will\b", re.IGNORECASE),
    re.compile(r"\bno\s+prize\s+for\s+guessing\b", re.IGNORECASE),
    re.compile(r"\bget\s+it\s*\?", re.IGNORECASE),
    re.compile(r"\bsee\s+what\s+(?:I|you)\s+did\s+there\b", re.IGNORECASE),
    re.compile(r"\bI\s+(?:see|get)\s+what\s+you(?:'re|\s+are)\s+(?:saying|doing|getting\s+at)\b", re.IGNORECASE),
    re.compile(r"['\u201c](?:pun|wordplay|joke)[\s\S]{0,10}['\u201d]", re.IGNORECASE),
]

HYPERBOLE_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bliterally\s+(?:the\s+)?(?:best|worst|greatest|most|least|craziest|weirdest|funniest|most\s+amazing)\s+(?:thing|day|idea|experience|moment|person|place)\b", re.IGNORECASE),
    re.compile(r"\b(?:a\s+)?(?:million|billion|trillion|thousand|zillion|gazillion)\s+times?\b", re.IGNORECASE),
    re.compile(r"\binfinity\s+(?:plus\s+one|times|percent)\b", re.IGNORECASE),
    re.compile(r"\bI\s+would\s+rather\s+(?:die|eat\s+glass|jump\s+off\s+a\s+bridge|walk\s+through\s+fire|drink\s+battery\s+acid)\b", re.IGNORECASE),
    re.compile(r"\bthe\s+longest\s+(?:day|week|month|year|hour|minute|night|meeting|class|lecture)\s+in\s+(?:history|the\s+world|my\s+life|human\s+history|recorded\s+history)\b", re.IGNORECASE),
    re.compile(r"\bend\s+of\s+(?:the\s+)?(?:world|world\s+as\s+we\s+know\s+it|civilization)\b", re.IGNORECASE),
    re.compile(r"\b(?:worst|best)\s+(?:day|thing|idea|decision|moment)\s+(?:of\s+my\s+life|ever|in\s+history)\b", re.IGNORECASE),
    re.compile(r"\bI'?m?\s+(?:dying|dead|deceased|gone|finished|done\s+for|not\s+okay)\b", re.IGNORECASE),
    re.compile(r"\bI\s+(?:can'?t|cannot)\s+(?:even|deal|breathe|function|adult|peopling)\b", re.IGNORECASE),
    re.compile(r"\b(?:my|this)\s+(?:brain|head)\s+(?:exploded|is\s+exploding|will\s+explode|melted|is\s+melting)\b", re.IGNORECASE),
    re.compile(r"\b(?:screaming|crying|dying|sobbing|laughing)\s+(?:internally|externally|on\s+the\s+inside|in\s+(?:the\s+)?(?:public|private))\b", re.IGNORECASE),
    re.compile(r"\bthe\s+(?:audacity|nerve|gall|chutzpah)\s+of\b", re.IGNORECASE),
    re.compile(r"\bcatastrophic(?:ally)?\s+(?:bad|terrible|awful|wrong|broken)\b", re.IGNORECASE),
    re.compile(r"\bworld-?(?:ending|shattering|breaking|changing)\s+(?:event|disaster|problem|issue)\b", re.IGNORECASE),
    re.compile(r"\b(?:absolute|total|complete|utter)\s+(?:disaster|catastrophe|trainwreck|dumpster\s+fire|nightmare|chaos)\b", re.IGNORECASE),
]

ABSURDIST_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(?:and\s+then\s+)?(?:aliens?|dinosaurs?|robots?|wizards?|ninjas?|pirates?)\s+(?:showed?\s+up|appeared?|attacked?|arrived?)\b", re.IGNORECASE),
    re.compile(r"\b(?:for\s+(?:some\s+)?(?:legal|tax|insurance)\s+reasons?)\b", re.IGNORECASE),
    re.compile(r"\b(?:this\s+is\s+(?:fine|not\s+fine))\b", re.IGNORECASE),
    re.compile(r"\b(?:plot\s+twist)\b", re.IGNORECASE),
    re.compile(r"\b(?:narrator:\s*(?:it|they|he|she)\s+(?:was|was\s+not|did|didn'?t))\b", re.IGNORECASE),
    re.compile(r"\b(?:in\s+(?:a\s+)?(?:parallel|alternate)\s+universe)\b", re.IGNORECASE),
    re.compile(r"\b(?:chaos\s+(?:ensued|reigned))\b", re.IGNORECASE),
    re.compile(r"\b(?:and\s+(?:then\s+)?everything\s+went\s+(?:wrong|sideways|pear-shaped|south|to\s+hell))\b", re.IGNORECASE),
    re.compile(r"\b(?:cue\s+the\s+(?:dramatic|suspense|sad|romantic)\s+music)\b", re.IGNORECASE),
    re.compile(r"\b(?:insert\s+(?:dramatic|ominous|suspenseful|comedic)\s+(?:sound|music|noise)\s+(?:effect|here))\b", re.IGNORECASE),
    re.compile(r"\b(?:record\s+scratch|freeze\s+frame)\b", re.IGNORECASE),
    re.compile(r"\byep,\s+that'?s?\s+(?:me|my\s+life|my\s+luck|typical)\b", re.IGNORECASE),
    re.compile(r"\bsure,\s+why\s+not\b", re.IGNORECASE),
    re.compile(r"\bat\s+this\s+point\b.*\b(?:might\s+as\s+well|why\s+not|nothing\s+(?:matters|surprises))\b", re.IGNORECASE),
    re.compile(r"(?:404|error)\s*[\u2014:\-]\s*(?:motivation|brain|sanity|patience|sleep|will\s+to\s+live)\s+not\s+found", re.IGNORECASE),
]

SELF_DEPRECATION_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bI'?m?\s+(?:not\s+(?:smart|clever|bright|talented|gifted|special|a\s+genius)|an?\s+(?:idiot|moron|fool|disaster|mess|hot\s+mess|walking\s+disaster))\b", re.IGNORECASE),
    re.compile(r"\bI\s+(?:have|got)\s+(?:the\s+)?(?:IQ|brain|intellect)\s+of\s+(?:a\s+)?(?:potato|goldfish|rock|turnip|peanut|amoeba|toddler)\b", re.IGNORECASE),
    re.compile(r"\b(?:in\s+my\s+defense|to\s+be\s+fair\s+to\s+me),?\s+I\s+(?:was|had\s+been)\b", re.IGNORECASE),
    re.compile(r"\bI\s+tried\s+my\s+best\b.*\b(?:it\s+wasn'?t|still|but|yet|failed|terrible|awful|disaster)\b", re.IGNORECASE),
    re.compile(r"\bI'?m?\s+(?:terrible|awful|horrible|bad|atrocious|hopeless)\s+at\b", re.IGNORECASE),
    re.compile(r"\b(?:my|this)\s+(?:attempt|effort|try|work|result)\s+(?:is|was|looks?|looked?)\s+(?:pathetic|sad|embarrassing|atrocious|terrible|laughable)\b", re.IGNORECASE),
    re.compile(r"\bI\s+(?:can'?t|cannot)\s+(?:even|do\s+anything\s+right|get\s+anything\s+right|adult|function|peopling|humaning)\b", re.IGNORECASE),
    re.compile(r"\b(?:bless|god\s+bless)\s+(?:my|this|their)\s+(?:heart|soul|little\s+heart)\b", re.IGNORECASE),
    re.compile(r"\b(?:I|me)\s+(?:being|as\s+always)\s+(?:my|the)\s+(?:usual|typical|classic)\s+(?:self|me)\b", re.IGNORECASE),
    re.compile(r"\bsurprisingly,\s+I\s+(?:did|managed|pulled\s+it\s+off|succeeded|didn'?t\s+(?:fail|mess|screw))\b", re.IGNORECASE),
    re.compile(r"\bI\s+(?:somehow|miraculously|magically|against\s+all\s+odds)\s+(?:managed|pulled\s+it\s+off|succeeded|survived|passed)\b", re.IGNORECASE),
    re.compile(r"\bmy\s+(?:one|only|sole)\s+(?:talent|skill|gift|ability|superpower)\s+(?:is|seems\s+to\s+be)\b", re.IGNORECASE),
    re.compile(r"\bI\s+peaked\s+in\s+(?:high\s+school|college|middle\s+school|elementary)\b", re.IGNORECASE),
    re.compile(r"\b(?:my|the)\s+bar\s+(?:is|was)\s+(?:low|on\s+the\s+floor|in\s+the\s+basement|underground|nonexistent)\b", re.IGNORECASE),
]

COMEDIC_TIMING_PATTERNS: List[re.Pattern] = [
    # Rule of three: "X, Y, and Z" where Z is the punchline (comma-separated with "and")
    re.compile(r",\s+and\s+—\s+", re.IGNORECASE),
    # Dash-punchline pattern
    re.compile(r"\w+\s+—\s+(?:oh|wait|never\s+mind|actually|just\s+kidding|plot\s+twist|spoiler|surprise)\b", re.IGNORECASE),
    # Ellipsis-punchline
    re.compile(r"\.\.\.\s*(?:nope|nah|just\s+kidding|psych|plot\s+twist|surprise|not|never\s+mind)\b", re.IGNORECASE),
    # "And then" escalation
    re.compile(r"\band\s+then\s+(?:—|,\s+)?(?:oh|well|so|guess\s+what|plot\s+twist|here'?s?\s+the)\b", re.IGNORECASE),
    # Parenthetical comedic aside
    re.compile(r"\((?:no\s+judgment|don'?t\s+judge|I\s+know,\s+I\s+know|shut\s+up|bear\s+with\s+me|I\s+see\s+you)\)", re.IGNORECASE),
    # "The real X is Y" punchline
    re.compile(r"\bthe\s+real\s+(?:question|problem|issue|tragedy|horror|comedy|villain|hero)\s+(?:is|was|has\s+always\s+been)\b", re.IGNORECASE),
    # "Plot twist" as standalone punchline
    re.compile(r"\bplot\s+twist\s*:", re.IGNORECASE),
    # "Wait for it" timing marker
    re.compile(r"\bwait\s+for\s+it\b", re.IGNORECASE),
    # Dramatic pause
    re.compile(r"\b\*dramatic\s+pause\*\b", re.IGNORECASE),
    # "...and I took that personally" meme format
    re.compile(r"\band\s+I\s+took\s+that\s+personally\b", re.IGNORECASE),
    # "Nobody:" / "Absolutely nobody:" setup format
    re.compile(r"\b(?:nobody|absolutely\s+no\s*one|not\s+a\s+single\s+person):\s*\n", re.IGNORECASE),
    # "Me:" reaction format
    re.compile(r"^\s*me:\s*", re.IGNORECASE | re.MULTILINE),
]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences on '.', '!', '?', preserving content."""
    parts = re.split(r'[.!?]+', text)
    return [p.strip() for p in parts if p.strip()]


def _count_matching(sentences: List[str], patterns: List[re.Pattern]) -> int:
    """Count sentences matching at least one pattern."""
    count = 0
    for sent in sentences:
        if any(p.search(sent) for p in patterns):
            count += 1
    return count


# ---------------------------------------------------------------------------
# WriterHumorDensity class
# ---------------------------------------------------------------------------


class WriterHumorDensity:
    """Measure the humor density in prose."""

    def __init__(self):
        self.wordplay = WORDPLAY_PATTERNS
        self.hyperbole = HYPERBOLE_PATTERNS
        self.absurdist = ABSURDIST_PATTERNS
        self.self_deprecation = SELF_DEPRECATION_PATTERNS
        self.comedic_timing = COMEDIC_TIMING_PATTERNS

    def _split_sentences(self, text: str) -> List[str]:
        return _split_sentences(text)

    def _count_matching(self, sentences: List[str], patterns: List[re.Pattern]) -> int:
        return _count_matching(sentences, patterns)

    def measure_wordplay_rate(self, text: str) -> float:
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        return self._count_matching(sentences, self.wordplay) / len(sentences)

    def measure_hyperbole_rate(self, text: str) -> float:
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        return self._count_matching(sentences, self.hyperbole) / len(sentences)

    def measure_absurdist_language_rate(self, text: str) -> float:
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        return self._count_matching(sentences, self.absurdist) / len(sentences)

    def measure_self_deprecation_rate(self, text: str) -> float:
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        return self._count_matching(sentences, self.self_deprecation) / len(sentences)

    def measure_comedic_timing_rate(self, text: str) -> float:
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        return self._count_matching(sentences, self.comedic_timing) / len(sentences)

    def compute_humor_density_index(
        self,
        wordplay: float,
        hyperbole: float,
        absurdist: float,
        self_dep: float,
        timing: float,
    ) -> float:
        return (
            wordplay * 0.20
            + hyperbole * 0.20
            + absurdist * 0.20
            + self_dep * 0.20
            + timing * 0.20
        )

    def classify(self, index: float) -> str:
        if index >= 0.50:
            return "laugh_out_loud"
        elif index >= 0.30:
            return "comedic"
        elif index >= 0.15:
            return "witty"
        elif index >= 0.05:
            return "deadpan"
        else:
            return "humor_free"

    def measure(self, text: str) -> Dict[str, Any]:
        wordplay = self.measure_wordplay_rate(text)
        hyperbole = self.measure_hyperbole_rate(text)
        absurdist = self.measure_absurdist_language_rate(text)
        self_dep = self.measure_self_deprecation_rate(text)
        timing = self.measure_comedic_timing_rate(text)
        index = self.compute_humor_density_index(
            wordplay, hyperbole, absurdist, self_dep, timing
        )
        classification = self.classify(index)

        return {
            "wordplay_rate": round(wordplay, 4),
            "hyperbole_rate": round(hyperbole, 4),
            "absurdist_language_rate": round(absurdist, 4),
            "self_deprecation_rate": round(self_dep, 4),
            "comedic_timing_rate": round(timing, 4),
            "humor_density_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    comedic_text = """Oh, it was literally the worst day in history. I woke
    up and my coffee maker had declared independence — plot twist: it was
    unplugged. I'm not saying I'm a disaster, but my one talent is making
    breakfast set off the smoke alarm. A million times I've told myself to
    buy a better toaster. And then — oh, you'll love this — the cat knocked
    over the cereal box. Sure, why not. At this point, nothing surprises me.
    In my defense, I was half asleep. My brain? 404 — motivation not found.
    The real tragedy is that I peaked in high school. Nobody:
    Me at 3am: I should learn to knit."""

    serious_text = """The committee reviewed the quarterly financial
    statements. Revenue increased by twelve percent compared to the
    previous period. Operating expenses remained within the approved
    budget. The board approved the proposed capital expenditure plan.
    Next quarter projections were presented for discussion."""

    whd = WriterHumorDensity()

    print("=== Comedic Text ===")
    result = whd.measure(comedic_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")

    print("\n=== Serious Text ===")
    result = whd.measure(serious_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")
