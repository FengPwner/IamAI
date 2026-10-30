"""Tests for iamai.repo_endocrine_system.

Covers: Hormone, FeedbackLoop, Imbalance data classes, individual
hormone measurements, loop analysis, imbalance detection, receptor
resistance, scoring, and end-to-end analyze().
"""

import json
import os
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

from iamai.repo_endocrine_system import (
    DEFAULT_HORMONES,
    DEFAULT_LOOPS,
    EndocrineAnalyzer,
    FeedbackLoop,
    Hormone,
    Imbalance,
    _classify_commit,
    _count_pushes_from_log,
    _count_uncommitted,
    _git_log,
    _list_modules,
    _module_has_docstring,
    _module_line_count,
    _most_recent_test_mtime,
    _read_strokes,
)


# ---------------------------------------------------------------------------
# Hormone dataclass
# ---------------------------------------------------------------------------

class TestHormone:
    def test_basic_creation(self):
        h = Hormone(name="test_signal", gland="test_gland")
        assert h.name == "test_signal"
        assert h.gland == "test_gland"
        assert h.value == 0.0
        assert h.unit == ""

    def test_in_band_true(self):
        h = Hormone(name="x", gland="g", value=5.0, target_low=1.0, target_high=10.0)
        assert h.in_band is True

    def test_in_band_low_boundary(self):
        h = Hormone(name="x", gland="g", value=1.0, target_low=1.0, target_high=10.0)
        assert h.in_band is True

    def test_in_band_high_boundary(self):
        h = Hormone(name="x", gland="g", value=10.0, target_low=1.0, target_high=10.0)
        assert h.in_band is True

    def test_in_band_below(self):
        h = Hormone(name="x", gland="g", value=0.5, target_low=1.0, target_high=10.0)
        assert h.in_band is False

    def test_in_band_above(self):
        h = Hormone(name="x", gland="g", value=15.0, target_low=1.0, target_high=10.0)
        assert h.in_band is False

    def test_classification_balanced(self):
        h = Hormone(name="x", gland="g", value=5.0, target_low=1.0, target_high=10.0)
        assert h.classification == "balanced"

    def test_classification_hypo(self):
        h = Hormone(name="x", gland="g", value=0.5, target_low=1.0, target_high=10.0)
        assert h.classification == "hypo"

    def test_classification_hyper(self):
        h = Hormone(name="x", gland="g", value=15.0, target_low=1.0, target_high=10.0)
        assert h.classification == "hyper"

    def test_band_fraction_all_in(self):
        h = Hormone(
            name="x", gland="g", value=5.0,
            target_low=1.0, target_high=10.0,
            samples=[2.0, 3.0, 5.0, 7.0, 9.0],
        )
        assert h.band_fraction() == 1.0

    def test_band_fraction_none_in(self):
        h = Hormone(
            name="x", gland="g", value=5.0,
            target_low=1.0, target_high=10.0,
            samples=[0.1, 0.2, 11.0, 12.0],
        )
        assert h.band_fraction() == 0.0

    def test_band_fraction_partial(self):
        h = Hormone(
            name="x", gland="g", value=5.0,
            target_low=1.0, target_high=10.0,
            samples=[2.0, 5.0, 0.5, 15.0],
        )
        assert h.band_fraction() == 0.5

    def test_band_fraction_empty_samples_uses_value(self):
        h_in = Hormone(name="x", gland="g", value=5.0, target_low=1.0, target_high=10.0)
        assert h_in.band_fraction() == 1.0

        h_out = Hormone(name="x", gland="g", value=0.5, target_low=1.0, target_high=10.0)
        assert h_out.band_fraction() == 0.0

    def test_normalised_deviation_at_centre(self):
        h = Hormone(
            name="x", gland="g", value=5.0,
            target_low=0.0, target_high=10.0,
            samples=[5.0],
        )
        assert h.normalised_deviation() == 0.0

    def test_normalised_deviation_off_centre(self):
        h = Hormone(
            name="x", gland="g", value=7.0,
            target_low=0.0, target_high=10.0,
            samples=[7.0],
        )
        assert h.normalised_deviation() == pytest.approx(0.2)

    def test_normalised_deviation_no_samples(self):
        h = Hormone(name="x", gland="g", value=5.0, target_low=0.0, target_high=10.0)
        assert h.normalised_deviation() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# FeedbackLoop dataclass
