#!/usr/bin/env python3
"""push_credential_readiness — proactive push credential validation.

the existing push_preflight.py checks prerequisites at push time.
this module adds a *readiness layer* that can be called earlier in the
pipeline — before the batch committer even starts accumulating commits —
so that credential issues are surfaced immediately after restart rather
than discovered 10 minutes later when the first push attempt fails.

design goals:
  1. fast: no network calls unless explicitly requested
  2. actionable: each check returns a remediation hint
  3. cacheable: results valid for a configurable TTL
  4. composable: can be used as a library or CLI

usage:
    from iamai.push_credential_readiness import CredentialReadiness

    cr = CredentialReadiness()
    result = cr.check_all()
    if not result["ready"]:
        print(result["remediation"])

CLI:
    python3 -m iamai.push_credential_readiness
    python3 -m iamai.push_credential_readiness --network   # include ssh probe
    python3 -m iamai.push_credential_readiness --json
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Any


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_FILE = DATA_DIR / "credential_readiness_cache.json"
DEFAULT_CACHE_TTL = 300  # seconds


@dataclass
class CredentialCheck:
    """A single credential readiness check."""
    name: str
    passed: bool
    detail: str = ""
    remediation: str = ""
    severity: str = "error"  # error | warning | info
    checked_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CredentialReadiness:
    """Proactive push credential validator.

    Performs a series of checks to determine whether `git push` will succeed,
    ordered from cheapest (file existence) to most expensive (ssh probe).
    Stops at the first failure by default; use `check_all(check_network=True)`
    to run all checks regardless.
    """

    def __init__(
        self,
        repo_path: Optional[Path] = None,
        ssh_key_path: Optional[Path] = None,
        cache_ttl: int = DEFAULT_CACHE_TTL,
    ):
        self.repo_path = repo_path or Path(__file__).resolve().parent.parent
        self.ssh_key_path = ssh_key_path or self._find_ssh_key()
        self.cache_ttl = cache_ttl

    def _find_ssh_key(self) -> Path:
        """Locate the SSH private key, checking standard and repo-local paths."""
        candidates = [
            Path.home() / ".ssh" / "id_ed25519",
            Path.home() / ".ssh" / "id_rsa",
            self.repo_path.parent / ".ssh" / "id_ed25519",
            self.repo_path.parent / ".ssh" / "id_rsa",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]  # default, will fail existence check

    def check_key_exists(self) -> CredentialCheck:
        """Verify the SSH private key file exists and is readable."""
        if not self.ssh_key_path.exists():
            return CredentialCheck(
                name="key_exists",
                passed=False,
                detail=f"SSH key not found at {self.ssh_key_path}",
                remediation=(
                    "generate a new key: ssh-keygen -t ed25519 -f "
                    f"{self.ssh_key_path} -N ''"
                ),
                severity="error",
            )
        if not os.access(self.ssh_key_path, os.R_OK):
            return CredentialCheck(
                name="key_exists",
                passed=False,
                detail=f"SSH key exists but not readable: {self.ssh_key_path}",
                remediation=f"chmod 600 {self.ssh_key_path}",
                severity="error",
            )
        return CredentialCheck(
            name="key_exists",
            passed=True,
            detail=f"key found at {self.ssh_key_path}",
            severity="info",
        )

    def check_key_permissions(self) -> CredentialCheck:
        """Verify the SSH key has restrictive permissions (600 or stricter)."""
        if not self.ssh_key_path.exists():
            return CredentialCheck(
                name="key_permissions",
                passed=False,
                detail="cannot check permissions — key file missing",
                remediation="run check_key_exists first",
                severity="error",
            )
        mode = oct(self.ssh_key_path.stat().st_mode & 0o777)
        # SSH requires private keys to be readable only by owner
        if self.ssh_key_path.stat().st_mode & 0o077:
            return CredentialCheck(
                name="key_permissions",
                passed=False,
                detail=f"key permissions too open: {mode} (need 0600 or stricter)",
                remediation=f"chmod 600 {self.ssh_key_path}",
                severity="error",
            )
        return CredentialCheck(
            name="key_permissions",
            passed=True,
            detail=f"permissions OK: {mode}",
            severity="info",
        )

    def check_known_hosts(self) -> CredentialCheck:
        """Verify github.com is in known_hosts."""
        known_hosts = Path.home() / ".ssh" / "known_hosts"
        repo_known = self.repo_path.parent / ".ssh" / "known_hosts"

        for path in [known_hosts, repo_known]:
            if path.exists():
                content = path.read_text(errors="replace")
                if "github.com" in content:
                    return CredentialCheck(
                        name="known_hosts",
                        passed=True,
                        detail=f"github.com found in {path}",
                        severity="info",
                    )

        return CredentialCheck(
            name="known_hosts",
            passed=False,
            detail="github.com not found in any known_hosts file",
            remediation="ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts",
            severity="warning",
        )

    def check_git_remote(self) -> CredentialCheck:
        """Verify the git remote is configured for SSH."""
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                cwd=self.repo_path,
                timeout=5,
            )
            if result.returncode != 0:
                return CredentialCheck(
                    name="git_remote",
                    passed=False,
                    detail="no origin remote configured",
                    remediation="git remote add origin git@github.com:OWNER/REPO.git",
                    severity="error",
                )
            url = result.stdout.strip()
            if url.startswith("git@") or url.startswith("ssh://"):
                return CredentialCheck(
                    name="git_remote",
                    passed=True,
                    detail=f"remote URL: {url}",
                    severity="info",
                )
            # HTTPS URL — different credential flow
            return CredentialCheck(
                name="git_remote",
                passed=True,
                detail=f"remote uses HTTPS: {url} (credential helper needed)",
                severity="warning",
            )
        except subprocess.TimeoutExpired:
            return CredentialCheck(
                name="git_remote",
                passed=False,
                detail="git remote check timed out",
                severity="warning",
            )

    def check_ssh_probe(self, timeout: int = 10) -> CredentialCheck:
        """Actually try SSH to github.com (network check)."""
        try:
            result = subprocess.run(
                [
                    "ssh",
                    "-i", str(self.ssh_key_path),
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "BatchMode=yes",
                    "-o", f"ConnectTimeout={timeout}",
                    "-T",
                    "git@github.com",
                ],
                capture_output=True,
                text=True,
                timeout=timeout + 5,
            )
            stderr = result.stderr.strip()
            # GitHub always returns exit 1 even on success, with a specific message
            if "successfully authenticated" in stderr:
                return CredentialCheck(
                    name="ssh_probe",
                    passed=True,
                    detail="SSH authentication successful",
                    severity="info",
                )
            if "Permission denied" in stderr:
                return CredentialCheck(
                    name="ssh_probe",
                    passed=False,
                    detail="SSH key not registered on GitHub",
                    remediation=(
                        "add this public key to GitHub Settings > SSH Keys:\n"
                        f"  cat {self.ssh_key_path}.pub\n"
                        "then visit: https://github.com/settings/ssh/new"
                    ),
                    severity="error",
                )
            if "Could not resolve hostname" in stderr:
                return CredentialCheck(
                    name="ssh_probe",
                    passed=False,
                    detail="cannot resolve github.com (network issue)",
                    remediation="check DNS and network connectivity",
                    severity="warning",
                )
            return CredentialCheck(
                name="ssh_probe",
                passed=False,
                detail=f"unexpected SSH response: {stderr[:200]}",
                remediation="check SSH configuration manually",
                severity="warning",
            )
        except subprocess.TimeoutExpired:
            return CredentialCheck(
                name="ssh_probe",
                passed=False,
                detail=f"SSH probe timed out after {timeout}s",
                remediation="check network connectivity to github.com",
                severity="warning",
            )
        except FileNotFoundError:
            return CredentialCheck(
                name="ssh_probe",
                passed=False,
                detail="ssh command not found",
                remediation="install openssh-client",
                severity="error",
            )

    def check_all(
        self,
        check_network: bool = False,
        stop_on_failure: bool = True,
    ) -> Dict[str, Any]:
        """Run all credential checks and return a readiness report.

        Args:
            check_network: include the SSH network probe (slower)
            stop_on_failure: stop at first failure (faster)

        Returns:
            dict with keys: ready, checks, failed, remediation, checked_at
        """
        checks: List[CredentialCheck] = []
        ordered_checks = [
            self.check_key_exists,
            self.check_key_permissions,
            self.check_known_hosts,
            self.check_git_remote,
        ]
        if check_network:
            ordered_checks.append(self.check_ssh_probe)

        failed = []
        for check_fn in ordered_checks:
            result = check_fn()
            checks.append(result)
            if not result.passed:
                failed.append(result)
                if stop_on_failure:
                    break

        ready = len(failed) == 0
        remediation_parts = [
            f"[{c.name}] {c.remediation}" for c in failed if c.remediation
        ]

        report = {
            "ready": ready,
            "checks": [c.to_dict() for c in checks],
            "failed_count": len(failed),
            "remediation": "\n".join(remediation_parts) if remediation_parts else "",
            "checked_at": time.time(),
            "network_checked": check_network,
        }

        # cache the result
        self._cache_result(report)
        return report

    def _cache_result(self, report: Dict[str, Any]) -> None:
        """Cache the check result for TTL-based reuse."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(json.dumps(report, indent=2))
        except OSError:
            pass  # cache is best-effort

    def cached_result(self) -> Optional[Dict[str, Any]]:
        """Return a cached result if still within TTL, else None."""
        if not CACHE_FILE.exists():
            return None
        try:
            report = json.loads(CACHE_FILE.read_text())
            age = time.time() - report.get("checked_at", 0)
            if age < self.cache_ttl:
                return report
        except (json.JSONDecodeError, OSError):
            pass
        return None

    def readiness_summary(self, check_network: bool = False) -> str:
        """Human-readable readiness summary."""
        cached = self.cached_result()
        if cached and not check_network:
            report = cached
            source = "cached"
        else:
            report = self.check_all(check_network=check_network)
            source = "fresh"

        lines = [f"credential readiness ({source}):"]
        for check in report["checks"]:
            icon = "OK" if check["passed"] else "FAIL"
            lines.append(f"  [{icon}] {check['name']}: {check['detail']}")

        if report["ready"]:
            lines.append("  -> push should succeed")
        else:
            lines.append(f"  -> NOT ready ({report['failed_count']} check(s) failed)")
            if report["remediation"]:
                lines.append(f"  fix: {report['remediation']}")

        return "\n".join(lines)


def readiness_report(
    repo_path: Optional[Path] = None,
    check_network: bool = False,
) -> str:
    """Convenience function: return a human-readable readiness report."""
    cr = CredentialReadiness(repo_path=repo_path)
    return cr.readiness_summary(check_network=check_network)


if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--network", action="store_true",
                    help="include SSH network probe")
    ap.add_argument("--json", action="store_true", dest="json_output",
                    help="emit JSON instead of text")
    args = ap.parse_args()

    cr = CredentialReadiness()
    if args.json_output:
        report = cr.check_all(check_network=args.network)
        print(json.dumps(report, indent=2))
    else:
        print(cr.readiness_summary(check_network=args.network))

    # exit code: 0 if ready, 1 if not
    result = cr.check_all(check_network=args.network)
    sys.exit(0 if result["ready"] else 1)
