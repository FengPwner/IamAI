"""restart_smoothness — measure how cleanly a process recovers after restart.

A restart is not just "did the process come back?" but "how fast did it
settle into its normal rhythm?"  A process that starts but takes five
minutes to produce its first stroke is technically alive but functionally
dead for those five minutes.  A process that restarts cleanly produces
its first stroke within one cadence interval and stabilizes within three.

Public API::

    from iamai.restart_smoothness import RestartSmoothness, smoothness_report

    rs = RestartSmoothness(stroke_times, expected_interval=15)
    s = rs.summary()
    # {"warmup_s": 18.3, "first_stroke_ok": True, "settle_strokes": 3,
    #  "gap_loss_s": 42.1, "grade": "smooth"}

    print(smoothness_report(stroke_times, expected_interval=15))
    # "restart: warmup 18s, settled in 3 strokes, 42s gap loss — smooth"

Smoothness model
----------------

After a restart, the recovery has three phases:

============  ============  ============================================
phase         duration      what happens
============  ============  ============================================
warmup        start→1st     process initializes, loads state, writes
settle        1st→stable    intervals converge to expected cadence
steady        stable→∞      normal operation, jitter within bounds
============  ============  ============================================

**Warmup time** is the seconds between process start and first stroke.
A warmup under 1× expected interval is fast; under 2× is acceptable;
over 4× is slow; over 8× is pathological.

**Settle strokes** counts how many strokes it takes for the rolling
average interval to come within 20% of the expected interval.  Fewer
is better; 1-3 is smooth, 4-7 is rough, 8+ is unstable.

**Gap loss** is the total seconds between the last pre-restart stroke
and the first post-restart stroke, minus the expected interval.  It
measures how much productive time was lost to the restart itself.

**Grade** combines all three signals::

============  ===========  ============================================
score range   grade        meaning
============  ===========  ============================================
≥ 0.85        smooth       fast warmup, quick settle, minimal loss
≥ 0.65        acceptable   minor delays, normal settle
≥ 0.40        rough        slow warmup or long settle
≥ 0.20        slow         significant recovery overhead
< 0.20        painful      restart took longer than it should have
============  ===========  ============================================
"""

from __future__ import annotations

from statistics import mean, stdev
from typing import Any, Dict, List, Optional


