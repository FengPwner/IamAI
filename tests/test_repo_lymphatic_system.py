"""Tests for iamai.repo_lymphatic_system.

Covers: WasteItem, OedemaRegion, LymphaticReport data classes, each
detector function in isolation, composite scoring, oedema detection,
drainage rate computation, CLI entry point, and default definitions.
"""

import json
import os
import subprocess
import tempfile
import textwrap
import time
from pathlib import Path
from unittest import mock

import pytest

from iamai.repo_lymphatic_system import (
    COMMENTED_CODE_MIN_LINES,
    DEFAULT_BRANCH_STALE_DAYS,
    DEFAULT_DIR_OEDEMA_THRESHOLD,
    DEFAULT_OEDEMA_THRESHOLD,
    DEFAULT_STALE_DAYS,
    DEFAULT_WEIGHTS,
    EXEMPT_FUNCTION_NAMES,
    EXEMPT_FUNCTION_PREFIXES,
    LymphaticAnalyzer,
    LymphaticReport,
    OedemaRegion,
    SNIPPET_MIN_LINES,
    VALID_CATEGORIES,
    WasteItem,
    _build_called_set,
    _detect_commented_code,
    _detect_dead_functions,
    _detect_duplicate_snippets,
    _detect_empty_modules,
    _detect_orphan_tests,
    _detect_stale_branches,
    _detect_stale_todos,
    _detect_unused_imports,
    _fingerprint_block,
    _parse_ast,
    _read_lines,
    _repo_files,
    _test_files,
    drainage_rate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_repo(tmp_path):
    """Create a minimal repo layout for testing."""
    iamai_dir = tmp_path / "iamai"
    tests_dir = tmp_path / "tests"
    iamai_dir.mkdir()
    tests_dir.mkdir()
    (iamai_dir / "__init__.py").write_text("")
    return tmp_path


def _write_module(tmp_repo, name, content):
    """Write a Python module into the iamai/ directory."""
    p = tmp_repo / "iamai" / name
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def _write_test(tmp_repo, name, content):
    """Write a test file into the tests/ directory."""
    p = tmp_repo / "tests" / name
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# WasteItem dataclass
# ---------------------------------------------------------------------------

class TestWasteItem:
    def test_to_dict(self):
        item = WasteItem(
            category="unused_import",
            file="iamai/foo.py",
            line=3,
            detail="imported name 'os' not used",
            severity="warning",
        )
        d = item.to_dict()
        assert d["category"] == "unused_import"
        assert d["file"] == "iamai/foo.py"
        assert d["line"] == 3
        assert d["detail"] == "imported name 'os' not used"
        assert d["severity"] == "warning"

    def test_default_severity(self):
        item = WasteItem(category="test", file="f.py", line=1, detail="x")
        assert item.severity == "info"

    def test_round_trip(self):
        item = WasteItem(category="dead_function", file="a.py", line=10,
                         detail="func not called", severity="critical")
        d = item.to_dict()
        item2 = WasteItem(**d)
        assert item == item2


# ---------------------------------------------------------------------------
# OedemaRegion dataclass
# ---------------------------------------------------------------------------

class TestOedemaRegion:
    def test_to_dict_file(self):
        oed = OedemaRegion(path="iamai/big.py", waste_count=12, kind="file")
        d = oed.to_dict()
        assert d["path"] == "iamai/big.py"
        assert d["waste_count"] == 12
        assert d["kind"] == "file"

    def test_to_dict_directory(self):
        oed = OedemaRegion(path="iamai", waste_count=30, kind="directory")
        assert oed.to_dict()["kind"] == "directory"

    def test_default_kind(self):
        oed = OedemaRegion(path="x", waste_count=1)
        assert oed.kind == "file"


# ---------------------------------------------------------------------------
# LymphaticReport dataclass
# ---------------------------------------------------------------------------

class TestLymphaticReport:
    def test_to_dict(self):
        report = LymphaticReport(
            lymphatic_score=78.5,
            total_waste=10,
            items=[WasteItem("unused_import", "a.py", 1, "x")],
            oedema_regions=[],
            category_counts={"unused_import": 1},
            category_scores={"unused_import": 94.0},
            files_scanned=20,
            scan_seconds=0.123,
        )
        d = report.to_dict()
        assert d["lymphatic_score"] == 78.5
        assert d["total_waste"] == 10
        assert len(d["items"]) == 1
        assert d["files_scanned"] == 20
        assert d["scan_seconds"] == 0.123

    def test_empty_report(self):
        report = LymphaticReport(lymphatic_score=100.0, total_waste=0)
        d = report.to_dict()
        assert d["lymphatic_score"] == 100.0
        assert d["items"] == []
        assert d["oedema_regions"] == []


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_repo_files_finds_py(self, tmp_repo):
        _write_module(tmp_repo, "foo.py", "# hello\n")
        _write_module(tmp_repo, "bar.py", "# bar\n")
        files = _repo_files(str(tmp_repo))
        names = {p.name for p in files}
        assert "foo.py" in names
        assert "bar.py" in names
        assert "__init__.py" in names

    def test_repo_files_missing_dir(self, tmp_path):
        # No iamai/ dir.
        assert _repo_files(str(tmp_path)) == []

    def test_test_files(self, tmp_repo):
        _write_test(tmp_repo, "test_foo.py", "# test\n")
        files = _test_files(str(tmp_repo))
        assert any(p.name == "test_foo.py" for p in files)

    def test_test_files_missing(self, tmp_path):
        assert _test_files(str(tmp_path)) == []

    def test_read_lines(self, tmp_path):
        p = tmp_path / "x.py"
        p.write_text("a\nb\nc\n")
        assert _read_lines(p) == ["a", "b", "c"]

    def test_read_lines_missing_file(self, tmp_path):
        assert _read_lines(tmp_path / "nope.py") == []

    def test_parse_ast_valid(self, tmp_path):
        p = tmp_path / "ok.py"
        p.write_text("x = 1\n")
        tree = _parse_ast(p)
        assert tree is not None

    def test_parse_ast_syntax_error(self, tmp_path):
        p = tmp_path / "bad.py"
        p.write_text("def (\n")
        assert _parse_ast(p) is None

    def test_fingerprint_block_ignores_whitespace(self):
        a = ["x = 1", "y = 2", "z = x + y"]
        b = ["x  =  1", "y  =  2", "z  =  x  +  y"]
        assert _fingerprint_block(a) == _fingerprint_block(b)

    def test_fingerprint_block_ignores_comments(self):
        a = ["x = 1", "# comment", "y = 2"]
        b = ["x = 1", "y = 2"]
        assert _fingerprint_block(a) == _fingerprint_block(b)

    def test_fingerprint_block_different_code(self):
        a = ["x = 1", "y = 2"]
        b = ["x = 3", "y = 4"]
        assert _fingerprint_block(a) != _fingerprint_block(b)


# ---------------------------------------------------------------------------
# Detector: unused imports
# ---------------------------------------------------------------------------

class TestDetectUnusedImports:
    def test_unused_import(self, tmp_repo):
        p = _write_module(tmp_repo, "mod_a.py", """\
            import os
            import sys

            def hello():
                print(sys.argv)
        """)
        items = _detect_unused_imports(p, str(tmp_repo))
        names = [it.detail for it in items]
        assert any("'os'" in n for n in names)

    def test_all_imports_used(self, tmp_repo):
        p = _write_module(tmp_repo, "mod_b.py", """\
            import os
            import sys

            print(os.getcwd(), sys.argv)
        """)
        items = _detect_unused_imports(p, str(tmp_repo))
        assert items == []

    def test_from_import_unused(self, tmp_repo):
        p = _write_module(tmp_repo, "mod_c.py", """\
            from pathlib import Path, PurePosixPath

            p = Path(".")
        """)
        items = _detect_unused_imports(p, str(tmp_repo))
        assert any("'PurePosixPath'" in it.detail for it in items)

    def test_from_import_used(self, tmp_repo):
        p = _write_module(tmp_repo, "mod_d.py", """\
            from pathlib import Path

            p = Path(".")
            print(p)
        """)
        items = _detect_unused_imports(p, str(tmp_repo))
        assert items == []

    def test_star_import_ignored(self, tmp_repo):
        p = _write_module(tmp_repo, "mod_e.py", """\
            from os.path import *
            print(join("a", "b"))
        """)
        items = _detect_unused_imports(p, str(tmp_repo))
        # Star imports should not produce false positives.
        assert items == []

    def test_aliased_import(self, tmp_repo):
        p = _write_module(tmp_repo, "mod_f.py", """\
            import numpy as np
            x = np.array([1])
        """)
        items = _detect_unused_imports(p, str(tmp_repo))
        assert items == []

    def test_syntax_error_file(self, tmp_repo):
        p = _write_module(tmp_repo, "broken.py", "def (\nimport os\n")
        items = _detect_unused_imports(p, str(tmp_repo))
        assert items == []  # Should not crash.

    def test_no_imports(self, tmp_repo):
        p = _write_module(tmp_repo, "plain.py", """\
            x = 42
            print(x)
        """)
        items = _detect_unused_imports(p, str(tmp_repo))
        assert items == []


# ---------------------------------------------------------------------------
# Detector: dead functions
# ---------------------------------------------------------------------------

class TestDetectDeadFunctions:
    def test_dead_function(self, tmp_repo):
        p = _write_module(tmp_repo, "tool.py", """\
            def unused_helper():
                return 42

            def used_func():
                return 1

            result = used_func()
        """)
        called = _build_called_set(tmp_repo)
        items = _detect_dead_functions(p, str(tmp_repo), called)
        names = [it.detail for it in items]
        assert any("unused_helper" in n for n in names)
        assert not any("used_func" in n for n in names)

    def test_exempt_functions(self, tmp_repo):
        p = _write_module(tmp_repo, "entry.py", """\
            def main():
                pass

            def __init__():
                pass
        """)
        called = _build_called_set(tmp_repo)
        items = _detect_dead_functions(p, str(tmp_repo), called)
        assert items == []

    def test_test_functions_excluded(self, tmp_repo):
        p = _write_module(tmp_repo, "check.py", """\
            def test_something():
                assert True

            def fixture_data():
                return []
        """)
        called = _build_called_set(tmp_repo)
        items = _detect_dead_functions(p, str(tmp_repo), called)
        assert items == []

    def test_private_functions_excluded(self, tmp_repo):
        p = _write_module(tmp_repo, "priv.py", """\
            def _internal():
                return 1
        """)
        called = _build_called_set(tmp_repo)
        items = _detect_dead_functions(p, str(tmp_repo), called)
        assert items == []

    def test_syntax_error_file(self, tmp_repo):
        p = _write_module(tmp_repo, "bad_syntax.py", "def (\n")
        called = _build_called_set(tmp_repo)
        items = _detect_dead_functions(p, str(tmp_repo), called)
        assert items == []

    def test_called_via_method(self, tmp_repo):
        p = _write_module(tmp_repo, "obj.py", """\
            class MyClass:
                def do_thing(self):
                    return 1

            obj = MyClass()
            obj.do_thing()
        """)
        called = _build_called_set(tmp_repo)
        items = _detect_dead_functions(p, str(tmp_repo), called)
        assert not any("do_thing" in it.detail for it in items)


# ---------------------------------------------------------------------------
# Detector: commented-out code
# ---------------------------------------------------------------------------

class TestDetectCommentedCode:
    def test_commented_block(self, tmp_repo):
        lines = [
            "# real code above",
            "# import os",
            "# x = os.getcwd()",
            "# print(x)",
            "# y = x + 1",
            "# real code below",
            "z = 42",
        ]
        p = _write_module(tmp_repo, "cmt.py", "\n".join(lines) + "\n")
        items = _detect_commented_code(p, str(tmp_repo))
        assert len(items) >= 1
        assert items[0].category == "commented_code"
        assert f"{4}-line" in items[0].detail or "4" in items[0].detail

    def test_short_comment_block_not_flagged(self, tmp_repo):
        lines = [
            "# import os",
            "# x = 1",
            "z = 42",
        ]
        p = _write_module(tmp_repo, "short_cmt.py", "\n".join(lines) + "\n")
        items = _detect_commented_code(p, str(tmp_repo))
        assert items == []

    def test_prose_comments_not_flagged(self, tmp_repo):
        lines = [
            "# This module does things.",
            "# It is very useful.",
            "# See the docs for more.",
            "# End of preamble.",
            "x = 1",
        ]
        p = _write_module(tmp_repo, "prose.py", "\n".join(lines) + "\n")
        items = _detect_commented_code(p, str(tmp_repo))
        assert items == []

    def test_empty_file(self, tmp_repo):
        p = _write_module(tmp_repo, "empty.py", "")
        items = _detect_commented_code(p, str(tmp_repo))
        assert items == []

    def test_trailing_block(self, tmp_repo):
        lines = [
            "x = 1",
            "# import sys",
            "# y = sys.argv",
            "# print(y)",
        ]
        p = _write_module(tmp_repo, "trail.py", "\n".join(lines) + "\n")
        items = _detect_commented_code(p, str(tmp_repo))
        assert len(items) == 1


# ---------------------------------------------------------------------------
# Detector: stale TODOs
# ---------------------------------------------------------------------------

class TestDetectStaleTodos:
    def test_stale_todo(self, tmp_repo):
        p = _write_module(tmp_repo, "todo_mod.py", """\
            # TODO: fix this later
            x = 1
        """)
        # Set mtime to 200 days ago.
        old_time = time.time() - 200 * 86400
        os.utime(p, (old_time, old_time))
        items = _detect_stale_todos(p, str(tmp_repo), stale_days=90)
        assert len(items) == 1
        assert items[0].category == "stale_todo"
        assert "TODO" in items[0].detail

    def test_fresh_todo_not_flagged(self, tmp_repo):
        p = _write_module(tmp_repo, "fresh_todo.py", """\
            # TODO: do this soon
            x = 1
        """)
        # mtime is now — should not be flagged.
        items = _detect_stale_todos(p, str(tmp_repo), stale_days=90)
        assert items == []

    def test_fixme_detected(self, tmp_repo):
        p = _write_module(tmp_repo, "fixme_mod.py", """\
            # FIXME: broken
            x = 1
        """)
        old_time = time.time() - 200 * 86400
        os.utime(p, (old_time, old_time))
        items = _detect_stale_todos(p, str(tmp_repo), stale_days=90)
        assert any("FIXME" in it.detail for it in items)

    def test_hack_detected(self, tmp_repo):
        p = _write_module(tmp_repo, "hack_mod.py", """\
            # HACK: temporary workaround
            x = 1
        """)
        old_time = time.time() - 200 * 86400
        os.utime(p, (old_time, old_time))
        items = _detect_stale_todos(p, str(tmp_repo), stale_days=90)
        assert any("HACK" in it.detail for it in items)

    def test_no_todos(self, tmp_repo):
        p = _write_module(tmp_repo, "clean.py", """\
            # This is clean.
            x = 1
        """)
        items = _detect_stale_todos(p, str(tmp_repo))
        assert items == []


# ---------------------------------------------------------------------------
# Detector: orphan tests
# ---------------------------------------------------------------------------

class TestDetectOrphanTests:
    def test_orphan_detected(self, tmp_repo):
        _write_test(tmp_repo, "test_gone_module.py", "def test_x(): pass\n")
        # gone_module.py does not exist in iamai/.
        items = _detect_orphan_tests(str(tmp_repo))
        assert len(items) == 1
        assert items[0].category == "orphan_test"
        assert "gone_module" in items[0].detail

    def test_matching_module_not_orphan(self, tmp_repo):
        _write_module(tmp_repo, "alive.py", "x = 1\n")
        _write_test(tmp_repo, "test_alive.py", "def test_x(): pass\n")
        items = _detect_orphan_tests(str(tmp_repo))
        assert not any("alive" in it.detail for it in items)

    def test_empty_tests_dir(self, tmp_repo):
        items = _detect_orphan_tests(str(tmp_repo))
        assert items == []

    def test_missing_dirs(self, tmp_path):
        items = _detect_orphan_tests(str(tmp_path))
        assert items == []


# ---------------------------------------------------------------------------
# Detector: empty modules
# ---------------------------------------------------------------------------

class TestDetectEmptyModules:
    def test_empty_file(self, tmp_repo):
        p = _write_module(tmp_repo, "stub.py", "\n")
        items = _detect_empty_modules(p, str(tmp_repo))
        assert len(items) == 1
        assert items[0].category == "empty_module"

    def test_substantive_module_not_flagged(self, tmp_repo):
        p = _write_module(tmp_repo, "real.py", """\
            \"\"\"A real module.\"\"\"

            def compute(x):
                return x * 2

            result = compute(21)
            print(result)
        """)
        items = _detect_empty_modules(p, str(tmp_repo))
        assert items == []

    def test_init_excluded(self, tmp_repo):
        p = tmp_repo / "iamai" / "__init__.py"
        p.write_text("")
        items = _detect_empty_modules(p, str(tmp_repo))
        assert items == []

    def test_docstring_only_module(self, tmp_repo):
        p = _write_module(tmp_repo, "doconly.py", '''\
            """This module exists but has no code yet."""
        ''')
        items = _detect_empty_modules(p, str(tmp_repo))
        # With only a docstring and ≤ 3 non-blank lines, should flag.
        assert len(items) == 1


# ---------------------------------------------------------------------------
# Detector: duplicate snippets
# ---------------------------------------------------------------------------

class TestDetectDuplicateSnippets:
    def test_duplicate_detected(self, tmp_repo):
        snippet = "\n".join(f"x_{i} = {i}" for i in range(15))
        _write_module(tmp_repo, "dup_a.py", snippet + "\n")
        _write_module(tmp_repo, "dup_b.py", snippet + "\n")
        items = _detect_duplicate_snippets(str(tmp_repo))
        assert len(items) >= 1
        assert items[0].category == "duplicate_snippet"

    def test_unique_files_no_duplicate(self, tmp_repo):
        _write_module(tmp_repo, "uniq_a.py", "\n".join(f"a_{i} = {i}" for i in range(15)) + "\n")
        _write_module(tmp_repo, "uniq_b.py", "\n".join(f"b_{i} = {i}" for i in range(15)) + "\n")
        items = _detect_duplicate_snippets(str(tmp_repo))
        assert items == []

    def test_small_files_skipped(self, tmp_repo):
        _write_module(tmp_repo, "tiny.py", "x = 1\n")
        items = _detect_duplicate_snippets(str(tmp_repo))
        assert items == []


# ---------------------------------------------------------------------------
# Detector: stale branches
# ---------------------------------------------------------------------------

class TestDetectStaleBranches:
    def test_stale_branch_detected(self, tmp_repo):
        # Mock git output.
        old_ts = int(time.time()) - 120 * 86400
        fake_output = f"old-feature {old_ts}\n"
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0, stdout=fake_output, stderr="",
            )
            items = _detect_stale_branches(str(tmp_repo), stale_days=60)
            assert len(items) == 1
            assert items[0].category == "stale_branch"
            assert "old-feature" in items[0].detail

    def test_fresh_branch_not_flagged(self, tmp_repo):
        fresh_ts = int(time.time()) - 10 * 86400
        fake_output = f"recent-work {fresh_ts}\n"
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0, stdout=fake_output, stderr="",
            )
            items = _detect_stale_branches(str(tmp_repo), stale_days=60)
            assert items == []

    def test_git_not_available(self, tmp_repo):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            items = _detect_stale_branches(str(tmp_repo))
            assert items == []

    def test_git_error(self, tmp_repo):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1, stdout="", stderr="err")
            items = _detect_stale_branches(str(tmp_repo))
            assert items == []

    def test_git_timeout(self, tmp_repo):
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 10)):
            items = _detect_stale_branches(str(tmp_repo))
            assert items == []


