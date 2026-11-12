#!/usr/bin/env python3
"""writer_conviction — measure whether writing commits to its statements.

Conviction is the willingness of a writer to stand behind what they say.
A writer with conviction makes declarative claims, owns their opinions,
and avoids the verbal tics of self-protective hedging.  A writer without
conviction hides behind qualifiers, weasel words, and passive
constructions that disown responsibility.

This module is orthogonal to the other writer metrics:

- **restraint** tracks *what is left unsaid*.  Restraint is the discipline
  of omission — choosing not to say things.  Conviction is about *how*
  you say what you do say.  A restrained writer can still have strong
  conviction in the words they choose to include.

- **subtext** tracks *layers of meaning beneath the surface*.  Subtext
  is about implication.  A writer can have conviction in explicit
  statements while embedding rich subtext — conviction is about the
  surface layer, subtext about what lies below.

- **confidence** (if tracked separately) would be about the *writer's
  psychological state*.  Conviction is a textual property — the writing
  *reads* as committed, regardless of how the writer felt.  An anxious
  writer can produce text with conviction; a confident writer can produce
  hedged text.

- **elegance** tracks *craft quality*.  Elegant prose can lack conviction
  (beautifully hedged, artfully noncommittal).  Conviction is about
  commitment, not beauty.

- **voice_consistency** tracks *whether the voice stays the same*.
  Conviction is about *what kind* of voice it is — committed or evasive.

Conviction asks: **does the text stand behind its claims, or does it
flinch from commitment?**

Four signals are tracked:

1. **Hedge density** — frequency of hedge words and phrases per hundred
   words.  Hedges soften or retract commitment: "perhaps", "maybe",
   "it seems", "it might be", "arguably", "somewhat", "to some extent",
   "in a way", "one could argue".  Not all hedging is bad — intellectual
   honesty requires hedging when evidence is genuinely uncertain — but
   excessive hedging signals a writer afraid to commit.

2. **Weasel constructions** — phrases that disown the claim by attributing
   it to unnamed sources or vague consensus: "it is said that", "some
   people think", "many believe", "it is generally accepted", "they say",
   "one might say", "it could be argued".  These constructions let the
   writer make a point without standing behind it.

3. **Categorical markers** — the positive signal: declarative assertions,
   "I think", "I believe", "the evidence shows", "the data indicates",
   unqualified statements, imperatives, and future-tense commitments
   ("we will", "this must").  A text with high categorical density
   commits to its positions.

4. **Self-undermining patterns** — phrases that preemptively apologize
   or weaken the upcoming statement: "I'm no expert, but...", "this
   might be wrong, but...", "just my opinion", "take this with a grain
   of salt", "I could be wrong", "don't quote me on this".  These are
   the textual equivalent of shrinking back before anyone has challenged
   you.

From these signals a session-level **conviction_index** is computed
and classified:

==============  ============================================================
class           meaning
==============  ============================================================
resolute        index >= 0.75 — strong, committed voice; declarations
                outnumber hedges; the writer stands behind their words
                and owns their positions
assertive       0.55 <= index < 0.75 — mostly confident; occasional
                hedging but the overall voice is committed and direct
measured        0.35 <= index < 0.55 — balanced between commitment and
                caution; some hedging that may be appropriate for the
                subject matter, but the voice could be more direct
tentative       0.20 <= index < 0.35 — hesitant; hedges and weasel
                constructions outnumber declarations; the writer seems
                uncertain or afraid to commit
diffident       index < 0.20 — deeply evasive; almost every claim is
                softened, attributed to others, or preemptively
                apologized for; the text reads as if the writer is
                bracing for objection before any has been raised
==============  ============================================================

Orthogonal to restraint (restraint = discipline of omission; conviction =
commitment in expression), subtext (subtext = implied meaning; conviction =
explicit commitment), and elegance (elegance = craft quality; conviction =
stance ownership).
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants: hedge words and phrases
# ---------------------------------------------------------------------------

# Words that soften or avoid commitment
HEDGE_WORDS = [
    re.compile(r"\bperhaps\b", re.I),
    re.compile(r"\bmaybe\b", re.I),
    re.compile(r"\bpossibly\b", re.I),
    re.compile(r"\bprobably\b", re.I),
    re.compile(r"\barguably\b", re.I),
    re.compile(r"\bsomewhat\b", re.I),
    re.compile(r"\bslightly\b", re.I),
    re.compile(r"\brather\b", re.I),
    re.compile(r"\bsort of\b", re.I),
    re.compile(r"\bkind of\b", re.I),
    re.compile(r"\ba bit\b", re.I),
    re.compile(r"\ba little\b", re.I),
    re.compile(r"\bto some (extent|degree)\b", re.I),
    re.compile(r"\bin a (way|sense)\b", re.I),
    re.compile(r"\bat least (partially|partly)\b", re.I),
    re.compile(r"\bnot (entirely|necessarily|always|exactly)\b", re.I),
    re.compile(r"\bseemingly\b", re.I),
    re.compile(r"\bapparently\b", re.I),
    re.compile(r"\bsupposedly\b", re.I),
    re.compile(r"\bostensibly\b", re.I),
]

# Hedge phrases — multi-word constructions that soften commitment
HEDGE_PHRASES = [
    re.compile(r"\bit (seems|appears|looks) (like|that|as if)\b", re.I),
    re.compile(r"\bit (might|could|may|would) be (that|the case|argued|said|suggested|noted)\b", re.I),
    re.compile(r"\bone (could|might|may|would) (argue|say|suggest|think|believe|assume)\b", re.I),
    re.compile(r"\bthere (might|could|may|would) be\b", re.I),
    re.compile(r"\bit is (possible|conceivable|plausible|unclear|uncertain|debatable|questionable)\b", re.I),
    re.compile(r"\b(I|we) (think|guess|suppose|imagine|reckon) (maybe|perhaps|possibly)?\b", re.I),
    re.compile(r"\b(I|we) (am|are) not (sure|certain|convinced) (if|whether|that)?\b", re.I),
    re.compile(r"\b(I|we) (would|might|could) (say|suggest|argue|think|guess)\b", re.I),
]


# ---------------------------------------------------------------------------
# Constants: weasel constructions
# ---------------------------------------------------------------------------

WEASEL_PHRASES = [
    re.compile(r"\bsome (people|experts|analysts|observers|critics|say|think|believe|argue|suggest|claim)\b", re.I),
    re.compile(r"\bmany (people|experts|analysts|observers|critics|say|think|believe|argue|suggest|claim)\b", re.I),
    re.compile(r"\bit is (said|believed|thought|claimed|argued|suggested|generally accepted|widely held|commonly understood|well known)\b", re.I),
    re.compile(r"\bthey (say|think|believe|claim|suggest|argue)\b", re.I),
    re.compile(r"\baccording to (some|many|various|several) (sources?|reports?|experts?|analysts?|observers?)\b", re.I),
    re.compile(r"\bconventional wisdom (holds|suggests|says|dictates)\b", re.I),
    re.compile(r"\bit is (often|sometimes|frequently|commonly|generally) (said|claimed|argued|believed|thought|suggested)\b", re.I),
    re.compile(r"\b(one|you|we) (could|might|may|would) (argue|say|think|suggest|claim)\b", re.I),
    re.compile(r"\bresearch (suggests|indicates|implies|may show|could indicate)\b", re.I),
    re.compile(r"\bstudies (suggest|indicate|imply|may show|could indicate)\b", re.I),
]


# ---------------------------------------------------------------------------
# Constants: categorical / commitment markers (positive signal)
# ---------------------------------------------------------------------------

CATEGORICAL_MARKERS = [
    re.compile(r"\b(I|we) (think|believe|know|assert|maintain|contend|hold|insist)\b", re.I),
    re.compile(r"\bthe (evidence|data|facts|record|results?) (show|demonstrate|prove|confirm|establish|indicate|reveal|make clear)\b", re.I),
    re.compile(r"\b(it|this|that) is (clear|obvious|evident|undeniable|certain|true|the case)\b", re.I),
    re.compile(r"\b(we|you|they) (must|should|need to|have to|ought to)\b", re.I),
    re.compile(r"\b(we|I) will\b", re.I),
    re.compile(r"\bno (doubt|question)\b", re.I),
    re.compile(r"\bwithout (question|doubt|exception)\b", re.I),
    re.compile(r"\bin (fact|reality|truth)\b", re.I),
    re.compile(r"\bthe (truth|reality|fact) is\b", re.I),
    re.compile(r"\blet me be (clear|direct|plain|frank|honest)\b", re.I),
]

# Imperatives and declaratives that signal ownership
COMMITMENT_VERBS = [
    re.compile(r"\b(decide|choose|commit|stand|support|oppose|reject|accept|endorse|demand|insist|guarantee|promise|pledge)\b", re.I),
]


# ---------------------------------------------------------------------------
# Constants: self-undermining patterns
# ---------------------------------------------------------------------------

SELF_UNDERMINING = [
    re.compile(r"\b(I'm|I am) (not an expert|no expert|not a specialist|not qualified)\b", re.I),
    re.compile(r"\b(this|it|I) might be wrong\b", re.I),
    re.compile(r"\b(I could|I may|I might) be (wrong|mistaken|off base|off base)\b", re.I),
    re.compile(r"\bjust my (opinion|take|view|thought|two cents)\b", re.I),
    re.compile(r"\btake (this|it) with a grain of salt\b", re.I),
    re.compile(r"\bdon't quote me on (this|that)\b", re.I),
    re.compile(r"\bfor what it'?s worth\b", re.I),
    re.compile(r"\bthis is (probably|likely|maybe) (wrong|incorrect|off)\b", re.I),
    re.compile(r"\bI (hate to|don't want to) (say|admit|point out)\b", re.I),
    re.compile(r"\bnot that (I|it)\b", re.I),
    re.compile(r"\bI (stand to be|could be) corrected\b", re.I),
    re.compile(r"\bwith all due respect\b", re.I),
    re.compile(r"\bno offense(, but)?\b", re.I),
]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _split_words(text: str) -> list[str]:
    """Split text into lowercase words, stripping punctuation."""
    return [w.lower() for w in re.findall(r"[a-zA-Z']+", text)]


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    cleaned = re.sub(r"(Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc)\.", r"\1DOT", text)
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    return [s.replace("DOT", ".") for s in sentences if s.strip()]


def _get_stroke_text(stroke: dict[str, Any] | str) -> str:
    """Extract text from a stroke (string or dict)."""
    if isinstance(stroke, str):
        return stroke
    for key in ("text", "content", "body"):
        if key in stroke and isinstance(stroke[key], str):
            return stroke[key]
    return ""


def _count_pattern_matches(text: str, patterns: list[re.Pattern]) -> int:
    """Count total matches across a list of patterns."""
    total = 0
    for pat in patterns:
        total += len(pat.findall(text))
    return total


# ---------------------------------------------------------------------------
# Signal 1: Hedge density
# ---------------------------------------------------------------------------


def compute_hedge_density(text: str) -> dict[str, Any]:
    """Measure frequency of hedge words and phrases per hundred words.

    Returns
    -------
    dict with keys:
        hedge_words: int
        hedge_phrases: int
        total_hedges: int
        word_count: int
        density: float  (hedges per 100 words)
    """
    words = _split_words(text)
    word_count = max(len(words), 1)

    hw = _count_pattern_matches(text, HEDGE_WORDS)
    hp = _count_pattern_matches(text, HEDGE_PHRASES)
    total = hw + hp
    density = (total / word_count) * 100

    return {
        "hedge_words": hw,
        "hedge_phrases": hp,
        "total_hedges": total,
        "word_count": word_count,
        "density": round(density, 4),
    }


# ---------------------------------------------------------------------------
# Signal 2: Weasel constructions
# ---------------------------------------------------------------------------


def compute_weasel_density(text: str) -> dict[str, Any]:
    """Measure frequency of weasel/disowning constructions per hundred words.

    Returns
    -------
    dict with keys:
        weasel_count: int
        word_count: int
        density: float  (weasels per 100 words)
    """
    words = _split_words(text)
    word_count = max(len(words), 1)

    wc = _count_pattern_matches(text, WEASEL_PHRASES)
    density = (wc / word_count) * 100

    return {
        "weasel_count": wc,
        "word_count": word_count,
        "density": round(density, 4),
    }


# ---------------------------------------------------------------------------
# Signal 3: Categorical / commitment markers
# ---------------------------------------------------------------------------


def compute_categorical_density(text: str) -> dict[str, Any]:
    """Measure frequency of declarative/commitment markers per hundred words.

    Returns
    -------
    dict with keys:
        categorical_count: int
        commitment_verbs: int
        total: int
        word_count: int
        density: float  (commitment markers per 100 words)
    """
    words = _split_words(text)
    word_count = max(len(words), 1)

    cc = _count_pattern_matches(text, CATEGORICAL_MARKERS)
    cv = _count_pattern_matches(text, COMMITMENT_VERBS)
    total = cc + cv
    density = (total / word_count) * 100

    return {
        "categorical_count": cc,
        "commitment_verbs": cv,
        "total": total,
        "word_count": word_count,
        "density": round(density, 4),
    }


# ---------------------------------------------------------------------------
# Signal 4: Self-undermining patterns
# ---------------------------------------------------------------------------


def compute_self_undermining(text: str) -> dict[str, Any]:
    """Measure frequency of self-undermining/apologetic phrases.

    Returns
    -------
    dict with keys:
        undermining_count: int
        word_count: int
        density: float  (self-undermining per 100 words)
    """
    words = _split_words(text)
    word_count = max(len(words), 1)

    uc = _count_pattern_matches(text, SELF_UNDERMINING)
    density = (uc / word_count) * 100

    return {
        "undermining_count": uc,
        "word_count": word_count,
        "density": round(density, 4),
    }


# ---------------------------------------------------------------------------
# Per-stroke analysis
# ---------------------------------------------------------------------------


def analyze_stroke_conviction(stroke: dict[str, Any] | str) -> dict[str, Any]:
    """Analyze conviction signals for a single stroke.

    Returns
    -------
    dict with all four signal analyses plus a composite conviction_score.
    """
    text = _get_stroke_text(stroke)
    if not text or not text.strip():
        return {
            "hedges": compute_hedge_density(""),
            "weasels": compute_weasel_density(""),
            "categorical": compute_categorical_density(""),
            "undermining": compute_self_undermining(""),
            "conviction_score": 0.0,
            "conviction_class": "diffident",
        }

    hedges = compute_hedge_density(text)
    weasels = compute_weasel_density(text)
    categorical = compute_categorical_density(text)
    undermining = compute_self_undermining(text)

    # Normalize signals: lower hedges/weasels/undermining = higher conviction
    # Higher categorical = higher conviction
    #
    # Hedge score: 0 hedges per 100 words = 1.0, 10+ = 0.0
    hedge_score = max(0.0, 1.0 - (hedges["density"] / 10.0))

    # Weasel score: 0 weasels per 100 words = 1.0, 5+ = 0.0
    weasel_score = max(0.0, 1.0 - (weasels["density"] / 5.0))

    # Categorical score: some commitment markers are good
    # 0 per 100 words = 0.2 (neutral — short text might not have any)
    # 5+ per 100 words = 1.0
    cat_score = min(1.0, 0.2 + (categorical["density"] / 5.0) * 0.8)

    # Undermining score: 0 = 1.0, 3+ = 0.0
    undermine_score = max(0.0, 1.0 - (undermining["density"] / 3.0))

    # Weighted composite
    score = (
        0.30 * hedge_score
        + 0.20 * weasel_score
        + 0.30 * cat_score
        + 0.20 * undermine_score
    )

    return {
        "hedges": hedges,
        "weasels": weasels,
        "categorical": categorical,
        "undermining": undermining,
        "conviction_score": round(score, 4),
        "conviction_class": _classify_conviction(score),
    }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _classify_conviction(score: float) -> str:
    """Classify a conviction score into a human-readable label."""
    if score >= 0.75:
        return "resolute"
    elif score >= 0.55:
        return "assertive"
    elif score >= 0.35:
        return "measured"
    elif score >= 0.20:
        return "tentative"
    else:
        return "diffident"


# ---------------------------------------------------------------------------
# Session-level metrics
# ---------------------------------------------------------------------------


def compute_conviction_metrics(
    strokes: list[dict[str, Any] | str],
    window_size: int = 50,
) -> dict[str, Any]:
    """Compute session-level conviction metrics over recent strokes.

    Parameters
    ----------
    strokes : list
        List of stroke dicts or strings.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict with session-level conviction metrics.
    """
    if not strokes:
        return _empty_metrics()

    recent = strokes[-window_size:]
    analyses = [analyze_stroke_conviction(s) for s in recent]

    if not analyses:
        return _empty_metrics()

    scores = [a["conviction_score"] for a in analyses]
    avg_score = sum(scores) / len(scores)

    total_words = sum(a["hedges"]["word_count"] for a in analyses)
    total_hedges = sum(a["hedges"]["total_hedges"] for a in analyses)
    total_weasels = sum(a["weasels"]["weasel_count"] for a in analyses)
    total_categorical = sum(a["categorical"]["total"] for a in analyses)
    total_undermining = sum(a["undermining"]["undermining_count"] for a in analyses)

    conviction_class = _classify_conviction(avg_score)

    # Class distribution
    class_dist: dict[str, int] = {}
    for a in analyses:
        cc = a["conviction_class"]
        class_dist[cc] = class_dist.get(cc, 0) + 1

    return {
        "strokes_analyzed": len(analyses),
        "total_words": total_words,
        "conviction_index": round(avg_score, 4),
        "conviction_class": conviction_class,
        "total_hedges": total_hedges,
        "total_weasels": total_weasels,
        "total_categorical": total_categorical,
        "total_undermining": total_undermining,
        "hedge_density": round(
            (total_hedges / total_words * 100) if total_words > 0 else 0.0, 4
        ),
        "weasel_density": round(
            (total_weasels / total_words * 100) if total_words > 0 else 0.0, 4
        ),
        "categorical_density": round(
            (total_categorical / total_words * 100) if total_words > 0 else 0.0, 4
        ),
        "undermining_density": round(
            (total_undermining / total_words * 100) if total_words > 0 else 0.0, 4
        ),
        "class_distribution": class_dist,
    }


def _empty_metrics() -> dict[str, Any]:
    """Return empty metrics structure."""
    return {
        "strokes_analyzed": 0,
        "total_words": 0,
        "conviction_index": 0.0,
        "conviction_class": "diffident",
        "total_hedges": 0,
        "total_weasels": 0,
        "total_categorical": 0,
        "total_undermining": 0,
        "hedge_density": 0.0,
        "weasel_density": 0.0,
        "categorical_density": 0.0,
        "undermining_density": 0.0,
        "class_distribution": {},
    }


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------


def compute_conviction_trend(
    strokes: list[dict[str, Any] | str],
    window_size: int = 20,
    step: int = 10,
) -> list[dict[str, Any]]:
    """Compute conviction snapshots over time for trend analysis.

    Parameters
    ----------
    strokes : list
        Full stroke list.
    window_size : int
        Strokes per snapshot window.
    step : int
        Stride between windows.

    Returns
    -------
    list[dict]
        List of snapshot dicts with conviction metrics.
    """
    if not strokes:
        return []

    snapshots: list[dict[str, Any]] = []
    for start in range(0, max(1, len(strokes) - window_size + 1), step):
        window = strokes[start : start + window_size]
        metrics = compute_conviction_metrics(window, window_size)
        metrics["window_start"] = start
        snapshots.append(metrics)
    return snapshots


def classify_trend(snapshots: list[dict[str, Any]]) -> str:
    """Classify the conviction trend from snapshots.

    Returns one of: strengthening, stable, weakening, insufficient_data.
    """
    if len(snapshots) < 2:
        return "insufficient_data"

    scores = [s.get("conviction_index", 0.0) for s in snapshots]
    first_half = scores[: len(scores) // 2]
    second_half = scores[len(scores) // 2 :]

    avg_first = sum(first_half) / len(first_half) if first_half else 0.0
    avg_second = sum(second_half) / len(second_half) if second_half else 0.0

    delta = avg_second - avg_first

    if delta > 0.05:
        return "strengthening"
    elif delta < -0.05:
        return "weakening"
    else:
        return "stable"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def format_conviction_report(metrics: dict[str, Any]) -> str:
    """Format conviction metrics as a human-readable report."""
    lines = [
        "=== Writer Conviction ===",
        f"Strokes analyzed:          {metrics['strokes_analyzed']}",
        f"Total words:               {metrics['total_words']}",
        f"Conviction index:          {metrics['conviction_index']:.4f} ({metrics['conviction_class']})",
        "",
        f"Total hedges:              {metrics['total_hedges']}",
        f"Total weasels:             {metrics['total_weasels']}",
        f"Total categorical markers:{metrics['total_categorical']}",
        f"Total self-undermining:    {metrics['total_undermining']}",
        f"Hedge density:             {metrics['hedge_density']:.4f}/100w",
        f"Weasel density:            {metrics['weasel_density']:.4f}/100w",
        f"Categorical density:       {metrics['categorical_density']:.4f}/100w",
        f"Undermining density:       {metrics['undermining_density']:.4f}/100w",
        "",
    ]

    dist = metrics.get("class_distribution", {})
    if dist:
        lines.append("Class distribution:")
        for cls in ("resolute", "assertive", "measured", "tentative", "diffident"):
            count = dist.get(cls, 0)
            if count:
                lines.append(f"  {cls:14s} {count}")
        lines.append("")

    cc = metrics["conviction_class"]
    lines.append("Interpretation:")
    if cc == "resolute":
        lines.append("  Strong, committed voice. Declarations outnumber hedges;")
        lines.append("  the writer stands behind their words.")
    elif cc == "assertive":
        lines.append("  Mostly confident. Occasional hedging but the overall")
        lines.append("  voice is committed and direct.")
    elif cc == "measured":
        lines.append("  Balanced between commitment and caution. Some hedging")
        lines.append("  may be appropriate; the voice could be more direct.")
    elif cc == "tentative":
        lines.append("  Hesitant. Hedges and weasel constructions outnumber")
        lines.append("  declarations; the writer seems uncertain.")
    else:
        lines.append("  Deeply evasive. Almost every claim is softened or")
        lines.append("  disowned; the text reads as bracing for objection.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Standalone analysis (reads from strokes.jsonl)
# ---------------------------------------------------------------------------


def analyze_conviction(
    strokes_path: str = "data/strokes.jsonl",
    window_size: int = 50,
) -> dict[str, Any]:
    """Analyze conviction from the strokes file.

    Parameters
    ----------
    strokes_path : str
        Path to strokes JSONL file.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict
        Conviction metrics.
    """
    path = Path(strokes_path)
    if not path.exists():
        return _empty_metrics()

    strokes: list[dict[str, Any]] = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    strokes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    return compute_conviction_metrics(strokes, window_size)


if __name__ == "__main__":
    metrics = analyze_conviction()
    print(format_conviction_report(metrics))
