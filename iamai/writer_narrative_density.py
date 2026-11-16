#!/usr/bin/env python3
"""writer_narrative_density — measure how much prose tells a story.

Narrative is the art of recounting events through agents acting in
time.  "She opened the door and stepped inside" is narrative; "The
door was made of oak" is description; "Doors symbolize opportunity"
is exposition.  The same sentence can sit in any register depending
on context, but at the macro level a text's narrative density is
surprisingly stable and measurable.

Why it matters: a technical manual should score near zero — it
describes procedures, not stories.  A novel should score near one —
it is nothing but story.  Essays hover in the middle, weaving
anecdote into argument.  Knowing where a text sits on this axis helps
calibrate tone, pacing, and reader expectations.

Narrative manifests through five independent channels.  **Action
verbs** recount physical deeds that advance a plot: "ran", "grabbed",
"slammed", "whispered", "fled".  They exclude stative and cognitive
verbs ("is", "seems", "believes").  **Temporal sequencing** orders
events along a timeline: "then", "after", "before", "next",
"suddenly", "meanwhile", "later that day".  Without sequence there
is no plot, only tableau.  **Character presence** signals agents
who act and are acted upon: third-person pronouns ("he", "she",
"they"), proper nouns used as subjects, and character-introduction
verbs ("met", "encountered", "recognized").  **Dialogue markers**
capture speech — the lifeblood of scene: quotation-verb patterns
("said", "asked", "replied", "shouted"), direct-speech punctuation
(quoted strings), and speech-act tags ("he murmured", "she snapped").
**Scene-setting** establishes the physical and temporal stage on
which the narrative unfolds: locative prepositions used cinematically
("entered the room", "at dawn", "on the bridge", "across the
field"), motion-into-location patterns, and atmospheric verbs
("rained", "darkened", "echoed").

A text with high narrative density recounts what happened, to whom,
and when.  A text with low narrative density explains what something
is, means, or implies.  Most good non-fiction oscillates between the
two, using narrative passages to anchor abstract argument.

This module measures narrative density as a composite index
(0.0 – 1.0) across five independent channels, orthogonal to
abstraction_density (which measures conceptual altitude),
specificity (which measures precision of reference), formality
(which measures register), hedging (which measures commitment
avoidance), and verbosity (which measures padding-to-payload ratio).

written by Qwen during manual caretaker visit 649, 2026-11-16
"""

import re
from dataclasses import dataclass, field
from typing import List


# ── regex primitives ────────────────────────────────────────────

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_SPLIT = re.compile(r"[a-zA-Z'-]+")


# ── channel 1: action verbs ─────────────────────────────────────
# Physical, observable deeds — someone *did* something.
# Excludes stative (is, seems, appears), cognitive (believes, thinks),
# and existential (exists, remains) verbs.