# ---------------------------------------------------------------------------
# Build called set
# ---------------------------------------------------------------------------

class TestBuildCalledSet:
    def test_finds_calls(self, tmp_repo):
        _write_module(tmp_repo, "caller.py", """\
            def helper():
                return 1

            helper()
        """)
        called = _build_called_set(tmp_repo)
        assert "helper" in called

    def test_finds_method_calls(self, tmp_repo):
        _write_module(tmp_repo, "obj2.py", """\
            class Foo:
                def bar(self):
                    return 1

            Foo().bar()
        """)
        called = _build_called_set(tmp_repo)
        assert "bar" in called

    def test_finds_decorator_refs(self, tmp_repo):
        _write_module(tmp_repo, "deco.py", """\
            def my_decorator(f):
                return f

            @my_decorator
            def wrapped():
                pass
        """)
        called = _build_called_set(tmp_repo)
        assert "my_decorator" in called

    def test_ignores_syntax_errors(self, tmp_repo):
        _write_module(tmp_repo, "bad.py", "def (\n")
        _write_module(tmp_repo, "good.py", "foo()\n")
        called = _build_called_set(tmp_repo)
        assert "foo" in called


# ---------------------------------------------------------------------------
# LymphaticAnalyzer — composite scoring
# ---------------------------------------------------------------------------

