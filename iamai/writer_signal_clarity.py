#!/usr/bin/env python3
"""writer_signal_clarity — measure whether a writer produces substantive,
unique content versus repetitive filler or noise.

A clear signal means each stroke carries new information: a fresh idea,
a distinct observation, a meaningful extension of prior work. A noisy
signal means strokes repeat the same phrases, recycle the same metrics,
or pad the log with filler that adds volume without substance.

Signal clarity is orthogonal to momentum and synthesis. A writer can
have high momentum (extending recent work) but low clarity (repeating
the same extension over and over). A writer can have high synthesis
(weaving many threads) but low clarity (weaving the same threads in
the same way each time). Clarity asks: *is this stroke saying something
new?*

The module detects three kinds of noise:

1. **Verbatim repetition** — strokes that are near-duplicates of recent
   strokes (high text overlap measured by Jaccard similarity on word
   sets).
2. **Template looping** — strokes that follow the same structural
   template with only variable substitution (e.g. "X is already in the
   pool of 9 modules, nothing new to add there").
3. **Metric recycling** — strokes that report the same metric values
   as recent strokes without meaningful change (the numbers haven't
   moved enough to justify the report).

A writer with perfect clarity never says the same thing twice. A writer
with zero clarity is a broken record. Most productive writers sit
somewhere in between, and this module helps them notice when they're
slipping toward noise.

Dimensions
----------

========================  ================================================
metric                    meaning
========================  ================================================
uniqueness_ratio          fraction of strokes in the window that are not
                          near-duplicates of any other stroke in the
                          window; higher = less verbatim repetition
template_diversity        number of distinct structural templates detected
                          divided by total strokes; higher = more varied
                          output structure
information_delta         average Jaccard distance between consecutive
                          strokes; higher = each stroke brings more new
                          content relative to its predecessor
filler_ratio              fraction of strokes classified as filler
                          (near-duplicate, template loop, or recycled
                          metric); the inverse of signal
clarity_class             broadcast | communicator | repeater | noise
========================  ================================================

Clarity classes
---------------

==============  ============================================================
class           meaning
==============  ============================================================
broadcast       score >= 0.75 — nearly every stroke carries unique content;
                the writer rarely repeats themselves and output is
                consistently substantive
communicator    0.50 <= score < 0.75 — healthy signal with occasional
                repetition; the normal mode for sustained automated writing
                where some metric updates are expected
repeater        0.25 <= score < 0.50 — significant noise; many strokes are
                near-duplicates or template filler; the writer is producing
                volume but not proportional value
noise           score < 0.25 — output is dominated by repetition; most
                strokes could be deleted without losing information;
                intervention is needed to restore signal
==============  ============================================================
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> set[str]:
    """Lowercase word-level tokenization for Jaccard comparison."""
    return set(re.findall(r"\w+", text.lower()))


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two token sets."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union > 0 else 0.0


def _jaccard_distance(a: set[str], b: set[str]) -> float:
    """Jaccard distance (1 - similarity)."""
    return 1.0 - _jaccard_similarity(a, b)


def _extract_template(stroke_text: str) -> str:
    """Extract structural template from stroke text by replacing variables.

    Replaces numbers, file paths, hashes, and proper nouns with
    placeholders so that two strokes differing only in variable values
    produce the same template signature.
    """
    t = stroke_text.strip()
    # Replace ISO timestamps first (before numbers consume the digits)
    t = re.sub(r"\d{4}-\d{2}-\d{2}T[\d:]+(?:[+-]\d{2}:\d{2})?", "<TS>", t)
    # Replace hex hashes
    t = re.sub(r"[0-9a-f]{7,}", "<HASH>", t)
    # Replace file paths (before numbers, to avoid partial replacement)
    t = re.sub(r"\S+\.\w{1,5}\b", "<PATH>", t)
    # Replace numbers (integers and floats)
    t = re.sub(r"\b\d+(?:\.\d+)?\b", "<N>", t)
    return t


def _is_near_duplicate(
    tokens_a: set[str],
    tokens_b: set[str],
    threshold: float = 0.80,
) -> bool:
    """Check if two token sets are near-duplicates."""
    return _jaccard_similarity(tokens_a, tokens_b) >= threshold


def _is_filler_stroke(
    stroke: dict[str, Any],
    recent_tokens: list[set[str]],
    template_counts: dict[str, int],
    near_dup_threshold: float = 0.80,
    template_repeat_threshold: int = 3,
) -> bool:
    """Classify a stroke as filler based on three noise signals.

    A stroke is filler if ANY of:
    1. It is a near-duplicate of any recent stroke.
    2. Its template has been seen >= template_repeat_threshold times.
    3. It has very few tokens (< 5) and matches a recent stroke.
    """
    text = stroke.get("text", "") or stroke.get("content", "") or ""
    tokens = _tokenize(text)

    # Check near-duplicate against recent
    for rt in recent_tokens:
        if _is_near_duplicate(tokens, rt, near_dup_threshold):
            return True

    # Check template repetition
    template = _extract_template(text)
    if template_counts.get(template, 0) >= template_repeat_threshold:
        return True

    # Very short strokes that overlap with recent
    if len(tokens) < 5 and len(tokens) > 0:
        for rt in recent_tokens:
            if len(rt) > 0 and _jaccard_similarity(tokens, rt) >= 0.60:
                return True

    return False


# ---------------------------------------------------------------------------
# Core metrics
# ---------------------------------------------------------------------------

def compute_clarity_metrics(
    strokes: list[dict[str, Any]],
    window_size: int = 20,
    near_dup_threshold: float = 0.80,
    template_repeat_threshold: int = 3,
) -> dict[str, Any]:
    """Compute signal clarity metrics for a list of strokes.

    Parameters
    ----------
    strokes : list[dict]
        Stroke records, each with at least a 'text' or 'content' field.
    window_size : int
        Number of strokes to analyze.
    near_dup_threshold : float
        Jaccard similarity threshold for near-duplicate detection.
    template_repeat_threshold : int
        Number of template repetitions before classifying as template loop.

    Returns
    -------
    dict with keys: uniqueness_ratio, template_diversity, information_delta,
    filler_ratio, clarity_score, clarity_class.
    """
    if not strokes:
        return _empty_metrics()

    n = min(len(strokes), window_size)
    window = strokes[-n:]

    # Tokenize all strokes
    all_tokens: list[set[str]] = []
    for s in window:
        text = s.get("text", "") or s.get("content", "") or ""
        all_tokens.append(_tokenize(text))

    # --- Uniqueness ratio ---
    duplicate_count = 0
    for i in range(len(all_tokens)):
        for j in range(i + 1, len(all_tokens)):
            if _is_near_duplicate(all_tokens[i], all_tokens[j], near_dup_threshold):
                duplicate_count += 1
                break  # count each stroke at most once as duplicate
    uniqueness_ratio = 1.0 - (duplicate_count / n) if n > 0 else 0.0

    # --- Template diversity ---
    templates: list[str] = []
    for s in window:
        text = s.get("text", "") or s.get("content", "") or ""
        templates.append(_extract_template(text))
    unique_templates = len(set(templates))
    template_diversity = unique_templates / n if n > 0 else 0.0

    # --- Information delta ---
    deltas: list[float] = []
    for i in range(1, len(all_tokens)):
        deltas.append(_jaccard_distance(all_tokens[i - 1], all_tokens[i]))
    information_delta = sum(deltas) / len(deltas) if deltas else 0.0

    # --- Filler ratio ---
    template_counts: dict[str, int] = {}
    for t in templates:
        template_counts[t] = template_counts.get(t, 0) + 1

    filler_count = 0
    recent_window: list[set[str]] = []
    for i, s in enumerate(window):
        recent = recent_window[-5:]  # compare against last 5
        if _is_filler_stroke(s, recent, template_counts,
                             near_dup_threshold, template_repeat_threshold):
            filler_count += 1
        text = s.get("text", "") or s.get("content", "") or ""
        recent_window.append(_tokenize(text))

    filler_ratio = filler_count / n if n > 0 else 0.0

    # --- Composite clarity score ---
    # Weight: uniqueness (30%), template diversity (25%),
    #         information delta (25%), inverse filler (20%)
    clarity_score = (
        0.30 * uniqueness_ratio
        + 0.25 * template_diversity
        + 0.25 * information_delta
        + 0.20 * (1.0 - filler_ratio)
    )

    # --- Classification ---
    clarity_class = _classify(clarity_score)

    return {
        "uniqueness_ratio": round(uniqueness_ratio, 4),
        "template_diversity": round(template_diversity, 4),
        "information_delta": round(information_delta, 4),
        "filler_ratio": round(filler_ratio, 4),
        "clarity_score": round(clarity_score, 4),
        "clarity_class": clarity_class,
        "strokes_analyzed": n,
        "duplicate_count": duplicate_count,
        "filler_count": filler_count,
        "unique_templates": unique_templates,
    }


def _classify(score: float) -> str:
    """Classify writer signal clarity from composite score."""
    if score >= 0.75:
        return "broadcast"
    elif score >= 0.50:
        return "communicator"
    elif score >= 0.25:
        return "repeater"
    else:
        return "noise"


def _empty_metrics() -> dict[str, Any]:
    """Return empty metrics when no strokes are available."""
    return {
        "uniqueness_ratio": 0.0,
        "template_diversity": 0.0,
        "information_delta": 0.0,
        "filler_ratio": 0.0,
        "clarity_score": 0.0,
        "clarity_class": "noise",
        "strokes_analyzed": 0,
        "duplicate_count": 0,
        "filler_count": 0,
        "unique_templates": 0,
    }


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def compute_clarity_trend(
    strokes: list[dict[str, Any]],
    window_size: int = 20,
    step: int = 10,
) -> list[dict[str, Any]]:
    """Compute clarity metrics over sliding windows.

    Parameters
    ----------
    strokes : list[dict]
        Full stroke history.
    window_size : int
        Size of each analysis window.
    step : int
        Step between consecutive windows.

    Returns
    -------
    list[dict]
        One metrics dict per window.
    """
    if len(strokes) < window_size:
        return [compute_clarity_metrics(strokes, window_size)]

    snapshots: list[dict[str, Any]] = []
    for start in range(0, len(strokes) - window_size + 1, step):
        window = strokes[start : start + window_size]
        metrics = compute_clarity_metrics(window, window_size)
        metrics["window_start"] = start
        snapshots.append(metrics)

    return snapshots


def classify_trend(snapshots: list[dict[str, Any]]) -> str:
    """Classify the clarity trend from snapshots.

    Returns
    -------
    str
        One of: improving, stable, degrading, insufficient_data.
    """
    if len(snapshots) < 2:
        return "insufficient_data"

    scores = [s.get("clarity_score", 0.0) for s in snapshots]
    first_half = scores[: len(scores) // 2]
    second_half = scores[len(scores) // 2 :]

    avg_first = sum(first_half) / len(first_half) if first_half else 0.0
    avg_second = sum(second_half) / len(second_half) if second_half else 0.0

    delta = avg_second - avg_first

    if delta > 0.05:
        return "improving"
    elif delta < -0.05:
        return "degrading"
    else:
        return "stable"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def format_clarity_report(metrics: dict[str, Any]) -> str:
    """Format clarity metrics as a human-readable report."""
    lines = [
        "=== Writer Signal Clarity ===",
        f"Strokes analyzed: {metrics['strokes_analyzed']}",
        f"Clarity score:    {metrics['clarity_score']:.4f} ({metrics['clarity_class']})",
        "",
        f"Uniqueness ratio:    {metrics['uniqueness_ratio']:.4f}",
        f"Template diversity:  {metrics['template_diversity']:.4f}",
        f"Information delta:   {metrics['information_delta']:.4f}",
        f"Filler ratio:        {metrics['filler_ratio']:.4f}",
        "",
        f"Near-duplicates:     {metrics['duplicate_count']}",
        f"Filler strokes:      {metrics['filler_count']}",
        f"Unique templates:    {metrics['unique_templates']}",
        "",
    ]

    cc = metrics["clarity_class"]
    lines.append("Interpretation:")
    if cc == "broadcast":
        lines.append("  Nearly every stroke carries unique content. The writer")
        lines.append("  rarely repeats and output is consistently substantive.")
    elif cc == "communicator":
        lines.append("  Healthy signal with occasional repetition. This is the")
        lines.append("  normal mode for sustained automated writing.")
    elif cc == "repeater":
        lines.append("  Significant noise detected. Many strokes are near-duplicates")
        lines.append("  or template filler. Consider varying output structure.")
    else:
        lines.append("  Output is dominated by repetition. Most strokes could be")
        lines.append("  deleted without losing information. Intervention needed.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Standalone analysis (reads from strokes.jsonl)
# ---------------------------------------------------------------------------

def analyze_signal_clarity(
    strokes_path: str = "data/strokes.jsonl",
    window_size: int = 50,
) -> dict[str, Any]:
    """Analyze signal clarity from the strokes file.

    Parameters
    ----------
    strokes_path : str
        Path to strokes JSONL file.
    window_size : int
        Number of recent strokes to analyze.

    Returns
    -------
    dict
        Clarity metrics.
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

    return compute_clarity_metrics(strokes, window_size)


if __name__ == "__main__":
    metrics = analyze_signal_clarity()
    print(format_clarity_report(metrics))
