#!/usr/bin/env python3
"""Check whether the workspace SSH keys are synced to ~/.ssh/.

The deploy key lives in /root/userdata/workspace/.ssh/ but the SSH client
reads from ~/.ssh/. When a container rebuilds, the workspace directory
survives but ~/.ssh/ is wiped — and the next push silently fails with
"Host key verification failed" or "Permission denied (publickey)".

This script compares the two directories and reports drift. Run it before
pushing; run it in a cron; run it whenever the caretaker sees an SSH error
that "shouldn't" happen.

    python3 tools/ssh_path_sync_check.py              # report only
    python3 tools/ssh_path_sync_check.py --sync       # copy missing files
    python3 tools/ssh_path_sync_check.py --json       # machine-readable output
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


# The workspace SSH directory is stable across container rebuilds;
# the home SSH directory is ephemeral. This asymmetry is the whole bug.
WORKSPACE_SSH = Path("/root/userdata/workspace/.ssh")
HOME_SSH = Path.home() / ".ssh"

# Files that must be identical in both locations for push to work.
REQUIRED_FILES = ["id_ed25519", "id_ed25519.pub", "known_hosts", "config"]


@dataclass
class FileStatus:
    name: str
    in_workspace: bool
    in_home: bool
    match: Optional[bool]  # None if one side is missing
    workspace_sha256: Optional[str] = None
    home_sha256: Optional[str] = None


@dataclass
class SyncReport:
    workspace_dir: str
    home_dir: str
    files: list[FileStatus]
    synced: bool  # True if all required files are present and match

    @property
    def missing_in_home(self) -> list[str]:
        return [f.name for f in self.files if f.in_workspace and not f.in_home]

    @property
    def drifted(self) -> list[str]:
        return [f.name for f in self.files if f.match is False]

    @property
    def recommendation(self) -> str:
        if self.synced:
            return "all SSH files are in sync — push should work"
        parts = []
        if self.missing_in_home:
            parts.append(f"missing in ~/.ssh/: {', '.join(self.missing_in_home)}")
        if self.drifted:
            parts.append(f"content differs: {', '.join(self.drifted)}")
        return "run with --sync to copy from workspace: " + "; ".join(parts)


def _sha256(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    h = hashlib.sha256()
    try:
        h.update(path.read_bytes())
        return h.hexdigest()
    except OSError:
        return None


def check_sync(
    workspace: Path = WORKSPACE_SSH,
    home: Path = HOME_SSH,
    required: list[str] | None = None,
) -> SyncReport:
    """Compare SSH files between workspace and home directories."""
    files_to_check = required or REQUIRED_FILES
    statuses = []

    for name in files_to_check:
        ws_path = workspace / name
        hm_path = home / name
        ws_sha = _sha256(ws_path)
        hm_sha = _sha256(hm_path)
        ws_exists = ws_path.exists()
        hm_exists = hm_path.exists()

        if ws_exists and hm_exists:
            match = ws_sha == hm_sha
        else:
            match = None  # can't compare if one side is missing

        statuses.append(FileStatus(
            name=name,
            in_workspace=ws_exists,
            in_home=hm_exists,
            match=match,
            workspace_sha256=ws_sha,
            home_sha256=hm_sha,
        ))

    synced = all(
        s.in_workspace and s.in_home and s.match is not False
        for s in statuses
    )

    return SyncReport(
        workspace_dir=str(workspace),
        home_dir=str(home),
        files=statuses,
        synced=synced,
    )


def do_sync(
    workspace: Path = WORKSPACE_SSH,
    home: Path = HOME_SSH,
    required: list[str] | None = None,
) -> list[str]:
    """Copy missing or drifted files from workspace to home.

    Returns the list of files that were copied.
    Creates the home .ssh directory if it doesn't exist.
    Sets appropriate permissions (700 for dir, 600 for private keys).
    """
    files_to_check = required or REQUIRED_FILES
    copied = []

    home.mkdir(parents=True, exist_ok=True)
    os.chmod(str(home), 0o700)

    for name in files_to_check:
        ws_path = workspace / name
        hm_path = home / name

        if not ws_path.exists():
            continue  # nothing to copy from

        ws_sha = _sha256(ws_path)
        hm_sha = _sha256(hm_path)

        if ws_sha == hm_sha:
            continue  # already in sync

        shutil.copy2(str(ws_path), str(hm_path))

        # private key must be 600
        if name.startswith("id_") and not name.endswith(".pub"):
            os.chmod(str(hm_path), 0o600)
        elif name == "known_hosts" or name == "config" or name.endswith(".pub"):
            os.chmod(str(hm_path), 0o644)

        copied.append(name)

    return copied


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sync", action="store_true", help="copy missing/drifted files from workspace to home")
    ap.add_argument("--json", action="store_true", help="output machine-readable JSON")
    args = ap.parse_args()

    if args.sync:
        copied = do_sync()
        if copied:
            print(f"synced {len(copied)} file(s): {', '.join(copied)}")
        else:
            print("already in sync")

    report = check_sync()

    if args.json:
        output = {
            "synced": report.synced,
            "workspace_dir": report.workspace_dir,
            "home_dir": report.home_dir,
            "missing_in_home": report.missing_in_home,
            "drifted": report.drifted,
            "recommendation": report.recommendation,
            "files": [asdict(f) for f in report.files],
        }
        print(json.dumps(output, indent=2))
    else:
        for f in report.files:
            status = "✓" if f.match else ("✗" if f.match is False else "?")
            ws = "ws" if f.in_workspace else "  "
            hm = "hm" if f.in_home else "  "
            print(f"  {status} {f.name:20s} [{ws}] [{hm}]")
        print()
        print(report.recommendation)

    return 0 if report.synced else 1


if __name__ == "__main__":
    sys.exit(main())
