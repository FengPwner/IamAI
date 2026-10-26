"""push_recovery_orchestrator — single-call push recovery pipeline.

the existing modules each handle one slice of the push problem:

  ssh_key_health    → is the key file present and valid?
  push_key_recovery → can we restore it from a backup?
  ssh_key_registration → is github willing to accept it?
  push_key_watchdog → should we stop retrying?

this orchestrator chains them into a single call that a caretaker or
cron job can invoke without knowing the internal module topology.
the pipeline is:

  1. preflight: does the key exist at ~/.ssh/id_ed25519?
  2. recovery:  if missing, try known backup locations.
  3. probe:     does github accept the key?
  4. push:      attempt `git push origin main`.
  5. report:    structured outcome with actionable next steps.

design notes:

  - each step is idempotent. calling orchestrate() twice in a row
    produces the same report (minus any commits that landed between calls).
  - no step mutates github-side state. registration is always a human
    action; the orchestrator just makes the gap obvious.
  - the report includes a `remediation` field that a caretaker can
    surface verbatim to the repo owner.

usage:

    from iamai.push_recovery_orchestrator import orchestrate

    report = orchestrate()
    if report.push_succeeded:
        print("all clear")
    else:
        print(report.remediation)
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional


class PipelineStep(str, Enum):
    """which step the pipeline reached before stopping."""
    PREFLIGHT = "preflight"
    RECOVERY = "recovery"
    PROBE = "probe"
    PUSH = "push"
    DONE = "done"


class PushOutcome(str, Enum):
    """final outcome of the orchestration."""
    SUCCESS = "success"          # push completed, backlog drained
    KEY_MISSING = "key_missing"  # no key found anywhere
    KEY_UNREGISTERED = "key_unregistered"  # key exists but github rejects it
    PUSH_FAILED = "push_failed"  # key accepted but push itself failed
    NETWORK_ERROR = "network_error"


DEFAULT_PRIMARY = Path.home() / ".ssh" / "id_ed25519"
BACKUP_LOCATIONS = [
    Path("/root/userdata/workspace/.ssh/id_ed25519"),
    Path("/tmp/iamai_key"),
]
SEARCH_DIRS = [Path("/root")]
SEARCH_DEPTH = 4


@dataclass
class RecoveryReport:
    """structured result of the full push recovery pipeline."""
    outcome: PushOutcome
    reached_step: PipelineStep
    key_present: bool = False
    key_source: Optional[str] = None
    key_fingerprint: Optional[str] = None
    github_accepts_key: Optional[bool] = None
    push_exit_code: Optional[int] = None
    unpushed_before: int = 0
    unpushed_after: int = 0
    remediation: str = ""
    errors: List[str] = field(default_factory=list)
    elapsed_s: float = 0.0

    @property
    def push_succeeded(self) -> bool:
        return self.outcome == PushOutcome.SUCCESS

    @property
    def backlog_drained(self) -> bool:
        return self.unpushed_after == 0

    @property
    def needs_human_action(self) -> bool:
        return self.outcome in (
            PushOutcome.KEY_MISSING,
            PushOutcome.KEY_UNREGISTERED,
        )

    def as_dict(self) -> dict:
        return {
            "outcome": self.outcome.value,
            "reached_step": self.reached_step.value,
            "key_present": self.key_present,
            "key_source": self.key_source,
            "key_fingerprint": self.key_fingerprint,
            "github_accepts_key": self.github_accepts_key,
            "push_exit_code": self.push_exit_code,
            "unpushed_before": self.unpushed_before,
            "unpushed_after": self.unpushed_after,
            "remediation": self.remediation,
            "errors": self.errors,
            "elapsed_s": round(self.elapsed_s, 2),
        }


def _count_unpushed(repo: str = ".") -> int:
    """count commits ahead of origin/main."""
    try:
        out = subprocess.run(
            ["git", "rev-list", "--count", "HEAD", "^origin/main"],
            capture_output=True, text=True, cwd=repo, timeout=10,
        )
        return int(out.stdout.strip()) if out.returncode == 0 else 0
    except (ValueError, subprocess.TimeoutExpired):
        return 0


def _key_fingerprint(key_path: Path) -> Optional[str]:
    """extract SHA256 fingerprint from a key file."""
    try:
        result = subprocess.run(
            ["ssh-keygen", "-lf", str(key_path)],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.split()
            if len(parts) >= 2 and parts[1].startswith("SHA256:"):
                return parts[1]
    except (subprocess.TimeoutExpired, Exception):
        pass
    return None


def _probe_github(timeout: int = 10) -> tuple[bool, str]:
    """test ssh connectivity to github. returns (accepted, stderr)."""
    try:
        result = subprocess.run(
            ["ssh", "-T", "git@github.com"],
            capture_output=True, text=True, timeout=timeout,
        )
        # github returns exit 1 even on success (it doesn't offer a shell).
        # the success marker is in stderr: "Hi <user>! You've successfully..."
        stderr = result.stderr
        if "successfully authenticated" in stderr.lower():
            return True, stderr
        return False, stderr
    except subprocess.TimeoutExpired:
        return False, "ssh probe timed out"
    except Exception as e:
        return False, str(e)


def _attempt_push(repo: str = ".", timeout: int = 60) -> tuple[int, str]:
    """run git push origin main. returns (exit_code, output)."""
    try:
        result = subprocess.run(
            ["git", "push", "origin", "main"],
            capture_output=True, text=True, cwd=repo, timeout=timeout,
        )
        output = result.stdout + result.stderr
        return result.returncode, output
    except subprocess.TimeoutExpired:
        return -1, "push timed out"
    except Exception as e:
        return -2, str(e)


def _try_restore_key(
    primary: Path = DEFAULT_PRIMARY,
    backups: Optional[List[Path]] = None,
    search_dirs: Optional[List[Path]] = None,
    depth: int = SEARCH_DEPTH,
) -> tuple[bool, Optional[str]]:
    """attempt to restore key from backup locations.

    returns (restored, source_path).
    """
    backup_locations = list(backups if backups is not None else BACKUP_LOCATIONS)

    # add recursive search under known dirs
    for search_dir in (search_dirs if search_dirs is not None else SEARCH_DIRS):
        if search_dir.exists():
            for candidate in search_dir.rglob("id_ed25519"):
                # limit depth
                try:
                    rel = candidate.relative_to(search_dir)
                    if len(rel.parts) <= depth:
                        backup_locations.append(candidate)
                except ValueError:
                    continue

    for source in backup_locations:
        if source.exists() and source.is_file():
            try:
                primary.parent.mkdir(parents=True, exist_ok=True)
                # copy private key
                primary.write_bytes(source.read_bytes())
                primary.chmod(0o600)
                # copy public key if available
                pub_source = source.with_suffix(source.suffix + ".pub")
                if pub_source.exists():
                    pub_dest = primary.with_suffix(primary.suffix + ".pub")
                    pub_dest.write_bytes(pub_source.read_bytes())
                    pub_dest.chmod(0o644)
                return True, str(source)
            except (OSError, PermissionError):
                continue

    return False, None


def orchestrate(
    repo: str = ".",
    primary_key: Optional[Path] = None,
    backup_locations: Optional[List[Path]] = None,
    search_dirs: Optional[List[Path]] = None,
    probe_timeout: int = 10,
    push_timeout: int = 60,
    attempt_recovery: bool = True,
) -> RecoveryReport:
    """run the full push recovery pipeline.

    this is the single entry point for caretakers and cron jobs.
    it is safe to call repeatedly; each call is independent.

    args:
        repo: path to the git repository (default: cwd).
        primary_key: override the default ~/.ssh/id_ed25519 path.
        backup_locations: override the default backup search list.
        probe_timeout: seconds to wait for ssh probe.
        push_timeout: seconds to wait for git push.
        attempt_recovery: if True, try to restore missing keys from backups.

    returns:
        RecoveryReport with structured outcome and remediation hint.
    """
    t0 = time.time()
    primary = primary_key or DEFAULT_PRIMARY
    errors: List[str] = []

    report = RecoveryReport(
        outcome=PushOutcome.PUSH_FAILED,
        reached_step=PipelineStep.PREFLIGHT,
    )
    report.unpushed_before = _count_unpushed(repo)

    # --- step 1: preflight ---
    report.reached_step = PipelineStep.PREFLIGHT
    if primary.exists() and primary.is_file():
        report.key_present = True
        report.key_source = str(primary)
        report.key_fingerprint = _key_fingerprint(primary)
    elif attempt_recovery:
        # --- step 2: recovery ---
        report.reached_step = PipelineStep.RECOVERY
        restored, source = _try_restore_key(
            primary=primary,
            backups=backup_locations,
            search_dirs=search_dirs,
        )
        if restored:
            report.key_present = True
            report.key_source = source
            report.key_fingerprint = _key_fingerprint(primary)
        else:
            report.outcome = PushOutcome.KEY_MISSING
            report.remediation = (
                "no SSH key found at primary path or any backup location. "
                "generate a new key with `ssh-keygen -t ed25519` and add the "
                "public key as a deploy key on the github repo."
            )
            report.errors.append("key missing and no backup found")
            report.elapsed_s = time.time() - t0
            return report
    else:
        report.outcome = PushOutcome.KEY_MISSING
        report.remediation = (
            f"SSH key not found at {primary}. recovery was disabled "
            f"(attempt_recovery=False). restore the key manually or "
            f"enable recovery."
        )
        report.errors.append("key missing and recovery disabled")
        report.elapsed_s = time.time() - t0
        return report

    # --- step 3: probe github ---
    report.reached_step = PipelineStep.PROBE
    accepted, probe_stderr = _probe_github(timeout=probe_timeout)
    report.github_accepts_key = accepted

    if not accepted:
        report.outcome = PushOutcome.KEY_UNREGISTERED
        report.remediation = (
            f"SSH key {report.key_fingerprint or '(unknown fingerprint)'} "
            f"exists locally but github rejects it. add the public key at "
            f"~/.ssh/id_ed25519.pub as a deploy key on "
            f"https://github.com/<owner>/<repo>/settings/keys"
        )
        report.errors.append(f"github probe failed: {probe_stderr.strip()}")
        report.elapsed_s = time.time() - t0
        return report

    # --- step 4: push ---
    report.reached_step = PipelineStep.PUSH
    exit_code, push_output = _attempt_push(repo=repo, timeout=push_timeout)
    report.push_exit_code = exit_code
    report.unpushed_after = _count_unpushed(repo)

    if exit_code == 0:
        report.outcome = PushOutcome.SUCCESS
        report.reached_step = PipelineStep.DONE
        report.remediation = (
            f"push succeeded. drained {report.unpushed_before} commits. "
            f"repo is up to date."
        )
    elif "could not resolve host" in push_output.lower() or "network" in push_output.lower():
        report.outcome = PushOutcome.NETWORK_ERROR
        report.remediation = (
            "push failed due to network error. this is transient; "
            "retry in a few minutes."
        )
        report.errors.append(push_output.strip())
    else:
        report.outcome = PushOutcome.PUSH_FAILED
        report.remediation = (
            f"push failed with exit code {exit_code}. "
            f"check `git status` and remote configuration."
        )
        report.errors.append(push_output.strip())

    report.elapsed_s = time.time() - t0
    return report
