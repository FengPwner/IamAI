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
    warmup_until=None,
) -> dict:
    """Summarise strokes after ``since`` as of ``now``.

    ``interval`` is the commit window (seconds) and ``every`` the stroke cadence
    (seconds). A stall is only claimable when both the cadence and at least one
    recorded stroke exist: with no history there is nothing to compare against, and
    reporting a stall would be a guess.

    ``warmup_until`` suppresses stall detection inside a window after a process
    restart.  The heartbeat reads the last stroke timestamp from the writer state
    file; after a reclamation and restart, that timestamp predates the death and
    the gap to ``now`` is always larger than 2x cadence.  Passing the restart
    time plus a grace period (e.g. ``warmup_until=restart_time + timedelta(seconds=60)``)
    keeps the stall detector quiet until the writer has had a chance to produce
    its first post-restart stroke.  Once ``now`` passes ``warmup_until``, normal
    arithmetic resumes — a stall that begins after the warmup window fires as
    expected.
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

    # Suppress stall inside the warmup window: a just-restarted writer has not
    # had time to produce its first stroke yet, and the gap from the last
    # pre-death stroke to now is always going to look like a stall.
    warmup_active = False
    if warmup_until is not None and stalled:
        deadline = _as_time(warmup_until)
        if deadline is not None and moment < deadline:
            stalled = False
            warmup_active = True

    return {
        "strokes": len(rows),
        "kinds": dict(sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))),
        "paths": paths,
        "first": first.isoformat() if first else None,
        "last": last.isoformat() if last else None,
        "max_gap_seconds": round(max_gap, 1),
        "gap_seconds": round(gap_seconds, 1),
        "stalled": stalled,
        "warmup_active": warmup_active,
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


def cadence(history: list[dict], every: int = 15) -> dict:
    """Measure how regular the stroke intervals are.

    A stall is binary: the writer stopped or it didn't. Cadence is the gradient
    before that -- the writer might still be producing strokes but at half speed,
    which means something is wrong but the stall detector hasn't fired yet.

    Returns the mean interval, standard deviation, and a jitter score (0 = perfect
    clock, 1 = intervals vary by 100% of the expected cadence). Pure arithmetic,
    no clock reading -- the timestamps come from the history entries.
    """

    stamps: list[datetime] = []
    for entry in history or ():
        if not isinstance(entry, dict):
            continue
        at = _as_time(entry.get("at"))
        if at is not None:
            stamps.append(at)
    stamps.sort()

    if len(stamps) < 2:
        return {
            "count": len(stamps),
            "mean_interval": 0.0,
            "std_interval": 0.0,
            "jitter": 0.0,
            "every": every,
            "degraded": False,
        }

    gaps = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:])]
    mean_gap = sum(gaps) / len(gaps)
    variance = sum((g - mean_gap) ** 2 for g in gaps) / len(gaps)
    std_gap = variance ** 0.5
    jitter = std_gap / every if every > 0 else 0.0

    return {
        "count": len(stamps),
        "mean_interval": round(mean_gap, 1),
        "std_interval": round(std_gap, 1),
        "jitter": round(jitter, 3),
        "every": every,
        "degraded": jitter > 1.0 or mean_gap > every * 2,
    }


def health_check(
    cadence_result: dict,
    gap_seconds: float = 0.0,
) -> dict:
    """Classify a writer's health into one of four states from cadence signals.

    Takes a cadence() result and the current gap since last stroke, and
    returns a health verdict:

    - ``healthy``: low jitter, mean close to expected cadence
    - ``degraded``: elevated jitter or mean drifting, but still producing
    - ``dying``: mean interval > 2× expected and max_gap rising
    - ``dead``: no strokes at all, or gap exceeds 4× expected cadence

    The boundary between dying and dead is the gap: a writer can have
    terrible cadence numbers yet still be alive if it produced a stroke
    recently. The gap is what tells you whether the writer is *still*
    running or merely left behind bad numbers on its way out.

    Returns a dict with ``status``, ``confidence`` (0.0–1.0), and
    ``reason`` explaining the verdict.
    """
    every = cadence_result.get("every", 15)
    count = cadence_result.get("count", 0)
    mean_interval = cadence_result.get("mean_interval", 0.0)
    jitter = cadence_result.get("jitter", 0.0)

    if count < 2:
        return {
            "status": "dead" if gap_seconds > every * 4 else "degraded",
            "confidence": 0.5,
            "reason": f"too few strokes ({count}) to assess cadence",
        }

    if gap_seconds > every * 4:
        return {
            "status": "dead",
            "confidence": 0.95,
            "reason": f"gap {gap_seconds:.0f}s exceeds 4× cadence ({every * 4}s)",
        }

    if mean_interval > every * 2 and gap_seconds > every * 2:
        return {
            "status": "dying",
            "confidence": 0.85,
            "reason": (
                f"mean interval {mean_interval:.1f}s > 2× expected ({every * 2}s) "
                f"and gap {gap_seconds:.0f}s still growing"
            ),
        }

    if jitter > 1.0 or mean_interval > every * 1.5:
        return {
            "status": "degraded",
            "confidence": 0.8,
            "reason": (
                f"jitter {jitter:.2f} or mean {mean_interval:.1f}s "
                f"exceeds healthy threshold"
            ),
        }

    return {
        "status": "healthy",
        "confidence": 0.95,
        "reason": (
            f"cadence stable: mean {mean_interval:.1f}s, "
            f"jitter {jitter:.2f}, gap {gap_seconds:.0f}s"
        ),
    }
