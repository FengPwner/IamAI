#!/usr/bin/env python3
"""repo_triage.py — quick health triage for the IamAI repo.

Produces a compact, human-readable report that a caretaker can glance
at to decide whether the repo needs attention.  Combines signals from
several existing tools into a single view:

    - process status (writer / batch: running or dead?)
    - uncommitted file count
    - recent commit cadence (last 10 gaps, median, max)
    - push freshness (how far behind origin?)
    - stroke production rate (strokes in the last hour)

Usage:
    python3 tools/repo_triage.py
    python3 tools/repo_triage.py --json

Exit codes:
    0  all clear
    1  at least one red-flag condition detected
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import List, Optional

REPO = Path(__file__).resolve().parent.parent
CST = timezone(timedelta(hours=8))

# Thresholds
MAX_UNCOMMITTED = 5
MAX_COMMIT_GAP_MINUTES = 30
MIN_STROKES_PER_HOUR = 2
PUSH_LAG_THRESHOLD = 3  # commits behind origin


def _run(cmd: list[str], cwd: Path = REPO) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=15)
        return r.returncode, r.stdout.strip()
    except Exception as e:
        return 1, str(e)


@dataclass
class TriageSignal:
    name: str
    status: str  # "ok" | "warn" | "red"
    detail: str
    value: object = None


@dataclass
class TriageReport:
    timestamp: str
    signals: List[TriageSignal] = field(default_factory=list)
    verdict: str = "ok"  # "ok" | "warn" | "red"

    @property
    def red_count(self) -> int:
        return sum(1 for s in self.signals if s.status == "red")

    @property
    def warn_count(self) -> int:
        return sum(1 for s in self.signals if s.status == "warn")


def check_processes() -> TriageSignal:
    """Check whether writer and batch processes are running."""
    writer_alive = False
    batch_alive = False
    try:
        code, out = _run(["pgrep", "-af", "writer_loop"])
        writer_alive = code == 0 and "writer_loop" in out
    except Exception:
        pass
    try:
        code, out = _run(["pgrep", "-af", "commit_batch"])
        batch_alive = code == 0 and "commit_batch" in out
    except Exception:
        pass

    if writer_alive and batch_alive:
        return TriageSignal("processes", "ok", "writer and batch both running",
                            {"writer": True, "batch": True})
    elif writer_alive or batch_alive:
        dead = "batch" if writer_alive else "writer"
        return TriageSignal("processes", "red", f"{dead} process is NOT running",
                            {"writer": writer_alive, "batch": batch_alive})
    else:
        return TriageSignal("processes", "red", "NEITHER writer nor batch running",
                            {"writer": False, "batch": False})


def check_uncommitted() -> TriageSignal:
    """Count uncommitted file changes."""
    code, out = _run(["git", "status", "--porcelain"])
    if code != 0:
        return TriageSignal("uncommitted", "warn", "git status failed", 0)

    files = [line for line in out.split("\n") if line.strip()]
    count = len(files)

    if count == 0:
        return TriageSignal("uncommitted", "ok", "working tree clean", 0)
    elif count <= MAX_UNCOMMITTED:
        return TriageSignal("uncommitted", "ok", f"{count} file(s) uncommitted", count)
    else:
        return TriageSignal("uncommitted", "warn", f"{count} files uncommitted (>{MAX_UNCOMMITTED})", count)


def check_commit_cadence() -> TriageSignal:
    """Analyze recent commit gaps."""
    code, out = _run(["git", "log", "--format=%aI", "-15", "--reverse"])
    if code != 0 or not out:
        return TriageSignal("cadence", "warn", "git log failed", None)

    timestamps = []
    for line in out.strip().split("\n"):
        line = line.strip()
        if line:
            try:
                timestamps.append(datetime.fromisoformat(line))
            except ValueError:
                continue

    if len(timestamps) < 2:
        return TriageSignal("cadence", "warn", "fewer than 2 commits to analyze", len(timestamps))

    gaps_minutes = []
    for i in range(1, len(timestamps)):
        gap = (timestamps[i] - timestamps[i - 1]).total_seconds() / 60
        gaps_minutes.append(round(gap, 1))

    med = round(median(gaps_minutes), 1)
    max_gap = round(max(gaps_minutes), 1)

    if max_gap > MAX_COMMIT_GAP_MINUTES:
        return TriageSignal("cadence", "warn",
                            f"max gap {max_gap}min (median {med}min, {len(gaps_minutes)} gaps)",
                            {"median_min": med, "max_min": max_gap, "gaps": gaps_minutes})
    else:
        return TriageSignal("cadence", "ok",
                            f"median {med}min, max {max_gap}min ({len(gaps_minutes)} gaps)",
                            {"median_min": med, "max_min": max_gap, "gaps": gaps_minutes})


def check_push_freshness() -> TriageSignal:
    """Check how far behind origin we are."""
    code, out = _run(["git", "rev-list", "--count", "origin/main..HEAD"])
    if code != 0:
        # Try fetching first
        _run(["git", "fetch", "origin", "--quiet"])
        code, out = _run(["git", "rev-list", "--count", "origin/main..HEAD"])
        if code != 0:
            return TriageSignal("push_freshness", "warn", "could not compare with origin", None)

    try:
        behind = int(out.strip())
    except ValueError:
        return TriageSignal("push_freshness", "warn", "unexpected rev-list output", out)

    # Also check if we're behind origin (origin has commits we don't)
    code2, out2 = _run(["git", "rev-list", "--count", "HEAD..origin/main"])
    ahead_of_us = 0
    if code2 == 0:
        try:
            ahead_of_us = int(out2.strip())
        except ValueError:
            pass

    if ahead_of_us > PUSH_LAG_THRESHOLD:
        return TriageSignal("push_freshness", "red",
                            f"origin is {ahead_of_us} commits ahead — need pull",
                            {"unpushed": behind, "behind": ahead_of_us})
    elif behind > 0:
        return TriageSignal("push_freshness", "warn",
                            f"{behind} unpushed commit(s)",
                            {"unpushed": behind, "behind": ahead_of_us})
    else:
        return TriageSignal("push_freshness", "ok", "up to date with origin",
                            {"unpushed": 0, "behind": ahead_of_us})


def check_stroke_rate() -> TriageSignal:
    """Estimate recent stroke production rate from the state file."""
    state_path = REPO / "data" / "writer_state.qwen.json"
    if not state_path.exists():
        return TriageSignal("stroke_rate", "warn", "no writer state file found", None)

    try:
        import json as _json
        state = _json.loads(state_path.read_text())
        history = state.get("history", [])
    except Exception as e:
        return TriageSignal("stroke_rate", "warn", f"state file parse error: {e}", None)

    if not history:
        return TriageSignal("stroke_rate", "warn", "no stroke history in state", 0)

    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    recent = 0
    for entry in history:
        ts_str = entry.get("ts", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts >= one_hour_ago:
                recent += 1
        except (ValueError, AttributeError):
            continue

    if recent >= MIN_STROKES_PER_HOUR:
        return TriageSignal("stroke_rate", "ok", f"{recent} strokes in the last hour", recent)
    elif recent > 0:
        return TriageSignal("stroke_rate", "warn",
                            f"only {recent} stroke(s) in the last hour (min {MIN_STROKES_PER_HOUR})",
                            recent)
    else:
        return TriageSignal("stroke_rate", "red", "NO strokes in the last hour", recent)


def triage() -> TriageReport:
    """Run all triage checks and produce a report."""
    report = TriageReport(
        timestamp=datetime.now(CST).isoformat()
    )

    checks = [
        check_processes,
        check_uncommitted,
        check_commit_cadence,
        check_push_freshness,
        check_stroke_rate,
    ]

    for check in checks:
        try:
            signal = check()
        except Exception as e:
            signal = TriageSignal(check.__name__, "warn", f"check failed: {e}")
        report.signals.append(signal)

    # Compute overall verdict
    if report.red_count > 0:
        report.verdict = "red"
    elif report.warn_count > 0:
        report.verdict = "warn"
    else:
        report.verdict = "ok"

    return report


def format_text(report: TriageReport) -> str:
    """Format triage report as human-readable text."""
    lines = [f"=== REPO TRIAGE — {report.timestamp} ===", ""]

    icons = {"ok": "✓", "warn": "⚠", "red": "✗"}
    for s in report.signals:
        icon = icons.get(s.status, "?")
        lines.append(f"  {icon} {s.name}: {s.detail}")

    lines.append("")
    verdict_icon = icons.get(report.verdict, "?")
    lines.append(f"  VERDICT: {verdict_icon} {report.verdict.upper()}")
    if report.red_count > 0:
        lines.append(f"  {report.red_count} red flag(s) — immediate action needed")
    elif report.warn_count > 0:
        lines.append(f"  {report.warn_count} warning(s) — monitor closely")
    else:
        lines.append("  all clear — no action needed")

    return "\n".join(lines)


def format_json(report: TriageReport) -> str:
    """Format triage report as JSON."""
    data = {
        "timestamp": report.timestamp,
        "verdict": report.verdict,
        "signals": [asdict(s) for s in report.signals],
    }
    return json.dumps(data, indent=2, default=str)


def main():
    parser = argparse.ArgumentParser(description="Quick health triage for IamAI repo")
    parser.add_argument("--json", action="store_true", help="output JSON instead of text")
    args = parser.parse_args()

    report = triage()

    if args.json:
        print(format_json(report))
    else:
        print(format_text(report))

    sys.exit(1 if report.verdict == "red" else 0)


if __name__ == "__main__":
    main()
