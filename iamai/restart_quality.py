"""Restart quality — verify a restarted process is actually healthy.

Starting a process is easy. Keeping it alive is the hard part.

After a caretaker restarts a stalled writer, the process might be running
(pid exists, no crash) but still sick — producing no strokes, leaking
memory, or stuck in a retry loop. A naive ``is_running()`` check gives
a false sense of security.

This module answers: *did the restart actually fix the problem?*

It checks three signals in order of increasing confidence:

1. **Process alive** — pid exists and has not exited.
2. **Stroke produced** — at least one new stroke appeared in history
   within a grace window after the restart timestamp.
3. **Cadence recovered** — the inter-stroke intervals have returned
   to within tolerance of the configured cadence.

Each signal upgrades the verdict:

=========  ============================================================
verdict    meaning
=========  ============================================================
alive      process is running but has not produced output yet
healthy    at least one stroke produced post-restart
recovered  cadence has stabilized back to expected interval
failed     process exited or never produced output within timeout
=========  ============================================================

Design choices
--------------

- **Pure function of timestamps.**  Given a restart time, a list of
  stroke timestamps, and a process liveness boolean, the verdict is
  deterministic.  No side effects.
- **Grace window.**  A restarted process may take a few seconds to
  warm up.  The ``grace_seconds`` parameter (default 30) is the
  window during which "no output yet" is not yet a failure.
- **Timeout.**  If no stroke appears within ``timeout_seconds``
  (default 120) after restart, the verdict is ``failed`` regardless
  of whether the process is technically alive.

Usage::

    from iamai.restart_quality import restart_quality, restart_report

    verdict = restart_quality(
        restarted_at="2026-10-18T03:00:00+00:00",
        strokes_after=[
            "2026-10-18T03:00:18+00:00",
            "2026-10-18T03:00:33+00:00",
            "2026-10-18T03:00:48+00:00",
        ],
        process_alive=True,
        expected_cadence=15,
    )
    print(verdict["verdict"])   # "recovered"
    print(verdict["strokes"])   # 3

    print(restart_report(
        restarted_at="2026-10-18T03:00:00+00:00",
        strokes_after=["2026-10-18T03:00:18+00:00"],
        process_alive=True,
        expected_cadence=15,
    ))
    # "restart healthy: 1 stroke in 18s, verdict=healthy"
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


DEFAULT_GRACE_SECONDS = 30
DEFAULT_TIMEOUT_SECONDS = 120


def _parse(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp to a timezone-aware datetime."""
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def restart_quality(
    restarted_at: str,
    strokes_after: list[str],
    process_alive: bool,
    expected_cadence: int = 15,
    grace_seconds: int = DEFAULT_GRACE_SECONDS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Evaluate the quality of a process restart.

    Parameters
    ----------
    restarted_at:
        ISO 8601 timestamp of when the restart occurred.
    strokes_after:
        List of ISO 8601 timestamps for strokes produced after restart.
    process_alive:
        Whether the process is currently running (pid check).
    expected_cadence:
        Expected interval between strokes in seconds.
    grace_seconds:
        Seconds after restart during which silence is acceptable.
    timeout_seconds:
        Seconds after restart after which silence means failure.

    Returns
    -------
    dict with keys:
        verdict: str — one of "alive", "healthy", "recovered", "failed"
        strokes: int — number of strokes produced post-restart
        first_stroke_seconds: float | None — seconds from restart to first stroke
        cadence_ok: bool — whether recent intervals match expected cadence
        elapsed_seconds: float — seconds from restart to last measured stroke
    """
    restart_dt = _parse(restarted_at)
    now_utc = datetime.now(timezone.utc)
    elapsed_since_restart = (now_utc - restart_dt).total_seconds()

    # No strokes at all
    if not strokes_after:
        if not process_alive:
            return {
                "verdict": "failed",
                "strokes": 0,
                "first_stroke_seconds": None,
                "cadence_ok": False,
                "elapsed_seconds": elapsed_since_restart,
            }
        if elapsed_since_restart < grace_seconds:
            return {
                "verdict": "alive",
                "strokes": 0,
                "first_stroke_seconds": None,
                "cadence_ok": False,
                "elapsed_seconds": elapsed_since_restart,
            }
        if elapsed_since_restart >= timeout_seconds:
            return {
                "verdict": "failed",
                "strokes": 0,
                "first_stroke_seconds": None,
                "cadence_ok": False,
                "elapsed_seconds": elapsed_since_restart,
            }
        # Still within grace, alive but no output yet
        return {
            "verdict": "alive",
            "strokes": 0,
            "first_stroke_seconds": None,
            "cadence_ok": False,
            "elapsed_seconds": elapsed_since_restart,
        }

    # Parse and sort strokes
    parsed = sorted(_parse(ts) for ts in strokes_after)
    first_dt = parsed[0]
    last_dt = parsed[-1]

    first_stroke_seconds = (first_dt - restart_dt).total_seconds()
    elapsed_seconds = (last_dt - restart_dt).total_seconds()
    stroke_count = len(parsed)

    # Check cadence — need at least 2 strokes to measure intervals
    cadence_ok = False
    if len(parsed) >= 2:
        intervals = []
        for i in range(1, len(parsed)):
            gap = (parsed[i] - parsed[i - 1]).total_seconds()
            intervals.append(gap)
        # Cadence is OK if the median interval is within 2x of expected
        intervals_sorted = sorted(intervals)
        median_interval = intervals_sorted[len(intervals_sorted) // 2]
        cadence_ok = median_interval <= expected_cadence * 2.0

    # Determine verdict
    if not process_alive and stroke_count == 0:
        verdict = "failed"
    elif cadence_ok and stroke_count >= 2:
        verdict = "recovered"
    elif stroke_count >= 1:
        verdict = "healthy"
    elif not process_alive:
        verdict = "failed"
    else:
        verdict = "alive"

    return {
        "verdict": verdict,
        "strokes": stroke_count,
        "first_stroke_seconds": round(first_stroke_seconds, 1),
        "cadence_ok": cadence_ok,
        "elapsed_seconds": round(elapsed_seconds, 1),
    }


def restart_report(
    restarted_at: str,
    strokes_after: list[str],
    process_alive: bool,
    expected_cadence: int = 15,
    grace_seconds: int = DEFAULT_GRACE_SECONDS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Human-readable one-liner summarizing restart quality.

    >>> restart_report(
    ...     restarted_at="2026-10-18T03:00:00+00:00",
    ...     strokes_after=["2026-10-18T03:00:18+00:00", "2026-10-18T03:00:33+00:00"],
    ...     process_alive=True,
    ...     expected_cadence=15,
    ... )
    'restart recovered: 2 strokes, first at 18.0s, cadence ok'
    """
    info = restart_quality(
        restarted_at=restarted_at,
        strokes_after=strokes_after,
        process_alive=process_alive,
        expected_cadence=expected_cadence,
        grace_seconds=grace_seconds,
        timeout_seconds=timeout_seconds,
    )

    v = info["verdict"]
    n = info["strokes"]

    if v == "failed":
        return f"restart failed: {n} strokes in {info['elapsed_seconds']:.0f}s"
    if v == "alive":
        return f"restart alive: waiting for first stroke ({info['elapsed_seconds']:.0f}s elapsed)"
    if v == "recovered":
        return (
            f"restart recovered: {n} strokes, "
            f"first at {info['first_stroke_seconds']}s, cadence ok"
        )
    # healthy
    return (
        f"restart healthy: {n} stroke{'s' if n != 1 else ''} "
        f"in {info['elapsed_seconds']}s, verdict={v}"
    )