_ACTION_VERBS: List[re.Pattern] = [
    # locomotion
    re.compile(r"\b(?:ran|run|walked|strode|marched|hiked|jogged|sprinted|dashed|darted|rushed|hurried|hastened|fled|escaped|chased|pursued|followed|trailed|wandered|roamed|strolled|ambled|crept|crawled|slipped|sneaked|snuck|stumbled|staggered|limped|hobbled|leapt|jumped|bounded|vaulted|climbed|scaled|descended|ascended|crossed|traversed|approached|arrived|departed|left|exited|entered|returned)\b", re.IGNORECASE),
    # manipulation
    re.compile(r"\b(?:grabbed|seized|snatched|caught|threw|tossed|hurled|flung|pushed|shoved|pulled|dragged|hauled|lifted|dropped|placed|set|put|slid|slipped|rolled|folded|unfolded|tore|ripped|split|cracked|broke|smashed|shattered|crushed|opened|closed|slammed|shut|locked|unlocked|twisted|turned|spun|swung|waved|pointed|gestured|reached|extended)\b", re.IGNORECASE),
    # combat / conflict
    re.compile(r"\b(?:struck|hit|punched|kicked|slapped|stabbed|shot|fired|blocked|dodged|parried|charged|attacked|fought|wrestled|tackled|grappled|shoved|tripped|stumbled)\b", re.IGNORECASE),
    # bodily actions
    re.compile(r"\b(?:sat|stood|knelt|crouched|bent|leaned|stretched|yawned|sighed|gasped|choked|coughed|sneezed|swallowed|blinked|stared|glared|peered|squinted|frowned|smiled|grinned|laughed|cried|wept|sobbed|moaned|groaned|screamed|shouted|yelled|whispered|muttered|mumbled|hissed|spat|swore|nodded|shook|trembled|shivered|sweated|bled|collapsed|fainted|fell|rose|awoke|slept|dreamed)\b", re.IGNORECASE),
    # creation / destruction
    re.compile(r"\b(?:built|constructed|assembled|carved|sculpted|painted|drew|sketched|wrote|typed|printed|composed|sang|played|danced|cooked|baked|fried|boiled|roasted|chopped|sliced|diced|minced|poured|stirred|mixed|blended|wove|sewed|stitched|knitted|planted|dug|buried|harvested|reaped|sowed|burned|lit|extinguished|doused|flooded|washed|scrubbed|wiped|swept|mopped|polished)\b", re.IGNORECASE),
]


# ── channel 2: temporal sequencing ──────────────────────────────
# Words and phrases that order events along a timeline.
# Without sequence there is tableau, not narrative.

_TEMPORAL_SEQUENCERS: List[re.Pattern] = [
    re.compile(r"\bthen\b", re.IGNORECASE),
    re.compile(r"\bafter(?:ward[s]?)?\b", re.IGNORECASE),
    re.compile(r"\bbefore(?:hand)?\b", re.IGNORECASE),
    re.compile(r"\bnext\b", re.IGNORECASE),
    re.compile(r"\b(?:first|second|third|finally|lastly)\b", re.IGNORECASE),
    re.compile(r"\blater(?:\s+that\s+\w+)?\b", re.IGNORECASE),
    re.compile(r"\b(?:meanwhile|meantime)\b", re.IGNORECASE),
    re.compile(r"\bsuddenly\b", re.IGNORECASE),
    re.compile(r"\b(?:all\s+at\s+once|at\s+once)\b", re.IGNORECASE),
    re.compile(r"\b(?:in\s+that\s+moment|at\s+that\s+moment)\b", re.IGNORECASE),
    re.compile(r"\b(?:moments?\s+later|seconds?\s+later|minutes?\s+later|hours?\s+later|days?\s+later|weeks?\s+later)\b", re.IGNORECASE),
    re.compile(r"\b(?:the\s+next\s+(?:morning|day|week|month|year))\b", re.IGNORECASE),
    re.compile(r"\b(?:earlier|previously)\b", re.IGNORECASE),
    re.compile(r"\b(?:by\s+the\s+time|no\s+sooner)\b", re.IGNORECASE),
    re.compile(r"\b(?:as\s+soon\s+as|once)\b", re.IGNORECASE),
    re.compile(r"\b(?:in\s+the\s+meantime)\b", re.IGNORECASE),
    re.compile(r"\b(?:subsequently|thereafter)\b", re.IGNORECASE),
    re.compile(r"\b(?:when|while|whenever)\b", re.IGNORECASE),
    re.compile(r"\b(?:just\s+then|right\s+then)\b", re.IGNORECASE),
    re.compile(r"\b(?:eventually|ultimately)\b", re.IGNORECASE),
]


# ── channel 3: character presence ────────────────────────────────
# Pronouns and patterns that signal agents who act and are acted
# upon.  High character presence means *someone* is doing things.