class TestLymphaticAnalyzer:
    def test_clean_repo_high_score(self, tmp_repo):
        _write_module(tmp_repo, "clean.py", """\
            \"\"\"A clean module with no waste.\"\"\"

            def compute(x):
                \"\"\"Compute something.\"\"\"
                return x * 2

            result = compute(21)
            print(result)
        """)
        _write_test(tmp_repo, "test_clean.py", """\
            def test_compute():
                assert True
        """)
        analyzer = LymphaticAnalyzer(repo_root=str(tmp_repo))
        report = analyzer.analyze()
        assert report["lymphatic_score"] >= 80
        assert report["files_scanned"] >= 2

    def test_dirty_repo_lower_score(self, tmp_repo):
        # Create a file with unused imports.
        _write_module(tmp_repo, "dirty.py", """\
            import os
            import sys
            import json
            import re
            import time
            import math

            x = 1
        """)
        analyzer = LymphaticAnalyzer(repo_root=str(tmp_repo))
        report = analyzer.analyze()
        assert report["category_counts"]["unused_import"] >= 4
        # Even with many unused imports the weighted average across 8
        # categories only drops a few points each, so verify it is
        # measurably below a perfectly clean score.
        assert report["lymphatic_score"] < 98

    def test_report_is_json_serializable(self, tmp_repo):
        _write_module(tmp_repo, "json_test.py", """\
            \"\"\"Module for JSON test.\"\"\"
            x = 1
            print(x)
        """)
        analyzer = LymphaticAnalyzer(repo_root=str(tmp_repo))
        report = analyzer.analyze()
        # Should not raise.
        json.dumps(report)

    def test_custom_weights(self, tmp_repo):
        _write_module(tmp_repo, "wt.py", """\
            \"\"\"Weight test.\"\"\"
            x = 1
            print(x)
        """)
        # All weights zero except one.
        weights = {c: 0.0 for c in VALID_CATEGORIES}
        weights["unused_import"] = 1.0
        analyzer = LymphaticAnalyzer(repo_root=str(tmp_repo), weights=weights)
        report = analyzer.analyze()
        # With only one non-zero weight and no unused imports, score should be 100.
        assert report["category_scores"]["unused_import"] == 100.0

    def test_oedema_detection(self, tmp_repo):
        # Create a file with many waste items.
        _write_module(tmp_repo, "bloated.py", """\
            import os
            import sys
            import json
            import re
            import time
            import math
            import collections
            import itertools

            x = 1
        """)
        analyzer = LymphaticAnalyzer(
            repo_root=str(tmp_repo),
            oedema_threshold=3,  # Low threshold to trigger.
        )
        report = analyzer.analyze()
        assert len(report["oedema_regions"]) >= 1

    def test_empty_repo(self, tmp_repo):
        analyzer = LymphaticAnalyzer(repo_root=str(tmp_repo))
        report = analyzer.analyze()
        assert report["lymphatic_score"] == 100.0
        assert report["total_waste"] == 0

    def test_missing_iamai_dir(self, tmp_path):
        analyzer = LymphaticAnalyzer(repo_root=str(tmp_path))
        report = analyzer.analyze()
        assert report["total_waste"] == 0
        assert report["files_scanned"] == 0

    def test_custom_stale_days(self, tmp_repo):
        p = _write_module(tmp_repo, "todo_custom.py", """\
            # TODO: test this
            x = 1
        """)
        old_time = time.time() - 100 * 86400
        os.utime(p, (old_time, old_time))

        # With stale_days=200, should not flag.
        analyzer = LymphaticAnalyzer(repo_root=str(tmp_repo), stale_days=200)
        report = analyzer.analyze()
        assert report["category_counts"]["stale_todo"] == 0

        # With stale_days=50, should flag.
        analyzer2 = LymphaticAnalyzer(repo_root=str(tmp_repo), stale_days=50)
        report2 = analyzer2.analyze()
        assert report2["category_counts"]["stale_todo"] >= 1

    def test_category_counts_keys(self, tmp_repo):
        _write_module(tmp_repo, "keys.py", '"""k."""\nx = 1\nprint(x)\n')
        analyzer = LymphaticAnalyzer(repo_root=str(tmp_repo))
        report = analyzer.analyze()
        for cat in VALID_CATEGORIES:
            assert cat in report["category_counts"]
            assert cat in report["category_scores"]


