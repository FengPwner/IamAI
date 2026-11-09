"""588 — commit_backlog_forecaster: predict backlog clearance and pressure alerts.

the batch committer runs every 600s. the writer produces strokes every 15s.
when commits can't keep pace — maybe push failures, lock contention, or just
a burst of strokes — the backlog grows. right now the caretaker only sees
the current backlog *size*. that's a lagging indicator.

this module turns it into a *leading* indicator:

    history of (timestamp, pending_count) samples
                          │
                          ▼
              commit_backlog_forecaster
                          │
              ┌───────────┼────────────┐
              ▼           ▼            ▼
          velocity    eta_clear     pressure
        (files/min)  (seconds)    (green/yellow/red)

it answers three questions the caretaker actually needs:

  1. **is the backlog growing or shrinking?** velocity tells you the
     net rate: positive means commits outpace new strokes, negative
     means the backlog is accumulating.

  2. **when will it clear?** if velocity is positive, eta_seconds
     estimates how long until pending_count hits zero at the current
     rate. infinity if stalled or growing.

  3. **should i worry?** pressure level synthesizes size + velocity +
     trend into green / yellow / red. green: shrinking or small.
     yellow: growing slowly or moderately sized. red: growing fast
     or already large.

design decisions:

  1. **samples are (timestamp, count) pairs, not just counts.** you
     need the time axis to compute velocity. a bare count of 8
     means nothing without knowing whether it was 4 a minute ago
     or 16 a minute ago.

  2. **linear regression on a sliding window.** keeping it simple.
     exponential models overfit noisy data; linear gives a stable
     trend line that's good enough for short-term prediction.
     default window: last 30 samples (~30 minutes at 1-min cadence).

  3. **velocity sign convention.** positive velocity = backlog
     shrinking (count decreasing over time). this matches the
     caretaker's intuition: "velocity is good" should mean things
     are improving.

  4. **pressure thresholds are configurable, not hardcoded.**
     different repos have different baselines. a 20-file backlog
     is alarming in a repo that usually has 2, but normal in one
     that batches 50.

  5. **ForecastReport is a dataclass, not a dict.** typed fields,
     IDE autocomplete, no stringly-typed key errors.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Tuple


@dataclass
class ForecastReport:
    """snapshot of backlog forecast at a point in time."""
    pending_count: int
    velocity: float  # files per second; positive = shrinking
    eta_seconds: float  # seconds until clear; inf if not clearing
    pressure: str  # "green" | "yellow" | "red"
    trend_samples: int  # how many samples were used
    detail: str = ""

    @property
    def is_clearing(self) -> bool:
        return self.velocity > 0 and self.eta_seconds < float("inf")

    @property
    def is_growing(self) -> bool:
        return self.velocity < 0

    def __repr__(self) -> str:
        eta_str = (
            f"{self.eta_seconds:.0f}s"
            if self.eta_seconds < float("inf")
            else "never"
        )
        return (
            f"ForecastReport(pending={self.pending_count}, "
            f"vel={self.velocity:+.4f}/s, "
            f"eta={eta_str}, "
            f"pressure={self.pressure!r})"
        )


class CommitBacklogForecaster:
    """tracks pending-file counts over time and forecasts clearance."""

    def __init__(
        self,
        max_samples: int = 60,
        pressure_yellow_size: int = 10,
        pressure_red_size: int = 25,
        pressure_yellow_velocity: float = -0.01,
        pressure_red_velocity: float = -0.05,
        clock=None,
    ):
        """
        Args:
            max_samples: how many (time, count) pairs to retain.
            pressure_yellow_size: backlog size triggering yellow
                (if velocity is also non-positive).
            pressure_red_size: backlog size triggering red.
            pressure_yellow_velocity: velocity threshold; below this
                (i.e. growing faster) triggers yellow.
            pressure_red_velocity: velocity threshold; below this
                triggers red.
            clock: callable returning current time (default time.time).
        """
        self.max_samples = max_samples
        self.pressure_yellow_size = pressure_yellow_size
        self.pressure_red_size = pressure_red_size
        self.pressure_yellow_velocity = pressure_yellow_velocity
        self.pressure_red_velocity = pressure_red_velocity
        self._clock = clock or time.time
        self._samples: Deque[Tuple[float, int]] = deque(maxlen=max_samples)

    # ── data ingestion ─────────────────────────────────────────

    def add_sample(self, pending_count: int, timestamp: Optional[float] = None) -> None:
        """record a backlog observation.

        Args:
            pending_count: number of uncommitted files right now.
            timestamp: when observed (default: current time).
        """
        ts = timestamp if timestamp is not None else self._clock()
        self._samples.append((ts, max(0, pending_count)))

    def add_samples(self, observations: List[Tuple[float, int]]) -> None:
        """bulk-load historical (timestamp, count) pairs."""
        for ts, count in observations:
            self.add_sample(count, ts)

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    @property
    def latest(self) -> Optional[Tuple[float, int]]:
        if not self._samples:
            return None
        return self._samples[-1]

    # ── analysis ───────────────────────────────────────────────

    def _linear_fit(self) -> Tuple[float, float]:
        """fit y = a + b*t over stored samples.

        returns (intercept, slope) where slope is files/second.
        slope < 0 means backlog is shrinking (count decreasing).
        """
        n = len(self._samples)
        if n < 2:
            # not enough data for a trend
            if n == 1:
                return (float(self._samples[0][1]), 0.0)
            return (0.0, 0.0)

        sum_t = sum(s[0] for s in self._samples)
        sum_y = sum(s[1] for s in self._samples)
        sum_tt = sum(s[0] * s[0] for s in self._samples)
        sum_ty = sum(s[0] * s[1] for s in self._samples)

        denom = n * sum_tt - sum_t * sum_t
        if abs(denom) < 1e-12:
            # all timestamps identical — no trend computable
            return (sum_y / n, 0.0)

        slope = (n * sum_ty - sum_t * sum_y) / denom
        intercept = (sum_y - slope * sum_t) / n
        return (intercept, slope)

    def velocity(self) -> float:
        """backlog change rate in files/second.

        positive = shrinking (good), negative = growing (bad).
        sign is inverted from the raw slope so that "positive is good."
        """
        _, slope = self._linear_fit()
        return -slope

    def eta_clear(self) -> float:
        """estimated seconds until backlog reaches zero.

        returns float('inf') if backlog is not shrinking or data
        is insufficient.
        """
        if not self._samples:
            return float("inf")

        current = self._samples[-1][1]
        if current <= 0:
            return 0.0

        vel = self.velocity()
        if vel <= 0:
            return float("inf")

        return current / vel

    def pressure_level(self) -> str:
        """synthesize size + velocity into a traffic-light signal.

        logic:
          - red if count >= red_size, OR velocity <= red_velocity
          - yellow if count >= yellow_size OR velocity <= yellow_velocity
          - green otherwise
        """
        if not self._samples:
            return "green"

        count = self._samples[-1][1]
        vel = self.velocity()

        # red conditions
        if count >= self.pressure_red_size:
            return "red"
        if vel <= self.pressure_red_velocity:
            return "red"

        # yellow conditions
        if count >= self.pressure_yellow_size:
            return "yellow"
        if vel <= self.pressure_yellow_velocity:
            return "yellow"

        return "green"

    def forecast(self) -> ForecastReport:
        """produce a complete forecast snapshot."""
        count = self._samples[-1][1] if self._samples else 0
        vel = self.velocity()
        eta = self.eta_clear()
        pressure = self.pressure_level()

        # build detail string
        if not self._samples:
            detail = "no samples yet"
        elif len(self._samples) < 3:
            detail = f"warming up ({len(self._samples)} samples)"
        elif vel > 0 and eta < float("inf"):
            detail = f"clearing in ~{eta:.0f}s at {vel:.4f} files/s"
        elif vel < 0:
            detail = f"growing at {abs(vel):.4f} files/s — needs attention"
        else:
            detail = f"stable at {count} files, no clear trend"

        return ForecastReport(
            pending_count=count,
            velocity=vel,
            eta_seconds=eta,
            pressure=pressure,
            trend_samples=len(self._samples),
            detail=detail,
        )

    # ── utilities ──────────────────────────────────────────────

    def clear(self) -> None:
        """drop all samples and start fresh."""
        self._samples.clear()

    def samples_as_list(self) -> List[Tuple[float, int]]:
        """return a copy of the sample buffer."""
        return list(self._samples)
