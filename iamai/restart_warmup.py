"""Measure how quickly a writer produces its first stroke after restart.

A writer that takes 30 s to warm up is fine; one that takes 5 min is
sick.  This module records every (restart, first-stroke) pair so we can
track cold-start latency over time and spot degradation.

Events are appended to ``data/restart_warmup.jsonl``.  Each line is a
JSON object:

==============  ========================================================
key             meaning
==============  ========================================================
writer          writer identity (e.g. ``"qwen"``)
event           ``"restart"`` | ``"first_stroke"``
ts              ISO-8601 timestamp
pid             process id (may be ``null``)
stroke_seq      stroke sequence number (``null`` for restart events)
==============  ========================================================

The ``warmup_report`` function pairs each restart with its next
first-stroke and computes latency statistics.

Usage::

    from iamai.restart_warmup import record_restart, record_first_stroke, warmup_report

    record_restart(repo, writer="qwen", pid=1411)
    # ... writer produces first stroke ...
    record_first_stroke(repo, writer="qwen", pid=1411, stroke_seq=12468)

    report = warmup_report(repo, writer="qwen")
    print(report["pairs"])          # e.g. 42
    print(report["mean_seconds"])   # e.g. 8.3
    print(report["p95_seconds"])    # e.g. 24.1
    print(report["max_seconds"])    # e.g. 312.0
    print(report["slow_count"])     # pairs > 60 s
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

LEDGER = "data/restart_warmup.jsonl"

# Threshold (seconds) above which a warmup is considered "slow".
SLOW_THRESHOLD_SEC = 60.0


def ledger_path(repo: Path | str) -> Path:
    return Path(repo) / LEDGER


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _append(repo: Path | str, record: Dict[str, Any]) -> Dict[str, Any]:
    path = ledger_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def record_restart(
    repo: Path | str,
    writer: str,
    pid: Optional[int] = None,
    ts: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Record a writer restart event."""
    record = {
        "writer": writer,
        "event": "restart",
        "ts": (ts or _now()).isoformat(),
        "pid": pid,
        "stroke_seq": None,
    }
    return _append(repo, record)


def record_first_stroke(
    repo: Path | str,
    writer: str,
    pid: Optional[int] = None,
    stroke_seq: Optional[int] = None,
    ts: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Record the first stroke produced after a restart."""
    record = {
        "writer": writer,
        "event": "first_stroke",
        "ts": (ts or _now()).isoformat(),
        "pid": pid,
        "stroke_seq": stroke_seq,
    }
    return _append(repo, record)


def read_events(repo: Path | str, writer: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read all warmup events, optionally filtered by writer."""
    path = ledger_path(repo)
    if not path.exists():
        return []
    events: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if writer and obj.get("writer") != writer:
                continue
            events.append(obj)
    return events


def _pair_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Match each restart with its next first_stroke, compute latency."""
    pairs: List[Dict[str, Any]] = []
    pending_restart: Optional[Dict[str, Any]] = None

    for ev in events:
        if ev["event"] == "restart":
            pending_restart = ev
        elif ev["event"] == "first_stroke" and pending_restart is not None:
            restart_ts = datetime.fromisoformat(pending_restart["ts"])
            stroke_ts = datetime.fromisoformat(ev["ts"])
            delta = (stroke_ts - restart_ts).total_seconds()
            pairs.append({
                "restart_ts": pending_restart["ts"],
                "first_stroke_ts": ev["ts"],
                "latency_sec": max(delta, 0.0),
                "restart_pid": pending_restart.get("pid"),
                "stroke_pid": ev.get("pid"),
                "stroke_seq": ev.get("stroke_seq"),
            })
            pending_restart = None  # consumed

    return pairs


def _percentile(values: List[float], pct: float) -> float:
    """Simple nearest-rank percentile on a sorted list."""
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(len(s) * pct / 100.0)))
    return s[k]


def warmup_report(
    repo: Path | str,
    writer: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute warmup latency statistics from the ledger.

    Returns a dict with keys: ``pairs`` (count), ``mean_seconds``,
    ``p50_seconds``, ``p95_seconds``, ``max_seconds``, ``slow_count``,
    ``slow_threshold_sec``, and ``last_latency_sec`` (most recent pair).
    """
    events = read_events(repo, writer=writer)
    pairs = _pair_events(events)
    latencies = [p["latency_sec"] for p in pairs]

    if not latencies:
        return {
            "pairs": 0,
            "mean_seconds": 0.0,
            "p50_seconds": 0.0,
            "p95_seconds": 0.0,
            "max_seconds": 0.0,
            "slow_count": 0,
            "slow_threshold_sec": SLOW_THRESHOLD_SEC,
            "last_latency_sec": None,
        }

    slow = sum(1 for v in latencies if v > SLOW_THRESHOLD_SEC)
    return {
        "pairs": len(latencies),
        "mean_seconds": round(sum(latencies) / len(latencies), 2),
        "p50_seconds": round(_percentile(latencies, 50), 2),
        "p95_seconds": round(_percentile(latencies, 95), 2),
        "max_seconds": round(max(latencies), 2),
        "slow_count": slow,
        "slow_threshold_sec": SLOW_THRESHOLD_SEC,
        "last_latency_sec": round(latencies[-1], 2),
    }
