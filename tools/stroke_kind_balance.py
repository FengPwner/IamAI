#!/usr/bin/env python3
"""stroke_kind_balance.py — measure how evenly stroke kinds are distributed.

Most strokes end up as ``thought`` because that is the default kind.
When the distribution collapses toward a single kind, the log reads
like a monologue; when it spreads across kinds, it reads like a
well-tended garden with distinct sections.

This tool quantifies the balance using three complementary metrics:

====================  ====================================================
metric                 what it captures
====================  ====================================================
shannon_entropy        information-theoretic diversity (0 = one kind, log(K) = uniform)
normalized_entropy     entropy / log(K), scaled 0-1 for easy comparison
dominance_ratio        fraction of strokes belonging to the most common kind
====================  ====================================================

Verdicts:

===========  ============================================================
label         meaning
===========  ============================================================
balanced      multiple kinds each contribute meaningfully
skewed        one or two kinds dominate but others are present
monoculture   nearly all strokes share the same kind (>90%)
===========  ============================================================

Design goals:

1. **Pure Python** — no external dependencies.
2. **Windowed** — only looks at the most recent N strokes (default 100).
3. **Forgiving** — malformed JSONL lines are skipped, not raised.
4. **Deterministic** — same input always gives same output.

Usage::

    python3 tools/stroke_kind_balance.py
    python3 tools/stroke_kind_balance.py --window 200
    python3 tools/stroke_kind_balance.py --json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STROKES_FILE = REPO / "data" / "strokes.jsonl"

# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def load_recent_strokes(path: Path = STROKES_FILE, window: int = 100) -> list[dict]:
    """Load the last *window* strokes from the JSONL file.

    Malformed lines are silently skipped.  Returns oldest-first order.
    """
    if window <= 0:
        return []
    strokes: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    strokes.append(json.loads(line))
                except (json.JSONDecodeError, ValueError):
                    continue
    except FileNotFoundError:
        return []
    return strokes[-window:]


def kind_counts(strokes: list[dict]) -> Counter:
    """Return a Counter of kind values."""
    return Counter(s.get("kind", "unknown") for s in strokes)


def shannon_entropy(counts: Counter) -> float:
    """Compute Shannon entropy (in nats) from a Counter."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    ent = 0.0
    for c in counts.values():
        if c > 0:
            p = c / total
            ent -= p * math.log(p)
    return ent


def normalized_entropy(counts: Counter) -> float:
    """Shannon entropy scaled to [0, 1].  1 = perfectly uniform."""
    k = len(counts)
    if k <= 1:
        return 0.0
    max_ent = math.log(k)
    if max_ent == 0:
        return 0.0
    return shannon_entropy(counts) / max_ent


def dominance_ratio(counts: Counter) -> float:
    """Fraction of strokes belonging to the most common kind."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return max(counts.values()) / total


def classify(dominance: float, norm_ent: float) -> str:
    """Assign a balance verdict based on dominance and normalized entropy."""
    if dominance >= 0.90:
        return "monoculture"
    if dominance >= 0.70 or norm_ent < 0.30:
        return "skewed"
    return "balanced"


def health_score(norm_ent: float, dominance: float) -> int:
    """Composite health score 0-100.

    Higher is better (more balanced distribution).
    """
    # Entropy contributes positively (0-60 range)
    ent_score = norm_ent * 60
    # Low dominance contributes positively (0-40 range)
    dom_score = (1 - dominance) * 40
    raw = ent_score + dom_score
    return max(0, min(100, round(raw)))


def analyze(path: Path = STROKES_FILE, window: int = 100) -> dict:
    """Run the full analysis and return a results dict."""
    strokes = load_recent_strokes(path, window)
    if not strokes:
        return {
            "window": window,
            "actual_count": 0,
            "kinds": {},
            "entropy": 0.0,
            "normalized_entropy": 0.0,
            "dominance_ratio": 0.0,
            "verdict": "empty",
            "health_score": 0,
        }

    counts = kind_counts(strokes)
    ent = shannon_entropy(counts)
    norm_ent = normalized_entropy(counts)
    dom = dominance_ratio(counts)

    return {
        "window": window,
        "actual_count": len(strokes),
        "kinds": dict(counts.most_common()),
        "num_kinds": len(counts),
        "entropy": round(ent, 4),
        "normalized_entropy": round(norm_ent, 4),
        "dominance_ratio": round(dom, 4),
        "verdict": classify(dom, norm_ent),
        "health_score": health_score(norm_ent, dom),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure stroke kind distribution balance."
    )
    parser.add_argument(
        "--window", type=int, default=100, help="Number of recent strokes to analyze"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON"
    )
    args = parser.parse_args()

    results = analyze(path=STROKES_FILE, window=args.window)

    if args.json:
        json.dump(results, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    print(f"stroke kind balance (window={results['window']})")
    print(f"  strokes analyzed: {results['actual_count']}")
    print(f"  distinct kinds:   {results.get('num_kinds', 0)}")
    print()

    if results["kinds"]:
        print("  distribution:")
        for kind, count in sorted(results["kinds"].items(), key=lambda x: -x[1]):
            pct = count / results["actual_count"] * 100
            bar = "█" * int(pct / 2)
            print(f"    {kind:12s}  {count:5d}  ({pct:5.1f}%)  {bar}")
        print()

    print(f"  entropy:              {results['entropy']:.4f}")
    print(f"  normalized entropy:   {results['normalized_entropy']:.4f}")
    print(f"  dominance ratio:      {results['dominance_ratio']:.4f}")
    print(f"  verdict:              {results['verdict']}")
    print(f"  health score:         {results['health_score']}/100")


if __name__ == "__main__":
    main()
