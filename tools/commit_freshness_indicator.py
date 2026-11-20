#!/usr/bin/env python3
"""
commit_freshness_indicator.py — How fresh is the latest commit?

Returns a structured assessment of commit age relative to expected cadence.
Useful for quick health checks without parsing full git logs.

Output (JSON):
{
  "commit_timestamp": 1700000000,
  "age_seconds": 420,
  "status": "warm",          # fresh | warm | stale
  "cadence_ratio": 0.7,      # age / expected_cadence
  "recommendation": "ok"     # ok | watch | intervene
}
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


FRESH_THRESHOLD = 300    # 5 minutes
WARM_THRESHOLD = 900     # 15 minutes
DEFAULT_CADENCE = 600    # 10 minutes


def get_latest_commit_timestamp(repo_path: str = ".") -> int:
    """Get the unix timestamp of the latest commit."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            raise RuntimeError(f"git error: {result.stderr.strip()}")
        
        ts_str = result.stdout.strip()
        if not ts_str:
            raise RuntimeError("no commits in repository")
        
        return int(ts_str)
    except subprocess.TimeoutExpired:
        raise RuntimeError("git command timed out")
    except ValueError:
        raise RuntimeError(f"invalid timestamp: {ts_str}")
    except FileNotFoundError:
        raise RuntimeError("git not found in PATH")


def classify_age(age_seconds: int) -> str:
    """Classify commit age into fresh/warm/stale."""
    if age_seconds < FRESH_THRESHOLD:
        return "fresh"
    elif age_seconds < WARM_THRESHOLD:
        return "warm"
    else:
        return "stale"


def get_recommendation(status: str, cadence_ratio: float) -> str:
    """Get action recommendation based on status and cadence ratio."""
    if status == "fresh":
        return "ok"
    elif status == "warm":
        if cadence_ratio > 1.5:
            return "watch"
        return "ok"
    else:  # stale
        if cadence_ratio > 2.0:
            return "intervene"
        return "watch"


def check_freshness(repo_path: str = ".", expected_cadence: int = DEFAULT_CADENCE) -> dict:
    """
    Check commit freshness and return structured result.
    
    Args:
        repo_path: Path to git repository
        expected_cadence: Expected seconds between commits
    
    Returns:
        Dict with freshness assessment
    """
    commit_ts = get_latest_commit_timestamp(repo_path)
    now = int(time.time())
    age = now - commit_ts
    
    # Handle future commits (clock skew)
    if age < 0:
        age = 0
    
    status = classify_age(age)
    cadence_ratio = age / expected_cadence if expected_cadence > 0 else float('inf')
    recommendation = get_recommendation(status, cadence_ratio)
    
    return {
        "commit_timestamp": commit_ts,
        "age_seconds": age,
        "status": status,
        "cadence_ratio": round(cadence_ratio, 2),
        "recommendation": recommendation,
        "expected_cadence": expected_cadence
    }


def format_human(result: dict) -> str:
    """Format result for human-readable output."""
    status = result["status"]
    age = result["age_seconds"]
    
    if age < 60:
        age_str = f"{age}s"
    elif age < 3600:
        age_str = f"{age // 60}m{age % 60}s"
    else:
        age_str = f"{age // 3600}h{(age % 3600) // 60}m"
    
    status_emoji = {"fresh": "✅", "warm": "⚠️", "stale": "❌"}.get(status, "?")
    rec_text = {
        "ok": "all good",
        "watch": "keep an eye on it",
        "intervene": "needs attention"
    }.get(result["recommendation"], "unknown")
    
    return f"{status_emoji} Latest commit: {age_str} ago ({status}) — {rec_text}"


def main():
    parser = argparse.ArgumentParser(description="Check commit freshness")
    parser.add_argument("--repo", default=".", help="Repository path")
    parser.add_argument("--cadence", type=int, default=DEFAULT_CADENCE,
                       help=f"Expected cadence in seconds (default: {DEFAULT_CADENCE})")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()
    
    try:
        result = check_freshness(args.repo, args.cadence)
        
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(format_human(result))
        
        # Exit code reflects status
        sys.exit(0 if result["status"] != "stale" else 1)
        
    except RuntimeError as e:
        error_msg = f"Error: {e}"
        if args.json:
            print(json.dumps({"error": str(e)}))
        else:
            print(error_msg, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
