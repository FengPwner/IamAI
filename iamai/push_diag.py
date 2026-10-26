"""push_diag.py — quick push pipeline diagnostic for caretaker visits.

when push fails, the caretaker needs a fast answer to: "why can't we push,
and what do we do about it?" this module checks the entire push pipeline
in a single call and produces actionable output.

checks performed (in order):

  1. key file exists at the expected path
  2. key file has correct permissions (600)
  3. public key file exists (needed for registration)
  4. ssh connection to github succeeds
  5. unpushed commit count and total size

diagnosis states:

  HEALTHY    — push should work; if it doesn't, something else is wrong
  NO_KEY     — private key missing entirely
  BAD_PERMS  — key exists but permissions are too open
  UNREGISTERED — key exists but github doesn't recognise it
  NETWORK    — can't reach github at all

each state has a specific remediation. the module prints the exact
commands or steps needed, so the caretaker can act immediately.

usage:
    python3 -m iamai.push_diag              # human-readable report
    python3 -m iamai.push_diag --json       # machine-readable output
    python3 -m iamai.push_diag --fix-hint   # only show the fix command

design: this module is read-only. it never modifies keys, git config,
or remote state. it observes and recommends.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


REPO = Path(__file__).resolve().parent.parent
DEFAULT_KEY_PATH = Path.home() / ".ssh" / "id_ed25519"
WORKSPACE_KEY = Path("/root/userdata/workspace/.ssh/id_ed25519")


class PushState(str, Enum):
    HEALTHY = "HEALTHY"
    NO_KEY = "NO_KEY"
    BAD_PERMS = "BAD_PERMS"
    NO_PUBKEY = "NO_PUBKEY"
    UNREGISTERED = "UNREGISTERED"
    NETWORK = "NETWORK"
    UNKNOWN = "UNKNOWN"


@dataclass
class PushDiagnosis:
    """complete push pipeline diagnostic."""
    timestamp: str
    state: str
    key_path: str
    key_exists: bool
    key_permissions: str
    pubkey_exists: bool
    pubkey_fingerprint: str
    ssh_test_passed: bool
    ssh_test_error: str
    unpushed_count: int
    unpushed_oldest_hours: float
    fix_hint: str
    workspace_key_exists: bool = False
    workspace_key_matches: bool = False


def _run(*args: str, timeout: int = 10) -> tuple[int, str, str]:
    """run a command, return (exit_code, stdout, stderr)."""
    try:
        r = subprocess.run(
            list(args), capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def _check_key_file(path: Path) -> tuple[bool, str]:
    """check if key file exists and its permissions."""
    if not path.exists():
        return False, ""
    mode = oct(path.stat().st_mode & 0o777)
    return True, mode


def _get_fingerprint(pub_path: Path) -> str:
    """get ssh key fingerprint from public key file."""
    if not pub_path.exists():
        return ""
    code, out, _ = _run("ssh-keygen", "-lf", str(pub_path))
    if code != 0:
        return ""
    # output: "256 SHA256:xxx comment (TYPE)"
    parts = out.split()
    return parts[1] if len(parts) >= 2 else out


def _test_ssh(key_path: Path) -> tuple[bool, str]:
    """test ssh connection to github."""
    code, out, err = _run(
        "ssh", "-i", str(key_path),
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=8",
        "-T", "git@github.com",
        timeout=15,
    )
    # github returns exit 1 on success with "Hi user! You've successfully..."
    # but also returns 1 on auth failure. we check the message.
    combined = (out + " " + err).lower()
    if "successfully authenticated" in combined:
        return True, ""
    if "permission denied" in combined:
        return False, "Permission denied (publickey)"
    if "could not resolve" in combined or "network" in combined:
        return False, "Network error"
    if "timeout" in combined:
        return False, "Connection timeout"
    if "no such file" in combined:
        return False, "Key file not found"
    return False, err or out or "Unknown error"


def _get_unpushed_count() -> int:
    """count unpushed commits."""
    code, out, _ = _run(
        "git", "-C", str(REPO), "log", "--format=%H",
        "origin/main..HEAD"
    )
    if code != 0 or not out:
        return 0
    return len([h for h in out.split("\n") if h.strip()])


def _get_unpushed_oldest_hours() -> float:
    """get age in hours of the oldest unpushed commit."""
    code, out, _ = _run(
        "git", "-C", str(REPO), "log", "--format=%aI",
        "--reverse", "origin/main..HEAD"
    )
    if code != 0 or not out:
        return 0.0
    lines = [l.strip() for l in out.split("\n") if l.strip()]
    if not lines:
        return 0.0
    try:
        oldest = datetime.fromisoformat(lines[0])
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return round((now - oldest).total_seconds() / 3600.0, 2)
    except (ValueError, TypeError):
        return 0.0


def _keys_match(path_a: Path, path_b: Path) -> bool:
    """check if two private key files have the same content."""
    if not path_a.exists() or not path_b.exists():
        return False
    try:
        return path_a.read_bytes() == path_b.read_bytes()
    except (OSError, PermissionError):
        return False


def generate_fix_hint(state: PushState, diagnosis: PushDiagnosis) -> str:
    """generate actionable fix instructions based on diagnosis state."""
    if state == PushState.HEALTHY:
        return (
            "push pipeline is healthy. if push still fails, check:\n"
            "  git push origin main\n"
            "  # if this fails, the issue may be a diverged remote"
        )

    if state == PushState.NO_KEY:
        hints = ["private key missing. recovery options:"]
        if diagnosis.workspace_key_exists:
            hints.append(
                f"  # workspace key found at {WORKSPACE_KEY}\n"
                f"  cp {WORKSPACE_KEY} {DEFAULT_KEY_PATH}\n"
                f"  chmod 600 {DEFAULT_KEY_PATH}\n"
                f"  # then register the public key on github"
            )
        else:
            hints.append(
                "  # no key found anywhere. generate a new one:\n"
                f"  ssh-keygen -t ed25519 -f {DEFAULT_KEY_PATH} -N ''\n"
                f"  # then register the public key on github"
            )
        hints.append(
            "  # register at: https://github.com/FengPwner/IamAI/settings/keys"
        )
        return "\n".join(hints)

    if state == PushState.BAD_PERMS:
        return (
            f"key permissions too open. fix:\n"
            f"  chmod 600 {DEFAULT_KEY_PATH}\n"
            f"  # then retry: git push origin main"
        )

    if state == PushState.NO_PUBKEY:
        return (
            f"public key file missing. regenerate from private key:\n"
            f"  ssh-keygen -y -f {DEFAULT_KEY_PATH} > {DEFAULT_KEY_PATH}.pub\n"
            f"  # then register the pubkey on github"
        )

    if state == PushState.UNREGISTERED:
        return (
            f"key exists but is not registered on github.\n"
            f"  cat {DEFAULT_KEY_PATH}.pub\n"
            f"  # copy the output, then:\n"
            f"  # https://github.com/FengPwner/IamAI/settings/keys\n"
            f"  # Add deploy key → paste → enable write access\n"
            f"  # then: git push origin main"
        )

    if state == PushState.NETWORK:
        return (
            "cannot reach github. check network:\n"
            "  ping github.com\n"
            "  curl -I https://github.com\n"
            "  # if network is fine, the issue is dns or firewall"
        )

    return "unknown state — run manual diagnostics."


def diagnose(
    key_path: Optional[Path] = None,
    remote: str = "origin",
) -> PushDiagnosis:
    """run full push pipeline diagnostic."""
    now = datetime.now(timezone.utc).isoformat()
    kp = key_path or DEFAULT_KEY_PATH

    # check key file
    key_exists, perms = _check_key_file(kp)
    pubkey_path = kp.with_suffix(kp.suffix + ".pub") if kp.suffix else Path(str(kp) + ".pub")
    # handle id_ed25519 -> id_ed25519.pub naming
    if not kp.suffix:
        pubkey_path = Path(str(kp) + ".pub")
    else:
        pubkey_path = Path(str(kp).replace(kp.suffix, "") + ".pub")
    # simplest: just append .pub
    pubkey_path = Path(str(kp) + ".pub")

    pubkey_exists = pubkey_path.exists()
    fingerprint = _get_fingerprint(pubkey_path) if pubkey_exists else ""

    # check workspace key
    ws_key_exists = WORKSPACE_KEY.exists()
    ws_matches = _keys_match(kp, WORKSPACE_KEY) if ws_key_exists and key_exists else False

    # check permissions
    bad_perms = False
    if key_exists and perms:
        mode_int = int(perms, 8)
        bad_perms = mode_int > 0o600

    # ssh test
    ssh_ok, ssh_err = (False, "key missing")
    if key_exists and not bad_perms:
        ssh_ok, ssh_err = _test_ssh(kp)

    # unpushed stats
    unpushed = _get_unpushed_count()
    oldest = _get_unpushed_oldest_hours()

    # determine state
    if not key_exists:
        state = PushState.NO_KEY
    elif bad_perms:
        state = PushState.BAD_PERMS
    elif not pubkey_exists:
        state = PushState.NO_PUBKEY
    elif ssh_ok:
        state = PushState.HEALTHY
    elif "network" in ssh_err.lower() or "timeout" in ssh_err.lower():
        state = PushState.NETWORK
    elif "permission denied" in ssh_err.lower():
        state = PushState.UNREGISTERED
    else:
        state = PushState.UNKNOWN

    diag = PushDiagnosis(
        timestamp=now,
        state=state.value,
        key_path=str(kp),
        key_exists=key_exists,
        key_permissions=perms,
        pubkey_exists=pubkey_exists,
        pubkey_fingerprint=fingerprint,
        ssh_test_passed=ssh_ok,
        ssh_test_error=ssh_err,
        unpushed_count=unpushed,
        unpushed_oldest_hours=oldest,
        fix_hint="",  # filled below
        workspace_key_exists=ws_key_exists,
        workspace_key_matches=ws_matches,
    )
    diag.fix_hint = generate_fix_hint(state, diag)

    return diag


def format_report(d: PushDiagnosis) -> str:
    """format diagnosis as human-readable report."""
    state_icons = {
        "HEALTHY": "[OK]",
        "NO_KEY": "[!!]",
        "BAD_PERMS": "[!!]",
        "NO_PUBKEY": "[!!]",
        "UNREGISTERED": "[!!]",
        "NETWORK": "[!!]",
        "UNKNOWN": "[??]",
    }
    icon = state_icons.get(d.state, "[??]")

    lines = [
        f"=== Push Diagnostic ({d.timestamp}) ===",
        f"",
        f"  state:        {icon} {d.state}",
        f"  key path:     {d.key_path}",
        f"  key exists:   {d.key_exists}"
        + (f" (perms: {d.key_permissions})" if d.key_permissions else ""),
        f"  pubkey:       {d.pubkey_exists}"
        + (f" (fp: {d.pubkey_fingerprint})" if d.pubkey_fingerprint else ""),
    ]

    if d.workspace_key_exists:
        match_note = "MATCHES" if d.workspace_key_matches else "DIFFERS"
        lines.append(f"  workspace key: exists ({match_note})")

    lines.extend([
        f"  ssh test:     {'PASS' if d.ssh_test_passed else 'FAIL'}"
        + (f" — {d.ssh_test_error}" if d.ssh_test_error else ""),
        f"  unpushed:     {d.unpushed_count} commits"
        + (f" (oldest: {d.unpushed_oldest_hours:.1f}h)"
           if d.unpushed_oldest_hours > 0 else ""),
        f"",
        f"--- fix ---",
        d.fix_hint,
    ])

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="push pipeline diagnostic")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--fix-hint", action="store_true",
                        help="only print fix instructions")
    parser.add_argument("--key-path", type=str, default=None,
                        help="path to private key")
    args = parser.parse_args()

    kp = Path(args.key_path) if args.key_path else None
    diag = diagnose(key_path=kp)

    if args.fix_hint:
        print(diag.fix_hint)
    elif args.json:
        print(json.dumps(asdict(diag), indent=2))
    else:
        print(format_report(diag))

    return 0 if diag.state == PushState.HEALTHY.value else 1


if __name__ == "__main__":
    sys.exit(main())
