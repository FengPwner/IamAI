"""Tests for iamai.stroke_coherence — stroke text coherence assessment.

Covers:
  - CoherenceVerdict enum values
  - CoherenceResult dataclass (frozen, ok property)
  - assess: coherent / degraded / incoherent verdicts
  - Dimension checks: length, repetition, char health, sentence completeness
  - Edge cases: empty string, single character, Unicode, very long text
  - assess_batch and summary convenience functions
"""

import pytest

from iamai.stroke_coherence import (
    CoherenceResult,
    CoherenceVerdict,
    assess,
    assess_batch,
    summary,
)


# ---------------------------------------------------------------------------
# CoherenceVerdict
# ---------------------------------------------------------------------------

class TestCoherenceVerdict:
    def test_values(self):
        assert CoherenceVerdict.COHERENT == "coherent"
        assert CoherenceVerdict.DEGRADED == "degraded"
        assert CoherenceVerdict.INCOHERENT == "incoherent"

    def test_is_string(self):
        assert isinstance(CoherenceVerdict.COHERENT, str)


# ---------------------------------------------------------------------------
# CoherenceResult
# ---------------------------------------------------------------------------

class TestCoherenceResult:
    def test_defaults(self):
        r = CoherenceResult(verdict=CoherenceVerdict.COHERENT, score=1.0)
        assert r.length_ok is True
        assert r.repetition_ratio == 0.0
        assert r.char_health == 1.0
        assert r.sentence_complete is True
        assert r.reasons == []

    def test_ok_property(self):
        ok = CoherenceResult(verdict=CoherenceVerdict.COHERENT, score=0.9)
        bad = CoherenceResult(verdict=CoherenceVerdict.DEGRADED, score=0.5)
        assert ok.ok is True
        assert bad.ok is False

    def test_frozen(self):
        r = CoherenceResult(verdict=CoherenceVerdict.COHERENT, score=1.0)
        with pytest.raises(AttributeError):
            r.score = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# assess — coherent strokes
# ---------------------------------------------------------------------------

class TestCoherent:
    def test_normal_sentence(self):
        r = assess("The writer emitted a thoughtful stroke about code design.")
        assert r.verdict == CoherenceVerdict.COHERENT
        assert r.score >= 0.70
        assert r.reasons == []

    def test_multiline_prose(self):
        text = (
            "Repositories grow in ways their creators do not predict. "
            "A module added today solves a problem that did not exist yesterday. "
            "The best response is to keep the design simple and the tests honest."
        )
        r = assess(text)
        assert r.verdict == CoherenceVerdict.COHERENT

    def test_chinese_text(self):
        r = assess("代码仓库的成长往往超出创造者的预期。好的设计是保持简单。")
        assert r.verdict == CoherenceVerdict.COHERENT


# ---------------------------------------------------------------------------
# assess — degraded strokes
# ---------------------------------------------------------------------------

class TestDegraded:
    def test_repetitive_sentences(self):
        text = (
            "The fox jumped. The fox jumped. The fox jumped. "
            "The fox jumped. The fox jumped. The fox jumped. "
            "The fox jumped. The fox jumped."
        )
        r = assess(text)
        assert r.repetition_ratio > 0.50
        assert any("repetition" in reason for reason in r.reasons)

    def test_truncated_text(self):
        text = "The writer was producing output but then it got cut off mid"
        r = assess(text)
        assert r.sentence_complete is False
        assert any("mid-sentence" in reason for reason in r.reasons)


# ---------------------------------------------------------------------------
# assess — incoherent strokes
# ---------------------------------------------------------------------------

class TestIncoherent:
    def test_too_short(self):
        r = assess("hi")
        assert r.length_ok is False
        assert r.verdict == CoherenceVerdict.INCOHERENT

    def test_empty_string(self):
        r = assess("")
        assert r.length_ok is False
        assert r.verdict == CoherenceVerdict.INCOHERENT

    def test_control_characters(self):
        # Build a string mostly made of control characters (bell, etc.)
        bad = "".join(chr(i) for i in range(1, 32)) * 2
        r = assess(bad)
        assert r.char_health < 0.95
        assert any("char_health" in reason for reason in r.reasons)

    def test_replacement_char_garbage(self):
        text = "\ufffd" * 50
        r = assess(text)
        assert r.char_health < 0.50
        assert r.verdict == CoherenceVerdict.INCOHERENT


# ---------------------------------------------------------------------------
# Dimension checks — boundary conditions
# ---------------------------------------------------------------------------

class TestBoundaries:
    def test_exactly_min_chars(self):
        text = "a" * 10  # exactly at default min
        r = assess(text)
        assert r.length_ok is True

    def test_one_below_min(self):
        text = "a" * 9
        r = assess(text)
        assert r.length_ok is False

    def test_custom_min_chars(self):
        r = assess("hello world", min_chars=5)
        assert r.length_ok is True

    def test_text_ending_with_period(self):
        r = assess("This is a complete sentence.")
        assert r.sentence_complete is True

    def test_text_ending_with_chinese_period(self):
        r = assess("这是一句完整的话。")
        assert r.sentence_complete is True

    def test_text_ending_with_bracket(self):
        r = assess("This is a complete thought (with parens).")
        assert r.sentence_complete is True

    def test_single_sentence_no_repetition(self):
        r = assess("Just one sentence here.")
        assert r.repetition_ratio == 0.0

    def test_all_identical_short_sentences(self):
        text = "Yes. Yes. Yes. Yes. Yes. Yes. Yes. Yes. Yes. Yes."
        r = assess(text)
        # 9 duplicates out of 10 sentences
        assert r.repetition_ratio >= 0.80


# ---------------------------------------------------------------------------
# assess_batch
# ---------------------------------------------------------------------------

class TestAssessBatch:
    def test_empty_batch(self):
        results = assess_batch([])
        assert results == []

    def test_batch_returns_list(self):
        texts = ["Good stroke.", "Bad", "Another good stroke here."]
        results = assess_batch(texts)
        assert len(results) == 3
        assert all(isinstance(r, CoherenceResult) for r in results)


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------

class TestSummary:
    def test_empty(self):
        assert summary([]) == "no strokes assessed"

    def test_all_coherent(self):
        results = [
            CoherenceResult(verdict=CoherenceVerdict.COHERENT, score=0.95),
            CoherenceResult(verdict=CoherenceVerdict.COHERENT, score=0.85),
        ]
        s = summary(results)
        assert "2 strokes" in s
        assert "2 coherent" in s
        assert "0 degraded" in s
        assert "0 incoherent" in s

    def test_mixed(self):
        results = [
            CoherenceResult(verdict=CoherenceVerdict.COHERENT, score=0.9),
            CoherenceResult(verdict=CoherenceVerdict.DEGRADED, score=0.5),
            CoherenceResult(verdict=CoherenceVerdict.INCOHERENT, score=0.2),
        ]
        s = summary(results)
        assert "1 coherent" in s
        assert "1 degraded" in s
        assert "1 incoherent" in s
        assert "avg score 0.53" in s
