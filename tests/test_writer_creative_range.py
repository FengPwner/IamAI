"""Tests for iamai.writer_creative_range — writing diversity measurement.

Visit 815: this module quantifies how varied and creative the automated
writer's output is across five orthogonal dimensions.

Test areas:
     1. _tokenize                  — word tokenization
     2. _split_sentences           — sentence splitting
     3. _content_words             — stop-word filtering
     4. _simple_sentiment          — lightweight sentiment scoring
     5. vocabulary_richness        — type-token ratio
     6. sentence_length_cv         — sentence length variation
     7. topic_diversity            — Shannon entropy of content words
     8. structural_variety         — sentence-starting patterns
     9. polarity_range             — sentiment spread across strokes
    10. creative_range_score       — weighted composite
    11. creative_label             — classification
    12. load_strokes               — JSONL loading
    13. creative_range_report      — full report integration
    14. creative_range_summary     — human-readable output
    15. _cli                       — exit codes, --json flag
    16. edge cases                 — empty, single, degenerate inputs
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_creative_range import (
    _cli,
    _content_words,
    _simple_sentiment,
    _split_sentences,
    _tokenize,
    _STOP_WORDS,
    creative_label,
    creative_range_report,
    creative_range_score,
    creative_range_summary,
    load_strokes,
    polarity_range,
    sentence_length_cv,
    structural_variety,
    topic_diversity,
    vocabulary_richness,
)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _make_stroke(text: str, seq: int = 1, kind: str = "thought") -> dict:
    return {"seq": seq, "at": "2026-11-23T12:00:00+08:00", "kind": kind, "text": text}


def _make_strokes(texts: list) -> list:
    return [_make_stroke(t, seq=i + 1) for i, t in enumerate(texts)]


def _write_strokes_jsonl(tmp_path: Path, strokes: list) -> Path:
    p = tmp_path / "strokes.jsonl"
    with open(p, "w") as f:
        for s in strokes:
            f.write(json.dumps(s) + "\n")
    return p


# -----------------------------------------------------------------------
# 1. _tokenize
# -----------------------------------------------------------------------


class TestTokenize:
    def test_basic_words(self):
        assert _tokenize("hello world") == ["hello", "world"]

    def test_uppercase_lowered(self):
        assert _tokenize("Hello WORLD") == ["hello", "world"]

    def test_apostrophes_kept(self):
        assert _tokenize("don't stop") == ["don't", "stop"]

    def test_punctuation_stripped(self):
        assert _tokenize("hello, world! end.") == ["hello", "world", "end"]

    def test_numbers_excluded(self):
        assert _tokenize("test 123 abc") == ["test", "abc"]

    def test_empty_string(self):
        assert _tokenize("") == []

    def test_only_punctuation(self):
        assert _tokenize("!@#$%") == []

    def test_mixed_case(self):
        result = _tokenize("CaMeL CaSe")
        assert result == ["camel", "case"]


# -----------------------------------------------------------------------
# 2. _split_sentences
# -----------------------------------------------------------------------


class TestSplitSentences:
    def test_period_split(self):
        result = _split_sentences("First sentence. Second sentence.")
        assert len(result) == 2

    def test_exclamation_split(self):
        result = _split_sentences("Wow! Amazing!")
        assert len(result) == 2

    def test_question_split(self):
        result = _split_sentences("Why? Because.")
        assert len(result) == 2

    def test_single_sentence(self):
        result = _split_sentences("Just one sentence here.")
        assert len(result) == 1

    def test_empty_string(self):
        result = _split_sentences("")
        assert result == []

    def test_no_delimiter(self):
        result = _split_sentences("no delimiter at all")
        assert len(result) == 1

    def test_multiple_spaces_after_period(self):
        result = _split_sentences("One.  Two.  Three.")
        assert len(result) == 3


# -----------------------------------------------------------------------
# 3. _content_words
# -----------------------------------------------------------------------


class TestContentWords:
    def test_removes_stop_words(self):
        tokens = ["the", "cat", "is", "running", "fast"]
        result = _content_words(tokens)
        assert "the" not in result
        assert "is" not in result
        assert "cat" in result
        assert "running" in result

    def test_removes_short_words(self):
        tokens = ["a", "an", "to", "go", "big", "cat"]
        result = _content_words(tokens)
        assert "a" not in result
        # "go" is not a stop word and len > 2? no, len("go") = 2, filtered
        assert "go" not in result
        assert "big" in result

    def test_empty_input(self):
        assert _content_words([]) == []

    def test_all_stop_words(self):
        tokens = list(_STOP_WORDS)[:10]
        assert _content_words(tokens) == []


# -----------------------------------------------------------------------
# 4. _simple_sentiment
# -----------------------------------------------------------------------


class TestSimpleSentiment:
    def test_positive_text(self):
        score = _simple_sentiment("this is great and wonderful")
        assert score > 0

    def test_negative_text(self):
        score = _simple_sentiment("terrible broken crash fail")
        assert score < 0

    def test_neutral_text(self):
        score = _simple_sentiment("the cat sat on the mat")
        assert score == 0.0

    def test_mixed_text(self):
        score = _simple_sentiment("great progress but terrible error")
        # 1 positive, 1 negative → 0
        assert score == 0.0

    def test_empty_text(self):
        assert _simple_sentiment("") == 0.0

    def test_range_bounded(self):
        score = _simple_sentiment("good great excellent wonderful beautiful amazing brilliant")
        assert -1.0 <= score <= 1.0


# -----------------------------------------------------------------------
# 5. vocabulary_richness
# -----------------------------------------------------------------------


class TestVocabularyRichness:
    def test_all_unique_words(self):
        strokes = _make_strokes(["alpha beta gamma delta epsilon"])
        result = vocabulary_richness(strokes)
        assert result["ttr"] == 1.0
        assert result["unique_words"] == 5
        assert result["total_words"] == 5

    def test_all_repeated_words(self):
        strokes = _make_strokes(["the the the the the"])
        result = vocabulary_richness(strokes)
        assert result["ttr"] < 0.5  # "the" is one unique word out of 5
        assert result["unique_words"] == 1
        assert result["total_words"] == 5

    def test_empty_strokes(self):
        result = vocabulary_richness([])
        assert result["score"] == 0.0
        assert result["total_words"] == 0

    def test_score_increases_with_diversity(self):
        low = vocabulary_richness(_make_strokes(["word word word word"] * 5))
        high = vocabulary_richness(_make_strokes([
            "alpha beta gamma", "delta epsilon zeta",
            "eta theta iota", "kappa lambda mu"
        ]))
        assert high["score"] > low["score"]

    def test_score_bounded(self):
        strokes = _make_strokes(["some text here with words"] * 10)
        result = vocabulary_richness(strokes)
        assert 0.0 <= result["score"] <= 1.0

    def test_multiple_strokes(self):
        strokes = _make_strokes(["hello world", "hello earth", "hello planet"])
        result = vocabulary_richness(strokes)
        assert result["unique_words"] == 4  # hello, world, earth, planet
        assert result["total_words"] == 6


# -----------------------------------------------------------------------
# 6. sentence_length_cv
# -----------------------------------------------------------------------


class TestSentenceLengthCV:
    def test_uniform_sentences(self):
        strokes = _make_strokes([
            "One two three. Four five six. Seven eight nine."
        ])
        result = sentence_length_cv(strokes)
        assert result["cv"] < 0.1  # very uniform

    def test_varied_sentences(self):
        strokes = _make_strokes([
            "Short. A much longer sentence with many many more words in it."
        ])
        result = sentence_length_cv(strokes)
        assert result["cv"] > 0.3

    def test_single_sentence(self):
        strokes = _make_strokes(["Only one sentence here."])
        result = sentence_length_cv(strokes)
        assert result["score"] == 0.0  # can't compute CV with 1 sample

    def test_empty_strokes(self):
        result = sentence_length_cv([])
        assert result["score"] == 0.0

    def test_score_bounded(self):
        strokes = _make_strokes([
            "Hi. This is a longer one. Ok. " * 5
        ])
        result = sentence_length_cv(strokes)
        assert 0.0 <= result["score"] <= 1.0

    def test_cv_increases_with_variation(self):
        uniform = sentence_length_cv(_make_strokes([
            "Three word sentence. Three word sentence. Three word sentence."
        ]))
        varied = sentence_length_cv(_make_strokes([
            "Short. A considerably longer sentence with many additional words included."
        ]))
        assert varied["cv"] > uniform["cv"]


# -----------------------------------------------------------------------
# 7. topic_diversity
# -----------------------------------------------------------------------


class TestTopicDiversity:
    def test_diverse_content(self):
        strokes = _make_strokes([
            "quantum physics particles collide at speed",
            "medieval castle architecture stone walls",
            "tropical rainforest biodiversity species",
            "stock market trading algorithm profit",
            "cooking recipe ingredients kitchen spice",
        ])
        result = topic_diversity(strokes)
        assert result["normalized_entropy"] > 0.5

    def test_repetitive_content(self):
        strokes = _make_strokes([
            "the system is running and working",
            "the system is running and working",
            "the system is running and working",
        ])
        result = topic_diversity(strokes)
        assert result["normalized_entropy"] < 0.5

    def test_empty_strokes(self):
        result = topic_diversity([])
        assert result["score"] == 0.0
        assert result["entropy"] == 0.0

    def test_max_entropy(self):
        result = topic_diversity(_make_strokes(["test"]), n_buckets=10)
        assert result["max_entropy"] == pytest.approx(3.3219, abs=0.01)

    def test_score_bounded(self):
        strokes = _make_strokes(["various content words here"] * 20)
        result = topic_diversity(strokes)
        assert 0.0 <= result["score"] <= 1.0

    def test_single_word(self):
        strokes = _make_strokes(["hello"])
        result = topic_diversity(strokes)
        assert result["entropy"] == 0.0  # all in one bucket


# -----------------------------------------------------------------------
# 8. structural_variety
# -----------------------------------------------------------------------


class TestStructuralVariety:
    def test_varied_starts(self):
        strokes = _make_strokes([
            "The cat sat. Running fast helps. However, it failed. "
            "In the morning we start. I think therefore I am."
        ])
        result = structural_variety(strokes)
        assert result["patterns_found"] >= 3

    def test_uniform_starts(self):
        strokes = _make_strokes([
            "The cat sat. The dog ran. The bird flew. The fish swam."
        ])
        result = structural_variety(strokes)
        # All start with "The" → only 1 pattern
        assert result["patterns_found"] <= 2

    def test_empty_strokes(self):
        result = structural_variety([])
        assert result["score"] == 0.0
        assert result["patterns_found"] == 0

    def test_distribution_populated(self):
        strokes = _make_strokes([
            "Running is fun. The cat sat. I think so."
        ])
        result = structural_variety(strokes)
        assert len(result["distribution"]) > 0

    def test_score_bounded(self):
        strokes = _make_strokes(["Various sentences here."] * 10)
        result = structural_variety(strokes)
        assert 0.0 <= result["score"] <= 1.0

    def test_gerund_detected(self):
        strokes = _make_strokes(["Running fast is great. Jogging helps too."])
        result = structural_variety(strokes)
        assert "gerund" in result["distribution"]

    def test_subordinate_detected(self):
        strokes = _make_strokes(["When it rains, we stay. Because we care, we help."])
        result = structural_variety(strokes)
        assert "subordinate" in result["distribution"]


# -----------------------------------------------------------------------
# 9. polarity_range
# -----------------------------------------------------------------------


class TestPolarityRange:
    def test_mixed_sentiment(self):
        strokes = _make_strokes([
            "this is great and wonderful and amazing",
            "terrible broken crash fail error bug",
        ])
        result = polarity_range(strokes)
        assert result["range"] > 0.5
        assert result["min"] < 0
        assert result["max"] > 0

    def test_neutral_text(self):
        strokes = _make_strokes([
            "the cat sat on the mat",
            "a book is on the table",
            "water flows down the hill",
        ])
        result = polarity_range(strokes)
        assert result["range"] == 0.0

    def test_single_stroke(self):
        result = polarity_range(_make_strokes(["great wonderful"]))
        assert result["score"] == 0.0  # need at least 2

    def test_empty(self):
        result = polarity_range([])
        assert result["score"] == 0.0

    def test_score_bounded(self):
        strokes = _make_strokes([
            "good great excellent",
            "bad terrible awful",
            "neutral text here",
        ])
        result = polarity_range(strokes)
        assert 0.0 <= result["score"] <= 1.0

    def test_std_computed(self):
        strokes = _make_strokes([
            "great wonderful amazing",
            "terrible awful broken",
            "good progress success",
        ])
        result = polarity_range(strokes)
        assert result["std"] > 0


# -----------------------------------------------------------------------
# 10. creative_range_score
# -----------------------------------------------------------------------


class TestCreativeRangeScore:
    def test_perfect_scores(self):
        metrics = {
            "vocabulary_richness": {"score": 1.0},
            "sentence_length_cv": {"score": 1.0},
            "topic_diversity": {"score": 1.0},
            "structural_variety": {"score": 1.0},
            "polarity_range": {"score": 1.0},
        }
        assert creative_range_score(metrics) == 1.0

    def test_zero_scores(self):
        metrics = {
            "vocabulary_richness": {"score": 0.0},
            "sentence_length_cv": {"score": 0.0},
            "topic_diversity": {"score": 0.0},
            "structural_variety": {"score": 0.0},
            "polarity_range": {"score": 0.0},
        }
        assert creative_range_score(metrics) == 0.0

    def test_partial_metrics(self):
        metrics = {
            "vocabulary_richness": {"score": 0.8},
            "topic_diversity": {"score": 0.6},
        }
        score = creative_range_score(metrics)
        assert 0.0 < score < 1.0

    def test_weighted_average(self):
        metrics = {
            "vocabulary_richness": {"score": 1.0},
            "sentence_length_cv": {"score": 0.0},
            "topic_diversity": {"score": 0.0},
            "structural_variety": {"score": 0.0},
            "polarity_range": {"score": 0.0},
        }
        score = creative_range_score(metrics)
        # vocab weight is 0.25 out of 1.0 total
        assert score == pytest.approx(0.25, abs=0.01)

    def test_empty_metrics(self):
        assert creative_range_score({}) == 0.0


# -----------------------------------------------------------------------
# 11. creative_label
# -----------------------------------------------------------------------


class TestCreativeLabel:
    def test_exploring(self):
        assert creative_label(0.80) == "exploring"
        assert creative_label(0.75) == "exploring"

    def test_expressive(self):
        assert creative_label(0.55) == "expressive"
        assert creative_label(0.74) == "expressive"

    def test_focused(self):
        assert creative_label(0.35) == "focused"
        assert creative_label(0.54) == "focused"

    def test_repetitive(self):
        assert creative_label(0.0) == "repetitive"
        assert creative_label(0.34) == "repetitive"

    def test_boundary_values(self):
        assert creative_label(1.0) == "exploring"
        assert creative_label(0.749) == "expressive"
        assert creative_label(0.549) == "focused"
        assert creative_label(0.349) == "repetitive"


# -----------------------------------------------------------------------
# 12. load_strokes
# -----------------------------------------------------------------------


class TestLoadStrokes:
    def test_load_normal(self, tmp_path):
        strokes = [_make_stroke("hello world", i) for i in range(5)]
        p = _write_strokes_jsonl(tmp_path, strokes)
        loaded = load_strokes(path=p, n=5)
        assert len(loaded) == 5
        assert loaded[0]["text"] == "hello world"

    def test_load_tail(self, tmp_path):
        strokes = [_make_stroke(f"stroke {i}", i) for i in range(20)]
        p = _write_strokes_jsonl(tmp_path, strokes)
        loaded = load_strokes(path=p, n=5)
        assert len(loaded) == 5
        assert loaded[0]["text"] == "stroke 15"

    def test_missing_file(self, tmp_path):
        loaded = load_strokes(path=tmp_path / "nonexistent.jsonl")
        assert loaded == []

    def test_malformed_lines(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            '{"seq": 1, "text": "good"}\n'
            'this is not json\n'
            '{"seq": 3, "text": "also good"}\n'
        )
        loaded = load_strokes(path=p)
        assert len(loaded) == 2

    def test_n_larger_than_file(self, tmp_path):
        strokes = [_make_stroke("only three", i) for i in range(3)]
        p = _write_strokes_jsonl(tmp_path, strokes)
        loaded = load_strokes(path=p, n=100)
        assert len(loaded) == 3


# -----------------------------------------------------------------------
# 13. creative_range_report
# -----------------------------------------------------------------------


class TestCreativeRangeReport:
    def test_full_report(self, tmp_path):
        strokes = _make_strokes([
            "Running through the forest at dawn brings clarity.",
            "However, the system crashed again with terrible errors.",
            "Beautiful progress in the quantum computing lab today.",
            "I think the medieval architecture is wonderful and amazing.",
            "In the morning, we debug. In the evening, we write.",
        ])
        p = _write_strokes_jsonl(tmp_path, strokes)
        report = creative_range_report(path=p, n=10)
        assert report["strokes_analysed"] == 5
        assert "creative_range_score" in report
        assert "label" in report
        assert report["label"] in ("exploring", "expressive", "focused", "repetitive")

    def test_empty_report(self, tmp_path):
        report = creative_range_report(path=tmp_path / "nope.jsonl")
        assert report["strokes_analysed"] == 0
        assert report["creative_range_score"] == 0.0
        assert report["label"] == "repetitive"

    def test_all_metrics_present(self, tmp_path):
        strokes = _make_strokes(["hello world test"] * 5)
        p = _write_strokes_jsonl(tmp_path, strokes)
        report = creative_range_report(path=p)
        expected = [
            "vocabulary_richness", "sentence_length_cv",
            "topic_diversity", "structural_variety", "polarity_range",
        ]
        for key in expected:
            assert key in report
            assert "score" in report[key]


# -----------------------------------------------------------------------
# 14. creative_range_summary
# -----------------------------------------------------------------------


class TestCreativeRangeSummary:
    def test_basic_summary(self):
        report = {
            "strokes_analysed": 100,
            "creative_range_score": 0.65,
            "label": "expressive",
            "vocabulary_richness": {"score": 0.7},
            "topic_diversity": {"score": 0.6},
            "structural_variety": {"score": 0.5},
        }
        s = creative_range_summary(report)
        assert "expressive" in s
        assert "100" in s
        assert "0.65" in s

    def test_empty_report(self):
        report = {
            "strokes_analysed": 0,
            "creative_range_score": 0.0,
            "label": "repetitive",
            "vocabulary_richness": {"score": 0.0},
            "topic_diversity": {"score": 0.0},
            "structural_variety": {"score": 0.0},
        }
        s = creative_range_summary(report)
        assert "repetitive" in s
        assert "0 strokes" in s


# -----------------------------------------------------------------------
# 15. _cli
# -----------------------------------------------------------------------


class TestCLI:
    def test_default_output(self, tmp_path, capsys):
        strokes = _make_strokes(["test sentence here now today"] * 5)
        p = _write_strokes_jsonl(tmp_path, strokes)
        with patch(
            "iamai.writer_creative_range.DEFAULT_STROKES_PATH", p
        ):
            rc = _cli([])
        assert rc == 0
        out = capsys.readouterr().out
        assert "creative range" in out

    def test_json_output(self, tmp_path, capsys):
        strokes = _make_strokes(["test sentence here now today"] * 5)
        p = _write_strokes_jsonl(tmp_path, strokes)
        with patch(
            "iamai.writer_creative_range.DEFAULT_STROKES_PATH", p
        ):
            rc = _cli(["--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "creative_range_score" in data

    def test_custom_n(self, tmp_path, capsys):
        strokes = _make_strokes(["word"] * 50)
        p = _write_strokes_jsonl(tmp_path, strokes)
        with patch(
            "iamai.writer_creative_range.DEFAULT_STROKES_PATH", p
        ):
            rc = _cli(["-n", "10", "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["strokes_analysed"] == 10


# -----------------------------------------------------------------------
# 16. Edge cases
# -----------------------------------------------------------------------


class TestEdgeCases:
    def test_single_word_strokes(self):
        strokes = _make_strokes(["hello"] * 10)
        vr = vocabulary_richness(strokes)
        assert vr["ttr"] == 0.1  # 1 unique / 10 total
        assert vr["unique_words"] == 1
        assert vr["total_words"] == 10

    def test_very_long_text(self):
        # Use alphabetic-only words so tokenizer picks them all up
        base_words = [
            "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta",
            "theta", "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron",
            "pi", "rho", "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega",
        ]
        # Repeat the set to make a long text
        long_text = " ".join(base_words * 10)
        strokes = _make_strokes([long_text])
        vr = vocabulary_richness(strokes)
        assert vr["unique_words"] == 24
        assert vr["total_words"] == 240

    def test_special_characters_only(self):
        strokes = _make_strokes(["!@#$ %^&* ()"])
        vr = vocabulary_richness(strokes)
        assert vr["total_words"] == 0
        assert vr["score"] == 0.0

    def test_unicode_text(self):
        strokes = _make_strokes(["café résumé naïve"])
        vr = vocabulary_richness(strokes)
        assert vr["total_words"] >= 3

    def test_identical_strokes(self):
        strokes = _make_strokes(["same exact text"] * 50)
        report_metrics = {
            "vocabulary_richness": vocabulary_richness(strokes),
            "sentence_length_cv": sentence_length_cv(strokes),
            "topic_diversity": topic_diversity(strokes),
            "structural_variety": structural_variety(strokes),
            "polarity_range": polarity_range(strokes),
        }
        score = creative_range_score(report_metrics)
        # Identical strokes should produce a low score
        assert score < 0.5

    def test_all_kinds(self):
        """Different stroke kinds should all work."""
        strokes = [
            {"seq": 1, "at": "2026-01-01T00:00:00", "kind": "thought", "text": "thinking about code"},
            {"seq": 2, "at": "2026-01-01T00:01:00", "kind": "note", "text": "noting the weather"},
            {"seq": 3, "at": "2026-01-01T00:02:00", "kind": "snippet", "text": "def foo(): pass"},
        ]
        vr = vocabulary_richness(strokes)
        assert vr["total_words"] > 0

    def test_score_monotonic_with_diversity(self):
        """More diverse input should score higher than less diverse."""
        low_div = _make_strokes(["the system is running"] * 30)
        high_div = _make_strokes([
            "quantum entanglement spooky action distance",
            "medieval architecture gothic cathedral stone",
            "tropical rainforest biodiversity canopy species",
            "algorithmic trading profit margin stock",
            "philosophical existential meaning purpose life",
            "culinary recipe spice ingredient kitchen",
            "astronomical observation nebula galaxy star",
            "mathematical proof theorem conjecture logic",
            "musical composition symphony harmony rhythm",
            "architectural design blueprint structure form",
        ] * 3)

        low_metrics = {
            "vocabulary_richness": vocabulary_richness(low_div),
            "sentence_length_cv": sentence_length_cv(low_div),
            "topic_diversity": topic_diversity(low_div),
            "structural_variety": structural_variety(low_div),
            "polarity_range": polarity_range(low_div),
        }
        high_metrics = {
            "vocabulary_richness": vocabulary_richness(high_div),
            "sentence_length_cv": sentence_length_cv(high_div),
            "topic_diversity": topic_diversity(high_div),
            "structural_variety": structural_variety(high_div),
            "polarity_range": polarity_range(high_div),
        }

        low_score = creative_range_score(low_metrics)
        high_score = creative_range_score(high_metrics)
        assert high_score > low_score
