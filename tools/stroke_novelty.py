#!/usr/bin/env python3
"""stroke_novelty.py — detect content repetition loops in the stroke log.

While stroke_rhythm_stability.py measures *timing* health, this tool
measures *content* health.  A writer can produce strokes at perfect 15 s
cadence but still be broken if it is replaying the same handful of texts
in a cycle.

Core metrics:
  - novelty_ratio:     fraction of texts in the window that are unique
                          1.0 = every text is new, 0.0 = all duplicates
  - unique_count:      number of distinct text hashes in the window
  - repeat_count:      number of texts seen more than once
  - cycle_length:      length of the shortest repeating text subsequence
                       (0 when no cycle is detected)
  - freshness_class:   FRESH   — novelty_ratio ≥ 0.8
                       WARM    — novelty_ratio 0.5–0.8
                       STALE   — novelty_ratio 0.2–0.5
                       LOOPING — novelty_ratio < 0.2 or cycle_length > 0

Usage:
    python3 tools/stroke_novelty.py
    python3 tools/stroke_novelty.py --window 200
    python3 tools/stroke_novelty.py --json

Exit codes:
    0 — analysis complete (any freshness class)
    2 — unexpected error
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STROKES_FILE = REPO / "data" / "strokes.jsonl"
DEFAULT_WINDOW = 100


def load_strokes(path: Path = STROKES_FILE) -> list[dict]:
    """Load stroke records from JSONL file."""
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                try:
                    records.append(json.loads(stripped))
                except json.JSONDecodeError:
                    continue
    return records


def strip_measurement(text: str) -> str:
    """Remove the trailing '-- measured now: ...' suffix the writer appends.

    The writer stamps each stroke with live metrics, making every full text
    technically unique even when the underlying thought is recycled.  Stripping
    the suffix lets novelty detection see through this camouflage.
    """
    marker = "-- measured now:"
    idx = text.find(marker)
    if idx >= 0:
        return text[:idx].rstrip()
    return text


def text_hash(text: str) -> str:
    """Produce a short hash of a text for efficient comparison.

    Strips measurement suffixes before hashing so recycled thoughts with
    different live stats are correctly identified as duplicates.
    """
    cleaned = strip_measurement(text)
    return hashlib.sha256(cleaned.encode("utf-8", errors="replace")).hexdigest()[:16]


def unique_count(texts: list[str]) -> int:
    """Count distinct texts in the list."""
    return len({text_hash(t) for t in texts})


def novelty_ratio(texts: list[str]) -> float:
    """Fraction of texts that are unique (first occurrence counts as unique)."""
    if not texts:
        return 1.0
    seen: set[str] = set()
    novel = 0
    for t in texts:
        h = text_hash(t)
        if h not in seen:
            novel += 1
            seen.add(h)
    return novel / len(texts)


def repeat_count(texts: list[str]) -> int:
    """Count how many texts appear more than once."""
    counts = Counter(text_hash(t) for t in texts)
    return sum(1 for c in counts.values() if c > 1)


def detect_cycle_length(texts: list[str], max_cycle: int = 50) -> int:
    """Find the shortest repeating subsequence length.

    Tests candidate lengths 1..max_cycle.  A cycle is confirmed when the
    last (2 × candidate) texts consist of the same subsequence repeated.
    Returns 0 when no cycle is found.
    """
    n = len(texts)
    if n < 4:
        return 0
    hashes = [text_hash(t) for t in texts]
    for clen in range(1, min(max_cycle, n // 2) + 1):
        tail = hashes[-(2 * clen):]
        first_half = tail[:clen]
        second_half = tail[clen:]
        if first_half == second_half:
            return clen
    return 0


def classify_freshness(novelty: float, cycle: int) -> str:
    """Map novelty_ratio and cycle_length to a freshness class.

    FRESH:   novelty ≥ 0.8 and no cycle
    WARM:    novelty 0.5–0.8 and no cycle
    STALE:   novelty 0.2–0.5
    LOOPING: novelty < 0.2 or cycle detected
    """
    if cycle > 0 or novelty < 0.2:
        return "LOOPING"
    if novelty < 0.5:
        return "STALE"
    if novelty < 0.8:
        return "WARM"
    return "FRESH"


def analyze(
    path: Path = STROKES_FILE,
    window: int = DEFAULT_WINDOW,
) -> dict:
    """Run full novelty analysis on the trailing window."""
    records = load_strokes(path)
    tail = records[-window:] if len(records) > window else records
    texts = [r.get("text", "") for r in tail]

    nr = novelty_ratio(texts)
    uc = unique_count(texts)
    rc = repeat_count(texts)
    cycle = detect_cycle_length(texts)
    freshness = classify_freshness(nr, cycle)

    # most repeated text (for diagnostics)
    counts = Counter(text_hash(t) for t in texts)
    top_hash, top_count = counts.most_common(1)[0] if counts else ("", 0)
    # recover one example text for the top hash
    top_example = ""
    for t in texts:
        if text_hash(t) == top_hash:
            top_example = t[:80]
            break

    return {
        "stroke_count": len(tail),
        "unique_count": uc,
        "repeat_count": rc,
        "novelty_ratio": round(nr, 4),
        "cycle_length": cycle,
        "freshness_class": freshness,
        "top_repeat_count": top_count,
        "top_repeat_example": top_example,
    }


def format_text(result: dict) -> str:
    """Produce a human-readable summary."""
    lines = [
        "=== Stroke Content Novelty ===",
        f"  strokes analyzed:   {result['stroke_count']}",
        f"  unique texts:       {result['unique_count']}",
        f"  repeated kinds:     {result['repeat_count']}",
        f"  novelty ratio:      {result['novelty_ratio']:.2%}",
        f"  cycle length:       {result['cycle_length']}"
        + (" (LOOPING)" if result["cycle_length"] > 0 else " (none)"),
        f"  freshness:          {result['freshness_class']}",
        f"  most repeated:      {result['top_repeat_count']}× — "
        f"\"{result['top_repeat_example']}\"",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    ap.add_argument("--strokes", type=Path, default=STROKES_FILE)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    try:
        result = analyze(path=args.strokes, window=args.window)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
