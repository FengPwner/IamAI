#!/usr/bin/env python3
"""restart_audit.py — classify gaps in writer stroke history.

Distinguishes between three gap types:
  healthy:  gap < 2× cadence (normal variance)
  stall:    gap between 2× and 10× cadence (writer struggling)
  restart:  gap > 10× cadence (process died and was relaunched)

This matters because the heartbeat probe reports any gap > 2× cadence
as a stall, but a restart gap is qualitatively different — the process
was dead, not slow. Knowing which happened tells you what to fix.

Usage:
    python3 tools/restart_audit.py [--writer qwen] [--cadence 15]
    python3 tools/restart_audit.py --json
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load_history(state_path: Path) -> list[dict]:
    """Load stroke history from writer state file."""
    if not state_path.exists():
        return []
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data.get("history", [])


def classify_gap(gap_seconds: float, cadence: int,
                 stall_multiplier: float = 2.0,
                 restart_multiplier: float = 10.0) -> str:
    """Classify a single gap duration.

    Returns one of: "healthy", "stall", "restart".
    """
    if gap_seconds < 0:
        return "healthy"  # clock skew — treat as noise, not a gap
    if gap_seconds < cadence * stall_multiplier:
        return "healthy"
    if gap_seconds < cadence * restart_multiplier:
        return "stall"
    return "restart"


def audit_gaps(history: list[dict], cadence: int = 15,
               stall_multiplier: float = 2.0,
               restart_multiplier: float = 10.0) -> list[dict]:
    """Audit all gaps in the stroke history.

    Returns a list of gap records:
        {
            "index": position in history (1-based for the second stroke),
            "from_at": ISO timestamp of the stroke before the gap,
            "to_at": ISO timestamp of the stroke after the gap,
            "gap_seconds": duration of the gap,
            "kind": "healthy" | "stall" | "restart"
        }
    """
    if len(history) < 2:
        return []

    gaps = []
    for i in range(1, len(history)):
        prev = history[i - 1]
        curr = history[i]
        try:
            prev_time = datetime.fromisoformat(prev["at"])
            curr_time = datetime.fromisoformat(curr["at"])
        except (KeyError, ValueError):
            continue

        gap = (curr_time - prev_time).total_seconds()
        kind = classify_gap(gap, cadence, stall_multiplier, restart_multiplier)

        gaps.append({
            "index": i,
            "from_at": prev["at"],
            "to_at": curr["at"],
            "gap_seconds": round(gap, 1),
            "kind": kind,
        })

    return gaps


def summarize(gaps: list[dict]) -> dict:
    """Produce a summary of the audit.

    Returns counts per category and the most recent non-healthy gap
    (if any), which is usually the actionable one.
    """
    counts = {"healthy": 0, "stall": 0, "restart": 0}
    latest_problem = None

    for g in gaps:
        counts[g["kind"]] = counts.get(g["kind"], 0) + 1
        if g["kind"] != "healthy":
            latest_problem = g

    return {
        "total_gaps": len(gaps),
        "counts": counts,
        "latest_problem": latest_problem,
    }


def as_text(summary: dict) -> str:
    """Human-readable one-liner for the audit summary."""
    c = summary["counts"]
    parts = [f"{summary['total_gaps']} gaps"]
    if c.get("restart"):
        parts.append(f"{c['restart']} restart(s)")
    if c.get("stall"):
        parts.append(f"{c['stall']} stall(s)")
    parts.append(f"{c.get('healthy', 0)} healthy")

    line = ", ".join(parts)
    if summary["latest_problem"]:
        lp = summary["latest_problem"]
        line += f" | last issue: {lp['kind']} gap {lp['gap_seconds']}s at {lp['to_at']}"
    return line


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--writer", default="qwen", help="writer id")
    ap.add_argument("--cadence", type=int, default=15, help="expected stroke interval in seconds")
    ap.add_argument("--stall-x", type=float, default=2.0, help="stall threshold multiplier")
    ap.add_argument("--restart-x", type=float, default=10.0, help="restart threshold multiplier")
    ap.add_argument("--json", action="store_true", help="full JSON output")
    args = ap.parse_args()

    state_path = REPO / "data" / f"writer_state.{args.writer}.json"
    history = load_history(state_path)
    gaps = audit_gaps(history, cadence=args.cadence,
                      stall_multiplier=args.stall_x,
                      restart_multiplier=args.restart_x)

    if args.json:
        print(json.dumps({"gaps": gaps, "summary": summarize(gaps)},
                         ensure_ascii=False, indent=2))
    else:
        print(as_text(summarize(gaps)))

    # exit 1 if there are any restart gaps (process died at some point)
    s = summarize(gaps)
    return 1 if s["counts"].get("restart", 0) > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
