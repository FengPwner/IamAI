#!/usr/bin/env python3
"""writer_imperative_density — measure how much prose relies on imperative mood.

Imperatives are the prose of action: the writer reaching through the
page and telling the reader what to do.  They are the default voice of
recipes, manuals, tutorials, military orders, and parental advice.
They turn prose from description into instruction, from observation
into choreography.

Imperative density is not a quality metric.  A cookbook *should* be
dense with imperatives — "Chop the onions. Heat the oil. Add the
garlic."  A novel should use them sparingly, mostly in dialogue.
A philosophical essay might avoid them entirely.  The right density
depends on genre, audience, and the writer's relationship with
authority.

This module measures **how much of a text is spent directing the
reader** — bare commands, softened requests, hortative constructions,
procedural instructions, and prohibitions.

Orthogonality to other metrics
-------------------------------

- **conviction** tracks assertiveness.  Imperatives can carry strong
  conviction ("Do this now.") or weak conviction ("Maybe try this.").
  But conviction also operates in declarative sentences ("This is
  absolutely true.") that contain no imperative at all.  Conviction
  measures force of assertion; imperatives measure direction of
  action.

- **formality** tracks register.  Imperatives can be formal ("Please
  submit the completed form.") or informal ("Just do it.").  Formality
  also operates in declarative prose through vocabulary choice and
  syntactic complexity.  Formality measures social distance;
  imperatives measure instructional intent.

- **hedging_density** tracks qualification and uncertainty.  Some
  hedging uses imperative-like structures ("Consider the possibility
  that..."), but hedging also operates through modal verbs, epistemic
  markers, and attribution shields in purely declarative text.
  Hedging measures caution; imperatives measure direction.

- **fragment_density** tracks syntactic incompleteness.  Short
  imperatives ("Stop." "Listen." "Wait.") are also fragments, but
  imperatives can be full sentences ("Please review the attached
  document before the meeting.") and fragments can be non-imperative
  ("A cold morning." "Gone.").  Fragments measure form; imperatives
  measure function.

- **pacing** tracks speed.  Imperatives tend to accelerate prose
  (they're often short), but pacing also responds to sentence length,
  paragraph breaks, and information density.  A sequence of long,
  complex imperative sentences can pace slowly.  Pacing measures
  tempo; imperatives measure mood.

Imperative asks: **is the text directing the reader to act, and
how much of its language is spent on that effort?**

Dimensions
----------

==============================  =============================================
metric                          meaning
==============================  =============================================
direct_imperative_rate          frequency of sentences using bare imperative
                                mood per sentence: verbs in base form without
                                explicit subject, directing the reader to act
                                — "Consider this." "Run the tests." "Open the
                                file." "Stop." "Read the documentation."
                                "Compare the results."
softened_imperative_rate        frequency of imperative sentences modified by
                                politeness markers, mitigators, or hedging
                                words per sentence: "Please consider..."
                                "Do try to..." "Kindly submit..." "Just look
                                at..." "Perhaps try..." "You might want to..."
hortative_rate                  frequency of hortative constructions per
                                sentence: first-person-plural imperatives
                                using "let us" or "let's" — "Let's examine
                                the data." "Let us consider..." "Let me
                                show you..." "Let's not forget..."
instructional_rate              frequency of procedural/instructional markers
                                per sentence: sequential directives and
                                procedural language — "First, ..." "Next, ..."
                                "Then, ..." "After that, ..." "Make sure
                                to..." "Remember to..." "Be sure to..."
                                "The key is to..."
negative_imperative_rate        frequency of prohibitions per sentence:
                                negative imperatives telling the reader what
                                *not* to do — "Don't..." "Never..." "Avoid..."
                                "Refrain from..." "Do not..." "Steer clear
                                of..." "Be careful not to..."
==============================  =============================================

From these five dimensions a composite **imperative_density_index**
is computed as a weighted average and classified:

===========================  =================================================
class                        meaning
===========================  =================================================
declarative                  index < 0.05 — prose uses almost no imperatives
occasionally_directive       0.05 <= index < 0.15 — occasional directives
moderately_imperative        0.15 <= index < 0.30 — regular imperative use
heavily_instructional        0.30 <= index < 0.50 — text is primarily
                             instructional
command_saturated            index >= 0.50 — text is almost entirely
                             imperative (recipes, manuals, orders)
===========================  =================================================
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Pattern libraries
# ---------------------------------------------------------------------------

DIRECT_IMPERATIVE_PATTERNS: List[re.Pattern] = [
    # Base-form verb starting a sentence (short commands): "Stop." "Listen." "Wait."
    re.compile(r"^\s*(?:stop|wait|listen|look|come|go|run|stay|leave|sit|stand|move|turn|open|close|read|write|think|remember|forget|try|begin|start|end|breathe|watch|notice|observe|imagine|consider|compare|review|check|verify|test|measure|analyze|evaluate|assess|examine|inspect|explore|investigate|calculate|compute|count|find|locate|identify|determine|establish|confirm|ensure|note|mark|record|save|store|keep|hold|take|give|make|set|put|place|add|remove|include|exclude|send|receive|accept|reject|approve|deny|create|build|design|develop|implement|execute|deploy|install|configure|setup|initialize|reset|restart|continue|proceed|follow|apply|use|choose|select|pick|prefer|adopt|adapt|adjust|modify|change|update|upgrade|replace|fix|repair|solve|resolve|handle|manage|address|tackle|approach|avoid|prevent|reduce|increase|improve|optimize|simplify|clarify|explain|describe|define|state|express|articulate|formulate|present|show|display|demonstrate|illustrate|highlight|emphasize|stress|underline|mention|reference|cite|quote|paraphrase|summarize|outline|list|enumerate|detail|specify|indicate|signal|note)\b[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # Transitive verb + object (longer directives): "Read the documentation." "Open the file."
    re.compile(r"^\s*(?:read|open|close|write|edit|create|delete|remove|add|insert|update|modify|check|verify|validate|test|run|execute|build|compile|deploy|install|configure|restart|reset|review|examine|inspect|analyze|evaluate|compare|contrast|consider|imagine|remember|forget|try|attempt|make|take|give|set|put|place|keep|hold|send|deliver|submit|file|register|apply|use|choose|select|pick|find|locate|search|browse|explore|navigate|follow|trace|track|monitor|observe|watch|listen|hear|note|record|save|store|archive|backup|restore|recover|retrieve|fetch|load|import|export|download|upload|share|publish|print|display|show|hide|reveal|expose|cover|protect|secure|encrypt|decrypt|encode|decode|parse|format|render|process|transform|convert|translate|interpret|explain|describe|define|state|express|articulate|present|demonstrate|illustrate|highlight|emphasize)\s+(?:the|a|an|this|that|these|those|your|my|our|its|all|each|every|some|any|no)\b[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # Verb + adverb/complement: "Look carefully." "Think again." "Try harder."
    re.compile(r"^\s*(?:look|think|try|read|write|speak|listen|watch|wait|move|walk|run|go|come|stop|start|begin|end|work|play|act|respond|react|reply|answer|ask|tell|say)\s+(?:carefully|closely|quickly|slowly|gently|firmly|hard|harder|again|once\s+more|first|last|now|then|here|there|ahead|forward|back|away|together|alone|always|never)[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "See" as directive: "See also..." "See chapter..." "See the note..."
    re.compile(r"^\s*see\s+(?:also|further|chapter|section|page|table|figure|appendix|note|reference|below|above|previous|next)\b[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "Refer to" directive: "Refer to the documentation."
    re.compile(r"^\s*refer\s+to\b[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
]

SOFTENED_IMPERATIVE_PATTERNS: List[re.Pattern] = [
    # "Please" + verb: "Please consider..." "Please note..." "Please submit..."
    re.compile(r"^\s*please\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "Kindly" + verb: "Kindly review..." "Kindly submit..."
    re.compile(r"^\s*kindly\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "Do" + verb (emphatic polite): "Do try this." "Do consider..."
    re.compile(r"^\s*do\s+(?:try|consider|note|remember|keep|take|give|let|tell|ask|feel|excuse|forgive|mind|bear)\b[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "Just" + verb: "Just look at..." "Just run..." "Just try..."
    re.compile(r"^\s*just\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "Perhaps" / "Maybe" + imperative: "Perhaps consider..." "Maybe try..."
    re.compile(r"^\s*(?:perhaps|maybe)\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "You might want to" / "You may want to": suggestion imperatives
    re.compile(r"^\s*you\s+(?:might|may|could|should)\s+(?:want\s+to|wish\s+to|need\s+to|like\s+to)\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "Try to" / "Try + -ing" soft suggestion: "Try running..." "Try to keep..."
    re.compile(r"^\s*try\s+(?:to\s+[\w-]+|[\w-]+ing)[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "Consider + -ing" / "Consider + noun": gentle suggestion
    re.compile(r"^\s*consider\s+(?:[\w-]+ing|[\w\s,.'-]+)[.!?]\s*$", re.IGNORECASE),
    # "Feel free to": permissive imperative
    re.compile(r"^\s*feel\s+free\s+to\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "Don't hesitate to" / "Don't be afraid to": encouraging imperatives
    re.compile(r"^\s*don'?t\s+(?:hesitate|be\s+afraid|worry|fear)\s+to\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
]

HORTATIVE_PATTERNS: List[re.Pattern] = [
    # "Let's" + verb: "Let's examine..." "Let's try..." "Let's not forget..."
    re.compile(r"^\s*let'?s\s+(?:not\s+)?[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "Let us" + verb: "Let us consider..." "Let us examine..."
    re.compile(r"^\s*let\s+us\s+(?:not\s+)?[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "Let me" + verb: "Let me show..." "Let me explain..."
    re.compile(r"^\s*let\s+me\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "Let's" standalone / rhetorical: "Let's go." "Let's see."
    re.compile(r"^\s*let'?s\s+(?:go|see|try|begin|start|continue|proceed|move|take|look|check|find|get|put|make|do|say|face|hope|wait|stop|pause|rest|imagine|think|consider|remember|forget|pray|wish|dream)\s*[.!?]\s*$", re.IGNORECASE),
    # "Shall we" + verb: "Shall we begin?" "Shall we proceed?"
    re.compile(r"^\s*shall\s+we\s+[\w-]+[\w\s,.'-]*[?!.]\s*$", re.IGNORECASE),
]

INSTRUCTIONAL_PATTERNS: List[re.Pattern] = [
    # Sequential markers + imperative: "First, open the file." "Next, run the tests."
    re.compile(r"^\s*(?:first|second|third|fourth|fifth|next|then|afterwards|after\s+that|finally|lastly|last)\s*,?\s*[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "Make sure to" / "Be sure to": procedural emphasis
    re.compile(r"^\s*(?:make\s+sure|be\s+sure)\s+to\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "Remember to" / "Don't forget to": memory imperatives
    re.compile(r"^\s*(?:remember|don'?t\s+forget)\s+to\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "The key is to" / "The trick is to": instructional framing
    re.compile(r"^\s*(?:the\s+key|the\s+trick|the\s+secret|the\s+important\s+thing|the\s+main\s+thing|the\s+goal|the\s+aim|the\s+point)\s+is\s+to\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "You need to" / "You have to" / "You must": necessity imperatives
    re.compile(r"^\s*you\s+(?:need\s+to|have\s+to|must|should|ought\s+to|are\s+(?:going\s+to|supposed\s+to|meant\s+to))\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "What you need to do is": extended instructional framing
    re.compile(r"^\s*what\s+you\s+(?:need|have|want|should)\s+to?\s*do\s+is\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "In order to" purpose + directive: "In order to fix this, run..."
    re.compile(r"^\s*in\s+order\s+to\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
]

NEGATIVE_IMPERATIVE_PATTERNS: List[re.Pattern] = [
    # "Don't" + verb: "Don't worry." "Don't forget." "Don't run this."
    re.compile(r"^\s*don'?t\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "Do not" + verb: "Do not attempt..." "Do not exceed..."
    re.compile(r"^\s*do\s+not\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "Never" + verb: "Never ignore..." "Never skip..."
    re.compile(r"^\s*never\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "Avoid" + gerund/noun: "Avoid using..." "Avoid this."
    re.compile(r"^\s*avoid\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "Refrain from" + gerund: "Refrain from editing..."
    re.compile(r"^\s*refrain\s+from\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "Steer clear of" / "Stay away from": cautionary imperatives
    re.compile(r"^\s*(?:steer\s+clear\s+of|stay\s+away\s+from|keep\s+away\s+from|keep\s+(?:your|my)\s+\w+\s+(?:away|off|out)\s+(?:of|from))\s*[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "Be careful not to" / "Take care not to": cautionary imperatives
    re.compile(r"^\s*(?:be\s+careful|take\s+care|be\s+sure|make\s+sure)\s+(?:not\s+to|you\s+don'?t)\s+[\w-]+[\w\s,.'-]*[.!?]\s*$", re.IGNORECASE),
    # "No" + gerund (sign-style): "No smoking." "No parking." "No entry."
    re.compile(r"^\s*no\s+[\w-]+ing\s*[.!?]\s*$", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences, preserving terminal punctuation."""
    parts = re.split(r'(?<=[.!?…—–])\s+', text)
    return [p.strip() for p in parts if p.strip()]


