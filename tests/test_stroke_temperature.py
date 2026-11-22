"""Tests for iamai.stroke_temperature — writer output health metric.

Visit 808: this module synthesises multiple content health signals
into a single temperature metric (0–1).  It complements existing
diagnostic modules by providing a dashboard-ready summary.

Test areas:
    1. vocabulary_richness  — type-token ratio
    2. kind_balance         — normalised Shannon entropy
    3. length_variation     — inverted CV with bell curve
    4. novelty              — template phrase detection
    5. temperature          — composite weighted score
    6. label                — band classification
    7. temperature_report   — full report structure
    8. temperature_summary  — human-readable format
    9. _cli                 — exit codes, --json flag
   10. edge cases           — empty input, single stroke, all templates
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_temperature import (
    _cli,
    _load_recent_strokes,
    kind_balance,
    label,
    length_variation,
    novelty,
    temperature,
    temperature_report,
    temperature_summary,
    vocabulary_richness,
)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _stroke(kind: str, text: str, seq: int = 0) -> dict:
    return {"seq": seq, "kind": kind, "text": text}


def _write_strokes(tmp_path: Path, strokes: list[dict]) -> Path:
    p = tmp_path / "strokes.jsonl"
    lines = [json.dumps(s) for s in strokes]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# -----------------------------------------------------------------------
# 1. vocabulary_richness
# -----------------------------------------------------------------------


class TestVocabularyRichness:
    def test_all_unique_words(self):
        strokes = [_stroke("thought", "alpha beta gamma delta")]
        assert vocabulary_richness(strokes) == 1.0

    def test_all_identical_words(self):
        strokes = [_stroke("thought", "go go go go go")]
        assert vocabulary_richness(strokes) == pytest.approx(0.2, abs=0.01)

    def test_mixed_vocabulary(self):
        strokes = [
            _stroke("thought", "the cat sat on the mat"),
            _stroke("note", "the dog ran in the park"),
        ]
        # tokens: the(3) cat(1) sat(1) on(1) mat(1) dog(1) ran(1) in(1) park(1)
        # 9 unique / 12 total
        result = vocabulary_richness(strokes)
        assert 0.7 < result < 0.8

    def test_empty_strokes(self):
        assert vocabulary_richness([]) == 0.0

    def test_empty_text(self):
        strokes = [_stroke("thought", "")]
        assert vocabulary_richness(strokes) == 0.0

    def test_case_insensitive(self):
        strokes = [_stroke("thought", "Hello hello HELLO")]
        # all same word after lowering → TTR = 1/3
        assert vocabulary_richness(strokes) == pytest.approx(1 / 3, abs=0.01)


# -----------------------------------------------------------------------
# 2. kind_balance
# -----------------------------------------------------------------------


class TestKindBalance:
    def test_perfect_balance(self):
        strokes = [
            _stroke(k, "test") for k in ["devlog", "garden", "metrics", "note", "snippet", "thought"]
        ] * 10
        result = kind_balance(strokes)
        assert result == pytest.approx(1.0, abs=0.01)

    def test_single_kind(self):
        strokes = [_stroke("thought", "test")] * 20
        assert kind_balance(strokes) == 0.0

    def test_two_kinds_balanced(self):
        strokes = (
            [_stroke("thought", "a")] * 10
            + [_stroke("note", "b")] * 10
        )
        result = kind_balance(strokes)
        # 2 kinds, perfectly balanced → entropy = ln(2), max = ln(2) → 1.0
        assert result == pytest.approx(1.0, abs=0.01)

    def test_skewed_distribution(self):
        strokes = (
            [_stroke("thought", "a")] * 18
            + [_stroke("note", "b")] * 1
            + [_stroke("devlog", "c")] * 1
        )
        result = kind_balance(strokes)
        # heavily skewed → low normalised entropy
        assert 0.0 < result < 0.6

    def test_empty_input(self):
        assert kind_balance([]) == 0.0


# -----------------------------------------------------------------------
# 3. length_variation
# -----------------------------------------------------------------------


class TestLengthVariation:
    def test_identical_lengths(self):
        strokes = [_stroke("thought", "abcde")] * 10  # all len 5
        result = length_variation(strokes)
        # CV = 0 → exp(-(0-0.5)^2 / 0.5) = exp(-0.5) ≈ 0.606
        assert result == pytest.approx(math.exp(-0.5), abs=0.01)

    def test_moderate_variation(self):
        strokes = [
            _stroke("thought", "short"),
            _stroke("note", "a medium length text here"),
            _stroke("devlog", "x"),
            _stroke("garden", "this is a somewhat longer piece of text with more words"),
        ]
        result = length_variation(strokes)
        assert 0.0 < result <= 1.0

    def test_empty_input(self):
        assert length_variation([]) == 0.0

    def test_empty_text(self):
        strokes = [_stroke("thought", "")] * 5
        assert length_variation(strokes) == 0.0

    def test_returns_positive_for_variation(self):
        strokes = [_stroke("thought", "ab")] + [_stroke("note", "abcdefghij")] * 5
        result = length_variation(strokes)
        assert result > 0.0


# -----------------------------------------------------------------------
# 4. novelty
# -----------------------------------------------------------------------


class TestNovelty:
    def test_all_original_content(self):
        strokes = [
            _stroke("thought", "a truly original thought about life"),
            _stroke("note", "notes on the garden design principles"),
            _stroke("devlog", "today I refactored the batch committer"),
        ]
        result = novelty(strokes)
        assert result == 1.0

    def test_all_templated(self):
        strokes = [
            _stroke("thought", "measured now: 6963 strokes written so far into 2659 files"),
            _stroke("thought", "measured now: 6964 strokes written so far into 2659 files"),
            _stroke("thought", "measured now: commit 1171: the count of times this repo was pushed"),
        ]
        result = novelty(strokes)
        assert result == 0.0

    def test_mixed_content(self):
        strokes = [
            _stroke("thought", "measured now: 100 strokes written so far into 50 files"),
            _stroke("note", "an original note about software design patterns"),
        ]
        result = novelty(strokes)
        assert result == pytest.approx(0.5, abs=0.01)

    def test_empty_input(self):
        assert novelty([]) == 0.0

    def test_custom_templates(self):
        strokes = [
            _stroke("thought", "CUSTOM_PATTERN: value 42"),
            _stroke("note", "something completely different"),
        ]
        result = novelty(strokes, templates=["custom_pattern:"])
        assert 0.0 < result < 1.0

    def test_empty_text_counts_as_template(self):
        strokes = [_stroke("thought", "")]
        result = novelty(strokes)
        assert result == 0.0


# -----------------------------------------------------------------------
# 5. temperature (composite)
# -----------------------------------------------------------------------


class TestTemperature:
    def test_healthy_writer(self):
        """All signals healthy → high temperature."""
        strokes = [
            _stroke(k, f"unique original text about {k} topic number {i}")
            for k in ["devlog", "garden", "metrics", "note", "snippet", "thought"]
            for i in range(10)
        ]
        result = temperature(strokes)
        assert result >= 0.5

    def test_formulaic_writer(self):
        """All strokes are templates of same kind → low temperature."""
        strokes = [
            _stroke("thought", "measured now: 100 strokes written so far into 50 files")
        ] * 20
        result = temperature(strokes)
        assert result < 0.4

    def test_empty_input(self):
        assert temperature([]) == 0.0

    def test_result_in_range(self):
        strokes = [_stroke("thought", "some text")] * 5
        result = temperature(strokes)
        assert 0.0 <= result <= 1.0


# -----------------------------------------------------------------------
# 6. label
# -----------------------------------------------------------------------


class TestLabel:
    def test_hot(self):
        assert label(0.85) == "hot"
        assert label(0.70) == "hot"

    def test_warm(self):
        assert label(0.55) == "warm"
        assert label(0.40) == "warm"

    def test_cool(self):
        assert label(0.30) == "cool"
        assert label(0.20) == "cool"

    def test_cold(self):
        assert label(0.10) == "cold"
        assert label(0.0) == "cold"


# -----------------------------------------------------------------------
# 7. temperature_report
# -----------------------------------------------------------------------


class TestTemperatureReport:
    def test_report_keys(self, tmp_path):
        strokes = [_stroke("thought", "hello world")] * 5
        path = _write_strokes(tmp_path, strokes)
        report = temperature_report(n_strokes=5, path=path)
        expected_keys = {
            "n_strokes_analysed", "temperature", "label",
            "vocabulary_richness", "kind_balance", "length_variation",
            "novelty",
        }
        assert set(report.keys()) == expected_keys

    def test_report_values_types(self, tmp_path):
        strokes = [_stroke("thought", "hello world")] * 5
        path = _write_strokes(tmp_path, strokes)
        report = temperature_report(n_strokes=5, path=path)
        assert isinstance(report["n_strokes_analysed"], int)
        assert isinstance(report["temperature"], float)
        assert isinstance(report["label"], str)

    def test_report_n_strokes(self, tmp_path):
        strokes = [_stroke("thought", f"text {i}") for i in range(20)]
        path = _write_strokes(tmp_path, strokes)
        report = temperature_report(n_strokes=10, path=path)
        assert report["n_strokes_analysed"] == 10

    def test_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.jsonl"
        report = temperature_report(path=path)
        assert report["n_strokes_analysed"] == 0
        assert report["temperature"] == 0.0


# -----------------------------------------------------------------------
# 8. temperature_summary
# -----------------------------------------------------------------------


class TestTemperatureSummary:
    def test_summary_format(self, tmp_path):
        strokes = [_stroke("thought", "hello world foo bar")] * 5
        path = _write_strokes(tmp_path, strokes)
        summary = temperature_summary(n_strokes=5, path=path)
        assert "temperature:" in summary
        assert "vocab" in summary
        assert "kind" in summary
        assert "length" in summary
        assert "novelty" in summary
        assert "strokes" in summary

    def test_summary_contains_label(self, tmp_path):
        strokes = [_stroke("thought", "hello world")] * 5
        path = _write_strokes(tmp_path, strokes)
        summary = temperature_summary(n_strokes=5, path=path)
        # label should be one of the known bands
        assert any(b in summary for b in ["hot", "warm", "cool", "cold"])


# -----------------------------------------------------------------------
# 9. _cli
# -----------------------------------------------------------------------


class TestCli:
    def test_text_output(self, tmp_path, capsys):
        strokes = [_stroke("thought", "hello world")] * 5
        path = _write_strokes(tmp_path, strokes)
        exit_code = _cli(["--n", "5", "--path", str(path)])
        captured = capsys.readouterr()
        assert "temperature:" in captured.out
        assert exit_code in (0, 1)

    def test_json_output(self, tmp_path, capsys):
        strokes = [_stroke("thought", "hello world")] * 5
        path = _write_strokes(tmp_path, strokes)
        exit_code = _cli(["--n", "5", "--path", str(path), "--json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "temperature" in data
        assert "label" in data

    def test_exit_code_healthy(self, tmp_path):
        strokes = [
            _stroke(k, f"unique original text about {k} number {i}")
            for k in ["devlog", "garden", "metrics", "note", "snippet", "thought"]
            for i in range(10)
        ]
        path = _write_strokes(tmp_path, strokes)
        exit_code = _cli(["--n", str(len(strokes)), "--path", str(path)])
        # healthy/warm → exit 0
        assert exit_code == 0

    def test_exit_code_cold(self, tmp_path):
        strokes = [
            _stroke("thought", "measured now: 100 strokes written so far into 50 files")
        ] * 20
        path = _write_strokes(tmp_path, strokes)
        exit_code = _cli(["--n", "20", "--path", str(path)])
        # cool/cold → exit 1
        assert exit_code == 1


# -----------------------------------------------------------------------
# 10. edge cases
# -----------------------------------------------------------------------


class TestEdgeCases:
    def test_single_stroke(self):
        strokes = [_stroke("thought", "just one stroke")]
        # kind_balance should be 0 (only one kind)
        assert kind_balance(strokes) == 0.0
        # vocabulary_richness should be 1.0 (all words unique)
        assert vocabulary_richness(strokes) == 1.0
        # temperature should be > 0 but low due to single kind
        t = temperature(strokes)
        assert 0.0 < t < 1.0

    def test_malformed_jsonl(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            '{"seq":1,"kind":"thought","text":"good"}\n'
            'NOT VALID JSON\n'
            '{"seq":2,"kind":"note","text":"also good"}\n',
            encoding="utf-8",
        )
        strokes = _load_recent_strokes(path=p)
        assert len(strokes) == 2

    def test_large_n_with_few_strokes(self, tmp_path):
        strokes = [_stroke("thought", "only one")] 
        path = _write_strokes(tmp_path, strokes)
        report = temperature_report(n_strokes=1000, path=path)
        assert report["n_strokes_analysed"] == 1
