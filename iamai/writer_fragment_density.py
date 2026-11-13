#!/usr/bin/env python3
"""writer_fragment_density — measure how much prose relies on sentence fragments.

Fragments are the deliberate incompleteness of syntax: a phrase posed
as a sentence, a word standing alone, a thought that arrives without
the furniture of a full clause.  They are the prose equivalent of a
photograph cropped tight — what is left out *is* the composition.

Fragment density is not a quality metric.  Hemingway's staccato,
Joan Didion's list-like observations, and the clipped voice of noir
fiction *require* fragments — the incompleteness is the style.
Academic papers and legal briefs should have near-zero fragment
density.  Blog posts and personal essays land somewhere in between.
The right density depends on genre, voice, and the writer's
relationship with silence.

This module measures **how much of a text is spent on fragmentary
structures** — verbless phrases, subjectless utterances, single-word
sentences, conversational fragments, and trailing-off constructions.

Orthogonality to other metrics
-------------------------------

- **ellipsis_density** tracks what is left unsaid — gaps in meaning,
  trailing thoughts, deliberate omission.  Fragments and ellipsis
  overlap when a fragment trails off ("If only..."), but a fragment
  can be sharp and complete in its incompleteness ("The usual.")
  while ellipsis can occur inside a full sentence ("She was, well,
  somewhat...").  Fragments are structural; ellipsis is semantic.

- **concision** tracks economy of expression — saying more with
  fewer words.  Fragments are concise by definition, but concision
  also operates through tight full sentences.  A fragment drops
  syntax entirely; a concise sentence compresses within syntax.
  Concision is about density of meaning; fragments are about
  density of *form*.

- **sentence_variety** tracks variation in sentence length and
  structure.  Fragments contribute to variety (short fragments
  between long sentences), but variety operates at the macro
  level while fragments are a specific micro-structural choice.
  You can have variety without fragments (long, medium, short
  complete sentences) and fragments without variety (all fragments,
  all the same length).

- **pacing** tracks the speed at which prose moves.  Fragments
  accelerate pace — they read fast — but pacing also responds to
  sentence length, paragraph breaks, dialogue, and information
  density.  A fragment-rich text can pace quickly or slowly
  depending on what the fragments contain.

- **musicality** tracks rhythm, alliteration, and sonic patterning.
  Fragments can be musical ("Darkness. Silence. Rain.") but
  musicality also operates within full sentences through meter,
  sound repetition, and clause length.  Fragments create rhythm
  through *absence* of expected structure; musicality creates it
  through *presence* of sonic pattern.

- **conviction** tracks assertiveness.  Single-word fragments
  ("Never." "Impossible.") can carry enormous conviction, while
  other fragments ("Maybe. Sort of. If that makes sense.") weaken
  it.  Conviction measures force; fragments measure form.

Fragment asks: **is the text deliberately breaking syntactic
completeness for stylistic effect, and how much of its language
is spent on that effort?**

Dimensions
----------

==============================  =============================================
metric                          meaning
==============================  =============================================
verbless_fragment_rate          frequency of sentences without a finite verb
                                per sentence: noun phrases, adjective phrases,
                                prepositional phrases, and adverb phrases
                                posing as complete sentences — "A cold morning."
                                "The usual." "Red, like wine." "In the garden,
                                after dark."
subjectless_fragment_rate       frequency of sentences without an explicit
                                subject per sentence: verb phrases standing
                                alone, imperatives used as fragments, and
                                participial phrases — "Running late." "Forgot
                                everything." "Sitting alone in the dark."
                                "Gone."
single_word_sentence_rate       frequency of single-word sentences per
                                sentence: one word posed as a complete
                                utterance — "Yes." "Never." "Impossible."
                                "Stop." "Enough." "Fine."
conversational_fragment_rate    frequency of conversational markers used as
                                standalone utterances per sentence: social
                                phrases, interjections, and response tokens
                                that stand alone — "Of course." "No way."
                                "Absolutely." "Sure thing." "My bad."
                                "Fair enough." "Touché."
trailing_fragment_rate          frequency of sentences that trail off or
                                break mid-thought per sentence: constructions
                                ending with ellipsis, em-dash, or other
                                interruption markers — "If only..." "And then—"
                                "Well, maybe..." "She was about to—"
==============================  =============================================

From these five dimensions a composite **fragment_density_index**
is computed as a weighted average and classified:

===========================  =================================================
class                        meaning
===========================  =================================================
syntactically_complete       index < 0.05 — prose uses almost no fragments
minimally_fragmentary        0.05 <= index < 0.15 — occasional fragments
moderately_fragmentary       0.15 <= index < 0.30 — regular fragment use
richly_fragmentary           0.30 <= index < 0.50 — fragments are a major mode
staccato                     index >= 0.50 — text is primarily fragmentary
===========================  =================================================
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Pattern libraries
# ---------------------------------------------------------------------------

VERBLESS_FRAGMENT_PATTERNS: List[re.Pattern] = [
    # Noun phrase only (short, no common finite verbs): "A cold morning." "The usual routine."
    re.compile(r"^\s*(?:a|an|the|this|that|these|those|my|your|his|her|its|our|their|no|some|any|every)\s+(?!.*\b(?:is|are|was|were|be|been|being|have|has|had|do|does|did|will|would|shall|should|may|might|must|can|could|reviewed|approved|met|confirmed|increased|remained|voted|presented|discussed|proposed|decided|announced|reported|stated|declared|explained|described|found|showed|demonstrated|published|created|developed|designed|built|completed|finished|started|began|ended|continued|changed|improved|reduced|added|removed|included|excluded|provided|received|accepted|rejected|offered|requested|demanded|required|expected|considered|suggested|recommended|argued|claimed|asserted|maintained|believed|thought|knew|understood|realized|recognized|observed|noticed|seemed|appeared|became|remained|stayed|grew|turned|proved|resulted|led|caused|affected|influenced|involved|contained|consisted|comprised|represented|expressed|indicated|revealed|identified|determined|established|achieved|accomplished|obtained|gained|acquired|produced|generated|yielded|contributed|supported|opposed|challenged|questioned|examined|investigated|explored|analyzed|evaluated|assessed|measured|tested|verified|validated|compared|contrasted|correlated|associated|connected|related|depended|relied|focused|concentrated|centered|addressed|concerned|regarded|reflected|illustrated|typified|exemplified|demonstrated|manifested|exhibited|displayed|revealed|disclosed|uncovered|exposed)\b)[\w\s,'-]{1,30}[.!?]\s*$", re.IGNORECASE),
    # Adjective phrase: "Cold and dark." "Red, like wine." "Beautiful, truly."
    re.compile(r"^\s*[\w-]+(?:\s*,\s*[\w-]+)*\s*(?:and|or|but)\s+[\w-]+[.!?]\s*$", re.IGNORECASE),
    # Prepositional phrase: "In the garden." "After dark." "At last."
    re.compile(r"^\s*(?:in|on|at|by|for|with|from|to|into|through|after|before|during|under|over|above|below|between|beyond|behind|beside|against|among|around|across|along|down|up|off|out|past|toward|towards|within|without)\s+[\w\s,'-]+[.!?]\s*$", re.IGNORECASE),
    # Adverb phrase: "Very slowly." "Too late." "Not anymore." "Once more."
    re.compile(r"^\s*(?:very|really|quite|rather|too|so|not|never|always|still|yet|once|again|no\s+longer|no\s+more)\s+[\w\s,'-]+[.!?]\s*$", re.IGNORECASE),
    # "The + adjective" as noun: "The usual." "The impossible." "The absurd."
    re.compile(r"^\s*the\s+[\w-]+[.!?]\s*$", re.IGNORECASE),
    # Possessive + noun phrase: "My mistake." "Her problem." "Their loss."
    re.compile(r"^\s*(?:my|your|his|her|its|our|their)\s+[\w\s,'-]+[.!?]\s*$", re.IGNORECASE),
    # Quantifier phrases (short, with "of" or just pronoun): "All of them." "None of this." "Some of us."
    re.compile(r"^\s*(?:all|none|some|most|many|few|several|both|neither|either|each|every\s+one)\s+of\s+(?:them|this|that|these|those|us|you|it|him|her|whom|which)[\w\s,'-]*[.!?]\s*$", re.IGNORECASE),
    # Appositive/label: "Item seven." "Chapter three." "Phase two." "Exhibit A."
    re.compile(r"^\s*[\w-]+\s+(?:one|two|three|four|five|six|seven|eight|nine|ten|[A-Z]|[0-9]+)[.!?]\s*$", re.IGNORECASE),
    # "Such + noun": "Such beauty." "Such waste." "Such is life."
    re.compile(r"^\s*such\s+[\w\s,'-]+[.!?]\s*$", re.IGNORECASE),
    # "Like + noun phrase": "Like a dream." "Like always." "Like nothing."
    re.compile(r"^\s*like\s+[\w\s,'-]+[.!?]\s*$", re.IGNORECASE),
    # Short two-word nominal: "Big deal." "No wonder." "Good question." "Nice try."
    re.compile(r"^\s*(?:big|no|good|nice|great|bad|poor|fine|small|old|new|real|true|fair|odd|strange|weird)\s+[\w-]+[.!?]\s*$", re.IGNORECASE),
]

SUBJECTLESS_FRAGMENT_PATTERNS: List[re.Pattern] = [
    # Present participle fragment (short phrases only): "Running late." "Sitting alone."
    re.compile(r"^\s*[\w-]+ing\b(?:\s+[\w'-]+){0,4}[.!?]\s*$", re.IGNORECASE),
    # Past participle fragment: "Gone." "Forgotten." "Left behind." "Done."
    re.compile(r"^\s*(?:gone|done|finished|lost|found|broken|forgotten|remembered|taken|given|left|kept|hidden|seen|heard|known|told|said|made|built|destroyed|abandoned|accepted|denied|approved|rejected|completed|started|stopped|changed|moved|placed|removed)\s*[\w\s,'.-]*[.!?]\s*$", re.IGNORECASE),
    # Past-tense verb without explicit subject: "Went to the store." "Forgot everything."
    re.compile(r"^\s*(?:went|came|saw|took|gave|made|did|said|told|asked|knew|thought|found|left|kept|lost|got|began|started|stopped|tried|used|called|needed|wanted|looked|seemed|felt|became|ran|walked|sat|stood|lay|waited|worked|played|lived|died|happened|appeared|disappeared)\s+[\w\s,'.-]*[.!?]\s*$", re.IGNORECASE),
    # Infinitive fragment: "To be or not to be." "To think of everything."
    re.compile(r"^\s*to\s+[\w\s,'.-]+[.!?]\s*$", re.IGNORECASE),
    # Imperative-as-fragment: "Stop." "Listen." "Wait." "Come here."
    re.compile(r"^\s*(?:stop|wait|listen|look|come|go|run|stay|leave|sit|stand|move|turn|open|close|read|write|think|remember|forget|try|begin|start|end|breathe|watch|notice|observe|imagine|consider)\s*[\w\s,'.-]*[.!?]\s*$", re.IGNORECASE),
    # Verb phrase with adverb: "Always was." "Never mind." "Not anymore."
    re.compile(r"^\s*(?:always|never|still|yet|not|barely|hardly|scarcely|almost|nearly)\s+[\w\s,'.-]+[.!?]\s*$", re.IGNORECASE),
    # Short verb-only: "Agreed." "Denied." "Confirmed." "Noted." "Understood."
    re.compile(r"^\s*(?:agreed|denied|confirmed|noted|understood|accepted|rejected|approved|done|finished|completed|decided|settled|resolved|determined|established|proven|shown|demonstrated|observed)\s*[.!?]\s*$", re.IGNORECASE),
]

SINGLE_WORD_SENTENCE_PATTERNS: List[re.Pattern] = [
    # Single word ending with terminal punctuation
    re.compile(r"^\s*[\w'-]+\s*[.!?]\s*$"),
    # Interjections: "Oh!" "Ah!" "Wow!" "Hey!" "Ouch!"
    re.compile(r"^\s*(?:oh|ah|wow|hey|ouch|oops|ugh|hm|hmm|aha|alas|bravo|cheers|darn|damn|gee|gosh|jeez|rats|yikes|yuck)\s*[.!]\s*$", re.IGNORECASE),
    # Affirmatives/negatives: "Yes." "No." "Maybe." "Perhaps." "Certainly."
    re.compile(r"^\s*(?:yes|no|maybe|perhaps|certainly|sure|absolutely|definitely|exactly|precisely|indeed|right|wrong|true|false|never|always|enough|fine|okay|ok)\s*[.!]\s*$", re.IGNORECASE),
    # Evaluative adjectives: "Impossible." "Ridiculous." "Perfect." "Terrible."
    re.compile(r"^\s*(?:impossible|ridiculous|perfect|terrible|wonderful|beautiful|horrible|amazing|awful|brilliant|stupid|obvious|absurd|insane|crazy|mad|lucky|unlucky|inevitable|unthinkable|unbelievable|incredible|remarkable|extraordinary|pathetic|tragic|comic|ironic|typical|classic|predictable|surprising)\s*[.!]\s*$", re.IGNORECASE),
    # Temporal: "Now." "Then." "Today." "Tomorrow." "Always." "Never."
    re.compile(r"^\s*(?:now|then|today|tomorrow|yesterday|always|never|sometimes|often|rarely|soon|later|before|after|since|once|again)\s*[.!]\s*$", re.IGNORECASE),
    # Pronouns as sentences: "Me." "Nobody." "Everyone." "Something." "Nothing."
    re.compile(r"^\s*(?:me|you|him|her|us|them|nobody|everybody|someone|everyone|something|nothing|anything|everything|anyone)\s*[.!]\s*$", re.IGNORECASE),
]

CONVERSATIONAL_FRAGMENT_PATTERNS: List[re.Pattern] = [
    # Social/response phrases
    re.compile(r"^\s*(?:of\s+course|no\s+way|no\s+problem|no\s+doubt|no\s+wonder|sure\s+thing|my\s+bad|fair\s+enough|good\s+enough|right\s+now|not\s+really|not\s+quite|not\s+bad|not\s+today|well\s+done|well\s+said|so\s+what|so\s+far|so\s+long|come\s+on|go\s+ahead|take\s+care|take\s+it\s+easy|hang\s+on|hold\s+on|shut\s+up|get\s+out|forget\s+it|leave\s+it|let\s+it\s+go|never\s+mind|you\s+bet|you\s+know|you\s+see|you\s+first|after\s+you|same\s+here|me\s+too|me\s+neither|sounds\s+good|sounds\s+fair|looks\s+good|looks\s+fine|works\s+for\s+me|makes\s+sense)\s*[.!]\s*$", re.IGNORECASE),
    # Discourse markers as standalone
    re.compile(r"^\s*(?:anyway|anyhow|however|meanwhile|therefore|thus|hence|otherwise|besides|moreover|furthermore|nevertheless|nonetheless|still|yet|instead|rather|perhaps|possibly|probably|certainly|definitely|obviously|clearly|evidently|apparently|supposedly|allegedly|reportedly|fortunately|unfortunately|interestingly|surprisingly|sadly|happily|thankfully|honestly|frankly|candidly|personally|generally|typically|usually|naturally|inevitably|predictably|ironically|curiously|strangely|oddly)\s*[,.!]\s*$", re.IGNORECASE),
    # Acknowledgment tokens: "Touché." "Voilà." "Bingo." "Eureka." "Checkmate."
    re.compile(r"^\s*(?:touch[eé]|voil[aà]|bingo|eureka|checkmate|bravo|encore|kudos|props|salute|cheers|peace|word|facts|true\s+that|you\s+got\s+it|for\s+real|no\s+cap|on\s+point|well\s+played|game\s+over|end\s+of\s+story|case\s+closed|that\s+settles\s+it|enough\s+is\s+enough|so\s+it\s+goes|it\s+is\s+what\s+it\s+is)\s*[.!]\s*$", re.IGNORECASE),
    # Hedging conversational: "I guess." "I suppose." "I think so." "Maybe so."
    re.compile(r"^\s*(?:I\s+guess|I\s+suppose|I\s+think\s+so|I\s+hope\s+so|I\s+doubt\s+it|I\s+don'?t\s+think\s+so|maybe\s+so|perhaps\s+so|could\s+be|might\s+be|seems\s+so|seems\s+like\s+it|looks\s+like\s+it|appears\s+so|who\s+knows|time\s+will\s+tell|we'?ll\s+see|one\s+can\s+hope|fingers\s+crossed)\s*[.!]\s*$", re.IGNORECASE),
    # Exclamatory conversational: "No kidding!" "You don't say!"
    re.compile(r"^\s*(?:no\s+kidding|you\s+don'?t\s+say|get\s+out\s+of\s+here|shut\s+the\s+front\s+door|I\s+can'?t\s+even|I\s+can'?t\s+believe\s+it|unreal|this\s+again|here\s+we\s+go|there\s+you\s+go|there\s+it\s+is|what\s+a\s+mess|what\s+a\s+day|what\s+now|now\s+what|oh\s+dear|oh\s+my|oh\s+well|dear\s+me|good\s+grief|good\s+lord|good\s+heavens|for\s+heaven'?s\s+sake|for\s+goodness\s+sake)\s*[.!]\s*$", re.IGNORECASE),
]

TRAILING_FRAGMENT_PATTERNS: List[re.Pattern] = [
    # Sentence trailing off with ellipsis
    re.compile(r"\.\.\.\s*$"),
    # Sentence breaking with em-dash
    re.compile(r"—\s*$"),
    # Sentence breaking with en-dash
    re.compile(r"–\s*$"),
    # Conditional/trailing: "If only..." "If I could..."
    re.compile(r"^\s*(?:if\s+only|if\s+I|if\s+we|if\s+they|if\s+he|if\s+she|if\s+you|if\s+it|if\s+that|if\s+this)\b[\w\s,'-]*\.\.\.\s*$", re.IGNORECASE),
    # "And then" trailing: "And then—" "And then..."
    re.compile(r"^\s*and\s+then\s*(?:[—–]|\.\.\.)\s*$", re.IGNORECASE),
    # "Well, ..." hesitation: "Well, maybe..." "Well, perhaps..."
    re.compile(r"^\s*well\s*,\s*[\w\s,'-]*\.\.\.\s*$", re.IGNORECASE),
    # "But..." contradiction trailing: "But still..." "But then again..."
    re.compile(r"^\s*but\s+[\w\s,'-]*\.\.\.\s*$", re.IGNORECASE),
    # Mid-sentence break: "She was about to—" "I was going to say—"
    re.compile(r"\b(?:was\s+about\s+to|was\s+going\s+to|was\s+just\s+about\s+to|wanted\s+to|meant\s+to|tried\s+to|started\s+to|began\s+to)\s*[—–]\s*$", re.IGNORECASE),
    # Trailing "or something" / "or whatever" / "or what have you"
    re.compile(r"\b(?:or\s+something|or\s+whatever|or\s+what\s+have\s+you|or\s+whatever\s+it\s+(?:is|was)|or\s+so\s+they\s+say|or\s+so\s+I'?ve\s+heard)\s*[.!?…]\s*$", re.IGNORECASE),
    # Dotted continuation: "You know..." "I mean..." "It's just..."
    re.compile(r"^\s*(?:you\s+know|I\s+mean|it'?s\s+just|I'?m\s+just|I\s+was\s+just|we\s+were\s+just|they\s+were\s+just)\s*[\w\s,'-]*\.\.\.\s*$", re.IGNORECASE),
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


def _count_tokens(text: str) -> int:
    """Count whitespace-delimited tokens in text."""
    return len(text.split())


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class WriterFragmentDensity:
    """Measure how much prose relies on sentence fragments.

    Fragments are the deliberate use of syntactic incompleteness:
    phrases and words posed as sentences, conversational markers
    standing alone, and constructions that trail off mid-thought.
    """

    def __init__(self):
        self.verbless_fragment = VERBLESS_FRAGMENT_PATTERNS
        self.subjectless_fragment = SUBJECTLESS_FRAGMENT_PATTERNS
        self.single_word_sentence = SINGLE_WORD_SENTENCE_PATTERNS
        self.conversational_fragment = CONVERSATIONAL_FRAGMENT_PATTERNS
        self.trailing_fragment = TRAILING_FRAGMENT_PATTERNS

    def measure_verbless_fragment_rate(self, text: str) -> float:
        """Rate of sentences that are verbless fragments."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_matching(sentences, self.verbless_fragment)
        return count / len(sentences)

    def measure_subjectless_fragment_rate(self, text: str) -> float:
        """Rate of sentences that are subjectless fragments."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_matching(sentences, self.subjectless_fragment)
        return count / len(sentences)

    def measure_single_word_sentence_rate(self, text: str) -> float:
        """Rate of sentences that are single words."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_matching(sentences, self.single_word_sentence)
        return count / len(sentences)

    def measure_conversational_fragment_rate(self, text: str) -> float:
        """Rate of sentences that are conversational fragments."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_matching(sentences, self.conversational_fragment)
        return count / len(sentences)

    def measure_trailing_fragment_rate(self, text: str) -> float:
        """Rate of sentences that trail off or break mid-thought."""
        sentences = _split_sentences(text)
        if not sentences:
            return 0.0
        count = _count_matching(sentences, self.trailing_fragment)
        return count / len(sentences)

    def compute_fragment_density_index(
        self,
        verbless: float,
        subjectless: float,
        single_word: float,
        conversational: float,
        trailing: float,
    ) -> float:
        """Compute composite fragment density index (0.0 to 1.0).

        Weights: verbless 0.25, subjectless 0.20, single_word 0.20,
        conversational 0.20, trailing 0.15.
        """
        index = (
            0.25 * verbless
            + 0.20 * subjectless
            + 0.20 * single_word
            + 0.20 * conversational
            + 0.15 * trailing
        )
        return min(index, 1.0)

    def classify(self, index: float) -> str:
        """Classify fragment density into descriptive categories."""
        if index >= 0.50:
            return "staccato"
        elif index >= 0.30:
            return "richly_fragmentary"
        elif index >= 0.15:
            return "moderately_fragmentary"
        elif index >= 0.05:
            return "minimally_fragmentary"
        else:
            return "syntactically_complete"

    def measure(self, text: str) -> Dict[str, Any]:
        """Full measurement of fragment density in text."""
        verbless = self.measure_verbless_fragment_rate(text)
        subjectless = self.measure_subjectless_fragment_rate(text)
        single_word = self.measure_single_word_sentence_rate(text)
        conversational = self.measure_conversational_fragment_rate(text)
        trailing = self.measure_trailing_fragment_rate(text)
        index = self.compute_fragment_density_index(
            verbless, subjectless, single_word, conversational, trailing
        )
        classification = self.classify(index)

        return {
            "verbless_fragment_rate": round(verbless, 4),
            "subjectless_fragment_rate": round(subjectless, 4),
            "single_word_sentence_rate": round(single_word, 4),
            "conversational_fragment_rate": round(conversational, 4),
            "trailing_fragment_rate": round(trailing, 4),
            "fragment_density_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    fragmentary_text = """The usual. A cold morning. Running late.
    Forgot everything. Never. Impossible. Of course. Fair enough.
    If only... And then— Well, maybe. Stop. Listen. Gone.
    No way. Touché. My bad. Sounds good. Makes sense.
    Sitting alone in the dark. Red, like wine. Enough.
    After dark. In the garden. Very slowly. Too late."""

    formal_text = """The committee reviewed the quarterly financial
    statements and approved the proposed budget. Revenue increased
    by twelve percent compared to the previous fiscal period.
    Operating expenses remained within the approved allocation.
    The board confirmed the capital expenditure plan for the
    upcoming quarter. All members voted in favor of the resolution."""

    wfd = WriterFragmentDensity()

    print("=== Fragmentary Text ===")
    result = wfd.measure(fragmentary_text)
    for key, value in result.items():
        print(f"{key:35s} {value}")

    print("\n=== Formal Text ===")
    result = wfd.measure(formal_text)
    for key, value in result.items():
        print(f"{key:35s} {value}")
