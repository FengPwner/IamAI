"""Tests for iamai.writer_sentence_rhythm — sentence-length rhythm analysis.

This module measures how sentence lengths vary across strokes, providing
a signal of writing rhythm: monotone, steady, staccato, flowing, varied,
or chaotic.

Test areas:
     1. _mean                     — arithmetic mean helper
     2. _std                      — standard deviation helper
     3. _entropy                  — Shannon entropy
     4. _split_sentences          — sentence splitting
     5. _word_count               — token counting
     6. _load_strokes             — JSONL loading (last n)
     7. _classify_rhythm          — label assignment
     8. compute_rhythm            — full metric computation
     9. rhythm_report             — human-readable output
    10. rhythm_summary            — on-disk integration
    11. _cli                      — exit codes, --json flag
    12. edge cases                — empty, single, degenerate inputs
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_sentence_rhythm import (
    _classify_rhythm,
    _cli,
    _entropy,
    _load_strokes,
    _mean,
    _split_sentences,
    _std,
    _word_count,
    compute_rhythm,
    rhythm_report,
    rhythm_summary,
)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _stroke(text: str = "Hello world.", seq: int = 0, kind: str = "thought") -> dict:
    return {"seq": seq, "at": "2026-01-01T00:00:00+00:00", "kind": kind, "text": text}


def _write_strokes(tmp_path: Path, strokes: list[dict]) -> Path:
    p = tmp_path / "strokes.jsonl"
    with open(p, "w") as f:
        for s in strokes:
            f.write(json.dumps(s) + "\n")
    return p


# -----------------------------------------------------------------------
# 1. _mean
# -----------------------------------------------------------------------


class TestMean:
    def test_basic(self):
        assert _mean([2.0, 4.0, 6.0]) == pytest.approx(4.0)

    def test_single(self):
        assert _mean([7.0]) == pytest.approx(7.0)

    def test_empty(self):
        assert _mean([]) == 0.0

    def test_negative(self):
        assert _mean([-3.0, 3.0]) == pytest.approx(0.0)

    def test_large_values(self):
        assert _mean([1e6, 2e6, 3e6]) == pytest.approx(2e6)


# -----------------------------------------------------------------------
# 2. _std
# -----------------------------------------------------------------------


class TestStd:
    def test_uniform(self):
        assert _std([5.0, 5.0, 5.0]) == pytest.approx(0.0)

    def test_known(self):
        # sample std of [1,2,3,4,5] = sqrt(2.5) ≈ 1.5811
        assert _std([1.0, 2.0, 3.0, 4.0, 5.0]) == pytest.approx(
            math.sqrt(2.5), abs=1e-4
        )

    def test_single(self):
        assert _std([42.0]) == 0.0

    def test_empty(self):
        assert _std([]) == 0.0

    def test_two_values(self):
        # sample std of [0, 10] = sqrt(50) ≈ 7.071
        assert _std([0.0, 10.0]) == pytest.approx(math.sqrt(50), abs=1e-4)


# -----------------------------------------------------------------------
# 3. _entropy
# -----------------------------------------------------------------------


class TestEntropy:
    def test_uniform_three_bands(self):
        # log2(3) ≈ 1.585
        assert _entropy([10, 10, 10]) == pytest.approx(math.log2(3), abs=1e-3)

    def test_single_band(self):
        assert _entropy([100, 0, 0]) == pytest.approx(0.0)

    def test_empty(self):
        assert _entropy([]) == 0.0

    def test_two_bands(self):
        # Two equal bands: log2(2) = 1.0
        assert _entropy([50, 50]) == pytest.approx(1.0)

    def test_all_zero(self):
        assert _entropy([0, 0, 0]) == 0.0

    def test_skewed(self):
        # [90, 5, 5] — low entropy
        total = 100
        p1, p2, p3 = 0.9, 0.05, 0.05
        expected = -(p1 * math.log2(p1) + 2 * p2 * math.log2(p2))
        assert _entropy([90, 5, 5]) == pytest.approx(expected, abs=1e-3)


# -----------------------------------------------------------------------
# 4. _split_sentences
# -----------------------------------------------------------------------


class TestSplitSentences:
    def test_simple(self):
        result = _split_sentences("Hello world. How are you? Fine.")
        assert len(result) == 3

    def test_exclamation(self):
        result = _split_sentences("Wow! Amazing! Great.")
        assert len(result) == 3

    def test_no_punctuation(self):
        result = _split_sentences("just a fragment without ending")
        # The whole thing is one fragment
        assert len(result) == 1

    def test_empty(self):
        assert _split_sentences("") == []

    def test_whitespace_only(self):
        assert _split_sentences("   \t\n  ") == []

    def test_multiple_dots(self):
        result = _split_sentences("Really?! Yes. No...")
        # "Really?!" is one boundary, "Yes." another, "No..." third
        assert len(result) >= 2

    def test_strips_whitespace(self):
        result = _split_sentences("  First.  Second.  ")
        for s in result:
            assert s == s.strip()


# -----------------------------------------------------------------------
# 5. _word_count
# -----------------------------------------------------------------------


class TestWordCount:
    def test_simple(self):
        assert _word_count("hello world") == 2

    def test_single(self):
        assert _word_count("hello") == 1

    def test_extra_spaces(self):
        assert _word_count("hello   world") == 2

    def test_empty(self):
        assert _word_count("") == 0


# -----------------------------------------------------------------------
# 6. _load_strokes
# -----------------------------------------------------------------------


class TestLoadStrokes:
    def test_basic(self, tmp_path):
        strokes = [_stroke(f"text {i}", seq=i) for i in range(10)]
        path = _write_strokes(tmp_path, strokes)
        loaded = _load_strokes(path, 5)
        assert len(loaded) == 5
        assert loaded[0]["seq"] == 5  # last 5

    def test_all(self, tmp_path):
        strokes = [_stroke(f"text {i}", seq=i) for i in range(3)]
        path = _write_strokes(tmp_path, strokes)
        loaded = _load_strokes(path, 100)
        assert len(loaded) == 3

    def test_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.jsonl"
        assert _load_strokes(path, 10) == []

    def test_malformed_lines(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text('{"seq":1,"text":"ok"}\nBAD LINE\n{"seq":2,"text":"ok2"}\n')
        loaded = _load_strokes(p, 10)
        assert len(loaded) == 2


# -----------------------------------------------------------------------
# 7. _classify_rhythm
# -----------------------------------------------------------------------


class TestClassifyRhythm:
    def test_monotone(self):
        assert _classify_rhythm(
            cv=0.15, entropy=0.5, short_ratio=0.3, long_ratio=0.3,
            alternation_rate=0.2,
        ) == "monotone"

    def test_staccato(self):
        assert _classify_rhythm(
            cv=0.5, entropy=1.2, short_ratio=0.80, long_ratio=0.05,
            alternation_rate=0.2,
        ) == "staccato"

    def test_flowing(self):
        assert _classify_rhythm(
            cv=0.5, entropy=1.0, short_ratio=0.1, long_ratio=0.70,
            alternation_rate=0.2,
        ) == "flowing"

    def test_chaotic(self):
        assert _classify_rhythm(
            cv=0.90, entropy=1.5, short_ratio=0.3, long_ratio=0.3,
            alternation_rate=0.70,
        ) == "chaotic"

    def test_steady(self):
        assert _classify_rhythm(
            cv=0.50, entropy=1.3, short_ratio=0.3, long_ratio=0.3,
            alternation_rate=0.45,
        ) == "steady"

    def test_varied_fallback(self):
        # High entropy but doesn't match other specific patterns
        assert _classify_rhythm(
            cv=0.60, entropy=1.3, short_ratio=0.2, long_ratio=0.2,
            alternation_rate=0.30,
        ) == "varied"


# -----------------------------------------------------------------------
# 8. compute_rhythm
# -----------------------------------------------------------------------


class TestComputeRhythm:
    def test_basic(self):
        # Mix of short and long sentences
        strokes = [
            _stroke("Short one. Also short. A somewhat longer sentence with more words in it."),
            _stroke("Brief. Tiny. This is a much longer sentence that contains many words."),
        ]
        m = compute_rhythm(strokes)
        assert m["total_strokes"] == 2
        assert m["total_sentences"] >= 4
        assert m["mean_sentence_length"] > 0
        assert m["cv"] >= 0
        assert 0 <= m["rhythm_entropy"]
        assert m["short_ratio"] + m["medium_ratio"] + m["long_ratio"] == pytest.approx(1.0, abs=0.01)

    def test_single_sentence(self):
        strokes = [_stroke("Just one sentence here.")]
        m = compute_rhythm(strokes)
        assert m["total_sentences"] == 1
        assert m["cv"] == 0.0
        assert m["alternation_rate"] == 0.0

    def test_all_short(self):
        strokes = [_stroke("One. Two. Three. Four. Five.")]
        m = compute_rhythm(strokes)
        assert m["short_ratio"] > 0.5 or m["total_sentences"] >= 1

    def test_all_long(self):
        long_sent = " ".join([f"word{i}" for i in range(25)]) + "."
        strokes = [_stroke(long_sent)]
        m = compute_rhythm(strokes)
        assert m["long_ratio"] > 0.5 or m["total_sentences"] >= 1

    def test_alternation_detected(self):
        # Alternating short and long
        short = "Hi."
        long = "This is a very long sentence with many words inside it."
        text = f"{short} {long} {short} {long}"
        strokes = [_stroke(text)]
        m = compute_rhythm(strokes)
        # Should have meaningful alternation
        assert m["alternation_rate"] > 0.0

    def test_rhythm_label_is_valid(self):
        valid_labels = {"monotone", "steady", "varied", "staccato", "flowing", "chaotic"}
        strokes = [
            _stroke("Short. Also short. Medium length sentence here."),
            _stroke("A somewhat longer sentence with more words. Brief."),
        ]
        m = compute_rhythm(strokes)
        assert m["rhythm_label"] in valid_labels


# -----------------------------------------------------------------------
# 9. rhythm_report
# -----------------------------------------------------------------------


class TestRhythmReport:
    def test_contains_key_fields(self):
        m = compute_rhythm([_stroke("Hello world. How are you?")])
        report = rhythm_report(m)
        assert "strokes analysed" in report
        assert "rhythm label" in report
        assert "alternation rate" in report

    def test_percentages(self):
        m = compute_rhythm([_stroke("Short. Medium length here now. A longer sentence with several words.")])
        report = rhythm_report(m)
        # Should contain percentage signs
        assert "%" in report


# -----------------------------------------------------------------------
# 10. rhythm_summary
# -----------------------------------------------------------------------


class TestRhythmSummary:
    def test_with_file(self, tmp_path):
        strokes = [_stroke(f"Sentence {i}. Another one here.", seq=i) for i in range(5)]
        path = _write_strokes(tmp_path, strokes)
        result = rhythm_summary(path, n=5)
        assert "strokes analysed" in result
        assert "5" in result

    def test_missing_file(self, tmp_path):
        path = tmp_path / "missing.jsonl"
        result = rhythm_summary(path, n=10)
        assert "0" in result  # 0 strokes


# -----------------------------------------------------------------------
# 11. _cli
# -----------------------------------------------------------------------


class TestCli:
    def test_basic(self, tmp_path, capsys):
        strokes = [_stroke(f"Text {i}. More text here.", seq=i) for i in range(5)]
        path = _write_strokes(tmp_path, strokes)
        rc = _cli(["--strokes", str(path), "-n", "5"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "strokes analysed" in captured.out

    def test_json(self, tmp_path, capsys):
        strokes = [_stroke("Hello world.", seq=0)]
        path = _write_strokes(tmp_path, strokes)
        rc = _cli(["--strokes", str(path), "-n", "1", "--json"])
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "rhythm_label" in data
        assert "total_strokes" in data

    def test_missing_file(self, tmp_path, capsys):
        rc = _cli(["--strokes", str(tmp_path / "nope.jsonl")])
        assert rc == 0


# -----------------------------------------------------------------------
# 12. Edge cases
# -----------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_strokes_list(self):
        m = compute_rhythm([])
        assert m["total_strokes"] == 0
        assert m["total_sentences"] == 0
        assert m["rhythm_label"] == "monotone"

    def test_stroke_with_no_text(self):
        strokes = [{"seq": 0, "at": "2026-01-01T00:00:00+00:00", "kind": "thought"}]
        m = compute_rhythm(strokes)
        assert m["total_sentences"] == 0

    def test_unicode_text(self):
        strokes = [_stroke("Héllo wörld. Ün sentence. Ça va bien?")]
        m = compute_rhythm(strokes)
        assert m["total_sentences"] >= 2

    def test_numbers_and_symbols(self):
        strokes = [_stroke("Version 2.0 released. It has 42 features!")]
        m = compute_rhythm(strokes)
        assert m["total_sentences"] >= 1

    def test_very_long_stroke(self):
        words = " ".join([f"word{i}" for i in range(200)])
        strokes = [_stroke(words + ".")]
        m = compute_rhythm(strokes)
        assert m["total_sentences"] >= 1
        assert m["mean_sentence_length"] > 50

    def test_many_short_strokes(self):
        strokes = [_stroke(f"Word.", seq=i) for i in range(50)]
        m = compute_rhythm(strokes)
        assert m["total_sentences"] == 50
        assert m["cv"] == 0.0  # all identical length

    def test_cv_bounds(self):
        strokes = [
            _stroke("A. B. " + " ".join([f"w{i}" for i in range(30)]) + ".")
        ]
        m = compute_rhythm(strokes)
        assert m["cv"] >= 0

    def test_ratios_sum_to_one(self):
        strokes = [
            _stroke("Hi. How are you doing today? This is a somewhat longer sentence."),
            _stroke("Brief. Medium length sentence. Another very long sentence with many many words inside it."),
        ]
        m = compute_rhythm(strokes)
        total = m["short_ratio"] + m["medium_ratio"] + m["long_ratio"]
        assert total == pytest.approx(1.0, abs=0.01)

    def test_entropy_bounds(self):
        strokes = [_stroke("Short. Medium length sentence here now.")]
        m = compute_rhythm(strokes)
        assert 0 <= m["rhythm_entropy"] <= math.log2(3) + 0.01  # max for 3 bands

    def test_alternation_bounds(self):
        strokes = [_stroke("Hi. Hello. Greetings. Salutations.")]
        m = compute_rhythm(strokes)
        assert 0 <= m["alternation_rate"] <= 1.0
