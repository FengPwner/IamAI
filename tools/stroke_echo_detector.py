#!/usr/bin/env python3
"""
stroke_echo_detector.py — Detect near-duplicate ("echo") strokes.

The writer sometimes enters a loop where it produces the same aphorism
repeatedly, varying only embedded numbers (line counts, commit counts,
stroke counts). This tool detects such echoes by:

1. Extracting a structural *skeleton* from each stroke's text:
   - Numbers and numeric expressions are replaced with a placeholder
   - Whitespace is normalised
   - The result is a template that captures the phrasing without the
     variable data

2. Computing a *uniqueness ratio* over a sliding window:
   - ratio = distinct_skeletons / window_size
   - A low ratio means most strokes share the same phrasing

3. Classifying each window:
   - healthy:   ratio >= 0.7  (most strokes are structurally distinct)
   - stale:     0.4 <= ratio < 0.7  (some repetition, tolerable)
   - echo:      ratio < 0.4  (severe repetition, needs intervention)

4. Reporting echo clusters: consecutive windows classified as "echo"

Usage:
    python3 tools/stroke_echo_detector.py
    python3 tools/stroke_echo_detector.py --window 20 --tail 10
    python3 tools/stroke_echo_detector.py --json

Exit codes:
    0 — analysis complete, no echo detected
    1 — echo chamber detected in recent windows
    2 — data file missing or unreadable
"""

import json
import re
import sys
import argparse
from pathlib import Path
from collections import Counter
from dataclasses import dataclass, asdict
from typing import List, Tuple, Optional

REPO = Path(__file__).resolve().parent.parent
STROKES_FILE = REPO / "data" / "strokes.jsonl"

DEFAULT_WINDOW = 20
DEFAULT_TAIL = 0  # 0 = analyse all windows

HEALTHY = "healthy"
STALE = "stale"
ECHO = "echo"

HEALTHY_THRESHOLD = 0.7
STALE_THRESHOLD = 0.4


@dataclass
class WindowResult:
    window_index: int
    start_seq: int
    end_seq: int
    size: int
    distinct_skeletons: int
    uniqueness_ratio: float
    classification: str
    dominant_skeleton: str
    dominant_count: int


def load_strokes(path: Path = STROKES_FILE) -> List[dict]:
    """Load strokes from JSONL. Returns list of dicts with at least seq, text."""
    strokes = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    stroke = json.loads(line)
                    if "text" in stroke:
                        strokes.append(stroke)
                except json.JSONDecodeError:
                    continue
    except (OSError, IOError):
        sys.exit(2)
    return strokes


def extract_skeleton(text: str) -> str:
    """Extract a structural skeleton from stroke text.

    Replaces numbers, commit counts, file counts, line counts, and
    stroke counts with a generic placeholder. Normalises whitespace.
    """
    if not text:
        return ""

    # Replace specific patterns first (order matters)
    s = text

    # "commit 1018:" / "commit 994:" etc.
    s = re.sub(r"\bcommit\s+\d+", "commit N", s)

    # "tree is 2494 files" / "2483 tracked files"
    s = re.sub(r"\b\d+\s+files\b", "N files", s)

    # "645885 lines" / "6844 strokes"
    s = re.sub(r"\b\d+\s+(?:lines|strokes|commits|files)\b", "N LINES", s)

    # "stroke 6845" / "stroke 308"
    s = re.sub(r"\bstroke\s+\d+", "stroke N", s)

    # Bare numbers (integers and decimals)
    s = re.sub(r"\b\d+(?:\.\d+)?\b", "N", s)

    # Normalise whitespace
    s = re.sub(r"\s+", " ", s).strip()

    return s.lower()


def compute_uniqueness(skeletons: List[str]) -> Tuple[int, float, str, int]:
    """Compute uniqueness metrics for a list of skeletons.

    Returns:
        (distinct_count, ratio, dominant_skeleton, dominant_count)
    """
    if not skeletons:
        return 0, 0.0, "", 0

    counter = Counter(skeletons)
    distinct = len(counter)
    ratio = distinct / len(skeletons)
    dominant_skeleton, dominant_count = counter.most_common(1)[0]

    return distinct, ratio, dominant_skeleton, dominant_count


