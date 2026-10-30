"""repo_immune_system — detect pathogens and score immune defence.

A living repository is constantly under attack from subtle pathogens:
stale lock files left by crashed processes, zombie PIDs that point to
nothing, orphaned state files with no consumer, duplicated indices, and
corrupt metadata.  Left unchecked, these accumulate into autoimmune
disorders where the repo's own machinery trips over itself.

The immune-system metaphor
--------------------------

=========================  ===================================================
concept                    what it maps to
=========================  ===================================================
**pathogen**               a concrete failure artifact (stale lock, zombie
                           PID, orphan state, duplicate index, corrupt JSON)
**antibody**               an automated cleaner or guard that neutralises
                           a specific pathogen class
**infection**              a pathogen present *without* a paired antibody
**immunity**               a pathogen present *with* a paired antibody that
                           can handle it
**inflammation**           active infections (antibody missing or failing)
**immune memory**          log of past infections that led to new antibodies
                           being added
=========================  ===================================================

Pathogen classes
----------------

========================  =====================================================
class                     detection heuristic
========================  =====================================================
``stale_lock``            ``.lock`` / ``.pid`` file older than ``max_lock_age``
                          seconds or referencing a dead PID
``zombie_pid``            PID file whose process no longer exists
``orphan_state``          ``data/*.json`` with no module importing it
``duplicate_index``       two files mapping to the same logical key
``corrupt_json``          ``*.json`` / ``*.jsonl`` that fails ``json.loads``
``dangling_symlink``      symlink target does not exist
========================  =====================================================

Antibody registry
-----------------

Each antibody declares:

- **target**: the pathogen class it neutralises
- **mechanism**: short description of how it works
- **coverage**: fraction of pathogens in that class it handles (0.0–1.0)

Metrics
-------

============================  ================================================
metric                        description
============================  ================================================
``pathogens_found``           total distinct pathogen instances detected
``antibodies_active``         number of antibody classes registered
``infections``                pathogens without a covering antibody
``immunity_score``            0–100; higher = better coverage
``state``                     one of: immune, vulnerable, inflamed,
                              immunocompromised, septic
============================  ================================================

Edge cases
----------

- Empty repo (no files at all): returns ``state='dormant'`` with zero scores.
- Lock files from the *current* running process are excluded from stale
  detection via PID liveness check.
- Corrupt JSON in ``node_modules/`` or ``.git/`` is ignored.

Usage::

    from iamai.repo_immune_system import immune_report, immune_summary

    r = immune_report(repo_path=".")
    print(r.immunity_score)   # e.g. 85.0
    print(r.state)            # "immune"
    print(r.infections)       # []
    print(immune_summary(r))
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Pathogen types
# ---------------------------------------------------------------------------

PATHOGEN_CLASSES = (
    "stale_lock",
    "zombie_pid",
    "orphan_state",
    "duplicate_index",
    "corrupt_json",
    "dangling_symlink",
)


@dataclass(frozen=True)
class Pathogen:
    """A single detected pathogen artifact."""

    kind: str          # one of PATHOGEN_CLASSES
    path: str          # file path relative to repo root
    detail: str = ""   # human-readable extra info


# ---------------------------------------------------------------------------
# Antibody registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Antibody:
    """An automated defence against a pathogen class."""

    target: str         # pathogen class name
    tool: str           # module or script that provides the defence
    mechanism: str      # short description
    coverage: float = 1.0  # 0.0–1.0


_DEFAULT_ANTIBODIES: Tuple[Antibody, ...] = (
    Antibody(
        target="stale_lock",
        tool="lock_clearance",
        mechanism="detects and removes stale .lock/.pid files",
        coverage=0.95,
    ),
    Antibody(
        target="zombie_pid",
        tool="stale_pid_detector",
        mechanism="validates PID liveness and cleans dead references",
        coverage=0.90,
    ),
    Antibody(
        target="orphan_state",
        tool="session_memory",
        mechanism="tracks state-file consumers and flags orphans",
        coverage=0.70,
    ),
    Antibody(
        target="duplicate_index",
        tool="note_index",
        mechanism="deduplicates index entries on write",
        coverage=0.85,
    ),
    Antibody(
        target="corrupt_json",
        tool="stroke_checksum",
        mechanism="validates JSON integrity on commit",
        coverage=0.80,
    ),
    Antibody(
        target="dangling_symlink",
        tool="index_guard",
        mechanism="verifies symlink targets exist before indexing",
        coverage=0.75,
    ),
)

# Directories to skip when scanning for pathogens.
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".github"}


# ---------------------------------------------------------------------------
# Pathogen detectors
# ---------------------------------------------------------------------------

def _is_pid_alive(pid: int) -> bool:
    """Check whether a process with the given PID exists."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _detect_stale_locks(repo_path: str, max_age_s: int = 3600) -> List[Pathogen]:
    """Find lock/PID files that are stale or reference dead processes."""
    pathogens: List[Pathogen] = []
    root = Path(repo_path)
    for pat in ("**/*.lock", "**/*.pid"):
        for fp in root.glob(pat):
            # Skip ignored directories.
            if _SKIP_DIRS & set(fp.parts):
                continue
            rel = str(fp.relative_to(root))
            try:
                content = fp.read_text().strip()
            except (OSError, PermissionError):
                continue

            # If the file contains a PID, check liveness.
            if content.isdigit():
                pid = int(content)
                if not _is_pid_alive(pid):
                    pathogens.append(Pathogen(
                        kind="zombie_pid",
                        path=rel,
                        detail=f"PID {pid} not alive",
                    ))
                continue

            # Otherwise check age.
            try:
                age = _file_age(fp)
                if age > max_age_s:
                    pathogens.append(Pathogen(
                        kind="stale_lock",
                        path=rel,
                        detail=f"age {age}s > max {max_age_s}s",
                    ))
            except OSError:
                continue
    return pathogens


