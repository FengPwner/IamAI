#!/usr/bin/env python3
"""writer_passive_voice_density — measure passive vs. active voice usage.

The passive voice is one of the most debated constructions in English
prose.  Strunk & White warn against it; the APA manual tolerates it;
scientific journals often demand it.  "The experiment was conducted"
hides the actor; "We conducted the experiment" foregrounds it.  Both
are grammatically correct — the choice is rhetorical.

Passive voice is not inherently bad.  It serves legitimate purposes:

- **Agent irrelevant**: "The road was built in 1923" — who built it
  is not the point.
- **Agent unknown**: "The server was compromised at 03:00" — we
  don't know who did it.
- **Focus on patient**: "The patient was given 50mg of…" — the
  patient, not the doctor, is the topic.
- **Diplomacy**: "Mistakes were made" — avoids assigning blame
  when the goal is moving forward.

But excessive passive voice creates distance between the reader
and the action.  A text where everything "was done" or "is
believed" or "has been observed" reads as bureaucratic, evasive,
or timorous.  The reader asks: *who* did this?  *who* believes
this?  When the answer is consistently hidden, trust erodes.

This module detects passive voice through the standard linguistic
pattern: a form of *be* (or *get*) followed by a past participle.

**Be-passive patterns**:
- is/was/were/are/been/being/am + past_participle
- "The cake was eaten", "The results were published"

**Get-passive patterns**:
- get/got/getting/gets + past_participle
- "The window got broken", "He got fired"

**Past participle detection**:
- Regular: -ed ending (played, opened, committed)
- Irregular: common set (written, taken, seen, done, given,
  known, found, made, built, sold, broken, chosen, driven,
  eaten, fallen, forgotten, grown, hidden, ridden, risen,
  shaken, shown, spoken, stolen, swollen, torn, worn, etc.)

Each passive is further classified:

- **Agentless passive**: no "by" phrase — "The code was reviewed"
- **Agent passive**: explicit "by" phrase — "The code was reviewed
  by the team"
- **Get-passive**: informal register — "The bug got fixed"

From these signals a session-level classification is computed:

| passive_rate  | classification    | description                       |
|---------------|-------------------|-----------------------------------|
| < 5%          | active_dominant   | prose lives in the active voice   |
| 5–15%         | balanced          | mix of active and passive         |
| 15–25%        | passive_leaning   | passive voice is the default      |
| 25–40%        | bureaucratic      | heavy passive, agency obscured    |
| > 40%         | institutional     | almost no visible actors          |

This metric is orthogonal to hedging (confidence language),
formality (register level), verbosity (word count), and
nominalization density (noun-from-verb conversion).  A formal
paper can be active-dominant; a casual blog can be bureaucratic.

written by Qwen during manual caretaker visit 664, 2026-11-17
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from collections import Counter


# ── auxiliary be-forms ──────────────────────────────────────────

_BE_FORMS = {
    "am", "is", "are", "was", "were",
    "be", "been", "being",
}

_GET_FORMS = {"get", "gets", "got", "gotten", "getting"}

# Contractions that contain be-forms
_BE_CONTRACTIONS = {
    "'m", "'s", "'re",  # I'm, he's, they're
}


# ── common irregular past participles ──────────────────────────

_IRREGULAR_PARTICIPLES = {
    # high-frequency irregulars
    "arisen", "awoken", "been", "beaten", "become", "begun",
    "bent", "bet", "bidden", "bitten", "bled", "blown",
    "born", "bought", "bound", "bred", "brought", "broken",
    "built", "burnt", "burst", "cast", "caught", "chosen",
    "clung", "come", "cost", "crept", "cut", "dealt",
    "done", "drawn", "dreamt", "driven", "drunk", "dug",
    "eaten", "fallen", "fed", "felt", "fled", "flown",
    "flung", "forbidden", "forecast", "forgiven", "forgotten",
    "forsaken", "found", "frozen", "given", "gone", "got",
    "gotten", "ground", "grown", "had", "heard", "held",
    "hidden", "hit", "hung", "hurt", "kept", "knelt",
    "knit", "known", "laid", "led", "left", "lent",
    "let", "lain", "lit", "lost", "made", "meant",
    "met", "misled", "mistaken", "misunderstood", "mown",
    "outdone", "outgrown", "outrun", "overcome", "overdone",
    "overtaken", "paid", "pleaded", "proved", "put",
    "quit", "read", "rebound", "redone", "ridden",
    "risen", "run", "said", "sat", "seen", "sold",
    "sent", "set", "sewn", "shaken", "shone", "shot",
    "shown", "shrunk", "shut", "slain", "slept", "slid",
    "slung", "smelt", "sneaked", "sold", "sought",
    "spoken", "spent", "spilt", "spit", "split",
    "spoilt", "sprung", "spun", "stolen", "stood",
    "stuck", "stung", "stunk", "stridden", "striven",
    "struck", "strung", "sung", "sunk", "sworn",
    "swept", "swollen", "swum", "swung", "taken",
    "taught", "thought", "thrown", "told", "torn",
    "trodden", "undergone", "understood", "undertaken",
    "undone", "unwound", "upheld", "waken", "wept",
    "woken", "won", "wound", "withdrawn", "withheld",
    "withstood", "worn", "woven", "wrung", "written",
}


# ── data class ──────────────────────────────────────────────────


@dataclass
class PassiveVoiceResult:
    """Result of passive voice analysis."""

    # counts
    passive_count: int = 0
    active_count: int = 0
    total_clauses: int = 0

    # rates
    passive_rate: float = 0.0        # passive clauses per 100 clauses
    passive_per_100_words: float = 0.0

    # subtypes
    agentless_passive: int = 0
    agent_passive: int = 0
    get_passive: int = 0

    # ratios
    agentless_ratio: float = 0.0     # fraction of passives that are agentless

    # details
    passive_verbs: List[str] = field(default_factory=list)
    top_passive_verbs: List[Tuple[str, int]] = field(default_factory=list)

    # classification
    classification: str = "unknown"

    # metadata
    word_count: int = 0
    sentence_count: int = 0


# ── helpers ─────────────────────────────────────────────────────


def _tokenize(text: str) -> List[str]:
    """Split text into lowercased word tokens (letters/apostrophes only)."""
    return re.findall(r"[a-z']+", text.lower())


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences on . ! ? followed by space or end."""
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]


