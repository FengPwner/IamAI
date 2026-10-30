#!/usr/bin/env python3
"""stroke_dedup_gate.py — prevent the writer from emitting duplicate strokes.

The writer has a small pool of ~15 OPINIONS and 6 NOTE_TOPICS. At 15-second
cadence it exhausts the pool in minutes, then cycles. stroke_loop_detector.py
and stroke_novelty.py *measure* the problem after the fact; this module
*prevents* it at write time.

How it works:

    1. Load the last N strokes from strokes.jsonl.
    2. Hash each text (after stripping the metric suffix).
    3. When a candidate stroke's hash matches one in the window, reject it.

The gate is a pure function: ``should_accept(candidate, recent_strokes, window)``
returns True/False. The writer_loop can call it before appending.

Design choices:

    - Hashing ignores the trailing '-- measured now: ...' suffix because the
      metrics change every stroke even when the body is identical.
    - The window defaults to 100 strokes (~25 minutes at 15 s cadence). A
      duplicate within that window means the writer is cycling.
    - Returns a dict with ``accept`` (bool), ``reason`` (str), and
      ``duplicate_of_seq`` (int or None) for structured logging.

Usage:
    python3 tools/stroke_dedup_gate.py --candidate-text "tests are the part..."
    python3 tools/stroke_dedup_gate.py --check-last 50
    python3 tools/stroke_dedup_gate.py --json --check-last 100
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STROKES_PATH = REPO / "data" / "strokes.jsonl"
DEFAULT_WINDOW = 100

METRIC_SUFFIX_RE = re.compile(r"\s*--\s*measured now:\s*.*$")


def strip_metric_suffix(text: str) -> str:
    """Remove the trailing '-- measured now: ...' annotation."""
    return METRIC_SUFFIX_RE.sub("", text).strip()


def text_hash(text: str) -> str:
    """Stable hash of a stroke body, ignoring metric suffix."""
    return hashlib.sha256(strip_metric_suffix(text).encode("utf-8")).hexdigest()[:16]


def load_recent_strokes(path: Path, window: int) -> list[dict]:
    """Load the last `window` strokes from the JSONL file."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    tail = lines[-window:] if len(lines) >= window else lines
    strokes = []
    for line in tail:
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return strokes


def build_recent_hashes(strokes: list[dict]) -> dict[str, int]:
    """Map text_hash -> seq for the most recent occurrence of each hash."""
    hashes: dict[str, int] = {}
    for s in strokes:
        h = text_hash(s.get("text", ""))
        hashes[h] = s.get("seq", 0)
    return hashes


def should_accept(
    candidate_text: str,
    recent_strokes: list[dict],
    window: int = DEFAULT_WINDOW,
) -> dict:
    """Decide whether a candidate stroke should be accepted.

    Returns:
        {
            "accept": bool,
            "reason": str,
            "duplicate_of_seq": int | None,
        }
    """
    candidate_hash = text_hash(candidate_text)
    recent_hashes = build_recent_hashes(recent_strokes[-window:])

    if candidate_hash in recent_hashes:
        dup_seq = recent_hashes[candidate_hash]
        return {
            "accept": False,
            "reason": f"duplicate of stroke #{dup_seq} (within last {window})",
            "duplicate_of_seq": dup_seq,
        }

    return {
        "accept": True,
        "reason": "unique within window",
        "duplicate_of_seq": None,
    }


def check_last_n(strokes: list[dict], n: int) -> dict:
    """Analyse the last N strokes for duplicates within that window.

    Returns summary statistics useful for tuning the gate.
    """
    window = strokes[-n:] if len(strokes) >= n else strokes
    hashes: dict[str, list[int]] = {}
    for s in window:
        h = text_hash(s.get("text", ""))
        hashes.setdefault(h, []).append(s.get("seq", 0))

    duplicates = {h: seqs for h, seqs in hashes.items() if len(seqs) > 1}
    total = len(window)
    unique = len(hashes)

    return {
        "window_size": total,
        "unique_texts": unique,
        "duplicate_hashes": len(duplicates),
        "acceptance_rate": unique / total if total > 0 else 1.0,
        "would_reject": total - unique,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strokes-path", type=Path, default=STROKES_PATH)
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    ap.add_argument("--candidate-text", type=str, default=None,
                    help="check whether this text would be accepted")
    ap.add_argument("--check-last", type=int, default=None,
                    help="analyse the last N strokes for duplicate rate")
    ap.add_argument("--json", action="store_true", dest="json_output")
    args = ap.parse_args()

    strokes = load_recent_strokes(args.strokes_path, max(args.window, args.check_last or 0))

    if args.candidate_text is not None:
        result = should_accept(args.candidate_text, strokes, args.window)
        if args.json_output:
            print(json.dumps(result))
        else:
            status = "ACCEPT" if result["accept"] else "REJECT"
            print(f"{status}: {result['reason']}")
        return 0

    if args.check_last is not None:
        result = check_last_n(strokes, args.check_last)
        if args.json_output:
            print(json.dumps(result))
        else:
            print(f"window: {result['window_size']}")
            print(f"unique: {result['unique_texts']}")
            print(f"duplicates: {result['duplicate_hashes']}")
            print(f"acceptance rate: {result['acceptance_rate']:.2%}")
            print(f"would reject: {result['would_reject']}")
        return 0

    # Default: check last `window` strokes
    result = check_last_n(strokes, args.window)
    if args.json_output:
        print(json.dumps(result))
    else:
        print(f"window: {result['window_size']}")
        print(f"unique: {result['unique_texts']}")
        print(f"duplicates: {result['duplicate_hashes']}")
        print(f"acceptance rate: {result['acceptance_rate']:.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
