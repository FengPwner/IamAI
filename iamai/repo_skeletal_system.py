"""repo_skeletal_system — structural integrity and load-bearing analysis.

A living repository needs a strong skeleton: the directory layout, core
modules, and foundational interfaces that everything else hangs off.
When the skeleton is healthy, new features slot in cleanly and changes
propagate predictably.  When it degrades — fractures (broken imports),
osteoporosis (thinly-tested modules), misalignment (naming drift),
overloaded joints (god modules with too many dependents) — the whole
body moves stiffly and breaks under stress.

The skeletal metaphor
---------------------

=========================  ===================================================
concept                    what it maps to
=========================  ===================================================
**bone**                   a Python module (``iamai/*.py``)
**joint**                  an import relationship between two bones
**fracture**               a broken or circular import
**osteoporosis**           a module with little or no test coverage
**load-bearing bone**      a module that many others depend on
**misalignment**           naming inconsistency or directory drift
**bone density**           ratio of docstrings + comments to code lines
**skeleton score**         0–100 composite health score
=========================  ===================================================

Fracture classes
----------------

========================  =====================================================
class                     detection heuristic
========================  =====================================================
``broken_import``         module referenced in import but file missing
``circular_import``       A imports B imports … imports A
``duplicate_module``      two files with identical stem under different dirs
``stale_init``            ``__init__.py`` re-exports a symbol that no longer
                          exists in the package
``missing_init``          package directory without ``__init__.py``
``orphan_test``           test file whose target module is gone
========================  =====================================================

Load-bearing analysis
---------------------

A bone is *load-bearing* when ≥ ``load_threshold`` other modules import
from it.  Removing a load-bearing bone would cascade failures across
the body.  The more load-bearing bones, the more the skeleton's weight
is distributed; a single bone carrying > 40 % of all joints is a
*stress concentration* risk.

Osteoporosis scoring
--------------------

For each bone, compute::

    density = test_lines / max(code_lines, 1)

Bones with density < 0.3 are *osteoporotic* (thinly tested).
The osteoporosis ratio is::

    osteoporotic_bones / total_bones

Misalignment detection
----------------------

========================  =====================================================
signal                    heuristic
========================  =====================================================
``naming_drift``          module name uses underscores in one place and
                          hyphens in another for the same concept
``directory_drift``       modules placed outside the canonical package
                          directory
``empty_bone``            module file with < 5 lines of actual code
========================  =====================================================

Bone density
------------

For each module, count:

- **code_lines**: non-blank, non-comment lines
- **doc_lines**: docstring + comment lines

``density = doc_lines / max(code_lines, 1)``

A well-documented module has density ≥ 0.2.

Skeletal score
--------------

Start at 100 and deduct:

- **−8** per fracture
- **−3** per osteoporotic bone (density < 0.3)
- **−5** per stress-concentration (> 40 % joints on one bone)
- **−2** per misalignment signal
- **−1** per empty bone

Floor at 0.

Usage::

    from iamai.repo_skeletal_system import skeletal_report, skeletal_summary

    r = skeletal_report(repo_path=".")
    print(r.skeleton_score)   # e.g. 78.0
    print(r.state)            # "sound"
    print(r.fractures)        # []
    print(skeletal_summary(r))
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FRACTURE_CLASSES = (
    "broken_import",
    "circular_import",
    "duplicate_module",
    "stale_init",
    "missing_init",
    "orphan_test",
)

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".github"}

_DEFAULT_LOAD_THRESHOLD = 3  # imports from N+ modules → load-bearing
_STRESS_CONCENTRATION_RATIO = 0.40  # one bone carrying >40% of joints
_OSTEOPOROSIS_DENSITY_THRESHOLD = 0.3
_DOC_DENSITY_HEALTHY = 0.2
_EMPTY_BONE_MIN_LINES = 5


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Fracture:
    """A single structural defect."""

    kind: str          # one of FRACTURE_CLASSES
    path: str          # file path relative to repo root
    detail: str = ""


@dataclass(frozen=True)
class Bone:
    """A module in the skeleton."""

    path: str
    code_lines: int = 0
    doc_lines: int = 0
    importers: int = 0        # how many other modules import this one
    has_test: bool = False
    test_lines: int = 0

    @property
    def doc_density(self) -> float:
        return self.doc_lines / max(self.code_lines, 1)

    @property
    def test_density(self) -> float:
        return self.test_lines / max(self.code_lines, 1)

    @property
    def is_osteoporotic(self) -> bool:
        return self.test_density < _OSTEOPOROSIS_DENSITY_THRESHOLD

    @property
    def is_empty(self) -> bool:
        return self.code_lines < _EMPTY_BONE_MIN_LINES

    @property
    def is_well_documented(self) -> bool:
        return self.doc_density >= _DOC_DENSITY_HEALTHY


@dataclass(frozen=True)
class Misalignment:
    """A naming or placement inconsistency."""

    kind: str          # naming_drift | directory_drift | empty_bone
    path: str
    detail: str = ""


@dataclass
class SkeletalReport:
    """Complete skeletal integrity report."""

    bones: List[Bone] = field(default_factory=list)
    fractures: List[Fracture] = field(default_factory=list)
    misalignments: List[Misalignment] = field(default_factory=list)
    load_bearing: List[str] = field(default_factory=list)
    stress_concentration: Optional[str] = None
    osteoporotic_count: int = 0
    osteoporosis_ratio: float = 0.0
    skeleton_score: float = 100.0
    state: str = "sound"
    fractures_by_class: Dict[str, int] = field(default_factory=dict)
    avg_doc_density: float = 0.0
    avg_test_density: float = 0.0


# ---------------------------------------------------------------------------
# Import graph helpers
# ---------------------------------------------------------------------------

def _parse_imports(filepath: Path) -> List[str]:
    """Return module names imported by *filepath*."""
    try:
        source = filepath.read_text(errors="ignore")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, ValueError):
        return []

    modules: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module.split(".")[0])
    return modules


def _count_lines(filepath: Path) -> Tuple[int, int]:
    """Return (code_lines, doc_lines) for a Python file."""
    try:
        source = filepath.read_text(errors="ignore")
    except (OSError, PermissionError):
        return 0, 0

    code = 0
    doc = 0
    in_docstring = False
    for line in source.splitlines():
        stripped = line.strip()
        if in_docstring:
            doc += 1
            if '"""' in stripped or "'''" in stripped:
                in_docstring = False
            continue
        if not stripped:
            continue
        if stripped.startswith("#"):
            doc += 1
            continue
        if stripped.startswith(('"""', "'''")):
            doc += 1
            # Check if docstring closes on the same line.
            quote = stripped[:3]
            if stripped.count(quote) == 1:
                in_docstring = True
            continue
        code += 1
    return code, doc


