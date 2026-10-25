"""100 — backlog_pressure: measure uncommitted work pressure in a git repo.

commit_health gives you a whole-repo score. stroke_freshness tells you how
recent the last stroke was. neither answers the question a caretaker asks
when they see uncommitted files: *how bad is the backlog, really?*

backlog_pressure looks at three dimensions:

  - **volume**: how many uncommitted files?  1 is noise, 50 is a crisis.
  - **age**: how long has the oldest file been pending?  a file modified
    30 seconds ago is mid-flight; one modified 3 hours ago is forgotten.
  - **kind**: are the pending files state (json, lock), content (md, py),
    or data (jsonl)?  state files self-resolve; content files need a human.

each dimension scores 0.0–1.0 and combines into a composite pressure score.
pressure is not health — it is urgency.  a repo can be healthy (writer
running, cadence good) and still have high pressure (backlog growing faster
than the batch committer can flush).

thresholds (configurable):

  ===========  =========  ========================================
  pressure     verdict    meaning
  ===========  =========  ========================================
  0.0 – 0.2    low        normal operating state
  0.2 – 0.5    moderate   backlog is building; committer may lag
  0.5 – 0.8    high       significant uncommitted work; investigate
  0.8 – 1.0    critical   backlog at risk of conflicts or loss
  ===========  =========  ========================================

zero dependencies.  stdlib only.  operates on a git working tree path.

>>> import tempfile, os, subprocess
>>> d = tempfile.mkdtemp()
>>> _ = subprocess.run(["git","init","-q",d], check=True)
>>> report = measure_pressure(d)
>>> report["pressure"] >= 0.0
True
>>> report["verdict"] in ("low","moderate","high","critical")
True
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# thresholds — tune these to your repo's tolerance
# ---------------------------------------------------------------------------

# volume: number of uncommitted files → score
_VOLUME_LOW = 3        # ≤ this → score 0.0
_VOLUME_HIGH = 50      # ≥ this → score 1.0

# age: seconds since oldest pending modification → score
_AGE_LOW = 60          # ≤ this → score 0.0  (mid-flight)
_AGE_HIGH = 3600       # ≥ this → score 1.0  (forgotten)

# kind weights: state files are less worrying than content files
_KIND_WEIGHTS = {
    "state": 0.2,       # json, lock, pid — self-resolving
    "data": 0.4,        # jsonl, csv — append-only, low risk
    "content": 0.7,     # md, py, txt — human-authored, higher stakes
    "binary": 0.9,      # images, compiled — hard to re-merge
}
_KIND_DEFAULT = 0.5

# composite weights
_W_VOLUME = 0.4
_W_AGE = 0.3
_W_KIND = 0.3


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_STATE_EXTS = {".json", ".lock", ".pid", ".tmp", ".bak"}
_DATA_EXTS = {".jsonl", ".csv", ".tsv", ".log"}
_BINARY_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".pyc", ".so"}
_CONTENT_EXTS = {".md", ".py", ".txt", ".yaml", ".yml", ".toml", ".sh", ".rst"}


def _classify_file(path: str) -> str:
    """Return the kind bucket for a file path."""
    ext = Path(path).suffix.lower()
    if ext in _STATE_EXTS:
        return "state"
    if ext in _DATA_EXTS:
        return "data"
    if ext in _BINARY_EXTS:
        return "binary"
    if ext in _CONTENT_EXTS:
        return "content"
    return "content"  # unknown → treat as content (conservative)


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _score_volume(n_files: int) -> float:
    """Score the volume dimension: more files → higher score."""
    if n_files <= _VOLUME_LOW:
        return 0.0
    if n_files >= _VOLUME_HIGH:
        return 1.0
    return _clamp(
        (n_files - _VOLUME_LOW) / (_VOLUME_HIGH - _VOLUME_LOW)
    )


def _score_age(seconds: float) -> float:
    """Score the age dimension: older pending files → higher score."""
    if seconds <= _AGE_LOW:
        return 0.0
    if seconds >= _AGE_HIGH:
        return 1.0
    return _clamp(
        (seconds - _AGE_LOW) / (_AGE_HIGH - _AGE_LOW)
    )


def _score_kind(files: list[str]) -> float:
    """Score the kind dimension: weighted average of file classifications."""
    if not files:
        return 0.0
    total = sum(_KIND_WEIGHTS.get(_classify_file(f), _KIND_DEFAULT) for f in files)
    return _clamp(total / len(files))


# ---------------------------------------------------------------------------
# git interaction
# ---------------------------------------------------------------------------

def _get_uncommitted_files(repo_path: str) -> list[str]:
    """Return list of uncommitted file paths (porcelain format)."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True,
            cwd=repo_path,
            timeout=10,
        )
        if result.returncode != 0:
            return []
        files = []
        # do NOT strip the whole output — porcelain lines like
        # " M file" start with a space that is part of the XY status
        # field; stripping it shifts the filename column by one.
        for raw_line in result.stdout.split("\n"):
            if not raw_line.strip():
                continue
            # porcelain v1: "XY path" — X (index) and Y (worktree) are
            # exactly 2 chars, then a space, then the path.
            if len(raw_line) < 4:
                continue
            path = raw_line[3:]
            # handle renames: "R  old -> new"
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            # strip surrounding quotes from git's core.quotePath
            if path.startswith('"') and path.endswith('"'):
                path = path[1:-1]
            files.append(path.strip())
        return files
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def _get_oldest_mtime(repo_path: str, files: list[str]) -> float:
    """Return seconds since the oldest modification among the given files.

    Returns 0.0 if no files exist on disk or the repo path is invalid.
    """
    if not files:
        return 0.0
    now = time.time()
    oldest_age = 0.0
    for f in files:
        full = os.path.join(repo_path, f)
        try:
            mtime = os.path.getmtime(full)
            age = now - mtime
            if age > oldest_age:
                oldest_age = age
        except OSError:
            continue
    return oldest_age


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

