"""repo_meta_health — is the watcher eating the watched?

A self-monitoring repo has two populations: the *content* (strokes,
notes, docs, thoughts — the thing being produced) and the *instrumentation*
(modules, tests, caretaker scripts — the thing that watches).

Healthy growth means content leads.  When instrumentation grows faster
than content, the repo is spending more energy watching itself than
producing anything worth watching.  That's a leading indicator of
introspective paralysis: a system that measures everything and creates
nothing.

This module classifies every tracked file into one of four buckets:

============  =========================================================
bucket        what lives here
============  =========================================================
``content``   strokes, notes, docs, thoughts, garden, metrics
``instrument`` iamai/*.py modules, tests/*, scripts
``infra``     tools/, CI config, Makefile, requirements, pytest.ini
``other``     everything else (README, assets, snippets)
============  =========================================================

The **meta ratio** is::

    meta_ratio = instrument / max(content, 1)

A ratio above 1.0 means more watchers than creators.  The thresholds:

==========  =========================================================
verdict     meaning
==========  =========================================================
``lean``    ratio ≤ 0.5 — instrumentation is modest relative to output
``balanced`` 0.5 < ratio ≤ 1.0 — watchers and creators in rough parity
``heavy``   1.0 < ratio ≤ 2.0 — instrumentation dominates
``bloated`` ratio > 2.0 — the watchers have won
==========  =========================================================

Trend
-----

Given two snapshots, the module also reports whether the ratio is
improving (content catching up) or worsening (instrumentation pulling
ahead).  A *worsening* trend while the ratio is already ``heavy`` or
``bloated`` is the signal to stop adding analysis modules and start
writing more strokes.

Usage::

    from iamai.repo_meta_health import MetaSnapshot, analyze, trend

    snap = analyze(repo_path)
    print(snap.verdict)        # "balanced"
    print(snap.meta_ratio)     # 0.87

    # Compare two snapshots
    direction = trend(earlier, later)
    print(direction)           # "improving" | "worsening" | "stable"
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# --- Classification rules ---------------------------------------------------

_CONTENT_PREFIXES = (
    "notes/",
    "docs/",
    "data/strokes",
    "snippets/",
)

_INSTRUMENT_PREFIXES = (
    "iamai/",
    "tests/",
    "scripts/",
)

_INFRA_PREFIXES = (
    "tools/",
    "agent/",
)

_INFRA_EXACT = {
    "Makefile",
    "pytest.ini",
    "requirements-dev.txt",
    "requirements.txt",
    ".github/",
    ".gitignore",
}


def _classify_file(path: str) -> str:
    """Classify a tracked file path into a bucket."""
    # Content first (notes/ and docs/ are unambiguous)
    for prefix in _CONTENT_PREFIXES:
        if path.startswith(prefix):
            return "content"
    # Instrument
    for prefix in _INSTRUMENT_PREFIXES:
        if path.startswith(prefix):
            return "instrument"
    # Infra
    for prefix in _INFRA_PREFIXES:
        if path.startswith(prefix):
            return "infra"
    for exact in _INFRA_EXACT:
        if path == exact or path.startswith(exact):
            return "infra"
    return "other"


# --- Snapshot ---------------------------------------------------------------

@dataclass
class MetaSnapshot:
    """Point-in-time classification of the repo's file population."""

    content: int = 0
    instrument: int = 0
    infra: int = 0
    other: int = 0
    total: int = 0

    @property
    def meta_ratio(self) -> float:
        """instrument files per content file (clamped: min content = 1)."""
        return self.instrument / max(self.content, 1)

    @property
    def verdict(self) -> str:
        r = self.meta_ratio
        if r <= 0.5:
            return "lean"
        if r <= 1.0:
            return "balanced"
        if r <= 2.0:
            return "heavy"
        return "bloated"

    def bucket_counts(self) -> Dict[str, int]:
        return {
            "content": self.content,
            "instrument": self.instrument,
            "infra": self.infra,
            "other": self.other,
        }

    def summary(self) -> str:
        return (
            f"{self.verdict}: ratio {self.meta_ratio:.2f} "
            f"({self.instrument} instrument / {self.content} content, "
            f"{self.total} total)"
        )


# --- Analyze ----------------------------------------------------------------

def _tracked_files(repo: str | Path) -> List[str]:
    """Return list of git-tracked file paths relative to repo root."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    ]


def analyze(repo: str | Path, files: Optional[List[str]] = None) -> MetaSnapshot:
    """Classify every tracked file and return a MetaSnapshot.

    If *files* is given, skip the git call and classify the provided list
    directly.  Useful for testing.
    """
    if files is None:
        files = _tracked_files(repo)

    snap = MetaSnapshot()
    for f in files:
        bucket = _classify_file(f)
        if bucket == "content":
            snap.content += 1
        elif bucket == "instrument":
            snap.instrument += 1
        elif bucket == "infra":
            snap.infra += 1
        else:
            snap.other += 1
        snap.total += 1

    return snap


# --- Trend ------------------------------------------------------------------

def trend(earlier: MetaSnapshot, later: MetaSnapshot) -> str:
    """Compare two snapshots and return the ratio direction.

    Returns one of: ``'improving'``, ``'worsening'``, ``'stable'``.

    *improving* means the ratio went down (more content relative to
    instrumentation).  *worsening* means it went up.  *stable* means
    the change is within ±0.05.
    """
    delta = later.meta_ratio - earlier.meta_ratio
    if abs(delta) < 0.05:
        return "stable"
    return "improving" if delta < 0 else "worsening"


# --- Report -----------------------------------------------------------------

def meta_health_report(repo: str | Path) -> str:
    """One-liner suitable for caretaker briefings."""
    snap = analyze(repo)
    return snap.summary()


# --- CLI --------------------------------------------------------------------

def main(repo: str = ".") -> None:
    snap = analyze(repo)
    print(snap.summary())
    counts = snap.bucket_counts()
    for bucket, count in sorted(counts.items()):
        print(f"  {bucket}: {count}")


if __name__ == "__main__":
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
