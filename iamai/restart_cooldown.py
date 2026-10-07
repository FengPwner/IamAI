"""restart_cooldown — prevent rapid-fire restarts from masking real failures.

After 75 caretaker visits, the pattern is clear: the writer dies, the
caretaker restarts it, it runs for ~50 minutes, it dies again. Each
restart is individually correct, but the *aggregate* hides a deeper
problem — the process is not stable enough to survive unattended.

This module provides a simple cooldown gate:

    gate = RestartCooldownGate("data/restart_cooldown.jsonl")
    decision = gate.should_restart(reason="process dead")
    if decision.allowed:
        # proceed with restart
        ...
    else:
        # wait or escalate
        print(f"cooldown active: {decision.remaining_s:.0f}s left")

Design:
  - max_restarts: maximum restarts allowed within the window (default 3)
  - window_s: sliding window length in seconds (default 3600 = 1 hour)
  - cooldown_s: how long to block after hitting the limit (default 1800)

Each restart attempt is recorded as a JSONL line with timestamp, reason,
and whether it was allowed or denied. This creates an audit trail that
the caretaker can review to distinguish "the process crashed once and
recovered" from "the process is in a crash loop."

Usage:
    from iamai.restart_cooldown import RestartCooldownGate

    gate = RestartCooldownGate("data/restart_cooldown.jsonl")
    decision = gate.should_restart(reason="writer dead")
    if decision.allowed:
        restart_writer()
    else:
        escalate(f"restart blocked: {decision.remaining_s:.0f}s cooldown")
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RestartDecision:
    """Outcome of a should_restart() check."""

    allowed: bool
    remaining_s: float
    restarts_in_window: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "remaining_s": round(self.remaining_s, 1),
            "restarts_in_window": self.restarts_in_window,
            "reason": self.reason,
        }


class RestartCooldownGate:
    """Gate restart attempts to prevent crash-loop masking."""

    def __init__(
        self,
        filepath: str | Path,
        max_restarts: int = 3,
        window_s: int = 3600,
        cooldown_s: int = 1800,
    ) -> None:
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self.max_restarts = max_restarts
        self.window_s = window_s
        self.cooldown_s = cooldown_s

    def _load_events(self) -> list[dict[str, Any]]:
        """Load restart event log. Returns empty list on any error."""
        if not self.filepath.exists():
            return []
        events: list[dict[str, Any]] = []
        try:
            for line in self.filepath.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        except (json.JSONDecodeError, OSError):
            return []
        return events

    def _recent_restarts(
        self, events: list[dict[str, Any]], now: datetime
    ) -> list[dict[str, Any]]:
        """Return restarts that were allowed within the sliding window."""
        cutoff = now.timestamp() - self.window_s
        result = []
        for ev in events:
            if ev.get("decision") != "allowed":
                continue
            try:
                ts = datetime.fromisoformat(ev["at"]).timestamp()
                if ts >= cutoff:
                    result.append(ev)
            except (KeyError, ValueError, TypeError):
                continue
        return result

    def _last_denied(
        self, events: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Return the most recent denied restart, or None."""
        for ev in reversed(events):
            if ev.get("decision") == "denied":
                return ev
        return None

    def should_restart(
        self,
        reason: str = "unknown",
        now: datetime | None = None,
    ) -> RestartDecision:
        """Check whether a restart should proceed.

        Args:
            reason: human-readable reason for the restart attempt.
            now: override current time (for testing). Defaults to utcnow.

        Returns:
            A RestartDecision indicating whether the restart is allowed
            and how much cooldown remains if blocked.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        events = self._load_events()
        recent = self._recent_restarts(events, now)

        # Check if we're still in cooldown from a recent denial
        last_denied = self._last_denied(events)
        if last_denied is not None:
            try:
                denied_at = datetime.fromisoformat(last_denied["at"]).timestamp()
                denied_age = now.timestamp() - denied_at
                if denied_age < self.cooldown_s:
                    remaining = self.cooldown_s - denied_age
                    return RestartDecision(
                        allowed=False,
                        remaining_s=remaining,
                        restarts_in_window=len(recent),
                        reason=f"cooldown active ({remaining:.0f}s remaining)",
                    )
            except (KeyError, ValueError, TypeError):
                pass

        # Check if we've exceeded the restart budget
        if len(recent) >= self.max_restarts:
            # Record the denial
            self._record(now, reason, "denied", len(recent))
            return RestartDecision(
                allowed=False,
                remaining_s=float(self.cooldown_s),
                restarts_in_window=len(recent),
                reason=f"budget exhausted ({len(recent)}/{self.max_restarts} in window)",
            )

        # Allowed — record and proceed
        self._record(now, reason, "allowed", len(recent))
        return RestartDecision(
            allowed=True,
            remaining_s=0.0,
            restarts_in_window=len(recent) + 1,
            reason="within budget",
        )

    def _record(
        self,
        now: datetime,
        reason: str,
        decision: str,
        count_in_window: int,
    ) -> None:
        """Append a restart event to the log."""
        event = {
            "at": now.isoformat(),
            "reason": reason,
            "decision": decision,
            "restarts_in_window": count_in_window,
        }
        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the most recent restart events."""
        events = self._load_events()
        return events[-limit:]

    def reset(self) -> None:
        """Clear the cooldown log. Use after manual intervention."""
        if self.filepath.exists():
            self.filepath.write_text("", encoding="utf-8")
