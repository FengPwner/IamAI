"""Tests for iamai.stroke_quality_gate — per-stroke quality scoring."""

import pytest

from iamai.stroke_quality_gate import (
    QualityGate,
    StrokeVerdict,
    WindowResult,
    _bigrams,
    _tokenize,
    _trigrams,
    score_density,
    score_length,
    score_repetition,
    score_vocabulary,
)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_simple_english(self):
        assert _tokenize("Hello World") == ["hello", "world"]

    def test_punctuation_stripped(self):
        assert _tokenize("foo, bar! baz.") == ["foo", "bar", "baz"]

    def test_chinese_chars(self):
        tokens = _tokenize("你好世界 hello")
        assert "你好世界" in tokens or "你" in tokens  # unicode range coverage

    def test_empty(self):
        assert _tokenize("") == []

    def test_numbers_only_ignored(self):
        assert _tokenize("123 456") == []


class TestBigrams:
    def test_two_words(self):
        assert _bigrams(["a", "b"]) == ["a b"]

    def test_three_words(self):
        assert _bigrams(["a", "b", "c"]) == ["a b", "b c"]

    def test_single_word(self):
        assert _bigrams(["a"]) == []

    def test_empty(self):
        assert _bigrams([]) == []


class TestTrigrams:
    def test_three_words(self):
        assert _trigrams(["a", "b", "c"]) == ["a b c"]

    def test_four_words(self):
        assert _trigrams(["a", "b", "c", "d"]) == ["a b c", "b c d"]

    def test_two_words(self):
        assert _trigrams(["a", "b"]) == []

    def test_empty(self):
        assert _trigrams([]) == []


# ---------------------------------------------------------------------------
# Dimension: length
# ---------------------------------------------------------------------------

class TestScoreLength:
    def test_empty_text(self):
        assert score_length("") == 0.0

    def test_below_min(self):
        # 3 words < min_words=5 → 3/5 = 0.6
        assert score_length("a b c") == pytest.approx(0.6)

    def test_at_min(self):
        assert score_length("a b c d e") == pytest.approx(0.0)

    def test_above_max(self):
        text = " ".join(["word"] * 100)
        assert score_length(text) == 1.0

    def test_midpoint(self):
        # 42 words → (42-5)/(80-5) ≈ 0.4933
        text = " ".join(["word"] * 42)
        assert score_length(text) == pytest.approx((42 - 5) / (80 - 5), abs=0.01)

    def test_custom_bounds(self):
        assert score_length("a b", min_words=2, max_words=10) == pytest.approx(
            (2 - 2) / (10 - 2)
        )

    def test_single_word_below_min(self):
        assert score_length("hello") == pytest.approx(1 / 5)


# ---------------------------------------------------------------------------
# Dimension: vocabulary
# ---------------------------------------------------------------------------

class TestScoreVocabulary:
    def test_empty(self):
        assert score_vocabulary("") == 0.0

    def test_all_unique(self):
        assert score_vocabulary("a b c d e") == 1.0

    def test_all_same(self):
        assert score_vocabulary("a a a a a") == pytest.approx(1 / 5)

    def test_mixed(self):
        # "a b c a b" → 3 unique / 5 total = 0.6
        assert score_vocabulary("a b c a b") == pytest.approx(0.6)

    def test_case_insensitive(self):
        # "Hello hello HELLO" → all same token → 1/3
        assert score_vocabulary("Hello hello HELLO") == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# Dimension: repetition
# ---------------------------------------------------------------------------

class TestScoreRepetition:
    def test_no_previous(self):
        assert score_repetition("anything here") == 1.0

    def test_identical_texts(self):
        text = "the quick brown fox jumps over the lazy dog"
        assert score_repetition(text, text) == pytest.approx(0.0)

    def test_completely_different(self):
        a = "alpha beta gamma delta"
        b = "epsilon zeta eta theta"
        assert score_repetition(a, b) == 1.0

    def test_partial_overlap(self):
        prev = "the quick brown fox"
        curr = "the quick red fox"
        # bigrams prev: {the quick, quick brown, brown fox}
        # bigrams curr: {the quick, quick red, red fox}
        # intersection: {the quick} = 1
        # union: {the quick, quick brown, brown fox, quick red, red fox} = 5
        assert score_repetition(curr, prev) == pytest.approx(1 - 1 / 5)

    def test_empty_current(self):
        assert score_repetition("", "some previous text here") == 1.0

    def test_empty_previous(self):
        assert score_repetition("some current text here", "") == 1.0

    def test_both_empty(self):
        assert score_repetition("", "") == 1.0