def _is_past_participle(word: str) -> bool:
    """Check whether a word looks like a past participle."""
    if word in _IRREGULAR_PARTICIPLES:
        return True
    # regular -ed ending (but not bare -e or -eed without stem)
    if word.endswith("ed") and len(word) > 3:
        return True
    # -en ending (broken, chosen, driven, etc.)
    if word.endswith("en") and len(word) > 3:
        return True
    # -t ending for some irregulars (built, burnt, dealt, etc.)
    if word.endswith("t") and len(word) > 3 and word in _IRREGULAR_PARTICIPLES:
        return True
    return False


def _find_passives_in_sentence(sentence: str) -> List[Tuple[str, str, str]]:
    """Find passive constructions in a sentence.

    Returns list of (be_form, participle, subtype) tuples.
    subtype is one of: 'agentless', 'agent', 'get_passive'.
    """
    tokens = _tokenize(sentence)
    lower_sentence = sentence.lower()
    results = []

    for i in range(len(tokens) - 1):
        tok = tokens[i]

        # Check for be-passive: be-form + past participle
        is_be = tok in _BE_FORMS
        # Also check if the token is a contraction containing be
        if not is_be:
            # Handle "he's" → tokens might be ["he", "'s"]
            # But our tokenizer splits on apostrophe, so "'s" is a token
            if tok in _BE_CONTRACTIONS:
                is_be = True

        # Check for get-passive: get-form + past participle
        is_get = tok in _GET_FORMS

        if is_be or is_get:
            next_tok = tokens[i + 1]
            # Skip if next word is an adverb (not/well/already/etc.)
            # The participle might be 2 positions ahead
            pp_candidate = next_tok
            pp_offset = 1

            # Common adverbs that can appear between be and participle
            _INTERVENING_ADVERBS = {
                "not", "n't", "already", "just", "recently",
                "never", "often", "always", "well", "badly",
                "quickly", "slowly", "carefully", "largely",
                "widely", "commonly", "frequently", "rarely",
                "seldom", "still", "also", "even", "yet",
                "now", "once", "ever",
            }

            if pp_candidate in _INTERVENING_ADVERBS and i + 2 < len(tokens):
                pp_candidate = tokens[i + 2]
                pp_offset = 2

            if _is_past_participle(pp_candidate):
                # Determine subtype
                if is_get:
                    subtype = "get_passive"
                elif re.search(r'\bby\s+\w', sentence.lower()):
                    subtype = "agent"
                else:
                    subtype = "agentless"

                results.append((tok, pp_candidate, subtype))

    return results