def _file_age(fp: Path) -> int:
    """Return seconds since file was last modified."""
    import time
    mtime = fp.stat().st_mtime
    return int(time.time() - mtime)


def _detect_orphan_state(repo_path: str) -> List[Pathogen]:
    """Find JSON state files in data/ not referenced by any Python module."""
    pathogens: List[Pathogen] = []
    root = Path(repo_path)
    data_dir = root / "data"
    if not data_dir.is_dir():
        return pathogens

    # Collect all Python source files.
    py_files: List[Path] = []
    for ext in ("*.py",):
        py_files.extend(root.rglob(ext))

    # Build a simple "mentions" index.
    all_source = ""
    for pf in py_files:
        if _SKIP_DIRS & set(pf.parts):
            continue
        try:
            all_source += pf.read_text(errors="ignore") + "\n"
        except (OSError, PermissionError):
            continue

    for jf in data_dir.glob("*.json"):
        name = jf.stem  # e.g. "writer_state"
        if name not in all_source:
            pathogens.append(Pathogen(
                kind="orphan_state",
                path=str(jf.relative_to(root)),
                detail=f"'{name}' not referenced in any .py file",
            ))
    return pathogens


def _detect_duplicate_index(repo_path: str) -> List[Pathogen]:
    """Detect duplicate logical keys in index files."""
    pathogens: List[Pathogen] = []
    root = Path(repo_path)

    # Look for index-style files (data/*.jsonl with key-value structure).
    for jf in root.glob("data/*.jsonl"):
        if _SKIP_DIRS & set(jf.parts):
            continue
        try:
            lines = jf.read_text().strip().splitlines()
        except (OSError, PermissionError):
            continue

        keys_seen: Dict[str, int] = {}
        for i, line in enumerate(lines):
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            # Use 'id' or 'key' or first string field as logical key.
            key = obj.get("id") or obj.get("key") or obj.get("name")
            if key is not None:
                key_str = str(key)
                if key_str in keys_seen:
                    pathogens.append(Pathogen(
                        kind="duplicate_index",
                        path=str(jf.relative_to(root)),
                        detail=f"key '{key_str}' at lines {keys_seen[key_str]} and {i+1}",
                    ))
                else:
                    keys_seen[key_str] = i + 1
    return pathogens


