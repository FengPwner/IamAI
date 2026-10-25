"""repo_renal — detect and score repository waste accumulation.

A living repository generates metabolic waste as a byproduct of growth:
dead code paths, orphaned test files, stale branches that were never
merged, files tracked but no longer imported, empty directories, and
deprecated utilities kept "just in case." In a biological kidney, the
glomerulus filters blood plasma, the tubules reabsorb what is still
useful, and the collecting duct excretes the rest as urine. When the
kidneys fail, toxic metabolites accumulate (uremia) and the organism
degrades.

The renal metaphor
-------------------

=========================  ===================================================
concept                    what it maps to
=========================  ===================================================
**glomerular filtration**  scanning the tree for potential waste items
**filtration rate (GFR)**  percentage of tree covered by waste scan
**tubular reabsorption**   re-evaluating flagged items that are still imported
                           or referenced elsewhere (false positives)
**excretion**              actually deleting or pruning confirmed waste
**uremia**                 elevated waste score (>60) indicating toxic buildup
**dialysis**               an external caretaker intervention to clear waste
**kidney stone**           a single large waste item blocking progress
                           (e.g. a 5000-line dead module)
**nephron**                one scan-and-clean cycle
=========================  ===================================================

Waste categories
----------------

1. **orphan_modules** — Python files not imported by any other file
   and not referenced in any script or configuration.
2. **dead_branches** — local or remote branches with no commits in the
   last N days that were never merged.
3. **stale_files** — tracked files not modified in the last N days and
   not referenced in the current test suite.
4. **empty_artifacts** — zero-byte files, empty directories, or files
   containing only whitespace / boilerplate.
5. **deprecated_code** — functions or classes decorated with
   ``@deprecated`` or marked ``TODO: remove`` in comments.
6. **redundant_tests** — test files whose imports have all been
   deleted (they test nothing that still exists).
7. **zombie_config** — configuration keys in JSON/YAML that no module
   reads.

Scoring
-------

Each category produces a sub-score 0-100. The overall renal health
score is inverted (100 − waste_score) so that higher is healthier.

========================  ======
category                  weight
========================  ======
orphan_modules            0.20
dead_branches             0.15
stale_files               0.15
empty_artifacts           0.10
deprecated_code           0.15
redundant_tests           0.15
zombie_config             0.10
========================  ======

Renal states: healthy (score ≥ 80), mild_waste (60-79),
moderate_waste (40-59), uremic (20-39), renal_failure (< 20).

Edge cases
----------

- Empty repository (no tracked files): returns ``healthy`` with score
  100 and zero waste items.
- Repository with no Python files: orphan_modules and redundant_tests
  score 0 (nothing to filter).
- Fewer than 5 commits: stale_files uses a shorter look-back window.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class WasteItem:
    """One identified piece of repository waste."""

    path: str
    category: str
    score: float  # 0-100 severity for this item
    evidence: str
    salvageable: bool = False  # True if reabsorption flagged it

    @property
    def excrete(self) -> bool:
        """Should this item be removed?"""
        return self.score > 50 and not self.salvageable


@dataclass
class WasteCategory:
    """Aggregated waste for one category."""

    name: str
    items: List[WasteItem] = field(default_factory=list)
    score: float = 0.0
    weight: float = 0.0

    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def weighted(self) -> float:
        return self.score * self.weight


@dataclass
class RenalReport:
    """Full renal health assessment."""

    categories: List[WasteCategory] = field(default_factory=list)
    health_score: float = 100.0
    renal_state: str = "healthy"
    total_waste_items: int = 0
    excretion_candidates: int = 0
    kidney_stones: int = 0
    recommendation: str = ""
    scanned_files: int = 0
    scanned_branches: int = 0

    @property
    def waste_score(self) -> float:
        return round(100.0 - self.health_score, 1)

    @property
    def needs_dialysis(self) -> bool:
        return self.health_score < 40


# ---------------------------------------------------------------------------
# Shell helper
# ---------------------------------------------------------------------------


def _run(cmd: str, cwd: Optional[str] = None) -> str:
    """Run a shell command and return stdout."""
    try:
        r = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
        )
        return r.stdout.strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Waste detectors
# ---------------------------------------------------------------------------


def detect_orphan_modules(repo_path: str) -> WasteCategory:
    """Find Python files not imported anywhere else in the repo."""
    cat = WasteCategory(name="orphan_modules", weight=0.20)

    py_files = []
    for root, dirs, files in os.walk(repo_path):
        # Skip hidden dirs, __pycache__, tests
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))

    if not py_files:
        cat.score = 0.0
        return cat

    # Build set of all module basenames (without .py)
    all_modules = {os.path.splitext(os.path.basename(f))[0] for f in py_files}

    # For each module, check if it's imported by any other file
    orphans = []
    for fpath in py_files:
        modname = os.path.splitext(os.path.basename(fpath))[0]
        # Skip __init__.py, __main__.py, setup.py, conftest.py
        if modname in ("__init__", "__main__", "setup", "conftest"):
            continue

        # Search for imports of this module in other files
        found_import = False
        for other in py_files:
            if other == fpath:
                continue
            try:
                content = Path(other).read_text(errors="ignore")
                # Check for: import modname, from modname import, from .modname
                patterns = [
                    rf"import\s+{modname}\b",
                    rf"from\s+{modname}\s+import",
                    rf"from\s+\S*\.?{modname}\s+import",
                    rf'"{modname}"',  # string references in configs
                    rf"'{modname}'",
                ]
                if any(re.search(p, content) for p in patterns):
                    found_import = True
                    break
            except OSError:
                continue

        if not found_import:
            orphans.append(fpath)

    # Score: 0 orphans = 0, 50+ = 100
    raw_score = min(100, len(orphans) * 2)

    for opath in orphans:
        rel = os.path.relpath(opath, repo_path)
        cat.items.append(WasteItem(
            path=rel,
            category="orphan_modules",
            score=raw_score,
            evidence=f"not imported by any other tracked Python file",
        ))

    cat.score = round(raw_score, 1)
    return cat


def detect_dead_branches(repo_path: str, days: int = 30) -> WasteCategory:
    """Find branches with no activity in the last N days."""
    cat = WasteCategory(name="dead_branches", weight=0.15)

    raw = _run("git branch -a --format='%(refname:short)|%(committerdate:iso8601)'", cwd=repo_path)
    cutoff = datetime.now() - timedelta(days=days)
    dead = []

    for line in raw.splitlines():
        if "|" not in line:
            continue
        parts = line.split("|", 1)
        branch = parts[0].strip()
        date_str = parts[1].strip()[:19] if len(parts) > 1 else ""

        # Skip main/master
        if branch in ("main", "master", "origin/main", "origin/master", "HEAD"):
            continue

        try:
            last_commit = datetime.fromisoformat(date_str)
            if last_commit < cutoff:
                dead.append((branch, last_commit))
        except (ValueError, IndexError):
            # Can't parse date, skip
            continue

    # Score: 0 dead = 0, 20+ = 100
    raw_score = min(100, len(dead) * 5)

    for branch, dt in dead:
        age_days = (datetime.now() - dt).days
        cat.items.append(WasteItem(
            path=branch,
            category="dead_branches",
            score=raw_score,
            evidence=f"last commit {age_days} days ago",
        ))

    cat.score = round(raw_score, 1)
    return cat


def detect_stale_files(repo_path: str, days: int = 60) -> WasteCategory:
    """Find tracked files not modified recently and not in tests."""
    cat = WasteCategory(name="stale_files", weight=0.15)

    since_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    all_tracked = _run("git ls-files", cwd=repo_path).splitlines()
    recently_modified = _run(
        f'git log --since="{since_date}" --name-only --format="" | sort -u',
        cwd=repo_path,
    ).splitlines()

    recent_set = set(recently_modified)

    # Find test imports to check reference
    test_files = [f for f in all_tracked if f.startswith("tests/") and f.endswith(".py")]
    test_content = ""
    for tf in test_files:
        try:
            test_content += Path(os.path.join(repo_path, tf)).read_text(errors="ignore")
        except OSError:
            pass

    stale = []
    for fpath in all_tracked:
        if fpath in recent_set:
            continue
        # Skip dotfiles, configs, docs
        if fpath.startswith(".") or fpath.startswith("docs/"):
            continue
        # Check if referenced in tests
        basename = os.path.splitext(os.path.basename(fpath))[0]
        if basename in test_content:
            continue
        stale.append(fpath)

    # Score: 0 stale = 0, 100+ = 100
    raw_score = min(100, len(stale))

    for sf in stale[:50]:  # Cap to avoid huge lists
        cat.items.append(WasteItem(
            path=sf,
            category="stale_files",
            score=raw_score,
            evidence=f"not modified in {days} days, not referenced in tests",
        ))

    cat.score = round(raw_score, 1)
    return cat


def detect_empty_artifacts(repo_path: str) -> WasteCategory:
    """Find zero-byte files and empty directories."""
    cat = WasteCategory(name="empty_artifacts", weight=0.10)

    tracked = _run("git ls-files", cwd=repo_path).splitlines()
    empties = []

    for fpath in tracked:
        full = os.path.join(repo_path, fpath)
        try:
            if os.path.getsize(full) == 0:
                empties.append(fpath)
            else:
                content = Path(full).read_text(errors="ignore").strip()
                # Files with only imports or pass are near-empty
                if len(content) < 10 and content in ("", "pass", "# TODO"):
                    empties.append(fpath)
        except OSError:
            continue

    # Score: 0 empties = 0, 30+ = 100
    raw_score = min(100, len(empties) * 3.3)

    for ef in empties:
        cat.items.append(WasteItem(
            path=ef,
            category="empty_artifacts",
            score=raw_score,
            evidence="zero-byte or boilerplate-only file",
            salvageable=False,
        ))

    cat.score = round(raw_score, 1)
    return cat


def detect_deprecated_code(repo_path: str) -> WasteCategory:
    """Find functions/classes marked deprecated or TODO remove."""
    cat = WasteCategory(name="deprecated_code", weight=0.15)

    tracked = _run("git ls-files '*.py'", cwd=repo_path).splitlines()
    deprecated = []

    deprecated_patterns = [
        r"@deprecated",
        r"TODO:\s*remove",
        r"FIXME:\s*delete",
        r"HACK:\s*remove",
        r"# DEPRECATED",
        r"warnings\.warn\(.*[Dd]eprecated",
    ]

    for fpath in tracked:
        full = os.path.join(repo_path, fpath)
        try:
            content = Path(full).read_text(errors="ignore")
            for i, line in enumerate(content.splitlines(), 1):
                for pat in deprecated_patterns:
                    if re.search(pat, line):
                        rel = os.path.relpath(full, repo_path)
                        deprecated.append((rel, i, line.strip()))
                        break
        except OSError:
            continue

    # Score: 0 deprecated = 0, 20+ = 100
    raw_score = min(100, len(deprecated) * 5)

    for fpath, lineno, text in deprecated:
        cat.items.append(WasteItem(
            path=f"{fpath}:{lineno}",
            category="deprecated_code",
            score=raw_score,
            evidence=f"marked deprecated/TODO remove: {text[:60]}",
            salvageable=True,  # might still be in use during migration
        ))

    cat.score = round(raw_score, 1)
    return cat


def detect_redundant_tests(repo_path: str) -> WasteCategory:
    """Find test files whose target modules no longer exist."""
    cat = WasteCategory(name="redundant_tests", weight=0.15)

    test_dir = os.path.join(repo_path, "tests")
    if not os.path.isdir(test_dir):
        cat.score = 0.0
        return cat

    # Build set of existing iamai modules
    iamai_dir = os.path.join(repo_path, "iamai")
    existing_modules = set()
    if os.path.isdir(iamai_dir):
        for f in os.listdir(iamai_dir):
            if f.endswith(".py"):
                existing_modules.add(os.path.splitext(f)[0])

    test_files = [
        f for f in os.listdir(test_dir) if f.startswith("test_") and f.endswith(".py")
    ]

    redundant = []
    for tf in test_files:
        full = os.path.join(test_dir, tf)
        try:
            content = Path(full).read_text(errors="ignore")
        except OSError:
            continue

        # Extract imported module names from iamai.*
        imports = re.findall(r"from\s+iamai\.(\w+)\s+import", content)
        if not imports:
            continue

        # Check if ALL imported modules still exist
        missing = [m for m in imports if m not in existing_modules]
        if len(missing) == len(imports):
            redundant.append((tf, missing))

    # Score: 0 redundant = 0, 10+ = 100
    raw_score = min(100, len(redundant) * 10)

    for tf, missing in redundant:
        cat.items.append(WasteItem(
            path=f"tests/{tf}",
            category="redundant_tests",
            score=raw_score,
            evidence=f"all target modules deleted: {', '.join(missing)}",
        ))

    cat.score = round(raw_score, 1)
    return cat


def detect_zombie_config(repo_path: str) -> WasteCategory:
    """Find config keys in JSON files that no Python file references."""
    cat = WasteCategory(name="zombie_config", weight=0.10)

    # Find JSON config files (not in data/ or .git/)
    config_files = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "data"]
        for f in files:
            if f.endswith(".json") and f not in ("package.json", "package-lock.json"):
                config_files.append(os.path.join(root, f))

    zombie_keys = []

    for cf in config_files:
        try:
            data = json.loads(Path(cf).read_text(errors="ignore"))
        except (json.JSONDecodeError, OSError):
            continue

        if not isinstance(data, dict):
            continue

        # Check top-level keys
        for key in data.keys():
            if not isinstance(key, str) or len(key) < 3:
                continue
            # Search for key reference in Python files
            found = _run(
                f'grep -r --include="*.py" -l "{key}" "{repo_path}" 2>/dev/null',
            )
            if not found.strip():
                rel = os.path.relpath(cf, repo_path)
                zombie_keys.append((rel, key))

    # Score: 0 zombie keys = 0, 20+ = 100
    raw_score = min(100, len(zombie_keys) * 5)

    for cf, key in zombie_keys:
        cat.items.append(WasteItem(
            path=f"{cf}:{key}",
            category="zombie_config",
            score=raw_score,
            evidence=f"config key '{key}' not referenced in any Python file",
            salvageable=True,
        ))

    cat.score = round(raw_score, 1)
    return cat


# ---------------------------------------------------------------------------
# State classification
# ---------------------------------------------------------------------------

_STATES = [
    (20, "renal_failure"),
    (40, "uremic"),
    (60, "moderate_waste"),
    (80, "mild_waste"),
    (101, "healthy"),
]


def _classify_state(score: float) -> str:
    for threshold, label in _STATES:
        if score <= threshold:
            return label
    return "healthy"


def _make_recommendation(state: str, total: int, stones: int) -> str:
    if state == "healthy":
        return "Renal function normal. Waste clearance is keeping the tree clean."
    if state == "mild_waste":
        return (
            f"Mild waste accumulation ({total} items). "
            "Schedule a routine nephron cycle to clear orphans and stale files."
        )
    if state == "moderate_waste":
        msg = f"Moderate waste buildup ({total} items). "
        if stones:
            msg += f"{stones} kidney stone(s) detected — large dead modules should be removed first."
        else:
            msg += "Prioritise orphan module cleanup and stale file pruning."
        return msg
    if state == "uremic":
        return (
            f"Uremic: {total} waste items, health score critically low. "
            "Immediate dialysis recommended — caretaker should run a full "
            "tree audit and remove dead branches, orphan modules, and empty artifacts."
        )
    return (
        f"Renal failure: {total} waste items. "
        "Emergency intervention required. Consider a tree-wide purge of all "
        "unreferenced modules, dead branches, and stale configuration."
    )


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------


def analyze_renal(repo_path: str = ".", stale_days: int = 60) -> RenalReport:
    """Run full renal health analysis.

    Parameters
    ----------
    repo_path : str
        Path to the git repository.
    stale_days : int
        Days threshold for considering a file stale.

    Returns
    -------
    RenalReport
    """
    repo_path = str(Path(repo_path).resolve())

    categories = [
        detect_orphan_modules(repo_path),
        detect_dead_branches(repo_path),
        detect_stale_files(repo_path, stale_days),
        detect_empty_artifacts(repo_path),
        detect_deprecated_code(repo_path),
        detect_redundant_tests(repo_path),
        detect_zombie_config(repo_path),
    ]

    total_weight = sum(c.weight for c in categories)
    waste_raw = sum(c.weighted for c in categories)
    waste_score = round(waste_raw / total_weight, 1) if total_weight else 0.0
    health_score = round(100.0 - waste_score, 1)

    all_items = []
    for c in categories:
        all_items.extend(c.items)

    excretion_candidates = sum(1 for item in all_items if item.excrete)
    kidney_stones = sum(
        1
        for item in all_items
        if item.score > 70 and item.category in ("orphan_modules", "stale_files")
    )

    state = _classify_state(health_score)
    recommendation = _make_recommendation(state, len(all_items), kidney_stones)

    # Count scanned files
    tracked = _run("git ls-files", cwd=repo_path)
    scanned_files = len([l for l in tracked.splitlines() if l.strip()])
    branches = _run("git branch -a", cwd=repo_path)
    scanned_branches = len([l for l in branches.splitlines() if l.strip()])

    return RenalReport(
        categories=categories,
        health_score=health_score,
        renal_state=state,
        total_waste_items=len(all_items),
        excretion_candidates=excretion_candidates,
        kidney_stones=kidney_stones,
        recommendation=recommendation,
        scanned_files=scanned_files,
        scanned_branches=scanned_branches,
    )


def renal_summary(report: RenalReport) -> str:
    """One-line human-readable summary."""
    if report.renal_state == "healthy":
        return (
            f"healthy: score={report.health_score}, "
            f"{report.total_waste_items} waste items across "
            f"{report.scanned_files} files, {report.scanned_branches} branches"
        )
    dialysis_tag = " [needs dialysis]" if report.needs_dialysis else ""
    return (
        f"{report.renal_state}{dialysis_tag}: "
        f"health={report.health_score}, waste={report.waste_score}, "
        f"{report.total_waste_items} items, "
        f"{report.excretion_candidates} candidates for excretion, "
        f"{report.kidney_stones} kidney stone(s)"
    )


if __name__ == "__main__":
    report = analyze_renal()
    print(renal_summary(report))
    for cat in report.categories:
        print(f"  {cat.name}: {cat.score} (w={cat.weight}) — {cat.count} items")
        for item in cat.items[:3]:
            tag = "♻" if item.salvageable else "🗑"
            print(f"    {tag} {item.path}: {item.evidence[:60]}")
        if cat.count > 3:
            print(f"    ... and {cat.count - 3} more")
    print(f"\nRecommendation: {report.recommendation}")