VERDICTS = [
    (0.2, "low"),
    (0.5, "moderate"),
    (0.8, "high"),
    (1.01, "critical"),  # inclusive of 1.0
]


def _verdict(pressure: float) -> str:
    for threshold, label in VERDICTS:
        if pressure < threshold:
            return label
    return "critical"


def measure_pressure(
    repo_path: str = ".",
    *,
    files: list[str] | None = None,
    oldest_age_s: float | None = None,
) -> dict[str, Any]:
    """Measure the backlog pressure for a git working tree.

    Parameters
    ----------
    repo_path:
        Path to the git working tree.  Defaults to cwd.
    files:
        Override the uncommitted file list (skip git call).  Useful for
        testing or when the caller already has the list.
    oldest_age_s:
        Override the oldest file age in seconds (skip filesystem check).
        Useful for testing.

    Returns
    -------
    dict with keys:
        pressure   — float 0.0–1.0 composite score
        verdict    — str: low / moderate / high / critical
        volume     — dict: n_files, score
        age        — dict: oldest_seconds, score
        kind       — dict: files, classifications, score
        breakdown  — dict: volume_weight, age_weight, kind_weight
    """
    repo_path = os.path.abspath(repo_path)

    if files is None:
        files = _get_uncommitted_files(repo_path)

    if oldest_age_s is None:
        oldest_age_s = _get_oldest_mtime(repo_path, files)

    vol_score = _score_volume(len(files))
    age_score = _score_age(oldest_age_s)
    kind_score = _score_kind(files)

    pressure = _clamp(
        _W_VOLUME * vol_score
        + _W_AGE * age_score
        + _W_KIND * kind_score
    )

    classifications = {f: _classify_file(f) for f in files}

    return {
        "pressure": round(pressure, 4),
        "verdict": _verdict(pressure),
        "volume": {"n_files": len(files), "score": round(vol_score, 4)},
        "age": {"oldest_seconds": round(oldest_age_s, 2), "score": round(age_score, 4)},
        "kind": {
            "files": files,
            "classifications": classifications,
            "score": round(kind_score, 4),
        },
        "breakdown": {
            "volume_weight": _W_VOLUME,
            "age_weight": _W_AGE,
            "kind_weight": _W_KIND,
        },
    }


def pressure_report(repo_path: str = ".") -> str:
    """One-line human-readable pressure summary.

    Example: ``backlog pressure: moderate (0.34) — 8 files, oldest 420s``
    """
    r = measure_pressure(repo_path)
    return (
        f"backlog pressure: {r['verdict']} ({r['pressure']:.2f}) "
        f"— {r['volume']['n_files']} files, "
        f"oldest {r['age']['oldest_seconds']:.0f}s"
    )