def _detect_corrupt_json(repo_path: str) -> List[Pathogen]:
    """Find JSON/JSONL files that fail to parse."""
    pathogens: List[Pathogen] = []
    root = Path(repo_path)

    for pattern in ("**/*.json", "**/*.jsonl"):
        for fp in root.glob(pattern):
            if _SKIP_DIRS & set(fp.parts):
                continue
            rel = str(fp.relative_to(root))
            try:
                content = fp.read_text()
            except (OSError, PermissionError):
                continue

            if not content.strip():
                continue

            if fp.suffix == ".jsonl":
                for i, line in enumerate(content.strip().splitlines(), 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        pathogens.append(Pathogen(
                            kind="corrupt_json",
                            path=rel,
                            detail=f"line {i} invalid JSON",
                        ))
                        break  # one per file is enough
            else:
                try:
                    json.loads(content)
                except (json.JSONDecodeError, ValueError):
                    pathogens.append(Pathogen(
                        kind="corrupt_json",
                        path=rel,
                        detail="entire file fails to parse",
                    ))
    return pathogens


def _detect_dangling_symlinks(repo_path: str) -> List[Pathogen]:
    """Find symlinks whose targets do not exist."""
    pathogens: List[Pathogen] = []
    root = Path(repo_path)
    for fp in root.rglob("*"):
        if _SKIP_DIRS & set(fp.parts):
            continue
        if fp.is_symlink() and not fp.exists():
            pathogens.append(Pathogen(
                kind="dangling_symlink",
                path=str(fp.relative_to(root)),
                detail=f"target '{os.readlink(fp)}' missing",
            ))
    return pathogens


def detect_pathogens(
    repo_path: str = ".",
    max_lock_age_s: int = 3600,
) -> List[Pathogen]:
    """Run all pathogen detectors and return combined results."""
    found: List[Pathogen] = []
    found.extend(_detect_stale_locks(repo_path, max_lock_age_s))
    found.extend(_detect_orphan_state(repo_path))
    found.extend(_detect_duplicate_index(repo_path))
    found.extend(_detect_corrupt_json(repo_path))
    found.extend(_detect_dangling_symlinks(repo_path))
    return found


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _coverage_for_class(
    kind: str,
    antibodies: Tuple[Antibody, ...] = _DEFAULT_ANTIBODIES,
) -> float:
    """Return the best antibody coverage for a pathogen class."""
    best = 0.0
    for ab in antibodies:
        if ab.target == kind:
            best = max(best, ab.coverage)
    return best


def _classify_infections(
    pathogens: List[Pathogen],
    antibodies: Tuple[Antibody, ...] = _DEFAULT_ANTIBODIES,
) -> List[Pathogen]:
    """Return pathogens with no effective antibody (coverage < 0.5)."""
    infections = []
    for p in pathogens:
        cov = _coverage_for_class(p.kind, antibodies)
        if cov < 0.5:
            infections.append(p)
    return infections


def _compute_immunity_score(
    pathogens: List[Pathogen],
    antibodies: Tuple[Antibody, ...] = _DEFAULT_ANTIBODIES,
) -> float:
    """0–100 score based on pathogen count and antibody coverage.

    Scoring formula:
    - Start at 100.
    - For each pathogen: deduct ``10 * (1 - best_coverage)`` points.
    - For each infection (no antibody): deduct additional 5 points.
    - Floor at 0.
    """
    if not pathogens:
        return 100.0
    score = 100.0
    for p in pathogens:
        cov = _coverage_for_class(p.kind, antibodies)
        score -= 10.0 * (1.0 - cov)
        if cov < 0.5:
            score -= 5.0
    return round(max(0.0, score), 1)


def _classify_state(
    score: float,
    infections: List[Pathogen],
    total_pathogens: int,
) -> str:
    """Classify overall immune state."""
    if total_pathogens == 0:
        return "immune"
    if score >= 85:
        return "immune"
    if score >= 65:
        if not infections:
            return "vulnerable"
        return "inflamed"
    if score >= 40:
        return "immunocompromised"
    return "septic"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class ImmuneReport:
    """Complete immune system health report."""

    pathogens: List[Pathogen] = field(default_factory=list)
    antibodies_active: int = 0
    infections: List[Pathogen] = field(default_factory=list)
    immunity_score: float = 100.0
    state: str = "immune"
    pathogens_by_class: Dict[str, int] = field(default_factory=dict)


def immune_report(
    repo_path: str = ".",
    max_lock_age_s: int = 3600,
    antibodies: Optional[Tuple[Antibody, ...]] = None,
) -> ImmuneReport:
    """Scan the repository for pathogens and score immune defence.

    Parameters
    ----------
    repo_path:
        Path to the git repository root.
    max_lock_age_s:
        Seconds after which a lock file is considered stale.
    antibodies:
        Custom antibody registry.  Defaults to ``_DEFAULT_ANTIBODIES``.

    Returns
    -------
    ImmuneReport with all metrics populated.
    """
    abs_reg = antibodies or _DEFAULT_ANTIBODIES
    pathogens = detect_pathogens(repo_path, max_lock_age_s)

    # Count by class.
    by_class: Dict[str, int] = {}
    for p in pathogens:
        by_class[p.kind] = by_class.get(p.kind, 0) + 1

    infections = _classify_infections(pathogens, abs_reg)
    score = _compute_immunity_score(pathogens, abs_reg)
    state = _classify_state(score, infections, len(pathogens))

    # Count active antibodies.
    active = sum(1 for ab in abs_reg if _coverage_for_class(ab.target, abs_reg) > 0)

    return ImmuneReport(
        pathogens=pathogens,
        antibodies_active=active,
        infections=infections,
        immunity_score=score,
        state=state,
        pathogens_by_class=by_class,
    )


def immune_summary(report: ImmuneReport) -> str:
    """Human-readable one-liner summary."""
    parts = [f"immunity {report.immunity_score}/100 ({report.state})"]
    parts.append(f"{len(report.pathogens)} pathogen(s)")
    parts.append(f"{report.antibodies_active} antibod(ies)")

    if report.infections:
        kinds = sorted(set(p.kind for p in report.infections))
        parts.append(f"infections: {', '.join(kinds)}")

    if report.pathogens_by_class:
        top = sorted(report.pathogens_by_class.items(), key=lambda x: -x[1])
        parts.append(f"top threat: {top[0][0]} ({top[0][1]})")

    return " | ".join(parts)