# ---------------------------------------------------------------------------
# Drainage rate
# ---------------------------------------------------------------------------

class TestDrainageRate:
    def test_cleaning_improves(self):
        before = {
            "items": [
                {"category": "unused_import", "file": "a.py", "line": 1},
                {"category": "unused_import", "file": "a.py", "line": 2},
                {"category": "dead_function", "file": "b.py", "line": 5},
            ]
        }
        after = {
            "items": [
                {"category": "unused_import", "file": "a.py", "line": 1},
            ]
        }
        rate = drainage_rate(before, after)
        assert rate["resolved"] == 2
        assert rate["created"] == 0
        assert rate["net_drain"] == 2

    def test_getting_worse(self):
        before = {"items": []}
        after = {
            "items": [
                {"category": "unused_import", "file": "a.py", "line": 1},
                {"category": "dead_function", "file": "b.py", "line": 5},
            ]
        }
        rate = drainage_rate(before, after)
        assert rate["resolved"] == 0
        assert rate["created"] == 2
        assert rate["net_drain"] == -2

    def test_no_change(self):
        snapshot = {
            "items": [
                {"category": "unused_import", "file": "a.py", "line": 1},
            ]
        }
        rate = drainage_rate(snapshot, snapshot)
        assert rate["resolved"] == 0
        assert rate["created"] == 0
        assert rate["net_drain"] == 0

    def test_empty_reports(self):
        rate = drainage_rate({"items": []}, {"items": []})
        assert rate["net_drain"] == 0
        assert rate["before_total"] == 0
        assert rate["after_total"] == 0


