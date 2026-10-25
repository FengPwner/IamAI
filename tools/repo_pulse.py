#!/usr/bin/env python3
"""repo_pulse.py — quick multi-signal health check for the writing system.

Combines several health indicators into a single summary:
  - writer process alive
  - last stroke age
  - last commit age
  - pending (uncommitted) file count
  - stroke diversity balance
  - recent stall count

Usage:
    python3 tools/repo_pulse.py
    python3 tools/repo_pulse.py --json
    python3 tools/repo_pulse.py --writer qwen

Exit codes:
    0  healthy  — all signals green
    1  warning  — one or more signals degraded
    2  critical — writer down or major stall
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_WRITER = "qwen"
DEFAULT_KINDS = ("devlog", "garden", "metrics", "note", "snippet", "thought")

# Thresholds
STROKE_FRESH_S = 120       # last stroke within 2 min → green
STROKE_STALE_S = 600       # last stroke within 10 min → yellow, else red
COMMIT_FRESH_S = 900       # last commit within 15 min → green
COMMIT_STALE_S = 3600      # last commit within 1 hr → yellow, else red
PENDING_WARN = 5           # more than 5 uncommitted files → yellow
PENDING_CRIT = 20          # more than 20 → red
DIVERSITY_WARN = 0.3       # imbalance score thresholds
DIVERSITY_CRIT = 0.5
STALL_WARN = 2             # number of recent stalls
STALL_CRIT = 5


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def check_writer_alive(writer: str) -> dict:
    """Check if the writer process is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"writer_loop.*--writer {writer}"],
            capture_output=True, text=True, timeout=5,
        )
        alive = result.returncode == 0
        pids = result.stdout.strip().split("\n") if alive else []
        return {"signal": "writer_alive", "status": "green" if alive else "red",
                "alive": alive, "pids": [p for p in pids if p]}
    except Exception as exc:
        return {"signal": "writer_alive", "status": "red",
                "alive": False, "pids": [], "error": str(exc)}


def check_last_stroke_age(state_path: Path) -> dict:
    """Check how old the most recent stroke is."""
    if not state_path.exists():
        return {"signal": "stroke_age", "status": "red",
                "age_seconds": None, "error": "state file missing"}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        history = data.get("history", [])
        if not history:
            return {"signal": "stroke_age", "status": "red",
                    "age_seconds": None, "error": "empty history"}
        last = history[-1]
        last_at = datetime.fromisoformat(last["at"])
        age_s = (now_utc() - last_at).total_seconds()
        if age_s <= STROKE_FRESH_S:
            status = "green"
        elif age_s <= STROKE_STALE_S:
            status = "yellow"
        else:
            status = "red"
        return {"signal": "stroke_age", "status": status,
                "age_seconds": round(age_s), "last_kind": last.get("kind"),
                "last_seq": last.get("seq")}
    except Exception as exc:
        return {"signal": "stroke_age", "status": "red",
                "age_seconds": None, "error": str(exc)}


def check_last_commit_age() -> dict:
    """Check how old the most recent commit is."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%aI"],
            capture_output=True, text=True, cwd=REPO, timeout=5,
        )
        if result.returncode != 0:
            return {"signal": "commit_age", "status": "red",
                    "age_seconds": None, "error": "git log failed"}
        last_at = datetime.fromisoformat(result.stdout.strip())
        age_s = (now_utc() - last_at).total_seconds()
        if age_s <= COMMIT_FRESH_S:
            status = "green"
        elif age_s <= COMMIT_STALE_S:
            status = "yellow"
        else:
            status = "red"
        return {"signal": "commit_age", "status": status,
                "age_seconds": round(age_s)}
    except Exception as exc:
        return {"signal": "commit_age", "status": "red",
                "age_seconds": None, "error": str(exc)}


def check_pending_files() -> dict:
    """Count uncommitted modified files."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=REPO, timeout=5,
        )
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        count = len(lines)
        if count == 0:
            status = "green"
        elif count <= PENDING_WARN:
            status = "green"
        elif count <= PENDING_CRIT:
            status = "yellow"
        else:
            status = "red"
        return {"signal": "pending_files", "status": status, "count": count}
    except Exception as exc:
        return {"signal": "pending_files", "status": "red",
                "count": None, "error": str(exc)}