def _build_import_graph(
    repo_path: str,
) -> Dict[str, Set[str]]:
    """Build a mapping: module_stem → set of module stems it imports."""
    root = Path(repo_path)
    graph: Dict[str, Set[str]] = {}

    pkg_dir = root / "iamai"
    if not pkg_dir.is_dir():
        return graph

    for fp in pkg_dir.glob("*.py"):
        if fp.name.startswith("__"):
            continue
        stem = fp.stem
        imported = _parse_imports(fp)
        # Keep only intra-package imports.
        graph[stem] = set()
        for mod in imported:
            if (pkg_dir / f"{mod}.py").exists() and mod != stem:
                graph[stem].add(mod)
    return graph


# ---------------------------------------------------------------------------
# Fracture detectors
# ---------------------------------------------------------------------------

def _detect_broken_imports(
    repo_path: str,
    import_graph: Dict[str, Set[str]],
) -> List[Fracture]:
    """Find imports that reference modules that no longer exist."""
    fractures: List[Fracture] = []
    root = Path(repo_path)
    pkg_dir = root / "iamai"

    all_stems = {fp.stem for fp in pkg_dir.glob("*.py") if not fp.name.startswith("__")}

    for stem, deps in import_graph.items():
        for dep in deps:
            if dep not in all_stems:
                fractures.append(Fracture(
                    kind="broken_import",
                    path=f"iamai/{stem}.py",
                    detail=f"imports '{dep}' which does not exist",
                ))
    return fractures


