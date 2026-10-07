"""Process mortality ledger — track deaths and restarts over time.

Individual caretaker visit notes record *one* death each.  This module
lets you see the *rate* of death, which is the number that actually
matters for reliability.

Events are appended to ``data/process_mortality.jsonl``.  Each line is a
JSON object with keys:

========  ============================================================
key       meaning
========  ============================================================
ts        ISO-8601 timestamp of the event
writer    writer identity (e.g. ``"qwen"``)
event     ``"death"`` | ``"restart"`` | ``"unknown"``
pid       process id at the time of the event (may be ``null``)
gap_sec   seconds since the previous event of any kind (``null`` for first)
========  ============================================================

Usage::

    from iamai.process_mortality import record_event, mortality_report

    record_event(repo, writer="qwen", event="restart", pid=1355)

    report = mortality_report(repo, writer="qwen")
    print(report["uptime_pct"])      # e.g. 67.3
    print(report["mtbf_minutes"])    # e.g. 88.5
    print(report["deaths_24h"])      # e.g. 12
    print(report["total_events"])    # e.g. 148

The ``uptime_pct`` estimate assumes each death is followed by a restart
and that downtime equals the gap between a death event and the next
restart event.  If the ledger is missing events (e.g. the caretaker
restarted without recording the death), the estimate will be optimistic.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LEDGER = "data/process_mortality.jsonl"


def ledger_path(repo: Path | str) -> Path:
    return Path(repo) / LEDGER


def record_event(
    repo: Path | str,
    writer: str,
    event: str,
    pid: int | None = None,
    *,
    ts: datetime | None = None,
) -> dict:
    """Append one event to the mortality ledger and return it."""
    if ts is None:
        ts = datetime.now(timezone.utc)
    repo_path = Path(repo)
    path = ledger_path(repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Compute gap from previous event
    gap_sec: float | None = None
    if path.exists():
        lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        if lines:
            try:
                last = json.loads(lines[-1])
                last_ts = datetime.fromisoformat(last["ts"])
                gap_sec = (ts - last_ts).total_seconds()
            except (json.JSONDecodeError, KeyError, ValueError):
                pass

    record = {
        "ts": ts.isoformat(),
        "writer": writer,
        "event": event,
        "pid": pid,
        "gap_sec": gap_sec,
    }

    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")

    return record


def read_events(repo: Path | str, writer: str | None = None) -> list[dict]:
    """Read all events from the ledger, optionally filtered by writer."""
    path = ledger_path(repo)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            continue
        if writer is not None and evt.get("writer") != writer:
            continue
        events.append(evt)
    return events


def mortality_report(
    repo: Path | str,
    writer: str | None = None,
    *,
    window_hours: float | None = 24.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compute mortality statistics from the ledger.

    Returns a dict with keys:

    - ``total_events``: number of events in the window
    - ``deaths``: number of death events
    - ``restarts``: number of restart events
    - ``deaths_24h``: deaths in the last 24 hours (or ``None`` if window < 24h)
    - ``mtbf_minutes``: mean time between failures (deaths), in minutes
    - ``uptime_pct``: estimated uptime percentage (0–100)
    - ``avg_downtime_minutes``: average gap from death to next restart
    """
    if now is None:
        now = datetime.now(timezone.utc)

    events = read_events(repo, writer=writer)

    # Filter by window
    if window_hours is not None:
        cutoff = now.timestamp() - window_hours * 3600
        events = [
            e for e in events
            if datetime.fromisoformat(e["ts"]).timestamp() >= cutoff
        ]

    deaths = [e for e in events if e.get("event") == "death"]
    restarts = [e for e in events if e.get("event") == "restart"]

    # MTBF: average time between consecutive death events
    mtbf_minutes: float | None = None
    if len(deaths) >= 2:
        death_times = sorted(datetime.fromisoformat(d["ts"]).timestamp() for d in deaths)
        gaps = [death_times[i + 1] - death_times[i] for i in range(len(death_times) - 1)]
        mtbf_minutes = (sum(gaps) / len(gaps)) / 60.0

    # Uptime: estimate downtime as gaps between death and next restart
    total_downtime_sec = 0.0
    downtime_gaps: list[float] = []
    for d in deaths:
        d_ts = datetime.fromisoformat(d["ts"]).timestamp()
        # Find the first restart after this death
        next_restart_ts = None
        for r in restarts:
            r_ts = datetime.fromisoformat(r["ts"]).timestamp()
            if r_ts > d_ts:
                next_restart_ts = r_ts
                break
        if next_restart_ts is not None:
            gap = next_restart_ts - d_ts
            total_downtime_sec += gap
            downtime_gaps.append(gap)

    window_sec = window_hours * 3600 if window_hours else (now.timestamp() - min(
        (datetime.fromisoformat(e["ts"]).timestamp() for e in events),
        default=now.timestamp()
    ))
    if window_sec <= 0:
        window_sec = 1.0

    uptime_pct = max(0.0, min(100.0, 100.0 * (1.0 - total_downtime_sec / window_sec)))

    avg_downtime_minutes: float | None = None
    if downtime_gaps:
        avg_downtime_minutes = (sum(downtime_gaps) / len(downtime_gaps)) / 60.0

    # Deaths in last 24h
    deaths_24h: int | None = None
    if window_hours is None or window_hours >= 24:
        cutoff_24h = now.timestamp() - 24 * 3600
        deaths_24h = sum(
            1 for d in deaths
            if datetime.fromisoformat(d["ts"]).timestamp() >= cutoff_24h
        )

    return {
        "total_events": len(events),
        "deaths": len(deaths),
        "restarts": len(restarts),
        "deaths_24h": deaths_24h,
        "mtbf_minutes": mtbf_minutes,
        "uptime_pct": round(uptime_pct, 1),
        "avg_downtime_minutes": avg_downtime_minutes,
    }
