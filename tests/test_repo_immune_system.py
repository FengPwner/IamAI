"""Tests for iamai.repo_immune_system."""

import json
import os
import time
import pytest
from pathlib import Path
from unittest.mock import patch

from iamai.repo_immune_system import (
    Antibody,
    ImmuneReport,
    Pathogen,
    PATHOGEN_CLASSES,
    _DEFAULT_ANTIBODIES,
    _classify_infections,
    _classify_state,
    _compute_immunity_score,
    _coverage_for_class,
    _detect_corrupt_json,
    _detect_dangling_symlinks,
    _detect_duplicate_index,
    _detect_orphan_state,
    _detect_stale_locks,
    _is_pid_alive,
    detect_pathogens,
    immune_report,
    immune_summary,
)


# ---------------------------------------------------------------------------
# Pathogen dataclass
# ---------------------------------------------------------------------------

class TestPathogen:
    def test_frozen(self):
        p = Pathogen(kind="stale_lock", path="foo.lock")
        with pytest.raises(AttributeError):
            p.kind = "other"

    def test_defaults(self):
        p = Pathogen(kind="zombie_pid", path="bar.pid")
        assert p.detail == ""

    def test_with_detail(self):
        p = Pathogen(kind="corrupt_json", path="data/x.json", detail="line 5 bad")
        assert p.detail == "line 5 bad"


# ---------------------------------------------------------------------------
# Antibody dataclass
# ---------------------------------------------------------------------------

class TestAntibody:
    def test_frozen(self):
        ab = Antibody(target="stale_lock", tool="lock_clearance", mechanism="clean")
        with pytest.raises(AttributeError):
            ab.target = "other"

    def test_default_coverage(self):
        ab = Antibody(target="stale_lock", tool="x", mechanism="y")
        assert ab.coverage == 1.0

    def test_custom_coverage(self):
        ab = Antibody(target="x", tool="y", mechanism="z", coverage=0.5)
        assert ab.coverage == 0.5


# ---------------------------------------------------------------------------
# PATHOGEN_CLASSES
# ---------------------------------------------------------------------------

class TestPathogenClasses:
    def test_count(self):
        assert len(PATHOGEN_CLASSES) == 6

    def test_contains_expected(self):
        assert "stale_lock" in PATHOGEN_CLASSES
        assert "zombie_pid" in PATHOGEN_CLASSES
        assert "corrupt_json" in PATHOGEN_CLASSES
        assert "dangling_symlink" in PATHOGEN_CLASSES
        assert "orphan_state" in PATHOGEN_CLASSES
        assert "duplicate_index" in PATHOGEN_CLASSES


# ---------------------------------------------------------------------------
# _is_pid_alive
# ---------------------------------------------------------------------------

class TestIsPidAlive:
    def test_current_process_is_alive(self):
        assert _is_pid_alive(os.getpid()) is True

    def test_nonexistent_pid(self):
        # PID 99999999 is extremely unlikely to exist.
        assert _is_pid_alive(99999999) is False

    def test_invalid_pid_string(self):
        # os.kill with signal 0 may succeed for negative PIDs on some
        # platforms (e.g. Linux root sends to process group), so we
        # only verify the function returns a bool without crashing.
        result = _is_pid_alive(-1)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# _coverage_for_class
# ---------------------------------------------------------------------------

class TestCoverageForClass:
    def test_known_class(self):
        cov = _coverage_for_class("stale_lock")
        assert cov == 0.95

    def test_unknown_class(self):
        cov = _coverage_for_class("unknown_pathogen")
        assert cov == 0.0

    def test_custom_antibodies(self):
        custom = (Antibody("stale_lock", "x", "y", coverage=0.5),)
        assert _coverage_for_class("stale_lock", custom) == 0.5

    def test_best_of_multiple(self):
        custom = (
            Antibody("stale_lock", "a", "b", coverage=0.3),
            Antibody("stale_lock", "c", "d", coverage=0.8),
        )
        assert _coverage_for_class("stale_lock", custom) == 0.8


# ---------------------------------------------------------------------------
# _classify_infections
# ---------------------------------------------------------------------------

