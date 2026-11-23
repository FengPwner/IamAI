#!/usr/bin/env python3
"""Tests for writer_paragraph_architecture module."""

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iamai.writer_paragraph_architecture import (
    STOP_WORDS,
    _classify,
    _content_words,
    _empty_result,
    _jaccard_similarity,
    _pearson_correlation,
    _split_paragraphs,
    _split_sentences,
    _tokenize,
    _word_set,
    architecture_report,
    architecture_summary,
    compute_paragraph_architecture,
    main,
)


# ===================================================================
# _tokenize
# ===================================================================

class TestTokenize:
    def test_basic(self):
        assert _tokenize("Hello world") == ["hello", "world"]

    def test_short_words_filtered(self):
        result = _tokenize("a big cat is on the mat")
        assert "big" in result
        assert "cat" in result
        assert "mat" in result
        assert "a" not in result

    def test_punctuation_stripped(self):
        assert _tokenize("one, two; three!") == ["one", "two", "three"]

    def test_empty(self):
        assert _tokenize("") == []

    def test_mixed_case(self):
        assert _tokenize("UPPER lower") == ["upper", "lower"]

    def test_two_char_words_filtered(self):
        result = _tokenize("go to my big house")
        assert "go" not in result
        assert "big" in result
        assert "house" in result


# ===================================================================
# _content_words
# ===================================================================

class TestContentWords:
    def test_filters_stop_words(self):
        tokens = ["the", "big", "cat", "is", "running", "through", "garden"]
        result = _content_words(tokens)
        assert "the" not in result
        assert "is" not in result
        assert "big" in result
        assert "cat" in result

    def test_empty(self):
        assert _content_words([]) == []

    def test_all_stop_words(self):
        tokens = ["the", "and", "but", "for"]
        assert _content_words(tokens) == []


# ===================================================================
# _split_paragraphs
# ===================================================================

class TestSplitParagraphs:
    def test_basic(self):
        text = "First paragraph.\n\nSecond paragraph."
        result = _split_paragraphs(text)
        assert len(result) == 2

    def test_single(self):
        text = "Just one paragraph."
        result = _split_paragraphs(text)
        assert len(result) == 1

    def test_multiple_blanks(self):
        text = "One.\n\n\nTwo.\n\n\n\nThree."
        result = _split_paragraphs(text)
        assert len(result) == 3

    def test_empty(self):
        assert _split_paragraphs("") == []

    def test_strips_whitespace(self):
        text = "  First  \n\n  Second  "
        result = _split_paragraphs(text)
        assert result[0] == "First"
        assert result[1] == "Second"


# ===================================================================
# _split_sentences
# ===================================================================

class TestSplitSentences:
    def test_basic(self):
        text = "First sentence. Second sentence. Third sentence."
        result = _split_sentences(text)
        assert len(result) == 3

    def test_question_and_exclamation(self):
        text = "What? Yes! Really."
        result = _split_sentences(text)
        assert len(result) == 3

    def test_single_sentence(self):
        text = "Just one sentence."
        result = _split_sentences(text)
        assert len(result) == 1

    def test_empty(self):
        assert _split_sentences("") == []


# ===================================================================
# _word_set
# ===================================================================

class TestWordSet:
    def test_content_words_only(self):
        result = _word_set("The big cat sat on the mat")
        assert "big" in result
        assert "cat" in result
        assert "sat" in result
        # Stop words filtered
        assert "the" not in result
        assert "on" not in result

    def test_empty(self):
        assert _word_set("") == set()


# ===================================================================
# _jaccard_similarity
# ===================================================================

class TestJaccardSimilarity:
    def test_identical(self):
        s = {"cat", "dog", "bird"}
        assert _jaccard_similarity(s, s) == 1.0

    def test_disjoint(self):
        assert _jaccard_similarity({"cat"}, {"dog"}) == 0.0

    def test_partial_overlap(self):
        a = {"cat", "dog", "bird"}
        b = {"cat", "dog", "fish"}
        # intersection=2, union=4
        assert _jaccard_similarity(a, b) == pytest.approx(0.5)

    def test_both_empty(self):
        assert _jaccard_similarity(set(), set()) == 0.0

    def test_one_empty(self):
        assert _jaccard_similarity({"cat"}, set()) == 0.0

    def test_subset(self):
        a = {"cat", "dog"}
        b = {"cat", "dog", "bird"}
        # intersection=2, union=3
        assert _jaccard_similarity(a, b) == pytest.approx(2 / 3)


