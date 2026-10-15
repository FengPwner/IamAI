"""Topic drift — has the writer's behaviour shifted?

``stroke_entropy`` asks *how varied* the recent window is; this module
asks *how different* two consecutive windows are.  A writer that slowly
narrows from six stroke kinds down to two is not necessarily broken —
it may just be in a focused phase — but a caretaker should notice.

Three public functions:

- ``kind_distribution(strokes_path, window)`` — relative frequency of
  each kind in the most recent *window* strokes (a normalised Counter).
- ``drift(before, after)`` — Jensen-Shannon divergence between two
  distributions, returned as a float in [0, 1] and a human label.
- ``drift_report(repo, window)`` — end-to-end one-liner comparing
  strokes [window+1 .. 2*window] against strokes [1 .. window].

Scale (Jensen-Shannon divergence, base-2, in bits):

==========  =================================================
verdict     meaning
==========  =================================================
``stable``  JSD < 0.05 — distributions are nearly identical
``shift``   JSD < 0.20 — noticeable but not alarming
``drift``   JSD ≥ 0.20 — significant behavioural change
==========  =================================================
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

def _load_kinds(strokes_path: Path, window: int, offset: int = 0) -> list[str]:
    """Read ``kind`` from the last *window + offset* lines, return the
    slice ``[-(window+offset) : -offset]`` (or ``[-window:]`` when offset=0).

    Seeks from the end so large files stay cheap.
    """
    if not strokes_path.exists():
        return []
    total_needed = window + offset
    with strokes_path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        if size == 0:
            return []
        chunk = min(size, total_needed * 512)
        fh.seek(-chunk, 2)
        raw = fh.read().decode("utf-8", errors="replace")
    kinds: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        kinds.append(rec.get("kind", "unknown"))
    tail = kinds[-total_needed:]
    if offset == 0:
        return tail[-window:]
    return tail[:window]


def _normalise(counter: Counter) -> dict[str, float]:
    """Convert a Counter to a probability distribution (dict)."""
    total = sum(counter.values())
    if total == 0:
        return {}
    return {k: v / total for k, v in counter.items()}


def _jsd(p: dict[str, float], q: dict[str, float]) -> float:
    """Jensen-Shannon divergence (base 2) between two distributions.

    Returns a value in [0, 1] where 0 means identical and 1 means
    maximally different (no shared support).
    """
    if not p and not q:
        return 0.0
    universe = set(p) | set(q)
    if not universe:
        return 0.0
    m: dict[str, float] = {}
    for k in universe:
        pk = p.get(k, 0.0)
        qk = q.get(k, 0.0)
        m[k] = (pk + qk) / 2.0

    def _kl(a: dict[str, float], b: dict[str, float]) -> float:
        total = 0.0
        for k in a:
            ak = a.get(k, 0.0)
            bk = b.get(k, 0.0)
            if ak > 0 and bk > 0:
                total += ak * math.log2(ak / bk)
        return total

    return (_kl(p, m) + _kl(q, m)) / 2.0


def _classify(jsd_value: float) -> str:
    if jsd_value < 0.05:
        return "stable"
    if jsd_value < 0.20:
        return "shift"
    return "drift"


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def kind_distribution(
    strokes_path: Path | str,
    window: int = 30,
) -> dict[str, float]:
    """Relative frequency of each kind in the last *window* strokes."""
    strokes_path = Path(strokes_path)
    kinds = _load_kinds(strokes_path, window)
    return _normalise(Counter(kinds))


def drift(
    before: dict[str, float],
    after: dict[str, float],
) -> dict:
    """Jensen-Shannon divergence between two kind distributions.

    Returns ``{"jsd": float, "verdict": str, "before_keys": int,
    "after_keys": int, "shared_keys": int}``.
    """
    jsd_value = _jsd(before, after)
    return {
        "jsd": round(jsd_value, 4),
        "verdict": _classify(jsd_value),
        "before_keys": len(before),
        "after_keys": len(after),
        "shared_keys": len(set(before) & set(after)),
    }


def drift_report(
    repo: Path | str | None = None,
    window: int = 30,
) -> str:
    """One-liner comparing the two most recent *window*-stroke blocks.

    "before" = strokes [2*window .. window+1] from the end (older).
    "after"  = strokes [window .. 1] from the end (newer).
    """
    if repo is None:
        repo = Path(__file__).resolve().parent.parent
    repo = Path(repo)
    strokes_path = repo / "data" / "strokes.jsonl"

    newer_kinds = _load_kinds(strokes_path, window, offset=0)
    older_kinds = _load_kinds(strokes_path, window, offset=window)

    before = _normalise(Counter(older_kinds))
    after = _normalise(Counter(newer_kinds))
    info = drift(before, after)

    return (
        f"{info['verdict']} — JSD {info['jsd']:.4f} "
        f"({info['before_keys']} kinds → {info['after_keys']} kinds, "
        f"{info['shared_keys']} shared)"
    )
