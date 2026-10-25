"""Process graveyard — track when processes die and come back.

Every resurrection leaves a record.  This module maintains a simple
ledger of process death/restart events so we can answer:

- how many times has writer died today?
- what is the mean time between restarts?
- which hour of the day sees the most deaths?
- is the graveyard growing faster this week than last week?

The ledger is a plain JSONL file (``data/process_graveyard.jsonl``),
one JSON object per line::

    {
        "ts": "2026-10-20T11:00:00+08:00",
        "process": "writer",
        "event": "death",       # or "restart" or "stall"
        "pid": 12479,           # may be null for death events
        "cause": "container_sweep",  # may be null
        "gap_seconds": 5266     # seconds since last seen alive
    }

Usage::

    from process_graveyard import Graveyard

    gy = Graveyard("data/process_graveyard.jsonl")
    gy.record("writer", "restart", pid=12479, cause="container_sweep")
    print(gy.deaths_today("writer"))
    print(gy.mean_gap("writer"))
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "Graveyard",
    "GraveyardEntry",
    "HourProfile",
]

_CST = timezone(timedelta(hours=8))


def GraveyardEntry(
    process: str,
    event: str,
    pid: Optional[int] = None,
    cause: Optional[str] = None,
    gap_seconds: Optional[float] = None,
    ts: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build a single graveyard entry dict."""
    return {
        "ts": (ts or datetime.now(_CST)).isoformat(timespec="seconds"),
        "process": process,
        "event": event,
        "pid": pid,
        "cause": cause,
        "gap_seconds": gap_seconds,
    }


class HourProfile:
    """Count events per hour-of-day (0-23) in a given timezone."""

    def __init__(self, tz: timezone = _CST) -> None:
        self.tz = tz
        self.counts: Counter[int] = Counter()

    def add(self, ts_iso: str) -> None:
        dt = datetime.fromisoformat(ts_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self.tz)
        self.counts[dt.hour] += 1

    def peak_hour(self) -> Optional[int]:
        if not self.counts:
            return None
        return self.counts.most_common(1)[0][0]

    def quiet_hours(self, top_n: int = 3) -> List[int]:
        all_hours = set(range(24))
        present = set(self.counts.keys())
        missing = sorted(all_hours - present)
        if missing:
            return missing[:top_n]
        return [h for h, _ in self.counts.most_common()[-top_n:]]

    def as_dict(self) -> Dict[int, int]:
        return dict(sorted(self.counts.items()))


class Graveyard:
    """Persistent process event ledger backed by a JSONL file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._entries: List[Dict[str, Any]] = []
        self._loaded = False

    # -- persistence ----------------------------------------------------------

    def load(self) -> None:
        self._entries.clear()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        self._entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        self._loaded = True

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def record(
        self,
        process: str,
        event: str,
        pid: Optional[int] = None,
        cause: Optional[str] = None,
        gap_seconds: Optional[float] = None,
        ts: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Append an event to the ledger and flush to disk."""
        entry = GraveyardEntry(process, event, pid, cause, gap_seconds, ts)
        self._ensure_loaded()
        self._entries.append(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    @property
    def entries(self) -> List[Dict[str, Any]]:
        self._ensure_loaded()
        return list(self._entries)

    # -- queries --------------------------------------------------------------

    def filter(
        self,
        process: Optional[str] = None,
        event: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        self._ensure_loaded()
        result = []
        for e in self._entries:
            if process and e.get("process") != process:
                continue
            if event and e.get("event") != event:
                continue
            if since:
                et = datetime.fromisoformat(e["ts"])
                if et.tzinfo is None:
                    et = et.replace(tzinfo=_CST)
                if et < since:
                    continue
            result.append(e)
        return result

    def deaths_today(self, process: Optional[str] = None) -> int:
        today_start = datetime.now(_CST).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return len(self.filter(process=process, event="death", since=today_start))

    def restarts_today(self, process: Optional[str] = None) -> int:
        today_start = datetime.now(_CST).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return len(self.filter(process=process, event="restart", since=today_start))

    def mean_gap(self, process: Optional[str] = None) -> Optional[float]:
        entries = self.filter(process=process, event="restart")
        gaps = [e["gap_seconds"] for e in entries if e.get("gap_seconds") is not None]
        if not gaps:
            return None
        return sum(gaps) / len(gaps)

    def hour_profile(self, process: Optional[str] = None) -> HourProfile:
        hp = HourProfile()
        for e in self.filter(process=process, event="death"):
            hp.add(e["ts"])
        return hp

    def cause_breakdown(self, process: Optional[str] = None) -> Dict[str, int]:
        entries = self.filter(process=process, event="death")
        causes: Counter[str] = Counter()
        for e in entries:
            causes[e.get("cause") or "unknown"] += 1
        return dict(causes.most_common())

    def summary(self, process: Optional[str] = None) -> Dict[str, Any]:
        """Return a compact summary dict for a process (or all)."""
        all_entries = self.filter(process=process)
        deaths = [e for e in all_entries if e["event"] == "death"]
        restarts = [e for e in all_entries if e["event"] == "restart"]
        return {
            "process": process or "all",
            "total_deaths": len(deaths),
            "total_restarts": len(restarts),
            "deaths_today": self.deaths_today(process),
            "restarts_today": self.restarts_today(process),
            "mean_gap_seconds": self.mean_gap(process),
            "cause_breakdown": self.cause_breakdown(process),
            "peak_death_hour": self.hour_profile(process).peak_hour(),
        }