_CHARACTER_MARKERS: List[re.Pattern] = [
    # third-person pronouns (narrative perspective)
    re.compile(r"\bhe\b", re.IGNORECASE),
    re.compile(r"\bshe\b", re.IGNORECASE),
    re.compile(r"\bthey\b", re.IGNORECASE),
    re.compile(r"\bhim\b", re.IGNORECASE),
    re.compile(r"\bher\b", re.IGNORECASE),
    re.compile(r"\bthem\b", re.IGNORECASE),
    re.compile(r"\bhis\b", re.IGNORECASE),
    re.compile(r"\bhers\b", re.IGNORECASE),
    re.compile(r"\btheir[s]?\b", re.IGNORECASE),
    # first-person narrative
    re.compile(r"\bI\b"),
    re.compile(r"\bwe\b", re.IGNORECASE),
    # character-introduction verbs
    re.compile(r"\b(?:met|encountered|recognized|spotted|noticed|glimpsed|observed)\b", re.IGNORECASE),
    # character-addressing verbs
    re.compile(r"\b(?:called|summoned|invited|greeted|approached|confronted)\b", re.IGNORECASE),
]


# ── channel 4: dialogue markers ──────────────────────────────────
# Quoted speech and speech-act verbs that capture characters talking.
# Dialogue is the heartbeat of scene — it collapses distance between
# reader and event.

_SPEECH_VERBS: List[re.Pattern] = [
    re.compile(r"\bsaid\b", re.IGNORECASE),
    re.compile(r"\basked\b", re.IGNORECASE),
    re.compile(r"\breplied\b", re.IGNORECASE),
    re.compile(r"\banswered\b", re.IGNORECASE),
    re.compile(r"\bwhispered\b", re.IGNORECASE),
    re.compile(r"\bshouted\b", re.IGNORECASE),
    re.compile(r"\byelled\b", re.IGNORECASE),
    re.compile(r"\bscreamed\b", re.IGNORECASE),
    re.compile(r"\bmuttered\b", re.IGNORECASE),
    re.compile(r"\bmumbled\b", re.IGNORECASE),
    re.compile(r"\bexclaimed\b", re.IGNORECASE),
    re.compile(r"\bdeclared\b", re.IGNORECASE),
    re.compile(r"\binsisted\b", re.IGNORECASE),
    re.compile(r"\bdemanded\b", re.IGNORECASE),
    re.compile(r"\bbegged\b", re.IGNORECASE),
    re.compile(r"\bpleaded\b", re.IGNORECASE),
    re.compile(r"\badmitted\b", re.IGNORECASE),
    re.compile(r"\bconfessed\b", re.IGNORECASE),
    re.compile(r"\bargued\b", re.IGNORECASE),
    re.compile(r"\bsnapped\b", re.IGNORECASE),
    re.compile(r"\bhissed\b", re.IGNORECASE),
    re.compile(r"\bmoaned\b", re.IGNORECASE),
    re.compile(r"\bgrumbled\b", re.IGNORECASE),
    re.compile(r"\bsuggested\b", re.IGNORECASE),
    re.compile(r"\boffered\b", re.IGNORECASE),
    re.compile(r"\bwarned\b", re.IGNORECASE),
    re.compile(r"\bpromised\b", re.IGNORECASE),
    re.compile(r"\bswore\b", re.IGNORECASE),
    re.compile(r"\brepeated\b", re.IGNORECASE),
]

# Quoted strings: text inside double or single quotes (ASCII + smart quotes).
_DQ = "\u0022\u201c\u201d"  # " " "
_SQ = "\u0027\u2018\u2019"  # ' ' '
_QUOTED_SPEECH = re.compile(
    f"[{_DQ}][^{_DQ}]*[{_DQ}]|[{_SQ}][^{_SQ}]*[{_SQ}]"
)


# ── channel 5: scene-setting ────────────────────────────────────
# Locative and atmospheric patterns that establish where and when
# the narrative takes place.

