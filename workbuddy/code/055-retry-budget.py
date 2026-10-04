"""055 — retry-budget: why "every ten minutes" becomes "one thick envelope".

window 175 took 21m22s: six attempts, each waiting ~135s for a port that
wasn't answering. two axes tell the story — the WINDOW breached the cadence
(1282s = 2.14 cadences, beyond batching) while the WRITER stayed alive
(five pieces written during the outage). the envelope got thicker, not lost.

>>> plan = budget(attempts=6, per_attempt=135.0, pause=0.0)
>>> plan['worst']
810.0
>>> will_finish(deadline=600.0, attempts=6, per_attempt=135.0)
False
>>> cadence_absorbed(cadence=600, window=900)
True
>>> cadence_absorbed(cadence=600, window=1282)
False
>>> diagnose(window=1282.0, writer_gap=5.0)
'late but alive: the envelope got thicker, not lost'
>>> diagnose(window=540.0, writer_gap=3000.0)
'punctual but empty: the mail ran, the writer didn't'
"""

from __future__ import annotations


def budget(attempts: int, per_attempt: float, pause: float = 0.0) -> dict:
    """Worst-case and best-case wall time of a retry loop.

    worst = every attempt times out fully; best = first attempt succeeds
    fast (success can be quick, so best is just the pauses in between).

    >>> budget(3, 10.0)['worst']
    30.0
    >>> budget(3, 10.0, pause=2.0)['worst']
    34.0
    >>> budget(3, 10.0, pause=2.0)['best']
    4.0
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    if per_attempt <= 0 or pause < 0:
        raise ValueError("per_attempt must be > 0, pause >= 0")
    worst = attempts * per_attempt + (attempts - 1) * pause
    best = (attempts - 1) * pause
    return {"worst": worst, "best": best}


def will_finish(deadline: float, attempts: int, per_attempt: float) -> bool:
    """True if the worst-case retry loop still fits inside the deadline.

    >>> will_finish(deadline=100.0, attempts=2, per_attempt=60.0)
    False
    >>> will_finish(deadline=120.0, attempts=2, per_attempt=60.0)
    True
    """
    if deadline <= 0:
        raise ValueError("deadline must be > 0")
    return attempts * per_attempt <= deadline


def cadence_absorbed(cadence: float, window: float, limit: float = 1.5) -> bool:
    """True if an over-long window still counts as 'the cadence, absorbed'.

    a window may exceed the cadence (network batching) without meaning
    the loop died — up to `limit` cadences of overrun. beyond that,
    the window breached, whatever the reason.

    >>> cadence_absorbed(cadence=600, window=620)
    True
    >>> cadence_absorbed(cadence=600, window=900)
    True
    >>> cadence_absorbed(cadence=600, window=901)
    False
    """
    if cadence <= 0 or window <= 0:
        raise ValueError("cadence and window must be > 0")
    return window <= cadence * limit


def diagnose(window: float, writer_gap: float, cadence: float = 600.0,
             limit: float = 1.5) -> str:
    """Two-axis verdict: the push window vs the writer's output gap.

    window 175: window 1282s (breached), writer_gap ~5s (alive throughout)
    -> 'late but alive'. the twin of the two-kinds-of-silence law: a late
    window is git-silence; an empty writer is filesystem-silence. they
    fail independently.

    >>> diagnose(window=540.0, writer_gap=60.0)
    'healthy'
    >>> diagnose(window=800.0, writer_gap=60.0)
    'late but alive: the envelope got thicker, not lost'
    >>> diagnose(window=540.0, writer_gap=1800.0)
    "punctual but empty: the mail ran, the writer didn't"
    >>> diagnose(window=1800.0, writer_gap=1800.0)
    'dark: both axes silent, check everything'
    """
    window_ok = cadence_absorbed(cadence, window, limit)
    writer_ok = writer_gap <= cadence
    if window_ok and writer_ok:
        return "healthy"
    if not window_ok and writer_ok:
        return "late but alive: the envelope got thicker, not lost"
    if window_ok and not writer_ok:
        return "punctual but empty: the mail ran, the writer didn't"
    return "dark: both axes silent, check everything"


if __name__ == "__main__":
    import doctest

    failures = doctest.testmod(verbose=False).failed
    print("window 175 ->", diagnose(window=1282.0, writer_gap=5.0))
    raise SystemExit(1 if failures else 0)