def _detect_circular_imports(
    import_graph: Dict[str, Set[str]],
) -> List[Fracture]:
    """Detect simple circular import chains (A→B→A or A→B→C→A)."""
    fractures: List[Fracture] = []
    visited: Set[str] = set()

    def _dfs(node: str, path: List[str], seen: Set[str]) -> None:
        if node in seen:
            cycle_start = path.index(node) if node in path else -1
            if cycle_start >= 0:
                cycle = path[cycle_start:] + [node]
                fractures.append(Fracture(
                    kind="circular_import",
                    path=f"iamai/{node}.py",
                    detail=" → ".join(cycle),
                ))
            return
        if node in visited:
            return
        seen.add(node)
        path.append(node)
        for dep in import_graph.get(node, set()):
            _dfs(dep, list(path), set(seen))
        visited.add(node)

    for stem in import_graph:
        _dfs(stem, [], set())

    # Deduplicate: keep only one fracture per unique cycle set.
    seen_cycles: Set[str] = set()
    unique: List[Fracture] = []
    for f in fractures:
        parts = f.detail.split(" → ")
        key = "→".join(sorted(set(parts)))
        if key not in seen_cycles:
            seen_cycles.add(key)
            unique.append(f)
    return unique


def _detect_duplicate_modules(repo_path: str) -> List[Fracture]:
    """Find Python files with identical stems in different directories."""
    fractures: List[Fracture] = []
    root = Path(repo_path)
    seen: Dict[str, List[str]] = {}

    for fp in root.rglob("*.py"):
        if _SKIP_DIRS & set(fp.parts):
            continue
        if fp.name.startswith("__"):
            continue
        stem = fp.stem
        rel = str(fp.relative_to(root))
        seen.setdefault(stem, []).append(rel)

    for stem, paths in seen.items():
        if len(paths) > 1:
            # Only flag if at least two are in different directories.
            dirs = {os.path.dirname(p) for p in paths}
            if len(dirs) > 1:
                fractures.append(Fracture(
                    kind="duplicate_module",
                    path=paths[0],
                    detail=f"'{stem}' exists in: {', '.join(sorted(dirs))}",
                ))
    return fractures


def _detect_stale_init(repo_path: str) -> List[Fracture]:
    """Find __init__.py files that re-export symbols no longer present."""
    fractures: List[Fracture] = []
    root = Path(repo_path)
    pkg_dir = root / "iamai"
    init_file = pkg_dir / "__init__.py"

    if not init_file.exists():
        return fractures

    try:
        source = init_file.read_text(errors="ignore")
        tree = ast.parse(source, filename=str(init_file))
    except (SyntaxError, ValueError):
        return fractures

    # Collect all names exported via __all__ or imported.
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                target_file = pkg_dir / f"{node.module}.py"
                if not target_file.exists():
                    fractures.append(Fracture(
                        kind="stale_init",
                        path="iamai/__init__.py",
                        detail=f"re-exports from '{node.module}' which is gone",
                    ))
    return fractures


def _detect_missing_init(repo_path: str) -> List[Fracture]:
    """Find Python package directories missing __init__.py."""
    fractures: List[Fracture] = []
    root = Path(repo_path)

    for d in root.rglob("*"):
        if not d.is_dir():
            continue
        if _SKIP_DIRS & set(d.parts):
            continue
        # Check if directory contains .py files.
        py_files = list(d.glob("*.py"))
        if py_files and not (d / "__init__.py").exists():
            fractures.append(Fracture(
                kind="missing_init",
                path=str(d.relative_to(root)),
                detail=f"directory has {len(py_files)} .py file(s) but no __init__.py",
            ))
    return fractures


def _detect_orphan_tests(
    repo_path: str,
    import_graph: Dict[str, Set[str]],
) -> List[Fracture]:
    """Find test files whose target module no longer exists."""
    fractures: List[Fracture] = []
    root = Path(repo_path)
    tests_dir = root / "tests"
    pkg_dir = root / "iamai"

    if not tests_dir.is_dir():
        return fractures

    all_stems = {fp.stem for fp in pkg_dir.glob("*.py") if not fp.name.startswith("__")}

    for tf in tests_dir.glob("test_*.py"):
        # Infer target: test_foo.py → foo.py
        target = tf.stem.removeprefix("test_")
        if target not in all_stems:
            # Some test files test infrastructure, not a module; skip those
            # where the target stem is a known utility name.
            _utility_targets = {
                "iamai", "batch", "sync", "push", "roster", "pool",
                "garden", "thoughts", "writer", "caretaker", "snippets",
            }
            if target not in _utility_targets:
                fractures.append(Fracture(
                    kind="orphan_test",
                    path=str(tf.relative_to(root)),
                    detail=f"target module '{target}' not found in iamai/",
                ))
    return fractures


