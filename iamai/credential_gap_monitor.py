"""credential_gap_monitor — unified view of the credential-to-push chain.

the ssh key lifecycle has four failure points that all produce the same
symptom (Permission denied): missing key, wrong key, unregistered key,
revoked key. existing modules handle each in isolation. this monitor
composes them into a single diagnostic that answers the question a
caretaker actually asks: "why can't i push, and what do i do about it?"

design:
  - no network by default (fast path for batch committer pre-check)
  - network probe on demand (for caretaker visits)
  - output is a single dataclass with a human-readable remediation

the gap metaphor is deliberate: every failure is a gap somewhere in the
chain between "i wrote code" and "github has my code." naming the gap
helps the caretaker decide whether to wait, retry, or escalate.

usage:
    from iamai.credential_gap_monitor import CredentialGapMonitor

    monitor = CredentialGapMonitor()
    report = monitor.diagnose()
    print(report.summary)         # one-line human summary
    print(report.gap_type)        # MISSING | MISMATCH | UNREGISTERED | REVOKED | OK
    print(report.remediation)     # what to do next

with network probe:
    report = monitor.diagnose(probe=True)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class GapType(str, Enum):
    """classification of the credential gap."""

    OK = "ok"                    # key exists, registered, push works
    MISSING = "missing"          # key file does not exist
    UNREADABLE = "unreadable"    # key file exists but cannot be read
    MISMATCH = "mismatch"        # key exists but is not the one registered
    UNREGISTERED = "unregistered"  # key exists, never registered on github
    REVOKED = "revoked"          # key was registered, now rejected
    UNKNOWN = "unknown"          # cannot determine


@dataclass
class GapReport:
    """result of a credential gap diagnosis."""

    gap_type: GapType
    key_path: Path
    fingerprint: Optional[str] = None
    pubkey_content: Optional[str] = None
    remediation: str = ""
    summary: str = ""
    errors: list[str] = field(default_factory=list)
    probe_performed: bool = False
    probe_output: str = ""


class CredentialGapMonitor:
    """diagnose why push cannot work and what to do about it."""

    def __init__(self, key_path: str | Path | None = None, repo: str | Path | None = None):
        self.key_path = Path(key_path or Path.home() / ".ssh" / "id_ed25519")
        self.repo = Path(repo or ".")

    def diagnose(self, probe: bool = False) -> GapReport:
        """run the full diagnostic chain.

        if probe=False (default), diagnosis is local-only: checks file
        existence, readability, and fingerprint extraction. fast enough
        to call before every push attempt.

        if probe=True, also runs ssh -T git@github.com to determine
        registration status. slower but definitive.
        """
        # step 1: does the key exist?
        if not self.key_path.exists():
            return GapReport(
                gap_type=GapType.MISSING,
                key_path=self.key_path,
                remediation=self._remediation_missing(),
                summary=f"ssh key missing: {self.key_path}",
            )

        # step 2: can we read it?
        try:
            pubkey_path = self.key_path.with_suffix(self.key_path.suffix + ".pub")
            if pubkey_path.exists():
                pubkey_content = pubkey_path.read_text().strip()
            else:
                pubkey_content = None

            result = subprocess.run(
                ["ssh-keygen", "-l", "-f", str(self.key_path)],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return GapReport(
                    gap_type=GapType.UNREADABLE,
                    key_path=self.key_path,
                    remediation=(
                        f"key at {self.key_path} is unreadable or corrupt. "
                        f"regenerate: ssh-keygen -t ed25519 -f {self.key_path}"
                    ),
                    summary=f"ssh key unreadable: {self.key_path}",
                    errors=[result.stderr.strip()],
                )

            fingerprint = result.stdout.strip().split()[1] if result.stdout.strip() else None

        except (subprocess.TimeoutExpired, Exception) as e:
            return GapReport(
                gap_type=GapType.UNREADABLE,
                key_path=self.key_path,
                remediation=f"error reading key: {e}. regenerate if corrupt.",
                summary=f"ssh key read error: {self.key_path}",
                errors=[str(e)],
            )

        # step 3: probe github if requested
        if probe:
            probe_result = self._probe_github()
            probe_output = probe_result.get("stderr", "")

            if probe_result.get("exit_code") == 0:
                return GapReport(
                    gap_type=GapType.OK,
                    key_path=self.key_path,
                    fingerprint=fingerprint,
                    pubkey_content=pubkey_content,
                    remediation="push should work. if it doesn't, check network or repo access.",
                    summary=f"credential chain healthy. fingerprint: {fingerprint}",
                    probe_performed=True,
                    probe_output=probe_output,
                )

            # github rejected the key — determine mismatch vs unregistered vs revoked
            gap_type = self._classify_rejection(probe_output, fingerprint)
            return GapReport(
                gap_type=gap_type,
                key_path=self.key_path,
                fingerprint=fingerprint,
                pubkey_content=pubkey_content,
                remediation=self._remediation_registered(gap_type, pubkey_content),
                summary=self._summary_registered(gap_type, fingerprint),
                probe_performed=True,
                probe_output=probe_output,
                errors=[probe_output] if probe_output else [],
            )

        # no probe — report what we know locally
        return GapReport(
            gap_type=GapType.UNKNOWN,
            key_path=self.key_path,
            fingerprint=fingerprint,
            pubkey_content=pubkey_content,
            remediation=(
                f"key exists (fingerprint: {fingerprint}). "
                f"registration status unknown — run with probe=True or "
                f"`ssh -T git@github.com` to check."
            ),
            summary=f"key present, registration unverified: {fingerprint}",
        )

    def _probe_github(self) -> dict:
        """run ssh -T against github and return exit_code + stderr."""
        try:
            result = subprocess.run(
                ["ssh", "-i", str(self.key_path),
                 "-o", "StrictHostKeyChecking=no",
                 "-o", "BatchMode=yes",
                 "-o", "ConnectTimeout=10",
                 "-T", "git@github.com"],
                capture_output=True, text=True, timeout=15,
            )
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            }
        except subprocess.TimeoutExpired:
            return {"exit_code": -1, "stdout": "", "stderr": "ssh probe timed out (15s)"}
        except Exception as e:
            return {"exit_code": -1, "stdout": "", "stderr": str(e)}

    def _classify_rejection(self, probe_output: str, fingerprint: str | None) -> GapType:
        """classify a github rejection based on the probe output."""
        lower = probe_output.lower()
        if "permission denied" in lower:
            # cannot distinguish unregistered from revoked without history
            # default to unregistered (more common in this repo's experience)
            return GapType.UNREGISTERED
        if "could not resolve" in lower or "network" in lower:
            return GapType.UNKNOWN
        return GapType.UNKNOWN

    def _remediation_missing(self) -> str:
        return (
            f"ssh key missing at {self.key_path}. "
            f"generate: ssh-keygen -t ed25519 -f {self.key_path} -N '' && "
            f"then register the .pub file as a deploy key on github."
        )

    def _remediation_registered(self, gap_type: GapType, pubkey: str | None) -> str:
        if gap_type == GapType.UNREGISTERED:
            hint = ""
            if pubkey:
                hint = f" public key to register:\n{pubkey}"
            return (
                f"key exists locally but is not registered on github. "
                f"go to https://github.com/<owner>/<repo>/settings/keys, "
                f"click 'Add deploy key', paste the public key, enable write access."
                f"{hint}"
            )
        if gap_type == GapType.REVOKED:
            return (
                "key was previously registered but is now rejected. "
                "it may have been revoked. re-register or generate a new key."
            )
        return "github rejected the connection. check deploy key settings."

    def _summary_registered(self, gap_type: GapType, fingerprint: str | None) -> str:
        if gap_type == GapType.UNREGISTERED:
            return f"key {fingerprint} exists but not registered on github"
        if gap_type == GapType.REVOKED:
            return f"key {fingerprint} was revoked on github"
        return f"github rejected key {fingerprint}: {gap_type.value}"


if __name__ == "__main__":
    import sys
    import json

    do_probe = "--probe" in sys.argv
    monitor = CredentialGapMonitor()
    report = monitor.diagnose(probe=do_probe)

    if "--json" in sys.argv:
        from dataclasses import asdict
        print(json.dumps(asdict(report), indent=2, default=str))
    else:
        print(f"gap type:  {report.gap_type.value}")
        print(f"summary:   {report.summary}")
        print(f"fingerprint: {report.fingerprint or '(none)'}")
        if report.remediation:
            print(f"action:    {report.remediation}")
        if report.errors:
            print(f"errors:    {'; '.join(report.errors)}")
