"""restart_readiness_probe — pre-flight checks before restarting the writer.

Restarting a dead writer blindly can mask the real failure.  If the ssh
deploy key is missing, the new writer will start but never push; if
``.git/index.lock`` is stale, the batch committer will wedge on its
first commit; if disk is full, strokes will silently fail to write.

This module runs four independent probes and returns a readiness
verdict with specific failure reasons::

    from iamai.restart_readiness_probe import RestartReadinessProbe

    probe = RestartReadinessProbe(
        repo_root="/path/to/repo",
        ssh_key_path="/path/to/.ssh/id_ed25519",
    )
    report = probe.check()
    report.ready          # True / False
    report.score          # 0.0 – 1.0 (fraction of checks passed)
    report.failures       # list of failure reason strings
    report.summary()      # human-readable one-liner

The four probes:

====================  =====================================================
probe                 what it checks
====================  =====================================================
deploy_key            ssh private key file exists and is readable
index_lock            ``.git/index.lock`` is absent or younger than
                      ``lock_threshold`` seconds (default 120)
disk_headroom         filesystem free space exceeds ``min_free_mb``
                      (default 50 MB)
heartbeat_fresh       writer heartbeat file is absent (clean start) or
                      younger than ``heartbeat_max_age`` (default 3600 s)
====================  =====================================================

Design:

- Pure Python, no subprocess calls (filesystem checks only).
- All paths and thresholds are constructor arguments (testable).
- Frozen dataclass report — immutable snapshot at check time.
- Each probe is independent; one failure does not skip the others.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ── defaults ──────────────────────────────────────────────────

DEFAULT_LOCK_THRESHOLD: float = 120.0     # seconds; stale if older
DEFAULT_MIN_FREE_MB: float = 50.0         # megabytes of free disk
DEFAULT_HEARTBEAT_MAX_AGE: float = 3600.0  # seconds; 1 hour
DEFAULT_SSH_KEY_NAME: str = "id_ed25519"


# ── report ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProbeResult:
    """Single probe outcome."""

    name: str
    passed: bool
    detail: str = ""

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        suffix = f" — {self.detail}" if self.detail else ""
        return f"[{status}] {self.name}{suffix}"


@dataclass(frozen=True)
class ReadinessReport:
    """Aggregate of all probe results."""

    results: List[ProbeResult] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    @property
    def ready(self) -> bool:
        """True when every probe passed."""
        return all(r.passed for r in self.results)

    @property
    def score(self) -> float:
        """Fraction of probes that passed (0.0 – 1.0)."""
        if not self.results:
            return 0.0
        passed = sum(1 for r in self.results if r.passed)
        return round(passed / len(self.results), 4)

    @property
    def failures(self) -> List[str]:
        """List of failure reason strings (empty when ready)."""
        return [str(r) for r in self.results if not r.passed]

    def summary(self) -> str:
        """Human-readable one-liner."""
        if self.ready:
            return (
                f"ready ({len(self.results)}/{len(self.results)} probes passed, "
                f"score {self.score:.2f})"
            )
        n_fail = len(self.failures)
        return (
            f"NOT ready ({n_fail}/{len(self.results)} probes failed, "
            f"score {self.score:.2f})"
        )


# ── individual probes ────────────────────────────────────────


def _probe_deploy_key(ssh_key_path: Optional[str]) -> ProbeResult:
    """Check that the ssh private key file exists and is readable."""
    if not ssh_key_path:
        return ProbeResult(
            name="deploy_key",
            passed=False,
            detail="no ssh key path provided",
        )
    p = Path(ssh_key_path)
    if not p.exists():
        return ProbeResult(
            name="deploy_key",
            passed=False,
            detail=f"key file not found: {p}",
        )
    if not p.is_file():
        return ProbeResult(
            name="deploy_key",
            passed=False,
            detail=f"key path is not a file: {p}",
        )
    try:
        # readability check — open and read one byte
        with open(p, "rb") as f:
            f.read(1)
        return ProbeResult(name="deploy_key", passed=True, detail=str(p))
    except PermissionError:
        return ProbeResult(
            name="deploy_key",
            passed=False,
            detail=f"key file not readable (permission denied): {p}",
        )
    except OSError as exc:
        return ProbeResult(
            name="deploy_key",
            passed=False,
            detail=f"key file read error: {exc}",
        )


def _probe_index_lock(
    repo_root: str, lock_threshold: float, now: float
) -> ProbeResult:
    """Check that .git/index.lock is absent or younger than threshold."""
    lock_path = Path(repo_root) / ".git" / "index.lock"
    if not lock_path.exists():
        return ProbeResult(name="index_lock", passed=True, detail="no lock file")
    try:
        mtime = lock_path.stat().st_mtime
    except OSError as exc:
        return ProbeResult(
            name="index_lock",
            passed=False,
            detail=f"cannot stat lock file: {exc}",
        )
    age = now - mtime
    if age > lock_threshold:
        return ProbeResult(
            name="index_lock",
            passed=False,
            detail=f"stale lock: {age:.0f}s old (threshold {lock_threshold:.0f}s)",
        )
    return ProbeResult(
        name="index_lock",
        passed=True,
        detail=f"lock file young ({age:.0f}s), likely active",
    )


def _probe_disk_headroom(
    repo_root: str, min_free_mb: float
) -> ProbeResult:
    """Check that the filesystem has enough free space."""
    try:
        usage = os.statvfs(repo_root)
    except OSError as exc:
        return ProbeResult(
            name="disk_headroom",
            passed=False,
            detail=f"cannot stat filesystem: {exc}",
        )
    free_bytes = usage.f_bavail * usage.f_frsize
    free_mb = free_bytes / (1024 * 1024)
    if free_mb < min_free_mb:
        return ProbeResult(
            name="disk_headroom",
            passed=False,
            detail=f"low disk: {free_mb:.1f} MB free (need {min_free_mb:.0f} MB)",
        )
    return ProbeResult(
        name="disk_headroom",
        passed=True,
        detail=f"{free_mb:.1f} MB free",
    )


def _probe_heartbeat_fresh(
    repo_root: str, writer_id: str, heartbeat_max_age: float, now: float
) -> ProbeResult:
    """Check writer heartbeat file age.

    A missing heartbeat means a clean start (passed).  A recent
    heartbeat also passes — the previous writer died recently and
    state is likely consistent.  A very old heartbeat suggests the
    writer died long ago and state files may be stale.
    """
    hb_path = Path(repo_root) / "data" / f"heartbeat.{writer_id}.json"
    if not hb_path.exists():
        return ProbeResult(
            name="heartbeat_fresh",
            passed=True,
            detail="no heartbeat file (clean start)",
        )
    try:
        mtime = hb_path.stat().st_mtime
    except OSError as exc:
        return ProbeResult(
            name="heartbeat_fresh",
            passed=False,
            detail=f"cannot stat heartbeat: {exc}",
        )
    age = now - mtime
    if age > heartbeat_max_age:
        return ProbeResult(
            name="heartbeat_fresh",
            passed=False,
            detail=(
                f"stale heartbeat: {age:.0f}s old "
                f"(threshold {heartbeat_max_age:.0f}s)"
            ),
        )
    return ProbeResult(
        name="heartbeat_fresh",
        passed=True,
        detail=f"heartbeat {age:.0f}s old",
    )


# ── orchestrator ──────────────────────────────────────────────


class RestartReadinessProbe:
    """Run all pre-flight probes and produce a readiness report.

    Parameters
    ----------
    repo_root : str
        Path to the repository root (must contain ``.git/``).
    ssh_key_path : str or None
        Path to the ssh deploy key file.
    writer_id : str
        Writer identifier (used to locate heartbeat file).
    lock_threshold : float
        Max age in seconds for ``.git/index.lock`` before it is
        considered stale.
    min_free_mb : float
        Minimum free disk space in megabytes.
    heartbeat_max_age : float
        Max age in seconds for the writer heartbeat file.
    now : float or None
        Override current time (for testing).
    """

    def __init__(
        self,
        repo_root: str,
        ssh_key_path: Optional[str] = None,
        writer_id: str = "qwen",
        lock_threshold: float = DEFAULT_LOCK_THRESHOLD,
        min_free_mb: float = DEFAULT_MIN_FREE_MB,
        heartbeat_max_age: float = DEFAULT_HEARTBEAT_MAX_AGE,
        now: Optional[float] = None,
    ) -> None:
        self.repo_root = repo_root
        self.ssh_key_path = ssh_key_path
        self.writer_id = writer_id
        self.lock_threshold = lock_threshold
        self.min_free_mb = min_free_mb
        self.heartbeat_max_age = heartbeat_max_age
        self._now = now if now is not None else time.time()

    def check(self) -> ReadinessReport:
        """Execute all probes and return aggregate report."""
        results: List[ProbeResult] = [
            _probe_deploy_key(self.ssh_key_path),
            _probe_index_lock(self.repo_root, self.lock_threshold, self._now),
            _probe_disk_headroom(self.repo_root, self.min_free_mb),
            _probe_heartbeat_fresh(
                self.repo_root, self.writer_id, self.heartbeat_max_age, self._now
            ),
        ]
        return ReadinessReport(results=results, timestamp=self._now)
