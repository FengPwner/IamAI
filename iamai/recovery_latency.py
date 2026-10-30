#!/usr/bin/env python3
"""recovery_latency — measure time-to-first-stroke after process restart.

When the writer process is reclaimed and restarted, there's a gap between
the restart command and the first actual stroke landing in the tree.
This module tracks that gap so we can answer: "how long does cold recovery
actually take?"

Usage:
    from iamai.recovery_latency import RecoveryTracker

    tracker = RecoveryTracker()
    tracker.mark_restart()       # call right after run_both.sh
    tracker.mark_first_stroke()  # call when first stroke lands

    print(f"recovery took {tracker.latency_seconds:.1f}s")

CLI:
    python3 -m iamai.recovery_latency --check
    python3 -m iamai.recovery_latency --history
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATE_FILE = DATA_DIR / "recovery_latency.json"


@dataclass
class RecoveryEvent:
    """A single restart → first-stroke measurement."""
    restart_time: float       # unix timestamp of restart
    first_stroke_time: Optional[float] = None  # unix timestamp of first stroke
    latency_seconds: Optional[float] = None
    writer_id: str = "qwen"
    restart_pid: Optional[int] = None
    stroke_count_since: int = 0

    def complete(self, stroke_time: float, stroke_count: int = 1) -> None:
        """Mark the first stroke after restart."""
        self.first_stroke_time = stroke_time
        self.latency_seconds = stroke_time - self.restart_time
        self.stroke_count_since = stroke_count

    @property
    def is_complete(self) -> bool:
        return self.first_stroke_time is not None

    @property
    def is_pending(self) -> bool:
        return not self.is_complete


@dataclass
class RecoveryState:
    """Persistent state: current pending recovery + history."""
    current: Optional[RecoveryEvent] = None
    history: List[RecoveryEvent] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "current": asdict(self.current) if self.current else None,
            "history": [asdict(e) for e in self.history[-50:]],  # keep last 50
        }

    @classmethod
    def from_dict(cls, d: dict) -> RecoveryState:
        current = None
        if d.get("current"):
            current = RecoveryEvent(**d["current"])
        history = []
        for item in d.get("history", []):
            history.append(RecoveryEvent(**item))
        return cls(current=current, history=history)


class RecoveryTracker:
    """Track and persist recovery latency measurements."""

    def __init__(self, state_file: Optional[Path] = None, writer_id: str = "qwen"):
        self.state_file = state_file or STATE_FILE
        self.writer_id = writer_id
        self.state = self._load()

    def _load(self) -> RecoveryState:
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                return RecoveryState.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError):
                return RecoveryState()
        return RecoveryState()

    def _save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps(self.state.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )

    def mark_restart(self, pid: Optional[int] = None, timestamp: Optional[float] = None) -> RecoveryEvent:
        """Record a process restart event."""
        # Archive any existing pending recovery
        if self.state.current and self.state.current.is_pending:
            self.state.history.append(self.state.current)

        event = RecoveryEvent(
            restart_time=timestamp or time.time(),
            writer_id=self.writer_id,
            restart_pid=pid,
        )
        self.state.current = event
        self._save()
        return event

    def mark_first_stroke(self, timestamp: Optional[float] = None) -> Optional[float]:
        """Record the first stroke after restart. Returns latency in seconds."""
        if not self.state.current or self.state.current.is_complete:
            return None

        self.state.current.complete(timestamp or time.time())
        latency = self.state.current.latency_seconds
        # Move to history
        self.state.history.append(self.state.current)
        self.state.current = None
        self._save()
        return latency

    @property
    def pending(self) -> bool:
        """True if we're waiting for the first stroke after a restart."""
        return self.state.current is not None and self.state.current.is_pending

    @property
    def last_latency(self) -> Optional[float]:
        """Most recent completed recovery latency in seconds."""
        completed = [e for e in self.state.history if e.is_complete]
        if not completed:
            return None
        return completed[-1].latency_seconds

    @property
    def average_latency(self) -> Optional[float]:
        """Average recovery latency across all completed events."""
        completed = [e for e in self.state.history if e.is_complete]
        if not completed:
            return None
        return sum(e.latency_seconds for e in completed) / len(completed)

    @property
    def history_count(self) -> int:
        """Total number of recorded recovery events."""
        return len(self.state.history)

    def summary(self) -> dict:
        """Human-readable summary of recovery state."""
        completed = [e for e in self.state.history if e.is_complete]
        latencies = [e.latency_seconds for e in completed]
        return {
            "pending": self.pending,
            "total_recoveries": len(self.state.history),
            "completed": len(completed),
            "avg_latency_s": round(sum(latencies) / len(latencies), 1) if latencies else None,
            "min_latency_s": round(min(latencies), 1) if latencies else None,
            "max_latency_s": round(max(latencies), 1) if latencies else None,
            "last_latency_s": round(latencies[-1], 1) if latencies else None,
        }