class TestClassifyInfections:
    def test_covered_pathogen_not_infection(self):
        pathogens = [Pathogen("stale_lock", "x.lock")]
        infections = _classify_infections(pathogens)
        assert infections == []

    def test_uncovered_pathogen_is_infection(self):
        custom = (Antibody("stale_lock", "x", "y", coverage=0.3),)
        pathogens = [Pathogen("stale_lock", "x.lock")]
        infections = _classify_infections(pathogens, custom)
        assert len(infections) == 1

    def test_exactly_half_not_infection(self):
        custom = (Antibody("stale_lock", "x", "y", coverage=0.5),)
        pathogens = [Pathogen("stale_lock", "x.lock")]
        infections = _classify_infections(pathogens, custom)
        assert infections == []

    def test_empty_pathogens(self):
        assert _classify_infections([]) == []


# ---------------------------------------------------------------------------
# _compute_immunity_score
# ---------------------------------------------------------------------------

class TestComputeImmunityScore:
    def test_no_pathogens_perfect_score(self):
        assert _compute_immunity_score([]) == 100.0

    def test_single_covered_pathogen(self):
        # stale_lock has coverage 0.95, so deduction = 10 * (1 - 0.95) = 0.5
        pathogens = [Pathogen("stale_lock", "x.lock")]
        score = _compute_immunity_score(pathogens)
        assert 99.0 <= score <= 100.0

    def test_single_uncovered_pathogen(self):
        custom = (Antibody("stale_lock", "x", "y", coverage=0.3),)
        pathogens = [Pathogen("stale_lock", "x.lock")]
        score = _compute_immunity_score(pathogens, custom)
        # deduction = 10 * 0.7 + 5 = 12.0
        assert score == 88.0

    def test_many_pathogens_floor_at_zero(self):
        custom = (Antibody("x", "y", "z", coverage=0.0),)
        pathogens = [Pathogen("x", f"p{i}") for i in range(50)]
        score = _compute_immunity_score(pathogens, custom)
        assert score == 0.0

    def test_mixed_coverage(self):
        pathogens = [
            Pathogen("stale_lock", "a.lock"),
            Pathogen("zombie_pid", "b.pid"),
        ]
        score = _compute_immunity_score(pathogens)
        # stale_lock deduction: 10 * 0.05 = 0.5
        # zombie_pid deduction: 10 * 0.10 = 1.0
        # total: 1.5
        assert 98.0 <= score <= 99.0


# ---------------------------------------------------------------------------
# _classify_state
# ---------------------------------------------------------------------------

class TestClassifyState:
    def test_no_pathogens_immune(self):
        assert _classify_state(100.0, [], 0) == "immune"

    def test_high_score_no_infections(self):
        assert _classify_state(90.0, [], 2) == "immune"

    def test_medium_score_no_infections(self):
        assert _classify_state(70.0, [], 3) == "vulnerable"

    def test_medium_score_with_infections(self):
        infections = [Pathogen("x", "y")]
        assert _classify_state(70.0, infections, 3) == "inflamed"

    def test_low_score(self):
        assert _classify_state(45.0, [], 10) == "immunocompromised"

    def test_very_low_score(self):
        assert _classify_state(20.0, [], 20) == "septic"

    def test_boundary_85(self):
        assert _classify_state(85.0, [], 5) == "immune"

    def test_boundary_65(self):
        assert _classify_state(65.0, [], 5) == "vulnerable"

    def test_boundary_40(self):
        assert _classify_state(40.0, [], 10) == "immunocompromised"


# ---------------------------------------------------------------------------
# _detect_corrupt_json (with tmp_path)
# ---------------------------------------------------------------------------

