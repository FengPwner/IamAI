"""Heartbeat: is the writer still writing?

The dangerous failure of a repository that writes itself is not a bug. A bug shows
up as a red test. The dangerous one is **silence** -- the process gets reaped, the
loop dies, and the commit history simply stops, which is indistinguishable from a
quiet ten minutes unless somebody is measuring.

So this module answers one question with arithmetic: how long has it been since the
last stroke, and is that longer than the writer's own cadence allows?

Pure functions throughout -- ``report()`` takes ``now`` as an argument so a stall
can be tested without waiting for one.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_HISTORY_FILE = REPO_ROOT / "data" / "writer_state.json"


def state_file(writer_id=None, root=None):
    """Where THIS writer keeps its bookkeeping.

    Reading the wrong file is what made the probe cry wolf: after state went
    per-writer, the heartbeat kept watching the abandoned shared file and reported a
    permanent STALL. A probe must be pointed at the live source.
    """

    from .writer import States

    data_dir = (Path(root) if root else REPO_ROOT) / "data"
    state = States(writer_id=writer_id, root=root)
    if state.path.exists():
        return state.path
    legacy = data_dir / "writer_state.json"
    return legacy if legacy.exists() else state.path


def _parse(moment: str) -> datetime | None:
    if not isinstance(moment, str) or not moment.strip():
        return None
    try:
        parsed = datetime.fromisoformat(moment.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _as_time(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return _parse(value)


def load_history(path=None, writer_id=None, root=None) -> list[dict]:
    """The writer's own stroke log, newest last. Missing file means 'not started'."""

    file = Path(path) if path else state_file(writer_id=writer_id, root=root)
    if not file.exists():
        return []
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    history = raw.get("history") if isinstance(raw, dict) else None
    return history if isinstance(history, list) else []


def report(
    history,
    since,
    interval: int,
    now,
    every: int | None = None,
    started=None,
) -> dict:
    """Summarise strokes after ``since`` as of ``now``.

    ``interval`` is the commit window (seconds) and ``every`` the stroke cadence
    (seconds). A stall is only claimable when both the cadence and at least one
    recorded stroke exist: with no history there is nothing to compare against, and
    reporting a stall would be a guess.
    """

    lower = _as_time(since) if since is not None else None
    moment = _as_time(now)
    if moment is None:
        raise ValueError("report() needs a parseable 'now'")

    rows: list[tuple[datetime, dict]] = []
    for entry in history or ():
        if not isinstance(entry, dict):
            continue
        at = _as_time(entry.get("at"))
        kind = entry.get("kind")
        if at is None or not isinstance(kind, str):
            continue
        if lower is not None and at <= lower:
            continue
        rows.append((at, entry))
    rows.sort(key=lambda item: item[0])

    kinds: dict[str, int] = {}
    paths: list[str] = []
    for _, entry in rows:
        kinds[entry["kind"]] = kinds.get(entry["kind"], 0) + 1
        path = entry.get("path")
        if isinstance(path, str) and path not in paths:
            paths.append(path)

    stamps = [at for at, _ in rows]
    max_gap = 0.0
    for earlier, later in zip(stamps, stamps[1:]):
        gap = (later - earlier).total_seconds()
        max_gap = max(max_gap, gap)

    last = stamps[-1] if stamps else None
    first = stamps[0] if stamps else None
    gap_seconds = (moment - last).total_seconds() if last else 0.0

    reference = last if last is not None else _as_time(started)
    stalled = bool(every) and reference is not None and gap_seconds > 2 * float(every)

    return {
        "strokes": len(rows),
        "kinds": dict(sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))),
        "paths": paths,
        "first": first.isoformat() if first else None,
        "last": last.isoformat() if last else None,
        "max_gap_seconds": round(max_gap, 1),
        "gap_seconds": round(gap_seconds, 1),
        "stalled": stalled,
        "interval": int(interval),
        "every": every,
    }


def as_markdown(rep: dict) -> str:
    """One line. Fits in a devlog row or a commit body without a second thought."""

    if not rep.get("strokes"):
        head = "0 strokes"
    else:
        kinds = ", ".join(f"{k} x{v}" for k, v in rep["kinds"].items())
        head = f"{rep['strokes']} strokes ({kinds})"
    line = f"{head}, gap {rep['gap_seconds']:.0f}s, longest gap {rep['max_gap_seconds']:.0f}s"
    if rep.get("legacy_source"):
        line += f" [reading legacy {rep['source'].split('/')[-1]}]"
    if rep.get("stalled"):
        line += " -- STALL: writer silent past 2x its cadence"
    return line


def beat(interval: int = 600, every: int | None = 15, path=None, writer_id=None, root=None) -> dict:
    """Read the log and answer now. This is the only part that touches the clock."""

    file = Path(path) if path else state_file(writer_id=writer_id, root=root)
    history = load_history(path, writer_id=writer_id, root=root)
    started = None
    if file.exists():
        try:
            started = json.loads(file.read_text(encoding="utf-8")).get("started")
        except (ValueError, OSError):
            started = None
    now = datetime.now(timezone.utc)
    rep = report(
        history,
        since=None,
        interval=interval,
        now=now,
        every=every,
        started=started,
    )
    # 说清读的是谁的文件：没有 writer_state.doubao.json 时会退回共享旧文件，
    # 那份历史其实是改名前所有写手共用的，不标出来就会被读成"某个写手很勤快"。
    rep["source"] = str(file)
    rep["legacy_source"] = file.name == "writer_state.json"
    return rep
