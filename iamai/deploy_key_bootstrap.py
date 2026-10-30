"""Deploy key bootstrap — generate and configure SSH keys for GitHub push.

The repo has been blocked from pushing for 80+ commits because the SSH
deploy key is missing or unregistered.  ssh_key_health detects the
problem; push_diag classifies it; but nothing in the stack actually
*fixes* it.

This module closes the loop.  It provides a single callable that:

1. Checks whether a usable ed25519 key already exists.
2. If not, generates one (non-interactively, no passphrase).
3. Ensures ~/.ssh/config routes github.com through the right key.
4. Returns the public key text so the operator can register it as
   a GitHub deploy key (one click in the repo settings page).

The module is designed as pure logic + thin subprocess wrappers so
that tests can override the filesystem and command layers without
spawning real ssh-keygen processes.

Usage::

    from iamai.deploy_key_bootstrap import bootstrap

    result = bootstrap()
    if result.action == "generated":
        print("Register this key on GitHub:")
        print(result.public_key)
    elif result.action == "exists":
        print("Key already present; check registration.")

State model::

    MISSING   → no key file found → generate one
    EXISTS    → key file present, ssh config ok → return it
    ORPHAN    → key file present but ssh config missing/wrong → fix config
    READONLY  → key file exists but not writable, cannot regenerate
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class KeyState(str, Enum):
    """Pre-bootstrap state of the deploy key."""
    MISSING = "missing"
    EXISTS = "exists"
    ORPHAN = "orphan"       # key exists but ssh config is wrong
    READONLY = "readonly"   # cannot write, permission denied


class Action(str, Enum):
    """What the bootstrap function actually did."""
    GENERATED = "generated"     # created a new key pair
    REUSED = "reused"           # key already fine, nothing changed
    FIXED_CONFIG = "fixed"      # key ok, repaired ssh config
    SKIPPED = "skipped"         # could not proceed (readonly, etc.)


@dataclass
class BootstrapResult:
    """Outcome of a bootstrap call."""
    state: KeyState
    action: Action
    key_path: Path
    public_key: str = ""
    fingerprint: str = ""
    ssh_config_ok: bool = False
    reason: str = ""


# ---------------------------------------------------------------------------
# internal helpers — thin wrappers so tests can monkeypatch
# ---------------------------------------------------------------------------

def _key_exists(key_path: Path) -> bool:
    """True if both private and .pub files exist and are non-empty."""
    pub = key_path.with_suffix(key_path.suffix + ".pub")
    return (
        key_path.exists()
        and key_path.stat().st_size > 0
        and pub.exists()
        and pub.stat().st_size > 0
    )


def _key_writable(key_path: Path) -> bool:
    """True if we can write to the key's parent directory."""
    parent = key_path.parent
    if not parent.exists():
        try:
            parent.mkdir(parents=True, exist_ok=True)
            return True
        except PermissionError:
            return False
    return os.access(parent, os.W_OK)


