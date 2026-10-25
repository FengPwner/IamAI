"""commit_audit.py — validate recent commit history for anomalies.

A self-writing repo accumulates hundreds of commits per day.  Most are
healthy, but patterns emerge that signal trouble:

  * **Message-format drift** — commits without a recognised prefix make
    the log harder to scan and may indicate a rogue script.
  * **Burst commits** — a single commit touching 50+ files often means a
    backlog flush rather than organic growth.
  * **Out-of-order timestamps** — rebase or force-push can leave the log
    with commits whose dates don't monotonically increase.
  * **Duplicate messages** — the same message appearing multiple times
    in a row usually means the caretaker re-ran a flush blindly.

This module scores each dimension 0.0–1.0 and combines them into a
single ``AuditReport``.  Caretakers can call ``audit()`` at the top of
each visit to decide whether deeper investigation is needed.

Usage::

    python3 -c "from iamai.commit_audit import audit; print(audit())"
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent

# Recognised commit-message prefixes.  Anything else is "unconventional".
KNOWN_PREFIXES = (
    "caretaker",
    "catch-up",
    "guoban",
    "backlog flush",
    "backlog",
    "flush",
    "manual",
    "initial",
    "merge",
    "revert",
    "chore",
    "feat",
    "fix",
    "docs",
    "test",
    "refactor",
)

# Thresholds
MAX_FILES_NORMAL = 30        # more than this in one commit → "burst"
BURST_SCORE_PENALTY = 0.3    # per burst commit, deducted from burst_score
DUPLICATE_PENALTY = 0.2      # per duplicate pair
FORMAT_PENALTY = 0.1         # per unconventional message
OOO_PENALTY = 0.4            # per out-of-order pair
DEFAULT_LOOKBACK = 50        # number of recent commits to audit


@dataclass
class AuditReport:
    """Snapshot of commit-history health."""

    format_score: float = 1.0
    burst_score: float = 1.0
    order_score: float = 1.0
    dedup_score: float = 1.0
    total_commits: int = 0
    format_violations: list[str] = field(default_factory=list)
    burst_commits: list[tuple[str, int]] = field(default_factory=list)
    ooo_pairs: list[tuple[str, str]] = field(default_factory=list)
    duplicate_groups: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        """Composite score in [0, 1].  Equal weighting across dimensions."""
        raw = (
            self.format_score
            + self.burst_score
            + self.order_score
            + self.dedup_score
        ) / 4.0
        return max(0.0, min(1.0, raw))

    @property
    def healthy(self) -> bool:
        return self.score >= 0.7

    @property
    def summary(self) -> str:
        parts = [f"score={self.score:.2f}"]
        if self.format_violations:
            parts.append(f"format×{len(self.format_violations)}")
        if self.burst_commits:
            parts.append(f"burst×{len(self.burst_commits)}")
        if self.ooo_pairs:
            parts.append(f"ooo×{len(self.ooo_pairs)}")
        if self.duplicate_groups:
            parts.append(f"dup×{len(self.duplicate_groups)}")
        return " ".join(parts)

    def __str__(self) -> str:
        status = "healthy" if self.healthy else "needs attention"
        return f"AuditReport({status}, {self.summary}, n={self.total_commits})"


def _clamp01(v: float) -> float:
    """Clamp to [0, 1]."""
    return max(0.0, min(1.0, v))


def _parse_log_line(line: str) -> tuple[str, str, str]:
    """Parse a ``git log --format='%H|%s|%aI'`` line into (sha, msg, date).

    The message itself may contain ``|`` characters, so we split on the
    *first* and *last* pipe to avoid ambiguity.
    """
    first_pipe = line.find("|")
    if first_pipe == -1:
        return ("", "", "")
    last_pipe = line.rfind("|")
    if last_pipe == first_pipe:
        return ("", "", "")
    sha = line[:first_pipe].strip()
    msg = line[first_pipe + 1 : last_pipe].strip()
    date = line[last_pipe + 1 :].strip()
    return sha, msg, date


def _has_known_prefix(message: str) -> bool:
    """Check whether a commit message starts with a recognised prefix."""
    lower = message.lower()
    for prefix in KNOWN_PREFIXES:
        if lower.startswith(prefix):
            return True
    return False


def _count_files_in_commit(sha: str, repo: Path) -> int:
    """Return the number of files changed in a single commit."""
    try:
        result = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha],
            capture_output=True,
            text=True,
            cwd=repo,
            timeout=5,
        )
        if result.returncode != 0:
            return 0
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        return len(lines)
    except (subprocess.TimeoutExpired, OSError):
        return 0


def _get_log(repo: Path, n: int) -> list[str]:
    """Fetch the last *n* commits from git log."""
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                f"-{n}",
                "--format=%H|%s|%aI",
            ],
            capture_output=True,
            text=True,
            cwd=repo,
            timeout=10,
        )
        if result.returncode != 0:
            return []
        return [l for l in result.stdout.strip().split("\n") if l.strip()]
    except (subprocess.TimeoutExpired, OSError):
        return []


def audit(
    repo: Optional[Path] = None,
    lookback: int = DEFAULT_LOOKBACK,
    check_files: bool = False,
) -> AuditReport:
    """Audit the recent commit history.

    Parameters
    ----------
    repo : Path, optional
        Repository root.  Defaults to this repo.
    lookback : int
        Number of recent commits to examine.
    check_files : bool
        If True, run ``git diff-tree`` per commit to count files.
        This is more expensive and usually unnecessary.

    Returns
    -------
    AuditReport
    """
    repo = repo or REPO
    report = AuditReport()

    raw_lines = _get_log(repo, lookback)
    if not raw_lines:
        report.total_commits = 0
        return report

    entries = [_parse_log_line(l) for l in raw_lines]
    entries = [(s, m, d) for s, m, d in entries if s]
    report.total_commits = len(entries)

    # --- Format check ---
    for sha, msg, date in entries:
        if msg and not _has_known_prefix(msg):
            report.format_violations.append(msg)
    report.format_score = _clamp01(
        1.0 - len(report.format_violations) * FORMAT_PENALTY
    )

    # --- Burst check ---
    if check_files:
        for sha, msg, date in entries:
            n_files = _count_files_in_commit(sha, repo)
            if n_files > MAX_FILES_NORMAL:
                report.burst_commits.append((msg, n_files))
        report.burst_score = _clamp01(
            1.0 - len(report.burst_commits) * BURST_SCORE_PENALTY
        )

    # --- Order check ---
    for i in range(len(entries) - 1):
        _, _, date_a = entries[i]
        _, _, date_b = entries[i + 1]
        if date_a and date_b and date_a < date_b:
            report.ooo_pairs.append((date_a, date_b))
    report.order_score = _clamp01(
        1.0 - len(report.ooo_pairs) * OOO_PENALTY
    )

    # --- Duplicate check ---
    seen_msgs: dict[str, int] = {}
    for _, msg, _ in entries:
        if msg:
            seen_msgs[msg] = seen_msgs.get(msg, 0) + 1
    for msg, count in seen_msgs.items():
        if count >= 2:
            report.duplicate_groups.append(msg)
    report.dedup_score = _clamp01(
        1.0 - len(report.duplicate_groups) * DUPLICATE_PENALTY
    )

    return report