# ── main analysis ───────────────────────────────────────────────


def measure_passive_voice(text: str) -> PassiveVoiceResult:
    """Analyse passive voice density in a text.

    Args:
        text: The prose to analyse.

    Returns:
        PassiveVoiceResult with counts, rates, and classification.
    """
    if not text or not text.strip():
        return PassiveVoiceResult(classification="unknown")

    sentences = _split_sentences(text)
    if not sentences:
        return PassiveVoiceResult(classification="unknown")

    tokens = _tokenize(text)
    word_count = len(tokens)
    if word_count == 0:
        return PassiveVoiceResult(classification="unknown")

    sentence_count = len(sentences)
    passive_count = 0
    agentless = 0
    agent = 0
    get_pass = 0
    passive_verbs: List[str] = []
    verb_counter: Counter = Counter()

    for sent in sentences:
        found = _find_passives_in_sentence(sent)
        for be_form, participle, subtype in found:
            passive_count += 1
            passive_verbs.append(participle)
            verb_counter[participle] += 1
            if subtype == "agentless":
                agentless += 1
            elif subtype == "agent":
                agent += 1
            else:
                get_pass += 1

    # Estimate active clauses (total finite verbs minus passives)
    # Simple heuristic: count tokens that look like main verbs
    # (not auxiliaries, not participles already counted)
    # For simplicity, estimate active = sentence_count * 1.5 - passive_count
    # (average ~1.5 clauses per sentence in English prose)
    estimated_total_clauses = max(sentence_count, passive_count + 1)
    active_count = max(0, estimated_total_clauses - passive_count)
    total_clauses = passive_count + active_count

    # Rates
    passive_rate = (passive_count / total_clauses * 100) if total_clauses > 0 else 0.0
    passive_per_100 = (passive_count / word_count * 100) if word_count > 0 else 0.0

    # Agentless ratio
    agentless_ratio = (agentless / passive_count) if passive_count > 0 else 0.0

    # Top passive verbs
    top_verbs = verb_counter.most_common(5)

    # Classification based on passive_rate (percentage of clauses that are passive)
    if passive_rate < 5:
        classification = "active_dominant"
    elif passive_rate < 15:
        classification = "balanced"
    elif passive_rate < 25:
        classification = "passive_leaning"
    elif passive_rate < 40:
        classification = "bureaucratic"
    else:
        classification = "institutional"

    return PassiveVoiceResult(
        passive_count=passive_count,
        active_count=active_count,
        total_clauses=total_clauses,
        passive_rate=round(passive_rate, 2),
        passive_per_100_words=round(passive_per_100, 2),
        agentless_passive=agentless,
        agent_passive=agent,
        get_passive=get_pass,
        agentless_ratio=round(agentless_ratio, 3),
        passive_verbs=passive_verbs,
        top_passive_verbs=top_verbs,
        classification=classification,
        word_count=word_count,
        sentence_count=sentence_count,
    )
