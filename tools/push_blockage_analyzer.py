#!/usr/bin/env python3
"""push_blockage_analyzer.py — diagnose why git push fails and suggest fixes.

When commits pile up locally but never reach the remote, the cause is almost
always one of a small set of problems: missing SSH key, unregistered deploy
key, wrong remote URL, branch protection, or network issues. This tool runs
a sequence of diagnostic checks and produces a severity-classified report
with actionable fix suggestions.

Diagnostic checks (in order):
  1. **remote_url**: Is the remote URL valid and reachable?
  2. **ssh_key_present**: Does the configured identity file exist?
  3. **ssh_key_permissions**: Are permissions restrictive enough (0600)?
  4. **ssh_auth_test**: Does `ssh -T git@github.com` succeed?
  5. **push_debt_count**: How many unpushed commits exist?
  6. **push_debt_age**: How old is the oldest unpushed commit?

Severity classification:
  - clear:       push works fine, no blockage
  - warning:     push debt accumulating but auth works (maybe rate-limited)
  - blocked:     authentication failing, push impossible
  - critical:    blocked for >24h with >50 commits

Each check returns a PushCheckResult with:
  - name, passed (bool), detail (str), fix (str or None)

Usage:
    python3 tools/push_blockage_analyzer.py
    python3 tools/push_blockage_analyzer.py --json
    python3 tools/push_blockage_analyzer.py --repo /path/to/repo

Exit codes:
    0 — all clear, push is working
    1 — blockage detected
    2 — error (not a git repo, etc.)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


CLEAR = "clear"
WARNING = "warning"
BLOCKED = "blocked"
CRITICAL = "critical"

PUSH_DEBT_WARNING = 10
PUSH_DEBT_BLOCKED = 50
PUSH_AGE_CRITICAL_HOURS = 24


@dataclass
class PushCheckResult:
    name: str
    passed: bool
    detail: str
    fix: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PushDiagnosis:
    severity: str
    checks: List[PushCheckResult]
    unpushed_count: int
    oldest_unpushed_age_hours: Optional[float]
    remote_url: str
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "checks": [c.to_dict() for c in self.checks],
            "unpushed_count": self.unpushed_count,
            "oldest_unpushed_age_hours": self.oldest_unpushed_age_hours,
            "remote_url": self.remote_url,
            "timestamp": self.timestamp,
        }


def run_cmd(cmd: list[str], cwd: Optional[str] = None, timeout: int = 10) -> tuple[int, str, str]:
    """Run a command and return (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "command timed out"
    except FileNotFoundError:
        return -2, "", f"command not found: {cmd[0]}"


def check_remote_url(repo: str) -> PushCheckResult:
    """Check if the remote URL is configured and looks valid."""
    code, out, err = run_cmd(["git", "remote", "get-url", "origin"], cwd=repo)
    if code != 0:
        return PushCheckResult(
            name="remote_url",
            passed=False,
            detail="no origin remote configured",
            fix="git remote add origin git@github.com:<owner>/<repo>.git",
        )
    url = out.strip()
    if not url:
        return PushCheckResult(
            name="remote_url",
            passed=False,
            detail="origin remote URL is empty",
            fix="git remote set-url origin git@github.com:<owner>/<repo>.git",
        )
    return PushCheckResult(
        name="remote_url",
        passed=True,
        detail=f"remote URL: {url}",
    )


def check_ssh_key_present(repo: str) -> PushCheckResult:
    """Check if the SSH identity file exists."""
    # First check SSH config for IdentityFile
    config_path = Path.home() / ".ssh" / "config"
    identity_file = None

    if config_path.exists():
        content = config_path.read_text()
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("identityfile"):
                parts = stripped.split(None, 1)
                if len(parts) == 2:
                    identity_file = Path(parts[1]).expanduser()
                    break

    # Also check common locations
    candidates = []
    if identity_file:
        candidates.append(identity_file)
    candidates.extend([
        Path.home() / ".ssh" / "id_ed25519",
        Path.home() / ".ssh" / "id_rsa",
    ])

    for candidate in candidates:
        if candidate.exists():
            return PushCheckResult(
                name="ssh_key_present",
                passed=True,
                detail=f"SSH key found: {candidate}",
            )

    searched = ", ".join(str(c) for c in candidates)
    return PushCheckResult(
        name="ssh_key_present",
        passed=False,
        detail=f"no SSH key found (checked: {searched})",
        fix="ssh-keygen -t ed25519 -C 'deploy-key' && cat ~/.ssh/id_ed25519.pub",
    )


def check_ssh_key_permissions(repo: str) -> PushCheckResult:
    """Check if SSH key has restrictive permissions."""
    candidates = [
        Path.home() / ".ssh" / "id_ed25519",
        Path.home() / ".ssh" / "id_rsa",
    ]

    for candidate in candidates:
        if candidate.exists():
            mode = candidate.stat().st_mode & 0o777
            if mode > 0o600:
                return PushCheckResult(
                    name="ssh_key_permissions",
                    passed=False,
                    detail=f"{candidate} has permissions {oct(mode)} (too open)",
                    fix=f"chmod 600 {candidate}",
                )
            return PushCheckResult(
                name="ssh_key_permissions",
                passed=True,
                detail=f"{candidate} permissions: {oct(mode)}",
            )

    return PushCheckResult(
        name="ssh_key_permissions",
        passed=False,
        detail="no SSH key to check permissions",
        fix="generate an SSH key first",
    )


def check_ssh_auth(repo: str) -> PushCheckResult:
    """Test SSH authentication against GitHub."""
    code, out, err = run_cmd(
        ["ssh", "-T", "git@github.com", "-o", "ConnectTimeout=5"],
        timeout=15,
    )
    combined = f"{out}\n{err}"

    if "successfully authenticated" in combined.lower():
        return PushCheckResult(
            name="ssh_auth",
            passed=True,
            detail="SSH authentication successful",
        )

    if "permission denied" in combined.lower():
        return PushCheckResult(
            name="ssh_auth",
            passed=False,
            detail="SSH authentication failed (permission denied)",
            fix=(
                "deploy key not registered on GitHub repo. "
                "Steps: 1) cat ~/.ssh/id_ed25519.pub "
                "2) go to repo Settings → Deploy keys → Add deploy key "
                "3) paste the public key and save"
            ),
        )

    if "timed out" in combined.lower() or code == -1:
        return PushCheckResult(
            name="ssh_auth",
            passed=False,
            detail="SSH connection timed out",
            fix="check network connectivity and firewall rules",
        )

    return PushCheckResult(
        name="ssh_auth",
        passed=False,
        detail=f"SSH auth test failed: {combined[:200]}",
        fix="verify SSH key is registered on the GitHub repository",
    )


def check_push_debt(repo: str) -> tuple[PushCheckResult, int, Optional[float]]:
    """Count unpushed commits and age of oldest."""
    code, out, err = run_cmd(
        ["git", "log", "--oneline", "origin/main..HEAD"],
        cwd=repo,
    )

    if code != 0:
        # Might not have origin/main tracking
        code2, out2, _ = run_cmd(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo,
        )
        total = int(out2.strip()) if code2 == 0 and out2.strip().isdigit() else 0
        return PushCheckResult(
            name="push_debt",
            passed=False,
            detail=f"cannot determine unpushed count (no origin/main ref), total commits: {total}",
            fix="git fetch origin to establish tracking ref",
        ), total, None

    lines = [l for l in out.splitlines() if l.strip()]
    count = len(lines)

    # Get age of oldest unpushed commit
    oldest_age_hours = None
    if count > 0:
        code2, out2, _ = run_cmd(
            ["git", "log", "--format=%aI", "origin/main..HEAD", "--reverse"],
            cwd=repo,
        )
        if code2 == 0 and out2.strip():
            oldest_line = out2.strip().splitlines()[0]
            try:
                oldest_dt = datetime.fromisoformat(oldest_line)
                now = datetime.now(timezone.utc)
                oldest_age_hours = (now - oldest_dt).total_seconds() / 3600
            except (ValueError, TypeError):
                pass

    if count == 0:
        return PushCheckResult(
            name="push_debt",
            passed=True,
            detail="no unpushed commits",
        ), 0, None

    if count < PUSH_DEBT_WARNING:
        return PushCheckResult(
            name="push_debt",
            passed=True,
            detail=f"{count} unpushed commits (within normal range)",
        ), count, oldest_age_hours

    return PushCheckResult(
        name="push_debt",
        passed=False,
        detail=f"{count} unpushed commits",
        fix="resolve auth issues and run: git push origin main",
    ), count, oldest_age_hours


def determine_severity(checks: List[PushCheckResult], unpushed: int, age_hours: Optional[float]) -> str:
    """Determine overall severity from all check results."""
    auth_failed = any(not c.passed and c.name == "ssh_auth" for c in checks)
    key_missing = any(not c.passed and c.name == "ssh_key_present" for c in checks)

    if auth_failed or key_missing:
        if unpushed >= PUSH_DEBT_BLOCKED and age_hours and age_hours >= PUSH_AGE_CRITICAL_HOURS:
            return CRITICAL
        return BLOCKED

    if unpushed >= PUSH_DEBT_BLOCKED:
        return WARNING

    if unpushed >= PUSH_DEBT_WARNING:
        return WARNING

    return CLEAR


def diagnose(repo: str = ".") -> PushDiagnosis:
    """Run all diagnostic checks and return a comprehensive diagnosis."""
    repo_path = str(Path(repo).resolve())

    # Verify it's a git repo
    code, _, _ = run_cmd(["git", "rev-parse", "--git-dir"], cwd=repo_path)
    if code != 0:
        raise ValueError(f"{repo_path} is not a git repository")

    checks: List[PushCheckResult] = []

    # Get remote URL for reporting
    code, remote_url, _ = run_cmd(["git", "remote", "get-url", "origin"], cwd=repo_path)
    if code != 0:
        remote_url = "(not configured)"

    checks.append(check_remote_url(repo_path))
    checks.append(check_ssh_key_present(repo_path))
    checks.append(check_ssh_key_permissions(repo_path))
    checks.append(check_ssh_auth(repo_path))

    push_check, unpushed, age_hours = check_push_debt(repo_path)
    checks.append(push_check)

    severity = determine_severity(checks, unpushed, age_hours)

    return PushDiagnosis(
        severity=severity,
        checks=checks,
        unpushed_count=unpushed,
        oldest_unpushed_age_hours=round(age_hours, 2) if age_hours else None,
        remote_url=remote_url,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def format_human(diag: PushDiagnosis) -> str:
    """Format diagnosis as human-readable report."""
    lines = []
    severity_icon = {
        CLEAR: "✅",
        WARNING: "⚠️",
        BLOCKED: "🚫",
        CRITICAL: "🔴",
    }
    icon = severity_icon.get(diag.severity, "?")
    lines.append(f"{icon} Push Blockage Report — severity: {diag.severity.upper()}")
    lines.append(f"   Remote: {diag.remote_url}")
    lines.append(f"   Unpushed: {diag.unpushed_count} commits")
    if diag.oldest_unpushed_age_hours:
        lines.append(f"   Oldest unpushed: {diag.oldest_unpushed_age_hours:.1f}h old")
    lines.append("")

    for check in diag.checks:
        status = "✓" if check.passed else "✗"
        lines.append(f"  {status} {check.name}: {check.detail}")
        if check.fix and not check.passed:
            lines.append(f"    → Fix: {check.fix}")

    # Summary
    lines.append("")
    failed = [c for c in diag.checks if not c.passed]
    if not failed:
        lines.append("All checks passed. Push should be working.")
    else:
        lines.append(f"{len(failed)} check(s) failed. Action required:")
        for c in failed:
            if c.fix:
                lines.append(f"  • {c.name}: {c.fix}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Diagnose git push blockages")
    parser.add_argument("--repo", default=".", help="Path to git repository")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        diag = diagnose(args.repo)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        print(json.dumps(diag.to_dict(), indent=2))
    else:
        print(format_human(diag))

    sys.exit(0 if diag.severity == CLEAR else 1)


if __name__ == "__main__":
    main()
