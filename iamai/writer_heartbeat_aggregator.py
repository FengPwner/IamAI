"""writer_heartbeat_aggregator — composite health score from multiple signals.

A single cadence check, gap trend, or stall probe each captures one
facet of writer health.  This module fuses them into a single
``HeartbeatReport`` that a caretaker can glance at and act on.

===========================  ============================================
module                       what it contributes
===========================  ============================================
cadence_monitor              stroke/batch gap vs target
stroke_gap_analyzer          gap trend + risk score
stall_classifier             stall type classification
stall_probe                  binary "is it stalled now?"
writer_silence_detector      seconds since last stroke
**writer_heartbeat_aggregator**  **fuses all signals → one verdict**
===========================  ============================================

Signal model
------------

Each signal is a ``Signal`` dataclass:

- ``name`` (str): signal identifier
- ``score`` (float): 0.0 (dead) → 1.0 (perfect)
- ``weight`` (float): relative importance in the composite
- ``stale`` (bool): True if the signal itself could not be computed

The composite score is the weighted mean of non-stale signals.
If *all* signals are stale, the composite is 0.0 and the verdict
is ``unknown``.

Verdict thresholds
------------------

==========  =========  =========================================
score       verdict    meaning
==========  =========  =========================================
>= 0.80     healthy    all systems nominal
>= 0.60     fair       minor degradation, no action needed
>= 0.40     warning    significant degradation, investigate
>= 0.20     critical   major failure, restart likely needed
<  0.20     dead       no meaningful signal, full recovery
==========  =========  =========================================

Usage
-----

    >>> signals = [
    ...     Signal("cadence", 0.9, weight=2.0),
    ...     Signal("gap_trend", 0.7, weight=1.5),
    ...     Signal("silence", 0.85, weight=1.0),
    ...     Signal("stall_probe", 1.0, weight=2.0),
    ... ]
    >>> report = aggregate(signals)
    >>> report.verdict
    'healthy'
    >>> 0.8 <= report.composite <= 1.0
    True

Zero dependencies.  stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Signal:
    """A single health signal from a monitoring module."""

    name: str
    score: float
    weight: float = 1.0
    stale: bool = False
    detail: str = ""

    def __post_init__(self) -> None:
        if not (0.0 <= self.score <= 1.0):
            raise ValueError(
                f"Signal {self.name!r} score must be in [0, 1], got {self.score}"
            )
        if self.weight < 0:
            raise ValueError(
                f"Signal {self.name!r} weight must be >= 0, got {self.weight}"
            )


@dataclass(frozen=True)
class HeartbeatReport:
    """Composite health assessment."""

    composite: float
    verdict: str
    signals: List[Signal]
    stale_count: int
    active_count: int
    at: str  # ISO-8601 timestamp

    def summary(self) -> str:
        """One-line human-readable summary."""
        parts = [f"{s.name}={s.score:.2f}" for s in self.signals]
        signal_str = ", ".join(parts) if parts else "no signals"
        return (
            f"heartbeat {self.composite:.2f} ({self.verdict}) "
            f"[{signal_str}] stale={self.stale_count}"
        )

    def weakest(self) -> Optional[Signal]:
        """Return the signal with the lowest score, or None."""
        if not self.signals:
            return None
        return min(self.signals, key=lambda s: s.score)

    def strongest(self) -> Optional[Signal]:
        """Return the signal with the highest score, or None."""
        if not self.signals:
            return None
        return max(self.signals, key=lambda s: s.score)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        return {
            "composite": round(self.composite, 4),
            "verdict": self.verdict,
            "signals": [
                {
                    "name": s.name,
                    "score": round(s.score, 4),
                    "weight": s.weight,
                    "stale": s.stale,
                    "detail": s.detail,
                }
                for s in self.signals
            ],
            "stale_count": self.stale_count,
            "active_count": self.active_count,
            "at": self.at,
        }


# ---------------------------------------------------------------------------
# Verdict thresholds
# ---------------------------------------------------------------------------

_THRESHOLDS = [
    (0.80, "healthy"),
    (0.60, "fair"),
    (0.40, "warning"),
    (0.20, "critical"),
    (0.00, "dead"),
]


def _score_to_verdict(score: float) -> str:
    """Map a composite score to a verdict string."""
    for threshold, verdict in _THRESHOLDS:
        if score >= threshold:
            return verdict
    return "unknown"


# ---------------------------------------------------------------------------
# Core aggregation
# ---------------------------------------------------------------------------

def aggregate(
    signals: Sequence[Signal],
    now: Optional[datetime] = None,
) -> HeartbeatReport:
    """Compute the weighted composite score and verdict.

    Parameters
    ----------
    signals : sequence of Signal
        Health signals from individual monitoring modules.
    now : datetime, optional
        Timestamp for the report; defaults to ``datetime.now(timezone.utc)``.

    Returns
    -------
    HeartbeatReport
        Composite score, verdict, and per-signal breakdown.

    Raises
    ------
    ValueError
        If *signals* is empty.

    Examples
    --------
    >>> aggregate([Signal("a", 1.0), Signal("b", 0.5)]).verdict
    'fair'
    >>> aggregate([Signal("a", 1.0, weight=3.0), Signal("b", 0.0, weight=1.0)]).composite
    0.75
    """
    if not signals:
        raise ValueError("aggregate() requires at least one signal")

    ts = now or datetime.now(timezone.utc)
    sigs = list(signals)

    active = [s for s in sigs if not s.stale]
    stale = [s for s in sigs if s.stale]

    if not active:
        return HeartbeatReport(
            composite=0.0,
            verdict="unknown",
            signals=sigs,
            stale_count=len(stale),
            active_count=0,
            at=ts.isoformat(),
        )

    total_weight = sum(s.weight for s in active)
    if total_weight == 0:
        composite = 0.0
    else:
        composite = sum(s.score * s.weight for s in active) / total_weight

    # Clamp to [0, 1] for floating-point safety
    composite = max(0.0, min(1.0, composite))

    return HeartbeatReport(
        composite=composite,
        verdict=_score_to_verdict(composite),
        signals=sigs,
        stale_count=len(stale),
        active_count=len(active),
        at=ts.isoformat(),
    )


# ---------------------------------------------------------------------------
# Signal builders — convenience functions for common signals
# ---------------------------------------------------------------------------

def cadence_signal(
    actual_gap: float,
    target_gap: float,
    weight: float = 2.0,
) -> Signal:
    """Build a cadence signal from actual vs target gap.

    Score logic:
    - actual <= target → 1.0
    - actual <= 1.5× target → linear decay 1.0 → 0.7
    - actual <= 3× target → linear decay 0.7 → 0.3
    - actual > 3× target → 0.0

    >>> s = cadence_signal(15.0, 15.0)
    >>> s.score
    1.0
    >>> s = cadence_signal(45.0, 15.0)
    >>> round(s.score, 2)
    0.3
    >>> s = cadence_signal(100.0, 15.0)
    >>> s.score
    0.0
    """
    if target_gap <= 0:
        return Signal("cadence", 0.0, weight=weight, stale=True,
                       detail="target_gap must be > 0")

    ratio = actual_gap / target_gap

    if ratio <= 1.0:
        score = 1.0
    elif ratio <= 1.5:
        score = 1.0 - 0.6 * (ratio - 1.0)  # 1.0 → 0.7
    elif ratio <= 3.0:
        score = 0.7 - 0.4 * ((ratio - 1.5) / 1.5)  # 0.7 → 0.3
    else:
        score = 0.0

    return Signal(
        "cadence",
        score,
        weight=weight,
        detail=f"actual={actual_gap:.1f}s target={target_gap:.1f}s ratio={ratio:.2f}",
    )


def silence_signal(
    seconds_since_last: float,
    threshold: float = 60.0,
    weight: float = 1.5,
) -> Signal:
    """Build a signal from seconds since last stroke.

    Score decays linearly from 1.0 at 0 s to 0.0 at *threshold* s.

    >>> silence_signal(0.0, 60.0).score
    1.0
    >>> silence_signal(30.0, 60.0).score
    0.5
    >>> silence_signal(120.0, 60.0).score
    0.0
    """
    if threshold <= 0:
        return Signal("silence", 0.0, weight=weight, stale=True,
                       detail="threshold must be > 0")

    score = max(0.0, 1.0 - seconds_since_last / threshold)
    return Signal(
        "silence",
        score,
        weight=weight,
        detail=f"last_stroke={seconds_since_last:.0f}s threshold={threshold:.0f}s",
    )


def stall_probe_signal(
    is_alive: bool,
    weight: float = 2.5,
) -> Signal:
    """Binary alive/dead signal from a process probe.

    >>> stall_probe_signal(True).score
    1.0
    >>> stall_probe_signal(False).score
    0.0
    """
    return Signal(
        "stall_probe",
        1.0 if is_alive else 0.0,
        weight=weight,
        detail="alive" if is_alive else "dead",
    )


def gap_trend_signal(
    slope: float,
    max_slope: float = 10.0,
    weight: float = 1.5,
) -> Signal:
    """Build a signal from the gap trend slope.

    Negative slope (gaps shrinking) → 1.0.
    Zero slope → 0.8.
    Positive slope (gaps growing) → decays to 0.0 at *max_slope*.

    >>> gap_trend_signal(-1.0).score
    1.0
    >>> gap_trend_signal(0.0).score
    0.8
    >>> gap_trend_signal(10.0).score
    0.0
    """
    if max_slope <= 0:
        return Signal("gap_trend", 0.0, weight=weight, stale=True)

    if slope < 0:
        score = 1.0
    elif slope == 0:
        score = 0.8
    elif slope <= max_slope:
        score = 0.8 - 0.8 * (slope / max_slope)
    else:
        score = 0.0

    return Signal(
        "gap_trend",
        score,
        weight=weight,
        detail=f"slope={slope:.3f} max_slope={max_slope:.1f}",
    )


def commit_freshness_signal(
    seconds_since_commit: float,
    target_interval: float = 600.0,
    weight: float = 1.0,
) -> Signal:
    """Build a signal from time since last batch commit.

    Score decays from 1.0 at 0 s to 0.0 at 3× target_interval.

    >>> commit_freshness_signal(0.0, 600.0).score
    1.0
    >>> commit_freshness_signal(600.0, 600.0).score  # doctest: +ELLIPSIS
    0.666...
    >>> commit_freshness_signal(2400.0, 600.0).score
    0.0
    """
    if target_interval <= 0:
        return Signal("commit_freshness", 0.0, weight=weight, stale=True)

    max_age = 3.0 * target_interval
    score = max(0.0, 1.0 - seconds_since_commit / max_age)

    return Signal(
        "commit_freshness",
        score,
        weight=weight,
        detail=f"age={seconds_since_commit:.0f}s max={max_age:.0f}s",
    )


# ---------------------------------------------------------------------------
# Trend analysis — compare two reports
# ---------------------------------------------------------------------------

def trend(
    older: HeartbeatReport,
    newer: HeartbeatReport,
) -> Dict[str, Any]:
    """Compare two heartbeat reports to determine health trajectory.

    Returns a dict with:
    - ``delta`` (float): newer.composite - older.composite
    - ``direction`` (str): "improving" | "stable" | "declining"
    - ``verdict_change`` (bool): whether the verdict label changed
    - ``improving_signals`` (list[str]): signals that improved
    - ``declining_signals`` (list[str]): signals that declined

    >>> from datetime import datetime, timezone
    >>> now = datetime.now(timezone.utc)
    >>> old = HeartbeatReport(0.5, "warning", [], 0, 0, now.isoformat())
    >>> new = HeartbeatReport(0.8, "healthy", [], 0, 0, now.isoformat())
    >>> t = trend(old, new)
    >>> t["direction"]
    'improving'
    """
    delta = newer.composite - older.composite

    if delta > 0.05:
        direction = "improving"
    elif delta < -0.05:
        direction = "declining"
    else:
        direction = "stable"

    # Match signals by name for per-signal comparison
    old_map = {s.name: s for s in older.signals}
    new_map = {s.name: s for s in newer.signals}

    improving: List[str] = []
    declining: List[str] = []

    for name, new_sig in new_map.items():
        if name in old_map:
            old_sig = old_map[name]
            if new_sig.score > old_sig.score + 0.01:
                improving.append(name)
            elif new_sig.score < old_sig.score - 0.01:
                declining.append(name)

    return {
        "delta": round(delta, 4),
        "direction": direction,
        "verdict_change": older.verdict != newer.verdict,
        "improving_signals": sorted(improving),
        "declining_signals": sorted(declining),
    }


# ---------------------------------------------------------------------------
# Quick-check helpers
# ---------------------------------------------------------------------------

def is_healthy(report: HeartbeatReport) -> bool:
    """True when the report verdict is 'healthy'.

    >>> is_healthy(HeartbeatReport(0.9, "healthy", [], 0, 1, ""))
    True
    >>> is_healthy(HeartbeatReport(0.5, "warning", [], 0, 1, ""))
    False
    """
    return report.verdict == "healthy"


def needs_attention(report: HeartbeatReport) -> bool:
    """True when the verdict is 'warning', 'critical', 'dead', or 'unknown'.

    >>> needs_attention(HeartbeatReport(0.3, "critical", [], 0, 1, ""))
    True
    >>> needs_attention(HeartbeatReport(0.9, "healthy", [], 0, 1, ""))
    False
    """
    return report.verdict in ("warning", "critical", "dead", "unknown")


def build_default_report(
    actual_stroke_gap: float = 15.0,
    target_stroke_gap: float = 15.0,
    seconds_since_last: float = 15.0,
    is_alive: bool = True,
    gap_slope: float = 0.0,
    seconds_since_commit: float = 300.0,
    target_commit_interval: float = 600.0,
    now: Optional[datetime] = None,
) -> HeartbeatReport:
    """Build a full heartbeat report from raw measurements.

    Convenience wrapper that creates all signals and aggregates them
    with default weights.

    >>> r = build_default_report()
    >>> r.verdict
    'healthy'
    >>> r.active_count
    5
    """
    signals = [
        cadence_signal(actual_stroke_gap, target_stroke_gap),
        silence_signal(seconds_since_last),
        stall_probe_signal(is_alive),
        gap_trend_signal(gap_slope),
        commit_freshness_signal(seconds_since_commit, target_commit_interval),
    ]
    return aggregate(signals, now=now)


# ---------------------------------------------------------------------------
# CLI entry point (for caretaker scripts)
# ---------------------------------------------------------------------------

def _cli() -> None:  # pragma: no cover
    """Print a JSON heartbeat report to stdout."""
    import json
    import sys

    # Default: all signals healthy (caretaker scripts pass real values)
    report = build_default_report()
    json.dump(report.to_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":  # pragma: no cover
    _cli()
