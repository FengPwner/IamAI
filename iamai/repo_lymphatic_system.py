"""repo_lymphatic_system — waste clearance and fluid-balance analysis.

A living repository accumulates metabolic waste the same way a body
does: dead code that nobody calls, imports that resolve to nothing,
TODO markers that fossilise into architecture, commented-out blocks
that haunt future readers, test files whose targets have been deleted.
Left unchecked this waste creates **oedema** — the repo swells, moves
sluggishly, and resists change.

In a biological body the **lymphatic system** performs two jobs:

1. **Waste clearance** — collecting cellular debris, misfolded
   proteins, and foreign particles, then draining them to lymph nodes
   for disposal.
2. **Fluid balance** — returning interstitial fluid to the bloodstream
   so tissue does not bloat.

This module performs the same two jobs for a repository.  It scans
every Python file under ``iamai/`` (and its test counterparts) for
eight classes of waste, scores each one, and produces a composite
**lymphatic health score** from 0 (fully congested) to 100 (clean).

The lymphatic metaphor
-----------------------

=========================  ===================================================
concept                    what it maps to
=========================  ===================================================
**waste item**             a single instance of detectable waste
**waste category**         one of eight classes (see table below)
**lymph node**             a grouping key — usually a directory or module —
                           that aggregates waste items
**oedema**                 file or directory whose waste density exceeds
                           the congestion threshold
**drainage rate**          ratio of waste items resolved vs created between
                           two snapshots
**lymphatic score**        0–100 composite clearance health
=========================  ===================================================

Waste categories
-----------------

========================  =====================================================
category                  detection heuristic
========================  =====================================================
``unused_import``         import statement whose symbol is never referenced
                          elsewhere in the same file
``dead_function``         ``def`` not called anywhere in the repo (excluding
                          ``__init__``, ``main``, fixtures, and tests)
``commented_code``        block of ≥ 3 consecutive lines starting with ``#``
                          that look like Python statements
``stale_todo``            ``TODO`` / ``FIXME`` / ``HACK`` / ``XXX`` marker
                          whose file mtime is older than ``stale_days``
``orphan_test``           test file whose target module (by name convention)
                          no longer exists
``empty_module``          Python file with ≤ 5 non-blank lines and no
                          docstring (placeholder or abandoned stub)
``duplicate_snippet``     near-identical code block (≥ 10 lines) appearing
                          in ≥ 2 files (structural fingerprint hash)
``stale_branch``          local git branch not merged and not updated for
                          ``branch_stale_days``
========================  =====================================================

Scoring
--------

Each category produces a sub-score from 0 (worst) to 100 (best)::

    category_score = max(0, 100 - (item_count * weight))

The composite score is the weighted average::

    lymphatic_score = sum(category_score[i] * category_weight[i])
                      / sum(category_weight)

Default weights give heavier penalties to *unused_import* and
*orphan_test* (active hygiene failures) and lighter penalties to
*stale_todo* and *commented_code* (passive accumulation).

Oedema detection
-----------------

A file is **oedematous** when its per-file waste count exceeds
``oedema_threshold`` (default 5).  A directory is oedematous when the
sum of its files' waste exceeds ``dir_oedema_threshold`` (default 15).

Usage
------

::

    from iamai.repo_lymphatic_system import LymphaticAnalyzer

    report = LymphaticAnalyzer(repo_root=".").analyze()
    print(report["lymphatic_score"], report["total_waste"])
    for item in report["items"]:
        print(item.to_dict())

CLI
----

::

    python -m iamai.repo_lymphatic_system --repo . --json
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Days after which a TODO/FIXME marker is considered stale.
DEFAULT_STALE_DAYS = 90

#: Days after which an unmerged local branch is considered stale.
DEFAULT_BRANCH_STALE_DAYS = 60

#: Per-file waste count that triggers an oedema flag.
DEFAULT_OEDEMA_THRESHOLD = 5

#: Per-directory waste count that triggers an oedema flag.
DEFAULT_DIR_OEDEMA_THRESHOLD = 15

#: Minimum consecutive commented-out lines to count as a block.
COMMENTED_CODE_MIN_LINES = 3

#: Minimum lines for a duplicate-snippet fingerprint.
SNIPPET_MIN_LINES = 10

#: Names excluded from dead-function detection (entry points / fixtures).
EXEMPT_FUNCTION_NAMES = frozenset({
    "main", "__init__", "__new__", "__del__",
    "__str__", "__repr__", "__eq__", "__hash__",
    "__enter__", "__exit__", "__getitem__", "__setitem__",
    "__len__", "__iter__", "__next__", "__contains__",
    "__call__", "__bool__", "__int__", "__float__",
    "__add__", "__sub__", "__mul__", "__truediv__",
    "setUp", "tearDown", "setUpClass", "tearDownClass",
    "conftest", "pytest_collection_modifyitems",
})

#: Prefixes that mark a function as a test or fixture.
EXEMPT_FUNCTION_PREFIXES = ("test_", "fixture_", "_fixture", "conftest_")

#: Default category weights for composite scoring.
DEFAULT_WEIGHTS: Dict[str, float] = {
    "unused_import": 6.0,
    "dead_function": 5.0,
    "commented_code": 2.0,
    "stale_todo": 1.5,
    "orphan_test": 7.0,
    "empty_module": 3.0,
    "duplicate_snippet": 4.0,
    "stale_branch": 3.5,
}

VALID_CATEGORIES = tuple(DEFAULT_WEIGHTS.keys())


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WasteItem:
    """A single instance of detectable repository waste."""

    category: str
    file: str
    line: int
    detail: str
    severity: str = "info"  # info | warning | critical

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "file": self.file,
            "line": self.line,
            "detail": self.detail,
            "severity": self.severity,
        }


@dataclass
class OedemaRegion:
    """A file or directory whose waste density exceeds the threshold."""

    path: str
    waste_count: int
    kind: str = "file"  # file | directory

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "waste_count": self.waste_count,
            "kind": self.kind,
        }


@dataclass
class LymphaticReport:
    """Aggregated result of a full lymphatic scan."""

    lymphatic_score: float
    total_waste: int
    items: List[WasteItem] = field(default_factory=list)
    oedema_regions: List[OedemaRegion] = field(default_factory=list)
    category_counts: Dict[str, int] = field(default_factory=dict)
    category_scores: Dict[str, float] = field(default_factory=dict)
    files_scanned: int = 0
    scan_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lymphatic_score": round(self.lymphatic_score, 2),
            "total_waste": self.total_waste,
            "items": [it.to_dict() for it in self.items],
            "oedema_regions": [o.to_dict() for o in self.oedema_regions],
            "category_counts": dict(self.category_counts),
            "category_scores": {k: round(v, 2) for k, v in self.category_scores.items()},
            "files_scanned": self.files_scanned,
            "scan_seconds": round(self.scan_seconds, 3),
        }


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _repo_files(repo_root: str, suffix: str = ".py") -> List[Path]:
    """Return all files ending with *suffix* under *repo_root*/iamai/."""
    iamai_dir = Path(repo_root) / "iamai"
    if not iamai_dir.is_dir():
        return []
    return sorted(p for p in iamai_dir.rglob(f"*{suffix}") if p.is_file())


def _test_files(repo_root: str) -> List[Path]:
    """Return all test files under *repo_root*/tests/."""
    tests_dir = Path(repo_root) / "tests"
    if not tests_dir.is_dir():
        return []
    return sorted(p for p in tests_dir.rglob("test_*.py") if p.is_file())


def _all_py_files(repo_root: str) -> List[Path]:
    """Return all .py files under iamai/ and tests/."""
    return _repo_files(repo_root) + _test_files(repo_root)


def _read_lines(path: Path) -> List[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _parse_ast(path: Path) -> Optional[ast.Module]:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        return ast.parse(source, filename=str(path))
    except (SyntaxError, ValueError):
        return None


def _file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _rel(path: Path, repo_root: str) -> str:
    """Return a path relative to repo_root for stable reporting."""
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Detectors — one per waste category
# ---------------------------------------------------------------------------

def _detect_unused_imports(path: Path, repo_root: str) -> List[WasteItem]:
    """Find import names that are never used in the rest of the file."""
    tree = _parse_ast(path)
    if tree is None:
        return []

    imported_names: Dict[str, int] = {}  # name -> line
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                imported_names[name] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue
                name = alias.asname or alias.name
                imported_names[name] = node.lineno

    if not imported_names:
        return []

    # Collect all Name references (excluding import nodes themselves).
    used: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and not isinstance(
            getattr(node, "_parent", None), (ast.Import, ast.ImportFrom)
        ):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            # handle `module.func` — the module Name is caught above
            pass

    # Also do a simple text search for names used in strings/decorators.
    source_lines = _read_lines(path)
    full_text = "\n".join(source_lines)

    items: List[WasteItem] = []
    for name, lineno in imported_names.items():
        # Count uses outside the import line itself.
        # Quick heuristic: name appears as a word boundary match elsewhere.
        pattern = re.compile(r"\b" + re.escape(name) + r"\b")
        matches = pattern.findall(full_text)
        # Subtract the import-line occurrence(s).
        import_line_text = source_lines[lineno - 1] if lineno <= len(source_lines) else ""
        import_matches = pattern.findall(import_line_text)
        usage_count = len(matches) - len(import_matches)
        if usage_count <= 0:
            items.append(WasteItem(
                category="unused_import",
                file=_rel(path, repo_root),
                line=lineno,
                detail=f"imported name '{name}' not used in file",
                severity="warning",
            ))
    return items


def _detect_dead_functions(path: Path, repo_root: str,
                           all_called: Optional[set] = None) -> List[WasteItem]:
    """Find functions/methods that are never called in the repo.

    If *all_called* is not supplied, a repo-wide scan is performed
    lazily.  Callers doing batch analysis should pre-compute it once.
    """
    tree = _parse_ast(path)
    if tree is None:
        return []

    if all_called is None:
        all_called = _build_called_set(Path(repo_root))

    items: List[WasteItem] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = node.name
        if name in EXEMPT_FUNCTION_NAMES:
            continue
        if any(name.startswith(p) for p in EXEMPT_FUNCTION_PREFIXES):
            continue
        if name.startswith("_") and name.endswith("__"):
            continue  # dunder
        if name.startswith("_"):
            continue  # private helpers often legitimately unused
        if name not in all_called:
            items.append(WasteItem(
                category="dead_function",
                file=_rel(path, repo_root),
                line=node.lineno,
                detail=f"function '{name}' not called anywhere in repo",
                severity="warning",
            ))
    return items


def _build_called_set(repo_root: Path) -> set:
    """Build a set of all function/method names that appear in a call
    expression anywhere in the repository."""
    called: set = set()
    for py in repo_root.rglob("*.py"):
        if not py.is_file():
            continue
        tree = _parse_ast(py)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    called.add(func.id)
                elif isinstance(func, ast.Attribute):
                    called.add(func.attr)
            # Also count decorator references as "use".
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Name):
                        called.add(dec.id)
                    elif isinstance(dec, ast.Attribute):
                        called.add(dec.attr)
    return called


def _detect_commented_code(path: Path, repo_root: str) -> List[WasteItem]:
    """Find blocks of ≥ COMMENTED_CODE_MIN_LINES consecutive comment
    lines that look like Python code."""
    lines = _read_lines(path)
    if not lines:
        return []

    # Heuristic: a comment line "looks like code" if after stripping
    # the leading ``#`` it starts with a Python keyword/operator or
    # contains an ``=`` / ``(`` / ``)`` / ``:`` that suggests code.
    code_keywords = re.compile(
        r"^\s*(?:import|from|def|class|if|elif|else|for|while|with|try|"
        r"except|finally|return|yield|raise|pass|break|continue|assert|"
        r"self|print|lambda)\b|[=\(\)\[\]\{\}]|:=|->"
    )

    items: List[WasteItem] = []
    block_start: Optional[int] = None
    block_count = 0

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            after_hash = stripped[1:].strip()
            if after_hash and code_keywords.search(after_hash):
                if block_start is None:
                    block_start = i
                block_count += 1
                continue
        # End of potential block.
        if block_count >= COMMENTED_CODE_MIN_LINES and block_start is not None:
            items.append(WasteItem(
                category="commented_code",
                file=_rel(path, repo_root),
                line=block_start,
                detail=f"{block_count}-line commented-out code block",
                severity="info",
            ))
        block_start = None
        block_count = 0

    # Trailing block.
    if block_count >= COMMENTED_CODE_MIN_LINES and block_start is not None:
        items.append(WasteItem(
            category="commented_code",
            file=_rel(path, repo_root),
            line=block_start,
            detail=f"{block_count}-line commented-out code block",
            severity="info",
        ))
    return items


_TODO_RE = re.compile(r"#\s*(TODO|FIXME|HACK|XXX|WORKAROUND)\b", re.IGNORECASE)


def _detect_stale_todos(path: Path, repo_root: str,
                        stale_days: int = DEFAULT_STALE_DAYS) -> List[WasteItem]:
    """Find TODO/FIXME markers older than *stale_days*."""
    lines = _read_lines(path)
    if not lines:
        return []

    mtime = _file_mtime(path)
    if mtime == 0:
        return []
    now = time.time()
    age_days = (now - mtime) / 86400

    items: List[WasteItem] = []
    for i, line in enumerate(lines, start=1):
        m = _TODO_RE.search(line)
        if m and age_days > stale_days:
            tag = m.group(1).upper()
            items.append(WasteItem(
                category="stale_todo",
                file=_rel(path, repo_root),
                line=i,
                detail=f"{tag} marker is {int(age_days)} days old (threshold {stale_days})",
                severity="info",
            ))
    return items


def _detect_orphan_tests(repo_root: str) -> List[WasteItem]:
    """Find test files whose target module no longer exists."""
    iamai_dir = Path(repo_root) / "iamai"
    tests_dir = Path(repo_root) / "tests"
    if not tests_dir.is_dir() or not iamai_dir.is_dir():
        return []

    # Build a set of module stems that exist in iamai/.
    existing_stems: set = set()
    for p in iamai_dir.rglob("*.py"):
        if p.name == "__init__.py":
            continue
        existing_stems.add(p.stem)

    items: List[WasteItem] = []
    for tp in tests_dir.rglob("test_*.py"):
        # Convention: test_foo.py tests foo.py
        target_stem = tp.stem.replace("test_", "", 1)
        if target_stem and target_stem not in existing_stems:
            items.append(WasteItem(
                category="orphan_test",
                file=_rel(tp, repo_root),
                line=1,
                detail=f"test file has no matching target module '{target_stem}.py' in iamai/",
                severity="warning",
            ))
    return items


def _detect_empty_modules(path: Path, repo_root: str) -> List[WasteItem]:
    """Find Python files that are essentially empty placeholders."""
    lines = _read_lines(path)
    if path.name == "__init__.py":
        return []

    non_blank = [l for l in lines if l.strip()]
    if len(non_blank) > 5:
        return []

    # Check for module docstring.
    tree = _parse_ast(path)
    if tree and (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, (ast.Constant, ast.Str))
    ):
        # Has a docstring — might be a stub with documentation.
        # Only flag if truly tiny (≤ 3 lines).
        if len(non_blank) > 3:
            return []

    return [WasteItem(
        category="empty_module",
        file=_rel(path, repo_root),
        line=1,
        detail=f"module has {len(non_blank)} non-blank lines and no substantive content",
        severity="info",
    )]


def _fingerprint_block(lines: List[str]) -> str:
    """Produce a normalised hash for a block of code lines, ignoring
    whitespace and comments, to detect near-duplicate snippets."""
    normalised: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Collapse internal whitespace.
        normalised.append(" ".join(stripped.split()))
    blob = "\n".join(normalised)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _detect_duplicate_snippets(repo_root: str) -> List[WasteItem]:
    """Find near-identical code blocks of ≥ SNIPPET_MIN_LINES appearing
    in two or more files."""
    all_files = _all_py_files(repo_root)
    # fingerprint -> list of (file, start_line)
    fingerprints: Dict[str, List[Tuple[str, int]]] = {}

    for path in all_files:
        lines = _read_lines(path)
        if len(lines) < SNIPPET_MIN_LINES:
            continue
        rel_path = _rel(path, repo_root)
        for start in range(0, len(lines) - SNIPPET_MIN_LINES + 1):
            block = lines[start:start + SNIPPET_MIN_LINES]
            fp = _fingerprint_block(block)
            fingerprints.setdefault(fp, []).append((rel_path, start + 1))

    items: List[WasteItem] = []
    seen_pairs: set = set()
    for fp, locations in fingerprints.items():
        # Group by unique files.
        files_seen = {loc[0] for loc in locations}
        if len(files_seen) < 2:
            continue
        # Report one item per pair (capped to avoid explosion).
        file_list = sorted(files_seen)
        for i in range(len(file_list)):
            for j in range(i + 1, len(file_list)):
                pair_key = (file_list[i], file_list[j])
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                # Find first occurrence line numbers.
                loc_a = next(l for l in locations if l[0] == file_list[i])
                loc_b = next(l for l in locations if l[0] == file_list[j])
                items.append(WasteItem(
                    category="duplicate_snippet",
                    file=file_list[i],
                    line=loc_a[1],
                    detail=(
                        f"~{SNIPPET_MIN_LINES}-line duplicate snippet also in "
                        f"{file_list[j]}:{loc_b[1]}"
                    ),
                    severity="warning",
                ))
                if len(items) > 200:
                    return items  # cap to avoid runaway output
    return items


def _detect_stale_branches(repo_root: str,
                            stale_days: int = DEFAULT_BRANCH_STALE_DAYS) -> List[WasteItem]:
    """Find local git branches that have not been updated recently."""
    items: List[WasteItem] = []
    try:
        result = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname:short) %(committerdate:unix)",
             "refs/heads/"],
            capture_output=True, text=True, cwd=repo_root, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []

    now = time.time()
    for line in result.stdout.strip().splitlines():
        parts = line.rsplit(" ", 1)
        if len(parts) != 2:
            continue
        branch, ts_str = parts
        try:
            ts = float(ts_str)
        except ValueError:
            continue
        age_days = (now - ts) / 86400
        if age_days > stale_days:
            items.append(WasteItem(
                category="stale_branch",
                file=".git/refs/heads",
                line=0,
                detail=f"branch '{branch}' not updated for {int(age_days)} days",
                severity="info",
            ))
    return items


# ---------------------------------------------------------------------------
# Main analyzer
# ---------------------------------------------------------------------------

class LymphaticAnalyzer:
    """Scan a repository for waste accumulation and produce a health report.

    Parameters
    ----------
    repo_root : str
        Path to the repository root.
    stale_days : int
        Days after which a TODO marker is considered stale.
    branch_stale_days : int
        Days after which an unmerged branch is considered stale.
    oedema_threshold : int
        Per-file waste item count that triggers an oedema flag.
    dir_oedema_threshold : int
        Per-directory waste item count that triggers an oedema flag.
    weights : dict
        Category weights for composite scoring.
    """

    def __init__(
        self,
        repo_root: str = ".",
        stale_days: int = DEFAULT_STALE_DAYS,
        branch_stale_days: int = DEFAULT_BRANCH_STALE_DAYS,
        oedema_threshold: int = DEFAULT_OEDEMA_THRESHOLD,
        dir_oedema_threshold: int = DEFAULT_DIR_OEDEMA_THRESHOLD,
        weights: Optional[Dict[str, float]] = None,
    ) -> None:
        self.repo_root = str(Path(repo_root).resolve())
        self.stale_days = stale_days
        self.branch_stale_days = branch_stale_days
        self.oedema_threshold = oedema_threshold
        self.dir_oedema_threshold = dir_oedema_threshold
        self.weights = dict(weights or DEFAULT_WEIGHTS)

    # -- public API --------------------------------------------------------

    def analyze(self) -> Dict[str, Any]:
        """Run all detectors and return a JSON-serialisable report dict."""
        t0 = time.monotonic()
        all_items: List[WasteItem] = []
        py_files = _repo_files(self.repo_root)
        test_files = _test_files(self.repo_root)
        all_py = py_files + test_files

        # Pre-compute called-set once for dead-function detection.
        called_set = _build_called_set(Path(self.repo_root))

        for path in py_files:
            all_items.extend(_detect_unused_imports(path, self.repo_root))
            all_items.extend(_detect_dead_functions(path, self.repo_root, called_set))
            all_items.extend(_detect_commented_code(path, self.repo_root))
            all_items.extend(_detect_stale_todos(path, self.repo_root, self.stale_days))
            all_items.extend(_detect_empty_modules(path, self.repo_root))

        # Cross-file detectors.
        all_items.extend(_detect_orphan_tests(self.repo_root))
        all_items.extend(_detect_duplicate_snippets(self.repo_root))
        all_items.extend(_detect_stale_branches(self.repo_root, self.branch_stale_days))

        # Category counts and scores.
        counts: Dict[str, int] = {c: 0 for c in VALID_CATEGORIES}
        for item in all_items:
            counts[item.category] = counts.get(item.category, 0) + 1

        cat_scores: Dict[str, float] = {}
        for cat in VALID_CATEGORIES:
            w = self.weights.get(cat, 1.0)
            cat_scores[cat] = max(0.0, 100.0 - counts[cat] * w)

        weighted_sum = sum(cat_scores[c] * self.weights[c] for c in VALID_CATEGORIES)
        weight_total = sum(self.weights.values())
        lymphatic_score = weighted_sum / weight_total if weight_total else 0.0

        # Oedema detection.
        file_counts: Dict[str, int] = {}
        for item in all_items:
            file_counts[item.file] = file_counts.get(item.file, 0) + 1

        oedema_regions: List[OedemaRegion] = []
        for fpath, cnt in file_counts.items():
            if cnt >= self.oedema_threshold:
                oedema_regions.append(OedemaRegion(
                    path=fpath, waste_count=cnt, kind="file",
                ))

        dir_counts: Dict[str, int] = {}
        for fpath, cnt in file_counts.items():
            d = str(Path(fpath).parent)
            dir_counts[d] = dir_counts.get(d, 0) + cnt
        for dpath, cnt in dir_counts.items():
            if cnt >= self.dir_oedema_threshold:
                oedema_regions.append(OedemaRegion(
                    path=dpath, waste_count=cnt, kind="directory",
                ))

        elapsed = time.monotonic() - t0

        report = LymphaticReport(
            lymphatic_score=lymphatic_score,
            total_waste=len(all_items),
            items=all_items,
            oedema_regions=oedema_regions,
            category_counts=counts,
            category_scores=cat_scores,
            files_scanned=len(all_py),
            scan_seconds=elapsed,
        )
        return report.to_dict()


# ---------------------------------------------------------------------------
# Drainage rate — diff between two snapshots
# ---------------------------------------------------------------------------

def drainage_rate(
    before: Dict[str, Any],
    after: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute the waste clearance rate between two reports.

    Returns a dict with ``resolved``, ``created``, and ``net_drain``
    (positive means the repo got cleaner).
    """
    def _item_keys(items: list) -> set:
        return {(it["category"], it["file"], it["line"]) for it in items}

    before_set = _item_keys(before.get("items", []))
    after_set = _item_keys(after.get("items", []))

    resolved = len(before_set - after_set)
    created = len(after_set - before_set)
    return {
        "resolved": resolved,
        "created": created,
        "net_drain": resolved - created,
        "before_total": len(before_set),
        "after_total": len(after_set),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Repo lymphatic system analyzer")
    parser.add_argument("--repo", default=".", help="Path to repo root")
    parser.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS)
    parser.add_argument("--branch-stale-days", type=int, default=DEFAULT_BRANCH_STALE_DAYS)
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    analyzer = LymphaticAnalyzer(
        repo_root=args.repo,
        stale_days=args.stale_days,
        branch_stale_days=args.branch_stale_days,
    )
    report = analyzer.analyze()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Lymphatic score: {report['lymphatic_score']:.1f}/100")
        print(f"Total waste: {report['total_waste']} items across {report['files_scanned']} files")
        print(f"Scan time: {report['scan_seconds']:.3f}s")
        print()
        print("Category breakdown:")
        for cat in VALID_CATEGORIES:
            cnt = report["category_counts"].get(cat, 0)
            sc = report["category_scores"].get(cat, 100.0)
            print(f"  {cat:25s}  {cnt:3d} items  score {sc:.0f}")
        if report["oedema_regions"]:
            print(f"\nOedema regions ({len(report['oedema_regions'])}):")
            for oed in report["oedema_regions"]:
                print(f"  [{oed['kind']}] {oed['path']} — {oed['waste_count']} waste items")


if __name__ == "__main__":
    main()
