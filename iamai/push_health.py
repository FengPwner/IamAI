#!/usr/bin/env python3
"""push_health — monitor SSH key presence and push readiness.

The repo has been stuck with 46+ unpushed commits due to missing SSH keys.
This module provides a quick check for push readiness:
- SSH key file exists and is readable
- SSH key is registered with ssh-agent (optional)
- git push --dry-run succeeds

Usage:
    from iamai.push_health import PushHealth
    
    checker = PushHealth()
    result = checker.check()
    print(f"Push ready: {result.ready} ({result.status})")

CLI:
    python3 -m iamai.push_health
    python3 -m iamai.push_health --json
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class PushStatus:
    """Push readiness assessment."""
    ready: bool
    status: str  # "ready", "no_key", "key_not_registered", "push_failed"
    ssh_key_path: Optional[str] = None
    ssh_key_exists: bool = False
    ssh_key_readable: bool = False
    ssh_agent_has_key: bool = False
    dry_run_success: bool = False
    error: Optional[str] = None


class PushHealth:
    """Check if the repo can push to its remote."""
    
    DEFAULT_KEY_PATHS = [
        "~/.ssh/id_ed25519",
        "~/.ssh/id_rsa",
        "~/.ssh/id_ecdsa",
    ]
    
    def __init__(self, repo_path: str = ".", key_path: Optional[str] = None):
        """Initialize push health checker.
        
        Args:
            repo_path: Path to the git repository
            key_path: Explicit SSH key path (overrides auto-detection)
        """
        self.repo_path = Path(repo_path).resolve()
        self.key_path = Path(key_path).expanduser() if key_path else None
    
    def check(self) -> PushStatus:
        """Run all push readiness checks."""
        # Step 1: Find SSH key
        key_path = self._find_ssh_key()
        if not key_path:
            return PushStatus(
                ready=False,
                status="no_key",
                error="No SSH key found in standard locations"
            )
        
        # Step 2: Check key is readable
        if not self._key_readable(key_path):
            return PushStatus(
                ready=False,
                status="no_key",
                ssh_key_path=str(key_path),
                ssh_key_exists=True,
                ssh_key_readable=False,
                error=f"SSH key not readable: {key_path}"
            )
        
        # Step 3: Check ssh-agent (optional, non-blocking)
        agent_has_key = self._check_ssh_agent()
        
        # Step 4: Try dry-run push
        dry_run_ok, error = self._dry_run_push()
        
        if dry_run_ok:
            return PushStatus(
                ready=True,
                status="ready",
                ssh_key_path=str(key_path),
                ssh_key_exists=True,
                ssh_key_readable=True,
                ssh_agent_has_key=agent_has_key,
                dry_run_success=True
            )
        else:
            return PushStatus(
                ready=False,
                status="push_failed",
                ssh_key_path=str(key_path),
                ssh_key_exists=True,
                ssh_key_readable=True,
                ssh_agent_has_key=agent_has_key,
                dry_run_success=False,
                error=error
            )
    
    def _find_ssh_key(self) -> Optional[Path]:
        """Locate the SSH private key."""
        if self.key_path:
            return self.key_path if self.key_path.exists() else None
        
        for path_str in self.DEFAULT_KEY_PATHS:
            path = Path(path_str).expanduser()
            if path.exists():
                return path
        return None
    
    def _key_readable(self, key_path: Path) -> bool:
        """Check if the key file can be read."""
        try:
            with open(key_path, 'r') as f:
                content = f.read()
                return len(content) > 0 and "PRIVATE KEY" in content
        except (IOError, OSError, PermissionError):
            return False
    
    def _check_ssh_agent(self) -> bool:
        """Check if ssh-agent has any keys loaded."""
        try:
            result = subprocess.run(
                ["ssh-add", "-l"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0 and "no identities" not in result.stdout.lower()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def _dry_run_push(self) -> tuple[bool, Optional[str]]:
        """Attempt a dry-run push to verify connectivity."""
        try:
            result = subprocess.run(
                ["git", "push", "--dry-run", "origin", "main"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.repo_path)
            )
            if result.returncode == 0:
                return True, None
            return False, result.stderr.strip() or result.stdout.strip()
        except subprocess.TimeoutExpired:
            return False, "Push dry-run timed out after 30s"
        except Exception as e:
            return False, str(e)


def main():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Check push readiness")
    parser.add_argument("--repo", default=".", help="Repository path")
    parser.add_argument("--key", help="Explicit SSH key path")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    
    checker = PushHealth(repo_path=args.repo, key_path=args.key)
    result = checker.check()
    
    if args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        status_icon = "✓" if result.ready else "✗"
        print(f"{status_icon} Push status: {result.status}")
        if result.ssh_key_path:
            print(f"  SSH key: {result.ssh_key_path}")
        if result.error:
            print(f"  Error: {result.error}")
        if not result.ready:
            print("\nTo fix:")
            if result.status == "no_key":
                print("  ssh-keygen -t ed25519 -C \"your@email\"")
                print("  # Then add ~/.ssh/id_ed25519.pub to GitHub Settings → SSH Keys")
            elif result.status == "push_failed":
                print("  # Check that your SSH key is registered on GitHub")
                print("  # https://github.com/settings/keys")


if __name__ == "__main__":
    main()