_SCENE_MARKERS: List[re.Pattern] = [
    # motion into location
    re.compile(r"\b(?:entered|walked\s+into|stepped\s+into|strode\s+into|rushed\s+into|burst\s+into|stormed\s+into|wandered\s+into|slipped\s+into)\b", re.IGNORECASE),
    re.compile(r"\b(?:walked\s+out(?:\s+of)?|stepped\s+out(?:\s+of)?|rushed\s+out(?:\s+of)?|burst\s+out(?:\s+of)?)\b", re.IGNORECASE),
    # atmospheric / environmental verbs
    re.compile(r"\b(?:rained|snowed|hail[ed]*|thundered|lightning\s+flashed|wind\s+(?:howled|blew|whipped|gusted))\b", re.IGNORECASE),
    re.compile(r"\b(?:darkened|brightened|dimmed|faded|glowed|shimmered|sparkled|flickered)\b", re.IGNORECASE),
    re.compile(r"\b(?:echoed|resounded|reverberated|rang|tolled|chimed)\b", re.IGNORECASE),
    # temporal scene-setting
    re.compile(r"\b(?:at\s+dawn|at\s+dusk|at\s+midnight|at\s+noon|at\s+sunrise|at\s+sunset|in\s+the\s+morning|in\s+the\s+evening|in\s+the\s+afternoon|at\s+night)\b", re.IGNORECASE),
    # locative grounding
    re.compile(r"\b(?:across\s+the\s+\w+|through\s+the\s+\w+|along\s+the\s+\w+|down\s+the\s+\w+|up\s+the\s+\w+|over\s+the\s+\w+|beneath\s+the\s+\w+|behind\s+the\s+\w+|beside\s+the\s+\w+|beyond\s+the\s+\w+)\b", re.IGNORECASE),
    # scene-transition phrases
    re.compile(r"\b(?:the\s+room\s+(?:was|smelled|felt|looked))\b", re.IGNORECASE),
    re.compile(r"\b(?:the\s+(?:air|atmosphere)\s+(?:was|felt|seemed|grew))\b", re.IGNORECASE),
    re.compile(r"\b(?:silence\s+(?:fell|filled|hung|settled|gripped))\b", re.IGNORECASE),
    re.compile(r"\b(?:darkness\s+(?:fell|descended|crept|gathered|closed\s+in))\b", re.IGNORECASE),
    re.compile(r"\b(?:light\s+(?:flooded|streamed|poured|filtered|seeped))\b", re.IGNORECASE),
]


# ── result dataclass ────────────────────────────────────────────


@dataclass
class NarrativeDensityResult:
    """Results of narrative density analysis."""

    # Raw counts
    action_verb_count: int = 0
    temporal_sequence_count: int = 0
    character_presence_count: int = 0
    dialogue_marker_count: int = 0
    scene_setting_count: int = 0

    # Rates per 100 sentences
    action_verb_rate: float = 0.0
    temporal_sequence_rate: float = 0.0
    character_presence_rate: float = 0.0
    dialogue_marker_rate: float = 0.0
    scene_setting_rate: float = 0.0

    # Composite
    narrative_index: float = 0.0
    classification: str = "expository"

    # Metadata
    total_sentences: int = 0
    total_words: int = 0
    total_narrative_markers: int = 0
    quoted_speech_count: int = 0
    details: dict = field(default_factory=dict)


# ── helpers ─────────────────────────────────────────────────────


def _count_sentences(text: str) -> int:
    """Count sentences (approximate)."""
    stripped = text.strip()
    if not stripped:
        return 0
    sentences = [s for s in _SENTENCE_SPLIT.split(stripped) if s.strip()]
    return max(len(sentences), 1)


def _count_words(text: str) -> int:
    """Count words."""
    return len(_WORD_SPLIT.findall(text))


def _count_pattern_matches(text: str, patterns: List[re.Pattern]) -> int:
    """Count total matches across a list of patterns."""
    return sum(len(p.findall(text)) for p in patterns)


def _count_quoted_speech(text: str) -> int:
    """Count quoted speech instances."""
    return len(_QUOTED_SPEECH.findall(text))


# ── main measurement function ───────────────────────────────────


