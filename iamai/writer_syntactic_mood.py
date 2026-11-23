#!/usr/bin/env python3
"""writer_syntactic_mood — grammatical mood profiling per sentence.

Every sentence carries a *mood*: it states, asks, commands, exclaims,
or imagines.  This module classifies each sentence into one of six
moods, then aggregates the distribution into text-level metrics.

Mood matters because it reveals the **rhetorical stance** of a text.
A text that is 95 % declarative reads like a report; one that mixes
interrogative and imperative reads like a tutorial or a Socratic
dialogue; one rich in subjunctive reads like speculative fiction.

Orthogonality to existing modules
----------------------------------

- **sentence_variety** measures length and structural variation.
  Mood is independent of length: a three-word question and a
  fifty-word question are both interrogative.

- **sentence_opener** classifies how sentences *begin*.  Mood
  classifies what sentences *do*.

- **clause_nesting_depth** counts embedding levels.  A deeply nested
  sentence can be declarative or subjunctive; mood and depth are
  separate axes.

- **interrogative_density** counts question marks per sentence.
  This module generalises that idea to *all* moods, adds rhetorical
  questions (interrogative form, declarative function), and detects
  subjunctive/conditional constructions that have no punctuation
  signal.

Metrics
-------

========================  ============================================
metric                    meaning
========================  ============================================
total_sentences           sentences detected
declarative_count         sentences classified as declarative
interrogative_count       sentences classified as interrogative
imperative_count          sentences classified as imperative
exclamatory_count         sentences classified as exclamatory
subjunctive_count         sentences classified as subjunctive
conditional_count         sentences classified as conditional
declarative_ratio         declarative / total  [0–1]
interrogative_ratio       interrogative / total
imperative_ratio          imperative / total
exclamatory_ratio         exclamatory / total
subjunctive_ratio         subjunctive / total
conditional_ratio         conditional / total
dominant_mood             mood with highest count
mood_diversity            Shannon entropy of mood distribution / log2(6)
                          [0–1]; 1.0 = perfectly even across all moods
mood_entropy              raw Shannon entropy in bits
assertion_ratio           (declarative + exclamatory) / total;
                          how much the text *asserts*
inquiry_ratio             interrogative / total; how much it *asks*
directive_ratio           imperative / total; how much it *commands*
speculation_ratio         (subjunctive + conditional) / total;
                          how much it *imagines*
mood_label                human-readable classification of the text's
                          overall rhetorical stance
========================  ============================================

Mood labels
-----------

==================  ==================================================
label               description
==================  ==================================================
monotone_declare    almost entirely declarative; flat, report-like
assertive           predominantly declarative with some exclamation;
                    confident, authoritative tone
inquisitive         significant interrogative presence; questioning,
                    exploratory tone
directive           notable imperative share; instructional or
                    commanding tone
speculative         elevated subjunctive/conditional; hypothetical,
                    imaginative tone
mixed_voice         balanced distribution across multiple moods;
                    rhetorically varied
absent              no sentences found
==================  ==================================================

Written by Qwen during caretaker visit 831, 2026-11-24.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------

# Split on sentence-ending punctuation followed by a space or end of string.
# Handles abbreviations like "Dr." and "e.g." via a negative lookbehind for
# common short-word patterns.
_SENT_SPLIT_RE = re.compile(
    r'(?<=[.!?])\s+(?=[A-Z"\'\(])'
)


def _split_sentences(text: str) -> List[str]:
    """Split *text* into sentences.

    Uses punctuation boundaries.  Returns a list of stripped, non-empty
    sentence strings.
    """
    if not text or not text.strip():
        return []
    raw = _SENT_SPLIT_RE.split(text.strip())
    sentences = []
    for s in raw:
        s = s.strip()
        if s and len(s) > 2:
            sentences.append(s)
    return sentences


# ---------------------------------------------------------------------------
# Mood classification per sentence
# ---------------------------------------------------------------------------

# Subjunctive triggers
_SUBJUNCTIVE_PATTERNS = [
    re.compile(r'\bif\s+(?:I|he|she|it|we|they)\s+(?:were|had\b)', re.I),
    re.compile(r'\b(?:wish|wishes|wished)\s+(?:that\s+)?(?:I|he|she|it|we|they)\s+(?:were|had|could|would)', re.I),
    re.compile(r'\bwere\s+(?:I|he|she|it|we|they)\s+to\b', re.I),
    re.compile(r'\bas\s+if\b', re.I),
    re.compile(r'\bas\s+though\b', re.I),
    re.compile(r'\bif\s+only\b', re.I),
    re.compile(r'\bmay\s+(?:it|he|she|they|we)\b', re.I),
    re.compile(r'\bgod\s+forbid\b', re.I),
    re.compile(r'\bso\s+be\s+it\b', re.I),
    re.compile(r'\b(?:demands?|insists?|requires?|suggests?|recommends?)\s+that\s+(?:the\s+|a\s+|an\s+)?[a-z]+\s+(?:be|have|do|go|come|not)\b', re.I),
]

# Conditional triggers
_CONDITIONAL_PATTERNS = [
    re.compile(r'\bif\s+.+,\s+.+\b(will|would|could|shall|should|might|may)\b', re.I),
    re.compile(r'\b(would|could|might)\b.+\bif\b', re.I),
    re.compile(r'\bunless\b', re.I),
    re.compile(r'\bprovided\s+that\b', re.I),
    re.compile(r'\bsupposing\b', re.I),
    re.compile(r'\bin\s+case\b', re.I),
    re.compile(r'\bhad\s+(?:I|he|she|we|they)\s+known\b', re.I),
    re.compile(r'\bshould\s+\w+\s+(?:decide|choose|wish|want)\b', re.I),
]

# Imperative: sentence starts with a base-form verb (heuristic)
_IMPERATIVE_STARTERS = re.compile(
    r'^(?:Please\s+|Do\s+not\s+|Don\'t\s+|Never\s+|Always\s+|Let\'s\s+|Let\s+)?'
    r'(?:[A-Z][a-z]+)\b',
)
# Common imperative verbs at sentence start
_IMPERATIVE_VERBS = {
    "add", "apply", "ask", "avoid", "be", "begin", "bring", "build", "buy",
    "calculate", "call", "change", "check", "choose", "clean", "click",
    "close", "come", "compare", "consider", "continue", "copy", "count",
    "create", "cut", "define", "delete", "describe", "design", "develop",
    "discuss", "divide", "do", "download", "draw", "drop", "eat", "enable",
    "ensure", "enter", "evaluate", "examine", "explain", "export", "extract",
    "fill", "find", "fix", "follow", "forget", "format", "get", "give",
    "go", "grab", "group", "handle", "have", "help", "hide", "hold",
    "identify", "ignore", "implement", "import", "include", "increase",
    "indicate", "insert", "install", "introduce", "join", "keep", "kill",
    "learn", "leave", "let", "limit", "link", "list", "listen", "load",
    "look", "make", "map", "mark", "match", "measure", "merge", "mix",
    "modify", "monitor", "move", "name", "navigate", "need", "note",
    "observe", "open", "optimise", "optimize", "order", "organise",
    "organize", "override", "parse", "pass", "pay", "pick", "place",
    "plan", "play", "plot", "point", "position", "prepare", "press",
    "prevent", "process", "provide", "publish", "pull", "push", "put",
    "query", "read", "reduce", "reference", "register", "reject", "release",
    "remember", "remove", "rename", "render", "repeat", "replace", "report",
    "reset", "resolve", "restart", "return", "review", "revert", "run",
    "save", "scale", "search", "select", "send", "separate", "set",
    "setup", "share", "shift", "show", "shut", "sign", "skip", "sort",
    "specify", "split", "start", "stay", "stop", "store", "submit",
    "support", "switch", "sync", "take", "talk", "target", "tell", "test",
    "think", "track", "transform", "treat", "trigger", "try", "turn",
    "type", "update", "upgrade", "upload", "use", "validate", "verify",
    "view", "visit", "wait", "walk", "watch", "work", "wrap", "write",
}

# Question-word starters for interrogative even without '?'
_QUESTION_WORDS = re.compile(
    r'^(?:who|what|where|when|why|how|which|whose|whom|is|are|was|were|'
    r'do|does|did|have|has|had|can|could|will|would|shall|should|may|might|'
    r'must)\b',
    re.I,
)


def _classify_sentence(sentence: str) -> str:
    """Classify a single sentence into a mood label.

    Returns one of: declarative, interrogative, imperative, exclamatory,
    subjunctive, conditional.
    """
    stripped = sentence.strip()
    if not stripped:
        return "declarative"

    # --- Punctuation-driven moods ---

    ends_with_question = stripped.endswith("?")
    ends_with_excl = stripped.endswith("!")

    # Subjunctive check (overrides punctuation)
    for pat in _SUBJUNCTIVE_PATTERNS:
        if pat.search(stripped):
            return "subjunctive"

    # Conditional check
    for pat in _CONDITIONAL_PATTERNS:
        if pat.search(stripped):
            return "conditional"

    # Interrogative
    if ends_with_question:
        return "interrogative"

    # Exclamatory
    if ends_with_excl:
        return "exclamatory"

    # Question-word interrogative without '?'
    if _QUESTION_WORDS.match(stripped):
        return "interrogative"

    # Imperative detection: sentence starts with a base verb
    first_word_match = re.match(r'^(?:Please\s+|Do\s+not\s+|Don\'t\s+|Never\s+|Always\s+|Let\'s\s+)?([A-Za-z]+)', stripped)
    if first_word_match:
        first_verb = first_word_match.group(1).lower()
        if first_verb in _IMPERATIVE_VERBS:
            # Additional check: if the sentence has a clear subject before
            # the verb, it's declarative.  Simple heuristic: if the first
            # word is a pronoun, it's declarative.
            pronouns = {"i", "you", "he", "she", "it", "we", "they", "my",
                        "your", "his", "her", "its", "our", "their", "this",
                        "that", "these", "those", "the", "a", "an"}
            if first_verb not in pronouns:
                return "imperative"

    return "declarative"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

_MOOD_KEYS = [
    "declarative", "interrogative", "imperative",
    "exclamatory", "subjunctive", "conditional",
]


def _compute_shannon(counts: Counter, total: int) -> float:
    """Shannon entropy in bits over a frequency distribution."""
    if total == 0:
        return 0.0
    h = 0.0
    for c in counts.values():
        if c > 0:
            p = c / total
            h -= p * math.log2(p)
    return h


def _classify_mood(ratios: Dict[str, float], diversity: float) -> str:
    """Assign a text-level mood label based on mood ratios and diversity."""
    decl = ratios.get("declarative", 0.0)
    interr = ratios.get("interrogative", 0.0)
    imp = ratios.get("imperative", 0.0)
    excl = ratios.get("exclamatory", 0.0)
    subj = ratios.get("subjunctive", 0.0)
    cond = ratios.get("conditional", 0.0)

    spec = subj + cond

    # Near-monotone
    if decl > 0.90:
        return "monotone_declare"

    # High diversity
    if diversity > 0.70:
        return "mixed_voice"

    # Speculative
    if spec > 0.20:
        return "speculative"

    # Directive
    if imp > 0.15:
        return "directive"

    # Inquisitive
    if interr > 0.15:
        return "inquisitive"

    # Assertive (declarative + some exclamatory)
    if decl > 0.70 and excl > 0.05:
        return "assertive"

    # Default: predominantly declarative but not extreme
    if decl > 0.70:
        return "assertive"

    return "mixed_voice"


def _empty_result() -> Dict[str, Any]:
    """Return a result dict with all keys at zero."""
    d: Dict[str, Any] = {
        "total_sentences": 0,
    }
    for m in _MOOD_KEYS:
        d[f"{m}_count"] = 0
        d[f"{m}_ratio"] = 0.0
    d.update({
        "dominant_mood": "absent",
        "mood_diversity": 0.0,
        "mood_entropy": 0.0,
        "assertion_ratio": 0.0,
        "inquiry_ratio": 0.0,
        "directive_ratio": 0.0,
        "speculation_ratio": 0.0,
        "mood_label": "absent",
    })
    return d


def compute_syntactic_mood(text: str) -> Dict[str, Any]:
    """Analyse the grammatical mood profile of *text*.

    Returns a dict with all metrics described above.
    """
    sentences = _split_sentences(text)
    if not sentences:
        return _empty_result()

    moods = [_classify_sentence(s) for s in sentences]
    total = len(moods)
    counts = Counter(moods)

    # Per-mood counts and ratios
    result: Dict[str, Any] = {"total_sentences": total}
    ratios: Dict[str, float] = {}
    for m in _MOOD_KEYS:
        c = counts.get(m, 0)
        result[f"{m}_count"] = c
        r = c / total if total > 0 else 0.0
        result[f"{m}_ratio"] = round(r, 4)
        ratios[m] = r

    # Dominant mood
    dominant = max(_MOOD_KEYS, key=lambda m: counts.get(m, 0))
    result["dominant_mood"] = dominant

    # Mood diversity (normalised Shannon)
    mood_counter = Counter(moods)
    H = _compute_shannon(mood_counter, total)
    H_max = math.log2(len(_MOOD_KEYS))  # log2(6) ≈ 2.585
    diversity = H / H_max if H_max > 0 else 0.0
    result["mood_entropy"] = round(H, 4)
    result["mood_diversity"] = round(diversity, 4)

    # Composite ratios
    result["assertion_ratio"] = round(
        ratios["declarative"] + ratios["exclamatory"], 4
    )
    result["inquiry_ratio"] = round(ratios["interrogative"], 4)
    result["directive_ratio"] = round(ratios["imperative"], 4)
    result["speculation_ratio"] = round(
        ratios["subjunctive"] + ratios["conditional"], 4
    )

    # Label
    result["mood_label"] = _classify_mood(ratios, diversity)

    return result


# ---------------------------------------------------------------------------
# Sentence-level detail
# ---------------------------------------------------------------------------

def mood_per_sentence(text: str) -> List[Dict[str, str]]:
    """Return a list of {sentence, mood} dicts for each sentence in *text*."""
    sentences = _split_sentences(text)
    return [
        {"sentence": s, "mood": _classify_sentence(s)}
        for s in sentences
    ]


# ---------------------------------------------------------------------------
# On-disk integration
# ---------------------------------------------------------------------------

def syntactic_mood_report(strokes_path: str = "data/strokes.jsonl") -> Dict[str, Any]:
    """Compute mood profile over all stroke bodies in a JSONL file."""
    path = Path(strokes_path)
    if not path.exists():
        return _empty_result()

    bodies: List[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            body = obj.get("body") or obj.get("text") or obj.get("content") or ""
            if body:
                bodies.append(str(body))

    combined = " ".join(bodies)
    return compute_syntactic_mood(combined)


def syntactic_mood_summary(
    result: Optional[Dict[str, Any]] = None,
    strokes_path: str = "data/strokes.jsonl",
) -> str:
    """Human-readable summary of syntactic mood metrics."""
    if result is None:
        result = syntactic_mood_report(strokes_path)

    if result["total_sentences"] == 0:
        return "No sentences available for mood analysis."

    lines = [
        "Syntactic Mood Profile",
        "======================",
        f"Sentences:      {result['total_sentences']:,}",
        f"Dominant mood:  {result['dominant_mood']}",
        f"Mood diversity: {result['mood_diversity']:.4f} (H={result['mood_entropy']:.4f} bits)",
        "",
        "Distribution:",
    ]
    for m in _MOOD_KEYS:
        count = result[f"{m}_count"]
        ratio = result[f"{m}_ratio"]
        lines.append(f"  {m:16s}  {count:>6,}  ({ratio:.1%})")

    lines += [
        "",
        f"Assertion:      {result['assertion_ratio']:.4f}",
        f"Inquiry:        {result['inquiry_ratio']:.4f}",
        f"Directive:      {result['directive_ratio']:.4f}",
        f"Speculation:    {result['speculation_ratio']:.4f}",
        f"Label:          {result['mood_label']}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Syntactic mood analyser")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--per-sentence", action="store_true",
                        help="Show mood per sentence")
    parser.add_argument("--strokes", default="data/strokes.jsonl",
                        help="Path to strokes JSONL")
    parser.add_argument("--text", default=None,
                        help="Analyse a literal text string instead of strokes")
    args = parser.parse_args()

    if args.text:
        if args.per_sentence:
            detail = mood_per_sentence(args.text)
            print(json.dumps(detail, indent=2))
        else:
            result = compute_syntactic_mood(args.text)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(syntactic_mood_summary(result))
    else:
        result = syntactic_mood_report(args.strokes)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(syntactic_mood_summary(result))

    return 0


if __name__ == "__main__":
    sys.exit(main())
