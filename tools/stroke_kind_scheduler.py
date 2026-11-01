#!/usr/bin/env python3
"""stroke_kind_scheduler.py — weighted kind selector for balanced output.

The writer_loop.py defaults to "thought" kind for every stroke, causing
severe kind imbalance (>99% thought).  This module provides a weighted
random selector that favours underrepresented kinds, plus a CLI to
inspect the current recommendation.

Core logic:
    1. Count each kind's share in the trailing window
    2. Compute a weight inversely proportional to share:
         weight[k] = max(1, target_pct - actual_pct) ** power
    3. Select the next kind via weighted random sampling

Usage:
    python3 tools/stroke_kind_scheduler.py               # show weights + next pick
    python3 tools/stroke_kind_scheduler.py --json        # JSON output
    python3 tools/stroke_kind_scheduler.py --window 500  # last 500 strokes
    python3 tools/stroke_kind_scheduler.py --pick 5      # pick 5 kinds in a row

Exit code: 0 (always succeeds)
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STROKES_PATH = REPO / "data" / "strokes.jsonl"

ALL_KINDS = [
    "devlog",
    "garden",
    "snippet",
    "note",
    "metrics",
    "reading",
    "caretaker",
    "thought",
]

DEFAULT_WINDOW = 500
DEFAULT_TARGET_PCT = 12.5  # equal share for 8 kinds
DEFAULT_POWER = 2.0
DEFAULT_SEED = 20261003


def load_recent_kinds(path: Path, window: int) -> list[str]:
    """Read the last `window` kind values from strokes.jsonl."""
    if not path.exists():
        return []
    kinds: list[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                kinds.append(record.get("kind", "unknown"))
            except json.JSONDecodeError:
                continue
    return kinds[-window:]


def compute_weights(
    kinds: list[str],
    all_kinds: list[str] | None = None,
    target_pct: float = DEFAULT_TARGET_PCT,
    power: float = DEFAULT_POWER,
) -> dict[str, float]:
    """Compute selection weights inversely proportional to current share.

    For each kind:
      - undersaturated (actual < target): weight = (target_pct / max(actual_pct, 0.1)) ** power
      - oversaturated (actual >= target): weight = (target_pct / actual_pct) ** power
    This ensures a smooth gradient: more oversaturated kinds get lower weights,
    and more starved kinds get higher weights.  Weights are always positive.
    """
    if all_kinds is None:
        all_kinds = ALL_KINDS
    total = max(len(kinds), 1)
    counts = Counter(kinds)
    weights: dict[str, float] = {}
    for k in all_kinds:
        actual_pct = (counts.get(k, 0) / total) * 100.0
        effective_pct = max(actual_pct, 0.1)  # avoid division by zero
        ratio = target_pct / effective_pct
        weights[k] = ratio ** power
    return weights


def pick_kind(
    weights: dict[str, float],
    rng: random.Random | None = None,
) -> str:
    """Select one kind via weighted random sampling."""
    if rng is None:
        rng = random.Random()
    kinds = list(weights.keys())
    w = [weights[k] for k in kinds]
    total_w = sum(w)
    if total_w <= 0:
        return rng.choice(kinds)
    # Weighted selection without random.choices (for determinism with seed)
    r = rng.random() * total_w
    cumulative = 0.0
    for kind, weight in zip(kinds, w):
        cumulative += weight
        if r <= cumulative:
            return kind
    return kinds[-1]  # fallback (floating-point edge)


def recommend(
    path: Path = STROKES_PATH,
    window: int = DEFAULT_WINDOW,
    all_kinds: list[str] | None = None,
    target_pct: float = DEFAULT_TARGET_PCT,
    power: float = DEFAULT_POWER,
) -> dict:
    """Full recommendation: weights + next pick."""
    if all_kinds is None:
        all_kinds = ALL_KINDS
    kinds = load_recent_kinds(path, window)
    weights = compute_weights(kinds, all_kinds, target_pct, power)
    total = max(len(kinds), 1)
    counts = Counter(kinds)
    shares = {k: round(counts.get(k, 0) / total * 100, 2) for k in all_kinds}
    # Sort weights descending for readability
    sorted_weights = dict(sorted(weights.items(), key=lambda x: x[1], reverse=True))
    next_kind = pick_kind(weights, rng=random.Random(DEFAULT_SEED))
    return {
        "window": window,
        "total_strokes": len(kinds),
        "shares_pct": shares,
        "weights": {k: round(v, 4) for k, v in sorted_weights.items()},
        "next_kind": next_kind,
    }


def format_text(result: dict) -> str:
    """Human-readable output."""
    lines = [
        "=== Stroke Kind Scheduler ===",
        f"  window: {result['window']}  total strokes in window: {result['total_strokes']}",
        "",
        f"  {'kind':<12} {'share':>7} {'weight':>8}",
        f"  {'-'*12} {'-'*7} {'-'*8}",
    ]
    for kind, weight in result["weights"].items():
        share = result["shares_pct"].get(kind, 0.0)
        lines.append(f"  {kind:<12} {share:>6.2f}% {weight:>8.4f}")
    lines.append("")
    lines.append(f"  recommended next kind: {result['next_kind']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Weighted kind scheduler for balanced stroke output"
    )
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    parser.add_argument(
        "--target", type=float, default=DEFAULT_TARGET_PCT,
        help=f"target share per kind in percent (default {DEFAULT_TARGET_PCT})",
    )
    parser.add_argument(
        "--power", type=float, default=DEFAULT_POWER,
        help=f"weight exponent (default {DEFAULT_POWER})",
    )
    parser.add_argument(
        "--pick", type=int, default=1,
        help="number of kinds to pick in sequence (default 1)",
    )
    parser.add_argument(
        "--log", type=str, default=None,
        help="path to strokes.jsonl (default: data/strokes.jsonl)",
    )
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED,
        help="random seed for deterministic picks",
    )
    args = parser.parse_args()

    strokes_path = Path(args.log) if args.log else STROKES_PATH
    result = recommend(
        path=strokes_path,
        window=args.window,
        target_pct=args.target,
        power=args.power,
    )

    if args.pick > 1:
        rng = random.Random(args.seed)
        kinds = load_recent_kinds(strokes_path, args.window)
        weights = compute_weights(kinds, target_pct=args.target, power=args.power)
        picks = [pick_kind(weights, rng) for _ in range(args.pick)]
        result["picks"] = picks

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_text(result))
        if "picks" in result:
            print(f"\n  picks ({args.pick}): {', '.join(result['picks'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
