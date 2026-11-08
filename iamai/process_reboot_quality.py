"""process_reboot_quality — evaluate how well a process reboot went.

A reboot is the moment one process dies and another takes its place.
restart_smoothness answers "how fast did cadence recover?"  This module
answers a different question: "was the transition *clean*?"

A clean reboot means:

- no strokes were lost (or the loss is within the expected gap budget)
- no strokes were duplicated (two processes running simultaneously)
- the post-reboot cadence matches the expected interval
- the stroke sequence has no discontinuities beyond the one expected gap

Public API::

    from iamai.process_reboot_quality import RebootQuality, reboot_quality_report

    rq = RebootQuality(
        pre_strokes=pre,         # strokes before reboot (timestamps)
        post_strokes=post,       # strokes after reboot (timestamps)
        expected_interval=15,
        reboot_time=t_reboot,    # when the new process started
    )
    s = rq.summary()
    # {"loss_ratio": 0.0, "overlap_s": 0.0, "cadence_drift": 0.02,
    #  "sequence_gap": 1, "verdict": "clean"}

    print(reboot_quality_report(pre, post, expected_interval=15,
                                reboot_time=t_reboot))
    # "reboot: 0 lost strokes, 0s overlap, 2% cadence drift — clean"

Quality model
-------------

Four signals are combined into a verdict:

==================  ========================================================
signal              what it measures
==================  ========================================================
loss_ratio          fraction of expected strokes that never appeared
overlap_s           seconds where both old and new process were writing
cadence_drift       how far the post-reboot mean interval deviates from expected
sequence_gap        number of missing sequence numbers at the boundary
==================  ========================================================

**Verdict** is a single word that summarizes the transition::

============  ===========  =============================================
score range   verdict      meaning
============  ===========  =============================================
≥ 0.85        clean        seamless handoff, negligible loss
≥ 0.65        acceptable   minor imperfections, nothing actionable
≥ 0.40        rough        significant loss or overlap detected
≥ 0.20        degraded     multiple signals indicate problems
< 0.20        broken       the reboot caused data loss or corruption
============  ===========  =============================================

Why this matters
----------------

The IamAI repo runs as an autonomous writer that gets killed and restarted
by caretaker visits.  Every restart is a risk: strokes can be lost if the
old process died mid-write, or duplicated if the new one started before
the old one stopped.  This module lets the caretaker quantify whether
the restart was safe, not just whether it happened.
"""

from __future__ import annotations

from statistics import mean
from typing import Any, Dict, List, Optional


