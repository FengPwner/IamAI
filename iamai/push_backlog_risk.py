"""push_backlog_risk — estimate data-loss risk from unpushed commit backlog.

When pushes fail silently (amber SSH key, network blip), commits pile up
locally. If the container is recycled before the backlog drains, every
unpushed commit is gone. This module quantifies that risk so a caretaker
or automated alert can act before it becomes a loss event.

Risk tiers:
  LOW    — 0-5 unpushed commits, all < 1 hour old
  MEDIUM — 6-20 unpushed commits, or oldest > 1 hour
  HIGH   — 21-50 unpushed commits, or oldest > 6 hours
  CRITICAL — 50+ unpushed commits, or oldest > 24 hours, or SSH key missing

The thresholds come from observing this repo: a healthy writer produces
~6 commits/hour; 50 commits is ~8 hours of work that could vanish in a
single container recycle.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RiskTier(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class BacklogRisk:
    tier: RiskTier
    unpushed_count: int
    oldest_commit_age_s: float
    ssh_key_present: bool
    ssh_key_registered: bool
    summary: str

    def as_dict(self) -> dict:
        return {
            "tier": self.tier.value,
            "unpushed_count": self.unpushed_count,
            "oldest_commit_age_s": round(self.oldest_commit_age_s, 1),
            "ssh_key_present": self.ssh_key_present,
            "ssh_key_registered": self.ssh_key_registered,
            "summary": self.summary,
        }


def _count_unpushed(repo: str = ".") -> int:
    """Return the number of commits ahead of origin/main."""
    try:
        out = subprocess.run(
            ["git", "rev-list", "--count", "HEAD", "^origin/main"],
            capture_output=True, text=True, cwd=repo, timeout=10,
        )
        return int(out.stdout.strip()) if out.returncode == 0 else 0
    except (ValueError, subprocess.TimeoutExpired):
        return 0


def _oldest_unpushed_age_seconds(repo: str = ".") -> float:
    """Seconds since the oldest unpushed commit was authored."""
    try:
        out = subprocess.run(
            ["git", "log", "--format=%at", "origin/main..HEAD"],
            capture_output=True, text=True, cwd=repo, timeout=10,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return 0.0
        timestamps = [int(ts) for ts in out.stdout.strip().splitlines()]
        oldest = min(timestamps)
        return time.time() - oldest
    except (ValueError, subprocess.TimeoutExpired):
        return 0.0


def _check_ssh_key(key_path: str = "/root/.ssh/id_ed25519") -> tuple[bool, bool]:
    """Return (key_present, key_registered) via ssh -T test."""
    import os
    present = os.path.isfile(key_path)
    if not present:
        return False, False
    try:
        result = subprocess.run(
            ["ssh", "-T", "-o", "StrictHostKeyChecking=no",
             "-o", "ConnectTimeout=5", "-i", key_path,
             "git@github.com"],
            capture_output=True, text=True, timeout=15,
        )
        # GitHub returns exit 1 with "Hi <user>!" on success
        # exit 1 with "Permission denied" means key not registered
        combined = result.stdout + result.stderr
        registered = "successfully authenticated" in combined.lower() or \
                     "hi " in combined.lower()
        return True, registered
    except subprocess.TimeoutExpired:
        return True, False  # key exists but can't reach GitHub


def assess(
    repo: str = ".",
    key_path: str = "/root/.ssh/id_ed25519",
    unpushed_count: Optional[int] = None,
    oldest_age_s: Optional[float] = None,
    ssh_present: Optional[bool] = None,
    ssh_registered: Optional[bool] = None,
) -> BacklogRisk:
    """Assess push backlog risk. Override any field for testing."""
    if unpushed_count is None:
        unpushed_count = _count_unpushed(repo)
    if oldest_age_s is None:
        oldest_age_s = _oldest_unpushed_age_seconds(repo)
    if ssh_present is None or ssh_registered is None:
        p, r = _check_ssh_key(key_path)
        if ssh_present is None:
            ssh_present = p
        if ssh_registered is None:
            ssh_registered = r

    # Determine tier
    if not ssh_present or unpushed_count > 50 or oldest_age_s > 86400:
        tier = RiskTier.CRITICAL
    elif unpushed_count > 20 or oldest_age_s > 21600:
        tier = RiskTier.HIGH
    elif unpushed_count > 5 or oldest_age_s > 3600:
        tier = RiskTier.MEDIUM
    else:
        tier = RiskTier.LOW

    # Build summary
    parts = [f"{unpushed_count} unpushed commits"]
    if oldest_age_s > 3600:
        hours = oldest_age_s / 3600
        parts.append(f"oldest is {hours:.1f}h old")
    if not ssh_present:
        parts.append("SSH key MISSING")
    elif not ssh_registered:
        parts.append("SSH key not registered on GitHub")
    summary = "; ".join(parts)

    return BacklogRisk(
        tier=tier,
        unpushed_count=unpushed_count,
        oldest_commit_age_s=oldest_age_s,
        ssh_key_present=ssh_present,
        ssh_key_registered=ssh_registered,
        summary=summary,
    )


if __name__ == "__main__":
    risk = assess()
    d = risk.as_dict()
    print(f"[{d['tier']}] {d['summary']}")
    print(f"  unpushed: {d['unpushed_count']}  oldest: {d['oldest_commit_age_s']}s")
    print(f"  ssh_key: present={d['ssh_key_present']}  registered={d['ssh_key_registered']}")