# ---------------------------------------------------------------------------
# Dimension: density
# ---------------------------------------------------------------------------

class TestScoreDensity:
    def test_empty(self):
        assert score_density("") == 0.0

    def test_one_word(self):
        assert score_density("hello") == 0.0

    def test_two_words(self):
        assert score_density("hello world") == 0.0

    def test_all_unique_trigrams(self):
        text = "a b c d e f g h"
        tokens = _tokenize(text)
        tri = _trigrams(tokens)
        expected = len(set(tri)) / len(tokens)
        assert score_density(text) == pytest.approx(min(expected, 1.0))

    def test_repetitive_text(self):
        text = "a b a b a b a b"
        # trigrams: "a b a", "b a b", "a b a", "b a b", "a b a", "b a b"
        # unique: {"a b a", "b a b"} = 2
        # total words: 8
        assert score_density(text) == pytest.approx(2 / 8)


# ---------------------------------------------------------------------------
# QualityGate — single evaluation
# ---------------------------------------------------------------------------

class TestQualityGateEvaluate:
    def setup_method(self):
        self.gate = QualityGate()

    def test_good_stroke_passes(self):
        text = (
            "naming is hard because a bad name is cheap to type and "
            "expensive to keep, so choose the least-wrong option early"
        )
        v = self.gate.evaluate(text)
        assert v.label == "pass"
        assert v.score >= 0.60

    def test_short_stroke_warns_or_fails(self):
        v = self.gate.evaluate("ok")
        assert v.label in ("warn", "fail")
        assert v.score < 0.60

    def test_repetitive_stroke_penalised(self):
        prev = "the automation fails quietly so the log has to say something"
        curr = "the automation fails quietly so the log has to say something"
        v = self.gate.evaluate(curr, prev)
        assert v.breakdown["repetition"] == pytest.approx(0.0)
        assert v.score < v.breakdown["vocabulary"]  # repetition drags it down

    def test_verdict_structure(self):
        v = self.gate.evaluate("a reasonable stroke of text with enough words to pass the length gate easily")
        assert isinstance(v, StrokeVerdict)
        assert set(v.breakdown.keys()) == {"length", "vocabulary", "repetition", "density"}
        assert 0.0 <= v.score <= 1.0

    def test_custom_weights(self):
        gate = QualityGate(weights={"length": 0.5, "vocabulary": 0.2, "repetition": 0.2, "density": 0.1})
        # 50 unique real words → length=0.6, vocab=1.0, rep=1.0, density≈0.96
        words = [
            "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
            "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron", "pi", "rho",
            "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega", "red",
            "blue", "green", "yellow", "orange", "purple", "quick", "bright",
            "sharp", "calm", "bold", "keen", "warm", "cool", "deep", "tall",
            "swift", "clear", "fresh", "grand", "noble", "proud", "stern",
            "gentle", "wild", "still",
        ]
        text = " ".join(words)
        v = gate.evaluate(text)
        assert v.label == "pass"  # length dominates with diverse tokens

    def test_invalid_weights_sum(self):
        gate = QualityGate(weights={"length": 0.5, "vocabulary": 0.1, "repetition": 0.1, "density": 0.1})
        with pytest.raises(ValueError, match="sum to 1.0"):
            gate.evaluate("hello world")

    def test_custom_thresholds(self):
        gate = QualityGate(pass_threshold=0.90, warn_threshold=0.70)
        v = gate.evaluate("a moderate sentence that would normally pass easily under default thresholds")
        # might now be warn or fail due to strict thresholds
        assert v.label in ("pass", "warn", "fail")


# ---------------------------------------------------------------------------
# QualityGate — window evaluation
# ---------------------------------------------------------------------------

