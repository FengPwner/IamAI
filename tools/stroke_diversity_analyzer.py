#!/usr/bin/env python3
"""stroke_diversity_analyzer.py — measure how evenly stroke kinds are distributed.

The writer produces six kinds of strokes: thought, garden, metrics,
snippet, devlog, note.  A healthy writer cycles through all six; a
stuck writer hammers one kind and ignores the rest.

This tool reads data/strokes.jsonl, counts strokes by kind, and
computes:

  - kind_counts: {kind: count}
  - kind_pcts: {kind: percentage of total}
  - entropy: Shannon entropy of the distribution (bits)
  - max_entropy: theoretical maximum (log2 of number of kinds)
  - diversity_ratio: entropy / max_entropy (1.0 = perfectly even)
  - dominant_kind: the kind with the highest count
  - dominant_pct: percentage of strokes that are the dominant kind
  - verdict: "balanced" | "skewed" | "monoculture"

Thresholds:
  - balanced:      diversity_ratio >= 0.85
  - skewed:        0.60 <= diversity_ratio < 0.85
  - monoculture:   diversity_ratio < 0.60

Usage:
    python3 tools/stroke_diversity_analyzer.py
    python3 tools/stroke_diversity_analyzer.py --writer qwen
    python3 tools/stroke_diversity_analyzer.py --json

Exit codes:
    0 — balanced or skewed (informational)
    1 — monoculture (writer is stuck in one mode)
    2 — data file not found
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional


@dataclass
class DiversityReport:
    """Summary of stroke-kind distribution."""
    kind_counts: Dict[str, int]
    kind_pcts: Dict[str, float]
    entropy: float
    max_entropy: float
    diversity_ratio: float
    dominant_kind: str
    dominant_pct: float
    verdict: str

    def to_dict(self) -> dict:
        return asdict(self)


def compute_entropy(counts: Dict[str, int]) -> float:
    """Shannon entropy in bits."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in counts.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


def analyze_diversity(strokes_path: Path) -> DiversityReport:
    """Read strokes.jsonl and compute diversity metrics."""
    if not strokes_path.exists():
        raise FileNotFoundError(f"strokes file not found: {strokes_path}")

    kind_counts: Dict[str, int] = {}
    with open(strokes_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                stroke = json.loads(line)
                kind = stroke.get("kind", "unknown")
                kind_counts[kind] = kind_counts.get(kind, 0) + 1
            except json.JSONDecodeError:
                continue

    total = sum(kind_counts.values())
    if total == 0:
        return DiversityReport(
            kind_counts={},
            kind_pcts={},
            entropy=0.0,
            max_entropy=0.0,
            diversity_ratio=0.0,
            dominant_kind="none",
            dominant_pct=0.0,
            verdict="monoculture",
        )

    # Percentages
    kind_pcts = {k: round((v / total) * 100, 2) for k, v in kind_counts.items()}

    # Entropy
    entropy = compute_entropy(kind_counts)
    num_kinds = len(kind_counts)
    max_entropy = math.log2(num_kinds) if num_kinds > 1 else 1.0
    diversity_ratio = entropy / max_entropy if max_entropy > 0 else 0.0

    # Dominant kind
    dominant_kind = max(kind_counts, key=kind_counts.get)
    dominant_pct = kind_pcts[dominant_kind]

    # Verdict
    if diversity_ratio >= 0.85:
        verdict = "balanced"
    elif diversity_ratio >= 0.60:
        verdict = "skewed"
    else:
        verdict = "monoculture"

    return DiversityReport(
        kind_counts=kind_counts,
        kind_pcts=kind_pcts,
        entropy=round(entropy, 4),
        max_entropy=round(max_entropy, 4),
        diversity_ratio=round(diversity_ratio, 4),
        dominant_kind=dominant_kind,
        dominant_pct=dominant_pct,
        verdict=verdict,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Analyze stroke-kind diversity in strokes.jsonl"
    )
    parser.add_argument(
        "--writer",
        default="qwen",
        help="Writer name (default: qwen)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    # Locate strokes file
    repo_root = Path(__file__).resolve().parent.parent
    strokes_path = repo_root / "data" / "strokes.jsonl"

    try:
        report = analyze_diversity(strokes_path)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"=== Stroke Diversity Report ===")
        print(f"Total strokes: {sum(report.kind_counts.values())}")
        print()
        print("Kind distribution:")
        for kind in sorted(report.kind_counts.keys()):
            count = report.kind_counts[kind]
            pct = report.kind_pcts[kind]
            bar = "█" * int(pct / 2)
            print(f"  {kind:12s} {count:5d}  {pct:5.1f}%  {bar}")
        print()
        print(f"Entropy:         {report.entropy:.4f} bits")
        print(f"Max entropy:     {report.max_entropy:.4f} bits")
        print(f"Diversity ratio: {report.diversity_ratio:.4f}")
        print(f"Dominant kind:   {report.dominant_kind} ({report.dominant_pct:.1f}%)")
        print(f"Verdict:         {report.verdict}")

    # Exit code
    if report.verdict == "monoculture":
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
