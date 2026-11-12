#!/usr/bin/env python3
"""writer_dialog_density — measure the proportion of dialog vs narrative.

Dialog density captures how much of a text lives inside quoted speech
versus narrative prose.  A screenplay is almost entirely dialog; an
academic paper has none.  Most fiction falls somewhere in between, and
the balance between *people talking* and *the narrator describing* is
one of the most fundamental stylistic choices a writer makes.

This module is orthogonal to the other writer metrics:

- **formality** tracks *register conventions*.  Dialog can be formal
  ("I regret to inform you, sir") or colloquial ("yo what's good").
  Dialog density measures *how much* dialog exists, not what register
  it uses.

- **pacing** tracks *narrative speed*.  Dialog often accelerates pacing,
  but not always — a long philosophical dialog can slow a story to a
  crawl.  Pacing measures *rate of change*; dialog density measures
  *mode of presentation*.

- **tension** tracks *anticipation and forward pull*.  A whispered
  confession in dialog can be high-tension; a dinner order in dialog
  can be zero-tension.  Tension is about *narrative pull*; dialog
  density is about *structural mode*.

- **concreteness** tracks *sensory grounding*.  Dialog can be concrete
  ("pass the salt") or abstract ("justice requires patience").
  Concreteness measures *what kind of language*; dialog density
  measures *who is speaking*.

- **prose_rhythm** tracks *variation in sentence length*.  Dialog
  tends to have shorter sentences, but rhythm is about *patterning*,
  not about whether the words are spoken or narrated.

Dialog density asks: **how much of this text is people talking,
versus the narrator telling?**

Dimensions
----------

========================  ==============================================
metric                    meaning
========================  ==============================================
dialog_ratio              fraction of text tokens that appear inside
                          quotation marks (double quotes "...", single
                          quotes used for dialog, em-dash dialog, and
                          guillemets)
attribution_density       fraction of dialog segments accompanied by
                          a speech attribution verb (said, asked, replied,
                          whispered, shouted, muttered, etc.) within the
                          same or adjacent sentence
quote_count               total number of distinct dialog segments found
                          in the text
mean_quote_length          average number of words per dialog segment;
                          indicates whether dialog is terse ("Go.") or
                          expansive ("Well, you see, the thing about
                          quantum mechanics is...")
dialog_turn_frequency     number of dialog turns per 1000 words;
                          measures how *often* characters speak,
                          regardless of how *much* they say
narrative_bridge_ratio    fraction of text between dialog segments that
                          contains narrative description (action beats,
                          setting, internal thought) vs bare attribution
                          ("she said"); higher values indicate richer
                          narrative framing between dialog lines
dialog_density_index      composite score (0.0 to 1.0) combining
                          dialog_ratio (0.30), dialog_turn_frequency
                          normalized (0.20), quote_count normalized
                          (0.15), mean_quote_length normalized (0.15),
                          and narrative_bridge_ratio (0.20)
classification            categorical label based on index value:
                          dialog_heavy (>=0.60), mixed (>=0.40),
                          narrative_heavy (>=0.20), pure_narrative (<0.20)
========================  ==============================================
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple


# ── Speech attribution verbs ────────────────────────────────────────
SPEECH_VERBS: frozenset = frozenset({
    # common
    "said", "says", "ask", "asked", "asking",
    "replied", "reply", "replies", "answered", "answer", "answers",
    "responded", "respond", "responds",
    # volume
    "whispered", "whisper", "whispers",
    "shouted", "shout", "shouts",
    "yelled", "yell", "yells",
    "muttered", "mutter", "mutters",
    "mumbled", "mumble", "mumbles",
    "bellowed", "bellow", "bellows",
    "screamed", "scream", "screams",
    "hissed", "hiss", "hisses",
    "roared", "roar", "roars",
    "growled", "growl", "growls",
    "snapped", "snap", "snaps",
    "barked", "bark", "barks",
    # manner
    "demanded", "demand", "demands",
    "insisted", "insist", "insists",
    "suggested", "suggest", "suggests",
    "offered", "offer", "offers",
    "begged", "beg", "begs",
    "pleaded", "plead", "pleads",
    "admitted", "admit", "admits",
    "confessed", "confess", "confesses",
    "declared", "declare", "declares",
    "exclaimed", "exclaim", "exclaims",
    "remarked", "remark", "remarks",
    "observed", "observe", "observes",
    "noted", "note", "notes",
    "explained", "explain", "explains",
    "continued", "continue", "continues",
    "added", "add", "adds",
    "agreed", "agree", "agrees",
    "denied", "deny", "denies",
    "promised", "promise", "promises",
    "warned", "warn", "warns",
    "advised", "advise", "advises",
    "urged", "urge", "urges",
    "complained", "complain", "complains",
    "grumbled", "grumble", "grumbles",
    "protested", "protest", "protests",
    "stammered", "stammer", "stammers",
    "stuttered", "stutter", "stutters",
    "gasped", "gasp", "gasps",
    "sighed", "sigh", "sighs",
    "groaned", "groan", "groans",
    "moaned", "moan", "moans",
    "cried", "cry", "cries",
    "sang", "sing", "sings",
    "intoned", "intone", "intones",
    "recited", "recite", "recites",
    "read", "reads",
    "wrote", "write", "writes", "written",
    "called", "call", "calls",
    "announced", "announce", "announces",
    "proclaimed", "proclaim", "proclaims",
    "reported", "report", "reports",
    "stated", "state", "states",
    "testified", "testify", "testifies",
    "swore", "swear", "swears",
    "vowed", "vow", "vows",
    "commanded", "command", "commands",
    "ordered", "order", "orders",
    "instructed", "instruct", "instructs",
    "requested", "request", "requests",
    "begged",
    "implored", "implore", "implores",
    "entreated", "entreat", "entreats",
    "beseeched", "beseech", "beseeches",
    "echoed", "echo", "echoes",
    "repeated", "repeat", "repeats",
    "murmured", "murmur", "murmurs",
})

# ── Common dialog openers (words that frequently begin spoken text) ──
DIALOG_OPENERS: frozenset = frozenset({
    "yes", "no", "yeah", "nah", "nope", "yep", "yup",
    "hello", "hi", "hey", "goodbye", "bye",
    "please", "sorry", "thanks", "thank",
    "well", "look", "listen", "okay", "ok",
    "oh", "ah", "ohh", "hmm", "huh", "uh",
    "sure", "right", "fine", "whatever",
    "wait", "stop", "help",
})

# ── Function words (for content word filtering) ─────────────────────
FUNCTION_WORDS: frozenset = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "shall", "should", "may", "might", "must", "can",
    "could", "am", "i", "you", "he", "she", "it", "we", "they",
    "me", "him", "her", "us", "them", "my", "your", "his", "its",
    "our", "their", "this", "that", "these", "those", "and", "but",
    "or", "nor", "for", "yet", "so", "in", "on", "at", "to",
    "from", "by", "with", "of", "about", "into", "through",
    "during", "before", "after", "above", "below", "between",
    "under", "over", "not", "no", "if", "then", "than",
})


class WriterDialogDensity:
    """Analyze dialog density in prose text."""

    def __init__(self) -> None:
        self.speech_verbs = SPEECH_VERBS
        self.dialog_openers = DIALOG_OPENERS
        self.function_words = FUNCTION_WORDS
        # Compile regex patterns once
        self._double_quote_re = re.compile(r'"([^"]*)"')
        self._smart_double_quote_re = re.compile(r'\u201c([^\u201d]*)\u201d')
        self._single_quote_re = re.compile(r"'([^']{2,})'")
        self._smart_single_quote_re = re.compile(r'\u2018([^\u2019]{2,})\u2019')
        self._em_dash_dialog_re = re.compile(
            r'(?:^|\n)\s*(?:\u2014|--)\s*(.+?)(?=\n\s*(?:\u2014|--)|\n\n|$)',
            re.MULTILINE,
        )
        self._guillemet_re = re.compile(r'\u00ab([^\u00bb]*)\u00bb')
        self._sentence_end_re = re.compile(r'[.!?]+')
        self._word_re = re.compile(r"[a-zA-Z']+")

    # ── Helpers ──────────────────────────────────────────────────────

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences, stripping trailing punctuation."""
        if not text or not text.strip():
            return []
        parts = re.split(r'(?<=[.!?])\s+', text.strip())
        return [p.strip() for p in parts if p.strip()]

    def _tokenize(self, text: str) -> List[str]:
        """Extract lowercase word tokens."""
        return self._word_re.findall(text.lower())

    def _extract_quoted_segments(self, text: str) -> List[str]:
        """Extract all quoted text segments from the prose.

        Checks for:
        - Standard double quotes: "dialog"
        - Smart double quotes: \u201c dialog \u201d
        - Single quotes used for dialog: 'dialog' (min 2 chars to skip
          contractions)
        - Smart single quotes: \u2018 dialog \u2019
        - Em-dash dialog: \u2014 dialog (common in Russian, French,
          Spanish literature)
        - Guillemets: \u00ab dialog \u00bb (French, Italian, etc.)
        """
        segments: List[str] = []

        # Standard double quotes
        segments.extend(self._double_quote_re.findall(text))

        # Smart double quotes (curly)
        segments.extend(self._smart_double_quote_re.findall(text))

        # Guillemets
        segments.extend(self._guillemet_re.findall(text))

        # Em-dash dialog (only if no standard quotes found, to avoid
        # double-counting em-dashes used for parenthetical phrases)
        if not segments:
            segments.extend(self._em_dash_dialog_re.findall(text))

        # Single quotes as fallback (only longer segments to avoid
        # matching contractions like "don't" or possessives)
        if not segments:
            single_matches = self._single_quote_re.findall(text)
            segments.extend(m for m in single_matches if len(m.split()) >= 2)

        # Smart single quotes as last fallback
        if not segments:
            smart_single = self._smart_single_quote_re.findall(text)
            segments.extend(m for m in smart_single if len(m.split()) >= 2)

        return [s.strip() for s in segments if s.strip()]

    def _has_speech_attribution(
        self, text: str, segment: str, segment_start: int, segment_end: int
    ) -> bool:
        """Check if a dialog segment has a speech attribution verb nearby.

        Looks in a window of ~40 characters before the quote and ~60
        characters after it for a speech verb.
        """
        # Build context window
        pre_start = max(0, segment_start - 60)
        post_end = min(len(text), segment_end + 80)
        context_before = text[pre_start:segment_start].lower()
        context_after = text[segment_end:post_end].lower()

        # Check for speech verbs in surrounding context
        before_tokens = self._tokenize(context_before)
        after_tokens = self._tokenize(context_after)

        for token in before_tokens + after_tokens:
            if token in self.speech_verbs:
                return True
        return False

    def _is_narrative_bridge(self, text: str, start: int, end: int) -> bool:
        """Check if text between dialog segments is narrative (not bare).

        A bare attribution is just 'she said.' or 'he asked.'
        A narrative bridge contains action beats, description, or
        internal thought.
        """
        bridge = text[start:end].strip()
        if not bridge:
            return False
        tokens = self._tokenize(bridge)
        if not tokens:
            return False
        content_words = [t for t in tokens if t not in self.function_words]
        # Bare attribution: very short, mostly function words
        # Narrative bridge: has content words, action, description
        if len(content_words) >= 2 and len(tokens) >= 4:
            return True
        return False

    # ── Measurement methods ──────────────────────────────────────────

    def measure_dialog_ratio(self, text: str) -> float:
        """Fraction of total tokens that appear inside quotation marks."""
        all_tokens = self._tokenize(text)
        if not all_tokens:
            return 0.0
        segments = self._extract_quoted_segments(text)
        if not segments:
            return 0.0
        dialog_token_count = sum(len(self._tokenize(seg)) for seg in segments)
        return min(dialog_token_count / len(all_tokens), 1.0)

    def measure_attribution_density(
        self, text: str, segments: List[str] | None = None
    ) -> float:
        """Fraction of dialog segments with speech verb attribution."""
        if segments is None:
            segments = self._extract_quoted_segments(text)
        if not segments:
            return 0.0

        attributed = 0
        for seg in segments:
            # Find segment position in text
            idx = text.find(seg)
            if idx < 0:
                continue
            seg_start = max(0, idx - 2)  # account for quote char
            seg_end = idx + len(seg) + 2
            if self._has_speech_attribution(text, seg, seg_start, seg_end):
                attributed += 1

        return attributed / len(segments)

    def measure_quote_count(self, text: str) -> int:
        """Count distinct dialog segments."""
        return len(self._extract_quoted_segments(text))

    def measure_mean_quote_length(self, text: str) -> float:
        """Average word count per dialog segment."""
        segments = self._extract_quoted_segments(text)
        if not segments:
            return 0.0
        lengths = [len(self._tokenize(seg)) for seg in segments]
        return sum(lengths) / len(lengths)

    def measure_dialog_turn_frequency(self, text: str) -> float:
        """Dialog turns per 1000 words."""
        all_tokens = self._tokenize(text)
        if not all_tokens:
            return 0.0
        quote_count = self.measure_quote_count(text)
        return (quote_count / len(all_tokens)) * 1000.0

    def measure_narrative_bridge_ratio(self, text: str) -> float:
        """Fraction of inter-dialog gaps with narrative (not bare attr)."""
        # Find quote positions in text
        quote_positions: List[Tuple[int, int]] = []
        for pattern in [
            self._double_quote_re,
            self._smart_double_quote_re,
            self._guillemet_re,
        ]:
            for match in pattern.finditer(text):
                quote_positions.append((match.start(), match.end()))

        if len(quote_positions) < 2:
            return 0.0

        # Sort by position
        quote_positions.sort(key=lambda p: p[0])

        bridges = 0
        narrative_bridges = 0
        for i in range(len(quote_positions) - 1):
            gap_start = quote_positions[i][1]
            gap_end = quote_positions[i + 1][0]
            gap_text = text[gap_start:gap_end].strip()
            if gap_text:
                bridges += 1
                if self._is_narrative_bridge(text, gap_start, gap_end):
                    narrative_bridges += 1

        if bridges == 0:
            return 0.0
        return narrative_bridges / bridges

    def compute_dialog_density_index(
        self,
        dialog_ratio: float,
        turn_frequency: float,
        quote_count: int,
        mean_length: float,
        bridge_ratio: float,
    ) -> float:
        """Compute weighted composite dialog density score."""
        # Normalize turn_frequency: typical range 0-50 per 1000 words
        norm_turns = min(turn_frequency / 30.0, 1.0)
        # Normalize quote_count: typical range 0-50
        norm_count = min(quote_count / 30.0, 1.0)
        # Normalize mean_length: typical range 1-30 words
        norm_length = min(mean_length / 20.0, 1.0)

        return (
            dialog_ratio * 0.30
            + norm_turns * 0.20
            + norm_count * 0.15
            + norm_length * 0.15
            + bridge_ratio * 0.20
        )

    def classify(self, index: float) -> str:
        """Classify dialog density level."""
        if index >= 0.60:
            return "dialog_heavy"
        elif index >= 0.40:
            return "mixed"
        elif index >= 0.20:
            return "narrative_heavy"
        else:
            return "pure_narrative"

    def measure(self, text: str) -> Dict:
        """Measure all dialog density metrics for given text."""
        if not text or not text.strip():
            return {
                "dialog_ratio": 0.0,
                "attribution_density": 0.0,
                "quote_count": 0,
                "mean_quote_length": 0.0,
                "dialog_turn_frequency": 0.0,
                "narrative_bridge_ratio": 0.0,
                "dialog_density_index": 0.0,
                "classification": "pure_narrative",
            }

        dialog_ratio = self.measure_dialog_ratio(text)
        quote_count = self.measure_quote_count(text)
        segments = self._extract_quoted_segments(text)
        attribution = self.measure_attribution_density(text, segments)
        mean_length = self.measure_mean_quote_length(text)
        turn_freq = self.measure_dialog_turn_frequency(text)
        bridge_ratio = self.measure_narrative_bridge_ratio(text)

        index = self.compute_dialog_density_index(
            dialog_ratio, turn_freq, quote_count, mean_length, bridge_ratio
        )
        classification = self.classify(index)

        return {
            "dialog_ratio": round(dialog_ratio, 4),
            "attribution_density": round(attribution, 4),
            "quote_count": quote_count,
            "mean_quote_length": round(mean_length, 4),
            "dialog_turn_frequency": round(turn_freq, 4),
            "narrative_bridge_ratio": round(bridge_ratio, 4),
            "dialog_density_index": round(index, 4),
            "classification": classification,
        }


if __name__ == "__main__":
    dialog_heavy = """
    "What time is it?" she asked, glancing at the clock.
    "Almost midnight," he replied without looking up.
    "We should go," she said, pulling on her coat.
    "Wait," he called after her. "I need to tell you something."
    "What?" she asked from the doorway.
    "I never meant for any of this to happen," he said quietly.
    """

    narrative_heavy = """
    The rain fell in sheets across the empty parking lot, pooling
    in the cracked asphalt where weeds had broken through. A single
    streetlight flickered at the far end, casting long shadows
    across the rows of abandoned shopping carts. The wind carried
    the smell of wet earth and gasoline from the station across
    the road. No one had been here for hours. The last car had
    left before sunset, its taillights fading into the gray
    horizon like dying embers.
    """

    wdd = WriterDialogDensity()

    print("=== Dialog-Heavy Text ===")
    result = wdd.measure(dialog_heavy)
    for key, value in result.items():
        print(f"{key:30s} {value}")

    print("\n=== Narrative-Heavy Text ===")
    result = wdd.measure(narrative_heavy)
    for key, value in result.items():
        print(f"{key:30s} {value}")
