#!/usr/bin/env python3
"""push_key_recovery — automated SSH key recovery when primary is missing.

the ssh key health module detects amber and red states. this module goes
further: when the primary key at ~/.ssh/id_ed25519 is missing (red state),
it searches known backup locations and restores the key automatically.

backup locations (checked in order):
  1. /root/userdata/workspace/.ssh/id_ed25519
  2. /tmp/iamai_key
  3. any file matching /root/**/id_ed25519 (depth-limited)

after restoration, the module probes github to determine registration
status and provides a clear remediation path if the key is unregistered.

this does not solve the registration gap — that still requires a human
with repo admin access. but it eliminates the simpler failure mode where
the key exists somewhere on disk but not where ssh expects it.

usage:
    from iamai.push_key_recovery import PushKeyRecovery

    recovery = PushKeyRecovery()
    result = recovery.attempt_recovery()
    # result.recovered: bool — key now exists at primary path
    # result.registered: bool | None — github accepts it (None if not probed)
    # result.remediation: str — what to do next
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


DEFAULT_PRIMARY = Path.home() / ".ssh" / "id_ed25519"
BACKUP_LOCATIONS = [
    Path("/root/userdata/workspace/.ssh/id_ed25519"),
    Path("/tmp/iamai_key"),
]
SEARCH_DIRS = [Path("/root")]
SEARCH_DEPTH = 4


@dataclass
class RecoveryResult:
    """outcome of a recovery attempt."""
    recovered: bool
    source: Optional[str] = None
    registered: Optional[bool] = None
    fingerprint: Optional[str] = None
    remediation: str = ""
    errors: List[str] = field(default_factory=list)

    @property
    def push_ready(self) -> bool:
        return self.recovered and self.registered is True

    @property
    def needs_registration(self) -> bool:
        return self.recovered and self.registered is False


class PushKeyRecovery:
    """find and restore SSH keys from backup locations."""

    def __init__(
        self,
        primary_path: Optional[Path] = None,
        backup_locations: Optional[List[Path]] = None,
        search_dirs: Optional[List[Path]] = None,
        probe_github: bool = True,
    ):
        self.primary_path = primary_path or DEFAULT_PRIMARY
        self.backup_locations = backup_locations if backup_locations is not None else list(BACKUP_LOCATIONS)
        self.search_dirs = search_dirs if search_dirs is not None else list(SEARCH_DIRS)
        self.search_depth = SEARCH_DEPTH
        self.probe_github = probe_github

    def attempt_recovery(self) -> RecoveryResult:
        """try to restore the SSH key and assess push readiness."""
        # step 1: if primary already exists, skip restoration
        if self.primary_path.exists():
            fp = self._extract_fingerprint(self.primary_path)
            reg = self._probe_registration(self.primary_path)
            return RecoveryResult(
                recovered=True,
                source="primary (already present)",
                registered=reg,
                fingerprint=fp,
                remediation=self._remediation_text(reg, fp),
            )

        # step 2: search backup locations
        source = self._find_backup()
        if source is None:
            return RecoveryResult(
                recovered=False,
                remediation=(
                    "no SSH key found. generate one with:\n"
                    "  ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ''\n"
                    "then add the public key to github as a deploy key."
                ),
            )

        # step 3: restore from backup
        try:
            self._restore_key(source)
        except OSError as e:
            return RecoveryResult(
                recovered=False,
                errors=[f"failed to restore key: {e}"],
                remediation=f"manual copy required:\n  cp {source} {self.primary_path}\n  chmod 600 {self.primary_path}",
            )

        fp = self._extract_fingerprint(self.primary_path)
        reg = self._probe_registration(self.primary_path) if self.probe_github else None

        return RecoveryResult(
            recovered=True,
            source=str(source),
            registered=reg,
            fingerprint=fp,
            remediation=self._remediation_text(reg, fp),
        )

    def _find_backup(self) -> Optional[Path]:
        """search for a backup key in known locations."""
        for loc in self.backup_locations:
            if loc.exists() and loc.is_file():
                return loc

        # deeper search
        for search_dir in self.search_dirs:
            if not search_dir.exists():
                continue
            for root, dirs, files in os.walk(search_dir):
                depth = len(Path(root).relative_to(search_dir).parts)
                if depth > self.search_depth:
                    dirs.clear()
                    continue
                # skip proc, sys, etc.
                dirs[:] = [d for d in dirs if d not in ("proc", "sys", "dev", "run")]
                if "id_ed25519" in files:
                    candidate = Path(root) / "id_ed25519"
                    if candidate != self.primary_path:
                        return candidate
        return None

    def _restore_key(self, source: Path) -> None:
        """copy key from source to primary path with correct permissions."""
        self.primary_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(str(source), str(self.primary_path))
        os.chmod(str(self.primary_path), 0o600)

        # also copy public key if available
        pub_source = source.with_suffix(source.suffix + ".pub")
        pub_dest = self.primary_path.with_suffix(self.primary_path.suffix + ".pub")
        if pub_source.exists():
            shutil.copy2(str(pub_source), str(pub_dest))
            os.chmod(str(pub_dest), 0o644)

    def _extract_fingerprint(self, key_path: Path) -> Optional[str]:
        """get SHA256 fingerprint from a key file."""
        pub_path = key_path.with_suffix(key_path.suffix + ".pub")
        target = pub_path if pub_path.exists() else key_path
        try:
            result = subprocess.run(
                ["ssh-keygen", "-lf", str(target)],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                parts = result.stdout.split()
                if len(parts) >= 2:
                    return parts[1]
        except (subprocess.TimeoutExpired, Exception):
            pass
        return None

    def _probe_registration(self, key_path: Path) -> Optional[bool]:
        """test whether github accepts this key for SSH auth."""
        try:
            result = subprocess.run(
                [
                    "ssh", "-T",
                    "-i", str(key_path),
                    "-o", "BatchMode=yes",
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "ConnectTimeout=5",
                    "git@github.com",
                ],
                capture_output=True, text=True, timeout=10,
            )
            # github returns exit 1 even on success (prints "Hi <user>!")
            output = result.stdout + result.stderr
            if "Hi " in output and "successfully authenticated" in output:
                return True
            if "Permission denied" in output:
                return False
        except (subprocess.TimeoutExpired, Exception):
            pass
        return None

    def _remediation_text(self, registered: Optional[bool], fingerprint: Optional[str]) -> str:
        if registered is True:
            return "key is registered. push should work."
        if registered is False:
            fp_line = f"\nfingerprint: {fingerprint}" if fingerprint else ""
            return (
                f"key exists but github rejects it (not registered or revoked).{fp_line}\n"
                "add the public key as a deploy key at:\n"
                "  https://github.com/FengPwner/IamAI/settings/keys\n"
                "or as an account key at:\n"
                "  https://github.com/settings/ssh/new"
            )
        return "registration status unknown. run: ssh -T git@github.com"


def recover_and_report() -> RecoveryResult:
    """convenience entry point for caretaker scripts."""
    recovery = PushKeyRecovery()
    return recovery.attempt_recovery()


if __name__ == "__main__":
    result = recover_and_report()
    print(f"recovered:   {result.recovered}")
    print(f"source:      {result.source}")
    print(f"registered:  {result.registered}")
    print(f"fingerprint: {result.fingerprint}")
    print(f"push_ready:  {result.push_ready}")
    print(f"remediation: {result.remediation}")