# ---------------------------------------------------------------------------
# RecoveryChain — track the three-phase recovery sequence
# ---------------------------------------------------------------------------

@dataclass
class RecoveryChain:
    """A full recovery chain: restart → backlog commit → push.

    The three phases are:
      1. restart   — writer and batch processes are alive
      2. backlog   — uncommitted changes are bundled into a catch-up commit
      3. push      — local commits reach the remote without rejection

    Each phase records a timestamp and a success flag.  The chain is
    *complete* when all three phases have been marked, regardless of
    whether every phase succeeded.  A chain where any phase failed is
    *complete but degraded*.
    """
    restart_ts: Optional[float] = None
    restart_ok: bool = False
    restart_pid: Optional[int] = None

    backlog_ts: Optional[float] = None
    backlog_ok: bool = False
    backlog_files: int = 0
    backlog_commit: Optional[str] = None

    push_ts: Optional[float] = None
    push_ok: bool = False
    push_remote_ref: Optional[str] = None

    @property
    def is_complete(self) -> bool:
        return (
            self.restart_ts is not None
            and self.backlog_ts is not None
            and self.push_ts is not None
        )

    @property
    def is_degraded(self) -> bool:
        """True when the chain finished but at least one phase failed."""
        return self.is_complete and not (
            self.restart_ok and self.backlog_ok and self.push_ok
        )

    @property
    def total_seconds(self) -> Optional[float]:
        """Wall-clock seconds from restart to push."""
        if self.restart_ts is None or self.push_ts is None:
            return None
        return self.push_ts - self.restart_ts

    @property
    def phases_done(self) -> int:
        return sum([
            self.restart_ts is not None,
            self.backlog_ts is not None,
            self.push_ts is not None,
        ])

    def mark_restart(self, ts: Optional[float] = None, pid: Optional[int] = None, ok: bool = True) -> None:
        self.restart_ts = ts or time.time()
        self.restart_ok = ok
        self.restart_pid = pid

    def mark_backlog(self, ts: Optional[float] = None, ok: bool = True,
                     files: int = 0, commit: Optional[str] = None) -> None:
        self.backlog_ts = ts or time.time()
        self.backlog_ok = ok
        self.backlog_files = files
        self.backlog_commit = commit

    def mark_push(self, ts: Optional[float] = None, ok: bool = True,
                  remote_ref: Optional[str] = None) -> None:
        self.push_ts = ts or time.time()
        self.push_ok = ok
        self.push_remote_ref = remote_ref

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RecoveryChain":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def summary(self) -> str:
        parts = []
        for name, ok in [
            ("restart", self.restart_ok),
            ("backlog", self.backlog_ok),
            ("push", self.push_ok),
        ]:
            ts = getattr(self, f"{name}_ts")
            if ts is None:
                parts.append(f"{name}=pending")
            else:
                status = "ok" if ok else "FAIL"
                parts.append(f"{name}={status}@{ts:.0f}")
        elapsed = f"{self.total_seconds:.1f}s" if self.total_seconds is not None else "n/a"
        degraded = " [DEGRADED]" if self.is_degraded else ""
        return f"RecoveryChain({', '.join(parts)}, total={elapsed}{degraded})"
