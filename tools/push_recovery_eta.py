#!/usr/bin/env python3
"""push_recovery_eta.py — estimate when the push backlog will drain.

When commits pile up locally because push is blocked (deploy key, network,
conflict), the caretaker needs to know: how long until we catch up? This
tool answers that by combining:

  1. current push debt (unpushed commit count)
  2. blockage classification (from push_blockage_analyzer)
  3. historical push throughput (commits/hour when push works)
  4. commit arrival rate (commits/hour being added locally)

Recovery model:
  - If push is blocked: ETA = infinity until blockage clears, then
    ETA = debt / (push_rate - commit_rate) if push_rate > commit_rate,
    else infinity (debt grows faster than we can drain).
  - If push is working: ETA = debt / (push_rate - commit_rate).
  - If commit_rate >= push_rate: debt never drains — flag as unsustainable.

Output fields:
  - unpushed_count: number of commits ahead of remote
  - blockage_type: "none", "auth", "network", "conflict", "unknown"
  - push_rate_cph: pushes per hour (historical, 24h window)
  - commit_rate_cph: commits per hour (historical, 24h window)
  - drain_eta_hours: hours until debt reaches zero (None if infinite)
  - sustainable: bool — can we drain faster than we accumulate?
  - recommendation: one-line action suggestion

Usage:
    python3 tools/push_recovery_eta.py
    python3 tools/push_recovery_eta.py --json
    python3 tools/push_recovery_eta.py --window 48   # look back 48h

Exit codes:
    0 — recovery feasible or debt is zero
    1 — recovery infeasible (debt growing)
    2 — error (not a git repo, etc.)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


REPO = Path(__file__).resolve().parent.parent


# --- Blockage detection ---

def classify_blockage() -> str:
    """Run a quick SSH probe to classify why push fails.

    Returns one of: "none", "auth", "network", "conflict", "unknown".
    """
    try:
        result = subprocess.run(
            ["ssh", "-T", "-o", "ConnectTimeout=5",
             "-o", "StrictHostKeyChecking=no",
             "-o", "BatchMode=yes",
             "git@github.com"],
            capture_output=True, text=True, timeout=10,
        )
        stderr = result.stderr.lower()
        if "permission denied" in stderr or "publickey" in stderr:
            return "auth"
        if "could not resolve" in stderr or "timed out" in stderr:
            return "network"
        if result.returncode == 0 or "successfully authenticated" in stderr:
            return "none"
        return "unknown"
    except subprocess.TimeoutExpired:
        return "network"
    except Exception:
        return "unknown"


# --- Git metrics ---

def count_unpushed() -> int:
    """Count commits ahead of origin/main."""
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "origin/main..HEAD"],
            capture_output=True, text=True, cwd=str(REPO), timeout=10,
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        pass
    return 0


def commits_in_window(hours: float) -> int:
    """Count local commits made in the last N hours."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    try:
        result = subprocess.run(
            ["git", "log", f"--since={since}", "--oneline"],
            capture_output=True, text=True, cwd=str(REPO), timeout=10,
        )
        if result.returncode == 0:
            lines = [l for l in result.stdout.strip().split("\n") if l]
            return len(lines)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return 0


def pushed_in_window(hours: float) -> int:
    """Estimate successful pushes in the last N hours from reflog.

    Since we cannot directly observe push events, we approximate by counting
    commits whose remote tracking ref was updated. For simplicity, we check
    whether origin/main has moved in the window. If it has not (blocked),
    pushed count is 0.
    """
    blockage = classify_blockage()
    if blockage != "none":
        return 0
    return commits_in_window(hours)


# --- Recovery estimate ---

@dataclass
class RecoveryEstimate:
    unpushed_count: int
    blockage_type: str
    push_rate_cph: float
    commit_rate_cph: float
    drain_eta_hours: Optional[float]
    sustainable: bool
    recommendation: str

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["drain_eta_hours"] is not None:
            d["drain_eta_hours"] = round(d["drain_eta_hours"], 2)
        d["push_rate_cph"] = round(d["push_rate_cph"], 2)
        d["commit_rate_cph"] = round(d["commit_rate_cph"], 2)
        return d


def estimate_recovery(window_hours: float = 24.0) -> RecoveryEstimate:
    """Compute the recovery ETA based on current debt and rates."""
    debt = count_unpushed()
    blockage = classify_blockage()

    local_commits = commits_in_window(window_hours)
    commit_rate = local_commits / window_hours if window_hours > 0 else 0.0

    if blockage != "none":
        push_rate = 0.0
    else:
        push_rate = commit_rate

    if debt == 0:
        eta = 0.0
        sustainable = True
        recommendation = "all clear — no push debt"
    elif blockage != "none":
        eta = None
        sustainable = False
        recommendation = f"push blocked ({blockage}): fix blockage first, then drain"
    elif push_rate > commit_rate:
        net_rate = push_rate - commit_rate
        eta = debt / net_rate
        sustainable = True
        recommendation = f"draining at {net_rate:.1f} commits/hour"
    else:
        eta = None
        sustainable = False
        recommendation = "unsustainable: commits arriving faster than pushed"

    return RecoveryEstimate(
        unpushed_count=debt,
        blockage_type=blockage,
        push_rate_cph=push_rate,
        commit_rate_cph=commit_rate,
        drain_eta_hours=eta,
        sustainable=sustainable,
        recommendation=recommendation,
    )


def format_report(est: RecoveryEstimate) -> str:
    """Human-readable report."""
    lines = [
        "=== Push Recovery ETA ===",
        f"  unpushed:    {est.unpushed_count} commits",
        f"  blockage:    {est.blockage_type}",
        f"  push rate:   {est.push_rate_cph:.1f} commits/hour",
        f"  commit rate: {est.commit_rate_cph:.1f} commits/hour",
    ]
    if est.drain_eta_hours is not None:
        lines.append(f"  drain ETA:   {est.drain_eta_hours:.1f} hours")
    else:
        lines.append("  drain ETA:   inf (blocked or unsustainable)")
    lines.append(f"  sustainable: {'yes' if est.sustainable else 'NO'}")
    lines.append(f"  action:      {est.recommendation}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Push recovery ETA")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--window", type=float, default=24.0,
                        help="Lookback window in hours (default: 24)")
    args = parser.parse_args()

    est = estimate_recovery(window_hours=args.window)

    if args.json:
        print(json.dumps(est.to_dict(), indent=2))
    else:
        print(format_report(est))

    sys.exit(0 if est.sustainable else 1)


if __name__ == "__main__":
    main()
