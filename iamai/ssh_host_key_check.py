"""SSH host-key preflight — verify the remote's host key is trusted before pushing.

The symptom that motivated this module: the batch committer finishes a clean
commit, calls ``git push``, and gets::

    Host key verification failed.
    fatal: Could not read from remote repository.

The deploy key was fine; the *host* key for github.com was simply absent from
``~/.ssh/known_hosts``.  On ephemeral cloud workspaces, ``known_hosts`` starts
empty every boot, so the first push after a restart will always fail unless
something primes it.

This module provides:

* ``is_host_key_present(host)`` — cheap check, no network beyond a keyscan
* ``ensure_host_key(host)``     — idempotent: scan once, append if missing

The design is deliberately narrow.  We do *not* manage deploy-key permissions
here (that is ``ssh_key_rescue``'s job).  We only answer: "will SSH trust this
host, or will it hang asking a question nobody is around to answer?"
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

DEFAULT_HOST = "github.com"
KNOWN_HOSTS = Path.home() / ".ssh" / "known_hosts"


def _known_hosts_lines() -> list[str]:
    if not KNOWN_HOSTS.exists():
        return []
    return KNOWN_HOSTS.read_text(errors="replace").splitlines()


def is_host_key_present(host: str = DEFAULT_HOST) -> bool:
    """Return True if *host* appears in the user's known_hosts file.

    A line in known_hosts looks like ``github.com ssh-ed25519 AAAA...`` or
    ``|1|<hash>|<hash> ssh-ed25519 AAAA...`` (hashed).  We accept either form:
    an unhashed entry that starts with the hostname, or any entry at all when
    the file is non-empty and ssh-keygen confirms it.
    """
    for line in _known_hosts_lines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # unhashed entry: first token is hostname(s)
        first = stripped.split()[0]
        if host in first.split(","):
            return True
    # fall back to ssh-keygen -F which handles hashed entries
    try:
        proc = subprocess.run(
            ["ssh-keygen", "-F", host],
            capture_output=True, text=True, timeout=10,
        )
        return proc.returncode == 0 and proc.stdout.strip() != ""
    except (OSError, subprocess.SubprocessError):
        return False


def ensure_host_key(host: str = DEFAULT_HOST) -> bool:
    """Make sure *host*'s key is in known_hosts.  Idempotent.

    Returns True if the key is now present (whether we added it or it was
    already there).  Returns False only if ssh-keyscan itself failed —
    typically a network outage or the host being unreachable.
    """
    if is_host_key_present(host):
        return True

    # ssh-keyscan is read-only: it fetches the public host key, nothing more.
    try:
        proc = subprocess.run(
            ["ssh-keyscan", "-t", "ed25519,rsa", host],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    if proc.returncode != 0 or not proc.stdout.strip():
        return False

    KNOWN_HOSTS.parent.mkdir(parents=True, exist_ok=True)
    with KNOWN_HOSTS.open("a") as fh:
        fh.write(proc.stdout)
    return is_host_key_present(host)
