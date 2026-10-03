"""The batch gate: pure arithmetic deciding when a commit is allowed.

Separating this from the writer is the whole point of the new shape:

    writer  == continuous, tiny, no idea what git is
    gate    == periodic, one commit per window, describing what the writer did

Because `gate_open` takes `now` as an argument and never reads a clock, and
`subject` takes a tally and never touches git, both are testable on a machine with
no network -- which is the only kind of machine worth trusting at 3am.
"""

from __future__ import annotations

SUBJECT_LIMIT = 72


def gate_open(last_commit, now, interval: int, pending: int = 1) -> bool:
    """Is the commit window closed and is there anything to say?

    ``last_commit`` is None on the very first pass: there is no window to wait
    for, so the gate opens as soon as the writer has produced anything.
    """

    if interval <= 0:
        raise ValueError("interval must be a positive number of seconds")
    if not pending:
        return False
    if last_commit is None:
        return True
    return (now - last_commit) >= interval


def _window(seconds: int) -> str:
    minutes = max(1, round(int(seconds) / 60))
    return f"{minutes} min" if minutes != 1 else "1 min"


def window_tally(history, since_iso) -> dict:
    """Count history entries whose timestamp is after ``since_iso``.

    This is the only correct way to describe a batch: the writer keeps appending to
    one file, and the committer may have been started long before any of that
    happened. Anything reading a cached copy of the history will report silence.
    """

    out: dict[str, int] = {}
    for entry in history or ():
        if not isinstance(entry, dict):
            continue
        at, kind = entry.get("at"), entry.get("kind")
        if not isinstance(at, str) or not isinstance(kind, str):
            continue
        if since_iso is not None and at <= since_iso:
            continue
        out[kind] = out.get(kind, 0) + 1
    return out


def subject(tally: dict, window_seconds: int = 600, pending: int = 1) -> str:
    """One line describing a batch: which kinds of strokes, and how many.

    Items are ordered by count then name so the busiest work is visible first and
    two identical batches produce byte-identical subjects. When the line would be
    too long, whole items are dropped -- never half an item.
    """

    if not tally or not any(int(count) > 0 for _, count in tally.items()):
        # Silence is a claim about the world, so it is only allowed when nothing is
        # staged. Work sitting in the index with no counter behind it means the
        # bookkeeping broke, and the commit message has to say so.
        if int(pending) > 0:
            return f"batch: {int(pending)} file(s) changed, strokes unrecorded ({_window(window_seconds)})"
        return f"quiet batch: nothing new in {_window(window_seconds)}"

    ordered = sorted(tally.items(), key=lambda kv: (-int(kv[1]), str(kv[0])))
    items = [f"{name} x{count}" for name, count in ordered if int(count) > 0]

    suffix = f" ({_window(window_seconds)})"
    prefix = "batch: "
    full = prefix + ", ".join(items) + suffix
    if len(full) <= SUBJECT_LIMIT:
        return full

    kept: list[str] = []
    for item in items:
        trial = kept + [item]
        dropped = len(items) - len(trial)
        candidate = prefix + ", ".join(trial) + (f", more x{dropped}" if dropped else "")
        if len(candidate) > SUBJECT_LIMIT:
            break
        kept = trial
    if not kept:  # a single item longer than the limit: keep it, clipped to length
        kept = [items[0]]
    dropped = len(items) - len(kept)
    line = prefix + ", ".join(kept) + (f", more x{dropped}" if dropped else "")
    return line[:SUBJECT_LIMIT]
