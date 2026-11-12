#!/usr/bin/env python3
"""writer_reflexivity — measure the self-awareness depth of prose.

Reflexivity tracks *the degree to which the writer demonstrates
awareness of their own act of writing, thinking, and knowing*.
A reflexive writer sees themselves in the mirror of their text:
they acknowledge their perspective, name their uncertainty, trace
the arc of their own understanding, and recognize that their
viewpoint is one among many possible viewpoints.  A non-reflexive
writer delivers information as if it simply *is* — unmediated by
any particular consciousness.

This module is orthogonal to the other writer metrics:

- **clarity** tracks *how easily the reader can understand the text*.
  Clear prose can be completely non-reflexive (a well-written manual).
  Reflexive prose may sometimes sacrifice clarity in service of
  exploring the writer's own thought process (Montaigne's essays
  wander, but they are deeply reflexive).

- **subtext** tracks *implied meaning between the lines*.  Subtext
  hides meaning; reflexivity *surfaces* the writer's relationship
  to meaning.  A text can have rich subtext and zero reflexivity
  (Hemingway's iceberg technique) or high reflexivity and minimal
  subtext (a diarist who says exactly what they think and feel).

- **resonance** tracks *associative and emotional depth*.  Resonance
  is about the layers within language itself — metaphor, allusion,
  connotation.  Reflexivity is about the writer's relationship to
  their own text — do they see themselves seeing?  A resonant poem
  about autumn leaves may carry no reflexivity; a flat sentence like
  "I'm not sure I'm the right person to judge this" is pure
  reflexivity.

- **voice_consistency** tracks *whether the writer's voice remains
  stable across the text*.  Voice consistency is about continuity;
  reflexivity is about depth.  A consistently breezy voice may lack
  reflexivity entirely; a reflexive voice may shift between
  confidence and doubt as the writer examines their own assumptions.

Reflexivity asks: **does the writer demonstrate awareness of their
own act of writing, thinking, and knowing — or do they deliver
content as if it exists independent of any particular mind?**

Dimensions
----------

===========================  ===========================================
metric                       meaning
===========================  ===========================================
self_reference_density       fraction of sentences containing explicit
                             first-person authorial presence: "I think",
                             "I believe", "in my experience", "I would
                             argue", "I confess", "I wonder", "it seems
                             to me", "from where I stand"; the writer
                             acknowledges they are *someone* producing
                             this text, not a transparent conduit for
                             information
metacognition_ratio            fraction of sentences that demonstrate
                             thinking about thinking: "the more I
                             consider", "on reflection", "my initial
                             instinct was... but", "I find myself
                             returning to", "what strikes me is",
                             "I'm aware that", "I notice that I",
                             "the question I keep asking"; these
                             phrases signal the writer observing their
                             own cognitive process — awareness turned
                             inward
perspective_acknowledgment     fraction of sentences that explicitly
                             recognize the existence of alternative
                             viewpoints: "others might see", "one could
                             argue", "from a different angle", "it
                             depends on", "there are those who", "not
                             everyone would agree", "the counter-
                             argument is", "seen from outside";
                             acknowledging other perspectives signals
                             that the writer understands their view is
                             situated, not universal
epistemic_humility_ratio        fraction of sentences expressing
                             uncertainty, provisional knowledge, or
                             limits of knowing: "I'm not sure",
                             "perhaps", "it may be that", "I don't
                             know", "this could be wrong", "evidence
                             suggests but doesn't prove", "as far as I
                             can tell", "I may be oversimplifying",
                             "the honest answer is I don't know";
                             epistemic humility is a cornerstone of
                             reflexivity — it takes self-awareness to
                             acknowledge the limits of one's knowledge
growth_marker_density           fraction of sentences that signal
                             evolution in the writer's understanding:
                             "I used to think... now I", "over time
                             I've come to", "looking back", "I was
                             wrong about", "my thinking has shifted",
                             "I've since realized", "what I didn't
                             understand then", "with the benefit of
                             hindsight", "I've learned that"; growth
                             markers reveal a writer who sees
                             themselves changing — reflexivity
                             extended across time
===========================  ===========================================

Reflexivity classes

====================  ==================================================
class                 meaning
====================  ==================================================
deeply_reflexive      >= 0.50 composite score; the writer consistently
                      demonstrates awareness of their own thinking and
                      writing process; the text is a dialogue between
                      the writer and their own mind; typical of
                      memoir, personal essays, philosophical writing,
                      and the most thoughtful criticism
reflexive             0.35–0.49 composite score; the writer regularly
                      acknowledges their perspective, uncertainty, or
                      growth; the reader feels they are in the company
                      of a mind examining itself; typical of quality
                      journalism, opinion columns, and reflective
                      nonfiction
aware                 0.20–0.34 composite score; the writer occasionally
                      signals self-awareness through hedging or
                      perspective acknowledgment but mostly delivers
                      content without visible mediation; typical of
                      competent analytical writing and literary
                      criticism
detached              0.08–0.19 composite score; the writer rarely
                      acknowledges their own presence or the situated
                      nature of their viewpoint; text is delivered as
                      if from nowhere; typical of news reporting,
                      academic papers, and technical documentation
absent                < 0.08 composite score; the writer shows no
                      discernible self-awareness; text presents itself
                      as unmediated truth without any acknowledgment
                      of authorial perspective; typical of propaganda,
                      poorly written opinion pieces, and
                      machine-generated content
====================  ==================================================

Composite score
---------------

The composite reflexivity_index is a weighted average::

    reflexivity_index = (
        self_reference_density        * 0.20 +
        metacognition_ratio           * 0.25 +
        perspective_acknowledgment    * 0.20 +
        epistemic_humility_ratio      * 0.20 +
        growth_marker_density         * 0.15
    )

Weights reflect diagnostic importance: metacognition (0.25) is the
core of reflexivity — thinking about thinking is the defining act
of self-awareness.  Self-reference (0.20), perspective acknowledgment
(0.20), and epistemic humility (0.20) are equally important facets
that together paint the writer's relationship to their own mind and
to other minds.  Growth markers (0.15) are temporally extended and
thus less frequent but highly diagnostic when present.

Usage
-----

    from iamai.writer_reflexivity import WriterReflexivity

    wr = WriterReflexivity()
    result = wr.measure(text)
    print(result["reflexivity_index"])      # 0.0–1.0
    print(result["classification"])         # deeply_reflexive|reflexive|aware|detached|absent
    print(result["self_reference_density"]) # 0.0–1.0
"""

