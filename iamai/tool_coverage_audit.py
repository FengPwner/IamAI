"""tool_coverage_audit — check whether every CLI tool has a module and test.

this repo accumulates tools fast. every caretaker visit might add a new
monitoring script to tools/. but a tool without a backing iamai module
is just a shell script with no testable core. and a module without a
test is unverified logic waiting to break silently.

this module answers three questions:

  1. which CLI tools in tools/ have a matching iamai/ module?
  2. which iamai/ modules have a matching test in tests/?
  3. what is the overall coverage ratio?

categories per tool:

  FULL      — CLI exists, iamai module exists, test exists
  NO_TEST   — CLI exists, iamai module exists, but no test
  NO_MODULE — CLI exists as standalone script, no iamai module
  ORPHAN    — iamai module exists but no CLI wrapper (not necessarily
              bad — some modules are library-only)

the audit produces a ToolCoverageReport with per-tool classification,
overall ratios, and a severity verdict:

  HEALTHY    coverage_ratio >= 0.80 and no_test_count <= 5
  ADEQUATE   coverage_ratio >= 0.60 and no_test_count <= 15
  THIN       coverage_ratio >= 0.40
  FRAGILE    everything else

usage::

    from iamai.tool_coverage_audit import audit

    report = audit()
    print(report.verdict)           # "HEALTHY" / "ADEQUATE" / etc.
    print(report.coverage_ratio)    # 0.73
    for gap in report.no_test:
        print(f"  needs test: {gap}")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Sequence

REPO = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO / "tools"
IAMAI_DIR = REPO / "iamai"
TESTS_DIR = REPO / "tests"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _cli_tool_stems() -> list[str]:
    """Return stems of Python CLI tools in tools/ (excluding tests)."""
    if not TOOLS_DIR.is_dir():
        return []
    stems = []
    for p in sorted(TOOLS_DIR.iterdir()):
        if p.suffix == ".py" and not p.name.startswith("test_"):
            stems.append(p.stem)
    return stems


def _iamai_module_stems() -> list[str]:
    """Return stems of Python modules in iamai/."""
    if not IAMAI_DIR.is_dir():
        return []
    stems = []
    for p in sorted(IAMAI_DIR.iterdir()):
        if p.suffix == ".py" and p.name != "__init__.py":
            stems.append(p.stem)
    return stems


def _test_stems() -> list[str]:
    """Return stems of test files in tests/."""
    if not TESTS_DIR.is_dir():
        return []
    stems = []
    for p in sorted(TESTS_DIR.iterdir()):
        if p.suffix == ".py" and p.name.startswith("test_"):
            stems.append(p.stem)
    return stems


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------

@dataclass
class ToolEntry:
    name: str
    has_cli: bool = False
    has_module: bool = False
    has_test: bool = False

    @property
    def category(self) -> str:
        if self.has_cli and self.has_module and self.has_test:
            return "FULL"
        if self.has_cli and self.has_module and not self.has_test:
            return "NO_TEST"
        if self.has_cli and not self.has_module:
            return "NO_MODULE"
        if self.has_module and not self.has_cli:
            return "ORPHAN"
        return "UNKNOWN"


def classify_tools(
    cli_stems: Sequence[str] = (),
    module_stems: Sequence[str] = (),
    test_stems: Sequence[str] = (),
) -> list[ToolEntry]:
    """Classify every known tool name into a coverage category."""
    all_names = sorted(set(cli_stems) | set(module_stems))
    entries = []
    cli_set = set(cli_stems)
    mod_set = set(module_stems)
    test_set = set(test_stems)

    for name in all_names:
        entry = ToolEntry(
            name=name,
            has_cli=name in cli_set,
            has_module=name in mod_set,
            has_test=f"test_{name}" in test_set or name in test_set,
        )
        entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

@dataclass
class ToolCoverageReport:
    total_tools: int = 0
    total_modules: int = 0
    total_tests: int = 0
    full_count: int = 0
    no_test_count: int = 0
    no_module_count: int = 0
    orphan_count: int = 0
    coverage_ratio: float = 0.0
    verdict: str = "UNKNOWN"
    entries: list[ToolEntry] = field(default_factory=list)

    @property
    def full(self) -> list[str]:
        return [e.name for e in self.entries if e.category == "FULL"]

    @property
    def no_test(self) -> list[str]:
        return [e.name for e in self.entries if e.category == "NO_TEST"]

    @property
    def no_module(self) -> list[str]:
        return [e.name for e in self.entries if e.category == "NO_MODULE"]

    @property
    def orphan(self) -> list[str]:
        return [e.name for e in self.entries if e.category == "ORPHAN"]


def _compute_verdict(ratio: float, no_test_count: int) -> str:
    if ratio >= 0.80 and no_test_count <= 5:
        return "HEALTHY"
    if ratio >= 0.60 and no_test_count <= 15:
        return "ADEQUATE"
    if ratio >= 0.40:
        return "THIN"
    return "FRAGILE"


def audit(
    tools_dir: Path | None = None,
    iamai_dir: Path | None = None,
    tests_dir: Path | None = None,
) -> ToolCoverageReport:
    """Run the full coverage audit and return a report."""
    t_dir = tools_dir or TOOLS_DIR
    i_dir = iamai_dir or IAMAI_DIR
    te_dir = tests_dir or TESTS_DIR

    # gather stems
    cli_stems = []
    if t_dir.is_dir():
        for p in sorted(t_dir.iterdir()):
            if p.suffix == ".py" and not p.name.startswith("test_"):
                cli_stems.append(p.stem)

    mod_stems = []
    if i_dir.is_dir():
        for p in sorted(i_dir.iterdir()):
            if p.suffix == ".py" and p.name != "__init__.py":
                mod_stems.append(p.stem)

    test_stems = []
    if te_dir.is_dir():
        for p in sorted(te_dir.iterdir()):
            if p.suffix == ".py" and p.name.startswith("test_"):
                test_stems.append(p.stem)

    entries = classify_tools(cli_stems, mod_stems, test_stems)

    full_count = sum(1 for e in entries if e.category == "FULL")
    no_test_count = sum(1 for e in entries if e.category == "NO_TEST")
    no_module_count = sum(1 for e in entries if e.category == "NO_MODULE")
    orphan_count = sum(1 for e in entries if e.category == "ORPHAN")

    total_cli = len(cli_stems)
    covered = full_count + no_test_count  # cli tools with a backing module
    ratio = covered / total_cli if total_cli > 0 else 0.0

    return ToolCoverageReport(
        total_tools=total_cli,
        total_modules=len(mod_stems),
        total_tests=len(test_stems),
        full_count=full_count,
        no_test_count=no_test_count,
        no_module_count=no_module_count,
        orphan_count=orphan_count,
        coverage_ratio=round(ratio, 4),
        verdict=_compute_verdict(ratio, no_test_count),
        entries=entries,
    )


def format_report(report: ToolCoverageReport) -> str:
    """Human-readable summary."""
    lines = [
        "=== Tool Coverage Audit ===",
        f"CLI tools:    {report.total_tools}",
        f"iamai modules: {report.total_modules}",
        f"test files:    {report.total_tests}",
        "",
        f"FULL coverage:  {report.full_count}",
        f"NO_TEST:        {report.no_test_count}",
        f"NO_MODULE:      {report.no_module_count}",
        f"ORPHAN:         {report.orphan_count}",
        "",
        f"coverage ratio: {report.coverage_ratio:.2%}",
        f"verdict:        {report.verdict}",
    ]
    if report.no_test:
        lines.append("")
        lines.append("tools missing tests:")
        for name in report.no_test[:10]:
            lines.append(f"  - {name}")
        if len(report.no_test) > 10:
            lines.append(f"  ... and {len(report.no_test) - 10} more")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    report = audit()
    print(format_report(report))