# ---------------------------------------------------------------------------
# Default definitions integrity
# ---------------------------------------------------------------------------

class TestDefaultDefinitions:
    def test_valid_categories_count(self):
        assert len(VALID_CATEGORIES) == 8

    def test_weights_cover_all_categories(self):
        for cat in VALID_CATEGORIES:
            assert cat in DEFAULT_WEIGHTS

    def test_weights_positive(self):
        for cat, w in DEFAULT_WEIGHTS.items():
            assert w > 0

    def test_exempt_function_names_nonempty(self):
        assert len(EXEMPT_FUNCTION_NAMES) > 0

    def test_exempt_prefixes_nonempty(self):
        assert len(EXEMPT_FUNCTION_PREFIXES) > 0

    def test_constants_positive(self):
        assert DEFAULT_STALE_DAYS > 0
        assert DEFAULT_BRANCH_STALE_DAYS > 0
        assert DEFAULT_OEDEMA_THRESHOLD > 0
        assert DEFAULT_DIR_OEDEMA_THRESHOLD > 0
        assert COMMENTED_CODE_MIN_LINES >= 2
        assert SNIPPET_MIN_LINES >= 5

    def test_category_names_consistent(self):
        """VALID_CATEGORIES should match DEFAULT_WEIGHTS keys."""
        assert set(VALID_CATEGORIES) == set(DEFAULT_WEIGHTS.keys())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCLI:
    def test_cli_text_output(self, tmp_repo):
        _write_module(tmp_repo, "cli_test.py", '"""cli."""\nx = 1\nprint(x)\n')
        from iamai.repo_lymphatic_system import main as cli_main
        with mock.patch("sys.argv", ["prog", "--repo", str(tmp_repo)]):
            # Should not raise.
            cli_main()

    def test_cli_json_output(self, tmp_repo, capsys):
        _write_module(tmp_repo, "cli_json.py", '"""cli."""\nx = 1\nprint(x)\n')
        from iamai.repo_lymphatic_system import main as cli_main
        with mock.patch("sys.argv", ["prog", "--repo", str(tmp_repo), "--json"]):
            cli_main()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "lymphatic_score" in data
        assert "total_waste" in data

    def test_cli_custom_stale_days(self, tmp_repo):
        _write_module(tmp_repo, "cli_stale.py", '"""cli."""\nx = 1\nprint(x)\n')
        from iamai.repo_lymphatic_system import main as cli_main
        with mock.patch("sys.argv", ["prog", "--repo", str(tmp_repo),
                                     "--stale-days", "30"]):
            cli_main()


# ---------------------------------------------------------------------------
# Integration — analyze on the real repo (self-test)
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_self_analysis(self):
        """The analyzer should be able to analyze its own repo without crashing."""
        repo_root = str(Path(__file__).resolve().parent.parent)
        analyzer = LymphaticAnalyzer(repo_root=repo_root)
        report = analyzer.analyze()
        assert report["files_scanned"] > 0
        assert 0 <= report["lymphatic_score"] <= 100
        assert report["total_waste"] >= 0

    def test_self_analysis_json_round_trip(self):
        repo_root = str(Path(__file__).resolve().parent.parent)
        analyzer = LymphaticAnalyzer(repo_root=repo_root)
        report = analyzer.analyze()
        # JSON round trip.
        serialised = json.dumps(report)
        restored = json.loads(serialised)
        assert restored["lymphatic_score"] == report["lymphatic_score"]
        assert restored["total_waste"] == report["total_waste"]
