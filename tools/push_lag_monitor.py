#!/usr/bin/env python3
"""push_lag_monitor.py — measure how far local commits have drifted from origin.

a commit that sits on disk but never reaches the remote is invisible to
collaborators and vulnerable to garbage collection. this tool computes
*push lag*: the wall-clock seconds between the newest local commit and
the newest commit that origin knows about.

lag categories:
  - nominal:   lag < 600s  (one batch interval)
  - warning:   lag < 1800s (three batch intervals)
  - critical:  lag >= 1800s

usage:
    python3 tools/push_lag_monitor.py
    python3 tools/push_lag_monitor.py --writer qwen --threshold 1200
    python3 tools/push_lag_monitor.py --json

exit codes:
    0 — nominal
    1 — warning or critical
    2 — error (e.g. no remote, no commits)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


class PushLag:
    """Snapshot of local-vs-remote commit divergence."""

    __slots__ = ("local_sha", "remote_sha", "local_ts", "remote_ts",
                 "lag_seconds", "unpushed_count", "category")

    NOMINAL = "nominal"
    WARNING = "warning"
    CRITICAL = "critical"

    def __init__(self, local_sha: str, remote_sha: str,
                 local_ts: float, remote_ts: float,
                 unpushed_count: int, warning_threshold: int = 600,
                 critical_threshold: int = 1800):
        self.local_sha = local_sha
        self.remote_sha = remote_sha
        self.local_ts = local_ts
        self.remote_ts = remote_ts
        self.lag_seconds = max(0.0, local_ts - remote_ts)
        self.unpushed_count = unpushed_count

        if self.lag_seconds < warning_threshold:
            self.category = self.NOMINAL
        elif self.lag_seconds < critical_threshold:
            self.category = self.WARNING
        else:
            self.category = self.CRITICAL

    def to_dict(self) -> dict:
        return {
            "local_sha": self.local_sha[:12],
            "remote_sha": self.remote_sha[:12] if self.remote_sha else "none",
            "local_ts": self.local_ts,
            "remote_ts": self.remote_ts,
            "lag_seconds": round(self.lag_seconds, 1),
            "unpushed_count": self.unpushed_count,
            "category": self.category,
        }

    def format_report(self) -> str:
        lag = self.lag_seconds
        if lag < 60:
            lag_str = f"{lag:.0f}s"
        elif lag < 3600:
            lag_str = f"{lag / 60:.1f}m"
        else:
            lag_str = f"{lag / 3600:.1f}h"

        lines = [
            f"push lag: {lag_str} [{self.category}]",
            f"  local:  {self.local_sha[:12]}  ({_fmt_ts(self.local_ts)})",
            f"  remote: {self.remote_sha[:12] if self.remote_sha else 'none'}  "
            f"({_fmt_ts(self.remote_ts) if self.remote_ts else 'n/a'})",
            f"  unpushed: {self.unpushed_count} commit(s)",
        ]
        return "\n".join(lines)


def _fmt_ts(epoch: float) -> str:
    if not epoch:
        return "never"
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _git(args: list[str], repo: Path) -> tuple[int, str]:
    """Run a git command in the given repo, return (exitcode, stdout)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return 2, "timeout"
    except FileNotFoundError:
        return 2, "git not found"


def get_commit_ts(repo: Path, ref: str) -> float:
    """Get the author timestamp of a git ref as epoch seconds."""
    rc, out = _git(["log", "-1", "--format=%at", ref], repo)
    if rc != 0 or not out:
        return 0.0
    try:
        return float(out)
    except ValueError:
        return 0.0


def get_commit_sha(repo: Path, ref: str) -> str:
    """Get the SHA of a git ref."""
    rc, out = _git(["rev-parse", "--verify", ref], repo)
    return out if rc == 0 else ""


def count_unpushed(repo: Path, local_ref: str = "HEAD",
                   remote_ref: str = "origin/main") -> int:
    """Count commits on local_ref that are not on remote_ref."""
    rc, out = _git(
        ["rev-list", "--count", f"{remote_ref}..{local_ref}"], repo
    )
    if rc != 0 or not out:
        return 0
    try:
        return int(out)
    except ValueError:
        return 0


def measure_lag(repo: Path | None = None,
                warning_threshold: int = 600,
                critical_threshold: int = 1800) -> PushLag:
    """Measure push lag for the given repository.

    Args:
        repo: Path to the git repo. Defaults to the repo containing this file.
        warning_threshold: Seconds of lag before category = warning.
        critical_threshold: Seconds of lag before category = critical.

    Returns:
        PushLag snapshot.
    """
    if repo is None:
        repo = Path(__file__).resolve().parent.parent

    local_sha = get_commit_sha(repo, "HEAD")
    remote_sha = get_commit_sha(repo, "origin/main")
    local_ts = get_commit_ts(repo, "HEAD") if local_sha else 0.0
    remote_ts = get_commit_ts(repo, "origin/main") if remote_sha else 0.0
    unpushed = count_unpushed(repo)

    return PushLag(
        local_sha=local_sha,
        remote_sha=remote_sha,
        local_ts=local_ts,
        remote_ts=remote_ts,
        unpushed_count=unpushed,
        warning_threshold=warning_threshold,
        critical_threshold=critical_threshold,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure git push lag.")
    parser.add_argument("--writer", default="qwen",
                        help="Writer id (for labelling output).")
    parser.add_argument("--repo", default=None,
                        help="Path to repo root.")
    parser.add_argument("--threshold", type=int, default=600,
                        help="Warning threshold in seconds.")
    parser.add_argument("--critical", type=int, default=1800,
                        help="Critical threshold in seconds.")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON instead of human-readable report.")
    args = parser.parse_args(argv)

    repo = Path(args.repo) if args.repo else None

    try:
        lag = measure_lag(repo, args.threshold, args.critical)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        out = lag.to_dict()
        out["writer"] = args.writer
        print(json.dumps(out, indent=2))
    else:
        print(f"[{args.writer}] {lag.format_report()}")

    return 0 if lag.category == PushLag.NOMINAL else 1


if __name__ == "__main__":
    sys.exit(main())