import re
from typing import Dict, List, Set


# --- Self-reference patterns ---

SELF_REFERENCE_PATTERNS: List[str] = [
    r'\bI\s+(?:think|believe|feel|suspect|wonder|imagine|suppose|'
    r'guess|reckon|would\s+argue|would\s+say|would\s+suggest|'
    r'confess|admit|maintain|contend|hold)\b',
    r'\b(?:in\s+my|from\s+my|to\s+my|by\s+my)\s+(?:view|opinion|'
    r'experience|understanding|reading|estimation|account|reckoning|'
    r'lights|judgment|judgement)\b',
    r'\b(?:it\s+seems|it\s+appears|it\s+strikes)\s+(?:me|to\s+me)\b',
    r'\bfrom\s+where\s+I\s+(?:stand|sit|look)\b',
    r'\b(?:as\s+I\s+see\s+it|the\s+way\s+I\s+see\s+it|as\s+far\s+as\s+I\'?m\s+concerned)\b',
    r'\bmy\s+(?:sense|feeling|instinct|intuition|take|view|read|'
    r'understanding|impression|position)\s+(?:is|was|has\s+been|'
    r'would\s+be|tells\s+me)\b',
    r'\bI\s+(?:am|was|have\s+been|will\s+be)\s+(?:not\s+sure|'
    r'uncertain|unsure|ambivalent|conflicted|torn|undecided)\b',
]

# --- Metacognition patterns ---

METACOGNITION_PATTERNS: List[str] = [
    r'\b(?:the\s+more\s+I\s+(?:think|consider|reflect|ponder|examine|'
    r'look\s+at|turn\s+over)|on\s+reflection|on\s+further\s+thought|'
    r'after\s+(?:some|much|a\s+great\s+deal\s+of)\s+(?:thought|'
    r'reflection|consideration))\b',
    r'\b(?:my\s+(?:initial|first|original|instinctive|gut)\s+'
    r'(?:instinct|reaction|impulse|response|feeling|thought)\s+'
    r'(?:was|is|has\s+always\s+been))\b',
    r'\b(?:but\s+then\s+I|and\s+yet\s+I|though\s+I|although\s+I|'
    r'despite\s+my|in\s+spite\s+of\s+my)\b',
    r'\b(?:I\s+(?:find|catch)\s+myself|I\s+keep\s+(?:coming\s+back|'
    r'returning)|I\s+notice\s+that\s+I|I\'?m\s+aware\s+that)\b',
    r'\b(?:what\s+strikes\s+me|what\s+I\s+keep\s+(?:asking|coming\s+back|'
    r'returning)\s+to|the\s+question\s+I\s+(?:keep|can\'?t\s+stop)\s+'
    r'(?:asking|wrestling\s+with))\b',
    r'\b(?:thinking\s+about\s+thinking|awareness\s+of\s+(?:my\s+own|'
    r'the)\s+(?:process|act|habit)|observing\s+(?:myself|my\s+own))\b',
    r'\b(?:I\s+realize\s+that\s+I|I\s+recognize\s+that\s+I|'
    r'I\'?m\s+conscious\s+of\s+(?:the\s+fact\s+that|my\s+own))\b',
]