def detect_fractures(
    repo_path: str = ".",
) -> List[Fracture]:
    """Run all fracture detectors and return combined results."""
    graph = _build_import_graph(repo_path)
    found: List[Fracture] = []
    found.extend(_detect_broken_imports(repo_path, graph))
    found.extend(_detect_circular_imports(graph))
    found.extend(_detect_duplicate_modules(repo_path))
    found.extend(_detect_stale_init(repo_path))
    found.extend(_detect_missing_init(repo_path))
    found.extend(_detect_orphan_tests(repo_path, graph))
    return found


# ---------------------------------------------------------------------------
# Bone inventory
# ---------------------------------------------------------------------------

def _inventory_bones(
    repo_path: str,
    import_graph: Dict[str, Set[str]],
) -> List[Bone]:
    """Build a Bone record for each module in iamai/."""
    root = Path(repo_path)
    pkg_dir = root / "iamai"
    tests_dir = root / "tests"
    bones: List[Bone] = []

    if not pkg_dir.is_dir():
        return bones

    # Count how many modules import each stem.
    importer_count: Dict[str, int] = {}
    for stem, deps in import_graph.items():
        for dep in deps:
            importer_count[dep] = importer_count.get(dep, 0) + 1

    for fp in sorted(pkg_dir.glob("*.py")):
        if fp.name.startswith("__"):
            continue
        stem = fp.stem
        code, doc = _count_lines(fp)

        # Find matching test file.
        has_test = False
        test_lines = 0
        test_file = tests_dir / f"test_{stem}.py"
        if test_file.exists():
            has_test = True
            test_lines = sum(
                1 for line in test_file.read_text(errors="ignore").splitlines()
                if line.strip()
            )

        bones.append(Bone(
            path=f"iamai/{fp.name}",
            code_lines=code,
            doc_lines=doc,
            importers=importer_count.get(stem, 0),
            has_test=has_test,
            test_lines=test_lines,
        ))
    return bones


# ---------------------------------------------------------------------------
# Load-bearing analysis
# ---------------------------------------------------------------------------

def _find_load_bearing(
    bones: List[Bone],
    threshold: int = _DEFAULT_LOAD_THRESHOLD,
) -> List[str]:
    """Return paths of bones imported by ≥ threshold others."""
    return [b.path for b in bones if b.importers >= threshold]


def _find_stress_concentration(
    bones: List[Bone],
) -> Optional[str]:
    """Return the path if one bone carries > 40% of all joints."""
    total_joints = sum(b.importers for b in bones)
    if total_joints == 0:
        return None
    for b in bones:
        if b.importers / total_joints > _STRESS_CONCENTRATION_RATIO:
            return b.path
    return None


# ---------------------------------------------------------------------------
# Misalignment detection
# ---------------------------------------------------------------------------

def _detect_misalignments(
    repo_path: str,
    bones: List[Bone],
) -> List[Misalignment]:
    """Find naming drift, directory drift, and empty bones."""
    mis: List[Misalignment] = []
    root = Path(repo_path)

    # --- naming_drift: underscore vs hyphen for same concept ---
    # Collect all module stems.
    stems = [Path(b.path).stem for b in bones]
    normalised: Dict[str, List[str]] = {}
    for s in stems:
        key = s.replace("_", "-")
        normalised.setdefault(key, []).append(s)
    for key, variants in normalised.items():
        if len(variants) > 1:
            mis.append(Misalignment(
                kind="naming_drift",
                path=f"iamai/{variants[0]}.py",
                detail=f"concept '{key}' spelled as: {', '.join(variants)}",
            ))

    # --- directory_drift: .py files outside iamai/ (excluding tests/) ---
    for fp in root.rglob("*.py"):
        if _SKIP_DIRS & set(fp.parts):
            continue
        rel = fp.relative_to(root)
        parts = rel.parts
        if parts[0] not in ("iamai", "tests", "tools", "scripts") and not fp.name.startswith("__"):
            mis.append(Misalignment(
                kind="directory_drift",
                path=str(rel),
                detail=f"module outside canonical dirs (iamai/, tests/, tools/, scripts/)",
            ))

    # --- empty_bone ---
    for b in bones:
        if b.is_empty:
            mis.append(Misalignment(
                kind="empty_bone",
                path=b.path,
                detail=f"only {b.code_lines} code line(s)",
            ))

    return mis


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _compute_skeleton_score(
    fractures: List[Fracture],
    bones: List[Bone],
    misalignments: List[Misalignment],
    stress_conc: Optional[str],
) -> float:
    """0–100 composite skeletal health score."""
    score = 100.0
    # −8 per fracture
    score -= 8.0 * len(fractures)
    # −3 per osteoporotic bone
    osteo = sum(1 for b in bones if b.is_osteoporotic)
    score -= 3.0 * osteo
    # −5 per stress concentration
    if stress_conc is not None:
        score -= 5.0
    # −2 per misalignment
    score -= 2.0 * len(misalignments)
    # −1 per empty bone (already counted in misalignments, but the
    # misalignment list may contain other kinds too, so count separately)
    empty = sum(1 for b in bones if b.is_empty)
    score -= 1.0 * empty
    return round(max(0.0, score), 1)


