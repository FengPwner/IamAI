"""push_conflict_anatomy — classify git push rejections and recommend fixes.

When a ``git push`` fails the output contains a reason. This module
parses that reason, classifies it into one of several well-known
conflict types, and returns a structured recommendation for how to
resolve it without losing work.

Supported rejection types
--------------------------

===================  ===================================================
type                 meaning
===================  ===================================================
non_fast_forward     remote has commits you don't have locally
reject_merge_commit  push includes merge commits on a linear-only branch
hook_declined        server-side hook (pre-receive, update) rejected push
permission_denied    deploy key / token lacks write access
branch_protected     branch protection rules prevent direct push
unknown              could not classify the rejection
===================  ===================================================

Public API::

    from iamai.push_conflict_anatomy import (
        PushRejection, classify_push_failure, recommend_resolution,
    )

    rej = classify_push_failure(push_stderr)
    # PushRejection(type='non_fast_forward', files=[...], message='...')

    rec = recommend_resolution(rej)
    # {"strategy": "rebase", "steps": ["git pull --rebase origin main",
    #   "git push origin main"], "risk": "low"}

Resolution strategies
---------------------

- **rebase** — pull with ``--rebase``, then push. Lowest disruption.
- **merge** — pull with merge, resolve conflicts, push. Preserves
  parallel history.
- **force_with_lease** — when local history was rewritten intentionally
  and remote hasn't moved since last fetch.
- **credential_refresh** — regenerate deploy key or token.
- **branch_policy** — open a PR instead of pushing directly.

Why this matters
----------------

A caretaker that encounters a push failure and just retries blindly
will loop forever. Classifying the failure on the first attempt lets
the caretaker pick the right fix immediately — rebase when the remote
moved, refresh credentials when the key expired, open a PR when the
branch is protected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class PushRejection:
    """Structured representation of a git push failure."""

    type: str  # one of the types in the table above
    message: str = ""
    files: List[str] = field(default_factory=list)
    remote_branch: Optional[str] = None
    raw_stderr: str = ""

    def is_resolvable(self) -> bool:
        """Can the caretaker fix this without human intervention?"""
        return self.type in {
            "non_fast_forward",
            "reject_merge_commit",
        }

    def requires_human(self) -> bool:
        """Definitely needs a human (permission, policy)."""
        return self.type in {
            "permission_denied",
            "branch_protected",
        }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_PATTERNS = [
    (
        "non_fast_forward",
        re.compile(
            r"rejected.*fetch first|non-fast-forward|Updates were rejected",
            re.IGNORECASE,
        ),
    ),
    (
        "reject_merge_commit",
        re.compile(
            r"merge commit|refusing to merge|contains merge commit",
            re.IGNORECASE,
        ),
    ),
    (
        "hook_declined",
        re.compile(
            r"pre-receive hook declined|update hook declined|"
            r"remote: error: hook|push declined",
            re.IGNORECASE,
        ),
    ),
    (
        "permission_denied",
        re.compile(
            r"permission denied|deploy key|fatal: could not read|"
            r"authentication failed|ERROR: Permission",
            re.IGNORECASE,
        ),
    ),
    (
        "branch_protected",
        re.compile(
            r"branch protection|protected branch|"
            r"required status check|rulesets? prevent",
            re.IGNORECASE,
        ),
    ),
]


def classify_push_failure(stderr: str) -> PushRejection:
    """Parse git push stderr and return a classified PushRejection.

    Parameters
    ----------
    stderr : str
        The complete stderr output from ``git push``.

    Returns
    -------
    PushRejection
        Classified rejection. ``type`` is ``"unknown"`` when no
        pattern matched.
    """
    if not stderr:
        return PushRejection(type="unknown", raw_stderr="")

    for rej_type, pattern in _PATTERNS:
        if pattern.search(stderr):
            files = _extract_conflicting_files(stderr)
            branch = _extract_remote_branch(stderr)
            return PushRejection(
                type=rej_type,
                message=_first_meaningful_line(stderr),
                files=files,
                remote_branch=branch,
                raw_stderr=stderr,
            )

    return PushRejection(
        type="unknown",
        message=_first_meaningful_line(stderr),
        raw_stderr=stderr,
    )


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

_STRATEGIES = {
    "non_fast_forward": {
        "strategy": "rebase",
        "steps": [
            "git stash push -u -m 'caretaker-autostash'",
            "git pull --rebase origin {branch}",
            "git stash pop",
            "git push origin {branch}",
        ],
        "risk": "low",
        "auto_safe": True,
    },
    "reject_merge_commit": {
        "strategy": "rebase",
        "steps": [
            "git rebase -i HEAD~{n}  # drop or squash merge commits",
            "git push origin {branch}",
        ],
        "risk": "medium",
        "auto_safe": False,
    },
    "hook_declined": {
        "strategy": "investigate",
        "steps": [
            "# read the hook output in raw_stderr",
            "# fix whatever the hook complained about",
            "git push origin {branch}",
        ],
        "risk": "medium",
        "auto_safe": False,
    },
    "permission_denied": {
        "strategy": "credential_refresh",
        "steps": [
            "# regenerate deploy key or token",
            "# update GIT_SSH_COMMAND or git credential helper",
            "git push origin {branch}",
        ],
        "risk": "high",
        "auto_safe": False,
    },
    "branch_protected": {
        "strategy": "branch_policy",
        "steps": [
            "git checkout -b fix/push-conflict-{ts}",
            "git push origin fix/push-conflict-{ts}",
            "# open pull request via GitHub API or web UI",
        ],
        "risk": "low",
        "auto_safe": True,
    },
}

_DEFAULT_STRATEGY = {
    "strategy": "manual",
    "steps": [
        "# unclassified failure — inspect raw_stderr",
        "git fetch origin",
        "git log --oneline --graph HEAD origin/{branch}",
    ],
    "risk": "unknown",
    "auto_safe": False,
}


def recommend_resolution(
    rejection: PushRejection,
    branch: str = "main",
) -> dict:
    """Return a resolution plan for the given PushRejection.

    Parameters
    ----------
    rejection : PushRejection
        Output of :func:`classify_push_failure`.
    branch : str
        Target branch name (default ``"main"``).

    Returns
    -------
    dict
        Keys: ``strategy``, ``steps`` (list of shell commands),
        ``risk`` (``"low"`` / ``"medium"`` / ``"high"`` / ``"unknown"``),
        ``auto_safe`` (bool — can the caretaker run this unattended?).
    """
    template = _STRATEGIES.get(rejection.type, _DEFAULT_STRATEGY)
    steps = [
        s.format(branch=branch, ts="caretaker", n="5")
        for s in template["steps"]
    ]
    return {
        "strategy": template["strategy"],
        "steps": steps,
        "risk": template["risk"],
        "auto_safe": template["auto_safe"],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FILE_RE = re.compile(r"!\s+\[rejected\].*->\s*(\S+)")
_BRANCH_RE = re.compile(r"(\S+)\s+->\s+(\S+)")
_CONFLICT_FILE_RE = re.compile(
    r"(?:CONFLICT(?:\s*\([^)]*\))?\s*:\s*|error:\s*(?:merge conflict in ))"
    r"(\S+\.\S+)",
    re.IGNORECASE,
)


def _extract_conflicting_files(stderr: str) -> List[str]:
    """Pull filenames from conflict lines in push output."""
    return list(dict.fromkeys(_CONFLICT_FILE_RE.findall(stderr)))


def _extract_remote_branch(stderr: str) -> Optional[str]:
    """Best-effort extraction of the remote branch name."""
    for line in stderr.splitlines():
        m = _BRANCH_RE.search(line)
        if m:
            return m.group(2).strip()
    return None


def _first_meaningful_line(stderr: str) -> str:
    """Return the first non-empty, non-hint line from push output."""
    for line in stderr.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("hint:"):
            return stripped
    return ""


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def diagnose_push(stderr: str, branch: str = "main") -> dict:
    """One-call convenience wrapper: classify + recommend.

    Returns a dict with keys ``rejection`` and ``resolution``.
    """
    rej = classify_push_failure(stderr)
    rec = recommend_resolution(rej, branch=branch)
    return {"rejection": rej, "resolution": rec}