# --- Perspective acknowledgment patterns ---

PERSPECTIVE_PATTERNS: List[str] = [
    r'\b(?:others?\s+might|some\s+(?:might|would|could)|one\s+could|'
    r'you\s+could)\s+(?:argue|say|see|think|feel|believe|disagree|'
    r'object|protest|counter)\b',
    r'\b(?:from\s+a\s+(?:different|another|opposing|alternative)\s+'
    r'(?:angle|perspective|viewpoint|standpoint|position)|seen\s+'
    r'(?:from\s+outside|differently|another\s+way))\b',
    r'\b(?:there\s+are\s+those\s+who|not\s+everyone\s+(?:would|will|'
    r'can)|many\s+(?:would|might|could))\s+(?:agree|see|disagree|'
    r'dispute|differ|object)\b',
    r'\b(?:the\s+counter.?argument|the\s+opposing\s+view|the\s+other|'
    r'(?:a|one)\s+valid\s+(?:criticism|objection|point))\s+(?:is|'
    r'would\s+be|runs|goes)\b',
    r'\b(?:it\s+depends\s+on|this\s+varies\s+(?:by|depending|across)|'
    r'context\s+dependent|contingent\s+on)\b',
    r'\b(?:fair\s+enough|that\'?s\s+a\s+(?:fair|valid|reasonable)\s+'
    r'(?:point|objection|criticism|question)|I\s+(?:see|take|hear)\s+'
    r'(?:the|your|that)\s+point)\b',
]

# --- Epistemic humility patterns ---

EPISTEMIC_HUMILITY_PATTERNS: List[str] = [
    r'\bI\s+(?:don\'?t|do\s+not)\s+(?:know|claim|pretend|assume|'
    r'presume)\b',
    r'\bI\s+(?:may|might|could)\s+(?:be\s+wrong|be\s+mistaken|'
    r'be\s+oversimplifying|be\s+missing|have\s+missed)\b',
    r'\b(?:perhaps|possibly|maybe|conceivably|arguably|plausibly)\b',
    r'\b(?:it\s+(?:may|might|could)\s+be\s+that|this\s+could\s+be|'
    r'evidence\s+(?:suggests|hints|implies)\s+but\s+(?:doesn\'?t|'
    r'does\s+not)\s+prove)\b',
    r'\b(?:as\s+far\s+as\s+I\s+(?:know|can\s+tell|understand)|'
    r'to\s+the\s+best\s+of\s+my\s+knowledge|for\s+all\s+I\s+know)\b',
    r'\b(?:the\s+honest\s+(?:answer|truth)\s+is|I\'?ll\s+be\s+honest|'
    r'frankly|in\s+all\s+honesty|I\s+have\s+to\s+admit)\b',
    r'\b(?:I\s+(?:hope|trust)\s+I\'?m\s+not|I\s+don\'?t\s+want\s+to|'
    r'I\'?d\s+hesitate\s+to)\s+(?:overstate|overgeneralize|claim|'
    r'presume|assume)\b',
]

# --- Growth marker patterns ---

GROWTH_MARKER_PATTERNS: List[str] = [
    r'\bI\s+(?:used\s+to|once|formerly)\s+(?:think|believe|assume|'
    r'imagine|suppose)\b',
    r'\b(?:over\s+time|gradually|slowly|eventually)\s+I\'?(?:ve|\s+have)?'
    r'\s+(?:come\s+to|learned|realized|discovered|understood)\b',
    r'\b(?:looking\s+back|in\s+retrospect|with\s+(?:the\s+benefit\s+of|'
    r'20/?20)\s+hindsight)\b',
    r'\bI\s+was\s+(?:wrong|mistaken|off\s+base|incorrect)\s+about\b',
    r'\b(?:my\s+thinking\s+has\s+(?:shifted|evolved|changed|developed)|'
    r'I\'?ve\s+(?:since|now)\s+realized|I\'?(?:ve|\s+have)\s+changed\s+'
    r'my\s+mind)\b',
    r'\b(?:what\s+I\s+didn\'?t\s+understand\s+(?:then|at\s+the\s+time|'
    r'before)|what\s+I\'?(?:ve|\s+have)\s+learned\s+since)\b',
    r'\b(?:I\'?(?:ve|\s+have)\s+since\s+(?:come\s+to|learned|realized)|'
    r'now\s+I\s+(?:see|understand|think|believe))\b',
]


