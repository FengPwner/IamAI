"""
test_coverage: measure what fraction of iamai/ modules have corresponding tests.

A growing codebase accumulates modules faster than tests.  This module
answers: **how many iamai/ modules have at least one test file in tests/?**

Convention: module ``iamai/foo.py`` is considered tested when
``tests/test_foo.py`` exists.  This is a coarse heuristic — it does not
measure statement coverage — but it catches the worst case: a module
with zero automated attention.

The module produces:

* ``total_modules``   — Python files in ``iamai/`` (excluding ``__init__``)
* ``tested``          — modules that have a matching ``test_<name>.py``
* ``untested``        — modules with no test file
* ``coverage_ratio``  — tested / total  (0.0 – 1.0)
* ``verdict``         — ``"solid"`` (≥ 0.9), ``"fair"`` (≥ 0.7), or ``"sparse"``

Usage::

    from iamai.test_coverage import module_test_coverage, coverage_report

    info = module_test_coverage(repo_root)
    print(info["coverage_ratio"])   # 0.82
    print(info["untested"])         # ["backlog_monitor", "roster", ...]

    print(coverage_report(repo_root))
    # "fair — 115/139 modules tested (82.7%), 24 untested"
"""

from pathlib import Path
from typing import Any, Dict, List


def _discover_modules(repo_dir: Path) -> List[str]:
    """Return sorted list of iamai/ module stems (excluding __init__)."""
    pkg = repo_dir / "iamai"
    if not pkg.is_dir():
        return []
    stems: List[str] = []
    for p in pkg.glob("*.py"):
        if p.stem == "__init__":
            continue
        stems.append(p.stem)
    return sorted(stems)


def _discover_tests(repo_dir: Path) -> set:
    """Return set of module stems that have a matching test file."""
    tests_dir = repo_dir / "tests"
    if not tests_dir.is_dir():
        return set()
    covered: set = set()
    for p in tests_dir.glob("test_*.py"):
        stem = p.stem
        if stem.startswith("test_"):
            module_stem = stem[len("test_"):]
            covered.add(module_stem)
    return covered


def module_test_coverage(repo_dir, limit=None):
    """Compute test coverage for iamai/ modules.

    Parameters
    ----------
    repo_dir : path
        Repository root directory.

    Returns
    -------
    dict with keys: total_modules, tested, untested, coverage_ratio, verdict.
    """
    repo_dir = Path(repo_dir)
    modules = _discover_modules(repo_dir)
    tested_stems = _discover_tests(repo_dir)

    total = len(modules)
    tested = sorted(m for m in modules if m in tested_stems)
    untested = sorted(m for m in modules if m not in tested_stems)

    ratio = len(tested) / total if total > 0 else 0.0

    if ratio >= 0.9:
        verdict = "solid"
    elif ratio >= 0.7:
        verdict = "fair"
    else:
        verdict = "sparse"

    return {
        "total_modules": total,
        "tested": tested,
        "untested": untested,
        "coverage_ratio": round(ratio, 4),
        "verdict": verdict,
    }


def coverage_report(repo_dir):
    """Human-readable one-liner test coverage report."""
    info = module_test_coverage(repo_dir)
    total = info["total_modules"]
    tested_count = len(info["tested"])
    untested_count = len(info["untested"])
    pct = info["coverage_ratio"] * 100
    parts = [info["verdict"]]
    parts.append(f"{tested_count}/{total} modules tested ({pct:.1f}%)")
    if untested_count > 0:
        parts.append(f"{untested_count} untested")
    if 0 < untested_count <= 10:
        parts.append(f"missing: {', '.join(info['untested'])}")
    return " — ".join(parts)
