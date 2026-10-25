#!/usr/bin/env python3
"""Scan recent commits for missing or default author attribution.

A commit without a proper author.name / author.email is usually a sign
that git config wasn't set up correctly on the machine that produced it.
In a multi-agent repo where each writer has its own identity, silent
mis-attribution erodes trust in the commit log.

Usage:
    python3 tools/unattributed_commit_scanner.py [--limit N] [--json]

Exit codes:
    0  all checked commits have real attribution
    1  one or more commits lack attribution
    2  repo error (not a git repo, etc.)

Patterns flagged as "unattributed":
    - author name is empty or "(no author)"
    - author email is empty or "(none)"
    - author name matches the git default "User" / "root" / "ubuntu"
      without a project-specific override
    - author email contains "@localhost" or "@none"

This tool complements commit_freshness.py (which measures *time* gaps)
by measuring *identity* hygiene.
"""

import argparse
import json
import subprocess
import sys
from typing import List, Dict, Optional

# Common default names that indicate git config was never set
DEFAULT_NAMES = frozenset({
    "", "(no author)", "root", "ubuntu", "user", "admin",
    "git", "nobody", "anonymous", "default",
})

# Email patterns that suggest no real identity was configured
SUSPICIOUS_EMAIL_SUFFIXES = (
    "@localhost",
    "@none",
    "@local",
    "@example.com",
)

SUSPICIOUS_EMAILS = frozenset({
    "", "(none)", "(no email)", "root@localhost", "user@localhost",
})


def get_repo_root() -> Optional[str]:
    """Return the repo root, or None if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def scan_commits(limit: int = 50, repo_root: Optional[str] = None) -> List[Dict]:
    """Scan the last `limit` commits for attribution issues.

    Returns a list of dicts, one per flagged commit:
        {
            "hash": "abc1234",
            "author_name": "root",
            "author_email": "root@localhost",
            "subject": "fix: ...",
            "date": "2026-10-19",
            "reason": "default_name"
        }
    """
    if repo_root is None:
        repo_root = get_repo_root()
    if repo_root is None:
        return []

    # %H = full hash, %an = author name, %ae = author email,
    # %s = subject, %ai = author date ISO
    fmt = "%H%x1f%an%x1f%ae%x1f%s%x1f%ai"
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={limit}", f"--format={fmt}"],
            capture_output=True, text=True, timeout=10,
            cwd=repo_root,
        )
        if result.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    flagged = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\x1f")
        if len(parts) < 5:
            continue

        commit_hash = parts[0][:10]
        author_name = parts[1]
        author_email = parts[2]
        subject = parts[3]
        date = parts[4][:10]

        reason = None

        # Check name
        if author_name.lower().strip() in DEFAULT_NAMES:
            reason = "default_name"
        # Check email
        elif author_email.lower().strip() in SUSPICIOUS_EMAILS:
            reason = "default_email"
        elif any(author_email.lower().endswith(s) for s in SUSPICIOUS_EMAIL_SUFFIXES):
            reason = "suspicious_email"

        if reason:
            flagged.append({
                "hash": commit_hash,
                "author_name": author_name or "(empty)",
                "author_email": author_email or "(empty)",
                "subject": subject,
                "date": date,
                "reason": reason,
            })

    return flagged


def format_report(flagged: List[Dict], total_scanned: int) -> str:
    """Format the scan results as a human-readable report."""
    if not flagged:
        return f"attribution ok — {total_scanned} commits scanned, all properly attributed."

    lines = [
        f"attribution issues — {len(flagged)} of {total_scanned} commits flagged:",
        "",
    ]
    for entry in flagged:
        lines.append(
            f"  {entry['hash']}  {entry['date']}  "
            f"[{entry['reason']}]  "
            f"{entry['author_name']} <{entry['author_email']}>  "
            f"— {entry['subject']}"
        )
    lines.append("")
    reasons = {}
    for entry in flagged:
        reasons[entry["reason"]] = reasons.get(entry["reason"], 0) + 1
    lines.append("breakdown:")
    for reason, count in sorted(reasons.items()):
        lines.append(f"  {reason}: {count}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Scan commits for missing attribution")
    parser.add_argument("--limit", type=int, default=50,
                        help="Number of recent commits to scan (default: 50)")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")
    args = parser.parse_args()

    repo_root = get_repo_root()
    if repo_root is None:
        print("error: not in a git repository", file=sys.stderr)
        sys.exit(2)

    flagged = scan_commits(limit=args.limit, repo_root=repo_root)

    if args.json:
        print(json.dumps({
            "scanned": args.limit,
            "flagged_count": len(flagged),
            "commits": flagged,
        }, indent=2))
    else:
        print(format_report(flagged, args.limit))

    sys.exit(1 if flagged else 0)


if __name__ == "__main__":
    main()