class WriterReflexivity:
    """Measure the self-awareness depth of prose."""

    def __init__(self):
        self.self_reference = [
            re.compile(p, re.IGNORECASE) for p in SELF_REFERENCE_PATTERNS
        ]
        self.metacognition = [
            re.compile(p, re.IGNORECASE) for p in METACOGNITION_PATTERNS
        ]
        self.perspective = [
            re.compile(p, re.IGNORECASE) for p in PERSPECTIVE_PATTERNS
        ]
        self.epistemic_humility = [
            re.compile(p, re.IGNORECASE) for p in EPISTEMIC_HUMILITY_PATTERNS
        ]
        self.growth_markers = [
            re.compile(p, re.IGNORECASE) for p in GROWTH_MARKER_PATTERNS
        ]

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        sentences = re.split(r'[.!?]+', text)
        return [s.strip() for s in sentences if s.strip()]

    def _count_matching(self, sentences: List[str], patterns: List) -> int:
        """Count sentences matching at least one pattern."""
        count = 0
        for sentence in sentences:
            for pattern in patterns:
                if pattern.search(sentence):
                    count += 1
                    break
        return count

    def measure_self_reference_density(self, text: str) -> float:
        """Fraction of sentences with explicit authorial presence."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        return self._count_matching(sentences, self.self_reference) / len(sentences)

    def measure_metacognition_ratio(self, text: str) -> float:
        """Fraction of sentences demonstrating thinking about thinking."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        return self._count_matching(sentences, self.metacognition) / len(sentences)

    def measure_perspective_acknowledgment(self, text: str) -> float:
        """Fraction of sentences recognizing alternative viewpoints."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        return self._count_matching(sentences, self.perspective) / len(sentences)

    def measure_epistemic_humility_ratio(self, text: str) -> float:
        """Fraction of sentences expressing uncertainty or limits of knowing."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        return self._count_matching(sentences, self.epistemic_humility) / len(sentences)

    def measure_growth_marker_density(self, text: str) -> float:
        """Fraction of sentences signaling evolution in understanding."""
        sentences = self._split_sentences(text)
        if not sentences:
            return 0.0
        return self._count_matching(sentences, self.growth_markers) / len(sentences)

    def compute_reflexivity_index(
        self,
        self_ref: float,
        metacog: float,
        perspective: float,
        epistemic: float,
        growth: float,
    ) -> float:
        """Compute weighted composite score."""
        return (
            self_ref * 0.20
            + metacog * 0.25
            + perspective * 0.20
            + epistemic * 0.20
            + growth * 0.15
        )

    def classify(self, index: float) -> str:
        """Classify reflexivity level."""
        if index >= 0.50:
            return "deeply_reflexive"
        elif index >= 0.35:
            return "reflexive"
        elif index >= 0.20:
            return "aware"
        elif index >= 0.08:
            return "detached"
        else:
            return "absent"

    def measure(self, text: str) -> Dict:
        """Measure all reflexivity metrics for given text."""
        self_ref = self.measure_self_reference_density(text)
        metacog = self.measure_metacognition_ratio(text)
        perspective = self.measure_perspective_acknowledgment(text)
        epistemic = self.measure_epistemic_humility_ratio(text)
        growth = self.measure_growth_marker_density(text)
        index = self.compute_reflexivity_index(
            self_ref, metacog, perspective, epistemic, growth
        )
        classification = self.classify(index)

        return {
            "self_reference_density": round(self_ref, 4),
            "metacognition_ratio": round(metacog, 4),
            "perspective_acknowledgment": round(perspective, 4),
            "epistemic_humility_ratio": round(epistemic, 4),
            "growth_marker_density": round(growth, 4),
            "reflexivity_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    # Demo
    deeply_reflexive_text = """I think the more I consider this question,
    the less certain I become. My initial instinct was to dismiss the
    argument outright, but then I find myself returning to it. Perhaps
    I'm oversimplifying. Others might argue that the evidence is
    conclusive, and that's a fair point — but from where I stand, the
    picture remains murky. I used to think this was straightforward.
    Over time I've come to realize it is anything but. I don't know
    the answer, and I'm not sure anyone does. What strikes me is how
    much my thinking has shifted since I first encountered this problem.
    Looking back, I was wrong about several key assumptions. The honest
    truth is that this question has humbled me."""

    absent_text = """The data shows a clear trend. Revenue increased
    by twelve percent in the third quarter. The market responded
    positively to the new product launch. Customer satisfaction scores
    improved across all segments. The strategy proved effective.
    Competitors adjusted their pricing in response. The outlook remains
    favorable for the coming quarters."""

    wr = WriterReflexivity()

    print("=== Deeply Reflexive Text ===")
    result = wr.measure(deeply_reflexive_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")

    print("\n=== Absent Text ===")
    result = wr.measure(absent_text)
    for key, value in result.items():
        print(f"{key:30s} {value}")
