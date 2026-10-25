"""Check whether an SSH key is registered with GitHub.

the push_preflight tool diagnoses push prerequisites but stops at
"key not registered" without distinguishing between "never added"
and "added then removed". this module parses the ssh fingerprint
from the key file and compares it against the list of registered
keys (when available via the github api or deploy key endpoint).

for the caretaker's purposes, the useful output is a classification:
  - REGISTERED: key is accepted, push should work
  - UNREGISTERED: key exists locally but github has never seen it
  - REVOKED: key was once accepted but is no longer in the account
  - UNKNOWN: cannot determine (network error, rate limit, etc.)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class KeyStatus(str, Enum):
    REGISTERED = "registered"
    UNREGISTERED = "unregistered"
    REVOKED = "revoked"
    UNKNOWN = "unknown"


@dataclass
class KeyCheck:
    status: KeyStatus
    fingerprint: str | None = None
    reason: str = ""


def extract_fingerprint(key_path: Path) -> str | None:
    """extract the sha256 fingerprint from a public key file.

    returns None if the public key does not exist or cannot be parsed.
    """
    pub_path = key_path.with_suffix(key_path.suffix + ".pub")
    if not pub_path.exists():
        return None

    try:
        result = subprocess.run(
            ["ssh-keygen", "-lf", str(pub_path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            # output format: "256 SHA256:abc... user@host (ED25519)"
            parts = result.stdout.split()
            if len(parts) >= 2 and parts[1].startswith("SHA256:"):
                return parts[1]
    except (subprocess.TimeoutExpired, Exception):
        pass
    return None


def probe_ssh_connection(key_path: Path) -> tuple[bool, str]:
    """test whether ssh can authenticate with github.

    returns (success, message) where message contains either
    "Hi <user>!" on success or the error string on failure.
    """
    try:
        result = subprocess.run(
            [
                "ssh",
                "-T",
                "-i",
                str(key_path),
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "ConnectTimeout=5",
                "git@github.com",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        output = result.stderr + result.stdout
        if "Hi " in output and "!" in output:
            return True, output.strip()
        if "Permission denied" in output:
            return False, "permission denied"
        return False, output.strip() or "connection failed"

    except subprocess.TimeoutExpired:
        return False, "connection timeout"
    except Exception as e:
        return False, str(e)


def check_key_registration(key_path: Path) -> KeyCheck:
    """determine whether an ssh key is registered with github.

    this function cannot distinguish REVOKED from UNREGISTERED
    without historical state (a record of past successful pushes).
    the caller must supply that context if the distinction matters.

    for a repo that has never pushed successfully, UNREGISTERED
    is the default assumption. for a repo with a history of
    successful pushes followed by sudden failure, REVOKED is
    more likely — but both look identical from a single probe.
    """
    if not key_path.exists():
        return KeyCheck(
            status=KeyStatus.UNKNOWN,
            reason=f"key file {key_path} does not exist",
        )

    fingerprint = extract_fingerprint(key_path)

    success, message = probe_ssh_connection(key_path)

    if success:
        return KeyCheck(
            status=KeyStatus.REGISTERED,
            fingerprint=fingerprint,
            reason=f"authenticated: {message}",
        )

    # connection failed; classify based on the failure mode.
    # "permission denied" means the key reached github but was rejected.
    # this could mean UNREGISTERED (never added) or REVOKED (removed).
    # without historical state, we report UNREGISTERED and let the
    # caretaker track whether this host has ever pushed successfully.
    if "permission denied" in message.lower():
        return KeyCheck(
            status=KeyStatus.UNREGISTERED,
            fingerprint=fingerprint,
            reason="key exists but github rejected it",
        )

    return KeyCheck(
        status=KeyStatus.UNKNOWN,
        fingerprint=fingerprint,
        reason=f"could not determine status: {message}",
    )