# ===================================================================
# _pearson_correlation
# ===================================================================

class TestPearsonCorrelation:
    def test_perfect_positive(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0, 4.0, 6.0, 8.0, 10.0]
        assert _pearson_correlation(x, y) == pytest.approx(1.0)

    def test_perfect_negative(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [10.0, 8.0, 6.0, 4.0, 2.0]
        assert _pearson_correlation(x, y) == pytest.approx(-1.0)

    def test_no_correlation(self):
        # Roughly uncorrelated
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [3.0, 1.0, 5.0, 2.0, 4.0]
        r = _pearson_correlation(x, y)
        assert abs(r) < 0.3

    def test_constant_x(self):
        x = [5.0, 5.0, 5.0]
        y = [1.0, 2.0, 3.0]
        assert _pearson_correlation(x, y) == 0.0

    def test_single_element(self):
        assert _pearson_correlation([1.0], [2.0]) == 0.0

    def test_empty(self):
        assert _pearson_correlation([], []) == 0.0


# ===================================================================
# compute_paragraph_architecture — empty / minimal
# ===================================================================

class TestComputeEmpty:
    def test_empty_texts(self):
        result = compute_paragraph_architecture([])
        assert result["total_paragraphs"] == 0
        assert result["architecture_label"] == "loose"

    def test_none_equivalent(self):
        result = compute_paragraph_architecture([])
        assert result == _empty_result()


# ===================================================================
# compute_paragraph_architecture — basic metrics
# ===================================================================

class TestComputeBasic:
    def test_single_paragraph(self):
        text = "This is a test paragraph about software testing. " \
               "The software needs careful testing to work properly."
        result = compute_paragraph_architecture([text])
        assert result["total_paragraphs"] == 1
        assert result["mean_paragraph_length"] > 0
        assert result["paragraph_length_cv"] == 0.0  # only one para

    def test_two_paragraphs(self):
        text = (
            "First paragraph about software engineering practices. "
            "The engineering team builds reliable software systems.\n\n"
            "Second paragraph about database optimization techniques. "
            "The optimization process improves database performance significantly."
        )
        result = compute_paragraph_architecture([text])
        assert result["total_paragraphs"] == 2
        assert result["mean_paragraph_length"] > 0
        assert result["median_paragraph_length"] > 0

    def test_multiple_paragraphs(self):
        paras = [
            "The server processes incoming requests efficiently. "
            "Each request receives careful attention from the routing layer.",
            "Database connections require pooling strategies. "
            "The pooling mechanism reduces connection overhead significantly.",
            "Cache invalidation remains a challenging problem. "
            "The cache layer implements timestamp-based expiry rules.",
        ]
        text = "\n\n".join(paras)
        result = compute_paragraph_architecture([text])
        assert result["total_paragraphs"] == 3
        assert result["paragraph_length_cv"] >= 0


# ===================================================================
# compute_paragraph_architecture — length progression
# ===================================================================

class TestLengthProgression:
    def test_lengthening_text(self):
        paras = [
            "Short paragraph here.",
            "This is a somewhat longer paragraph with more words in it.",
            "And this final paragraph is considerably longer than the previous ones, "
            "containing many more words and ideas to explore in detail.",
            "The concluding paragraph extends even further beyond the earlier ones, "
            "with additional elaboration and comprehensive coverage of the topic, "
            "including multiple clauses and subordinate phrases.",
        ]
        text = "\n\n".join(paras)
        result = compute_paragraph_architecture([text])
        assert result["length_progression"] > 0.5

    def test_shortening_text(self):
        paras = [
            "This opening paragraph contains many words and elaborate descriptions "
            "of the various systems and processes involved in the operation.",
            "The middle paragraph is shorter and more concise.",
            "Brief conclusion here.",
            "End.",
        ]
        text = "\n\n".join(paras)
        result = compute_paragraph_architecture([text])
        assert result["length_progression"] < -0.5

    def test_few_paragraphs_no_progression(self):
        text = "Single paragraph about testing."
        result = compute_paragraph_architecture([text])
        assert result["length_progression"] == 0.0


# ===================================================================
# compute_paragraph_architecture — internal cohesion
# ===================================================================

class TestInternalCohesion:
    def test_high_cohesion(self):
        # Sentences share many content words
        text = (
            "The database optimization process begins with indexing. "
            "Database indexing improves query performance significantly. "
            "The optimization strategy relies on proper indexing techniques."
        )
        result = compute_paragraph_architecture([text])
        assert result["internal_cohesion"] > 0.1

    def test_low_cohesion(self):
        # Each sentence about different topics
        text = (
            "The elephant walked through the savanna slowly. "
            "Quantum physics explores subatomic particle behavior. "
            "Medieval architecture featured elaborate stone carvings."
        )
        result = compute_paragraph_architecture([text])
        assert result["internal_cohesion"] < 0.1


# ===================================================================
# compute_paragraph_architecture — transition strength
# ===================================================================

class TestTransitionStrength:
    def test_strong_transitions(self):
        text = (
            "The database needs careful optimization strategies.\n\n"
            "Optimization strategies include indexing and caching.\n\n"
            "Caching mechanisms reduce database load effectively."
        )
        result = compute_paragraph_architecture([text])
        assert result["transition_strength"] > 0.0

    def test_no_transition(self):
        text = (
            "Elephants roam the African savanna freely.\n\n"
            "Quantum computing uses qubits for calculation.\n\n"
            "Medieval castles featured defensive moats."
        )
        result = compute_paragraph_architecture([text])
        assert result["transition_strength"] == 0.0

    def test_single_paragraph_no_transition(self):
        text = "Just one paragraph about software testing."
        result = compute_paragraph_architecture([text])
        assert result["transition_strength"] == 0.0


# ===================================================================
# compute_paragraph_architecture — topic sentence rate
# ===================================================================

class TestTopicSentenceRate:
    def test_high_topic_rate(self):
        # First sentence introduces topic that recurs
        text = (
            "Database optimization requires careful planning. "
            "The planning process involves analyzing query patterns. "
            "Query analysis reveals optimization opportunities."
        )
        result = compute_paragraph_architecture([text])
        assert result["topic_sentence_rate"] > 0.0

    def test_no_topic_sentence(self):
        # Each sentence introduces entirely new words
        text = (
            "Elephants roam freely across the savanna. "
            "Quantum physics explores subatomic particles. "
            "Medieval architecture features stone carvings."
        )
        result = compute_paragraph_architecture([text])
        # First sentence words don't recur in rest
        assert result["topic_sentence_rate"] == 0.0


# ===================================================================
# compute_paragraph_architecture — architecture index
# ===================================================================

class TestArchitectureIndex:
    def test_well_structured_text(self):
        paras = [
            "Database optimization begins with careful analysis of query patterns. "
            "The analysis reveals bottlenecks in the existing system architecture. "
            "Systematic optimization then addresses each identified bottleneck.",
            "Query optimization requires understanding access patterns thoroughly. "
            "Access patterns determine which indexing strategy works best. "
            "The indexing strategy must align with actual query behavior.",
            "Performance monitoring validates the optimization efforts continuously. "
            "Continuous monitoring catches regressions before users notice them. "
            "Proactive monitoring transforms optimization from reactive to preventive.",
        ]
        text = "\n\n".join(paras)
        result = compute_paragraph_architecture([text])
        assert result["architecture_index"] > 0.0
        assert result["architecture_label"] in (
            "well-structured", "developing", "uniform", "loose"
        )

    def test_poorly_structured_text(self):
        text = "Random words scattered about.\n\nNo structure here.\n\nJust fragments."
        result = compute_paragraph_architecture([text])
        assert result["architecture_index"] < 0.5

    def test_index_bounded(self):
        text = (
            "First paragraph about software testing methodologies. "
            "Testing ensures quality.\n\n"
            "Second paragraph about deployment strategies.\n\n"
            "Third paragraph about monitoring."
        )
        result = compute_paragraph_architecture([text])
        assert 0.0 <= result["architecture_index"] <= 1.0


# ===================================================================
# _classify
# ===================================================================

class TestClassify:
    def test_monolithic(self):
        label = _classify(
            arch_index=0.5, length_cv=0.15, cohesion=0.15,
            topic_rate=0.7, mean_length=150, n_paragraphs=5,
        )
        assert label == "monolithic"

    def test_fragmented(self):
        label = _classify(
            arch_index=0.3, length_cv=0.20, cohesion=0.05,
            topic_rate=0.3, mean_length=10, n_paragraphs=10,
        )
        assert label == "fragmented"

    def test_well_structured(self):
        label = _classify(
            arch_index=0.75, length_cv=0.45, cohesion=0.15,
            topic_rate=0.70, mean_length=60, n_paragraphs=8,
        )
        assert label == "well-structured"

    def test_uniform(self):
        label = _classify(
            arch_index=0.50, length_cv=0.15, cohesion=0.08,
            topic_rate=0.40, mean_length=50, n_paragraphs=6,
        )
        assert label == "uniform"

    def test_loose_low_cohesion(self):
        label = _classify(
            arch_index=0.30, length_cv=0.50, cohesion=0.02,
            topic_rate=0.20, mean_length=50, n_paragraphs=5,
        )
        assert label == "loose"

    def test_developing(self):
        label = _classify(
            arch_index=0.45, length_cv=0.40, cohesion=0.08,
            topic_rate=0.45, mean_length=55, n_paragraphs=6,
        )
        assert label == "developing"

    def test_empty_paragraphs(self):
        label = _classify(
            arch_index=0.0, length_cv=0.0, cohesion=0.0,
            topic_rate=0.0, mean_length=0.0, n_paragraphs=0,
        )
        assert label == "loose"

    def test_fallback_loose(self):
        label = _classify(
            arch_index=0.20, length_cv=0.50, cohesion=0.06,
            topic_rate=0.35, mean_length=50, n_paragraphs=5,
        )
        assert label == "loose"


# ===================================================================
# _empty_result
# ===================================================================

class TestEmptyResult:
    def test_fields(self):
        result = _empty_result()
        assert result["total_paragraphs"] == 0
        assert result["mean_paragraph_length"] == 0.0
        assert result["architecture_index"] == 0.0
        assert result["architecture_label"] == "loose"

    def test_all_keys_present(self):
        result = _empty_result()
        expected_keys = {
            "total_paragraphs", "mean_paragraph_length",
            "median_paragraph_length", "paragraph_length_cv",
            "length_progression", "internal_cohesion",
            "transition_strength", "topic_sentence_rate",
            "architecture_index", "architecture_label",
        }
        assert set(result.keys()) == expected_keys


# ===================================================================
# architecture_summary
# ===================================================================

class TestArchitectureSummary:
    def test_contains_all_metrics(self):
        result = _empty_result()
        summary = architecture_summary(result)
        assert "Paragraphs" in summary
        assert "Mean length" in summary
        assert "cohesion" in summary.lower()
        assert "Architecture" in summary
        assert "loose" in summary

    def test_formatted_values(self):
        metrics = {
            "total_paragraphs": 5,
            "mean_paragraph_length": 45.3,
            "median_paragraph_length": 42.0,
            "paragraph_length_cv": 0.3521,
            "length_progression": 0.1234,
            "internal_cohesion": 0.0876,
            "transition_strength": 0.0432,
            "topic_sentence_rate": 0.6000,
            "architecture_index": 0.5678,
            "architecture_label": "developing",
        }
        summary = architecture_summary(metrics)
        assert "5" in summary
        assert "45.3" in summary
        assert "developing" in summary


# ===================================================================
# Multiple strokes integration
# ===================================================================

class TestMultipleStrokes:
    def test_combines_strokes(self):
        strokes = [
            "The database optimization process requires careful planning. "
            "Planning involves analyzing existing query patterns thoroughly.",
            "Cache invalidation strategies determine system reliability. "
            "Reliability depends on proper timeout configuration.",
            "Monitoring dashboards provide real-time performance visibility. "
            "Visibility enables proactive issue detection and resolution.",
        ]
        result = compute_paragraph_architecture(strokes)
        assert result["total_paragraphs"] >= 3
        assert result["architecture_index"] >= 0.0

    def test_varied_paragraph_lengths(self):
        strokes = [
            "Short one.",
            "This paragraph contains significantly more words than the previous one, "
            "providing detailed explanation of the underlying concepts and theories "
            "that govern the system behavior under various conditions.",
            "Medium length paragraph with some content.",
        ]
        text = "\n\n".join(strokes)
        result = compute_paragraph_architecture([text])
        assert result["paragraph_length_cv"] > 0.3


# ===================================================================
# architecture_report (on-disk, smoke test)
# ===================================================================

class TestArchitectureReport:
    def test_returns_dict(self):
        result = architecture_report(10)
        assert isinstance(result, dict)
        assert "strokes_analysed" in result
        assert "architecture_index" in result


# ===================================================================
# CLI
# ===================================================================

class TestCLI:
    def test_main_text_output(self, capsys):
        exit_code = main(["-n", "5"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Architecture" in captured.out

    def test_main_json_output(self, capsys):
        exit_code = main(["-n", "5", "--json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "architecture_index" in data
