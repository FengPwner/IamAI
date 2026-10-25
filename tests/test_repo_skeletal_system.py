"""Tests for iamai.repo_skeletal_system."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from iamai.repo_skeletal_system import (
    FRACTURE_CLASSES,
    Bone,
    Fracture,
    Misalignment,
    SkeletalReport,
    _build_import_graph,
    _classify_state,
    _compute_skeleton_score,
    _count_lines,
    _detect_broken_imports,
    _detect_circular_imports,
    _detect_duplicate_modules,
    _detect_misalignments,
    _detect_missing_init,
    _detect_orphan_tests,
    _detect_stale_init,
    _find_load_bearing,
    _find_stress_concentration,
    _inventory_bones,
    _parse_imports,
    detect_fractures,
    skeletal_report,
    skeletal_summary,
    _SKIP_DIRS,
    _DEFAULT_LOAD_THRESHOLD,
    _STRESS_CONCENTRATION_RATIO,
    _OSTEOPOROSIS_DENSITY_THRESHOLD,
    _DOC_DENSITY_HEALTHY,
    _EMPTY_BONE_MIN_LINES,
)


# ---------------------------------------------------------------------------
# Fracture dataclass
# ---------------------------------------------------------------------------

class TestFracture:
    def test_frozen(self):
        f = Fracture(kind="broken_import", path="iamai/foo.py")
        with pytest.raises(AttributeError):
            f.kind = "other"

    def test_defaults(self):
        f = Fracture(kind="circular_import", path="iamai/bar.py")
        assert f.detail == ""

    def test_with_detail(self):
        f = Fracture(kind="orphan_test", path="tests/test_x.py", detail="target gone")
        assert f.detail == "target gone"


# ---------------------------------------------------------------------------
# Bone dataclass
# ---------------------------------------------------------------------------

class TestBone:
    def test_frozen(self):
        b = Bone(path="iamai/foo.py")
        with pytest.raises(AttributeError):
            b.path = "other"

    def test_defaults(self):
        b = Bone(path="iamai/x.py")
        assert b.code_lines == 0
        assert b.doc_lines == 0
        assert b.importers == 0
        assert b.has_test is False
        assert b.test_lines == 0

    def test_doc_density_zero_code(self):
        b = Bone(path="iamai/x.py", code_lines=0, doc_lines=5)
        assert b.doc_density == 5.0  # 5 / max(0,1)

    def test_doc_density_normal(self):
        b = Bone(path="iamai/x.py", code_lines=100, doc_lines=25)
        assert b.doc_density == 0.25

    def test_test_density(self):
        b = Bone(path="iamai/x.py", code_lines=100, test_lines=50)
        assert b.test_density == 0.5

    def test_is_osteoporotic_true(self):
        b = Bone(path="iamai/x.py", code_lines=100, test_lines=10)
        assert b.is_osteoporotic is True

    def test_is_osteoporotic_false(self):
        b = Bone(path="iamai/x.py", code_lines=100, test_lines=50)
        assert b.is_osteoporotic is False

    def test_is_empty_true(self):
        b = Bone(path="iamai/x.py", code_lines=3)
        assert b.is_empty is True

    def test_is_empty_false(self):
        b = Bone(path="iamai/x.py", code_lines=10)
        assert b.is_empty is False

    def test_is_well_documented_true(self):
        b = Bone(path="iamai/x.py", code_lines=100, doc_lines=25)
        assert b.is_well_documented is True

    def test_is_well_documented_false(self):
        b = Bone(path="iamai/x.py", code_lines=100, doc_lines=10)
        assert b.is_well_documented is False


# ---------------------------------------------------------------------------
# Misalignment dataclass
# ---------------------------------------------------------------------------

class TestMisalignment:
    def test_frozen(self):
        m = Misalignment(kind="naming_drift", path="iamai/foo.py")
        with pytest.raises(AttributeError):
            m.kind = "other"

    def test_defaults(self):
        m = Misalignment(kind="empty_bone", path="iamai/x.py")
        assert m.detail == ""


# ---------------------------------------------------------------------------
# FRACTURE_CLASSES constant
# ---------------------------------------------------------------------------

class TestFractureClasses:
    def test_count(self):
        assert len(FRACTURE_CLASSES) == 6

    def test_contains_expected(self):
        assert "broken_import" in FRACTURE_CLASSES
        assert "circular_import" in FRACTURE_CLASSES
        assert "duplicate_module" in FRACTURE_CLASSES
        assert "stale_init" in FRACTURE_CLASSES
        assert "missing_init" in FRACTURE_CLASSES
        assert "orphan_test" in FRACTURE_CLASSES


# ---------------------------------------------------------------------------
# _parse_imports
# ---------------------------------------------------------------------------

class TestParseImports:
    def test_regular_import(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text("import os\nimport sys\n")
        result = _parse_imports(f)
        assert "os" in result
        assert "sys" in result

    def test_from_import(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text("from pathlib import Path\n")
        result = _parse_imports(f)
        assert "pathlib" in result

    def test_relative_import(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text("from . import foo\n")
        result = _parse_imports(f)
        # module is None for relative with no module part
        assert result == [] or result == [None]  # depends on ast behaviour

    def test_syntax_error(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("def foo(\n")
        result = _parse_imports(f)
        assert result == []

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        result = _parse_imports(f)
        assert result == []

    def test_no_imports(self, tmp_path):
        f = tmp_path / "pure.py"
        f.write_text("x = 1\ny = 2\n")
        result = _parse_imports(f)
        assert result == []


# ---------------------------------------------------------------------------
# _count_lines
# ---------------------------------------------------------------------------

class TestCountLines:
    def test_basic(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text("# comment\nx = 1\ny = 2\n")
        code, doc = _count_lines(f)
        assert code == 2
        assert doc == 1

    def test_docstring(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text('"""Module docstring."""\nx = 1\n')
        code, doc = _count_lines(f)
        assert code == 1
        assert doc == 1

    def test_multiline_docstring(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text('"""\nMulti\nline\n"""\nx = 1\n')
        code, doc = _count_lines(f)
        assert code == 1
        assert doc == 4  # 4 lines of docstring

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        code, doc = _count_lines(f)
        assert code == 0
        assert doc == 0

    def test_blank_lines_ignored(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text("\n\n\nx = 1\n\n")
        code, doc = _count_lines(f)
        assert code == 1
        assert doc == 0


# ---------------------------------------------------------------------------
# _build_import_graph
# ---------------------------------------------------------------------------

class TestBuildImportGraph:
    def test_no_iamai_dir(self, tmp_path):
        graph = _build_import_graph(str(tmp_path))
        assert graph == {}

    def test_simple_graph(self, tmp_path):
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "foo.py").write_text("from iamai import bar\n")
        (pkg / "bar.py").write_text("x = 1\n")
        graph = _build_import_graph(str(tmp_path))
        assert "foo" in graph
        assert "bar" in graph


# ---------------------------------------------------------------------------
# Fracture detectors (unit level with tmp_path)
# ---------------------------------------------------------------------------

class TestDetectBrokenImports:
    def test_no_fractures(self, tmp_path):
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "foo.py").write_text("x = 1\n")
        graph = {"foo": set()}
        result = _detect_broken_imports(str(tmp_path), graph)
        assert result == []

    def test_broken(self, tmp_path):
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "foo.py").write_text("import ghost\n")
        graph = {"foo": {"ghost"}}
        result = _detect_broken_imports(str(tmp_path), graph)
        assert len(result) == 1
        assert result[0].kind == "broken_import"
        assert "ghost" in result[0].detail


class TestDetectCircularImports:
    def test_no_cycle(self):
        graph = {"a": {"b"}, "b": set()}
        result = _detect_circular_imports(graph)
        assert result == []

    def test_simple_cycle(self):
        graph = {"a": {"b"}, "b": {"a"}}
        result = _detect_circular_imports(graph)
        assert len(result) >= 1
        assert result[0].kind == "circular_import"

    def test_three_way_cycle(self):
        graph = {"a": {"b"}, "b": {"c"}, "c": {"a"}}
        result = _detect_circular_imports(graph)
        assert len(result) >= 1

    def test_empty_graph(self):
        result = _detect_circular_imports({})
        assert result == []


class TestDetectDuplicateModules:
    def test_no_duplicates(self, tmp_path):
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "foo.py").write_text("x = 1\n")
        result = _detect_duplicate_modules(str(tmp_path))
        assert result == []

    def test_duplicate_different_dirs(self, tmp_path):
        d1 = tmp_path / "iamai"
        d1.mkdir()
        d2 = tmp_path / "extra"
        d2.mkdir()
        (d1 / "foo.py").write_text("x = 1\n")
        (d2 / "foo.py").write_text("x = 2\n")
        result = _detect_duplicate_modules(str(tmp_path))
        assert len(result) == 1
        assert result[0].kind == "duplicate_module"


class TestDetectStaleInit:
    def test_no_init(self, tmp_path):
        result = _detect_stale_init(str(tmp_path))
        assert result == []

    def test_clean_init(self, tmp_path):
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "foo.py").write_text("x = 1\n")
        result = _detect_stale_init(str(tmp_path))
        assert result == []

    def test_stale_reexport(self, tmp_path):
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .ghost import something\n")
        result = _detect_stale_init(str(tmp_path))
        assert len(result) == 1
        assert result[0].kind == "stale_init"


class TestDetectMissingInit:
    def test_all_have_init(self, tmp_path):
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "foo.py").write_text("x = 1\n")
        result = _detect_missing_init(str(tmp_path))
        assert result == []

    def test_missing_init(self, tmp_path):
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        (pkg / "foo.py").write_text("x = 1\n")
        result = _detect_missing_init(str(tmp_path))
        assert len(result) == 1
        assert result[0].kind == "missing_init"


class TestDetectOrphanTests:
    def test_no_orphans(self, tmp_path):
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "foo.py").write_text("x = 1\n")
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_foo.py").write_text("def test_x(): pass\n")
        graph = {"foo": set()}
        result = _detect_orphan_tests(str(tmp_path), graph)
        assert result == []

    def test_orphan(self, tmp_path):
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_vanished.py").write_text("def test_x(): pass\n")
        graph = {}
        result = _detect_orphan_tests(str(tmp_path), graph)
        assert len(result) == 1
        assert result[0].kind == "orphan_test"


# ---------------------------------------------------------------------------
# detect_fractures (integration)
# ---------------------------------------------------------------------------

class TestDetectFractures:
    def test_clean_repo(self, tmp_path):
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "foo.py").write_text("x = 1\n")
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_foo.py").write_text("def test_x(): pass\n")
        result = detect_fractures(str(tmp_path))
        # Should have no broken_import or circular_import
        broken = [f for f in result if f.kind == "broken_import"]
        assert broken == []


# ---------------------------------------------------------------------------
# Bone inventory
# ---------------------------------------------------------------------------

class TestInventoryBones:
    def test_basic(self, tmp_path):
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "foo.py").write_text("# comment\nx = 1\ny = 2\n")
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_foo.py").write_text("def test_x():\n    pass\n")
        graph = {"foo": set()}
        bones = _inventory_bones(str(tmp_path), graph)
        assert len(bones) == 1
        assert bones[0].path == "iamai/foo.py"
        assert bones[0].code_lines == 2
        assert bones[0].has_test is True

    def test_no_tests(self, tmp_path):
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "bar.py").write_text("x = 1\n")
        (tmp_path / "tests").mkdir()
        graph = {"bar": set()}
        bones = _inventory_bones(str(tmp_path), graph)
        assert bones[0].has_test is False

    def test_importer_count(self, tmp_path):
        pkg = tmp_path / "iamai"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "core.py").write_text("x = 1\n")
        (pkg / "a.py").write_text("from iamai import core\n")
        (pkg / "b.py").write_text("from iamai import core\n")
        (tmp_path / "tests").mkdir()
        graph = {"core": set(), "a": {"core"}, "b": {"core"}}
        bones = _inventory_bones(str(tmp_path), graph)
        core_bone = next(b for b in bones if b.path == "iamai/core.py")
        assert core_bone.importers == 2


# ---------------------------------------------------------------------------
# Load-bearing analysis
# ---------------------------------------------------------------------------

class TestFindLoadBearing:
    def test_none(self):
        bones = [
            Bone(path="iamai/a.py", importers=1),
            Bone(path="iamai/b.py", importers=2),
        ]
        result = _find_load_bearing(bones, threshold=5)
        assert result == []

    def test_some(self):
        bones = [
            Bone(path="iamai/a.py", importers=1),
            Bone(path="iamai/core.py", importers=10),
        ]
        result = _find_load_bearing(bones, threshold=5)
        assert "iamai/core.py" in result

    def test_default_threshold(self):
        bones = [Bone(path="iamai/x.py", importers=_DEFAULT_LOAD_THRESHOLD)]
        result = _find_load_bearing(bones)
        assert "iamai/x.py" in result


class TestFindStressConcentration:
    def test_none(self):
        bones = [
            Bone(path="iamai/a.py", importers=5),
            Bone(path="iamai/b.py", importers=5),
            Bone(path="iamai/c.py", importers=5),
        ]
        assert _find_stress_concentration(bones) is None

    def test_concentrated(self):
        bones = [
            Bone(path="iamai/god.py", importers=90),
            Bone(path="iamai/other.py", importers=10),
        ]
        result = _find_stress_concentration(bones)
        assert result == "iamai/god.py"

    def test_zero_joints(self):
        bones = [Bone(path="iamai/a.py", importers=0)]
        assert _find_stress_concentration(bones) is None


# ---------------------------------------------------------------------------
# Misalignment detection
# ---------------------------------------------------------------------------

class TestDetectMisalignments:
    def test_empty_bones(self):
        bones = [Bone(path="iamai/tiny.py", code_lines=2)]
        mis = _detect_misalignments("/nonexistent", bones)
        empty = [m for m in mis if m.kind == "empty_bone"]
        assert len(empty) == 1

    def test_no_naming_drift(self):
        bones = [
            Bone(path="iamai/foo.py", code_lines=100),
            Bone(path="iamai/bar.py", code_lines=100),
        ]
        mis = _detect_misalignments("/nonexistent", bones)
        naming = [m for m in mis if m.kind == "naming_drift"]
        assert naming == []


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

class TestComputeSkeletonScore:
    def test_perfect(self):
        score = _compute_skeleton_score([], [], [], None)
        assert score == 100.0

    def test_fracture_deduction(self):
        fractures = [Fracture(kind="broken_import", path="x.py")]
        score = _compute_skeleton_score(fractures, [], [], None)
        assert score == 92.0

    def test_osteoporosis_deduction(self):
        bones = [Bone(path="iamai/x.py", code_lines=100, test_lines=10)]
        score = _compute_skeleton_score([], bones, [], None)
        assert score == 97.0  # -3 for 1 osteoporotic bone

    def test_stress_concentration(self):
        score = _compute_skeleton_score([], [], [], "iamai/god.py")
        assert score == 95.0

    def test_misalignment_deduction(self):
        mis = [Misalignment(kind="naming_drift", path="iamai/x.py", detail="naming")]
        bones = [Bone(path="iamai/x.py", code_lines=100, test_lines=50)]
        score = _compute_skeleton_score([], bones, mis, None)
        # -2 for one misalignment
        assert score == 98.0

    def test_floor_at_zero(self):
        fractures = [Fracture(kind="broken_import", path="x.py")] * 20
        score = _compute_skeleton_score(fractures, [], [], None)
        assert score == 0.0


class TestClassifyState:
    def test_sound_no_fractures(self):
        assert _classify_state(95, []) == "sound"

    def test_sound_with_fractures(self):
        fractures = [Fracture(kind="broken_import", path="x.py")]
        assert _classify_state(80, fractures) == "sound"

    def test_weakened(self):
        assert _classify_state(60, []) == "weakened"

    def test_fragile(self):
        assert _classify_state(40, []) == "fragile"

    def test_brittle(self):
        assert _classify_state(20, []) == "brittle"


# ---------------------------------------------------------------------------
# SkeletalReport
# ---------------------------------------------------------------------------

class TestSkeletalReport:
    def test_defaults(self):
        r = SkeletalReport()
        assert r.bones == []
        assert r.fractures == []
        assert r.skeleton_score == 100.0
        assert r.state == "sound"
        assert r.stress_concentration is None


# ---------------------------------------------------------------------------
# skeletal_report (integration — run against the real repo)
# ---------------------------------------------------------------------------

class TestSkeletalReportIntegration:
    def test_runs_without_error(self):
        # Run against the actual repo root (parent of iamai/).
        repo_root = str(Path(__file__).resolve().parent.parent)
        r = skeletal_report(repo_root)
        assert isinstance(r, SkeletalReport)
        assert 0 <= r.skeleton_score <= 100
        assert r.state in ("sound", "weakened", "fragile", "brittle")
        assert len(r.bones) > 0

    def test_bones_have_data(self):
        repo_root = str(Path(__file__).resolve().parent.parent)
        r = skeletal_report(repo_root)
        for b in r.bones:
            assert b.path.startswith("iamai/")
            assert b.code_lines >= 0

    def test_summary_format(self):
        repo_root = str(Path(__file__).resolve().parent.parent)
        r = skeletal_report(repo_root)
        s = skeletal_summary(r)
        assert "skeleton" in s
        assert "bone(s)" in s
        assert "fracture(s)" in s


# ---------------------------------------------------------------------------
# skeletal_summary
# ---------------------------------------------------------------------------

class TestSkeletalSummary:
    def test_clean(self):
        r = SkeletalReport(
            bones=[Bone(path="iamai/a.py", code_lines=50, test_lines=30)],
            skeleton_score=100.0,
            state="sound",
        )
        s = skeletal_summary(r)
        assert "100.0/100" in s
        assert "sound" in s

    def test_with_fractures(self):
        r = SkeletalReport(
            bones=[Bone(path="iamai/a.py", code_lines=50, test_lines=30)],
            fractures=[Fracture(kind="broken_import", path="iamai/a.py")],
            fractures_by_class={"broken_import": 1},
            skeleton_score=92.0,
            state="sound",
        )
        s = skeletal_summary(r)
        assert "broken_import" in s

    def test_stress_concentration(self):
        r = SkeletalReport(
            bones=[Bone(path="iamai/god.py", code_lines=500, test_lines=200, importers=50)],
            stress_concentration="iamai/god.py",
            skeleton_score=95.0,
            state="sound",
        )
        s = skeletal_summary(r)
        assert "stress concentration" in s

    def test_load_bearing_count(self):
        r = SkeletalReport(
            bones=[Bone(path="iamai/core.py", code_lines=100, test_lines=50, importers=10)],
            load_bearing=["iamai/core.py"],
            skeleton_score=90.0,
            state="sound",
        )
        s = skeletal_summary(r)
        assert "1 load-bearing" in s


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------

class TestConstants:
    def test_skip_dirs(self):
        assert ".git" in _SKIP_DIRS
        assert "__pycache__" in _SKIP_DIRS

    def test_load_threshold_positive(self):
        assert _DEFAULT_LOAD_THRESHOLD > 0

    def test_stress_ratio(self):
        assert 0 < _STRESS_CONCENTRATION_RATIO < 1

    def test_osteoporosis_threshold(self):
        assert 0 < _OSTEOPOROSIS_DENSITY_THRESHOLD < 1

    def test_doc_density_healthy(self):
        assert 0 < _DOC_DENSITY_HEALTHY < 1

    def test_empty_bone_min(self):
        assert _EMPTY_BONE_MIN_LINES > 0