def check_diversity(state_path: Path, window: int = 60) -> dict:
    """Check stroke kind balance over the last N strokes."""
    if not state_path.exists():
        return {"signal": "diversity", "status": "red",
                "imbalance": None, "error": "state file missing"}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        history = data.get("history", [])
        recent = history[-window:] if len(history) >= window else history
        if len(recent) < 6:
            return {"signal": "diversity", "status": "yellow",
                    "imbalance": None, "error": "too few strokes"}
        from collections import Counter
        raw_counts = Counter(s.get("kind") for s in recent)
        # Always measure against the full set of expected kinds so that
        # missing kinds register as a deviation.
        all_kinds = set(raw_counts.keys()) | set(DEFAULT_KINDS)
        counts = {k: raw_counts.get(k, 0) for k in all_kinds}
        expected = len(recent) / len(all_kinds)
        if expected == 0:
            return {"signal": "diversity", "status": "yellow",
                    "imbalance": None, "error": "no kinds found"}
        max_dev = max(abs(c - expected) for c in counts.values()) / expected
        if max_dev <= DIVERSITY_WARN:
            status = "green"
        elif max_dev <= DIVERSITY_CRIT:
            status = "yellow"
        else:
            status = "red"
        return {"signal": "diversity", "status": status,
                "imbalance": round(max_dev, 3),
                "distribution": dict(raw_counts),
                "window": len(recent)}
    except Exception as exc:
        return {"signal": "diversity", "status": "red",
                "imbalance": None, "error": str(exc)}


def aggregate(signals: list[dict]) -> str:
    """Aggregate individual signal statuses into an overall verdict."""
    statuses = [s["status"] for s in signals]
    if "red" in statuses:
        return "critical"
    if "yellow" in statuses:
        return "warning"
    return "healthy"


def run_pulse(writer: str = DEFAULT_WRITER) -> dict:
    """Run all health checks and return the pulse report."""
    state_path = REPO / "data" / f"writer_state.{writer}.json"
    signals = [
        check_writer_alive(writer),
        check_last_stroke_age(state_path),
        check_last_commit_age(),
        check_pending_files(),
        check_diversity(state_path),
    ]
    verdict = aggregate(signals)
    return {
        "verdict": verdict,
        "writer": writer,
        "checked_at": now_utc().isoformat(),
        "signals": signals,
    }


def format_text(report: dict) -> str:
    """Format pulse report as human-readable text."""
    v = report["verdict"]
    icon = {"healthy": "[OK]", "warning": "[WARN]", "critical": "[CRIT]"}
    lines = [f"repo pulse: {icon.get(v, '[?]')} {v}  (writer={report['writer']})"]
    for s in report["signals"]:
        status_icon = {"green": "+", "yellow": "!", "red": "x"}
        si = status_icon.get(s["status"], "?")
        detail = ""
        if s["signal"] == "writer_alive":
            detail = f"pids={s.get('pids', [])}" if s.get("alive") else "DOWN"
        elif s["signal"] == "stroke_age":
            age = s.get("age_seconds")
            detail = f"{age}s ago (kind={s.get('last_kind')}, seq={s.get('last_seq')})" if age else s.get("error", "?")
        elif s["signal"] == "commit_age":
            age = s.get("age_seconds")
            detail = f"{age}s ago" if age else s.get("error", "?")
        elif s["signal"] == "pending_files":
            detail = f"{s.get('count', '?')} files"
        elif s["signal"] == "diversity":
            imb = s.get("imbalance")
            detail = f"imbalance={imb}" if imb else s.get("error", "?")
        lines.append(f"  [{si}] {s['signal']}: {detail}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Quick health check for the writing system.")
    parser.add_argument("--writer", default=DEFAULT_WRITER, help="Writer name (default: qwen)")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    args = parser.parse_args()

    report = run_pulse(writer=args.writer)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_text(report))

    exit_code = {"healthy": 0, "warning": 1, "critical": 2}.get(report["verdict"], 2)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
