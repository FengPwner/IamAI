#!/usr/bin/env python3
"""writer_fingerprint.py — compute a behavioural fingerprint of the automated writer.

Every writer (human or machine) has a style: preferred sentence lengths,
vocabulary richness, punctuation habits, temporal patterns.  This tool
reduces the last N strokes to a compact *fingerprint* — seven bucketed
dimensions hashed into a short ID — so that caretakers can detect when
the writer's behaviour shifts after a restart, model swap, or prompt change.

Usage:
    python3 tools/writer_fingerprint.py                  # default: last 200 strokes
    python3 tools/writer_fingerprint.py --tail 50
    python3 tools/writer_fingerprint.py --json
    python3 tools/writer_fingerprint.py --compare <old-fp>  # diff against previous

Exit codes:
    0 — fingerprint computed, no significant drift
    1 — drift detected (when --compare is used)
    2 — insufficient data (< 10 strokes)

Dimensions:
    L  length      — mean character count per stroke
    V  vocabulary  — type-token ratio (unique words / total words)
    N  numericity  — fraction of characters that are digits
    P  punctuation — fraction of characters that are punctuation
    T  template    — fraction matching known boilerplate patterns
    C  cadence     — mean inter-stroke interval (seconds)
    R  regularity  — coefficient of variation of intervals

Each dimension is bucketed into one of three bands: low / mid / high.
The fingerprint is the concatenation: e.g. ``Lm-Vh-Nl-Pm-Tl-Cm-Rl``.
A 4-char hash suffix lets caretakers compare at a glance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import string
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STROKES_PATH = Path("data/strokes.jsonl")

# Bucket thresholds — each dimension maps a continuous value to L/M/H.
# Format: (low_max, high_min)  — below low_max → "l", above high_min → "h", else "m"
THRESHOLDS: Dict[str, Tuple[float, float]] = {
    "length":      (80.0, 200.0),
    "vocabulary":  (0.30, 0.55),
    "numericity":  (0.02, 0.08),
    "punctuation": (0.05, 0.12),
    "template":    (0.20, 0.60),
    "cadence":     (12.0, 30.0),
    "regularity":  (0.15, 0.50),
}

DIM_KEYS = ["length", "vocabulary", "numericity", "punctuation",
            "template", "cadence", "regularity"]

# Known boilerplate patterns (lowercase prefixes).
TEMPLATE_PREFIXES = [
    "tree is",
    "commit",
    "round",
    "measured now",
    "growth that never stops",
    "an append-only log",
    "if a number in a diary",
    "ten minutes is",
    "a deterministic garden",
    "automation fails quietly",
    "most architecture is",
    "deleting a file",
    "the useful abstraction",
]

MIN_STROKES = 10


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_strokes(path: Path = STROKES_PATH, tail: int = 200) -> List[dict]:
    """Load the last *tail* strokes from a JSONL file."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    selected = lines[-tail:]
    result = []
    for line in selected:
        line = line.strip()
        if not line:
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return result


# ---------------------------------------------------------------------------
# Per-dimension metrics
# ---------------------------------------------------------------------------

def mean_length(strokes: List[dict]) -> float:
    """Mean character count of stroke text."""
    texts = [s.get("text", "") for s in strokes]
    if not texts:
        return 0.0
    return sum(len(t) for t in texts) / len(texts)


def type_token_ratio(strokes: List[dict]) -> float:
    """Type-token ratio (unique words / total words) across all texts."""
    all_words: List[str] = []
    for s in strokes:
        words = re.findall(r"[a-z']+", s.get("text", "").lower())
        all_words.extend(words)
    if not all_words:
        return 0.0
    return len(set(all_words)) / len(all_words)


def numericity(strokes: List[dict]) -> float:
    """Fraction of characters that are digits."""
    all_chars = "".join(s.get("text", "") for s in strokes)
    if not all_chars:
        return 0.0
    return sum(1 for c in all_chars if c.isdigit()) / len(all_chars)


