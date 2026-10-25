#!/usr/bin/env python3
"""Compute a single "repo temperature" reading — how hot or cold the repo is.

Temperature is a metaphor from chemistry: a hot repo has lots of reactions
happening (commits, strokes, active writers), while a cold one is frozen.

The reading is a float in [0, 100] derived from four signals:

    - commit_heat:    time since last commit, scaled to batch interval
    - writer_heat:    is the writer process alive? (binary 0/25)
    - stroke_heat:    how many strokes in the last hour? (capped at 240)
    - breadth_heat:   how many distinct stroke categories updated recently?

Exit codes:
    0  temperature >= 50  (warm / active)
    1  temperature < 50    (cooling)
    2  temperature < 20    (cold / stalled)
    3  error

Usage:
    python3 tools/repo_temperature.py              # human-readable
    python3 tools/repo_temperature.py --json       # machine-readable
    python3 tools/repo_temperature.py --interval 600
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List

REPO = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class HeatSource:
    name: str
    value: float          # 0–25
    max: float = 25.0
    detail: str = ""


@dataclass(frozen=True)
class TemperatureReport:
    temperature: float
    grade: str            # hot / warm / cool / cold
    sources: List[HeatSource]
    timestamp: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sources"] = [asdict(s) for s in self.sources]
        return d


# ── Helpers ───────────────────────────────────────────────────────────


def _git(*args: str) -> str:
    """Run a git command in the repo root, return stdout."""
    r = subprocess.run(
        ["git", "-C", str(REPO)] + list(args),
        capture_output=True, text=True, timeout=10,
    )
    return r.stdout.strip()


def _seconds_since_last_commit() -> float:
    """Return seconds since the most recent commit."""
    ts = _git("log", "-1", "--format=%ct")
    if not ts:
        return float("inf")
    try:
        return time.time() - float(ts)
    except ValueError:
        return float("inf")


def _writer_alive(writer_id: str) -> bool:
    """Check if the writer process is alive via its pidfile."""
    pidfile = Path(f"/tmp/iamai-writer-{writer_id}.pid")
    if not pidfile.exists():
        return False
    try:
        pid = int(pidfile.read_text().strip())
        import os
        os.kill(pid, 0)  # signal 0 = check existence
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        return False


def _recent_strokes(lookback_seconds: int = 3600) -> int:
    """Count strokes written in the last `lookback_seconds` seconds."""
    strokes_file = REPO / "data" / "strokes.jsonl"
    if not strokes_file.exists():
        return 0
    cutoff = time.time() - lookback_seconds
    count = 0
    try:
        lines = strokes_file.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = entry.get("ts", 0)
                if ts < cutoff:
                    break
                count += 1
            except (json.JSONDecodeError, KeyError):
                continue
    except OSError:
        pass
    return count


def _recent_categories(lookback_seconds: int = 3600) -> int:
    """Count distinct stroke categories updated in the last `lookback_seconds`."""
    strokes_file = REPO / "data" / "strokes.jsonl"
    if not strokes_file.exists():
        return 0
    cutoff = time.time() - lookback_seconds
    cats = set()
    try:
        lines = strokes_file.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = entry.get("ts", 0)
                if ts < cutoff:
                    break
                cat = entry.get("category", "unknown")
                cats.add(cat)
            except (json.JSONDecodeError, KeyError):
                continue
    except OSError:
        pass
    return len(cats)


# ── Scoring ───────────────────────────────────────────────────────────


def score_commit_heat(age_seconds: float, interval: int = 600) -> HeatSource:
    """25 points if the last commit was within one batch interval, decaying to 0."""
    if age_seconds <= interval:
        val = 25.0
    elif age_seconds >= 5 * interval:
        val = 0.0
    else:
        # linear decay from 25 to 0 over [interval, 5*interval]
        val = 25.0 * (1.0 - (age_seconds - interval) / (4.0 * interval))
        val = max(0.0, val)
    return HeatSource(
        name="commit_heat",
        value=round(val, 2),
        detail=f"last commit {age_seconds:.0f}s ago, interval {interval}s",
    )


def score_writer_heat(alive: bool) -> HeatSource:
    """25 points if the writer process is alive, 0 otherwise."""
    return HeatSource(
        name="writer_heat",
        value=25.0 if alive else 0.0,
        detail="writer running" if alive else "writer not running",
    )


def score_stroke_heat(count: int, cap: int = 240) -> HeatSource:
    """25 points if `cap` or more strokes in the lookback window, proportional below."""
    if count >= cap:
        val = 25.0
    else:
        val = 25.0 * (count / cap)
    return HeatSource(
        name="stroke_heat",
        value=round(val, 2),
        detail=f"{count} strokes in last hour (cap {cap})",
    )


def score_breadth_heat(categories: int, target: int = 6) -> HeatSource:
    """25 points if all `target` categories are active, proportional below."""
    if categories >= target:
        val = 25.0
    else:
        val = 25.0 * (categories / target)
    return HeatSource(
        name="breadth_heat",
        value=round(val, 2),
        detail=f"{categories}/{target} categories active in last hour",
    )


def classify(temperature: float) -> str:
    """Map temperature to a human-readable grade."""
    if temperature >= 70:
        return "hot"
    if temperature >= 50:
        return "warm"
    if temperature >= 20:
        return "cool"
    return "cold"


# ── Orchestrator ──────────────────────────────────────────────────────


def measure(
    writer_id: str = "qwen",
    interval: int = 600,
) -> TemperatureReport:
    """Gather all signals and produce a temperature report."""
    age = _seconds_since_last_commit()
    alive = _writer_alive(writer_id)
    strokes = _recent_strokes(3600)
    cats = _recent_categories(3600)

    sources = [
        score_commit_heat(age, interval),
        score_writer_heat(alive),
        score_stroke_heat(strokes),
        score_breadth_heat(cats),
    ]
    temp = sum(s.value for s in sources)
    return TemperatureReport(
        temperature=round(temp, 2),
        grade=classify(temp),
        sources=sources,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def as_text(report: TemperatureReport) -> str:
    """Format report for terminal output."""
    lines = [
        f"repo temperature: {report.temperature:.1f}/100  [{report.grade}]",
        f"  measured at: {report.timestamp}",
        "",
    ]
    for s in report.sources:
        bar_len = int(s.value / s.max * 20)
        bar = "#" * bar_len + "." * (20 - bar_len)
        lines.append(f"  {s.name:16s}  [{bar}]  {s.value:5.1f}/{s.max:.0f}  {s.detail}")
    lines.append("")
    lines.append(f"  total: {report.temperature:.1f}/100")
    return "\n".join(lines)


def run(writer_id: str = "qwen", interval: int = 600, as_json: bool = False) -> int:
    report = measure(writer_id=writer_id, interval=interval)
    if as_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(as_text(report))
    if report.temperature >= 50:
        return 0
    if report.temperature >= 20:
        return 1
    return 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--writer", default="qwen", help="writer id to check")
    ap.add_argument("--interval", type=int, default=600, help="batch interval in seconds")
    ap.add_argument("--json", action="store_true", dest="as_json", help="output JSON")
    args = ap.parse_args()
    return run(writer_id=args.writer, interval=args.interval, as_json=args.as_json)


if __name__ == "__main__":
    sys.exit(main())