def _generate_key(key_path: Path, comment: str = "iamai-deploy-key") -> bool:
    """Generate an ed25519 key pair.  Returns True on success."""
    try:
        result = subprocess.run(
            [
                "ssh-keygen",
                "-t", "ed25519",
                "-f", str(key_path),
                "-N", "",           # no passphrase
                "-C", comment,
                "-q",               # quiet
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _read_public_key(key_path: Path) -> str:
    """Read the .pub file contents."""
    pub = key_path.with_suffix(key_path.suffix + ".pub")
    if pub.exists():
        return pub.read_text().strip()
    return ""


def _extract_fingerprint(key_path: Path) -> str:
    """Extract SHA256 fingerprint from the public key."""
    pub = key_path.with_suffix(key_path.suffix + ".pub")
    if not pub.exists():
        return ""
    try:
        result = subprocess.run(
            ["ssh-keygen", "-lf", str(pub)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.split()
            if len(parts) >= 2 and parts[1].startswith("SHA256:"):
                return parts[1]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


def _ssh_config_ok(ssh_dir: Path, key_path: Path) -> bool:
    """Check if ~/.ssh/config has a correct Host github.com block."""
    config = ssh_dir / "config"
    if not config.exists():
        return False
    text = config.read_text()
    # crude but sufficient: look for Host github.com and the key path
    if "Host github.com" not in text and "Host github.com\n" not in text:
        return False
    if str(key_path) in text:
        return True
    return False


def _write_ssh_config(ssh_dir: Path, key_path: Path) -> bool:
    """Append a Host github.com block to ~/.ssh/config."""
    config = ssh_dir / "config"
    block = (
        "\n# Added by deploy_key_bootstrap\n"
        "Host github.com\n"
        f"    IdentityFile {key_path}\n"
        "    IdentitiesOnly yes\n"
        "    StrictHostKeyChecking accept-new\n"
    )
    try:
        existing = config.read_text() if config.exists() else ""
        # remove old bootstrap block if present
        if "# Added by deploy_key_bootstrap" in existing:
            lines = existing.split("\n")
            new_lines = []
            skip = False
            for line in lines:
                if line.strip() == "# Added by deploy_key_bootstrap":
                    skip = True
                    continue
                if skip:
                    # skip lines belonging to our Host block:
                    #   - indented continuation lines
                    #   - the Host line itself (starts with "Host ")
                    #   - blank lines between directives
                    if line.startswith("    ") or line.strip() == "" or line.strip().startswith("Host "):
                        continue
                    # non-indented non-Host line = different block, stop skipping
                    skip = False
                if not skip:
                    new_lines.append(line)
            existing = "\n".join(new_lines)
        config.write_text(existing + block)
        config.chmod(0o600)
        return True
    except (PermissionError, OSError):
        return False


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def bootstrap(
    key_path: Optional[Path] = None,
    ssh_dir: Optional[Path] = None,
    comment: str = "iamai-deploy-key",
) -> BootstrapResult:
    """Bootstrap a deploy key for GitHub push access.

    Parameters
    ----------
    key_path : Path, optional
        Where to place the private key.  Defaults to ``~/.ssh/id_ed25519``.
    ssh_dir : Path, optional
        SSH configuration directory.  Defaults to ``~/.ssh``.
    comment : str
        Comment embedded in the generated key.

    Returns
    -------
    BootstrapResult with the action taken and the public key text.
    """
    if ssh_dir is None:
        ssh_dir = Path.home() / ".ssh"
    if key_path is None:
        key_path = ssh_dir / "id_ed25519"

    key_path = Path(key_path)
    ssh_dir = Path(ssh_dir)

    # ensure ssh dir exists
    try:
        ssh_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    except PermissionError:
        return BootstrapResult(
            state=KeyState.READONLY,
            action=Action.SKIPPED,
            key_path=key_path,
            reason=f"cannot create ssh dir {ssh_dir}",
        )

    # --- state assessment ---
    if _key_exists(key_path):
        state = KeyState.EXISTS
        if not _ssh_config_ok(ssh_dir, key_path):
            state = KeyState.ORPHAN
    elif not _key_writable(key_path):
        return BootstrapResult(
            state=KeyState.READONLY,
            action=Action.SKIPPED,
            key_path=key_path,
            reason=f"key path {key_path} not writable",
        )
    else:
        state = KeyState.MISSING

    # --- action ---
    if state == KeyState.MISSING:
        if not _generate_key(key_path, comment):
            return BootstrapResult(
                state=state,
                action=Action.SKIPPED,
                key_path=key_path,
                reason="ssh-keygen failed",
            )
        # fix permissions
        try:
            key_path.chmod(0o600)
            pub = key_path.with_suffix(key_path.suffix + ".pub")
            if pub.exists():
                pub.chmod(0o644)
        except OSError:
            pass
        config_ok = _write_ssh_config(ssh_dir, key_path)
        return BootstrapResult(
            state=state,
            action=Action.GENERATED,
            key_path=key_path,
            public_key=_read_public_key(key_path),
            fingerprint=_extract_fingerprint(key_path),
            ssh_config_ok=config_ok,
        )

    if state == KeyState.ORPHAN:
        config_ok = _write_ssh_config(ssh_dir, key_path)
        return BootstrapResult(
            state=state,
            action=Action.FIXED_CONFIG,
            key_path=key_path,
            public_key=_read_public_key(key_path),
            fingerprint=_extract_fingerprint(key_path),
            ssh_config_ok=config_ok,
        )

    # state == EXISTS
    return BootstrapResult(
        state=state,
        action=Action.REUSED,
        key_path=key_path,
        public_key=_read_public_key(key_path),
        fingerprint=_extract_fingerprint(key_path),
        ssh_config_ok=True,
    )


def format_instructions(result: BootstrapResult) -> str:
    """Human-readable next steps based on the bootstrap result."""
    if result.action == Action.SKIPPED:
        return f"[!] bootstrap skipped: {result.reason}\n    manual intervention needed."

    lines = [f"[*] key state: {result.state.value}  action: {result.action.value}"]
    lines.append(f"    path:        {result.key_path}")
    if result.fingerprint:
        lines.append(f"    fingerprint: {result.fingerprint}")

    if result.action in (Action.GENERATED, Action.FIXED_CONFIG):
        lines.append("")
        lines.append("[>] Register this key on GitHub:")
        lines.append(f"    repo -> Settings -> Deploy keys -> Add deploy key")
        lines.append(f"    paste the public key below:")
        lines.append("")
        lines.append(f"    {result.public_key}")
        lines.append("")
        lines.append("[>] then verify with:")
        lines.append("    ssh -T git@github.com")

    elif result.action == Action.REUSED:
        lines.append("")
        lines.append("[ok] key and ssh config look good.")
        lines.append("    if push still fails, the key may not be registered on GitHub.")
        lines.append("    register the public key above as a deploy key.")

    return "\n".join(lines)
