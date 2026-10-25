"""repo_hepatic — detect and score technical-debt toxin accumulation.

A living repository absorbs dependencies, APIs, patterns, and conventions
from its ecosystem the way a body absorbs nutrients and chemicals through
the portal vein.  The liver metabolises what is useful, neutralises what
is toxic, and excretes the rest as bile.  When hepatic function declines,
toxins accumulate (hepatotoxicity), metabolism slows, and the organism
becomes vulnerable to cascading failures.

The hepatic metaphor
--------------------

=========================  ===================================================
concept                    what it maps to
=========================  ===================================================
**hepatocyte**             one detoxification check (a single analyser func)
**portal vein**            the requirements / dependency surface bringing
                           external packages into the codebase
**bile duct**              the recommendation output — waste flagged for
                           removal by a caretaker
**detoxification pathway** an upgrade or migration plan for a stale dep
**cirrhosis**              chronic accumulation of tech debt (score > 70)
                           that impairs the repo's ability to evolve
**hepatitis**              acute inflammation from a breaking upstream
                           change (e.g. a yanked package)
**liver function test**    the overall hepatic_health_score — an inverted
                           aggregate where higher is healthier
=========================  ===================================================

Toxin categories
----------------

1. **stale_dependencies** — pinned or installed packages whose latest
   release is more than N minor versions or M months ahead.
2. **deprecated_api_usage** — calls to functions / classes decorated
   with ``@deprecated`` or ``DeprecationWarning`` in the current tree.
3. **orphan_imports** — ``import`` statements whose target is never
   referenced in the importing file's body (dead imports).
4. **config_drift** — keys in JSON / YAML / TOML configs that no
   running module ever reads.
5. **type_debt** — public functions lacking type annotations, measured
   as a percentage of all public functions.
6. **docstring_decay** — public functions whose docstring is missing,
   empty, or shorter than 20 characters.

Scoring
-------

Each category produces a sub-score 0-100.  The overall hepatic health
score is inverted (100 − toxin_score) so that higher is healthier.

========================  ======
category                  weight
========================  ======
stale_dependencies        0.25
deprecated_api_usage      0.20
orphan_imports            0.15
config_drift              0.15
type_debt                 0.15
docstring_decay           0.10
========================  ======

A toxin_score above 60 triggers a ``cirrhosis`` warning; above 80 is
``acute_hepatitis``.
"""

from __future__ import annotations

import ast
import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    yaml = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ToxinSignal:
    """One category of technical-debt toxin."""

    name: str
    score: float  # 0-100, higher = more toxic
    weight: float
    evidence: str = ""
    items: List[str] = field(default_factory=list)


@dataclass
class HepaticReport:
    """Full hepatic health report for the repository."""

    toxin_score: float  # 0-100, weighted aggregate
    health_score: float  # 100 - toxin_score
    hepatic_state: str  # healthy | stressed | cirrhosis | acute_hepatitis
    primary_toxin: str
    signals: List[ToxinSignal] = field(default_factory=list)
    recommendation: str = ""
    files_scanned: int = 0
    py_files_scanned: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_repo_root() -> Path:
    """Walk upward from CWD to find .git."""
    p = Path.cwd()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return parent
    return p


def _iter_py_files(root: Path, exclude: Optional[List[str]] = None) -> List[Path]:
    """Collect all .py files under *root*, honouring exclude patterns."""
    exclude = exclude or []
    py_files: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # prune excluded dirs
        dirnames[:] = [d for d in dirnames if d not in exclude and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".py"):
                py_files.append(Path(dirpath) / fn)
    return py_files


# ---------------------------------------------------------------------------
# Individual toxin analysers
# ---------------------------------------------------------------------------