class RestartSmoothness:
    """Analyze restart recovery from a sequence of stroke timestamps.

    Parameters
    ----------
    stroke_times : list of float
        Unix timestamps of strokes, sorted ascending.  The restart point
        is detected as the largest gap in the sequence.
    expected_interval : float
        The configured seconds between strokes (default 15).
    restart_time : float, optional
        Explicit restart timestamp.  If not given, the largest gap is
        used to infer the restart point.
    """

    def __init__(
        self,
        stroke_times: List[float],
        expected_interval: float = 15.0,
        restart_time: Optional[float] = None,
    ) -> None:
        self._times = sorted(stroke_times)
        self._interval = expected_interval
        self._restart_time = restart_time
        self._post: List[float] = []
        self._pre_last: Optional[float] = None
        self._detect_restart()

    # ------------------------------------------------------------------
    # Restart detection
    # ------------------------------------------------------------------

    def _detect_restart(self) -> None:
        """Find the restart boundary in the stroke sequence."""
        if len(self._times) < 2:
            self._post = list(self._times)
            return

        if self._restart_time is not None:
            self._post = [t for t in self._times if t >= self._restart_time]
            pre = [t for t in self._times if t < self._restart_time]
            self._pre_last = pre[-1] if pre else None
            return

        # find the largest gap — that is almost certainly the restart
        max_gap = 0.0
        max_idx = 0
        for i in range(1, len(self._times)):
            gap = self._times[i] - self._times[i - 1]
            if gap > max_gap:
                max_gap = gap
                max_idx = i

        # only treat as restart if gap exceeds 2× expected interval
        if max_gap > self._interval * 2:
            self._pre_last = self._times[max_idx - 1]
            self._post = self._times[max_idx:]
        else:
            # no restart detected — treat entire sequence as post
            self._post = list(self._times)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @property
    def warmup_s(self) -> float:
        """Seconds from restart to first post-restart stroke."""
        if not self._post:
            return float("inf")
        anchor = self._restart_time or (
            self._pre_last + self._interval if self._pre_last else self._post[0]
        )
        return max(0.0, self._post[0] - anchor)

    @property
    def first_stroke_ok(self) -> bool:
        """Whether the first stroke arrived within 2× expected interval."""
        return self.warmup_s <= self._interval * 2

    @property
    def settle_strokes(self) -> int:
        """Number of strokes before intervals stabilize within 20% of expected."""
        if len(self._post) < 2:
            return len(self._post)

        threshold = self._interval * 0.2
        window = max(3, min(5, len(self._post) - 1))

        for i in range(window, len(self._post)):
            recent = self._post[i - window : i + 1]
            intervals = [
                recent[j + 1] - recent[j] for j in range(len(recent) - 1)
            ]
            avg = mean(intervals)
            if abs(avg - self._interval) <= threshold:
                return i - window + 1

        # never settled within the available data
        return len(self._post) - 1

    @property
    def gap_loss_s(self) -> float:
        """Productive seconds lost between last pre-restart and first post stroke."""
        if self._pre_last is None or not self._post:
            return 0.0
        actual_gap = self._post[0] - self._pre_last
        return max(0.0, actual_gap - self._interval)

    @property
    def post_stroke_count(self) -> int:
        """Total strokes produced after restart."""
        return len(self._post)

    @property
    def post_interval_mean(self) -> float:
        """Mean interval between post-restart strokes."""
        if len(self._post) < 2:
            return float("inf")
        intervals = [
            self._post[i + 1] - self._post[i]
            for i in range(len(self._post) - 1)
        ]
        return mean(intervals)

    @property
    def post_interval_jitter(self) -> float:
        """Coefficient of variation of post-restart intervals."""
        if len(self._post) < 3:
            return float("inf")
        intervals = [
            self._post[i + 1] - self._post[i]
            for i in range(len(self._post) - 1)
        ]
        m = mean(intervals)
        if m == 0:
            return float("inf")
        return stdev(intervals) / m

    # ------------------------------------------------------------------
    # Grade
    # ------------------------------------------------------------------

    @property
    def grade(self) -> str:
        """Overall smoothness grade."""
        score = self._compute_score()
        if score >= 0.85:
            return "smooth"
        if score >= 0.65:
            return "acceptable"
        if score >= 0.40:
            return "rough"
        if score >= 0.20:
            return "slow"
        return "painful"

    def _compute_score(self) -> float:
        """Compute composite score in [0, 1]."""
        # warmup component: 1.0 if instant, 0.0 if >= 8× interval
        w = max(0.0, 1.0 - self.warmup_s / (self._interval * 8))

        # settle component: 1.0 if 1 stroke, decays with more
        s_count = self.settle_strokes
        s = max(0.0, 1.0 - (s_count - 1) * 0.1)

        # gap loss component: 1.0 if no loss, decays with more
        max_loss = self._interval * 20  # 5 minutes at 15s cadence
        g = max(0.0, 1.0 - self.gap_loss_s / max_loss)

        # jitter component: 1.0 if CV < 0.3, 0.0 if CV > 1.0
        jitter = self.post_interval_jitter
        if jitter == float("inf"):
            j = 0.5  # not enough data
        else:
            j = max(0.0, min(1.0, (1.0 - jitter) / 0.7))

        # weighted combination
        return 0.30 * w + 0.25 * s + 0.25 * g + 0.20 * j

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        """Return a dict of all smoothness metrics."""
        return {
            "warmup_s": round(self.warmup_s, 1),
            "first_stroke_ok": self.first_stroke_ok,
            "settle_strokes": self.settle_strokes,
            "gap_loss_s": round(self.gap_loss_s, 1),
            "post_stroke_count": self.post_stroke_count,
            "post_interval_mean": round(self.post_interval_mean, 1)
            if self.post_interval_mean != float("inf")
            else None,
            "post_interval_jitter": round(self.post_interval_jitter, 2)
            if self.post_interval_jitter != float("inf")
            else None,
            "grade": self.grade,
        }


def smoothness_report(
    stroke_times: List[float],
    expected_interval: float = 15.0,
    restart_time: Optional[float] = None,
) -> str:
    """One-line human-readable restart smoothness report."""
    rs = RestartSmoothness(stroke_times, expected_interval, restart_time)
    s = rs.summary()
    warmup = "inf" if s["warmup_s"] == float("inf") else str(int(s["warmup_s"]))
    settle = s["settle_strokes"]
    loss = "inf" if s["gap_loss_s"] == float("inf") else str(int(s["gap_loss_s"]))
    return (
        f"restart: warmup {warmup}s, settled in {settle} strokes, "
        f"{loss}s gap loss — {s['grade']}"
    )