def punctuation_ratio(strokes: List[dict]) -> float:
    """Fraction of characters that are punctuation."""
    all_chars = "".join(s.get("text", "") for s in strokes)
    if not all_chars:
        return 0.0
    punct = set(string.punctuation)
    return sum(1 for c in all_chars if c in punct) / len(all_chars)


def template_fraction(strokes: List[dict]) -> float:
    """Fraction of strokes whose text starts with a known boilerplate prefix."""
    if not strokes:
        return 0.0
    count = 0
    for s in strokes:
        text_lower = s.get("text", "").lower().strip()
        for prefix in TEMPLATE_PREFIXES:
            if text_lower.startswith(prefix):
                count += 1
                break
    return count / len(strokes)


def _parse_iso(ts: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp, returning None on failure."""
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S+00:00",
                "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # Last resort: try fromisoformat (Python 3.7+)
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def inter_stroke_intervals(strokes: List[dict]) -> List[float]:
    """Compute positive intervals (seconds) between consecutive strokes."""
    times = []
    for s in strokes:
        ts = s.get("at", "")
        dt = _parse_iso(ts)
        if dt is not None:
            times.append(dt)
    intervals = []
    for i in range(1, len(times)):
        delta = (times[i] - times[i - 1]).total_seconds()
        if delta > 0:
            intervals.append(delta)
    return intervals


def mean_cadence(intervals: List[float]) -> float:
    """Mean interval in seconds."""
    if not intervals:
        return 0.0
    return sum(intervals) / len(intervals)


def regularity_cv(intervals: List[float]) -> float:
    """Coefficient of variation of intervals (stddev / mean)."""
    if len(intervals) < 2:
        return 0.0
    mu = sum(intervals) / len(intervals)
    if mu == 0:
        return 0.0
    variance = sum((x - mu) ** 2 for x in intervals) / len(intervals)
    return math.sqrt(variance) / mu


# ---------------------------------------------------------------------------
# Bucketing
# ---------------------------------------------------------------------------

def bucket(value: float, dimension: str) -> str:
    """Map a continuous value to 'l' / 'm' / 'h' for the given dimension."""
    lo, hi = THRESHOLDS.get(dimension, (0.0, 1.0))
    if value < lo:
        return "l"
    elif value >= hi:
        return "h"
    return "m"


def bucket_label(b: str) -> str:
    return {"l": "low", "m": "mid", "h": "high"}[b]


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------

@dataclass
class Fingerprint:
    length: float
    vocabulary: float
    numericity: float
    punctuation: float
    template: float
    cadence: float
    regularity: float

    length_b: str = ""
    vocabulary_b: str = ""
    numericity_b: str = ""
    punctuation_b: str = ""
    template_b: str = ""
    cadence_b: str = ""
    regularity_b: str = ""

    tag: str = ""
    stroke_count: int = 0
    computed_at: str = ""

    def fill_buckets(self) -> None:
        self.length_b = bucket(self.length, "length")
        self.vocabulary_b = bucket(self.vocabulary, "vocabulary")
        self.numericity_b = bucket(self.numericity, "numericity")
        self.punctuation_b = bucket(self.punctuation, "punctuation")
        self.template_b = bucket(self.template, "template")
        self.cadence_b = bucket(self.cadence, "cadence")
        self.regularity_b = bucket(self.regularity, "regularity")

    def compute_tag(self) -> None:
        raw = f"{self.length_b}{self.vocabulary_b}{self.numericity_b}" \
              f"{self.punctuation_b}{self.template_b}{self.cadence_b}" \
              f"{self.regularity_b}"
        h = hashlib.sha256(raw.encode()).hexdigest()[:4]
        self.tag = f"{raw}-{h}"

    def label(self) -> str:
        parts = [
            f"L{self.length_b}",
            f"V{self.vocabulary_b}",
            f"N{self.numericity_b}",
            f"P{self.punctuation_b}",
            f"T{self.template_b}",
            f"C{self.cadence_b}",
            f"R{self.regularity_b}",
        ]
        return "-".join(parts)


def compute_fingerprint(strokes: List[dict]) -> Fingerprint:
    intervals = inter_stroke_intervals(strokes)
    fp = Fingerprint(
        length=round(mean_length(strokes), 2),
        vocabulary=round(type_token_ratio(strokes), 4),
        numericity=round(numericity(strokes), 4),
        punctuation=round(punctuation_ratio(strokes), 4),
        template=round(template_fraction(strokes), 4),
        cadence=round(mean_cadence(intervals), 2),
        regularity=round(regularity_cv(intervals), 4),
        stroke_count=len(strokes),
        computed_at=datetime.now(timezone.utc).isoformat(),
    )
    fp.fill_buckets()
    fp.compute_tag()
    return fp


# ---------------------------------------------------------------------------
# Comparison / drift
# ---------------------------------------------------------------------------

def compare_fingerprints(old_tag: str, new_fp: Fingerprint) -> Dict[str, Any]:
    """Compare a previous tag string against the new fingerprint.

    Returns a dict with ``drift`` (bool) and ``changes`` (list of dimension diffs).
    """
    # old_tag looks like "Lm-Vh-Nl-Pm-Tl-Cm-Rl-ab12"
    changes: List[str] = []
    old_label = old_tag.rsplit("-", 1)[0] if "-" in old_tag else ""
    new_label = new_fp.label()
    old_parts = old_label.split("-")
    new_parts = new_label.split("-")
    for o, n in zip(old_parts, new_parts):
        if o != n:
            changes.append(f"{o} → {n}")
    return {
        "drift": len(changes) > 0,
        "changes": changes,
        "old": old_tag,
        "new": f"{new_label}-{new_fp.tag.split('-')[-1]}",
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def text_report(fp: Fingerprint) -> str:
    lines = [
        f"=== Writer Fingerprint ({fp.stroke_count} strokes) ===",
        f"  Tag:    {fp.label()}-{fp.tag.split('-')[-1]}",
        f"  Hash:   {fp.tag.split('-')[-1]}",
        "",
        "  Dimensions:",
        f"    length      {fp.length:>8.1f}  [{bucket_label(fp.length_b):>4}]  (chars/stroke)",
        f"    vocabulary  {fp.vocabulary:>8.4f}  [{bucket_label(fp.vocabulary_b):>4}]  (type-token ratio)",
        f"    numericity  {fp.numericity:>8.4f}  [{bucket_label(fp.numericity_b):>4}]  (digit fraction)",
        f"    punctuation {fp.punctuation:>8.4f}  [{bucket_label(fp.punctuation_b):>4}]  (punct fraction)",
        f"    template    {fp.template:>8.4f}  [{bucket_label(fp.template_b):>4}]  (boilerplate fraction)",
        f"    cadence     {fp.cadence:>8.1f}  [{bucket_label(fp.cadence_b):>4}]  (mean interval, s)",
        f"    regularity  {fp.regularity:>8.4f}  [{bucket_label(fp.regularity_b):>4}]  (CV of intervals)",
        "",
        f"  Computed: {fp.computed_at}",
    ]
    return "\n".join(lines)


def json_report(fp: Fingerprint) -> str:
    return json.dumps(asdict(fp), indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Writer behavioural fingerprint")
    p.add_argument("--tail", type=int, default=200, help="number of recent strokes")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--compare", type=str, default="", help="previous tag to diff against")
    p.add_argument("--strokes", type=str, default=str(STROKES_PATH), help="path to strokes JSONL")
    args = p.parse_args(argv)

    strokes = load_strokes(Path(args.strokes), tail=args.tail)
    if len(strokes) < MIN_STROKES:
        print(f"error: need >= {MIN_STROKES} strokes, got {len(strokes)}", file=sys.stderr)
        return 2

    fp = compute_fingerprint(strokes)

    if args.compare:
        diff = compare_fingerprints(args.compare, fp)
        if args.json:
            print(json.dumps(diff, indent=2))
        else:
            print(text_report(fp))
            print()
            if diff["drift"]:
                print(f"  ⚠  DRIFT detected: {', '.join(diff['changes'])}")
            else:
                print("  ✓  No drift — fingerprint unchanged")
        return 1 if diff["drift"] else 0

    if args.json:
        print(json_report(fp))
    else:
        print(text_report(fp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
