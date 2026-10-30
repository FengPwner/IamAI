"""SSH key permission rescue — fix keys with overly permissive modes.

On FUSE-mounted workspaces (e.g. cloud OSS mounts), chmod may silently
fail: the filesystem reports success but permissions remain 0777.
SSH refuses to use keys with group/world-readable bits, causing
silent push failures that pile up as unpushed commits.

This module provides a two-step rescue:

1. **detect** — check if the SSH key has unsafe permissions (>0600)
2. **rescue** — copy the key to a writable filesystem (/tmp) with
   correct 0600 permissions and return a GIT_SSH_COMMAND environment
   override that git subprocess calls can use directly.

Usage::

    from iamai.ssh_key_rescue import rescue_key, needs_rescue

    if needs_rescue():
        env_override = rescue_key()
        # pass env_override to subprocess.run(..., env=env_override)

Design: the rescue is idempotent — calling it multiple times returns
the same /tmp path without re-copying. The copy is verified by
comparing file content, not just existence.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Dict, Optional

# Default key path used by this workspace's deploy_key_bootstrap config.
DEFAULT_KEY_PATH = Path("/root/userdata/workspace/.ssh/id_ed25519")
RESCUE_DIR = Path("/tmp/iamai-ssh-rescue")
RESCUE_KEY = RESCUE_DIR / "id_ed25519"


def _is_too_open(key_path: Path) -> bool:
    """Return True if the key has permissions wider than 0600."""
    if not key_path.exists():
        return False
    mode = key_path.stat().st_mode & 0o777
    return mode > 0o600


def _chmod_works(key_path: Path) -> bool:
    """Test whether chmod actually changes permissions on this filesystem."""
    if not key_path.exists():
        return False
    original = key_path.stat().st_mode & 0o777
    try:
        os.chmod(str(key_path), 0o600)
        result = key_path.stat().st_mode & 0o777
        return result == 0o600
    except OSError:
        return False
    finally:
        # Try to restore original — may also fail, which is fine.
        try:
            os.chmod(str(key_path), original)
        except OSError:
            pass


def needs_rescue(key_path: Optional[Path] = None) -> bool:
    """Check if the SSH key needs an permission rescue.

    Returns True when:
    - the key exists, AND
    - its permissions are too open (>0600), AND
    - chmod does not actually fix it on this filesystem.
    """
    key = key_path or DEFAULT_KEY_PATH
    if not _is_too_open(key):
        return False
    return not _chmod_works(key)


def rescue_key(key_path: Optional[Path] = None) -> Dict[str, str]:
    """Copy the key to /tmp with 0600 and return a GIT_SSH_COMMAND env dict.

    The returned dict can be merged into os.environ for subprocess calls::

        env = {**os.environ, **rescue_key()}
        subprocess.run(["git", "push"], env=env)

    Idempotent: if the rescue copy already exists and matches, skip.
    """
    key = key_path or DEFAULT_KEY_PATH

    if not key.exists():
        raise FileNotFoundError(f"SSH key not found: {key}")

    # Ensure rescue directory exists.
    RESCUE_DIR.mkdir(parents=True, exist_ok=True)

    # Copy if missing or content differs.
    if not RESCUE_KEY.exists() or RESCUE_KEY.read_bytes() != key.read_bytes():
        shutil.copy2(str(key), str(RESCUE_KEY))

    # Set correct permissions (this always works on /tmp).
    os.chmod(str(RESCUE_KEY), 0o600)

    # Build the SSH command override.
    ssh_cmd = (
        f"ssh -i {RESCUE_KEY} "
        f"-o StrictHostKeyChecking=accept-new "
        f"-o UserKnownHostsFile=/dev/null"
    )
    return {"GIT_SSH_COMMAND": ssh_cmd}


def rescue_env(key_path: Optional[Path] = None) -> Dict[str, str]:
    """Return a full environment dict with the SSH rescue applied.

    Convenience wrapper: merges rescue_key() output into a copy of
    the current os.environ.
    """
    if needs_rescue(key_path):
        override = rescue_key(key_path)
        return {**os.environ, **override}
    return dict(os.environ)
