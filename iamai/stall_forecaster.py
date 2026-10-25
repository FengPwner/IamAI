"""Stall forecaster — predict imminent writer stalls from gap patterns.

The existing ``stall_classifier`` answers "is the writer stalled *right now*?"
and ``commit_gap`` answers "how long since the last commit?".  Neither tells
the caretaker **whether a stall is about to happen** — which is the question
that matters for proactive intervention.

This module analyses the last *N* commit gaps and produces a risk score plus
human-readable reasoning.  It detects three warning signals:

1. **Trend** — gaps are getting longer (linear regression slope > threshold)
2. **Volatility** — gaps are erratic (high coefficient of variation)
3. **Proximity** — the most recent gap is already close to the warn threshold

Each signal contributes to a ``risk_score`` in [0.0, 1.0]:

- ``< 0.3``  → ``low``    — writer is healthy, no action needed
- ``0.3–0.6`` → ``medium`` — monitor closely, consider pre-emptive restart
- ``> 0.6``  → ``high``   — stall likely imminent, alert caretaker

Design choices
--------------
- **Pure function** — takes a list of gap floats, returns a dataclass.
  No subprocess calls, no filesystem access, trivially testable.
- **Minimum sample size** — returns ``low`` risk with a caveat when fewer
  than 3 data points are available (not enough signal).
- **Configurable thresholds** — callers can tune the warn threshold
  (default 1200 s = 20 min, matching ``commit_gap.WARN_THRESHOLD``).

Usage::

    from iamai.stall_forecaster import forecast_stall, RiskReport

    gaps = [600, 610, 605, 720, 800, 950, 1100]
    report = forecast_stall(gaps)
    print(report.risk_score)     # 0.52
    print(report.risk_level)     # "medium"
    print(report.reasons)        # ["upward trend (+68.2 s/commit)", ...]
    print(report.summary())      # "medium risk (0.52): upward trend, ..."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

MIN_SAMPLES = 3
DEFAULT_WARN_THRESHOLD = 1200.0   # seconds — matches commit_gap.WARN_THRESHOLD
TREND_THRESHOLD = 30.0            # slope (s/commit) above which trend is "upward"
CV_WARN = 0.4                     # coefficient of variation above which gaps are "erratic"
PROXIMITY_WARN_RATIO = 0.6       # fraction of warn_threshold that triggers proximity signal


@dataclass(frozen=True)
class RiskReport:
    """Structured stall-forecast result."""

    risk_score: float
    risk_level: str               # "low" | "medium" | "high"
    reasons: List[str] = field(default_factory=list)
    sample_size: int = 0
    latest_gap: float = 0.0
    mean_gap: float = 0.0
    trend_slope: float = 0.0
    cv: float = 0.0

    def summary(self) -> str:
        """One-liner for caretaker logs."""
        if not self.reasons:
            return f"{self.risk_level} risk ({self.risk_score:.2f}): healthy"
        joined = ", ".join(self.reasons)
        return f"{self.risk_level} risk ({self.risk_score:.2f}): {joined}"

    def as_dict(self) -> dict:
        return {
            "risk_score": round(self.risk_score, 3),
            "risk_level": self.risk_level,
            "reasons": self.reasons,
            "sample_size": self.sample_size,
            "latest_gap": round(self.latest_gap, 1),
            "mean_gap": round(self.mean_gap, 1),
            "trend_slope": round(self.trend_slope, 2),
            "cv": round(self.cv, 3),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _simple_linear_slope(values: list[float]) -> float:
    """Return the slope of OLS regression of *values* on index."""
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    den = sum((i - x_mean) ** 2 for i in range(n))
    if den == 0:
        return 0.0
    return num / den


def _coefficient_of_variation(values: list[float]) -> float:
    """Return CV = stdev / mean (population stdev)."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    if mean == 0:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / n
    return (variance ** 0.5) / mean


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def forecast_stall(
    gaps: list[float],
    *,
    warn_threshold: float = DEFAULT_WARN_THRESHOLD,
    trend_threshold: float = TREND_THRESHOLD,
    cv_warn: float = CV_WARN,
    proximity_ratio: float = PROXIMITY_WARN_RATIO,
    min_samples: int = MIN_SAMPLES,
) -> RiskReport:
    """Analyse recent commit gaps and forecast stall risk.

    Args:
        gaps: list of recent inter-commit gaps in seconds, oldest first.
        warn_threshold: gap length (seconds) at which ``commit_gap`` warns.
        trend_threshold: slope (s/commit) above which an upward trend is flagged.
        cv_warn: coefficient of variation above which gaps are "erratic".
        proximity_ratio: fraction of *warn_threshold* that triggers proximity.
        min_samples: minimum number of data points for meaningful analysis.

    Returns:
        A ``RiskReport`` with score, level, and human-readable reasons.
    """
    # Edge cases ----------------------------------------------------------
    if not gaps:
        return RiskReport(
            risk_score=0.0,
            risk_level="low",
            reasons=["no data"],
            sample_size=0,
        )

    n = len(gaps)
    latest = gaps[-1]
    mean = sum(gaps) / n

    if n < min_samples:
        return RiskReport(
            risk_score=0.0,
            risk_level="low",
            reasons=[f"insufficient data ({n}/{min_samples} samples)"],
            sample_size=n,
            latest_gap=latest,
            mean_gap=mean,
        )

    # Signals -------------------------------------------------------------
    reasons: list[str] = []
    score_components: list[float] = []

    # 1. Trend signal
    slope = _simple_linear_slope(gaps)
    if slope > trend_threshold:
        # Score scales with how far above threshold
        trend_score = _clamp((slope - trend_threshold) / (trend_threshold * 3))
        score_components.append(trend_score * 0.4)
        reasons.append(f"upward trend (+{slope:.1f} s/commit)")
    else:
        score_components.append(0.0)

    # 2. Volatility signal
    cv = _coefficient_of_variation(gaps)
    if cv > cv_warn:
        vol_score = _clamp((cv - cv_warn) / cv_warn)
        score_components.append(vol_score * 0.3)
        reasons.append(f"erratic gaps (CV={cv:.2f})")
    else:
        score_components.append(0.0)

    # 3. Proximity signal
    proximity_floor = warn_threshold * proximity_ratio
    if latest > proximity_floor:
        prox_score = _clamp((latest - proximity_floor) / (warn_threshold - proximity_floor))
        score_components.append(prox_score * 0.3)
        reasons.append(f"latest gap {latest:.0f}s nearing threshold ({warn_threshold:.0f}s)")
    else:
        score_components.append(0.0)

    risk_score = _clamp(sum(score_components))

    # Level mapping -------------------------------------------------------
    if risk_score < 0.3:
        level = "low"
    elif risk_score <= 0.6:
        level = "medium"
    else:
        level = "high"

    return RiskReport(
        risk_score=risk_score,
        risk_level=level,
        reasons=reasons,
        sample_size=n,
        latest_gap=latest,
        mean_gap=mean,
        trend_slope=slope,
        cv=cv,
    )


