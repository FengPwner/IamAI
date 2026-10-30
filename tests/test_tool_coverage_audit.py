"""Tests for tool_coverage_audit — coverage completeness checker."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.tool_coverage_audit import (
    ToolEntry,
    ToolCoverageReport,
    classify_tools,
    _compute_verdict,
    audit,
    format_report,
)


# ---------------------------------------------------------------------------
# ToolEntry.category
# ---------------------------------------------------------------------------

class TestToolEntryCategory:
    def test_full_coverage(self):
        e = ToolEntry(name="foo", has_cli=True, has_module=True, has_test=True)
        assert e.category == "FULL"

    def test_no_test(self):
        e = ToolEntry(name="foo", has_cli=True, has_module=True, has_test=False)
        assert e.category == "NO_TEST"

    def test_no_module(self):
        e = ToolEntry(name="foo", has_cli=True, has_module=False, has_test=False)
        assert e.category == "NO_MODULE"

    def test_orphan(self):
        e = ToolEntry(name="foo", has_cli=False, has_module=True, has_test=False)
        assert e.category == "ORPHAN"

    def test_full_overrides_other_flags(self):
        """If all three are true, category is FULL regardless."""
        e = ToolEntry(name="x", has_cli=True, has_module=True, has_test=True)
        assert e.category == "FULL"


# ---------------------------------------------------------------------------
# classify_tools
# ---------------------------------------------------------------------------

class TestClassifyTools:
    def test_empty_inputs(self):
        result = classify_tools([], [], [])
        assert result == []

    def test_single_full_tool(self):
        result = classify_tools(
            cli_stems=["push_lag"],
            module_stems=["push_lag"],
            test_stems=["test_push_lag"],
        )
        assert len(result) == 1
        assert result[0].category == "FULL"
        assert result[0].name == "push_lag"

    def test_no_test_detected(self):
        result = classify_tools(
            cli_stems=["stall_probe"],
            module_stems=["stall_probe"],
            test_stems=[],
        )
        assert result[0].category == "NO_TEST"

    def test_no_module_detected(self):
        result = classify_tools(
            cli_stems=["orphan_script"],
            module_stems=[],
            test_stems=[],
        )
        assert result[0].category == "NO_MODULE"

    def test_orphan_module_detected(self):
        result = classify_tools(
            cli_stems=[],
            module_stems=["lib_only"],
            test_stems=[],
        )
        assert result[0].category == "ORPHAN"

    def test_mixed_classification(self):
        result = classify_tools(
            cli_stems=["alpha", "beta", "gamma"],
            module_stems=["alpha", "beta", "delta"],
            test_stems=["test_alpha"],
        )
        cats = {e.name: e.category for e in result}
        assert cats["alpha"] == "FULL"
        assert cats["beta"] == "NO_TEST"
        assert cats["gamma"] == "NO_MODULE"
        assert cats["delta"] == "ORPHAN"

    def test_sorted_output(self):
        result = classify_tools(
            cli_stems=["z_tool", "a_tool"],
            module_stems=["z_tool", "a_tool"],
            test_stems=[],
        )
        names = [e.name for e in result]
        assert names == sorted(names)

    def test_deduplication(self):
        """Same name in cli and module should produce one entry."""
        result = classify_tools(
            cli_stems=["dup"],
            module_stems=["dup"],
            test_stems=["test_dup"],
        )
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _compute_verdict
# ---------------------------------------------------------------------------

class TestComputeVerdict:
    def test_healthy(self):
        assert _compute_verdict(0.90, 3) == "HEALTHY"

    def test_healthy_boundary(self):
        assert _compute_verdict(0.80, 5) == "HEALTHY"

    def test_adequate(self):
        assert _compute_verdict(0.65, 10) == "ADEQUATE"

    def test_adequate_boundary(self):
        assert _compute_verdict(0.60, 15) == "ADEQUATE"

    def test_thin(self):
        assert _compute_verdict(0.45, 20) == "THIN"

    def test_thin_boundary(self):
        assert _compute_verdict(0.40, 100) == "THIN"

    def test_fragile(self):
        assert _compute_verdict(0.30, 50) == "FRAGILE"

    def test_zero_ratio_fragile(self):
        assert _compute_verdict(0.0, 0) == "FRAGILE"

    def test_high_ratio_many_no_test_is_not_healthy(self):
        """High coverage but too many untested modules drops verdict."""
        assert _compute_verdict(0.85, 10) == "ADEQUATE"


# ---------------------------------------------------------------------------
# audit (integration with temp dirs)
# ---------------------------------------------------------------------------

class TestAudit:
    def test_audit_with_temp_dirs(self, tmp_path):
        tools = tmp_path / "tools"
        tools.mkdir()
        iamai = tmp_path / "iamai"
        iamai.mkdir()
        tests = tmp_path / "tests"
        tests.mkdir()

        # create CLI tools
        (tools / "alpha.py").write_text("# cli")
        (tools / "beta.py").write_text("# cli")
        (tools / "gamma.py").write_text("# cli")

        # create iamai modules
        (iamai / "__init__.py").write_text("")
        (iamai / "alpha.py").write_text("# mod")
        (iamai / "beta.py").write_text("# mod")

        # create tests
        (tests / "test_alpha.py").write_text("# test")

        report = audit(tools_dir=tools, iamai_dir=iamai, tests_dir=tests)

        assert report.total_tools == 3
        assert report.total_modules == 2
        assert report.total_tests == 1
        assert report.full_count == 1      # alpha
        assert report.no_test_count == 1    # beta
        assert report.no_module_count == 1  # gamma
        assert report.coverage_ratio == pytest.approx(2 / 3, abs=0.01)

    def test_audit_empty_dirs(self, tmp_path):
        tools = tmp_path / "tools"
        tools.mkdir()
        iamai = tmp_path / "iamai"
        iamai.mkdir()
        tests = tmp_path / "tests"
        tests.mkdir()

        report = audit(tools_dir=tools, iamai_dir=iamai, tests_dir=tests)
        assert report.total_tools == 0
        assert report.coverage_ratio == 0.0
        assert report.verdict == "FRAGILE"

    def test_audit_skips_test_files_in_tools(self, tmp_path):
        """test_*.py in tools/ should not be counted as CLI tools."""
        tools = tmp_path / "tools"
        tools.mkdir()
        iamai = tmp_path / "iamai"
        iamai.mkdir()
        tests = tmp_path / "tests"
        tests.mkdir()

        (tools / "real_tool.py").write_text("# cli")
        (tools / "test_something.py").write_text("# test in tools")

        report = audit(tools_dir=tools, iamai_dir=iamai, tests_dir=tests)
        assert report.total_tools == 1
        assert report.entries[0].name == "real_tool"


# ---------------------------------------------------------------------------
# ToolCoverageReport properties
# ---------------------------------------------------------------------------

class TestReportProperties:
    def _make_report(self):
        entries = [
            ToolEntry("a", True, True, True),
            ToolEntry("b", True, True, False),
            ToolEntry("c", True, False, False),
            ToolEntry("d", False, True, False),
        ]
        return ToolCoverageReport(
            total_tools=3,
            total_modules=3,
            total_tests=1,
            full_count=1,
            no_test_count=1,
            no_module_count=1,
            orphan_count=1,
            coverage_ratio=0.6667,
            verdict="ADEQUATE",
            entries=entries,
        )

    def test_full_list(self):
        r = self._make_report()
        assert r.full == ["a"]

    def test_no_test_list(self):
        r = self._make_report()
        assert r.no_test == ["b"]

    def test_no_module_list(self):
        r = self._make_report()
        assert r.no_module == ["c"]

    def test_orphan_list(self):
        r = self._make_report()
        assert r.orphan == ["d"]


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_contains_verdict(self):
        report = ToolCoverageReport(verdict="HEALTHY", coverage_ratio=0.95)
        text = format_report(report)
        assert "HEALTHY" in text
        assert "95.00%" in text

    def test_lists_no_test_tools(self):
        entries = [
            ToolEntry("push_lag", True, True, False),
            ToolEntry("stall_probe", True, True, True),
        ]
        report = ToolCoverageReport(
            no_test_count=1,
            entries=entries,
        )
        text = format_report(report)
        assert "push_lag" in text
        assert "stall_probe" not in text

    def test_truncates_long_no_test_list(self):
        entries = [
            ToolEntry(f"tool_{i}", True, True, False) for i in range(15)
        ]
        report = ToolCoverageReport(no_test_count=15, entries=entries)
        text = format_report(report)
        assert "and 5 more" in text


# ---------------------------------------------------------------------------
# real-repo sanity check
# ---------------------------------------------------------------------------

class TestRealRepo:
    def test_real_repo_runs_without_error(self):
        """Audit should run on the actual repo and produce a verdict."""
        report = audit()
        assert report.verdict in ("HEALTHY", "ADEQUATE", "THIN", "FRAGILE")
        assert report.total_tools > 0
        assert report.total_modules > 0
        assert 0.0 <= report.coverage_ratio <= 1.0