def _count_matching(sentences: List[str], patterns: List[re.Pattern]) -> int:
    """Count sentences matching at least one pattern."""
    count = 0
    for sent in sentences:
        if any(p.search(sent) for p in patterns):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class WriterImperativeDensity:
    """Measure how much prose relies on imperative mood.

    Imperatives are the language of direction: commands, requests,
    instructions, and prohibitions that tell the reader what to do
    (or not to do).
    """

    def __init__(self):
        self.direct_imperative = DIRECT_IMPERATIVE_PATTERNS
        self.softened_imperative = SOFTENED_IMPERATIVE_PATTERNS
        self.hortative = HORTATIVE_PATTERNS
        self.instructional = INSTRUCTIONAL_PATTERNS
        self.negative_imperative = NEGATIVE_IMPERATIVE_PATTERNS

    def measure_direct_imperative_rate(self, text: str) -> float:
        """Rate of sentences using bare imperative mood."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_matching(sentences, self.direct_imperative)
        return count / len(sentences)

    def measure_softened_imperative_rate(self, text: str) -> float:
        """Rate of sentences using softened/polite imperatives."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_matching(sentences, self.softened_imperative)
        return count / len(sentences)

    def measure_hortative_rate(self, text: str) -> float:
        """Rate of sentences using hortative constructions."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_matching(sentences, self.hortative)
        return count / len(sentences)

    def measure_instructional_rate(self, text: str) -> float:
        """Rate of sentences using procedural/instructional markers."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_matching(sentences, self.instructional)
        return count / len(sentences)

    def measure_negative_imperative_rate(self, text: str) -> float:
        """Rate of sentences using prohibitions/negative imperatives."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_matching(sentences, self.negative_imperative)
        return count / len(sentences)

    def compute_imperative_density_index(
        self,
        direct: float,
        softened: float,
        hortative: float,
        instructional: float,
        negative: float,
    ) -> float:
        """Compute composite imperative density index (0.0 to 1.0).

        Weights: direct 0.30, softened 0.15, hortative 0.15,
        instructional 0.25, negative 0.15.
        """
        index = (
            0.30 * direct
            + 0.15 * softened
            + 0.15 * hortative
            + 0.25 * instructional
            + 0.15 * negative
        )
        return min(index, 1.0)

    def classify(self, index: float) -> str:
        """Classify imperative density into descriptive categories."""
        if index >= 0.50:
            return "command_saturated"
        elif index >= 0.30:
            return "heavily_instructional"
        elif index >= 0.15:
            return "moderately_imperative"
        elif index >= 0.05:
            return "occasionally_directive"
        else:
            return "declarative"

    def measure(self, text: str) -> Dict[str, Any]:
        """Full measurement of imperative density in text."""
        direct = self.measure_direct_imperative_rate(text)
        softened = self.measure_softened_imperative_rate(text)
        hortative = self.measure_hortative_rate(text)
        instructional = self.measure_instructional_rate(text)
        negative = self.measure_negative_imperative_rate(text)
        index = self.compute_imperative_density_index(
            direct, softened, hortative, instructional, negative
        )
        classification = self.classify(index)

        return {
            "direct_imperative_rate": round(direct, 4),
            "softened_imperative_rate": round(softened, 4),
            "hortative_rate": round(hortative, 4),
            "instructional_rate": round(instructional, 4),
            "negative_imperative_rate": round(negative, 4),
            "imperative_density_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    instructional_text = """First, open the terminal. Next, navigate to
    the project directory. Run the install command. Make sure to check
    the output for errors. Don't skip the tests. After that, configure
    the settings file. Remember to set the API key. Then, start the
    server. Let's verify everything works. Please note the port number."""

    narrative_text = """The rain fell steadily through the afternoon.
    She watched the water collect in the gutters, forming small rivers
    along the pavement. The coffee had gone cold hours ago. A cat
    sat in the window across the street, unmoving. The light changed
    from grey to a deeper grey. Somewhere a door closed. The evening
    arrived without ceremony."""

    wid = WriterImperativeDensity()

    print("=== Instructional Text ===")
    result = wid.measure(instructional_text)
    for key, value in result.items():
        print(f"{key:35s} {value}")

    print("\n=== Narrative Text ===")
    result = wid.measure(narrative_text)
    for key, value in result.items():
        print(f"{key:35s} {value}")
