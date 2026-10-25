"""SSH key health monitor — detect silent push failures before they pile up.

a repo that cannot push is a repo that is lying to itself. the writer keeps
writing, the committer keeps committing, but nothing leaves the machine.
by the time a caretaker notices, there may be hundreds of unpushed commits
and days of accumulated work trapped on disk.

this module provides a three-state health model:

  GREEN:  key exists, registered on github, push succeeds
  AMBER:  key exists locally, but github rejects it (not registered or revoked)
  RED:    key file missing or unreadable

the monitor runs as a lightweight pre-flight check and can be called from
the writer loop or the batch committer to surface push failures early,
instead of discovering them after the next reclamation event.

usage:

    from iamai.ssh_key_health import ssh_health_check

    result = ssh_health_check()
    if result.state == HealthState.AMBER:
        # key exists but not registered — alert operator
        ...
    elif result.state == HealthState.RED:
        # key missing — push will never work
        ...
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class HealthState(str, Enum):
    """push health states, ordered by severity."""

    GREEN = "green"   # everything works
    AMBER = "amber"   # key exists but github rejects it
    RED = "red"       # key missing or unreadable
    UNKNOWN = "unknown"  # cannot determine


@dataclass
class HealthReport:
    """result of a single health check.

    the `unpushed_count` field lets callers decide whether amber state
    is tolerable (a few commits) or urgent (days of backlog).
    """

    state: HealthState
    key_path: Path
    fingerprint: str | None = None
    reason: str = ""
    unpushed_count: int = 0
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def _key_exists(key_path: Path) -> bool:
    """check whether the private key file exists and is readable."""
    return key_path.exists() and key_path.is_file()


def _extract_fingerprint(key_path: Path) -> str | None:
    """extract sha256 fingerprint from the public key file."""
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
            parts = result.stdout.split()
            if len(parts) >= 2 and parts[1].startswith("SHA256:"):
                return parts[1]
    except (subprocess.TimeoutExpired, Exception):
        pass
    return None


def _probe_github(key_path: Path) -> tuple[bool, str]:
    """test ssh authentication against github."""
    try:
        result = subprocess.run(
            [
                "ssh",
                "-T",
                "-i", str(key_path),
                "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5",
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


def _count_unpushed(repo_path: Path) -> int:
    """count commits ahead of origin that have not been pushed."""
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "origin/main..HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_path),
            timeout=5,
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, Exception):
        pass
    return -1  # unknown


def ssh_health_check(
    key_path: Path | None = None,
    repo_path: Path | None = None,
) -> HealthReport:
    """run a full push health check and return a report.

    args:
        key_path: path to the ssh private key.
                  defaults to ~/.ssh/id_ed25519
        repo_path: path to the git repository root.
                   defaults to the current working directory.

    returns:
        a HealthReport with state, fingerprint, unpushed count,
        and a human-readable reason string.
    """
    if key_path is None:
        key_path = Path.home() / ".ssh" / "id_ed25519"
    if repo_path is None:
        repo_path = Path.cwd()

    # step 1: does the key exist?
    if not _key_exists(key_path):
        return HealthReport(
            state=HealthState.RED,
            key_path=key_path,
            reason=f"key file missing: {key_path}",
            unpushed_count=_count_unpushed(repo_path),
        )

    # step 2: extract fingerprint for identification
    fingerprint = _extract_fingerprint(key_path)

    # step 3: can we authenticate with github?
    success, message = _probe_github(key_path)

    unpushed = _count_unpushed(repo_path)

    if success:
        return HealthReport(
            state=HealthState.GREEN,
            key_path=key_path,
            fingerprint=fingerprint,
            reason=f"authenticated: {message}",
            unpushed_count=unpushed,
        )

    # step 4: classify the failure
    if "permission denied" in message.lower():
        return HealthReport(
            state=HealthState.AMBER,
            key_path=key_path,
            fingerprint=fingerprint,
            reason="key exists but github rejected it — deploy key not registered",
            unpushed_count=unpushed,
        )

    return HealthReport(
        state=HealthState.UNKNOWN,
        key_path=key_path,
        fingerprint=fingerprint,
        reason=f"could not determine status: {message}",
        unpushed_count=unpushed,
    )


def format_health_report(report: HealthReport) -> str:
    """format a health report as a single-line status string.

    useful for log lines and caretaker briefings.

    example output:
        [AMBER] key=~/.ssh/id_ed25519 fingerprint=SHA256:abc... unpushed=41 reason=key exists but github rejected it
    """
    fp = report.fingerprint or "none"
    return (
        f"[{report.state.value.upper()}] "
        f"key={report.key_path} "
        f"fingerprint={fp} "
        f"unpushed={report.unpushed_count} "
        f"reason={report.reason}"
    )
