"""push_blockage_tracker — record push blockage events with duration.

push_debt measures the *cost* of unpushed commits. push_diag diagnoses
the *current* push state. but neither tracks blockage as a timeline of
events with start/end timestamps and caretaker-visit correlations.

this module fills that gap. every time the caretaker probes the push
pipeline and finds it blocked, a blockage event is recorded (or an
existing one extended). when push succeeds, the open event is closed.

each event captures:

    started_at      when blockage was first detected
    ended_at        when push recovered (None if still blocked)
    duration_hours  wall-clock span from start to end (or to now)
    cause           short label: MISSING_KEY, UNREGISTERED_KEY,
                    NETWORK, CREDENTIAL_EXPIRED, UNKNOWN
    visit_count     how many caretaker visits observed this event
    peak_unpushed   max unpushed commits seen during this event

the event log is append-only JSONL at data/push_blockage_events.jsonl.
a separate state cache at data/push_blockage_state.json tracks the
currently open event (if any).

usage::

    from iamai.push_blockage_tracker import probe, get_open_event

    event = probe(push_ok=False, cause="UNREGISTERED_KEY",
                  unpushed_count=79)
    print(event)
    # BlockageEvent(started_at=..., duration_hours=..., visit_count=380)

design: this module observes state; it never auto-fixes. fixes belong
in push_recovery_orchestrator.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
EVENTS_LOG = DATA_DIR / "push_blockage_events.jsonl"
STATE_CACHE = DATA_DIR / "push_blockage_state.json"


# ---------------------------------------------------------------------------
# data model
# ---------------------------------------------------------------------------

@dataclass
class BlockageEvent:
    """a single push blockage event."""
    started_at: str
    cause: str
    ended_at: Optional[str] = None
    visit_count: int = 1
    peak_unpushed: int = 0
    visit_timestamps: list[str] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.ended_at is None

    @property
    def duration_hours(self) -> float:
        start = datetime.fromisoformat(self.started_at)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if self.ended_at:
            end = datetime.fromisoformat(self.ended_at)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
        else:
            end = datetime.now(timezone.utc)
        return max(0.0, (end - start).total_seconds() / 3600.0)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration_hours"] = round(self.duration_hours, 2)
        d["is_open"] = self.is_open
        return d


# ---------------------------------------------------------------------------
# state persistence
# ---------------------------------------------------------------------------

def _load_state() -> Optional[BlockageEvent]:
    """load the currently open blockage event."""
    if not STATE_CACHE.exists():
        return None
    try:
        data = json.loads(STATE_CACHE.read_text().strip())
        return BlockageEvent(**data)
    except (json.JSONDecodeError, TypeError, KeyError):
        return None


def _save_state(event: BlockageEvent) -> None:
    """save the currently open blockage event."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_CACHE.write_text(json.dumps(asdict(event), indent=2))


def _clear_state() -> None:
    """clear the open event (push recovered)."""
    if STATE_CACHE.exists():
        STATE_CACHE.unlink()


def _append_event(event: BlockageEvent) -> None:
    """append a completed event to the log."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(EVENTS_LOG, "a") as f:
        f.write(json.dumps(event.to_dict()) + "\n")


# ---------------------------------------------------------------------------
# core API
# ---------------------------------------------------------------------------

def probe(push_ok: bool, cause: str = "UNKNOWN",
          unpushed_count: int = 0) -> Optional[BlockageEvent]:
    """probe the push pipeline and update blockage state.

    call this once per caretaker visit.

    if push_ok is True:
        close any open blockage event and record it.
    if push_ok is False:
        open a new event or extend the existing one.

    returns the current (or just-closed) event, or None if push is ok
    and no event was open.
    """
    now = datetime.now(timezone.utc).isoformat()
    open_event = _load_state()

    if push_ok:
        if open_event is not None:
            open_event.ended_at = now
            _append_event(open_event)
            _clear_state()
            return open_event
        return None

    # push is blocked
    if open_event is None:
        # new blockage event
        event = BlockageEvent(
            started_at=now,
            cause=cause,
            peak_unpushed=unpushed_count,
            visit_timestamps=[now],
        )
    else:
        # extend existing event
        if cause != "UNKNOWN":
            open_event.cause = cause
        open_event.visit_count += 1
        open_event.visit_timestamps.append(now)
        if unpushed_count > open_event.peak_unpushed:
            open_event.peak_unpushed = unpushed_count
        event = open_event

    _save_state(event)
    return event


def get_open_event() -> Optional[BlockageEvent]:
    """return the currently open blockage event, if any."""
    return _load_state()


def get_event_history(limit: int = 0) -> list[dict]:
    """load past blockage events. limit=0 means all."""
    if not EVENTS_LOG.exists():
        return []
    events = []
    for line in EVENTS_LOG.read_text().strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if limit > 0:
        return events[-limit:]
    return events


def format_summary(event: BlockageEvent) -> str:
    """format a blockage event as a human-readable summary."""
    status = "OPEN" if event.is_open else "CLOSED"
    lines = [
        f"=== Push Blockage [{status}] ===",
        f"  started:       {event.started_at}",
        f"  cause:         {event.cause}",
        f"  duration:      {event.duration_hours:.1f} hours",
        f"  visit count:   {event.visit_count}",
        f"  peak unpushed: {event.peak_unpushed} commits",
    ]
    if event.ended_at:
        lines.append(f"  ended:         {event.ended_at}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="push blockage tracker")
    parser.add_argument("--probe-ok", action="store_true",
                        help="report push is working")
    parser.add_argument("--probe-fail", action="store_true",
                        help="report push is blocked")
    parser.add_argument("--cause", default="UNKNOWN",
                        help="blockage cause label")
    parser.add_argument("--unpushed", type=int, default=0,
                        help="current unpushed commit count")
    parser.add_argument("--status", action="store_true",
                        help="show current blockage state")
    parser.add_argument("--history", type=int, default=0,
                        help="show last N events")
    parser.add_argument("--json", action="store_true",
                        help="JSON output")
    args = parser.parse_args()

    if args.status:
        event = get_open_event()
        if event is None:
            print("no open blockage event (push is healthy)")
            return 0
        if args.json:
            print(json.dumps(event.to_dict(), indent=2))
        else:
            print(format_summary(event))
        return 0

    if args.history > 0:
        events = get_event_history(limit=args.history)
        if args.json:
            print(json.dumps(events, indent=2))
        else:
            for e in events:
                status = "OPEN" if e.get("is_open") else "CLOSED"
                print(f"  {e.get('started_at', '?')}  "
                      f"cause={e.get('cause', '?')}  "
                      f"dur={e.get('duration_hours', 0):.1f}h  "
                      f"visits={e.get('visit_count', 0)}  "
                      f"peak={e.get('peak_unpushed', 0)}  "
                      f"[{status}]")
        return 0

    if args.probe_ok:
        event = probe(push_ok=True)
        if event:
            print(f"blockage closed: {event.duration_hours:.1f}h, "
                  f"{event.visit_count} visits")
        else:
            print("no open blockage — push was already healthy")
        return 0

    if args.probe_fail:
        event = probe(push_ok=False, cause=args.cause,
                      unpushed_count=args.unpushed)
        if args.json:
            print(json.dumps(event.to_dict(), indent=2))
        else:
            print(format_summary(event))
        return 1 if event and event.duration_hours > 24 else 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
