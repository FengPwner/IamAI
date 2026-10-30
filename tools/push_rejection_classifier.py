#!/usr/bin/env python3
"""Classify git push rejection reasons from stderr output.

Turns a binary push pass/fail into a diagnostic signal:
  - FETCH_FIRST:    remote advanced during local outage (need pull --rebase)
  - PERMISSION:     SSH key expired, wrong deploy key, or access revoked
  - NETWORK:        DNS or connectivity failure
  - HOOK_REJECTED:  server-side hook (pre-receive / update) refused the push
  - UNKNOWN:        anything else

Usage:
    git push origin main 2>&1 | python3 tools/push_rejection_classifier.py
    # or:
    from tools.push_rejection_classifier import classify_push_stderr
    classify_push_stderr(stderr_text)  # -> dict with 'kind', 'fix', 'severity'
"""

import sys
import json
from typing import Dict

PATTERNS = [
    # Each entry: (kind, [keywords — ANY match triggers], fix, severity)
    # FETCH_FIRST requires BOTH "rejected" AND "fetch first"
    (
        "FETCH_FIRST",
        [["rejected", "fetch first"]],
        "Remote has commits you don't have. Run: git stash && git pull --rebase origin main && git stash pop && git push origin main",
        "medium",
    ),
    (
        "PERMISSION",
        [["permission denied"], ["publickey"], ["authentication failed"], ["access denied"]],
        "SSH key is invalid or expired. Rescue deploy key: bash tools/ssh_push_rescue.sh",
        "high",
    ),
    (
        "NETWORK",
        [["could not resolve host"], ["could not resolve hostname"], ["connection refused"], ["connection timed out"], ["network is unreachable"]],
        "Network issue. Retry after connectivity is restored.",
        "low",
    ),
    (
        "HOOK_REJECTED",
        [["remote rejected"], ["pre-receive hook declined"], ["hook declined"]],
        "Server-side hook refused the push. Check commit message format or CI gate status.",
        "high",
    ),
    (
        "NON_FAST_FORWARD",
        [["non-fast-forward"], ["updates were rejected"]],
        "Branch diverged. Prefer rebase over merge: git pull --rebase origin main",
        "medium",
    ),
]


def classify_push_stderr(stderr: str) -> Dict[str, str]:
    """Classify a push failure from its stderr text.

    Returns a dict with keys: kind, fix, severity.
    On success (empty stderr or no error patterns), returns kind='OK'.
    """
    if not stderr or not stderr.strip():
        return {"kind": "OK", "fix": "none", "severity": "none"}

    lower = stderr.lower()

    for kind, keyword_groups, fix, severity in PATTERNS:
        # Each keyword_group is a list of phrases; ALL phrases in a group must match.
        # Multiple groups are OR'd — any group matching triggers this category.
        if any(all(phrase in lower for phrase in group) for group in keyword_groups):
            return {"kind": kind, "fix": fix, "severity": severity}

    # Check single-keyword patterns as fallback
    if "rejected" in lower:
        return {
            "kind": "FETCH_FIRST",
            "fix": "Run: git stash && git pull --rebase origin main && git stash pop && git push",
            "severity": "medium",
        }
    if "denied" in lower:
        return {
            "kind": "PERMISSION",
            "fix": "Check SSH key: ssh -T git@github.com",
            "severity": "high",
        }

    return {"kind": "UNKNOWN", "fix": "Inspect stderr manually", "severity": "medium"}


def push_recovery_steps(classification: Dict[str, str]) -> list:
    """Return an ordered list of recovery commands for a given classification."""
    steps = {
        "FETCH_FIRST": [
            "git stash",
            "git pull --rebase origin main",
            "git stash pop",
            "git push origin main",
        ],
        "NON_FAST_FORWARD": [
            "git stash",
            "git pull --rebase origin main",
            "git stash pop",
            "git push origin main",
        ],
        "PERMISSION": [
            "bash tools/ssh_push_rescue.sh",
            "ssh -T git@github.com",
            "git push origin main",
        ],
        "NETWORK": [
            "ping -c1 github.com",
            "git push origin main",
        ],
        "HOOK_REJECTED": [
            "git log --oneline -1",
            "# check commit message format matches convention",
            "git push origin main",
        ],
    }
    return steps.get(classification["kind"], ["git status", "# inspect manually"])


if __name__ == "__main__":
    stderr_text = sys.stdin.read()
    result = classify_push_stderr(stderr_text)
    if result["kind"] != "OK":
        result["recovery_steps"] = push_recovery_steps(result)
    print(json.dumps(result, indent=2))
