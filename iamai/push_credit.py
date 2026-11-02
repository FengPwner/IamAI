"""push_credit.py — track push success/failure history and compute reliability.

while push_debt measures what you owe (unpushed commits), push_credit
measures what you've earned: a record of push attempts and their outcomes.

every push attempt — success or failure — is logged as a PushEvent.
from this append-only log we derive:

  - success_rate:   fraction of attempts that succeeded
  - failure_streak: current consecutive failures (0 if last was success)
  - reliability:    weighted score combining rate, streak, and recency

reliability formula:

    reliability = success_rate × recency_weight

    where recency_weight = 1.0 if the last attempt was within 1 hour,
    decaying to 0.5 at 24 hours and 0.1 beyond 72 hours.

this answers: "how trustworthy is my push pipeline right now?"
a reliability below 0.5 means the pipeline is broken more often than not.

usage:
    python3 -m iamai.push_credit              # current reliability report
    python3 -m iamai.push_credit --json       # machine-readable output
    python3 -m iamai.push_credit --record ok  # log a successful push
    python3 -m iamai.push_credit --record fail --reason "rejected"

design: this module records and measures; it never auto-fixes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
CREDIT_LOG = DATA_DIR / "push_credit.jsonl"


class Outcome(str, Enum):
    OK = "ok"
    FAIL = "fail"


@dataclass
class PushEvent:
    """a single push attempt — outcome, timestamp, optional reason."""
    timestamp: str
    outcome: str
    reason: str = ""
    remote: str = "origin"
    branch: str = "main"


@dataclass
class ReliabilityReport:
    """derived metrics from the push credit log."""
    total_attempts: int
    successes: int
    failures: int
    success_rate: float
    failure_streak: int
    hours_since_last: float
    recency_weight: float
    reliability: float


# -- log i/o ----------------------------------------------------------------

def record_event(event: PushEvent) -> None:
    """append a push event to the credit log."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CREDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(event)) + "\n")


def load_events(limit: int = 0) -> list[PushEvent]:
    """load events from the credit log. limit=0 means all."""
    if not CREDIT_LOG.exists():
        return []

    events = []
    for line in CREDIT_LOG.read_text(encoding="utf-8").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            events.append(PushEvent(**data))
        except (json.JSONDecodeError, TypeError, KeyError):
            continue

    if limit > 0:
        return events[-limit:]
    return events


# -- computation ------------------------------------------------------------

def _parse_ts(ts_str: str) -> Optional[datetime]:
    """parse an ISO timestamp, return None on failure."""
    try:
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


def compute_recency_weight(hours: float) -> float:
    """decay factor based on how recently the last push was attempted.

    within 1 hour:  1.0
    at 24 hours:    0.5
    beyond 72 hours: 0.1
    linear interpolation between breakpoints.
    """
    if hours <= 1.0:
        return 1.0
    elif hours <= 24.0:
        # linear decay from 1.0 to 0.5 over 1..24 hours
        return 1.0 - 0.5 * (hours - 1.0) / 23.0
    elif hours <= 72.0:
        # linear decay from 0.5 to 0.1 over 24..72 hours
        return 0.5 - 0.4 * (hours - 24.0) / 48.0
    else:
        return 0.1


def compute_reliability(events: list[PushEvent]) -> ReliabilityReport:
    """compute reliability metrics from a list of push events."""
    total = len(events)
    if total == 0:
        return ReliabilityReport(
            total_attempts=0,
            successes=0,
            failures=0,
            success_rate=0.0,
            failure_streak=0,
            hours_since_last=float("inf"),
            recency_weight=0.0,
            reliability=0.0,
        )

    successes = sum(1 for e in events if e.outcome == Outcome.OK.value)
    failures = total - successes
    success_rate = successes / total if total > 0 else 0.0

    # failure streak: count consecutive failures from the end
    streak = 0
    for e in reversed(events):
        if e.outcome == Outcome.FAIL.value:
            streak += 1
        else:
            break

    # recency: hours since last attempt
    now = datetime.now(timezone.utc)
    last_ts = _parse_ts(events[-1].timestamp)
    if last_ts is not None:
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        hours_since = (now - last_ts).total_seconds() / 3600.0
    else:
        hours_since = float("inf")

    recency = compute_recency_weight(max(0.0, hours_since))

    # reliability = success_rate × recency, penalized by streak
    streak_penalty = max(0.0, 1.0 - streak * 0.15)
    reliability = success_rate * recency * streak_penalty

    return ReliabilityReport(
        total_attempts=total,
        successes=successes,
        failures=failures,
        success_rate=round(success_rate, 4),
        failure_streak=streak,
        hours_since_last=round(hours_since, 2),
        recency_weight=round(recency, 4),
        reliability=round(reliability, 4),
    )


# -- live push probe --------------------------------------------------------

def probe_push(remote: str = "origin", branch: str = "main") -> PushEvent:
    """attempt a push and record the result."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO), "push", remote, branch],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return PushEvent(timestamp=now, outcome=Outcome.OK.value,
                             remote=remote, branch=branch)
        else:
            reason = result.stderr.strip().split("\n")[-1] if result.stderr else "unknown"
            return PushEvent(timestamp=now, outcome=Outcome.FAIL.value,
                             reason=reason[:200], remote=remote, branch=branch)
    except subprocess.TimeoutExpired:
        return PushEvent(timestamp=now, outcome=Outcome.FAIL.value,
                         reason="timeout after 30s", remote=remote, branch=branch)
    except Exception as e:
        return PushEvent(timestamp=now, outcome=Outcome.FAIL.value,
                         reason=str(e)[:200], remote=remote, branch=branch)


# -- reporting --------------------------------------------------------------

def format_report(report: ReliabilityReport) -> str:
    """format a reliability report for human reading."""
    lines = [
        "=== Push Credit Report ===",
        f"  total attempts:   {report.total_attempts}",
        f"  successes:        {report.successes}",
        f"  failures:         {report.failures}",
        f"  success rate:     {report.success_rate:.1%}",
        f"  failure streak:   {report.failure_streak}",
        f"  hours since last: {report.hours_since_last:.1f}",
        f"  recency weight:   {report.recency_weight:.2f}",
        f"  reliability:      {report.reliability:.2f}",
    ]

    if report.reliability < 0.3:
        lines.append("")
        lines.append("  WARNING: push pipeline is unreliable.")
        lines.append("  investigate push failures immediately.")
    elif report.reliability < 0.5:
        lines.append("")
        lines.append("  NOTICE: push reliability is below 50%.")
        lines.append("  check push credentials and network.")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="push credit tracker")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--record", choices=["ok", "fail"],
                        help="record a push outcome")
    parser.add_argument("--reason", default="", help="failure reason")
    parser.add_argument("--probe", action="store_true",
                        help="attempt a live push and record result")
    parser.add_argument("--remote", default="origin", help="remote name")
    parser.add_argument("--branch", default="main", help="branch name")
    args = parser.parse_args()

    if args.record:
        event = PushEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            outcome=args.record,
            reason=args.reason if args.record == "fail" else "",
            remote=args.remote,
            branch=args.branch,
        )
        record_event(event)

    if args.probe:
        event = probe_push(remote=args.remote, branch=args.branch)
        record_event(event)
        if not args.json:
            print(f"push: {event.outcome}" +
                  (f" ({event.reason})" if event.reason else ""))

    events = load_events()
    report = compute_reliability(events)

    if args.json:
        print(json.dumps(asdict(report), indent=2))
    elif not args.record and not args.probe:
        print(format_report(report))

    if report.reliability < 0.3:
        return 3
    elif report.reliability < 0.5:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