def classify(ratio: float) -> str:
    """Classify a uniqueness ratio."""
    if ratio >= HEALTHY_THRESHOLD:
        return HEALTHY
    elif ratio >= STALE_THRESHOLD:
        return STALE
    else:
        return ECHO


def analyse_windows(
    strokes: List[dict],
    window_size: int = DEFAULT_WINDOW,
    tail: int = DEFAULT_TAIL,
) -> List[WindowResult]:
    """Analyse strokes in sliding windows.

    Args:
        strokes: list of stroke dicts
        window_size: number of strokes per window
        tail: if > 0, only return the last `tail` windows

    Returns:
        list of WindowResult
    """
    if not strokes or window_size < 1:
        return []

    results = []
    skeletons_with_meta = []
    for stroke in strokes:
        skeleton = extract_skeleton(stroke.get("text", ""))
        seq = stroke.get("seq", 0)
        skeletons_with_meta.append((seq, skeleton))

    # Sliding windows (non-overlapping for clarity)
    i = 0
    window_idx = 0
    while i + window_size <= len(skeletons_with_meta):
        window = skeletons_with_meta[i : i + window_size]
        skeleton_list = [s for _, s in window]
        distinct, ratio, dominant, dom_count = compute_uniqueness(skeleton_list)
        classification = classify(ratio)

        result = WindowResult(
            window_index=window_idx,
            start_seq=window[0][0],
            end_seq=window[-1][0],
            size=len(window),
            distinct_skeletons=distinct,
            uniqueness_ratio=round(ratio, 4),
            classification=classification,
            dominant_skeleton=dominant,
            dominant_count=dom_count,
        )
        results.append(result)
        i += window_size
        window_idx += 1

    if tail > 0:
        results = results[-tail:]

    return results


def detect_echo_chamber(results: List[WindowResult], recent: int = 3) -> bool:
    """Check if the most recent `recent` windows are all classified as echo."""
    if not results:
        return False
    recent_windows = results[-recent:]
    return all(w.classification == ECHO for w in recent_windows)


def format_human(results: List[WindowResult], echo_detected: bool) -> str:
    """Format results for human-readable output."""
    if not results:
        return "no windows to analyse"

    lines = [
        "stroke echo detector",
        "=" * 50,
        f"windows analysed: {len(results)}",
        f"window size: {results[0].size}",
        "",
    ]

    # Summary counts
    counts = Counter(w.classification for w in results)
    lines.append(
        f"classification: healthy={counts.get(HEALTHY, 0)}  "
        f"stale={counts.get(STALE, 0)}  echo={counts.get(ECHO, 0)}"
    )
    lines.append("")

    # Show last 5 windows
    lines.append("recent windows:")
    for w in results[-5:]:
        lines.append(
            f"  [{w.classification:>7}] seq {w.start_seq}-{w.end_seq}  "
            f"unique={w.distinct_skeletons}/{w.size}  "
            f"ratio={w.uniqueness_ratio:.2f}  "
            f"dominant×{w.dominant_count}"
        )
        # Truncate dominant skeleton for readability
        dom = w.dominant_skeleton[:60]
        if len(w.dominant_skeleton) > 60:
            dom += "…"
        lines.append(f"           \"{dom}\"")

    lines.append("")
    if echo_detected:
        lines.append("VERDICT: echo chamber detected in recent windows")
        lines.append("the writer is repeating the same structural patterns.")
        lines.append("consider: pause writer, review prompt, inject diversity.")
    else:
        lines.append("VERDICT: no echo chamber — writer output is diverse.")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Detect echo strokes in the writer log.")
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW,
                        help=f"strokes per window (default {DEFAULT_WINDOW})")
    parser.add_argument("--tail", type=int, default=DEFAULT_TAIL,
                        help="only show last N windows (0 = all)")
    parser.add_argument("--json", action="store_true",
                        help="output as JSON")
    args = parser.parse_args()

    strokes = load_strokes()
    if not strokes:
        print("no strokes found", file=sys.stderr)
        sys.exit(2)

    results = analyse_windows(strokes, window_size=args.window, tail=args.tail)
    echo_detected = detect_echo_chamber(results)

    if args.json:
        output = {
            "echo_detected": echo_detected,
            "windows": [asdict(w) for w in results],
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_human(results, echo_detected))

    sys.exit(1 if echo_detected else 0)


if __name__ == "__main__":
    main()