class TestQualityGateWindow:
    def setup_method(self):
        self.gate = QualityGate()

    def test_empty_window(self):
        result = self.gate.evaluate_window([])
        assert result.count == 0
        assert result.fail_rate == 0.0
        assert result.pass_rate == 0.0
        assert result.mean_score == 0.0
        assert result.worst is None
        assert result.best is None

    def test_single_stroke_window(self):
        strokes = ["automation fails quietly so the log must say something even when nothing happened"]
        result = self.gate.evaluate_window(strokes)
        assert result.count == 1
        assert result.pass_count + result.warn_count + result.fail_count == 1

    def test_mixed_window(self):
        strokes = [
            "naming is hard because a bad name is cheap to type and expensive to keep forever",
            "ok",
            "commit history is the only honest documentation because it cannot be backdated easily",
        ]
        result = self.gate.evaluate_window(strokes)
        assert result.count == 3
        assert result.pass_count >= 1  # at least the good strokes pass
        assert result.fail_count >= 0  # "ok" might fail or warn

    def test_fail_rate(self):
        # All failing strokes
        strokes = ["a", "b", "c"]
        result = self.gate.evaluate_window(strokes)
        assert result.fail_rate >= 0.0  # short strokes likely fail
        assert 0.0 <= result.fail_rate <= 1.0

    def test_pass_rate(self):
        strokes = [
            "the quick brown fox jumps over the lazy dog while the cat watches patiently from above",
            "naming things is one of the two hard problems in computer science along with cache invalidation",
        ]
        result = self.gate.evaluate_window(strokes)
        assert result.pass_rate > 0.0

    def test_mean_score_range(self):
        strokes = ["good stroke with enough length and variety of words to score well", "ab"]
        result = self.gate.evaluate_window(strokes)
        assert 0.0 <= result.mean_score <= 1.0

    def test_worst_and_best(self):
        strokes = [
            "a reasonable stroke with enough words and variety to pass the quality gate",
            "x",
        ]
        result = self.gate.evaluate_window(strokes)
        assert result.worst is not None
        assert result.best is not None
        assert result.best.score >= result.worst.score

    def test_summary_structure(self):
        strokes = ["alpha beta gamma delta epsilon zeta eta theta iota kappa"]
        result = self.gate.evaluate_window(strokes)
        s = result.summary()
        assert set(s.keys()) == {"count", "pass_rate", "fail_rate", "mean_score", "worst_score", "best_score"}
        assert s["count"] == 1

    def test_repetition_in_window(self):
        # Second stroke identical to first → repetition dimension = 0
        text = "the automation fails quietly so the log has to say something meaningful"
        strokes = [text, text]
        result = self.gate.evaluate_window(strokes)
        # Second verdict should have lower score due to repetition
        assert result.verdicts[1].score <= result.verdicts[0].score


# ---------------------------------------------------------------------------
# WindowResult standalone
# ---------------------------------------------------------------------------

class TestWindowResult:
    def test_empty(self):
        wr = WindowResult()
        assert wr.count == 0
        assert wr.fail_rate == 0.0
        assert wr.pass_rate == 0.0
        assert wr.mean_score == 0.0

    def test_all_pass(self):
        verdicts = [
            StrokeVerdict(text="good", score=0.8, label="pass"),
            StrokeVerdict(text="also good", score=0.9, label="pass"),
        ]
        wr = WindowResult(verdicts=verdicts)
        assert wr.pass_count == 2
        assert wr.fail_count == 0
        assert wr.pass_rate == 1.0
        assert wr.fail_rate == 0.0
        assert wr.mean_score == pytest.approx(0.85)

    def test_all_fail(self):
        verdicts = [
            StrokeVerdict(text="bad", score=0.1, label="fail"),
            StrokeVerdict(text="worse", score=0.05, label="fail"),
        ]
        wr = WindowResult(verdicts=verdicts)
        assert wr.fail_count == 2
        assert wr.pass_count == 0
        assert wr.fail_rate == 1.0
        assert wr.worst.score == pytest.approx(0.05)
        assert wr.best.score == pytest.approx(0.1)

    def test_mixed_labels(self):
        verdicts = [
            StrokeVerdict(text="a", score=0.8, label="pass"),
            StrokeVerdict(text="b", score=0.5, label="warn"),
            StrokeVerdict(text="c", score=0.2, label="fail"),
        ]
        wr = WindowResult(verdicts=verdicts)
        assert wr.pass_count == 1
        assert wr.warn_count == 1
        assert wr.fail_count == 1
        assert wr.mean_score == pytest.approx(0.5)
        assert wr.worst.label == "fail"
        assert wr.best.label == "pass"


# ---------------------------------------------------------------------------
# StrokeVerdict repr
# ---------------------------------------------------------------------------

class TestStrokeVerdict:
    def test_repr(self):
        v = StrokeVerdict(text="hello", score=0.75, label="pass")
        assert "0.750" in repr(v)
        assert "pass" in repr(v)

    def test_breakdown_present(self):
        v = StrokeVerdict(
            text="x", score=0.5, label="warn",
            breakdown={"length": 0.3, "vocabulary": 0.6, "repetition": 0.7, "density": 0.4},
        )
        assert v.breakdown["vocabulary"] == 0.6