# ---------------------------------------------------------------------------

class TestFeedbackLoop:
    def test_basic_creation(self):
        fl = FeedbackLoop(
            hormone="writer_rate", sensor="writer_heartbeat",
            actuator="writer_recovery",
        )
        assert fl.hormone == "writer_rate"
        assert fl.effective is False

    def test_to_dict(self):
        fl = FeedbackLoop(
            hormone="writer_rate", sensor="s", actuator="a",
            target_band=(2.0, 8.0), latency_s=30.0, effective=True,
        )
        d = fl.to_dict()
        assert d["hormone"] == "writer_rate"
        assert d["target_band"] == [2.0, 8.0]
        assert d["latency_s"] == 30.0
        assert d["effective"] is True


# ---------------------------------------------------------------------------
# Imbalance dataclass
# ---------------------------------------------------------------------------

class TestImbalance:
    def test_to_dict(self):
        imb = Imbalance(
            hormone="writer_rate", kind="hypo", severity="severe",
            detail="writer_rate=0.5",
        )
        d = imb.to_dict()
        assert d == {
            "hormone": "writer_rate",
            "kind": "hypo",
            "severity": "severe",
            "detail": "writer_rate=0.5",
        }


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_classify_commit_substantive(self):
        assert _classify_commit("feat: add repo_endocrine_system.py") == "substantive"

    def test_classify_commit_trivial_flush(self):
        assert _classify_commit("flush writer strokes") == "trivial"

    def test_classify_commit_trivial_catchup(self):
        assert _classify_commit("catch-up: commit pending changes") == "trivial"

    def test_classify_commit_trivial_typo(self):
        assert _classify_commit("fix typo in README") == "trivial"

    def test_count_pushes_from_log(self):
        lines = [
            "abc1234 catch-up: commit pending changes",
            "def5678 caretaker visit 350: add module",
            "ghi9012 push coordinator fix",
        ]
        assert _count_pushes_from_log(lines) == 2  # "catch-up" + "push"

    def test_count_pushes_from_log_empty(self):
        assert _count_pushes_from_log([]) == 0

    def test_count_uncommitted_empty_repo(self):
        with tempfile.TemporaryDirectory() as td:
            os.system(f"cd {td} && git init -q")
            assert _count_uncommitted(td) == 0

    def test_count_uncommitted_with_changes(self):
        with tempfile.TemporaryDirectory() as td:
            os.system(f"cd {td} && git init -q && git commit --allow-empty -m init -q")
            (Path(td) / "new_file.py").write_text("# hello")
            assert _count_uncommitted(td) == 1

    def test_list_modules_no_dir(self):
        with tempfile.TemporaryDirectory() as td:
            assert _list_modules(td) == []

    def test_list_modules_with_files(self):
        with tempfile.TemporaryDirectory() as td:
            pkg = Path(td) / "iamai"
            pkg.mkdir()
            (pkg / "foo.py").write_text("# foo")
            (pkg / "bar.py").write_text("# bar")
            result = _list_modules(td)
            assert len(result) == 2

    def test_module_has_docstring_true(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write('"""This is a docstring."""\n')
            f.flush()
            assert _module_has_docstring(Path(f.name)) is True
            os.unlink(f.name)

    def test_module_has_docstring_false(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("# no docstring here\nimport os\n")
            f.flush()
            assert _module_has_docstring(Path(f.name)) is False
            os.unlink(f.name)

    def test_module_line_count(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("line1\nline2\nline3\n")
            f.flush()
            assert _module_line_count(Path(f.name)) == 3
            os.unlink(f.name)

    def test_most_recent_test_mtime_no_dir(self):
        with tempfile.TemporaryDirectory() as td:
            assert _most_recent_test_mtime(td) == 0.0

    def test_most_recent_test_mtime_with_tests(self):
        with tempfile.TemporaryDirectory() as td:
            tests = Path(td) / "tests"
            tests.mkdir()
            tf = tests / "test_foo.py"
            tf.write_text("# test")
            mtime = _most_recent_test_mtime(td)
            assert mtime > 0

    def test_read_strokes_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            assert _read_strokes(td) == []

    def test_read_strokes_valid(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir()
            sf = data / "strokes.jsonl"
            sf.write_text(
                '{"ts": 1000, "kind": "garden"}\n'
                '{"ts": 1060, "kind": "note"}\n'
            )
            strokes = _read_strokes(td)
            assert len(strokes) == 2
            assert strokes[0]["kind"] == "garden"

    def test_read_strokes_malformed_lines(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir()
            sf = data / "strokes.jsonl"
            sf.write_text(
                '{"ts": 1000}\n'
                'not json\n'
                '{"ts": 1060}\n'
            )
            strokes = _read_strokes(td)
            assert len(strokes) == 2

    def test_git_log_no_repo(self):
        with tempfile.TemporaryDirectory() as td:
            assert _git_log(td) == []


# ---------------------------------------------------------------------------
# EndocrineAnalyzer — construction
# ---------------------------------------------------------------------------

class TestAnalyzerConstruction:
    def test_default_init(self):
        a = EndocrineAnalyzer()
        assert len(a.hormone_defs) == len(DEFAULT_HORMONES)
        assert len(a.loop_defs) == len(DEFAULT_LOOPS)

    def test_custom_hormones(self):
        custom = [{"name": "custom", "gland": "g", "target_low": 0, "target_high": 1}]
        a = EndocrineAnalyzer(hormone_defs=custom)
        assert len(a.hormone_defs) == 1

    def test_custom_loops(self):
        custom = [{"hormone": "x", "sensor": "s", "actuator": "a"}]
        a = EndocrineAnalyzer(loop_defs=custom)
        assert len(a.loop_defs) == 1


# ---------------------------------------------------------------------------
# EndocrineAnalyzer — hormone measurements
# ---------------------------------------------------------------------------

class TestAnalyzerMeasurements:
    def test_measure_writer_rate_no_strokes(self):
        with tempfile.TemporaryDirectory() as td:
            a = EndocrineAnalyzer(repo_root=td)
            assert a._measure_writer_rate() == 0.0

    def test_measure_writer_rate_with_strokes(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir()
            sf = data / "strokes.jsonl"
            now = time.time()
            lines = []
            for i in range(10):
                lines.append(json.dumps({"ts": now - (600 - i * 60)}))
            sf.write_text("\n".join(lines))
            a = EndocrineAnalyzer(repo_root=td)
            rate = a._measure_writer_rate()
            assert rate > 0

    def test_measure_writer_rate_single_stroke(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir()
            sf = data / "strokes.jsonl"
            sf.write_text(json.dumps({"ts": time.time()}))
            a = EndocrineAnalyzer(repo_root=td)
            assert a._measure_writer_rate() == 0.0

    def test_measure_commit_density_no_log(self):
        with tempfile.TemporaryDirectory() as td:
            os.system(f"cd {td} && git init -q")
            a = EndocrineAnalyzer(repo_root=td)
            assert a._measure_commit_density() == 0.0

    def test_measure_backlog_pressure_clean(self):
        with tempfile.TemporaryDirectory() as td:
            os.system(f"cd {td} && git init -q && git commit --allow-empty -m init -q")
            a = EndocrineAnalyzer(repo_root=td)
            assert a._measure_backlog_pressure() == 0.0

    def test_measure_backlog_pressure_dirty(self):
        with tempfile.TemporaryDirectory() as td:
            os.system(f"cd {td} && git init -q && git commit --allow-empty -m init -q")
            (Path(td) / "new.py").write_text("# new")
            (Path(td) / "new2.py").write_text("# new2")
            a = EndocrineAnalyzer(repo_root=td)
            assert a._measure_backlog_pressure() == 2.0

    def test_measure_test_freshness_no_tests(self):
        with tempfile.TemporaryDirectory() as td:
            a = EndocrineAnalyzer(repo_root=td, sample_window=7200)
            freshness = a._measure_test_freshness()
            assert freshness == pytest.approx(2.0)  # 7200/3600

    def test_measure_doc_coverage_no_modules(self):
        with tempfile.TemporaryDirectory() as td:
            a = EndocrineAnalyzer(repo_root=td)
            assert a._measure_doc_coverage() == 0.0

    def test_measure_doc_coverage_with_modules(self):
        with tempfile.TemporaryDirectory() as td:
            pkg = Path(td) / "iamai"
            pkg.mkdir()
            (pkg / "good.py").write_text('"""docstring"""\n')
            (pkg / "bad.py").write_text("# no docstring\n")
            a = EndocrineAnalyzer(repo_root=td)
            assert a._measure_doc_coverage() == pytest.approx(0.5)

    def test_measure_doc_coverage_all_documented(self):
        with tempfile.TemporaryDirectory() as td:
            pkg = Path(td) / "iamai"
            pkg.mkdir()
            for name in ["a.py", "b.py", "c.py"]:
                (pkg / name).write_text(f'"""docstring for {name}"""\n')
            a = EndocrineAnalyzer(repo_root=td)
            assert a._measure_doc_coverage() == pytest.approx(1.0)

    def test_measure_stall_duration_writer_not_running(self):
        with tempfile.TemporaryDirectory() as td:
            a = EndocrineAnalyzer(repo_root=td, sample_window=600)
            with mock.patch("iamai.repo_endocrine_system.Path.exists", return_value=False):
                assert a._measure_stall_duration() == 600.0

    def test_measure_stall_duration_writer_running(self):
        with tempfile.TemporaryDirectory() as td:
            pid_file = Path("/tmp/iamai-writer-qwen.pid")
            # Write current process PID
            pid_file.write_text(str(os.getpid()))
            try:
                data = Path(td) / "data"
                data.mkdir()
                state_file = data / "writer_state.qwen.json"
                state_file.write_text(json.dumps({
                    "last_stroke_ts": time.time() - 30
                }))
                a = EndocrineAnalyzer(repo_root=td)
                stall = a._measure_stall_duration()
                assert 0 <= stall <= 60
            finally:
                pid_file.unlink(missing_ok=True)

    def test_measure_all_hormones_returns_list(self):
        with tempfile.TemporaryDirectory() as td:
            os.system(f"cd {td} && git init -q")
            a = EndocrineAnalyzer(repo_root=td)
            hormones = a.measure_hormones()
            assert len(hormones) == len(DEFAULT_HORMONES)
            for h in hormones:
                assert isinstance(h, Hormone)
                assert isinstance(h.value, float)


# ---------------------------------------------------------------------------
# EndocrineAnalyzer — feedback loops
# ---------------------------------------------------------------------------

class TestAnalyzerLoops:
    def test_analyze_loops_all(self):
        with tempfile.TemporaryDirectory() as td:
            os.system(f"cd {td} && git init -q")
            a = EndocrineAnalyzer(repo_root=td)
            hormones = a.measure_hormones()
            loops = a.analyze_loops(hormones)
            assert len(loops) == len(DEFAULT_LOOPS)
            for l in loops:
                assert isinstance(l, FeedbackLoop)

    def test_loop_effectiveness_balanced_hormone(self):
        h = Hormone(name="writer_rate", gland="g", value=5.0,
                     target_low=2.0, target_high=8.0)
        a = EndocrineAnalyzer()
        loops = a.analyze_loops([h])
        writer_loop = [l for l in loops if l.hormone == "writer_rate"][0]
        assert writer_loop.effective is True

    def test_loop_effectiveness_unbalanced_hormone(self):
        h = Hormone(name="writer_rate", gland="g", value=0.5,
                     target_low=2.0, target_high=8.0)
        a = EndocrineAnalyzer()
        loops = a.analyze_loops([h])
        writer_loop = [l for l in loops if l.hormone == "writer_rate"][0]
        assert writer_loop.effective is False


# ---------------------------------------------------------------------------
# EndocrineAnalyzer — imbalance detection
# ---------------------------------------------------------------------------

class TestImbalanceDetection:
    def test_no_imbalances_when_balanced(self):
        hormones = [
            Hormone(name="x", gland="g", value=5.0, target_low=1.0, target_high=10.0),
        ]
        a = EndocrineAnalyzer()
        imbalances = a.detect_imbalances(hormones)
        assert len(imbalances) == 0

    def test_hypo_imbalance(self):
        hormones = [
            Hormone(name="x", gland="g", value=0.1, target_low=1.0, target_high=10.0),
        ]
        a = EndocrineAnalyzer()
        imbalances = a.detect_imbalances(hormones)
        assert len(imbalances) == 1
        assert imbalances[0].kind == "hypo"

    def test_hyper_imbalance(self):
        hormones = [
            Hormone(name="x", gland="g", value=20.0, target_low=1.0, target_high=10.0),
        ]
        a = EndocrineAnalyzer()
        imbalances = a.detect_imbalances(hormones)
        assert len(imbalances) == 1
        assert imbalances[0].kind == "hyper"

    def test_severity_mild(self):
        hormones = [
            Hormone(name="x", gland="g", value=55.0, target_low=0.0, target_high=50.0),
        ]
        a = EndocrineAnalyzer()
        imbalances = a.detect_imbalances(hormones)
        assert imbalances[0].severity == "mild"

    def test_severity_severe(self):
        hormones = [
            Hormone(name="x", gland="g", value=50.0, target_low=1.0, target_high=10.0),
        ]
        a = EndocrineAnalyzer()
        imbalances = a.detect_imbalances(hormones)
        assert imbalances[0].severity == "severe"

    def test_multiple_imbalances(self):
        hormones = [
            Hormone(name="a", gland="g", value=0.1, target_low=1.0, target_high=5.0),
            Hormone(name="b", gland="g", value=20.0, target_low=1.0, target_high=5.0),
            Hormone(name="c", gland="g", value=3.0, target_low=1.0, target_high=5.0),
        ]
        a = EndocrineAnalyzer()
        imbalances = a.detect_imbalances(hormones)
        assert len(imbalances) == 2  # a and b, not c


# ---------------------------------------------------------------------------
# EndocrineAnalyzer — receptor resistance
# ---------------------------------------------------------------------------

class TestReceptorResistance:
    def test_no_resistance_when_balanced(self):
        hormones = [
            Hormone(name="x", gland="g", value=5.0, target_low=1.0, target_high=10.0),
        ]
        loops = [
            FeedbackLoop(hormone="x", sensor="s", actuator="a", effective=True),
        ]
        a = EndocrineAnalyzer()
        resistance = a.detect_receptor_resistance(hormones, loops)
        assert len(resistance) == 0

    def test_resistance_detected(self):
        hormones = [
            Hormone(name="x", gland="g", value=0.1, target_low=1.0, target_high=10.0),
        ]
        loops = [
            FeedbackLoop(hormone="x", sensor="s", actuator="a", effective=False),
        ]
        a = EndocrineAnalyzer()
        resistance = a.detect_receptor_resistance(hormones, loops)
        assert len(resistance) == 1
        assert resistance[0].kind == "receptor_resistance"

    def test_no_resistance_without_loop(self):
        hormones = [
            Hormone(name="x", gland="g", value=0.1, target_low=1.0, target_high=10.0),
        ]
        a = EndocrineAnalyzer()
        resistance = a.detect_receptor_resistance(hormones, [])
        assert len(resistance) == 0

    def test_resistance_severity(self):
        hormones = [
            Hormone(name="x", gland="g", value=50.0, target_low=1.0, target_high=10.0),
        ]
        loops = [
            FeedbackLoop(hormone="x", sensor="s", actuator="a", effective=False),
        ]
        a = EndocrineAnalyzer()
        resistance = a.detect_receptor_resistance(hormones, loops)
        assert resistance[0].severity == "severe"


# ---------------------------------------------------------------------------
# EndocrineAnalyzer — scoring
# ---------------------------------------------------------------------------

class TestScoring:
    def test_perfect_score_all_balanced(self):
        hormones = [
            Hormone(name="writer_rate", gland="g", value=5.0,
                     target_low=2.0, target_high=8.0),
            Hormone(name="commit_density", gland="g", value=0.8,
                     target_low=0.6, target_high=1.0),
        ]
        loops = [
            FeedbackLoop(hormone="writer_rate", sensor="s", actuator="a", effective=True),
            FeedbackLoop(hormone="commit_density", sensor="s", actuator="a", effective=True),
        ]
        a = EndocrineAnalyzer()
        score = a.compute_score(hormones, loops)
        assert score >= 90.0

    def test_zero_score_no_hormones(self):
        a = EndocrineAnalyzer()
        assert a.compute_score([], []) == 0.0

    def test_low_score_all_imbalanced(self):
        hormones = [
            Hormone(name="writer_rate", gland="g", value=0.0,
                     target_low=2.0, target_high=8.0, samples=[0.0]),
            Hormone(name="commit_density", gland="g", value=0.0,
                     target_low=0.6, target_high=1.0, samples=[0.0]),
        ]
        a = EndocrineAnalyzer()
        score = a.compute_score(hormones, [])
        assert score < 20.0

    def test_score_never_exceeds_100(self):
        hormones = [
            Hormone(name="writer_rate", gland="g", value=5.0,
                     target_low=2.0, target_high=8.0),
        ]
        loops = [
            FeedbackLoop(hormone="writer_rate", sensor="s", actuator="a", effective=True),
        ]
        a = EndocrineAnalyzer()
        score = a.compute_score(hormones, loops)
        assert score <= 100.0

    def test_loop_bonus_capped(self):
        hormones = [
            Hormone(name="writer_rate", gland="g", value=5.0,
                     target_low=2.0, target_high=8.0),
        ]
        loops = [
            FeedbackLoop(hormone="writer_rate", sensor=f"s{i}", actuator=f"a{i}", effective=True)
            for i in range(20)
        ]
        a = EndocrineAnalyzer()
        score = a.compute_score(hormones, loops)
        assert score <= 100.0


# ---------------------------------------------------------------------------
# EndocrineAnalyzer — end-to-end analyze()
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_analyze_returns_report(self):
        with tempfile.TemporaryDirectory() as td:
            os.system(f"cd {td} && git init -q && git commit --allow-empty -m init -q")
            a = EndocrineAnalyzer(repo_root=td)
            report = a.analyze()
            assert "endocrine_score" in report
            assert "hormones" in report
            assert "feedback_loops" in report
            assert "imbalances" in report
            assert "receptor_resistance" in report
            assert "effective_loops" in report
            assert "total_loops" in report
            assert "total_hormones" in report

    def test_analyze_score_range(self):
        with tempfile.TemporaryDirectory() as td:
            os.system(f"cd {td} && git init -q && git commit --allow-empty -m init -q")
            a = EndocrineAnalyzer(repo_root=td)
            report = a.analyze()
            assert 0.0 <= report["endocrine_score"] <= 100.0

    def test_analyze_hormone_count(self):
        with tempfile.TemporaryDirectory() as td:
            os.system(f"cd {td} && git init -q")
            a = EndocrineAnalyzer(repo_root=td)
            report = a.analyze()
            assert report["total_hormones"] == len(DEFAULT_HORMONES)

    def test_analyze_loop_count(self):
        with tempfile.TemporaryDirectory() as td:
            os.system(f"cd {td} && git init -q")
            a = EndocrineAnalyzer(repo_root=td)
            report = a.analyze()
            assert report["total_loops"] == len(DEFAULT_LOOPS)

    def test_analyze_hormone_fields(self):
        with tempfile.TemporaryDirectory() as td:
            os.system(f"cd {td} && git init -q")
            a = EndocrineAnalyzer(repo_root=td)
            report = a.analyze()
            for h in report["hormones"]:
                assert "name" in h
                assert "gland" in h
                assert "value" in h
                assert "unit" in h
                assert "target" in h
                assert "classification" in h
                assert "band_fraction" in h

    def test_analyze_custom_hormones(self):
        custom_h = [{"name": "custom", "gland": "g", "target_low": 0, "target_high": 1}]
        custom_l = [{"hormone": "custom", "sensor": "s", "actuator": "a"}]
        with tempfile.TemporaryDirectory() as td:
            os.system(f"cd {td} && git init -q")
            a = EndocrineAnalyzer(repo_root=td, hormone_defs=custom_h, loop_defs=custom_l)
            report = a.analyze()
            assert report["total_hormones"] == 1
            assert report["total_loops"] == 1

    def test_analyze_json_serializable(self):
        with tempfile.TemporaryDirectory() as td:
            os.system(f"cd {td} && git init -q")
            a = EndocrineAnalyzer(repo_root=td)
            report = a.analyze()
            # Should not raise
            json_str = json.dumps(report)
            assert len(json_str) > 0

    def test_analyze_on_real_repo_structure(self):
        """Test on a repo with a realistic iamai/ package."""
        with tempfile.TemporaryDirectory() as td:
            os.system(f"cd {td} && git init -q && git commit --allow-empty -m init -q")
            pkg = Path(td) / "iamai"
            pkg.mkdir()
            for name in ["writer.py", "batch.py", "push.py"]:
                (pkg / name).write_text(f'"""Module {name}."""\nimport os\n')
            tests = Path(td) / "tests"
            tests.mkdir()
            (tests / "test_writer.py").write_text("# test\n")
            data = Path(td) / "data"
            data.mkdir()
            now = time.time()
            strokes = "\n".join(
                json.dumps({"ts": now - i * 15}) for i in range(20)
            )
            (data / "strokes.jsonl").write_text(strokes)
            a = EndocrineAnalyzer(repo_root=td)
            report = a.analyze()
            assert report["total_hormones"] == len(DEFAULT_HORMONES)
            # doc_coverage should be 1.0 (all have docstrings)
            doc_h = [h for h in report["hormones"] if h["name"] == "doc_coverage"][0]
            assert doc_h["value"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Default definitions integrity
# ---------------------------------------------------------------------------

class TestDefaultDefinitions:
    def test_default_hormones_count(self):
        assert len(DEFAULT_HORMONES) == 8

    def test_default_loops_count(self):
        assert len(DEFAULT_LOOPS) == 8

    def test_every_hormone_has_loop(self):
        hormone_names = {h["name"] for h in DEFAULT_HORMONES}
        loop_hormones = {l["hormone"] for l in DEFAULT_LOOPS}
        assert hormone_names == loop_hormones

    def test_hormone_fields(self):
        required = {"name", "gland", "target_low", "target_high"}
        for h in DEFAULT_HORMONES:
            assert required.issubset(h.keys())

    def test_loop_fields(self):
        required = {"hormone", "sensor", "actuator"}
        for l in DEFAULT_LOOPS:
            assert required.issubset(l.keys())

    def test_target_bands_consistent(self):
        """Each loop's target_band should match its hormone's targets."""
        h_map = {h["name"]: h for h in DEFAULT_HORMONES}
        for l in DEFAULT_LOOPS:
            h = h_map[l["hormone"]]
            band = l.get("target_band", (h["target_low"], h["target_high"]))
            assert band[0] == pytest.approx(h["target_low"])
            assert band[1] == pytest.approx(h["target_high"])
