#!/usr/bin/env python3
"""writer_irony_density — measure the gap between literal and intended meaning.

Irony is the distance between what a sentence *says* and what it *means*.
A text with high irony density is layered: the surface reading and the
intended reading diverge, and the reader must do interpretive work to
recover the author's actual stance.  A text with no irony is transparent:
every sentence means exactly what it says.

This is not a value judgment.  Technical documentation *should* have low
irony density.  Satire, memoir, and critical essays often benefit from
high irony density.  The metric exists so the writer can *see* whether
their ironic register matches their intent — not to maximize it.

This module is orthogonal to the other writer metrics:

- **ambiguity** tracks *unintended multiplicity of meaning*.  Ambiguity
  is a bug: the reader cannot tell what the writer means.  Irony is a
  feature: the reader can tell, precisely because the gap between literal
  and intended meaning is *productive* — it creates humor, critique, or
  emotional complexity.

- **subtext** tracks *implied meaning between the lines*.  Subtext hides
  meaning in the negative space of the text — what is *not* said.  Irony
  puts meaning in direct tension with what *is* said — the surface
  statement and the real meaning coexist in the same words.

- **conviction** tracks *how strongly the writer commits to their claims*.
  A writer can be deeply ironic (saying the opposite of what they mean)
  while being highly convicted (the ironic stance is unwavering).  Or
  they can have zero conviction and zero irony (hedging without layering).

- **restraint** tracks *how much the writer holds back*.  Restraint is
  about volume: less is said.  Irony is about direction: what is said
  points away from what is meant.

- **tension** tracks *anticipation and forward pull*.  Tension makes the
  reader want to know what happens next.  Irony makes the reader question
  what is happening *now*.

Irony asks: **does the text mean what it says, or does it point away
from its own surface?**

Dimensions
----------

===========================  ===========================================
metric                       meaning
===========================  ===========================================
verbal_irony_rate            fraction of sentences where the literal
                             meaning is inverted or undercut by context
litotes_density              fraction of sentences using litotes —
                             affirming something by negating its opposite
rhetorical_negation_rate     fraction of sentences containing negation
                             that emphasizes through pretense of denial
understatement_ratio         fraction of sentences where language
                             systematically undershoots apparent magnitude
socratic_questioning_rate    fraction of sentences using questions that
                             expose weakness rather than inquire
===========================  ===========================================

From these five dimensions a composite **irony_index** is computed as a
weighted average and classified:

==============  ============================================================
class           meaning
==============  ============================================================
satirical       index >= 0.45 — text consistently operates at ironic remove
wry             0.30 <= index < 0.45 — frequent ironic distance
dry             0.15 <= index < 0.30 — occasional ironic touches
sincere         0.05 <= index < 0.15 — rare ironic moments
literal         index < 0.05 — no detectable irony
==============  ============================================================
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Pattern libraries
# ---------------------------------------------------------------------------

VERBAL_IRONY_PATTERNS: List[re.Pattern] = [
    re.compile(r"\boh\s+great\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+a\s+(?:brilliant|fantastic|wonderful|terrific|lovely|great|marvelous|splendid)\s+(?:idea|plan|move|decision|choice|strategy|approach|solution)\b", re.IGNORECASE),
    re.compile(r"\bthat\s+went\s+well\b", re.IGNORECASE),
    re.compile(r"\bthat'?s?\s+(?:just|exactly)\s+what\s+(?:I|we)\s+(?:needed|wanted)\b", re.IGNORECASE),
    re.compile(r"\bsure,\s+(?:that'?ll|that\s+will)\s+(?:work|help|fix|solve)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+could\s+(?:possibly|ever)\s+go\s+wrong\b", re.IGNORECASE),
    re.compile(r"\bno\s+(?:kidding|shit|duh)\b", re.IGNORECASE),
    re.compile(r"\btell\s+me\s+something\s+I\s+don'?t\s+know\b", re.IGNORECASE),
    re.compile(r"\b(?:big|real|huge)\s+surprise\b", re.IGNORECASE),
    re.compile(r"\bwho\s+would\s+have\s+(?:thought|guessed|known)\b", re.IGNORECASE),
    re.compile(r"\b(?:love|enjoy|adore|appreciate)\s+(?:that|how|the\s+fact\s+that)\b", re.IGNORECASE),
    re.compile(r"\b(?:always|never)\s+fails?\s+to\b", re.IGNORECASE),
    re.compile(r"\bjust\s+(?:what|exactly)\s+(?:the|a)\s+world\s+needs?\b", re.IGNORECASE),
]

LITOTES_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bnot\s+(?:bad|terrible|awful|horrible|half\s+bad|the\s+worst)\b", re.IGNORECASE),
    re.compile(r"\bno\s+(?:small|mean|easy|simple|minor|ordinary)\s+(?:feat|task|achievement|accomplishment|matter|thing|effort|challenge|problem)\b", re.IGNORECASE),
    re.compile(r"\bnot\s+(?:exactly|precisely)\s+(?:a\s+)?(?:genius|masterpiece|success|triumph|winner|rocket\s+science|picnic|walk\s+in\s+the\s+park)\b", re.IGNORECASE),
    re.compile(r"\bit'?s?\s+not\s+(?:impossible|unheard\s+of|unthinkable|unknown|uncommon)\b", re.IGNORECASE),
    re.compile(r"\bnot\s+(?:un|in)(?:reasonable|common|fair|happy|pleasant|wise|expected|usual|familiar|welcome)\b", re.IGNORECASE),
    re.compile(r"\bnot\s+without\s+(?:its|their|some|a\s+certain)\b", re.IGNORECASE),
    re.compile(r"\bcan'?t\s+(?:say|help\s+but\s+think|help\s+feeling)\b", re.IGNORECASE),
    re.compile(r"\bnot\s+that\s+(?:I'?m|I\s+am)\s+(?:complaining|judging|saying|suggesting|arguing)\b", re.IGNORECASE),
    re.compile(r"\b(?:hardly|scarcely|barely)\s+(?:a|an)\b", re.IGNORECASE),
    re.compile(r"\bnothing\s+if\s+not\b", re.IGNORECASE),
]

RHETORICAL_NEGATION_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bI'?m?\s+not\s+saying\b", re.IGNORECASE),
    re.compile(r"\bnot\s+that\s+anyone\s+(?:asked|cares|listened|noticed)\b", re.IGNORECASE),
    re.compile(r"\bfar\s+be\s+it\s+from\s+me\s+to\b", re.IGNORECASE),
    re.compile(r"\bI\s+don'?t\s+want\s+to\s+(?:say|call|label|use\s+the\s+word)\b", re.IGNORECASE),
    re.compile(r"\bI\s+(?:won'?t|will\s+not)\s+(?:say|go\s+so\s+far\s+as\s+to\s+say|even\s+try\s+to)\b", re.IGNORECASE),
    re.compile(r"\bnot\s+to\s+(?:mention|put\s+too\s+fine\s+a\s+point|be\s+dramatic|be\s+harsh|be\s+unkind|be\s+too\s+blunt)\b", re.IGNORECASE),
    re.compile(r"\bwithout\s+(?:wishing\s+to|meaning\s+to|wanting\s+to)\s+(?:offend|insult|upset|disappoint)\b", re.IGNORECASE),
    re.compile(r"\bI\s+don'?t\s+(?:mean\s+to|want\s+to|intend\s+to)\s+(?:be|sound|come\s+across\s+as)\b", re.IGNORECASE),
    re.compile(r"\b(?:let'?s?\s+)?not\s+pretend\b", re.IGNORECASE),
    re.compile(r"\bnot\s+that\s+it\s+matters\b", re.IGNORECASE),
    re.compile(r"\bneedless\s+to\s+say\b", re.IGNORECASE),
]

UNDERSTATEMENT_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(?:a\s+)?bit\s+of\s+(?:a\s+)?(?:problem|issue|situation|mess|disaster|crisis|catastrophe)\b", re.IGNORECASE),
    re.compile(r"\bslightly\s+(?:concerning|worrying|troubling|problematic|alarming|disturbing)\b", re.IGNORECASE),
    re.compile(r"\bsomewhat\s+(?:inconvenient|problematic|difficult|challenging|tricky|awkward)\b", re.IGNORECASE),
    re.compile(r"\bmildly\s+(?:disappointing|concerning|irritating|annoying|disturbing|troubling)\b", re.IGNORECASE),
    re.compile(r"\brather\s+(?:unfortunate|regrettable|awkward|embarrassing)\b", re.IGNORECASE),
    re.compile(r"\ba\s+(?:slight|minor|small|tiny|modest|moderate)\s+(?:setback|hiccup|glitch|bump|snag|complication)\b", re.IGNORECASE),
    re.compile(r"\bnot\s+(?:ideal|great|perfect|optimal|the\s+best)\b", re.IGNORECASE),
    re.compile(r"\bcould\s+(?:be|have\s+been)\s+(?:worse|better)\b", re.IGNORECASE),
    re.compile(r"\bnothing\s+(?:major|serious|terrible|alarming)\b", re.IGNORECASE),
    re.compile(r"\bjust\s+(?:one\s+of\s+)?those\s+things\b", re.IGNORECASE),
]

SOCRATIC_QUESTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"\band\s+you\s+think\s+that'?s?\s+(?:a\s+)?(?:good|great|wise|smart|sound)\b", re.IGNORECASE),
    re.compile(r"\bis\s+that\s+really\s+(?:what|how)\s+we'?re?\s+(?:doing|going|handling|managing)\b", re.IGNORECASE),
    re.compile(r"\bwho\s+could\s+have\s+(?:predicted|foreseen|seen\s+this\s+coming|known)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+could\s+(?:possibly|ever)\s+go\s+wrong\b", re.IGNORECASE),
    re.compile(r"\b(?:and|so)\s+how'?s?\s+that\s+(?:working|going|turning\s+out)\b", re.IGNORECASE),
    re.compile(r"\bis\s+that\s+(?:so|really\s+so|really\s+the\s+case)\s*\?", re.IGNORECASE),
    re.compile(r"\bdo\s+we\s+really\s+(?:think|believe|want|need)\b", re.IGNORECASE),
    re.compile(r"\bwhy\s+would\s+anyone\s+(?:do|want|choose|think|suggest)\b", re.IGNORECASE),
    re.compile(r"\bhow\s+is\s+that\s+(?:even|remotely)\s+(?:possible|acceptable|reasonable|a\s+thing)\b", re.IGNORECASE),
    re.compile(r"\bare\s+we\s+sure\s+(?:about\s+that|that'?s)\b", re.IGNORECASE),
    re.compile(r"\banyone\s+else\s+(?:seeing|noticing|hearing)\s+this\b", re.IGNORECASE),
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
# WriterIronyDensity class
# ---------------------------------------------------------------------------


class WriterIronyDensity:
    """Measure the ironic distance in prose."""

    def __init__(self):
        self.verbal_irony = VERBAL_IRONY_PATTERNS
        self.litotes = LITOTES_PATTERNS
        self.rhetorical_negation = RHETORICAL_NEGATION_PATTERNS
        self.understatement = UNDERSTATEMENT_PATTERNS
        self.socratic_questioning = SOCRATIC_QUESTION_PATTERNS

    def _split_sentences(self, text: str) -> List[str]:
        return _split_sentences(text)

    def _count_matching(self, sentences: List[str], patterns: List[re.Pattern]) -> int:
        return _count_matching(sentences, patterns)

    def measure_verbal_irony_rate(self, text: str) -> float:
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        return self._count_matching(sentences, self.verbal_irony) / len(sentences)

    def measure_litotes_density(self, text: str) -> float:
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        return self._count_matching(sentences, self.litotes) / len(sentences)

    def measure_rhetorical_negation_rate(self, text: str) -> float:
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        return self._count_matching(sentences, self.rhetorical_negation) / len(sentences)

    def measure_understatement_ratio(self, text: str) -> float:
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        return self._count_matching(sentences, self.understatement) / len(sentences)

    def measure_socratic_questioning_rate(self, text: str) -> float:
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        return self._count_matching(sentences, self.socratic_questioning) / len(sentences)

    def compute_irony_index(
        self,
        verbal: float,
        litotes: float,
        rhetorical: float,
        understatement: float,
        socratic: float,
    ) -> float:
        return (
            verbal * 0.25
            + litotes * 0.20
            + rhetorical * 0.20
            + understatement * 0.20
            + socratic * 0.15
        )

    def classify(self, index: float) -> str:
        if index >= 0.45:
            return "satirical"
        elif index >= 0.30:
            return "wry"
        elif index >= 0.15:
            return "dry"
        elif index >= 0.05:
            return "sincere"
        else:
            return "literal"

    def measure(self, text: str) -> Dict[str, Any]:
        verbal = self.measure_verbal_irony_rate(text)
        litotes_val = self.measure_litotes_density(text)
        rhetorical = self.measure_rhetorical_negation_rate(text)
        understatement = self.measure_understatement_ratio(text)
        socratic = self.measure_socratic_questioning_rate(text)
        index = self.compute_irony_index(
            verbal, litotes_val, rhetorical, understatement, socratic
        )
        classification = self.classify(index)

        return {
            "verbal_irony_rate": round(verbal, 4),
            "litotes_density": round(litotes_val, 4),
            "rhetorical_negation_rate": round(rhetorical, 4),
            "understatement_ratio": round(understatement, 4),
            "socratic_questioning_rate": round(socratic, 4),
            "irony_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    satirical_text = """Oh great, another meeting about meetings. What a
    brilliant idea — let us discuss how to have fewer discussions. I am not
    saying it was a waste of time, but far be it from me to suggest we
    could have sent an email. The results were, shall we say, not exactly
    a masterpiece of productivity. Slightly concerning that we spent
    forty-five minutes on the font choice for the agenda. And you think
    that is a good use of everyone afternoon? It is fine. It is all fine.
    Who could have predicted that scheduling a meeting about avoiding
    meetings would itself be a meeting? Not that anyone asked me."""

    literal_text = """The quarterly report was submitted on time. Revenue
    increased by eight percent compared to the previous quarter. The
    team completed all assigned tasks. Customer satisfaction scores
    remained stable. The next review is scheduled for March."""

    wid = WriterIronyDensity()

    print("=== Satirical Text ===")
    result = wid.measure(satirical_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")

    print("\n=== Literal Text ===")
    result = wid.measure(literal_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")