def _classify_state(score: float, fractures: List[Fracture]) -> str:
    """Classify overall skeletal state."""
    if not fractures and score >= 90:
        return "sound"
    if score >= 75:
        return "sound"
    if score >= 55:
        return "weakened"
    if score >= 35:
        return "fragile"
    return "brittle"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def skeletal_report(
    repo_path: str = ".",
    load_threshold: int = _DEFAULT_LOAD_THRESHOLD,
) -> SkeletalReport:
    """Scan the repository and produce a full skeletal health report.

    Parameters
    ----------
    repo_path:
        Path to the git repository root.
    load_threshold:
        Number of importers above which a bone is considered load-bearing.

    Returns
    -------
    SkeletalReport with all metrics populated.
    """
    graph = _build_import_graph(repo_path)
    fractures = detect_fractures(repo_path)
    bones = _inventory_bones(repo_path, graph)
    misalignments = _detect_misalignments(repo_path, bones)
    load_bearing = _find_load_bearing(bones, load_threshold)
    stress_conc = _find_stress_concentration(bones)

    # Osteoporosis stats.
    osteo_count = sum(1 for b in bones if b.is_osteoporotic)
    osteo_ratio = osteo_count / max(len(bones), 1)

    # Averages.
    avg_doc = (
        sum(b.doc_density for b in bones) / max(len(bones), 1)
    )
    avg_test = (
        sum(b.test_density for b in bones) / max(len(bones), 1)
    )

    score = _compute_skeleton_score(fractures, bones, misalignments, stress_conc)
    state = _classify_state(score, fractures)

    # Fractures by class.
    by_class: Dict[str, int] = {}
    for f in fractures:
        by_class[f.kind] = by_class.get(f.kind, 0) + 1

    return SkeletalReport(
        bones=bones,
        fractures=fractures,
        misalignments=misalignments,
        load_bearing=load_bearing,
        stress_concentration=stress_conc,
        osteoporotic_count=osteo_count,
        osteoporosis_ratio=round(osteo_ratio, 3),
        skeleton_score=score,
        state=state,
        fractures_by_class=by_class,
        avg_doc_density=round(avg_doc, 3),
        avg_test_density=round(avg_test, 3),
    )


def skeletal_summary(report: SkeletalReport) -> str:
    """Human-readable one-liner summary."""
    parts = [f"skeleton {report.skeleton_score}/100 ({report.state})"]
    parts.append(f"{len(report.bones)} bone(s)")
    parts.append(f"{len(report.fractures)} fracture(s)")

    if report.load_bearing:
        parts.append(f"{len(report.load_bearing)} load-bearing")

    if report.stress_concentration:
        parts.append(f"stress concentration: {report.stress_concentration}")

    parts.append(
        f"osteoporosis: {report.osteoporotic_count}/{len(report.bones)} "
        f"({report.osteoporosis_ratio:.0%})"
    )

    if report.fractures_by_class:
        top = sorted(report.fractures_by_class.items(), key=lambda x: -x[1])
        parts.append(f"top defect: {top[0][0]} ({top[0][1]})")

    return " | ".join(parts)