class RebootQuality:
    """Evaluate the quality of a process reboot transition.

    Parameters
    ----------
    pre_strokes : list of float
        Timestamps of strokes produced by the old process (sorted ascending).
    post_strokes : list of float
        Timestamps of strokes produced by the new process (sorted ascending).
    expected_interval : float
        Configured seconds between strokes (default 15).
    reboot_time : float, optional
        When the new process was started.  If not given, the first
        post-stroke timestamp minus one interval is used as estimate.
    """

    def __init__(
        self,
        pre_strokes: List[float],
        post_strokes: List[float],
        expected_interval: float = 15.0,
        reboot_time: Optional[float] = None,
    ) -> None:
        self._pre = sorted(pre_strokes)
        self._post = sorted(post_strokes)
        self._interval = expected_interval
        self._reboot_time = reboot_time
        if self._reboot_time is None and self._post:
            self._reboot_time = self._post[0] - self._interval

    # ------------------------------------------------------------------
    # Core signals
    # ------------------------------------------------------------------

    @property
    def loss_ratio(self) -> float:
        """Fraction of expected strokes that were never produced.

        Computed as::

            expected_count = floor(downtime / interval)
            loss_ratio = max(0, (expected_count - actual_post_count)) / expected_count

        A reboot that loses zero strokes scores 0.0 (best).  A reboot
        that loses all expected strokes scores 1.0 (worst).
        """
        if not self._pre or not self._post or self._reboot_time is None:
            return 0.0

        last_pre = self._pre[-1]
        first_post = self._post[0]
        downtime = max(0.0, first_post - last_pre)
        expected_count = max(1, int(downtime / self._interval))
        # the first post-stroke "replaces" the one that was due
        actual_count = len(self._post)
        lost = max(0, expected_count - actual_count)
        return lost / expected_count

    @property
    def overlap_s(self) -> float:
        """Seconds where both processes were producing strokes.

        If the last pre-stroke is *after* the first post-stroke, the
        processes overlapped.  The overlap duration is estimated as
        the time between first post-stroke and last pre-stroke.
        """
        if not self._pre or not self._post:
            return 0.0
        last_pre = self._pre[-1]
        first_post = self._post[0]
        if last_pre > first_post:
            return last_pre - first_post
        return 0.0

    @property
    def cadence_drift(self) -> float:
        """Absolute fractional deviation of post-reboot mean interval.

        A value of 0.0 means the post-reboot cadence matches exactly.
        A value of 0.1 means the mean interval is 10% off from expected.
        """
        if len(self._post) < 2:
            return 0.0
        intervals = [
            self._post[i + 1] - self._post[i]
            for i in range(len(self._post) - 1)
        ]
        m = mean(intervals)
        if self._interval == 0:
            return 0.0
        return abs(m - self._interval) / self._interval

    @property
    def sequence_gap(self) -> int:
        """Estimated missing strokes at the reboot boundary.

        Uses the time gap between the last pre-stroke and first
        post-stroke to estimate how many strokes should have happened
        but did not.  Returns 0 for a perfect handoff.
        """
        if not self._pre or not self._post:
            return 0
        gap = self._post[0] - self._pre[-1]
        expected_in_gap = max(0, int(gap / self._interval) - 1)
        return max(0, expected_in_gap)

    @property
    def post_stroke_count(self) -> int:
        """Total strokes produced by the new process."""
        return len(self._post)

    @property
    def pre_stroke_count(self) -> int:
        """Total strokes produced by the old process."""
        return len(self._pre)

    @property
    def downtime_s(self) -> float:
        """Seconds between last pre-stroke and first post-stroke."""
        if not self._pre or not self._post:
            return 0.0
        return max(0.0, self._post[0] - self._pre[-1])

    # ------------------------------------------------------------------
    # Verdict
    # ------------------------------------------------------------------

    @property
    def verdict(self) -> str:
        """Overall reboot quality verdict."""
        score = self._compute_score()
        if score >= 0.85:
            return "clean"
        if score >= 0.65:
            return "acceptable"
        if score >= 0.40:
            return "rough"
        if score >= 0.20:
            return "degraded"
        return "broken"

    def _compute_score(self) -> float:
        """Compute composite score in [0, 1]."""
        # loss component: 1.0 if no loss, 0.0 if all lost
        loss_score = 1.0 - min(1.0, self.loss_ratio)

        # overlap component: 1.0 if no overlap, decays with overlap duration
        # 60s of overlap → 0.0 (two writers for a full minute is bad)
        overlap_score = max(0.0, 1.0 - self.overlap_s / 60.0)

        # cadence component: 1.0 if <5% drift, 0.0 if >50% drift
        drift_score = max(0.0, min(1.0, (0.50 - self.cadence_drift) / 0.45))

        # gap component: 1.0 if 0 missing, decays with more
        gap_score = max(0.0, 1.0 - self.sequence_gap * 0.1)

        # weighted: loss is the most important signal
        return (
            0.35 * loss_score
            + 0.20 * overlap_score
            + 0.25 * drift_score
            + 0.20 * gap_score
        )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        """Return a dict of all reboot quality metrics."""
        return {
            "loss_ratio": round(self.loss_ratio, 3),
            "overlap_s": round(self.overlap_s, 1),
            "cadence_drift": round(self.cadence_drift, 3),
            "sequence_gap": self.sequence_gap,
            "downtime_s": round(self.downtime_s, 1),
            "pre_stroke_count": self.pre_stroke_count,
            "post_stroke_count": self.post_stroke_count,
            "verdict": self.verdict,
        }


def reboot_quality_report(
    pre_strokes: List[float],
    post_strokes: List[float],
    expected_interval: float = 15.0,
    reboot_time: Optional[float] = None,
) -> str:
    """One-line human-readable reboot quality report."""
    rq = RebootQuality(pre_strokes, post_strokes, expected_interval, reboot_time)
    s = rq.summary()
    lost = int(round(s["loss_ratio"] * s.get("pre_stroke_count", 0)))
    overlap = int(s["overlap_s"])
    drift_pct = int(s["cadence_drift"] * 100)
    return (
        f"reboot: {lost} lost strokes, {overlap}s overlap, "
        f"{drift_pct}% cadence drift — {s['verdict']}"
    )