def detect_stale_dependencies(root: Path) -> ToxinSignal:
    """Scan requirements*.txt and pyproject.toml for pinned deps.

    Heuristic: a dependency pinned with ``==`` is considered stale if
    the version string is older-style (fewer than 3 segments is not
    penalised, but ``==0.*`` or ``==1.0`` when the ecosystem has moved
    on is flagged).  Without network access we cannot check PyPI, so
    we count the *proportion* of hard-pinned deps as a proxy for
    staleness risk — repos that pin everything tightly tend to lag.
    """
    stale_candidates: List[str] = []
    total_deps = 0

    # requirements*.txt
    for req_file in root.glob("requirements*.txt"):
        try:
            lines = req_file.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            total_deps += 1
            if "==" in line:
                ver_part = line.split("==")[-1].strip()
                # very low version numbers often indicate staleness
                segments = ver_part.split(".")
                if len(segments) <= 2:
                    stale_candidates.append(line)

    # pyproject.toml (PEP 621)
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(errors="replace"))
            deps = data.get("project", {}).get("dependencies", [])
            for dep in deps:
                total_deps += 1
                if "==" in str(dep):
                    stale_candidates.append(str(dep))
        except Exception:
            pass

    if total_deps == 0:
        return ToxinSignal(
            name="stale_dependencies", score=0.0, weight=0.25,
            evidence="no dependency files found",
        )
    ratio = len(stale_candidates) / total_deps
    score = min(100.0, ratio * 100.0)
    return ToxinSignal(
        name="stale_dependencies",
        score=round(score, 2),
        weight=0.25,
        evidence=f"{len(stale_candidates)}/{total_deps} deps tightly pinned",
        items=stale_candidates[:20],
    )


def detect_deprecated_api_usage(root: Path, py_files: List[Path]) -> ToxinSignal:
    """Look for ``@deprecated`` decorators and ``DeprecationWarning`` usage."""
    deprecated_items: List[str] = []
    total_funcs = 0

    for pyf in py_files:
        try:
            source = pyf.read_text(errors="replace")
        except OSError:
            continue
        try:
            tree = ast.parse(source, filename=str(pyf))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                total_funcs += 1
                for dec in node.decorator_list:
                    dec_name = ""
                    if isinstance(dec, ast.Name):
                        dec_name = dec.id
                    elif isinstance(dec, ast.Attribute):
                        dec_name = dec.attr
                    elif isinstance(dec, ast.Call):
                        if isinstance(dec.func, ast.Name):
                            dec_name = dec.func.id
                        elif isinstance(dec.func, ast.Attribute):
                            dec_name = dec.func.attr
                    if "deprecat" in dec_name.lower():
                        rel = str(pyf.relative_to(root))
                        deprecated_items.append(f"{rel}:{node.lineno} {node.name}")

            # Also flag raise DeprecationWarning
            if isinstance(node, ast.Raise) and node.exc:
                exc_name = ""
                if isinstance(node.exc, ast.Call):
                    if isinstance(node.exc.func, ast.Name):
                        exc_name = node.exc.func.id
                elif isinstance(node.exc, ast.Name):
                    exc_name = node.exc.id
                if "DeprecationWarning" in exc_name:
                    rel = str(pyf.relative_to(root))
                    deprecated_items.append(f"{rel}:{node.lineno} raise DeprecationWarning")

    if total_funcs == 0:
        return ToxinSignal(
            name="deprecated_api_usage", score=0.0, weight=0.20,
            evidence="no functions found",
        )
    ratio = len(deprecated_items) / max(total_funcs, 1)
    score = min(100.0, ratio * 500.0)  # amplify — even a few is significant
    return ToxinSignal(
        name="deprecated_api_usage",
        score=round(score, 2),
        weight=0.20,
        evidence=f"{len(deprecated_items)} deprecated markers in {total_funcs} functions",
        items=deprecated_items[:20],
    )


def detect_orphan_imports(root: Path, py_files: List[Path]) -> ToxinSignal:
    """Find import statements whose names are never used in the file body."""
    orphan_items: List[str] = []
    total_imports = 0

    for pyf in py_files:
        try:
            source = pyf.read_text(errors="replace")
        except OSError:
            continue
        try:
            tree = ast.parse(source, filename=str(pyf))
        except SyntaxError:
            continue

        imported_names: List[tuple] = []  # (name, lineno)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    imported_names.append((name, node.lineno))
                    total_imports += 1
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.asname or alias.name
                    imported_names.append((name, node.lineno))
                    total_imports += 1

        # check usage in the rest of the file (excluding the import lines)
        body_source = ""
        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                body_source += ast.unparse(node) + "\n"

        for name, lineno in imported_names:
            # simple word-boundary check
            if not re.search(rf"\b{re.escape(name)}\b", body_source):
                # __all__ re-exports and __future__ are legitimate
                if name.startswith("__"):
                    continue
                rel = str(pyf.relative_to(root))
                orphan_items.append(f"{rel}:{lineno} import '{name}' unused")

    if total_imports == 0:
        return ToxinSignal(
            name="orphan_imports", score=0.0, weight=0.15,
            evidence="no imports found",
        )
    ratio = len(orphan_items) / total_imports
    score = min(100.0, ratio * 200.0)
    return ToxinSignal(
        name="orphan_imports",
        score=round(score, 2),
        weight=0.15,
        evidence=f"{len(orphan_items)}/{total_imports} imports unused",
        items=orphan_items[:30],
    )


