#!/usr/bin/env python3
"""stroke_sequence_integrity.py — verify the stroke log has not been corrupted.

after a process restart, container recycle, or manual intervention, the
append-only stroke log may contain anomalies that indicate data loss or
corruption. this module checks:

1. **monotonic sequence**: seq numbers must be strictly increasing
2. **no duplicates**: no two strokes share the same seq number
3. **no gaps**: seq numbers should be contiguous (1, 2, 3, ... N)
4. **temporal ordering**: timestamps should be non-decreasing
5. **reasonable gaps**: no negative time deltas; flag suspiciously large gaps

the distinction from existing tools:

    resurrection_latency.py  — measures silence gaps between strokes
    stroke_dedup_gate.py     — prevents duplicate content *before* writing
    pack_integrity_check.py  — validates git object storage
    stroke_sequence_integrity — validates the *structural integrity* of the
                                stroke log itself after any recovery event

usage:
    python3 tools/stroke_sequence_integrity.py
    python3 tools/stroke_sequence_integrity.py --strokes data/strokes.jsonl
    python3 tools/stroke_sequence_integrity.py --json
    python3 tools/stroke_sequence_integrity.py --tail 100  # check last 100 only

exit codes:
    0 — log is clean (no anomalies)
    1 — anomalies detected
    2 — error reading log
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
DEFAULT_STROKES = REPO / "data" / "strokes.jsonl"


@dataclass
class IntegrityReport:
    """Result of a stroke log integrity check."""

    total_strokes: int = 0
    first_seq: int = 0
    last_seq: int = 0
    duplicate_seqs: List[int] = field(default_factory=list)
    missing_seqs: List[int] = field(default_factory=list)
    non_monotonic: List[Tuple[int, int]] = field(default_factory=list)
    temporal_inversions: List[Tuple[int, str, str]] = field(default_factory=list)
    negative_gaps: List[Tuple[int, float]] = field(default_factory=list)
    large_gaps: List[Tuple[int, float]] = field(default_factory=list)
    is_clean: bool = True

    def anomaly_count(self) -> int:
        return (
            len(self.duplicate_seqs)
            + len(self.missing_seqs)
            + len(self.non_monotonic)
            + len(self.temporal_inversions)
            + len(self.negative_gaps)
            + len(self.large_gaps)
        )

    def to_dict(self) -> dict:
        return {
            "total_strokes": self.total_strokes,
            "first_seq": self.first_seq,
            "last_seq": self.last_seq,
            "duplicate_seqs": self.duplicate_seqs,
            "missing_seqs": self.missing_seqs[:50],  # cap output
            "missing_count": len(self.missing_seqs),
            "non_monotonic": self.non_monotonic,
            "temporal_inversions": self.temporal_inversions[:20],
            "negative_gaps": self.negative_gaps[:20],
            "large_gaps": self.large_gaps[:20],
            "anomaly_count": self.anomaly_count(),
            "is_clean": self.is_clean and self.anomaly_count() == 0,
        }


def parse_iso_timestamp(ts: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string to a datetime object."""
    if not ts:
        return None
    try:
        cleaned = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        return None


def load_strokes(path: Path, tail: Optional[int] = None) -> List[dict]:
    """Load strokes from a JSONL file.

    Args:
        path: path to strokes.jsonl
        tail: if set, only load the last N strokes

    Returns:
        list of parsed stroke dicts
    """
    if not path.exists():
        raise FileNotFoundError(f"strokes file not found: {path}")

    strokes = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                stroke = json.loads(line)
                strokes.append(stroke)
            except json.JSONDecodeError:
                continue

    if tail and tail > 0:
        strokes = strokes[-tail:]

    return strokes


def check_monotonic(strokes: List[dict]) -> Tuple[List[int], List[Tuple[int, int]]]:
    """Check that sequence numbers are strictly increasing.

    Returns:
        (duplicates, non_monotonic_pairs)
    """
    seen = {}
    duplicates = []
    non_monotonic = []

    prev_seq = None
    for stroke in strokes:
        seq = stroke.get("seq")
        if seq is None:
            continue

        if seq in seen:
            duplicates.append(seq)
        seen[seq] = True

        if prev_seq is not None and seq <= prev_seq:
            non_monotonic.append((prev_seq, seq))

        prev_seq = seq

    return duplicates, non_monotonic


def check_gaps(first_seq: int, last_seq: int, seen_seqs: set) -> List[int]:
    """Find missing sequence numbers in the range [first_seq, last_seq].

    Returns:
        list of missing seq numbers (capped at 1000 for large gaps)
    """
    if first_seq >= last_seq:
        return []

    missing = []
    cap = 1000
    for s in range(first_seq, last_seq + 1):
        if s not in seen_seqs:
            missing.append(s)
            if len(missing) >= cap:
                break

    return missing


