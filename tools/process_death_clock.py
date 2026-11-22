#!/usr/bin/env python3
"""process_death_clock.py — record and analyze process death timestamps.

when writer_loop or commit_batch dies, the caretaker restarts it.  but
knowing *when* deaths cluster reveals root causes: simultaneous deaths
suggest container recycling, while staggered deaths suggest OOM or
individual crashes.

this tool maintains a small JSON ledger of death events and provides:

1. ``record_death(process, ts)`` — append a death event.
2. ``recent_deaths(window_sec)`` — deaths within the last N seconds.
3. ``correlation(window_sec)`` — pairs of deaths within *window_sec*
   of each other (likely same root cause).
4. ``death_rate(window_sec)`` — deaths per hour over the window.
5. ``time_since_last_death()`` — seconds since most recent death.
6. ``classify(window_sec)`` — one of "clean", "isolated", "clustered",
   "storm".

storage: ``data/death_clock.json`` — append-only log, kept to the last
500 events (FIFO trim on every write).

CLI
---
    python3 tools/process_death_clock.py --record writer
    python3 tools/process_death_clock.py --record batch
    python3 tools/process_death_clock.py --status
    python3 tools/process_death_clock.py --json
    python3 tools/process_death_clock.py --trim 200   # keep 200 events

exit codes:
    0 — clean or isolated
    1 — clustered or storm
    2 — insufficient data
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER = REPO / "data" / "death_clock.json"
MAX_EVENTS = 500

# classification thresholds (deaths within correlation window)
CORRELATION_WINDOW_SEC = 120          # deaths within 2 min = correlated
CLUSTER_THRESHOLD = 3                 # ≥3 correlated pairs → clustered
STORM_THRESHOLD = 6                   # ≥6 correlated pairs → storm

# ---------------------------------------------------------------------------
# data types
# ---------------------------------------------------------------------------


@dataclass
class DeathEvent:
    process: str          # "writer" | "batch" | other
    ts: float             # unix epoch
    pid: Optional[int] = None
    note: str = ""


# ---------------------------------------------------------------------------
# ledger I/O
# ---------------------------------------------------------------------------


def load_ledger(path: Path = DEFAULT_LEDGER) -> List[DeathEvent]:
    """Load death events from JSON ledger."""
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    events = []
    for item in raw:
        events.append(DeathEvent(
            process=item.get("process", "unknown"),
            ts=float(item.get("ts", 0)),
            pid=item.get("pid"),
            note=item.get("note", ""),
        ))
    return events


def save_ledger(events: Sequence[DeathEvent],
                path: Path = DEFAULT_LEDGER,
                max_events: int = MAX_EVENTS) -> None:
    """Save events to JSON ledger, trimming to *max_events*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    trimmed = list(events)[-max_events:]
    records = [asdict(e) for e in trimmed]
    path.write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# core operations
# ---------------------------------------------------------------------------


def record_death(process: str,
                 ts: Optional[float] = None,
                 pid: Optional[int] = None,
                 note: str = "",
                 path: Path = DEFAULT_LEDGER) -> DeathEvent:
    """Record a new death event and persist the ledger."""
    if ts is None:
        ts = time.time()
    event = DeathEvent(process=process, ts=ts, pid=pid, note=note)
    events = load_ledger(path)
    events.append(event)
    save_ledger(events, path)
    return event


def recent_deaths(window_sec: float = 3600,
                  now: Optional[float] = None,
                  events: Optional[List[DeathEvent]] = None,
                  path: Path = DEFAULT_LEDGER) -> List[DeathEvent]:
    """Return deaths within the last *window_sec* seconds."""
    if now is None:
        now = time.time()
    if events is None:
        events = load_ledger(path)
    cutoff = now - window_sec
    return [e for e in events if e.ts >= cutoff]


def correlated_pairs(window_sec: float = CORRELATION_WINDOW_SEC,
                     events: Optional[List[DeathEvent]] = None,
                     path: Path = DEFAULT_LEDGER) -> List[Tuple[DeathEvent, DeathEvent]]:
    """Find pairs of deaths within *window_sec* of each other."""
    if events is None:
        events = load_ledger(path)
    sorted_events = sorted(events, key=lambda e: e.ts)
    pairs: List[Tuple[DeathEvent, DeathEvent]] = []
    for i, a in enumerate(sorted_events):
        for b in sorted_events[i + 1:]:
            if b.ts - a.ts > window_sec:
                break
            pairs.append((a, b))
    return pairs


def death_rate(window_sec: float = 3600,
               now: Optional[float] = None,
               events: Optional[List[DeathEvent]] = None,
               path: Path = DEFAULT_LEDGER) -> float:
    """Deaths per hour over *window_sec*."""
    deaths = recent_deaths(window_sec, now, events, path)
    if not deaths:
        return 0.0
    hours = window_sec / 3600.0
    return len(deaths) / hours if hours > 0 else 0.0


