#!/usr/bin/env python3
"""writer_sensory_density — measure the richness of perceptual language.

Sensory density captures how much of a text is grounded in the five
senses: sight, sound, smell, taste, and touch.  A passage thick with
sensory language makes the reader *feel present* — they see the amber
light, hear the gravel crunch, smell the wet asphalt.  A passage with
no sensory language is purely abstract: ideas about ideas, concepts
moving across concepts, nothing you could photograph or record.

This is not a value judgment.  A philosophical treatise *should* have
low sensory density.  A food memoir or nature essay often benefits from
high sensory density.  The metric exists so the writer can *see* whether
their perceptual register matches their intent — not to maximize it.

This module is orthogonal to the other writer metrics:

- **concreteness** tracks *whether language refers to physical things
  versus abstract concepts*.  Concreteness and sensory density correlate
  but diverge: "the red ball" is concrete (physical object) but has low
  sensory density (one visual token in four words).  "The acrid smoke
  clawed at her throat, each breath a rasp of burnt sugar" has high
  sensory density *and* high concreteness.  "The algorithm consumed the
  data greedily" has sensory verbs applied to abstractions — high sensory
  language, low concreteness.

- **dialog_density** tracks *quoted speech versus narrative*.  Dialog
  can be sensory ("I can smell the rain coming") or abstract ("justice
  requires patience").  Dialog density measures *structural mode*;
  sensory density measures *perceptual texture*.

- **tension** tracks *anticipation and forward pull*.  Sensory detail
  can build tension (the creak of a floorboard in a dark hallway) or
  dissolve it (the warm sun on a picnic blanket).  Tension is about
  *narrative pull*; sensory density is about *perceptual presence*.

- **pacing** tracks *narrative speed*.  Dense sensory description often
  slows pacing — the reader lingers over each image.  But a rapid
  sequence of sensory impressions ("flash, crack, sting, the taste of
  copper") can accelerate it.  Pacing measures *rate of change*;
  sensory density measures *perceptual depth*.

- **prose_rhythm** tracks *variation in sentence length*.  Sensory
  passages can be rhythmic (long flowing descriptions) or staccato
  (short sharp impressions).  Rhythm is about *patterning*; sensory
  density is about *what the words invoke*.

Sensory density asks: **how much of this text can you see, hear,
smell, taste, or touch?**

Dimensions
----------

========================  ==============================================
metric                    meaning
========================  ==============================================
visual_density            fraction of tokens that are visual words —
                          colors, light, shapes, spatial extent,
                          brightness, texture-as-appearance
auditory_density          fraction of tokens that are auditory words —
                          sounds, music, silence, volume, pitch,
                          resonance, cacophony
olfactory_density         fraction of tokens that are olfactory words —
                          smells, scents, fragrances, stench,
                          bouquet, aroma, reek
gustatory_density         fraction of tokens that are gustatory words —
                          tastes, flavors, mouthfeel, sweetness,
                          bitterness, umami, spice, texture-in-mouth
tactile_density           fraction of tokens that are tactile words —
                          touch, temperature, texture-as-feeling,
                          pressure, weight, moisture, pain
kinesthetic_density       fraction of tokens that are kinesthetic —
                          body movement, proprioception, balance,
                          muscle effort, spatial orientation
========================  ==============================================

From these six dimensions a composite **sensory_density_index** is
computed as a weighted average (visual and tactile weighted higher as
the most common literary senses) and classified:

==============  ============================================================
class           meaning
==============  ============================================================
immersive       index >= 0.03 — text is thick with sensory experience
evocative       0.018 <= index < 0.03 — frequent sensory grounding
sparse          0.008 <= index < 0.018 — occasional sensory touches
abstract        0.002 <= index < 0.008 — mostly idea-language
disembodied     index < 0.002 — no detectable sensory engagement
==============  ============================================================

Additionally a **sensory_balance** score (Shannon evenness across the
six channels, 0.0 to 1.0) indicates whether the writer uses all senses
or leans heavily on one.  A text that is 90% visual and 10% everything
else has low balance; a text that distributes evenly has high balance.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Set


# ---------------------------------------------------------------------------
# Pattern libraries — one set per sensory modality
# ---------------------------------------------------------------------------

VISUAL_WORDS: List[str] = [
    # colors
    "red", "blue", "green", "yellow", "orange", "purple", "violet",
    "crimson", "scarlet", "amber", "gold", "golden", "silver", "bronze",
    "ivory", "ebony", "white", "black", "gray", "grey", "brown", "pink",
    "magenta", "cyan", "teal", "indigo", "ochre", "sienna", "umber",
    "turquoise", "maroon", "burgundy", "beige", "tan", "cream", "coral",
    "salmon", "peach", "lavender", "lilac", "mauve", "plum", "olive",
    "rust", "copper", "jade", "sapphire", "ruby", "emerald",
    # light
    "bright", "dim", "dark", "light", "glow", "glowing", "shining",
    "sparkle", "sparkling", "gleam", "gleaming", "glimmer", "glimmering",
    "flicker", "flickering", "radiant", "luminous", "dazzling", "blinding",
    "murky", "shadowy", "shadow", "shadows", "silhouette", "haze", "hazy",
    "translucent", "transparent", "opaque", "matte", "glossy", "sheen",
    "glare", "glaring", "twinkle", "twinkling", "shimmer", "shimmering",
    "iridescent", "fluorescent", "incandescent",
    # shape and appearance
    "round", "flat", "tall", "short", "wide", "narrow", "thin", "thick",
    "sharp", "blunt", "curved", "straight", "jagged", "smooth", "rough",
    "angular", "crooked", "symmetrical", "asymmetrical", "vast", "tiny",
    "enormous", "massive", "minute", "towering", "sprawling", "compact",
]

AUDITORY_WORDS: List[str] = [
    # sounds
    "loud", "quiet", "silent", "deafening", "thunderous", "faint",
    "muffled", "piercing", "shrill", "high-pitched", "low-pitched",
    "resonant", "booming", "echoing", "ringing", "humming", "buzzing",
    "crackling", "rustling", "whispering", "murmuring", "hissing",
    "sizzling", "popping", "clicking", "tapping", "knocking", "banging",
    "crashing", "clanging", "jingling", "tinkling", "chiming", "tolling",
    "roaring", "howling", "wailing", "shrieking", "screaming", "yelling",
    "bellowing", "thundering", "rumbling", "grinding", "scraping",
    "scratch", "scratching", "squeaking", "creaking", "groaning",
    "moaning", "sighing", "breathing", "panting", "gasping",
    # music-related
    "melodic", "harmonic", "dissonant", "rhythmic", "staccato", "legato",
    "cacophony", "symphony", "chorus", "refrain", "cadence",
]

OLFACTORY_WORDS: List[str] = [
    "smell", "smelled", "smelling", "scent", "scented", "fragrance",
    "fragrant", "aroma", "aromatic", "bouquet", "perfume", "perfumed",
    "stink", "stinking", "stench", "reek", "reeking", "musty", "mustiness",
    "mildew", "mildewed", "pungent", "acrid", "fetid", "putrid", "rank",
    "musky", "earthy", "woody", "smoky", "smoke", "floral", "citrus",
    "minty", "herbal", "spicy", "sweet-smelling", "foul-smelling",
    "fresh-smelling", "damp", "dank", "stale", "fresh", "crisp",
    "whiff", "sniff", "sniffing", "nose", "nostrils", "inhale",
    "exhale", "breath", "breathing", "odor", "odorous", "malodorous",
    "redolent", "redolence",
]

GUSTATORY_WORDS: List[str] = [
    "sweet", "sour", "bitter", "salty", "savory", "umami", "spicy",
    "hot", "mild", "bland", "tangy", "zesty", "piquant", "pungent",
    "sharp", "rich", "creamy", "buttery", "oily", "greasy", "fatty",
    "crispy", "crunchy", "chewy", "tender", "tough", "dry", "moist",
    "juicy", "succulent", "stale", "fresh", "ripe", "unripe", "raw",
    "cooked", "roasted", "grilled", "fried", "baked", "boiled", "steamed",
    "tart", "astringent", "metallic", "cloying", "saccharine",
    "peppery", "gingery", "garlicky", "lemony", "vinegary",
    "taste", "tasted", "tasting", "flavor", "flavored", "flavorful",
    "flavorless", "palate", "tongue", "sip", "sipping", "bite", "biting",
    "chew", "chewing", "swallow", "swallowing", "nibble", "nibbling",
    "gulp", "gulping", "savor", "savoring",
]

TACTILE_WORDS: List[str] = [
    # touch and texture
    "soft", "hard", "smooth", "rough", "coarse", "fine", "silky", "satin",
    "velvety", "furry", "fuzzy", "prickly", "scratchy", "bristly",
    "slick", "slippery", "sticky", "tacky", "gritty", "grainy",
    "crumbly", "flaky", "powdery", "chalky", "glassy", "leathery",
    "rubbery", "waxy", "clammy", "slimy", "gooey", "viscous",
    # temperature
    "hot", "warm", "cool", "cold", "freezing", "icy", "scalding",
    "blistering", "tepid", "lukewarm", "frosty", "chilly", "searing",
    "burning", "numb", "numbing", "frostbitten", "sun-warmed",
    # pressure and force
    "heavy", "light", "weightless", "dense", "solid", "hollow",
    "tight", "loose", "firm", "yielding", "rigid", "flexible",
    "stiff", "limp", "taut", "slack", "crushing", "pressing",
    "squeezing", "pinching", "gripping", "clutching", "grasping",
    # moisture
    "wet", "dry", "damp", "moist", "soaked", "drenched", "sodden",
    "parched", "arid", "humid", "muggy", "dewy", "misty",
    # pain and sensation
    "dull", "aching", "throbbing", "stinging", "tingling", "itching",
    "tickling", "sore", "raw",
]

KINESTHETIC_WORDS: List[str] = [
    # body movement
    "walk", "walked", "walking", "run", "ran", "running", "sprint",
    "sprinting", "jog", "jogging", "stumble", "stumbling", "stagger",
    "staggering", "lurch", "lurching", "sway", "swaying", "lean",
    "leaning", "bend", "bending", "crouch", "crouching", "kneel",
    "kneeling", "crawl", "crawling", "climb", "climbing", "leap",
    "leaping", "jump", "jumping", "fall", "falling", "tumble",
    "tumbling", "roll", "rolling", "spin", "spinning", "twist",
    "twisting", "turn", "turning", "reach", "reaching", "stretch",
    "stretching", "pull", "pulling", "push", "pushing", "lift",
    "lifting", "carry", "carrying", "drag", "dragging", "throw",
    "throwing", "catch", "catching", "kick", "kicking", "swing",
    "swinging", "shake", "shaking", "tremble", "trembling", "shiver",
    "shivering", "quake", "quaking", "flinch", "flinching", "wince",
    "wincing", "dodge", "dodging", "duck", "ducking", "weave",
    "weaving", "stride", "striding", "pace", "pacing", "wander",
    "wandering", "drift", "drifting", "float", "floating", "sink",
    "sinking", "rise", "rising", "descend", "descending",
    # proprioception and balance
    "balance", "balanced", "unbalanced", "steady", "unsteady",
    "vertigo", "dizzy", "dizziness", "grounded", "off-balance",
    "poised", "braced", "tense", "relaxed", "limp", "rigid",
]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _build_word_set(words: List[str]) -> Set[str]:
    """Build a lowercase set for fast lookup."""
    return {w.lower() for w in words}


def _tokenize(text: str) -> List[str]:
    """Split text into lowercase word tokens (strip punctuation)."""
    return re.findall(r"[a-z'-]+", text.lower())


def _split_sentences(text: str) -> List[str]:
    """Naive sentence splitter on '.', '!', '?'."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class WriterSensoryDensity:
    """Analyze the sensory language density of a text."""

    def __init__(self) -> None:
        self.visual: Set[str] = _build_word_set(VISUAL_WORDS)
        self.auditory: Set[str] = _build_word_set(AUDITORY_WORDS)
        self.olfactory: Set[str] = _build_word_set(OLFACTORY_WORDS)
        self.gustatory: Set[str] = _build_word_set(GUSTATORY_WORDS)
        self.tactile: Set[str] = _build_word_set(TACTILE_WORDS)
        self.kinesthetic: Set[str] = _build_word_set(KINESTHETIC_WORDS)

    # -- private helpers ---------------------------------------------------

    def _count_modality(
        self, tokens: List[str], lexicon: Set[str]
    ) -> int:
        """Count tokens matching a sensory lexicon."""
        return sum(1 for t in tokens if t in lexicon)

    def _density(self, count: int, total: int) -> float:
        """Safe density calculation."""
        return count / total if total > 0 else 0.0

    # -- per-modality measures ---------------------------------------------

    def measure_visual_density(self, text: str) -> float:
        tokens = _tokenize(text)
        if not tokens:
            return 0.0
        return self._density(self._count_modality(tokens, self.visual), len(tokens))

    def measure_auditory_density(self, text: str) -> float:
        tokens = _tokenize(text)
        if not tokens:
            return 0.0
        return self._density(self._count_modality(tokens, self.auditory), len(tokens))

    def measure_olfactory_density(self, text: str) -> float:
        tokens = _tokenize(text)
        if not tokens:
            return 0.0
        return self._density(self._count_modality(tokens, self.olfactory), len(tokens))

    def measure_gustatory_density(self, text: str) -> float:
        tokens = _tokenize(text)
        if not tokens:
            return 0.0
        return self._density(self._count_modality(tokens, self.gustatory), len(tokens))

    def measure_tactile_density(self, text: str) -> float:
        tokens = _tokenize(text)
        if not tokens:
            return 0.0
        return self._density(self._count_modality(tokens, self.tactile), len(tokens))

    def measure_kinesthetic_density(self, text: str) -> float:
        tokens = _tokenize(text)
        if not tokens:
            return 0.0
        return self._density(self._count_modality(tokens, self.kinesthetic), len(tokens))

    # -- composite ---------------------------------------------------------

    def compute_sensory_density_index(
        self,
        visual: float,
        auditory: float,
        olfactory: float,
        gustatory: float,
        tactile: float,
        kinesthetic: float,
    ) -> float:
        """Weighted composite: visual and tactile carry more weight as the
        most common literary senses; olfactory and gustatory carry less
        because they appear less frequently in most prose."""
        return (
            visual * 0.22
            + auditory * 0.18
            + olfactory * 0.12
            + gustatory * 0.12
            + tactile * 0.22
            + kinesthetic * 0.14
        )

    def compute_sensory_balance(
        self,
        visual: float,
        auditory: float,
        olfactory: float,
        gustatory: float,
        tactile: float,
        kinesthetic: float,
    ) -> float:
        """Shannon evenness across the six channels, normalized to [0, 1].

        Returns 1.0 when all channels are equal (perfect balance) and
        0.0 when all density is concentrated in a single channel.
        Returns 0.0 when total density is zero (no sensory language).
        """
        values = [visual, auditory, olfactory, gustatory, tactile, kinesthetic]
        total = sum(values)
        if total == 0.0:
            return 0.0

        proportions = [v / total for v in values]
        entropy = -sum(p * math.log(p) for p in proportions if p > 0)
        max_entropy = math.log(6)  # log(n_channels)
        return entropy / max_entropy if max_entropy > 0 else 0.0

    def classify(self, index: float) -> str:
        if index >= 0.03:
            return "immersive"
        elif index >= 0.018:
            return "evocative"
        elif index >= 0.008:
            return "sparse"
        elif index >= 0.002:
            return "abstract"
        else:
            return "disembodied"

    def dominant_modality(
        self,
        visual: float,
        auditory: float,
        olfactory: float,
        gustatory: float,
        tactile: float,
        kinesthetic: float,
    ) -> str:
        """Return the name of the strongest sensory channel."""
        channels = {
            "visual": visual,
            "auditory": auditory,
            "olfactory": olfactory,
            "gustatory": gustatory,
            "tactile": tactile,
            "kinesthetic": kinesthetic,
        }
        best = max(channels, key=channels.get)  # type: ignore[arg-type]
        return best if channels[best] > 0 else "none"

    # -- full measurement --------------------------------------------------

    def measure(self, text: str) -> Dict[str, Any]:
        visual = self.measure_visual_density(text)
        auditory = self.measure_auditory_density(text)
        olfactory = self.measure_olfactory_density(text)
        gustatory = self.measure_gustatory_density(text)
        tactile = self.measure_tactile_density(text)
        kinesthetic = self.measure_kinesthetic_density(text)

        index = self.compute_sensory_density_index(
            visual, auditory, olfactory, gustatory, tactile, kinesthetic
        )
        balance = self.compute_sensory_balance(
            visual, auditory, olfactory, gustatory, tactile, kinesthetic
        )
        classification = self.classify(index)
        dominant = self.dominant_modality(
            visual, auditory, olfactory, gustatory, tactile, kinesthetic
        )

        return {
            "visual_density": round(visual, 4),
            "auditory_density": round(auditory, 4),
            "olfactory_density": round(olfactory, 4),
            "gustatory_density": round(gustatory, 4),
            "tactile_density": round(tactile, 4),
            "kinesthetic_density": round(kinesthetic, 4),
            "sensory_density_index": round(index, 4),
            "sensory_balance": round(balance, 4),
            "classification": classification,
            "dominant_modality": dominant,
        }


if __name__ == "__main__":
    immersive_text = """The amber light slanted through the dusty window,
    casting warm rectangles across the rough wooden floor. She could smell
    the musty books and hear the faint ticking of the grandfather clock
    downstairs. The velvet curtain felt soft against her fingertips as she
    pulled it aside. Outside, the wind howled and the rain hammered against
    the glass. She tasted the last of her tea — lukewarm now, with a bitter
    edge of over-steeped leaves. The chair creaked as she settled into it,
    her bare feet sinking into the thick, scratchy wool of the rug."""

    abstract_text = """The concept of justice requires careful consideration
    of multiple factors. One must weigh the interests of various stakeholders
    and consider the implications of different approaches. The theoretical
    framework provides a basis for understanding the relationships between
    competing principles. Further analysis reveals important nuances in the
    application of these concepts to practical situations."""

    wsd = WriterSensoryDensity()

    print("=== Immersive Text ===")
    result = wsd.measure(immersive_text)
    for key, value in result.items():
        print(f"{key:25s} {value}")

    print("\n=== Abstract Text ===")
    result = wsd.measure(abstract_text)
    for key, value in result.items():
        print(f"{key:25s} {value}")