def detect_config_drift(root: Path) -> ToxinSignal:
    """Find config keys in JSON/YAML/TOML that no .py file references."""
    config_keys: List[str] = []
    drift_items: List[str] = []

    # collect config keys from JSON files
    for jf in root.rglob("*.json"):
        if ".git" in str(jf) or "node_modules" in str(jf):
            continue
        try:
            data = json.loads(jf.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            for k in data:
                config_keys.append(k)

    # collect config keys from TOML
    for tf in root.rglob("*.toml"):
        if ".git" in str(tf):
            continue
        try:
            data = tomllib.loads(tf.read_text(errors="replace"))
            if isinstance(data, dict):
                for k in data:
                    config_keys.append(k)
        except Exception:
            continue

    # collect config keys from YAML
    if yaml is not None:
        for yf in root.rglob("*.yml"):
            if ".git" in str(yf):
                continue
            try:
                data = yaml.safe_load(yf.read_text(errors="replace"))
                if isinstance(data, dict):
                    for k in data:
                        config_keys.append(k)
            except Exception:
                continue

    if not config_keys:
        return ToxinSignal(
            name="config_drift", score=0.0, weight=0.15,
            evidence="no config files found",
        )

    # scan all .py files for references to these keys
    all_py_source = ""
    for pyf in _iter_py_files(root, exclude=[".git", "node_modules", "__pycache__"]):
        try:
            all_py_source += pyf.read_text(errors="replace")
        except OSError:
            continue

    for key in config_keys:
        if key not in all_py_source:
            drift_items.append(key)

    ratio = len(drift_items) / max(len(config_keys), 1)
    score = min(100.0, ratio * 100.0)
    return ToxinSignal(
        name="config_drift",
        score=round(score, 2),
        weight=0.15,
        evidence=f"{len(drift_items)}/{len(config_keys)} config keys unreferenced",
        items=drift_items[:20],
    )


def detect_type_debt(root: Path, py_files: List[Path]) -> ToxinSignal:
    """Measure the proportion of public functions without type annotations."""
    untyped_funcs: List[str] = []
    total_public = 0

    for pyf in py_files:
        try:
            source = pyf.read_text(errors="replace")
        except OSError:
            continue
        try:
            tree = ast.parse(source, filename=str(pyf))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                total_public += 1
                # check return annotation and at least one arg annotation
                has_return = node.returns is not None
                arg_annotations = [
                    a for a in node.args.args
                    if a.arg != "self" and a.arg != "cls" and a.annotation is not None
                ]
                non_self_args = [
                    a for a in node.args.args
                    if a.arg != "self" and a.arg != "cls"
                ]
                if not has_return and not arg_annotations and non_self_args:
                    rel = str(pyf.relative_to(root))
                    untyped_funcs.append(f"{rel}:{node.lineno} {node.name}()")

    if total_public == 0:
        return ToxinSignal(
            name="type_debt", score=0.0, weight=0.15,
            evidence="no public functions found",
        )
    ratio = len(untyped_funcs) / total_public
    score = min(100.0, ratio * 100.0)
    return ToxinSignal(
        name="type_debt",
        score=round(score, 2),
        weight=0.15,
        evidence=f"{len(untyped_funcs)}/{total_public} public functions lack type hints",
        items=untyped_funcs[:20],
    )


def detect_docstring_decay(root: Path, py_files: List[Path]) -> ToxinSignal:
    """Measure public functions with missing or trivially short docstrings."""
    decayed: List[str] = []
    total_public = 0

    for pyf in py_files:
        try:
            source = pyf.read_text(errors="replace")
        except OSError:
            continue
        try:
            tree = ast.parse(source, filename=str(pyf))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                total_public += 1
                docstring = ast.get_docstring(node)
                if not docstring or len(docstring.strip()) < 20:
                    rel = str(pyf.relative_to(root))
                    decayed.append(f"{rel}:{node.lineno} {node.name}()")

    if total_public == 0:
        return ToxinSignal(
            name="docstring_decay", score=0.0, weight=0.10,
            evidence="no public functions found",
        )
    ratio = len(decayed) / total_public
    score = min(100.0, ratio * 100.0)
    return ToxinSignal(
        name="docstring_decay",
        score=round(score, 2),
        weight=0.10,
        evidence=f"{len(decayed)}/{total_public} public functions lack docstrings",
        items=decayed[:20],
    )


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

_STATES = [
    (80, "acute_hepatitis"),
    (60, "cirrhosis"),
    (30, "stressed"),
    (0, "healthy"),
]


def _classify(score: float) -> str:
    for threshold, state in _STATES:
        if score >= threshold:
            return state
    return "healthy"


_RECOMMENDATIONS = {
    "acute_hepatitis": (
        "urgent: the repository's tech-debt toxin load is critically high. "
        "Schedule a detoxification sprint — update pinned dependencies, remove "
        "deprecated API calls, and add type annotations to the most-called "
        "public functions."
    ),
    "cirrhosis": (
        "warning: chronic tech-debt accumulation is impairing evolvability. "
        "Prioritise dependency updates and orphan-import cleanup over the "
        "next two caretaker visits."
    ),
    "stressed": (
        "mild stress detected. Consider adding docstrings and type hints "
        "during the next feature pass — no emergency, but don't let it slide."
    ),
    "healthy": (
        "hepatic function nominal. Keep up regular maintenance and review "
        "dependency freshness during each caretaker visit."
    ),
}


def analyze_hepatic(
    root: Optional[Path] = None,
    exclude: Optional[List[str]] = None,
) -> HepaticReport:
    """Run all hepatic toxin analysers and return an aggregate report."""
    root = root or _find_repo_root()
    exclude = exclude or [".git", "node_modules", "__pycache__", ".pytest_cache"]
    py_files = _iter_py_files(root, exclude=exclude)

    signals = [
        detect_stale_dependencies(root),
        detect_deprecated_api_usage(root, py_files),
        detect_orphan_imports(root, py_files),
        detect_config_drift(root),
        detect_type_debt(root, py_files),
        detect_docstring_decay(root, py_files),
    ]

    total_weight = sum(s.weight for s in signals)
    if total_weight == 0:
        total_weight = 1.0
    toxin_score = sum(s.score * s.weight for s in signals) / total_weight
    toxin_score = round(min(100.0, max(0.0, toxin_score)), 2)
    health_score = round(100.0 - toxin_score, 2)
    state = _classify(toxin_score)

    primary = max(signals, key=lambda s: s.score * s.weight)
    recommendation = _RECOMMENDATIONS[state]

    return HepaticReport(
        toxin_score=toxin_score,
        health_score=health_score,
        hepatic_state=state,
        primary_toxin=primary.name,
        signals=signals,
        recommendation=recommendation,
        files_scanned=len(list(root.rglob("*"))),
        py_files_scanned=len(py_files),
    )


def hepatic_summary(report: HepaticReport) -> str:
    """One-line human-readable summary."""
    if report.hepatic_state == "healthy":
        return (
            f"healthy: health_score={report.health_score}, "
            f"no toxin categories elevated"
        )
    return (
        f"{report.hepatic_state}: "
        f"toxin_score={report.toxin_score}, "
        f"health={report.health_score}, "
        f"primary={report.primary_toxin}, "
        f"{report.py_files_scanned} py files scanned"
    )


if __name__ == "__main__":
    report = analyze_hepatic()
    print(hepatic_summary(report))
    for s in report.signals:
        print(f"  {s.name}: {s.score} (w={s.weight}) — {s.evidence}")
    print(f"\nRecommendation: {report.recommendation}")
