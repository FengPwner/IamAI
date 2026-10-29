"""Stroke stall detector — detect when the writer stops producing fresh content.

Two failure modes matter here:

1. **Silence stall** — the writer process is alive but emits nothing for
   longer than ``2 * cadence``.  Common causes: deadlock, unhandled
   exception caught by an outer try/except, or the process simply
   blocked on I/O that will never complete.

2. **Repetition stall** — the writer keeps emitting strokes, but they
   all say the same thing.  This is subtler: the process *looks* healthy
   (pid alive, files changing, commits happening) but no new ideas are
   entering the system.  The repo accumulates commits without
   accumulating knowledge.

   The real-world case that motivated this module: the writer spent
   ~3000 seconds cycling through the same three modules (chunk_text,
   parse_kv, retry) because it had exhausted its topic pool but kept
   drawing from a stale cache.  Commits kept landing; nothing new was
   being said.

This module provides:

* ``measure_silence(strokes, cadence_s)`` — seconds since last stroke,
  and whether that exceeds the silence threshold.
* ``measure_repetition(strokes, window)`` — fraction of recent strokes
  whose text is a near-duplicate of another stroke in the window.
* ``diagnose(strokes, cadence_s)`` — combined report with severity.

Usage::

    from iamai.stroke_stall_detector import diagnose, load_strokes

    strokes = load_strokes("data/strokes.jsonl")
    report = diagnose(strokes, cadence_s=15)
    if report["stalled"]:
        print(report["summary"])

Exit codes (for CLI / monitoring integration):

    0 — healthy
    1 — repetition stall
    2 — silence stall
    3 — both
"""

from __future__ import annotations

import json
import time
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


REPO = Path(__file__).resolve().parent.parent
DEFAULT_STROKES = REPO / "data" / "strokes.jsonl"

# Thresholds
REPETITION_RATIO_THRESHOLD = 0.6  # >60% duplicates = repetition stall
SILENCE_MULTIPLIER = 2.0          # >2x cadence = silence stall
DEFAULT_WINDOW = 50               # how many recent strokes to examine


def load_strokes(path: str | Path = DEFAULT_STROKES) -> List[Dict[str, Any]]:
    """Load strokes from a JSONL file.  Tolerates malformed lines."""
    strokes: List[Dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        return strokes
    for line in p.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            strokes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return strokes


def _extract_text(stroke: Dict[str, Any]) -> str:
    """Get the comparable text from a stroke dict."""
    return str(stroke.get("text", "") or stroke.get("content", "") or "")


def _similarity(a: str, b: str) -> float:
    """Return 0.0–1.0 similarity ratio between two strings."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def measure_silence(
    strokes: List[Dict[str, Any]],
    cadence_s: float = 15.0,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Measure how long the writer has been silent.

    Returns dict with keys: gap_s, threshold_s, silent, last_at.
    """
    if now is None:
        now = time.time()

    if not strokes:
        return {
            "gap_s": None,
            "threshold_s": cadence_s * SILENCE_MULTIPLIER,
            "silent": True,
            "last_at": None,
        }

    last = strokes[-1]
    last_at = last.get("at", "")
    gap_s: Optional[float] = None

    if last_at:
        try:
            # ISO format with timezone
            from datetime import datetime, timezone

            dt = datetime.fromisoformat(last_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            gap_s = now - dt.timestamp()
        except (ValueError, TypeError):
            pass

    threshold = cadence_s * SILENCE_MULTIPLIER
    silent = gap_s is not None and gap_s > threshold

    return {
        "gap_s": round(gap_s, 1) if gap_s is not None else None,
        "threshold_s": threshold,
        "silent": silent,
        "last_at": last_at or None,
    }


def measure_repetition(
    strokes: List[Dict[str, Any]],
    window: int = DEFAULT_WINDOW,
    similarity_threshold: float = 0.75,
) -> Dict[str, Any]:
    """Measure what fraction of recent strokes are near-duplicates.

    For each stroke in the window, check if any *other* stroke in the
    window is similar above the threshold.  This is O(n^2) but n is
    bounded by ``window`` (default 50) so it stays fast.

    Returns dict with keys: total, duplicates, ratio, stalled,
    duplicate_texts (list of the repeated texts, truncated).
    """
    recent = strokes[-window:] if len(strokes) > window else strokes[:]
    n = len(recent)
    if n < 2:
        return {
            "total": n,
            "duplicates": 0,
            "ratio": 0.0,
            "stalled": False,
            "duplicate_texts": [],
        }

    texts = [_extract_text(s) for s in recent]
    is_dup = [False] * n

    for i in range(n):
        if is_dup[i]:
            continue
        for j in range(i + 1, n):
            if is_dup[j]:
                continue
            if _similarity(texts[i], texts[j]) >= similarity_threshold:
                is_dup[j] = True

    dup_count = sum(is_dup)
    ratio = dup_count / n if n > 0 else 0.0
    dup_texts = [texts[i][:80] for i in range(n) if is_dup[i]]

    return {
        "total": n,
        "duplicates": dup_count,
        "ratio": round(ratio, 3),
        "stalled": ratio >= REPETITION_RATIO_THRESHOLD,
        "duplicate_texts": dup_texts[:5],
    }


def diagnose(
    strokes: List[Dict[str, Any]],
    cadence_s: float = 15.0,
    window: int = DEFAULT_WINDOW,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Combined diagnosis: silence + repetition, with severity.

    Returns dict with keys: stalled, silence, repetition, severity,
    summary, exit_code.
    """
    silence = measure_silence(strokes, cadence_s=cadence_s, now=now)
    repetition = measure_repetition(strokes, window=window)

    silence_stalled = silence["silent"]
    repetition_stalled = repetition["stalled"]
    stalled = silence_stalled or repetition_stalled

    if silence_stalled and repetition_stalled:
        severity = "critical"
        exit_code = 3
    elif silence_stalled:
        severity = "high"
        exit_code = 2
    elif repetition_stalled:
        severity = "medium"
        exit_code = 1
    else:
        severity = "healthy"
        exit_code = 0

    parts: list[str] = []
    if silence_stalled:
        gap = silence["gap_s"]
        parts.append(f"silence stall: {gap}s since last stroke (threshold {silence['threshold_s']}s)")
    if repetition_stalled:
        r = repetition
        parts.append(
            f"repetition stall: {r['duplicates']}/{r['total']} strokes are near-duplicates ({r['ratio']:.0%})"
        )
    if not parts:
        parts.append("no stall detected")

    summary = "; ".join(parts)

    return {
        "stalled": stalled,
        "silence": silence,
        "repetition": repetition,
        "severity": severity,
        "summary": summary,
        "exit_code": exit_code,
    }


# -- CLI entry point -------------------------------------------------------

def main() -> int:
    """Run diagnosis on the default strokes file and print results."""
    strokes = load_strokes()
    report = diagnose(strokes)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