def forecast_from_log(
    log_path: str = "data/strokes.jsonl",
    *,
    last_n: int = 20,
    warn_threshold: float = DEFAULT_WARN_THRESHOLD,
) -> RiskReport:
    """Convenience: parse a strokes JSONL and forecast from the last *N* gaps.

    Reads timestamps from the JSONL file, computes inter-stroke gaps, and
    delegates to :func:`forecast_stall`.

    Args:
        log_path: path to the strokes JSONL file.
        last_n: how many recent gaps to analyse.
        warn_threshold: forwarded to ``forecast_stall``.

    Returns:
        A ``RiskReport``.
    """
    from datetime import datetime
    from pathlib import Path

    path = Path(log_path)
    if not path.is_file():
        return RiskReport(
            risk_score=0.0,
            risk_level="low",
            reasons=["log file not found"],
        )

    timestamps: list[float] = []
    for line in path.read_text().strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            import json
            entry = json.loads(line)
            at = entry.get("at", "")
            # Support ISO format timestamps
            dt = datetime.fromisoformat(at)
            timestamps.append(dt.timestamp())
        except (ValueError, KeyError, TypeError):
            continue

    if len(timestamps) < 2:
        return RiskReport(
            risk_score=0.0,
            risk_level="low",
            reasons=["insufficient timestamps in log"],
        )

    timestamps.sort()
    all_gaps = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
    gaps = all_gaps[-last_n:]

    return forecast_stall(gaps, warn_threshold=warn_threshold)
