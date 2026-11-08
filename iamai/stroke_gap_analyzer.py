"""stroke_gap_analyzer — classify inter-stroke gaps by severity and pattern.

While cadence_adherence and cadence_jitter measure *how regular* the
heartbeat is, they treat every gap the same.  This module asks a
different question: *what kind of gap is this, and what does it mean?*

Gaps are classified into four buckets:

- **micro** (< 2× expected cadence) — normal jitter, no action needed
- **warm** (2–10× expected cadence) — mild stall, likely transient
- **hot** (10–100× expected cadence) — significant disruption, worth
  investigating
- **cold** (> 100× expected cadence) — process was dead or suspended
  for an extended period

Beyond classification, the analyzer tracks *gap sequences*: consecutive
gaps in the same bucket that suggest a systemic pattern rather than a
one-off blip.

Public API::

    from iamai.stroke_gap_analyzer import (
        StrokeGapAnalyzer, GapBucket, GapSequence, gap_report,
    )

    analyzer = StrokeGapAnalyzer(expected_cadence_s=15)
    analyzer.ingest(timestamps)          # list of epoch floats

    summary = analyzer.summary()
    # {'total_gaps': 400, 'micro': 380, 'warm': 12, 'hot': 5, 'cold': 3,
    #  'mean_gap_s': 22.4, 'p95_gap_s': 180.0, 'longest_sequence': ...}

    report = gap_report(summary)
    # human-readable multi-line string
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence


class GapBucket(str, Enum):
    """Severity bucket for an inter-stroke gap."""

    MICRO = "micro"
    WARM = "warm"
    HOT = "hot"
    COLD = "cold"


@dataclass(frozen=True)
class GapRecord:
    """One inter-stroke gap with its classification."""

    index: int
    gap_s: float
    bucket: GapBucket
    ratio: float  # gap_s / expected_cadence_s


@dataclass
class GapSequence:
    """A run of consecutive gaps in the same bucket."""

    bucket: GapBucket
    start_index: int
    length: int
    total_s: float
    mean_gap_s: float

    @property
    def end_index(self) -> int:
        return self.start_index + self.length - 1


class StrokeGapAnalyzer:
    """Ingest stroke timestamps and classify every inter-stroke gap.

    Parameters
    ----------
    expected_cadence_s : float
        The intended interval between strokes (seconds).  Defaults to
        15 s, matching the qwen writer's configured cadence.
    thresholds : dict or None
        Override bucket boundaries.  Keys are ``"warm"``, ``"hot"``,
        ``"cold"``; values are multipliers of *expected_cadence_s*.
        Defaults: warm ≥ 2×, hot ≥ 10×, cold ≥ 100×.
    """

    def __init__(
        self,
        expected_cadence_s: float = 15.0,
        thresholds: Optional[dict] = None,
    ) -> None:
        if expected_cadence_s <= 0:
            raise ValueError("expected_cadence_s must be positive")
        self.expected_cadence_s = expected_cadence_s

        _defaults = {"warm": 2.0, "hot": 10.0, "cold": 100.0}
        self._thresholds = {**_defaults, **(thresholds or {})}
        # Validate monotonicity
        if not (
            self._thresholds["warm"]
            < self._thresholds["hot"]
            < self._thresholds["cold"]
        ):
            raise ValueError("thresholds must satisfy warm < hot < cold")

        self._records: List[GapRecord] = []
        self._timestamps: List[float] = []

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest(self, timestamps: Sequence[float]) -> int:
        """Add a batch of stroke timestamps.

        Returns the number of *new* gaps classified.  Timestamps are
        sorted internally; duplicates are dropped.
        """
        existing = set(self._timestamps)
        fresh = sorted(t for t in timestamps if t not in existing)
        if not fresh:
            return 0

        merged = sorted(set(self._timestamps) | set(fresh))
        old_len = len(self._timestamps)
        self._timestamps = merged

        # Recompute gaps from the merged timeline
        new_gaps = 0
        start = max(0, old_len - 1)  # overlap by one to re-classify boundary
        for i in range(start, len(merged) - 1):
            gap_s = merged[i + 1] - merged[i]
            ratio = gap_s / self.expected_cadence_s
            bucket = self._classify(ratio)
            rec = GapRecord(
                index=i, gap_s=gap_s, bucket=bucket, ratio=ratio,
            )
            # Replace if exists at this index, else append
            if i < len(self._records):
                self._records[i] = rec
            else:
                self._records.append(rec)
            new_gaps += 1
        return new_gaps

    def add(self, timestamp: float) -> Optional[GapRecord]:
        """Add a single timestamp.  Returns the new GapRecord or None."""
        n = self.ingest([timestamp])
        if n == 0:
            return None
        return self._records[-1] if self._records else None

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def records(self) -> List[GapRecord]:
        return list(self._records)

    @property
    def total_gaps(self) -> int:
        return len(self._records)

    def gaps_in(self, bucket: GapBucket) -> List[GapRecord]:
        """Return all records classified into *bucket*."""
        return [r for r in self._records if r.bucket is bucket]

    def gap_values(self) -> List[float]:
        """Return raw gap durations in seconds."""
        return [r.gap_s for r in self._records]

    def summary(self) -> dict:
        """Aggregate statistics across all ingested gaps."""
        if not self._records:
            return {
                "total_gaps": 0,
                "micro": 0,
                "warm": 0,
                "hot": 0,
                "cold": 0,
                "mean_gap_s": 0.0,
                "median_gap_s": 0.0,
                "p95_gap_s": 0.0,
                "max_gap_s": 0.0,
                "longest_sequence": None,
                "dominant_bucket": GapBucket.MICRO,
            }

        values = self.gap_values()
        counts = {b: 0 for b in GapBucket}
        for r in self._records:
            counts[r.bucket] += 1

        sequences = self.sequences()
        longest_seq = max(sequences, key=lambda s: s.length) if sequences else None

        dominant = max(counts, key=counts.get)  # type: ignore[arg-type]

        sorted_vals = sorted(values)
        p95_idx = min(int(len(sorted_vals) * 0.95), len(sorted_vals) - 1)

        return {
            "total_gaps": len(self._records),
            "micro": counts[GapBucket.MICRO],
            "warm": counts[GapBucket.WARM],
            "hot": counts[GapBucket.HOT],
            "cold": counts[GapBucket.COLD],
            "mean_gap_s": round(statistics.mean(values), 2),
            "median_gap_s": round(statistics.median(values), 2),
            "p95_gap_s": round(sorted_vals[p95_idx], 2),
            "max_gap_s": round(max(values), 2),
            "longest_sequence": longest_seq,
            "dominant_bucket": dominant,
        }

    def sequences(self, min_length: int = 2) -> List[GapSequence]:
        """Find runs of consecutive gaps in the same bucket.

        Only sequences of at least *min_length* are returned.
        """
        if not self._records:
            return []

        seqs: List[GapSequence] = []
        cur_bucket = self._records[0].bucket
        cur_start = 0
        cur_total = 0.0
        cur_len = 0

        for rec in self._records:
            if rec.bucket is cur_bucket:
                cur_len += 1
                cur_total += rec.gap_s
            else:
                if cur_len >= min_length:
                    seqs.append(
                        GapSequence(
                            bucket=cur_bucket,
                            start_index=cur_start,
                            length=cur_len,
                            total_s=round(cur_total, 2),
                            mean_gap_s=round(cur_total / cur_len, 2),
                        )
                    )
                cur_bucket = rec.bucket
                cur_start = rec.index
                cur_total = rec.gap_s
                cur_len = 1

        # Flush final run
        if cur_len >= min_length:
            seqs.append(
                GapSequence(
                    bucket=cur_bucket,
                    start_index=cur_start,
                    length=cur_len,
                    total_s=round(cur_total, 2),
                    mean_gap_s=round(cur_total / cur_len, 2),
                )
            )
        return seqs

    def health_score(self) -> float:
        """Return a [0, 1] health score based on gap distribution.

        1.0 = all gaps are micro (perfect cadence).
        0.0 = all gaps are cold (worst case).

        Weighted: micro=1.0, warm=0.6, hot=0.2, cold=0.0.
        """
        if not self._records:
            return 1.0

        weights = {
            GapBucket.MICRO: 1.0,
            GapBucket.WARM: 0.6,
            GapBucket.HOT: 0.2,
            GapBucket.COLD: 0.0,
        }
        total = sum(weights[r.bucket] for r in self._records)
        return round(total / len(self._records), 4)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _classify(self, ratio: float) -> GapBucket:
        if ratio >= self._thresholds["cold"]:
            return GapBucket.COLD
        if ratio >= self._thresholds["hot"]:
            return GapBucket.HOT
        if ratio >= self._thresholds["warm"]:
            return GapBucket.WARM
        return GapBucket.MICRO


def gap_report(summary: dict) -> str:
    """Format a summary dict into a human-readable multi-line string."""
    if summary["total_gaps"] == 0:
        return "No gaps recorded."

    lines = [
        f"Stroke Gap Report — {summary['total_gaps']} gaps analyzed",
        f"  micro:  {summary['micro']:>5}  (healthy jitter)",
        f"  warm:   {summary['warm']:>5}  (mild stalls)",
        f"  hot:    {summary['hot']:>5}  (significant disruptions)",
        f"  cold:   {summary['cold']:>5}  (extended dead zones)",
        "",
        f"  mean gap:   {summary['mean_gap_s']}s",
        f"  median gap: {summary['median_gap_s']}s",
        f"  p95 gap:    {summary['p95_gap_s']}s",
        f"  max gap:    {summary['max_gap_s']}s",
        "",
        f"  dominant bucket: {summary['dominant_bucket'].value}",
    ]

    seq = summary.get("longest_sequence")
    if seq is not None:
        lines.append(
            f"  longest sequence: {seq.length} consecutive {seq.bucket.value} "
            f"gaps ({seq.total_s}s total, mean {seq.mean_gap_s}s)"
        )

    return "\n".join(lines)
