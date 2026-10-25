"""Documentation coverage — which iamai modules have tests and visit notes?

As the codebase grows past 100 modules, it becomes easy to ship code
without matching tests or to leave a module undocumented in the
caretaker visit log.  This module answers three questions:

1. Which ``iamai/*.py`` modules lack a ``tests/test_<name>.py``?
2. Which modules are mentioned in at least one caretaker visit note?
3. What is the overall test and documentation coverage ratio?

Usage::

    from iamai.doc_coverage import coverage_report, coverage_summary

    report = coverage_report(repo_root=".")
    print(report["test_coverage"])     # 0.92
    print(report["doc_coverage"])      # 0.85
    print(report["untested"])          # ["foo", "bar"]

    summary = coverage_summary(repo_root=".")
    # "iamai: 118/120 tested (98%), 101/120 documented (84%)"

Design
------

- **Pure reads.**  Scans the filesystem; never writes.
- **Fast.**  One ``glob`` per directory, set operations for diffs.
- **Deterministic.**  Sorted output, no randomness.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _discover_modules(iamai_dir: Path) -> set[str]:
    """Return stem names of all .py files in iamai/ except __init__."""
    return {
        p.stem for p in iamai_dir.glob("*.py")
        if p.stem != "__init__" and not p.name.startswith("__pycache__")
    }


def _discover_tests(tests_dir: Path) -> set[str]:
    """Return the module stems covered by test files."""
    return {
        p.stem.replace("test_", "", 1)
        for p in tests_dir.glob("test_*.py")
    }


def _discover_documented(notes_dir: Path) -> set[str]:
    """Return module stems mentioned in any caretaker visit note."""
    if not notes_dir.is_dir():
        return set()
    documented: set[str] = set()
    pattern = re.compile(r"iamai[/\\](\w+)\.py|`(\w+)` module|module `(\w+)`|(\w+) module")
    for note in notes_dir.glob("caretaker-visit-*.md"):
        text = note.read_text(encoding="utf-8", errors="replace")
        for m in pattern.finditer(text):
            name = next(g for g in m.groups() if g)
            documented.add(name)
    return documented


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def coverage_report(repo_root: str | Path = ".") -> dict[str, Any]:
    """Compute test and documentation coverage for the iamai package.

    Returns a dict with keys:

    - ``total_modules``: int
    - ``tested_count``: int
    - ``untested_count``: int
    - ``documented_count``: int
    - ``undocumented_count``: int
    - ``test_coverage``: float (0.0–1.0)
    - ``doc_coverage``: float (0.0–1.0)
    - ``untested``: sorted list of module stems without tests
    - ``undocumented``: sorted list of module stems not mentioned in visits
    - ``tested``: sorted list of module stems with tests
    - ``documented``: sorted list of module stems with visit mentions
    """
    root = Path(repo_root).resolve()
    iamai_dir = root / "iamai"
    tests_dir = root / "tests"
    notes_dir = root / "notes"

    modules = _discover_modules(iamai_dir)
    tested = _discover_tests(tests_dir) & modules
    documented = _discover_documented(notes_dir) & modules

    untested = modules - tested
    undocumented = modules - documented
    total = len(modules) or 1  # avoid zero-division

    return {
        "total_modules": len(modules),
        "tested_count": len(tested),
        "untested_count": len(untested),
        "documented_count": len(documented),
        "undocumented_count": len(undocumented),
        "test_coverage": round(len(tested) / total, 4),
        "doc_coverage": round(len(documented) / total, 4),
        "untested": sorted(untested),
        "undocumented": sorted(undocumented),
        "tested": sorted(tested),
        "documented": sorted(documented),
    }


def coverage_summary(repo_root: str | Path = ".") -> str:
    """One-line human-readable coverage summary."""
    r = coverage_report(repo_root)
    t_pct = round(r["test_coverage"] * 100)
    d_pct = round(r["doc_coverage"] * 100)
    return (
        f"iamai: {r['tested_count']}/{r['total_modules']} tested ({t_pct}%), "
        f"{r['documented_count']}/{r['total_modules']} documented ({d_pct}%)"
    )
