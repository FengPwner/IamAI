"""Tests for iamai.writer_paragraph_structure — paragraph-level analysis."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from iamai.writer_paragraph_structure import (
    _classify_structure,
    _count_sentences,
    _has_transition_marker,
    _load_strokes,
    _mean,
    _split_paragraphs,
    _std,
    compute_structure,
    structure_report,
    structure_summary,
)

# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------


class TestMean:
    def test_empty(self):
        assert _mean([]) == 0.0

    def test_single(self):
        assert _mean([5.0]) == 5.0

    def test_multiple(self):
        assert _mean([2.0, 4.0, 6.0]) == pytest.approx(4.0)

    def test_negative(self):
        assert _mean([-1.0, 1.0]) == pytest.approx(0.0)


class TestStd:
    def test_empty(self):
        assert _std([]) == 0.0

    def test_single(self):
        assert _std([5.0]) == 0.0

    def test_uniform(self):
        assert _std([3.0, 3.0, 3.0]) == 0.0

    def test_known(self):
        # std of [2, 4, 4, 4, 5, 5, 7, 9] with ddof=1 ≈ 2.0
        assert _std([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]) == pytest.approx(2.0, abs=0.15)


# ---------------------------------------------------------------------------
# Paragraph splitting
# ---------------------------------------------------------------------------


class TestSplitParagraphs:
    def test_empty(self):
        assert _split_paragraphs("") == []

    def test_whitespace_only(self):
        assert _split_paragraphs("   \n  \n  ") == []

    def test_single_paragraph(self):
        result = _split_paragraphs("Hello world. This is a test.")
        assert len(result) == 1
        assert "Hello world" in result[0]

    def test_two_paragraphs(self):
        text = "First paragraph here.\n\nSecond paragraph here."
        result = _split_paragraphs(text)
        assert len(result) == 2
        assert "First" in result[0]
        assert "Second" in result[1]

    def test_multiple_blank_lines(self):
        text = "Para one.\n\n\n\nPara two.\n\n\nPara three."
        result = _split_paragraphs(text)
        assert len(result) == 3

    def test_crlf_handling(self):
        text = "Line one.\r\n\r\nLine two."
        result = _split_paragraphs(text)
        assert len(result) == 2

    def test_indented_blank_lines(self):
        text = "Para A.\n   \nPara B."
        result = _split_paragraphs(text)
        assert len(result) == 2

    def test_no_double_newline_single_block(self):
        text = "Sentence one. Sentence two. Sentence three."
        result = _split_paragraphs(text)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Sentence counting
# ---------------------------------------------------------------------------


class TestCountSentences:
    def test_empty(self):
        assert _count_sentences("") == 0

    def test_one_sentence(self):
        assert _count_sentences("Hello world.") == 1

    def test_multiple_sentences(self):
        assert _count_sentences("First. Second. Third.") == 3

    def test_question_and_exclamation(self):
        assert _count_sentences("Really? Yes! OK.") == 3

    def test_whitespace_only(self):
        assert _count_sentences("   ") == 0

    def test_no_terminator(self):
        # Text without sentence terminators is treated as one fragment
        assert _count_sentences("no terminator here") == 1


# ---------------------------------------------------------------------------
# Transition markers
# ---------------------------------------------------------------------------


class TestHasTransitionMarker:
    def test_empty(self):
        assert _has_transition_marker("") is False

    def test_with_but(self):
        assert _has_transition_marker("But this is different. And more.") is True

    def test_with_however(self):
        assert _has_transition_marker("However, the results differ.") is True

    def test_with_therefore(self):
        assert _has_transition_marker("Therefore we conclude this.") is True

    def test_with_because(self):
        assert _has_transition_marker("Because of this, we change.") is True

    def test_no_marker(self):
        assert _has_transition_marker("The sky is blue today.") is False

    def test_marker_in_second_sentence_ignored(self):
        # Only the first sentence should be checked
        assert _has_transition_marker("The sky is blue. But clouds exist.") is False

    def test_case_insensitive(self):
        assert _has_transition_marker("HOWEVER, this works.") is True

    def test_while(self):
        assert _has_transition_marker("While this is true, other factors matter.") is True

    def test_since(self):
        assert _has_transition_marker("Since we started, things changed.") is True

    def test_word_boundary(self):
        # "butt" should NOT match "but"
        assert _has_transition_marker("Buttressing the wall is important.") is False


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TestClassifyStructure:
    def test_fragmented(self):
        label = _classify_structure(
            cv=0.9, short_ratio=0.6, long_ratio=0.05,
            single_sentence_ratio=0.55, transition_density=0.1,
            mean_length=1.5,
        )
        assert label == "fragmented"

    def test_dense(self):
        label = _classify_structure(
            cv=0.3, short_ratio=0.05, long_ratio=0.7,
            single_sentence_ratio=0.02, transition_density=0.10,
            mean_length=7.5,
        )
        assert label == "dense"

    def test_essayistic(self):
        label = _classify_structure(
            cv=0.4, short_ratio=0.1, long_ratio=0.55,
            single_sentence_ratio=0.05, transition_density=0.30,
            mean_length=5.5,
        )
        assert label == "essayistic"

    def test_structured(self):
        label = _classify_structure(
            cv=0.20, short_ratio=0.2, long_ratio=0.1,
            single_sentence_ratio=0.1, transition_density=0.15,
            mean_length=3.5,
        )
        assert label == "structured"

    def test_conversational(self):
        label = _classify_structure(
            cv=0.45, short_ratio=0.2, long_ratio=0.15,
            single_sentence_ratio=0.1, transition_density=0.35,
            mean_length=3.5,
        )
        assert label == "conversational"

    def test_balanced_fallback(self):
        label = _classify_structure(
            cv=0.5, short_ratio=0.3, long_ratio=0.2,
            single_sentence_ratio=0.2, transition_density=0.15,
            mean_length=3.0,
        )
        assert label == "balanced"


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


class TestComputeStructure:
    def test_empty_strokes(self):
        result = compute_structure([])
        assert result["total_strokes"] == 0
        assert result["total_paragraphs"] == 0
        assert result["structure_label"] == "fragmented"

    def test_no_text_field(self):
        result = compute_structure([{"other": "data"}])
        assert result["total_paragraphs"] == 0

    def test_empty_text(self):
        result = compute_structure([{"text": ""}])
        assert result["total_paragraphs"] == 0

    def test_single_paragraph_stroke(self):
        strokes = [{"text": "Hello world. This is a test. One more."}]
        result = compute_structure(strokes)
        assert result["total_strokes"] == 1
        assert result["total_paragraphs"] == 1
        assert result["mean_paragraph_length"] == 3.0

    def test_multi_paragraph_stroke(self):
        text = "First sentence. Second sentence.\n\nThird sentence. Fourth."
        strokes = [{"text": text}]
        result = compute_structure(strokes)
        assert result["total_paragraphs"] == 2
        assert result["mean_paragraph_length"] == 2.0

    def test_single_sentence_paragraphs(self):
        text = "One.\n\nTwo.\n\nThree."
        strokes = [{"text": text}]
        result = compute_structure(strokes)
        assert result["total_paragraphs"] == 3
        assert result["single_sentence_ratio"] == 1.0

    def test_transition_counting(self):
        text = "However, this is important.\n\nThe sky is blue."
        strokes = [{"text": text}]
        result = compute_structure(strokes)
        assert result["total_paragraphs"] == 2
        assert result["transition_density"] == 0.5

    def test_multiple_strokes(self):
        strokes = [
            {"text": "First stroke. Two sentences here."},
            {"text": "But second stroke.\n\nAnother paragraph. With two sentences."},
        ]
        result = compute_structure(strokes)
        assert result["total_strokes"] == 2
        assert result["total_paragraphs"] == 3

    def test_all_metrics_present(self):
        strokes = [{"text": "Hello world. Test.\n\nSecond para. Here."}]
        result = compute_structure(strokes)
        expected_keys = {
            "total_strokes", "total_paragraphs", "mean_paragraph_length",
            "std_paragraph_length", "cv", "short_ratio", "medium_ratio",
            "long_ratio", "single_sentence_ratio", "transition_density",
            "structure_label",
        }
        assert set(result.keys()) == expected_keys

    def test_cv_zero_for_uniform(self):
        # All paragraphs have exactly 3 sentences
        text = "A. B. C.\n\nD. E. F.\n\nG. H. I."
        strokes = [{"text": text}]
        result = compute_structure(strokes)
        assert result["cv"] == 0.0

    def test_long_paragraph_detection(self):
        sentences = ". ".join([f"Sentence {i}" for i in range(8)]) + "."
        strokes = [{"text": sentences}]
        result = compute_structure(strokes)
        assert result["long_ratio"] == 1.0


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


class TestStructureReport:
    def test_contains_all_fields(self):
        metrics = {
            "total_strokes": 10,
            "total_paragraphs": 25,
            "mean_paragraph_length": 3.2,
            "std_paragraph_length": 1.5,
            "cv": 0.47,
            "short_ratio": 0.2,
            "medium_ratio": 0.5,
            "long_ratio": 0.3,
            "single_sentence_ratio": 0.1,
            "transition_density": 0.35,
            "structure_label": "conversational",
        }
        report = structure_report(metrics)
        assert "10" in report
        assert "25" in report
        assert "conversational" in report
        assert "transition density" in report

    def test_percentage_formatting(self):
        metrics = {
            "total_strokes": 1,
            "total_paragraphs": 1,
            "mean_paragraph_length": 1.0,
            "std_paragraph_length": 0.0,
            "cv": 0.0,
            "short_ratio": 1.0,
            "medium_ratio": 0.0,
            "long_ratio": 0.0,
            "single_sentence_ratio": 1.0,
            "transition_density": 0.0,
            "structure_label": "fragmented",
        }
        report = structure_report(metrics)
        assert "100.0%" in report
        assert "0.0%" in report


# ---------------------------------------------------------------------------
# On-disk integration
# ---------------------------------------------------------------------------


class TestOnDiskIntegration:
    def _write_strokes(self, tmp_path: Path, texts: list[str]) -> Path:
        p = tmp_path / "strokes.jsonl"
        lines = [json.dumps({"text": t}) for t in texts]
        p.write_text("\n".join(lines), encoding="utf-8")
        return p

    def test_load_strokes(self, tmp_path: Path):
        p = self._write_strokes(tmp_path, ["Hello.", "World."])
        strokes = _load_strokes(p, 10)
        assert len(strokes) == 2

    def test_load_strokes_limit(self, tmp_path: Path):
        p = self._write_strokes(tmp_path, [f"S{i}." for i in range(20)])
        strokes = _load_strokes(p, 5)
        assert len(strokes) == 5

    def test_load_strokes_missing_file(self, tmp_path: Path):
        strokes = _load_strokes(tmp_path / "nope.jsonl", 10)
        assert strokes == []

    def test_load_strokes_bad_json(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        p.write_text('{"text": "ok"}\nnot json\n{"text": "also ok"}\n', encoding="utf-8")
        strokes = _load_strokes(p, 10)
        assert len(strokes) == 2

    def test_structure_summary(self, tmp_path: Path):
        p = self._write_strokes(tmp_path, [
            "Hello world. This is a test.\n\nSecond paragraph. Also two sentences.",
            "But wait. There is more.\n\nHowever, this is the end.",
        ])
        result = structure_summary(strokes_path=p, n=10)
        assert "strokes analysed" in result
        assert "structure label" in result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCLI:
    def _run_cli(self, tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
        strokes_file = tmp_path / "strokes.jsonl"
        if not strokes_file.exists():
            texts = [
                "First stroke. Two sentences.\n\nSecond para. Also two.",
                "But the third. Is different.\n\nHowever the fourth. Matches.",
            ]
            lines = [json.dumps({"text": t}) for t in texts]
            strokes_file.write_text("\n".join(lines), encoding="utf-8")
        cmd = [
            sys.executable, "-m", "iamai.writer_paragraph_structure",
            "--strokes", str(strokes_file),
            *args,
        ]
        return subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
        )

    def test_default_output(self, tmp_path: Path):
        result = self._run_cli(tmp_path)
        assert result.returncode == 0
        assert "strokes analysed" in result.stdout
        assert "structure label" in result.stdout

    def test_json_output(self, tmp_path: Path):
        result = self._run_cli(tmp_path, "--json")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "total_strokes" in data
        assert "structure_label" in data

    def test_count_flag(self, tmp_path: Path):
        result = self._run_cli(tmp_path, "-n", "1")
        assert result.returncode == 0
        assert "strokes analysed" in result.stdout
