"""Push readiness checker — diagnoses why the next push will fail before it does.

The deploy key goes missing, the known_hosts entry gets wiped on container
rebuild, the remote URL drifts. This module runs three cheap probes and
returns a structured verdict so the caretaker can tell the human exactly
what to fix instead of staring at a cryptic ssh error at 3am.

    from iamai.push_readiness import check_push_readiness
    report = check_push_readiness()
    print(report["verdict"])   # "ready" | "key_missing" | "host_unknown" | "remote_unreachable"
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class ProbeResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class ReadinessReport:
    verdict: str = ""  # "ready" | "key_missing" | "host_unknown" | "remote_unreachable" | "no_remote"
    probes: list = field(default_factory=list)
    remote_url: str = ""
    ssh_key_path: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, "", str(exc)


def probe_ssh_key(repo: Path) -> ProbeResult:
    """Check whether an SSH private key exists and is loadable."""
    # Try the workspace-level key first (the one the deploy_key_bootstrap wrote)
    candidates = [
        Path.home() / ".ssh" / "id_ed25519",
        Path.home() / ".ssh" / "id_rsa",
        Path(repo).parent / ".ssh" / "id_ed25519",
    ]

    # Also check SSH config for IdentityFile
    ssh_config = Path.home() / ".ssh" / "config"
    if ssh_config.exists():
        for line in ssh_config.read_text().splitlines():
            line = line.strip()
            if line.lower().startswith("identityfile"):
                path = line.split(None, 1)[1].strip()
                candidates.insert(0, Path(os.path.expanduser(path)))

    for candidate in candidates:
        if candidate.exists() and candidate.stat().st_size > 0:
            # Verify ssh-agent or key is parseable
            code, out, err = _run(["ssh-keygen", "-l", "-f", str(candidate)])
            if code == 0:
                return ProbeResult(
                    name="ssh_key",
                    ok=True,
                    detail=f"key found: {candidate} ({out})",
                )
    return ProbeResult(
        name="ssh_key",
        ok=False,
        detail="no loadable SSH private key found in standard locations or ssh config",
    )


def probe_host_key(remote_url: str) -> ProbeResult:
    """Check whether the remote host's key is in known_hosts."""
    # Extract host from git@host:owner/repo or ssh://git@host/...
    match = re.match(r"(?:ssh://)?(?:\w+@)?([^:/]+)", remote_url)
    if not match:
        return ProbeResult(name="host_key", ok=False, detail="cannot parse host from remote URL")

    host = match.group(1)
    known_hosts_paths = [
        Path.home() / ".ssh" / "known_hosts",
        Path("/root/userdata/workspace/.ssh/known_hosts"),
    ]

    for kh_path in known_hosts_paths:
        if not kh_path.exists():
            continue
        content = kh_path.read_text(errors="replace")
        # Check for host entry (first field before space)
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            entry_host = line.split()[0]
            if host == entry_host or entry_host.startswith(host):
                return ProbeResult(
                    name="host_key",
                    ok=True,
                    detail=f"host key for {host} found in {kh_path}",
                )

    # Try ssh-keyscan as a last resort (non-blocking, short timeout)
    code, out, _ = _run(["ssh-keyscan", "-T", "3", host], timeout=5)
    if code == 0 and out:
        return ProbeResult(
            name="host_key",
            ok=False,
            detail=f"host key for {host} not in known_hosts (but host is reachable via keyscan)",
        )

    return ProbeResult(
        name="host_key",
        ok=False,
        detail=f"host key for {host} not found in any known_hosts file",
    )


def probe_remote_reachable(remote_url: str) -> ProbeResult:
    """Try `git ls-remote` to verify the remote is reachable and we have access."""
    code, out, err = _run(["git", "ls-remote", "--exit-code", remote_url], timeout=15)
    if code == 0:
        refs = len(out.splitlines()) if out else 0
        return ProbeResult(
            name="remote_reachable",
            ok=True,
            detail=f"remote reachable, {refs} refs visible",
        )

    # Parse the error for a useful recommendation
    combined = f"{out}\n{err}".lower()
    if "permission denied" in combined:
        return ProbeResult(
            name="remote_reachable",
            ok=False,
            detail="SSH key not authorized — deploy key needs to be (re-)added to GitHub repo settings",
        )
    if "host key verification" in combined:
        return ProbeResult(
            name="remote_reachable",
            ok=False,
            detail="host key verification failed — run ssh-keyscan github.com >> ~/.ssh/known_hosts",
        )
    if "could not resolve" in combined or "name or service not known" in combined:
        return ProbeResult(
            name="remote_reachable",
            ok=False,
            detail="DNS resolution failed — check network connectivity",
        )
    return ProbeResult(
        name="remote_reachable",
        ok=False,
        detail=f"remote unreachable: {err[:200]}" if err else "remote unreachable (unknown reason)",
    )


def check_push_readiness(repo: Optional[Path] = None) -> dict:
    """Run all probes and return a structured readiness report."""
    repo = Path(repo) if repo else Path(__file__).resolve().parent.parent

    # Get remote URL
    code, remote_url, _ = _run(["git", "remote", "get-url", "origin"])
    if code != 0 or not remote_url:
        return ReadinessReport(
            verdict="no_remote",
            recommendation="configure a remote: git remote add origin git@github.com:OWNER/REPO.git",
        ).to_dict()

    report = ReadinessReport(remote_url=remote_url)

    # Probe 1: SSH key exists
    key_probe = probe_ssh_key(repo)
    report.probes.append(key_probe)
    if key_probe.ok:
        # Extract key path for the report
        report.ssh_key_path = key_probe.detail.split(":")[1].split("(")[0].strip() if ":" in key_probe.detail else ""

    # Probe 2: Host key is known
    host_probe = probe_host_key(remote_url)
    report.probes.append(host_probe)

    # Probe 3: Remote is reachable with our key
    reach_probe = probe_remote_reachable(remote_url)
    report.probes.append(reach_probe)

    # Determine verdict
    if all(p.ok for p in report.probes):
        report.verdict = "ready"
        report.recommendation = "all clear — next push should succeed"
    elif not key_probe.ok:
        report.verdict = "key_missing"
        report.recommendation = (
            "generate or restore the SSH deploy key, then add it to "
            "https://github.com/FengPwner/IamAI/settings/keys"
        )
    elif not host_probe.ok:
        report.verdict = "host_unknown"
        report.recommendation = "run: ssh-keyscan github.com >> ~/.ssh/known_hosts"
    else:
        report.verdict = "remote_unreachable"
        report.recommendation = reach_probe.detail

    return report.to_dict()


if __name__ == "__main__":
    import json
    print(json.dumps(check_push_readiness(), indent=2))