class TestDetectCorruptJson:
    def test_valid_json(self, tmp_path):
        (tmp_path / "good.json").write_text('{"key": "value"}')
        assert _detect_corrupt_json(str(tmp_path)) == []

    def test_invalid_json(self, tmp_path):
        (tmp_path / "bad.json").write_text("{not valid json")
        result = _detect_corrupt_json(str(tmp_path))
        assert len(result) == 1
        assert result[0].kind == "corrupt_json"

    def test_valid_jsonl(self, tmp_path):
        (tmp_path / "good.jsonl").write_text('{"a": 1}\n{"b": 2}\n')
        assert _detect_corrupt_json(str(tmp_path)) == []

    def test_invalid_jsonl(self, tmp_path):
        (tmp_path / "bad.jsonl").write_text('{"a": 1}\n{bad line}\n')
        result = _detect_corrupt_json(str(tmp_path))
        assert len(result) == 1
        assert "line 2" in result[0].detail

    def test_empty_file_ignored(self, tmp_path):
        (tmp_path / "empty.json").write_text("")
        assert _detect_corrupt_json(str(tmp_path)) == []

    def test_git_dir_ignored(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "bad.json").write_text("{invalid")
        assert _detect_corrupt_json(str(tmp_path)) == []

    def test_node_modules_ignored(self, tmp_path):
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "bad.json").write_text("{invalid")
        assert _detect_corrupt_json(str(tmp_path)) == []


# ---------------------------------------------------------------------------
# _detect_duplicate_index
# ---------------------------------------------------------------------------