def time_since_last_death(now: Optional[float] = None,
                          events: Optional[List[DeathEvent]] = None,
                          path: Path = DEFAULT_LEDGER) -> Optional[float]:
    """Seconds since the most recent death, or None if no events."""
    if events is None:
        events = load_ledger(path)
    if not events:
        return None
    if now is None:
        now = time.time()
    latest = max(e.ts for e in events)
    return now - latest


def classify(window_sec: float = 3600,
             now: Optional[float] = None,
             events: Optional[List[DeathEvent]] = None,
             path: Path = DEFAULT_LEDGER) -> str:
    """Classify recent death pattern.

    Returns one of:
        "clean"     — no deaths in window
        "isolated"  — deaths exist but no correlated pairs
        "clustered" — ≥ CLUSTER_THRESHOLD correlated pairs
        "storm"     — ≥ STORM_THRESHOLD correlated pairs
    """
    if events is None:
        events = load_ledger(path)
    recent = recent_deaths(window_sec, now, events, path)
    if not recent:
        return "clean"
    pairs = correlated_pairs(CORRELATION_WINDOW_SEC, recent, path)
    n_pairs = len(pairs)
    if n_pairs >= STORM_THRESHOLD:
        return "storm"
    if n_pairs >= CLUSTER_THRESHOLD:
        return "clustered"
    return "isolated"


# ---------------------------------------------------------------------------
# status report
# ---------------------------------------------------------------------------


def status_report(now: Optional[float] = None,
                  path: Path = DEFAULT_LEDGER) -> Dict[str, Any]:
    """Build a compact status dict for caretaker dashboards."""
    if now is None:
        now = time.time()
    events = load_ledger(path)
    total = len(events)
    recent_1h = recent_deaths(3600, now, events, path)
    recent_24h = recent_deaths(86400, now, events, path)
    tsl = time_since_last_death(now, events, path)
    cls = classify(3600, now, events, path)
    rate_1h = death_rate(3600, now, events, path)
    pairs = correlated_pairs(CORRELATION_WINDOW_SEC, events, path)

    last_event = None
    if events:
        latest = max(events, key=lambda e: e.ts)
        last_event = {
            "process": latest.process,
            "ts": latest.ts,
            "iso": datetime.fromtimestamp(latest.ts, tz=timezone.utc).isoformat(),
        }

    return {
        "total_events": total,
        "deaths_1h": len(recent_1h),
        "deaths_24h": len(recent_24h),
        "death_rate_1h": round(rate_1h, 2),
        "time_since_last_sec": round(tsl, 1) if tsl is not None else None,
        "correlated_pairs": len(pairs),
        "classification": cls,
        "last_event": last_event,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--record", metavar="PROCESS",
                    help="record a death event for PROCESS")
    ap.add_argument("--pid", type=int, default=None,
                    help="PID of the dead process")
    ap.add_argument("--note", default="", help="optional note")
    ap.add_argument("--status", action="store_true",
                    help="print human-readable status")
    ap.add_argument("--json", action="store_true",
                    help="print JSON status")
    ap.add_argument("--trim", type=int, default=None,
                    help="trim ledger to N events and exit")
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER),
                    help="path to ledger JSON")
    args = ap.parse_args()

    path = Path(args.ledger)

    if args.record:
        evt = record_death(args.record, pid=args.pid, note=args.note, path=path)
        ts_iso = datetime.fromtimestamp(evt.ts, tz=timezone.utc).isoformat()
        print(f"recorded death: {evt.process} at {ts_iso}")
        return 0

    if args.trim is not None:
        events = load_ledger(path)
        save_ledger(events, path, max_events=args.trim)
        kept = min(len(events), args.trim)
        print(f"trimmed ledger to {kept} events")
        return 0

    if args.json:
        report = status_report(path=path)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        cls = report["classification"]
        return 0 if cls in ("clean", "isolated") else 1

    if args.status:
        report = status_report(path=path)
        print(f"death clock — {report['classification']}")
        print(f"  total events:     {report['total_events']}")
        print(f"  deaths (1h):      {report['deaths_1h']}")
        print(f"  deaths (24h):     {report['deaths_24h']}")
        print(f"  rate (1h):        {report['death_rate_1h']}/hr")
        tsl = report['time_since_last_sec']
        if tsl is not None:
            print(f"  since last death: {tsl:.0f}s ({tsl/60:.1f}min)")
        else:
            print(f"  since last death: never")
        print(f"  correlated pairs: {report['correlated_pairs']}")
        if report['last_event']:
            le = report['last_event']
            print(f"  last death:       {le['process']} at {le['iso']}")
        cls = report["classification"]
        return 0 if cls in ("clean", "isolated") else 1

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
