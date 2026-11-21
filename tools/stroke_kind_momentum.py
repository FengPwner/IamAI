#!/usr/bin/env python3
"""stroke_kind_momentum.py — measure per-kind growth trends across recent strokes.

The writer rotates through six stroke kinds (thought, devlog, garden, note,
metrics, snippet). In a healthy steady state each kind gets roughly equal
representation. After a restart or a stall, some kinds may fall behind and
then catch up in bursts. This tool makes those dynamics visible.

For each kind the tool computes:

    recent_share    fraction of the last `window` strokes with this kind
    older_share     fraction of the preceding `window` strokes
    momentum        recent_share - older_share  (positive = accelerating)
    trend           'accelerating' | 'stable' | 'decelerating'
    deficit         how far below 1/num_kinds the recent share is

Classification thresholds:

    |momentum| < stable_threshold        -> stable
    momentum  > stable_threshold         -> accelerating
    momentum  < -stable_threshold        -> decelerating

Usage:
    python3 tools/stroke_kind_momentum.py
    python3 tools/stroke_kind_momentum.py --window 200 --json
    python3 tools/stroke_kind_momentum.py --kind thought

Exit codes:
    0  all kinds stable or accelerating
    1  one or more kinds decelerating significantly
    2  error (no strokes, bad arguments)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_STROKES = REPO / "data" / "strokes.jsonl"

ALL_KINDS = ("thought", "devlog", "garden", "note", "metrics", "snippet")
DEFAULT_WINDOW = 100
STABLE_THRESHOLD = 0.05  # 5 percentage points


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def load_strokes(path: Path, count: int = 0) -> list[dict]:
    """Load strokes from a JSONL file. Returns all lines; caller slices."""
    if not path.exists():
        return []
    strokes: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                strokes.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if count > 0:
        strokes = strokes[-count:]
    return strokes


def kind_counts(strokes: list[dict]) -> Counter:
    """Count occurrences of each kind in a list of strokes."""
    return Counter(s.get("kind", "unknown") for s in strokes)


def compute_shares(counts: Counter, total: int) -> dict[str, float]:
    """Convert raw counts to fractional shares."""
    if total <= 0:
        return {k: 0.0 for k in ALL_KINDS}
    return {k: counts.get(k, 0) / total for k in ALL_KINDS}


def compute_momentum(
    recent_shares: dict[str, float],
    older_shares: dict[str, float],
) -> dict[str, float]:
    """Positive = accelerating, negative = decelerating."""
    return {k: recent_shares[k] - older_shares[k] for k in ALL_KINDS}


def classify(momentum: float, threshold: float = STABLE_THRESHOLD) -> str:
    """Classify a momentum value into a trend label."""
    if momentum > threshold:
        return "accelerating"
    elif momentum < -threshold:
        return "decelerating"
    return "stable"


def compute_deficit(recent_shares: dict[str, float], num_kinds: int = len(ALL_KINDS)) -> dict[str, float]:
    """How far below the ideal equal share each kind is."""
    ideal = 1.0 / num_kinds
    return {k: ideal - recent_shares[k] for k in ALL_KINDS}


def analyze(
    strokes: list[dict],
    window: int = DEFAULT_WINDOW,
    threshold: float = STABLE_THRESHOLD,
) -> dict:
    """Full analysis: split strokes, compute momentum per kind, classify.

    Returns a dict with:
        window, num_kinds, kinds (list of per-kind dicts),
        any_decelerating (bool), verdict ('healthy' | 'imbalanced')
    """
    need = window * 2
    if len(strokes) < need:
        # fall back to whatever we have, split in half
        half = len(strokes) // 2
        if half < 1:
            return {
                "window": 0,
                "num_kinds": len(ALL_KINDS),
                "kinds": [],
                "any_decelerating": False,
                "verdict": "insufficient_data",
            }
        older = strokes[:half]
        recent = strokes[half:]
        w = len(recent)
    else:
        older = strokes[-need:-window]
        recent = strokes[-window:]
        w = window

    older_counts = kind_counts(older)
    recent_counts = kind_counts(recent)

    older_shares = compute_shares(older_counts, len(older))
    recent_shares = compute_shares(recent_counts, len(recent))
    momenta = compute_momentum(recent_shares, older_shares)
    deficits = compute_deficit(recent_shares)

    kinds = []
    any_dec = False
    for k in ALL_KINDS:
        trend = classify(momenta[k], threshold)
        if trend == "decelerating":
            any_dec = True
        kinds.append({
            "kind": k,
            "recent_count": recent_counts.get(k, 0),
            "older_count": older_counts.get(k, 0),
            "recent_share": round(recent_shares[k], 4),
            "older_share": round(older_shares[k], 4),
            "momentum": round(momenta[k], 4),
            "trend": trend,
            "deficit": round(deficits[k], 4),
        })

    return {
        "window": w,
        "num_kinds": len(ALL_KINDS),
        "kinds": kinds,
        "any_decelerating": any_dec,
        "verdict": "imbalanced" if any_dec else "healthy",
    }


# ---------------------------------------------------------------------------
# Text report
# ---------------------------------------------------------------------------


def text_report(result: dict) -> str:
    """Human-readable summary."""
    lines = [
        f"stroke kind momentum (window={result['window']}, kinds={result['num_kinds']})",
        f"verdict: {result['verdict']}",
        "",
        f"{'kind':<10} {'recent':>7} {'older':>7} {'momentum':>10} {'trend':<14} {'deficit':>8}",
        "-" * 60,
    ]
    for k in result["kinds"]:
        lines.append(
            f"{k['kind']:<10} {k['recent_count']:>7} {k['older_count']:>7} "
            f"{k['momentum']:>+10.4f} {k['trend']:<14} {k['deficit']:>+8.4f}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strokes", type=Path, default=DEFAULT_STROKES, help="path to strokes.jsonl")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW, help="how many strokes per half (default 100)")
    ap.add_argument("--threshold", type=float, default=STABLE_THRESHOLD, help="momentum threshold for trend classification")
    ap.add_argument("--kind", type=str, default=None, help="show only this kind")
    ap.add_argument("--json", action="store_true", help="output JSON instead of text")
    args = ap.parse_args()

    if args.window < 1:
        print("error: --window must be >= 1", file=sys.stderr)
        return 2

    strokes = load_strokes(args.strokes)
    if not strokes:
        print("error: no strokes found", file=sys.stderr)
        return 2

    result = analyze(strokes, window=args.window, threshold=args.threshold)

    if args.kind:
        result["kinds"] = [k for k in result["kinds"] if k["kind"] == args.kind]
        if not result["kinds"]:
            print(f"error: kind '{args.kind}' not found", file=sys.stderr)
            return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(text_report(result))

    return 1 if result.get("any_decelerating") else 0


if __name__ == "__main__":
    raise SystemExit(main())