def measure_narrative_density(text: str) -> NarrativeDensityResult:
    """Measure narrative density of a text.

    Returns a NarrativeDensityResult with narrative_index (0.0–1.0)
    and classification.
    """
    result = NarrativeDensityResult()

    stripped = text.strip()
    if not stripped:
        result.classification = "expository"
        return result

    sentences = _count_sentences(text)
    words = _count_words(text)
    result.total_sentences = sentences
    result.total_words = words

    scale = 100.0 / max(sentences, 1)

    # ── count each channel ───────────────────────────────────
    result.action_verb_count = _count_pattern_matches(text, _ACTION_VERBS)
    result.temporal_sequence_count = _count_pattern_matches(text, _TEMPORAL_SEQUENCERS)
    result.character_presence_count = _count_pattern_matches(text, _CHARACTER_MARKERS)
    result.dialogue_marker_count = _count_pattern_matches(text, _SPEECH_VERBS)
    result.quoted_speech_count = _count_quoted_speech(text)
    result.scene_setting_count = _count_pattern_matches(text, _SCENE_MARKERS)

    # Dialogue count combines speech verbs and quoted strings
    total_dialogue = result.dialogue_marker_count + result.quoted_speech_count

    result.total_narrative_markers = (
        result.action_verb_count
        + result.temporal_sequence_count
        + result.character_presence_count
        + total_dialogue
        + result.scene_setting_count
    )

    # ── rates per 100 sentences ──────────────────────────────
    result.action_verb_rate = round(result.action_verb_count * scale, 3)
    result.temporal_sequence_rate = round(result.temporal_sequence_count * scale, 3)
    result.character_presence_rate = round(result.character_presence_count * scale, 3)
    result.dialogue_marker_rate = round(total_dialogue * scale, 3)
    result.scene_setting_rate = round(result.scene_setting_count * scale, 3)

    # ── composite narrative index (0.0 – 1.0) ───────────────
    # Normalize each channel to ~0–1 via typical maxima
    cap_action = min(1.0, result.action_verb_rate / 60.0)
    cap_temporal = min(1.0, result.temporal_sequence_rate / 30.0)
    cap_character = min(1.0, result.character_presence_rate / 80.0)
    cap_dialogue = min(1.0, result.dialogue_marker_rate / 40.0)
    cap_scene = min(1.0, result.scene_setting_rate / 15.0)

    composite = (
        0.30 * cap_action
        + 0.15 * cap_temporal
        + 0.20 * cap_character
        + 0.20 * cap_dialogue
        + 0.15 * cap_scene
    )
    result.narrative_index = round(min(1.0, composite), 4)

    # ── classification ───────────────────────────────────────
    idx = result.narrative_index
    if idx < 0.10:
        result.classification = "expository"
    elif idx < 0.25:
        result.classification = "anecdotal"
    elif idx < 0.45:
        result.classification = "narrative"
    elif idx < 0.65:
        result.classification = "immersive"
    else:
        result.classification = "storied"

    result.details = {
        "action_verb_rate": result.action_verb_rate,
        "temporal_sequence_rate": result.temporal_sequence_rate,
        "character_presence_rate": result.character_presence_rate,
        "dialogue_marker_rate": result.dialogue_marker_rate,
        "scene_setting_rate": result.scene_setting_rate,
        "narrative_index": result.narrative_index,
        "classification": result.classification,
    }

    return result


# ── CLI convenience ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else None
    if path:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    r = measure_narrative_density(text)
    print(f"narrative_index           : {r.narrative_index:.4f}")
    print(f"classification            : {r.classification}")
    print(f"action_verb_rate          : {r.action_verb_rate}")
    print(f"temporal_sequence_rate    : {r.temporal_sequence_rate}")
    print(f"character_presence_rate   : {r.character_presence_rate}")
    print(f"dialogue_marker_rate      : {r.dialogue_marker_rate}")
    print(f"scene_setting_rate        : {r.scene_setting_rate}")
    print(f"total_narrative_markers   : {r.total_narrative_markers}")
    print(f"quoted_speech_count       : {r.quoted_speech_count}")
    print(f"total_sentences           : {r.total_sentences}")
    print(f"total_words               : {r.total_words}")