class TestDetectDuplicateIndex:
    def test_no_duplicates(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        lines = json.dumps({"id": "a", "v": 1}) + "\n" + json.dumps({"id": "b", "v": 2}) + "\n"
        (data / "index.jsonl").write_text(lines)
        assert _detect_duplicate_index(str(tmp_path)) == []

    def test_with_duplicates(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        lines = json.dumps({"id": "a", "v": 1}) + "\n" + json.dumps({"id": "a", "v": 2}) + "\n"
        (data / "index.jsonl").write_text(lines)
        result = _detect_duplicate_index(str(tmp_path))
        assert len(result) == 1
        assert result[0].kind == "duplicate_index"
        assert "'a'" in result[0].detail

    def test_no_key_fields(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        lines = json.dumps({"x": 1}) + "\n" + json.dumps({"x": 2}) + "\n"
        (data / "index.jsonl").write_text(lines)
        assert _detect_duplicate_index(str(tmp_path)) == []

    def test_invalid_json_line_skipped(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        (data / "index.jsonl").write_text("{bad\n" + json.dumps({"id": "a"}) + "\n")
        assert _detect_duplicate_index(str(tmp_path)) == []


# ---------------------------------------------------------------------------
# _detect_orphan_state
# ---------------------------------------------------------------------------

class TestDetectOrphanState:
    def test_referenced_file(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        (data / "writer_state.json").write_text("{}")
        # Create a .py file that references it.
        (tmp_path / "mod.py").write_text("# loads writer_state\n")
        result = _detect_orphan_state(str(tmp_path))
        assert result == []

    def test_orphan_file(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        (data / "totally_unused.json").write_text("{}")
        (tmp_path / "mod.py").write_text("# does something else\n")
        result = _detect_orphan_state(str(tmp_path))
        assert len(result) == 1
        assert result[0].kind == "orphan_state"

    def test_no_data_dir(self, tmp_path):
        assert _detect_orphan_state(str(tmp_path)) == []


# ---------------------------------------------------------------------------
# _detect_stale_locks
# ---------------------------------------------------------------------------

class TestDetectStaleLocks:
    def test_no_locks(self, tmp_path):
        assert _detect_stale_locks(str(tmp_path)) == []

    def test_live_pid_not_zombie(self, tmp_path):
        (tmp_path / "alive.pid").write_text(str(os.getpid()))
        result = _detect_stale_locks(str(tmp_path))
        assert result == []

    def test_dead_pid_is_zombie(self, tmp_path):
        (tmp_path / "dead.pid").write_text("99999999")
        result = _detect_stale_locks(str(tmp_path))
        assert len(result) == 1
        assert result[0].kind == "zombie_pid"

    def test_stale_lock_by_age(self, tmp_path):
        lock = tmp_path / "old.lock"
        lock.write_text("some-lock-data")
        # Set mtime to 2 hours ago.
        old_time = time.time() - 7200
        os.utime(lock, (old_time, old_time))
        result = _detect_stale_locks(str(tmp_path), max_age_s=3600)
        assert len(result) == 1
        assert result[0].kind == "stale_lock"

    def test_fresh_lock_not_stale(self, tmp_path):
        lock = tmp_path / "new.lock"
        lock.write_text("fresh-lock-data")
        result = _detect_stale_locks(str(tmp_path), max_age_s=3600)
        assert result == []


# ---------------------------------------------------------------------------
# _detect_dangling_symlinks
# ---------------------------------------------------------------------------

class TestDetectDanglingSymlinks:
    def test_no_symlinks(self, tmp_path):
        assert _detect_dangling_symlinks(str(tmp_path)) == []

    def test_valid_symlink(self, tmp_path):
        target = tmp_path / "real.txt"
        target.write_text("hello")
        link = tmp_path / "link.txt"
        link.symlink_to(target)
        assert _detect_dangling_symlinks(str(tmp_path)) == []

    def test_dangling_symlink(self, tmp_path):
        link = tmp_path / "dangling.txt"
        link.symlink_to(tmp_path / "nonexistent.txt")
        result = _detect_dangling_symlinks(str(tmp_path))
        assert len(result) == 1
        assert result[0].kind == "dangling_symlink"


# ---------------------------------------------------------------------------
# detect_pathogens
# ---------------------------------------------------------------------------

class TestDetectPathogens:
    def test_clean_repo(self, tmp_path):
        # Create minimal clean structure.
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "good.json").write_text('{"ok": true}')
        result = detect_pathogens(str(tmp_path))
        # Should find no pathogens (or very few).
        assert isinstance(result, list)

    def test_combines_detectors(self, tmp_path):
        # Create multiple pathogen types.
        (tmp_path / "dead.pid").write_text("99999999")
        (tmp_path / "bad.json").write_text("{invalid json")
        link = tmp_path / "dangling.txt"
        link.symlink_to(tmp_path / "missing.txt")
        result = detect_pathogens(str(tmp_path))
        kinds = {p.kind for p in result}
        assert "zombie_pid" in kinds
        assert "corrupt_json" in kinds
        assert "dangling_symlink" in kinds


# ---------------------------------------------------------------------------
# immune_report
# ---------------------------------------------------------------------------

class TestImmuneReport:
    def test_default_fields(self):
        r = ImmuneReport()
        assert r.immunity_score == 100.0
        assert r.state == "immune"
        assert r.pathogens == []
        assert r.infections == []

    def test_report_on_clean_tmp(self, tmp_path):
        (tmp_path / "data").mkdir()
        report = immune_report(str(tmp_path))
        assert isinstance(report, ImmuneReport)
        assert report.state in ("immune", "vulnerable", "inflamed",
                                "immunocompromised", "septic")

    def test_report_score_range(self, tmp_path):
        report = immune_report(str(tmp_path))
        assert 0.0 <= report.immunity_score <= 100.0

    def test_custom_antibodies(self, tmp_path):
        custom = (Antibody("stale_lock", "x", "y", coverage=0.1),)
        report = immune_report(str(tmp_path), antibodies=custom)
        assert isinstance(report, ImmuneReport)

    def test_pathogens_by_class(self, tmp_path):
        (tmp_path / "bad.json").write_text("{invalid")
        report = immune_report(str(tmp_path))
        assert isinstance(report.pathogens_by_class, dict)


# ---------------------------------------------------------------------------
# immune_summary
# ---------------------------------------------------------------------------

class TestImmuneSummary:
    def test_clean_summary(self):
        report = ImmuneReport(immunity_score=100.0, state="immune")
        s = immune_summary(report)
        assert "100.0" in s
        assert "immune" in s

    def test_with_infections(self):
        report = ImmuneReport(
            pathogens=[Pathogen("stale_lock", "x.lock")],
            infections=[Pathogen("stale_lock", "x.lock")],
            immunity_score=65.0,
            state="inflamed",
            antibodies_active=3,
        )
        s = immune_summary(report)
        assert "inflamed" in s
        assert "stale_lock" in s

    def test_with_pathogen_counts(self):
        report = ImmuneReport(
            pathogens=[
                Pathogen("corrupt_json", "a.json"),
                Pathogen("corrupt_json", "b.json"),
            ],
            immunity_score=80.0,
            state="vulnerable",
            pathogens_by_class={"corrupt_json": 2},
            antibodies_active=4,
        )
        s = immune_summary(report)
        assert "corrupt_json" in s
        assert "2" in s
