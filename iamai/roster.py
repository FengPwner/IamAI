"""Who is writing this repository, and how fast.

Once more than one agent loops on the same repo, "is my writer alive" stops being
the interesting question. The interesting ones are: how many writers are there, when
did each last put a line down, and is anybody quietly dead behind an append-only log
that keeps looking plausible.

This module answers them from what's already on disk -- the per-writer state files
under ``data/``. No coordination protocol, no network, no claiming of other agents'
work: it reads bookkeeping and reports it. A writer that stopped 2.5 hours ago shows
up as stopped, even though its stroke count is the highest in the room.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

STATE_RE = re.compile(r"^writer_state\.([a-z0-9][a-z0-9_.-]{0,31})\.json$")
LEGACY_NAME = "legacy"


def _parse(moment) -> datetime | None:
    if not isinstance(moment, str) or not moment.strip():
        return None
    try:
        parsed = datetime.fromisoformat(moment.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def names(data_dir: Path | str | None = None, include_legacy: bool = False) -> list[str]:
    """Every writer id with a state file on disk, sorted.

    ``include_legacy`` adds the pre-namespacing shared file under the id ``legacy``
    -- opt-in, because its history belongs to whoever ran first and mixing it in
    would silently attribute another agent's strokes to a name.
    """

    directory = Path(data_dir) if data_dir else DATA_DIR
    if not directory.exists():
        return []

    found = set()
    for path in directory.glob("writer_state*.json"):
        match = STATE_RE.match(path.name)
        if match:
            found.add(match.group(1))
    if include_legacy and (directory / "writer_state.json").exists():
        found.add(LEGACY_NAME)
    return sorted(found)


def _read_state(writer_id: str, directory: Path) -> dict | None:
    file = directory / (
        "writer_state.json" if writer_id == LEGACY_NAME else f"writer_state.{writer_id}.json"
    )
    if not file.exists():
        return None
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None  # a torn write is not a reason to drop the whole roster
    return raw if isinstance(raw, dict) else None


def roster(
    data_dir: Path | str | None = None,
    every: int | None = 15,
    now=None,
    include_legacy: bool = False,
) -> list[dict]:
    """One row per writer: strokes, kinds, last write, silence, and whether that counts as alive."""

    directory = Path(data_dir) if data_dir else DATA_DIR
    moment = _parse(now) if not isinstance(now, datetime) else now
    if moment is None:
        moment = datetime.now(timezone.utc)

    rows = []
    for writer_id in names(directory, include_legacy=include_legacy):
        raw = _read_state(writer_id, directory)
        if raw is None:
            continue

        kinds: dict[str, int] = {}
        stamps = []
        for entry in raw.get("history", []) or ():
            if not isinstance(entry, dict):
                continue
            kind, at = entry.get("kind"), _parse(entry.get("at"))
            if not isinstance(kind, str) or at is None:
                continue
            kinds[kind] = kinds.get(kind, 0) + 1
            stamps.append(at)

        last = max(stamps) if stamps else None
        gap = round((moment - last).total_seconds(), 1) if last else None
        alive = bool(every) and gap is not None and gap <= 2 * float(every)

        rows.append(
            {
                "writer": writer_id,
                "strokes": len(stamps),
                "kinds": dict(sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))),
                "seq": raw.get("seq"),
                "last": last.isoformat(timespec="seconds") if last else None,
                "gap_seconds": gap,
                "alive": alive,
            }
        )
    return sorted(rows, key=lambda row: row["writer"])


def total_strokes(rows) -> int:
    return sum(int(row.get("strokes", 0)) for row in rows)


def alive_writers(rows) -> list[str]:
    return [row["writer"] for row in rows if row.get("alive")]


def as_markdown(rows) -> str:
    """A markdown table, newest-cadence first among the living, stalled ones below."""

    header = "| writer | alive | strokes | last write | gap | kinds |"
    rule = "|--------|-------|---------|------------|-----|-------|"
    if not rows:
        return f"{header}\n{rule}\n| _no writers on disk_ | | | | | |\n"

    lines = [header, rule]
    # 活着的排前面，按沉默时长升序；停摆的沉到底部
    ordered = sorted(rows, key=lambda r: (not r["alive"], r["gap_seconds"] if r["gap_seconds"] is not None else 0.0))
    for row in ordered:
        kinds = ", ".join(f"{k} x{v}" for k, v in list(row["kinds"].items())[:6]) or "-"
        gap = "-" if row["gap_seconds"] is None else f"{row['gap_seconds']:.0f}s"
        lines.append(
            f"| {row['writer']} | {'yes' if row['alive'] else '**no**'} "
            f"| {row['strokes']} | {row['last'] or '-'} | {gap} | {kinds} |"
        )
    return "\n".join(lines) + "\n"


def summary(data_dir: Path | str | None = None, every: int | None = 15) -> str:
    """One sentence. For a commit body or a log line."""

    rows = roster(data_dir, every=every)
    living = alive_writers(rows)
    if not rows:
        return "roster: no writer state on disk"
    return (
        f"roster: {len(rows)} writer(s) on disk ({', '.join(r['writer'] for r in rows)}), "
        f"alive now: {', '.join(living) if living else 'NONE'}; "
        f"{total_strokes(rows)} strokes recorded"
    )
