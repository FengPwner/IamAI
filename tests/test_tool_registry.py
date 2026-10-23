#!/usr/bin/env python3
"""Tests for tools/tool_registry.py — catalogue and classify repo tools."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ensure tools/ is importable
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import tool_registry as tr  # noqa: E402


# ── fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def fake_tools(tmp_path):
    """Create a temporary tools/ directory with stub .py files."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()

    stubs = {
        "stall_classifier.py": '"""Diagnose writer stalls from state data."""\n',
        "stall_cluster_detector.py": '"""Detect clusters of stall events."""\n',
        "stall_probe.py": '"""Lightweight stall probe — exits 1 on stall."""\n',
        "commit_freshness.py": '"""How fresh is the latest commit?"""\n',
        "commit_gap_classifier.py": '"""Classify commit gaps into categories."""\n',
        "push_lag.py": '"""Measure push lag in seconds."""\n',
        "push_gate.py": '"""Pre-push gate — blocks push when unhealthy."""\n',
        "heartbeat.py": '"""Is the writer still writing? One-line health check."""\n',
        "tool_registry.py": '"""Catalogue tools by category."""\n',
        "__init__.py": "",  # should be skipped
        "broken_syntax.py": "def broken(:\n  pass\n",  # malformed
        "no_docstring.py": "# just a comment\nx = 1\n",
    }

    for name, content in stubs.items():
        (tools_dir / name).write_text(content, encoding="utf-8")

    return tools_dir


# ── extract_docstring ─────────────────────────────────────────────────

class TestExtractDocstring:
    def test_normal_docstring(self, fake_tools):
        result = tr.extract_docstring(fake_tools / "stall_classifier.py")
        assert "Diagnose writer stalls" in result

    def test_empty_on_syntax_error(self, fake_tools):
        result = tr.extract_docstring(fake_tools / "broken_syntax.py")
        assert result == ""

    def test_empty_on_no_docstring(self, fake_tools):
        result = tr.extract_docstring(fake_tools / "no_docstring.py")
        assert result == ""

    def test_first_line_only(self, tmp_path):
        f = tmp_path / "multi.py"
        f.write_text('"""First line.\nSecond line.\nThird line."""\n', encoding="utf-8")
        result = tr.extract_docstring(f)
        assert result == "First line."
        assert "Second" not in result

    def test_strips_em_dash(self, tmp_path):
        f = tmp_path / "dash.py"
        f.write_text('"""Some tool — detailed description."""\n', encoding="utf-8")
        result = tr.extract_docstring(f)
        assert "—" not in result
        assert "Some tool" in result


# ── classify ──────────────────────────────────────────────────────────

class TestClassify:
    def test_stall_keywords(self):
        assert tr.classify("stall_classifier") == "stall"
        assert tr.classify("writer_silence_detector") == "stall"
        assert tr.classify("deadman_switch") == "stall"
        assert tr.classify("stuck_gate_detector") == "stall"

    def test_process_keywords(self):
        assert tr.classify("process_reclaim_detector") == "process"
        assert tr.classify("stale_pid_detector") == "process"
        assert tr.classify("restart_audit") == "process"

    def test_commit_keywords(self):
        assert tr.classify("commit_freshness") == "commit"
        assert tr.classify("commit_gap_classifier") == "commit"
        assert tr.classify("commit_density") == "commit"

    def test_push_keywords(self):
        assert tr.classify("push_lag") == "push"
        assert tr.classify("push_gate") == "push"
        assert tr.classify("pre_push_sync") == "push"

    def test_stroke_keywords(self):
        assert tr.classify("stroke_diversity") == "stroke"
        assert tr.classify("stroke_novelty") == "stroke"
        assert tr.classify("stroke_pacer") == "stroke"

    def test_health_keywords(self):
        assert tr.classify("repo_triage") == "health"
        assert tr.classify("repo_pulse") == "health"
        assert tr.classify("writer_vitality") == "health"

    def test_caretaker_keywords(self):
        assert tr.classify("caretaker_briefing") == "caretaker"
        assert tr.classify("caretaker_dashboard") == "caretaker"
        assert tr.classify("visit_continuity_scorer") == "caretaker"

    def test_backlog_keywords(self):
        assert tr.classify("backlog_monitor") == "backlog"
        assert tr.classify("uncommitted_bytes") == "backlog"

    def test_meta_keywords(self):
        assert tr.classify("tool_registry") == "meta"
        assert tr.classify("session_summary") == "meta"

    def test_unknown_goes_to_other(self):
        assert tr.classify("totally_random_thing") == "other"

    def test_first_match_wins(self):
        # caretaker_ appears before stall in rules, so caretaker wins
        assert tr.classify("caretaker_stall_helper") == "caretaker"


# ── scan_tools ────────────────────────────────────────────────────────