def check_temporal_order(
    strokes: List[dict],
) -> Tuple[List[Tuple[int, str, str]], List[Tuple[int, float]], List[Tuple[int, float]]]:
    """Check that timestamps are non-decreasing and gaps are reasonable.

    Returns:
        (inversions, negative_gaps, large_gaps)
        where large_gaps are gaps > 86400s (24 hours)
    """
    inversions = []
    negative_gaps = []
    large_gaps = []

    prev_dt = None
    prev_seq = None

    for stroke in strokes:
        seq = stroke.get("seq")
        ts = stroke.get("at", "")
        dt = parse_iso_timestamp(ts)

        if dt is None or seq is None:
            continue

        if prev_dt is not None:
            delta = (dt - prev_dt).total_seconds()

            if delta < 0:
                inversions.append((seq, ts, str(prev_dt.isoformat())))
                negative_gaps.append((seq, delta))

            if delta > 86400:  # 24 hours
                large_gaps.append((seq, delta))

        prev_dt = dt
        prev_seq = seq

    return inversions, negative_gaps, large_gaps


def verify_integrity(
    strokes_path: Path = DEFAULT_STROKES,
    tail: Optional[int] = None,
    large_gap_threshold: float = 86400.0,
) -> IntegrityReport:
    """Run all integrity checks on the stroke log.

    Args:
        strokes_path: path to strokes.jsonl
        tail: if set, only check the last N strokes
        large_gap_threshold: seconds threshold for flagging large gaps

    Returns:
        IntegrityReport with all findings
    """
    report = IntegrityReport()

    try:
        strokes = load_strokes(strokes_path, tail=tail)
    except FileNotFoundError:
        report.is_clean = False
        return report

    if not strokes:
        report.is_clean = True
        return report

    report.total_strokes = len(strokes)

    # extract sequence numbers
    seqs = [s.get("seq") for s in strokes if s.get("seq") is not None]
    if not seqs:
        report.is_clean = False
        return report

    report.first_seq = seqs[0]
    report.last_seq = seqs[-1]

    # check monotonic and duplicates
    report.duplicate_seqs, report.non_monotonic = check_monotonic(strokes)

    # check gaps
    seen_seqs = set(seqs)
    report.missing_seqs = check_gaps(report.first_seq, report.last_seq, seen_seqs)

    # check temporal ordering
    (
        report.temporal_inversions,
        report.negative_gaps,
        report.large_gaps,
    ) = check_temporal_order(strokes)

    report.is_clean = report.anomaly_count() == 0
    return report


def format_report(report: IntegrityReport) -> str:
    """Format an IntegrityReport as a human-readable string."""
    lines = []
    lines.append(f"stroke sequence integrity: {'CLEAN' if report.is_clean else 'ANOMALIES'}")
    lines.append(f"  strokes checked: {report.total_strokes}")
    lines.append(f"  seq range: {report.first_seq} → {report.last_seq}")

    if report.duplicate_seqs:
        lines.append(f"  duplicates: {len(report.duplicate_seqs)} ({report.duplicate_seqs[:5]}...)")
    if report.missing_seqs:
        shown = report.missing_seqs[:10]
        suffix = f" ... +{len(report.missing_seqs) - 10} more" if len(report.missing_seqs) > 10 else ""
        lines.append(f"  missing seqs: {len(report.missing_seqs)} ({shown}{suffix})")
    if report.non_monotonic:
        lines.append(f"  non-monotonic: {len(report.non_monotonic)} pairs")
    if report.temporal_inversions:
        lines.append(f"  temporal inversions: {len(report.temporal_inversions)}")
    if report.negative_gaps:
        lines.append(f"  negative time gaps: {len(report.negative_gaps)}")
    if report.large_gaps:
        lines.append(f"  large gaps (>24h): {len(report.large_gaps)}")

    if report.is_clean:
        lines.append("  verdict: log integrity verified — no anomalies detected")
    else:
        lines.append(f"  verdict: {report.anomaly_count()} anomalies found — review recommended")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="verify stroke log integrity after process restarts"
    )
    parser.add_argument(
        "--strokes",
        type=Path,
        default=DEFAULT_STROKES,
        help="path to strokes.jsonl",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=None,
        help="only check the last N strokes",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="output as JSON",
    )
    args = parser.parse_args()

    try:
        report = verify_integrity(strokes_path=args.strokes, tail=args.tail)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_report(report))

    sys.exit(0 if report.is_clean else 1)


if __name__ == "__main__":
    main()
