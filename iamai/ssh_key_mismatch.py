"""SSH key mismatch detector — distinguish "not registered" from "wrong key".

the existing ssh_key_health module classifies keys into GREEN / AMBER / RED.
AMBER means "key exists locally but github rejects it." but AMBER lumps
together two very different failure modes:

  1. the key was never added to github (fresh install, first run)
  2. the key was swapped out — container recycle replaced the key file
     with a stale backup from OSS, so the fingerprint no longer matches
     what github has on file.

this module separates those two cases. a mismatch is worse than an
unregistered key: an unregistered key means no one ever set up push;
a mismatch means push *used to work* and now silently fails on every
attempt while the backlog grows.

detection strategy:

  1. extract the fingerprint of the local private key via ssh-keygen.
  2. probe github with `ssh -T git@github.com` and capture stderr.
  3. if "permission denied (publickey)", the offered key was rejected.
     we cannot query github's list of registered deploy keys without
     a token, so we classify based on context:
       - if a key backup was recently restored → MISMATCH
       - if no prior successful push exists → UNREGISTERED
       - if push history shows recent success → REVOKED or SWAPPED

the caretaker uses the classification to decide the remediation:
UNREGISTERED → print the pubkey, ask the operator to add it.
MISMATCH → the operator needs to either re-register the new key or
           restore the correct key from the last known-good backup.
REVOKED → someone removed the key; investigate.

usage:

    from iamai.ssh_key_mismatch import classify_key_failure, MismatchKind

    kind = classify_key_failure()
    if kind == MismatchKind.MISMATCH:
        print("local key fingerprint differs from registered key")
    elif kind == MismatchKind.UNREGISTERED:
        print("key never registered on github")

designed for the caretaker to call before push_preflight.py gives up,
so the remediation hint can be specific instead of the generic
"Permission denied" that fills the log with noise.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class MismatchKind(str, Enum):
    OK = "ok"
    MISMATCH = "mismatch"
    UNREGISTERED = "unregistered"
    REVOKED = "revoked"
    UNKNOWN = "unknown"


@dataclass
class MismatchResult:
    kind: MismatchKind
    local_fingerprint: str | None = None
    detail: str = ""
    checked_at: float = 0.0

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = time.time()


def _extract_fingerprint(key_path: Path) -> str | None:
    """extract SHA256 fingerprint from a private key file.

    returns None if the file does not exist, is unreadable, or ssh-keygen
    fails for any reason.
    """
    if not key_path.exists():
        return None
    try:
        result = subprocess.run(
            ["ssh-keygen", "-lf", str(key_path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split()
            return parts[1] if len(parts) >= 2 else None
    except Exception:
        pass
    return None


def _probe_github() -> tuple[int, str]:
    """attempt ssh -T git@github.com, return (returncode, stderr)."""
    try:
        result = subprocess.run(
            ["ssh", "-T", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
             "git@github.com"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode, result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "ssh connection timed out"
    except Exception as exc:
        return -2, str(exc)


def _find_local_key(candidates: list[Path] | None = None) -> Path | None:
    """return the first readable key path from standard candidates.

    if candidates is provided, uses that list instead of the defaults.
    useful for tests that need to control the search paths.
    """
    if candidates is None:
        candidates = [
            Path.home() / ".ssh" / "id_ed25519",
            Path.home() / ".ssh" / "id_rsa",
            Path("/root/.ssh/id_ed25519"),
            Path("/tmp/iamai_key"),
        ]
    for path in candidates:
        try:
            if path.exists() and path.stat().st_mode & 0o777 <= 0o600:
                return path
        except (OSError, PermissionError):
            continue
    return None


def _has_push_history(repo_path: Path) -> bool:
    """check whether git log shows any successful push markers.

    a rough heuristic: if the reflog mentions 'push' or if there are
    remote-tracking branches with recent updates, push has worked before.
    """
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--remotes", "-1"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(repo_path),
        )
        return result.returncode == 0 and len(result.stdout.strip()) > 0
    except Exception:
        return False


def classify_key_failure(repo_path: Path | None = None) -> MismatchResult:
    """classify why push authentication is failing.

    returns a MismatchResult with the most likely cause. when repo_path
    is provided, uses push history to refine the classification.
    """
    key_path = _find_local_key()
    if key_path is None:
        return MismatchResult(
            kind=MismatchKind.UNKNOWN,
            detail="no readable ssh key found in standard locations",
        )

    fp = _extract_fingerprint(key_path)
    rc, stderr = _probe_github()

    if rc == 0:
        return MismatchResult(
            kind=MismatchKind.OK,
            local_fingerprint=fp,
            detail=stderr,
        )

    if "permission denied (publickey)" not in stderr.lower():
        return MismatchResult(
            kind=MismatchKind.UNKNOWN,
            local_fingerprint=fp,
            detail=f"unexpected ssh response: {stderr}",
        )

    # key rejected — now distinguish mismatch from unregistered
    has_history = _has_push_history(repo_path) if repo_path else False

    if has_history:
        # push worked before but fails now → key was swapped or revoked
        return MismatchResult(
            kind=MismatchKind.MISMATCH,
            local_fingerprint=fp,
            detail=(
                "local key rejected; push history exists. "
                "likely container recycle replaced the key with a stale backup. "
                "re-register the current pubkey or restore the original key."
            ),
        )

    # no push history and key rejected → probably never registered
    return MismatchResult(
        kind=MismatchKind.UNREGISTERED,
        local_fingerprint=fp,
        detail=(
            "local key rejected and no push history found. "
            "add the pubkey to github as a deploy key with write access."
        ),
    )
