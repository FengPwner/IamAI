#!/usr/bin/env python3
"""Detect stale (duplicate or near-duplicate) strokes in the writer's output.

The writer sometimes falls into a loop, producing the same text with only
trivial variations (different counters, timestamps, or "At this moment:"
suffixes). This module detects those patterns so the caretaker can decide
whether to restart the writer or adjust its prompts.

Two detection methods:

1. **Exact duplicate**: identical ``text`` field within a sliding window.
2. **Prefix duplicate**: the first N characters match, ignoring the
   "At this moment:" / "measured now:" suffix that changes each cycle.

Usage as a CLI::

    python tools/stale_stroke_detector.py [--window 100] [--min-prefix 40]
    python tools/stale_stroke_detector.py --json   # machine-readable output

Exit codes:
    0 — no stale strokes found
    1 — stale strokes detected
    2 — file / parse error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DEFAULT_STROKES = REPO / "data" / "strokes.jsonl"

# Patterns the writer appends to vary its output; everything after the
# first match is stripped before prefix comparison.
_SUFFIX_RE = re.compile(
    r"\s*(?:At this moment:|measured now:|--)\s*.*$", re.DOTALL
)


@dataclass
class StaleGroup:
    """A cluster of strokes that look the same."""

    prefix: str
    indices: list[int] = field(default_factory=list)
    seqs: list[int] = field(default_factory=list)
    kind: str = ""  # "exact" or "prefix"

    @property
    def count(self) -> int:
        return len(self.indices)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def strip_suffix(text: str) -> str:
    """Remove the variable trailing clause so near-dupes can be compared."""
    return _SUFFIX_RE.sub("", text).strip()


def fingerprint(text: str, min_prefix: int = 40) -> str:
    """Return the stable prefix used for near-duplicate detection.

    If the stripped text is shorter than *min_prefix*, the full stripped
    text is returned (and will only match exact duplicates after stripping).
    """
    stripped = strip_suffix(text)
    if len(stripped) < min_prefix:
        return stripped
    return stripped[: len(stripped)]


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def load_strokes(path: Path) -> list[dict[str, Any]]:
    """Load strokes from a JSONL file, skipping malformed lines."""
    strokes: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                strokes.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return strokes


def detect_stale(
    strokes: list[dict[str, Any]],
    *,
    window: int = 100,
    min_prefix: int = 40,
) -> list[StaleGroup]:
    """Find duplicate and near-duplicate stroke groups within *window*.

    Parameters
    ----------
    strokes:
        Ordered list of stroke dicts (oldest first).
    window:
        How many recent strokes to scan.
    min_prefix:
        Minimum prefix length for a near-duplicate match.

    Returns
    -------
    list[StaleGroup]:
        Groups with count >= 2, sorted by count descending.
    """
    recent = strokes[-window:] if len(strokes) > window else strokes[:]

    # --- exact duplicates ---
    exact_map: dict[str, StaleGroup] = {}
    for i, s in enumerate(recent):
        text = s.get("text", "")
        if not text:
            continue
        if text in exact_map:
            exact_map[text].indices.append(i)
            exact_map[text].seqs.append(s.get("seq", -1))
        else:
            exact_map[text] = StaleGroup(
                prefix=text,
                indices=[i],
                seqs=[s.get("seq", -1)],
                kind="exact",
            )

    # --- prefix (near) duplicates ---
    prefix_map: dict[str, StaleGroup] = {}
    for i, s in enumerate(recent):
        text = s.get("text", "")
        fp = fingerprint(text, min_prefix)
        if len(fp) < min_prefix:
            continue  # too short to be a meaningful prefix match
        if fp in prefix_map:
            prefix_map[fp].indices.append(i)
            prefix_map[fp].seqs.append(s.get("seq", -1))
        else:
            prefix_map[fp] = StaleGroup(
                prefix=fp,
                indices=[i],
                seqs=[s.get("seq", -1)],
                kind="prefix",
            )

    # Merge: collect groups with >= 2 members, prefer exact over prefix
    groups: list[StaleGroup] = []
    seen_seqs: set[int] = set()

    for g in sorted(exact_map.values(), key=lambda g: g.count, reverse=True):
        if g.count < 2:
            continue
        key = tuple(g.seqs)
        if key in seen_seqs:
            continue
        seen_seqs.add(key)
        groups.append(g)

    for g in sorted(prefix_map.values(), key=lambda g: g.count, reverse=True):
        if g.count < 2:
            continue
        # Skip if all seqs are already covered by an exact group
        overlap = sum(1 for s in g.seqs if s in seen_seqs)
        if overlap == len(g.seqs):
            continue
        groups.append(g)

    groups.sort(key=lambda g: g.count, reverse=True)
    return groups


def format_text(groups: list[StaleGroup], total_scanned: int) -> str:
    """Human-readable summary."""
    if not groups:
        return f"stale_stroke_detector: clean ({total_scanned} strokes scanned)"
    lines = [f"stale_stroke_detector: {len(groups)} stale group(s) in last {total_scanned} strokes"]
    for i, g in enumerate(groups[:10], 1):
        preview = g.prefix[:80] + ("..." if len(g.prefix) > 80 else "")
        lines.append(f"  [{i}] {g.kind} x{g.count}: {preview!r}")
        lines.append(f"      seqs: {g.seqs}")
    return "\n".join(lines)


def format_json(groups: list[StaleGroup], total_scanned: int) -> str:
    """Machine-readable JSON output."""
    payload = {
        "total_scanned": total_scanned,
        "stale_groups": len(groups),
        "groups": [
            {
                "kind": g.kind,
                "count": g.count,
                "prefix": g.prefix[:200],
                "seqs": g.seqs,
            }
            for g in groups[:20]
        ],
    }
    return json.dumps(payload, indent=2)


def exit_code(groups: list[StaleGroup]) -> int:
    """0 = clean, 1 = stale strokes found."""
    return 1 if groups else 0


def run(
    strokes_path: Path = DEFAULT_STROKES,
    *,
    window: int = 100,
    min_prefix: int = 40,
    as_json: bool = False,
) -> tuple[int, str]:
    """Main entry point. Returns (exit_code, output_text)."""
    if not strokes_path.exists():
        return 2, f"error: strokes file not found: {strokes_path}"
    try:
        strokes = load_strokes(strokes_path)
    except OSError as exc:
        return 2, f"error reading strokes: {exc}"

    groups = detect_stale(strokes, window=window, min_prefix=min_prefix)
    total = min(len(strokes), window)
    if as_json:
        return exit_code(groups), format_json(groups, total)
    return exit_code(groups), format_text(groups, total)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect stale/duplicate strokes")
    parser.add_argument("--strokes", type=Path, default=DEFAULT_STROKES)
    parser.add_argument("--window", type=int, default=100)
    parser.add_argument("--min-prefix", type=int, default=40)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    code, output = run(
        args.strokes,
        window=args.window,
        min_prefix=args.min_prefix,
        as_json=args.as_json,
    )
    print(output)
    sys.exit(code)


if __name__ == "__main__":
    main()