class TestScanTools:
    def test_scans_all_py_files(self, fake_tools):
        records = tr.scan_tools(fake_tools)
        names = [r["name"] for r in records]
        assert "stall_classifier" in names
        assert "heartbeat" in names
        assert "tool_registry" in names

    def test_skips_dunder_init(self, fake_tools):
        records = tr.scan_tools(fake_tools)
        names = [r["name"] for r in records]
        assert "__init__" not in names

    def test_each_record_has_required_fields(self, fake_tools):
        records = tr.scan_tools(fake_tools)
        for r in records:
            assert "name" in r
            assert "file" in r
            assert "category" in r
            assert "docstring" in r

    def test_nonexistent_dir_returns_empty(self, tmp_path):
        result = tr.scan_tools(tmp_path / "nonexistent")
        assert result == []

    def test_broken_syntax_still_scanned(self, fake_tools):
        records = tr.scan_tools(fake_tools)
        broken = [r for r in records if r["name"] == "broken_syntax"]
        assert len(broken) == 1
        assert broken[0]["docstring"] == ""


# ── detect_overlaps ───────────────────────────────────────────────────

class TestDetectOverlaps:
    def test_detects_stall_cluster(self, fake_tools):
        records = tr.scan_tools(fake_tools)
        clusters = tr.detect_overlaps(records)
        # 3 stall tools in the fixture → should appear
        assert any("stall" in topic.lower() for topic in clusters)

    def test_threshold_is_three(self):
        # only 1 push tool → should NOT form a cluster
        records = [{"name": "push_lag", "file": "push_lag.py",
                     "category": "push", "docstring": ""}]
        clusters = tr.detect_overlaps(records)
        assert "push lag" not in clusters

    def test_empty_records(self):
        assert tr.detect_overlaps([]) == {}


# ── formatters ────────────────────────────────────────────────────────

class TestFormatters:
    def test_format_table_contains_header(self, fake_tools):
        records = tr.scan_tools(fake_tools)
        table = tr.format_table(records)
        assert "Tool Registry" in table
        assert str(len(records)) in table

    def test_format_table_groups_by_category(self, fake_tools):
        records = tr.scan_tools(fake_tools)
        table = tr.format_table(records)
        assert "STALL" in table.upper()

    def test_format_overlaps_no_clusters(self):
        result = tr.format_overlaps({})
        assert "No overlap" in result

    def test_format_overlaps_with_clusters(self):
        clusters = {"stall detection": ["stall_a", "stall_b", "stall_c"]}
        result = tr.format_overlaps(clusters)
        assert "stall detection" in result
        assert "stall_a" in result
        assert "3 tools" in result


# ── CLI integration ───────────────────────────────────────────────────

class TestCLI:
    def test_json_output(self, fake_tools):
        with patch("sys.argv", ["tool_registry.py", "--json",
                                "--tools-dir", str(fake_tools)]):
            # capture stdout
            import io
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                rc = tr.main()
            assert rc == 0
            data = json.loads(buf.getvalue())
            assert "total" in data
            assert "tools" in data
            assert data["total"] > 0

    def test_overlaps_only(self, fake_tools):
        with patch("sys.argv", ["tool_registry.py", "--overlaps",
                                "--tools-dir", str(fake_tools)]):
            import io
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                rc = tr.main()
            assert rc == 0
            output = buf.getvalue()
            # should not contain the full table
            assert "Tool Registry" not in output

    def test_bad_dir_exits_1(self, tmp_path):
        with patch("sys.argv", ["tool_registry.py", "--tools-dir",
                                str(tmp_path / "nope")]):
            rc = tr.main()
            assert rc == 1


# ── edge cases ────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_classify_empty_string(self):
        assert tr.classify("") == "other"

    def test_extract_docstring_nonexistent_file(self, tmp_path):
        result = tr.extract_docstring(tmp_path / "ghost.py")
        # should not crash; returns empty or raises — handle gracefully
        assert result == ""

    def test_scan_tools_with_symlinks(self, fake_tools, tmp_path):
        """Symlinked .py files should be scanned like regular files."""
        link = fake_tools / "linked_tool.py"
        target = tmp_path / "real_tool.py"
        target.write_text('"""A real tool via symlink."""\n', encoding="utf-8")
        link.symlink_to(target)
        records = tr.scan_tools(fake_tools)
        names = [r["name"] for r in records]
        assert "linked_tool" in names

    def test_category_counts_match(self, fake_tools):
        records = tr.scan_tools(fake_tools)
        from collections import Counter
        counts = Counter(r["category"] for r in records)
        assert sum(counts.values()) == len(records)


# ── keyword rule integrity ────────────────────────────────────────────

class TestRuleIntegrity:
    def test_all_categories_are_known(self):
        """Every category referenced in KEYWORD_RULES should be valid."""
        valid = {"process", "stall", "commit", "stroke", "push",
                 "backlog", "caretaker", "health", "repo", "meta", "other"}
        for cat, _ in tr.KEYWORD_RULES:
            assert cat in valid, f"Unknown category in rules: {cat}"

    def test_overlap_topics_have_string_keys(self):
        for topic in tr.OVERLAP_TOPICS:
            assert isinstance(topic, str)
            assert len(topic) > 0

    def test_keyword_lists_nonempty(self):
        for cat, kws in tr.KEYWORD_RULES:
            assert len(kws) > 0, f"Empty keyword list for category: {cat}"
