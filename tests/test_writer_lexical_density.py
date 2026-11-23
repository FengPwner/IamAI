#!/usr/bin/env python3
"""Tests for iamai.writer_lexical_density — lexical density analysis."""

import json
import math
import os
import sys
import tempfile
import textwrap

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_lexical_density import (
    _classify_density,
    _empty_result,
    _guess_class,
    _shannon_entropy,
    _tokenize,
    compute_lexical_density,
    lexical_density_report,
    lexical_density_summary,
    main,
)


# =========================================================================
# _tokenize
# =========================================================================

class TestTokenize:
    def test_basic(self):
        tokens = _tokenize("Hello world")
        assert tokens == ["hello", "world"]

    def test_empty(self):
        assert _tokenize("") == []

    def test_whitespace_only(self):
        assert _tokenize("   \n\t  ") == []

    def test_punctuation_stripped(self):
        tokens = _tokenize("Hello, world! How's it?")
        assert tokens == ["hello", "world", "how's", "it"]

    def test_numbers_skipped(self):
        tokens = _tokenize("There are 42 items here")
        assert "42" not in tokens
        assert tokens == ["there", "are", "items", "here"]

    def test_contractions(self):
        tokens = _tokenize("don't can't won't")
        assert "don't" in tokens
        assert "can't" in tokens

    def test_unicode_letters(self):
        # Only ASCII letters in our regex, so accented chars are skipped.
        tokens = _tokenize("café résumé")
        # "caf" and "sum" might appear depending on regex — just check no crash
        assert isinstance(tokens, list)


# =========================================================================
# _guess_class
# =========================================================================

class TestGuessClass:
    def test_function_article(self):
        assert _guess_class("the") == "function"

    def test_function_pronoun(self):
        assert _guess_class("they") == "function"

    def test_function_preposition(self):
        assert _guess_class("in") == "function"

    def test_function_auxiliary(self):
        assert _guess_class("will") == "function"

    def test_function_conjunction(self):
        assert _guess_class("and") == "function"

    def test_content_noun_suffix(self):
        assert _guess_class("architecture") == "noun"

    def test_content_verb_suffix(self):
        assert _guess_class("analyse") == "verb"

    def test_content_adjective_suffix(self):
        assert _guess_class("beautiful") == "adjective"

    def test_content_adverb_suffix(self):
        assert _guess_class("quickly") == "adverb"

    def test_force_content(self):
        assert _guess_class("run") == "verb"
        assert _guess_class("think") == "verb"

    def test_unknown_defaults_to_noun(self):
        assert _guess_class("xyzzyplugh") == "noun"


# =========================================================================
# _shannon_entropy
# =========================================================================

class TestShannonEntropy:
    def test_empty(self):
        assert _shannon_entropy({}) == 0.0

    def test_single_class(self):
        assert _shannon_entropy({"a": 10}) == 0.0

    def test_uniform_two(self):
        h = _shannon_entropy({"a": 5, "b": 5})
        assert abs(h - math.log(2)) < 0.001

    def test_uniform_four(self):
        h = _shannon_entropy({"a": 25, "b": 25, "c": 25, "d": 25})
        assert abs(h - math.log(4)) < 0.001

    def test_skewed(self):
        h = _shannon_entropy({"a": 97, "b": 1, "c": 1, "d": 1})
        assert 0 < h < math.log(4)


# =========================================================================
# _classify_density
# =========================================================================

class TestClassifyDensity:
    def test_very_dense(self):
        assert _classify_density(0.70) == "very_dense"
        assert _classify_density(0.65) == "very_dense"

    def test_dense(self):
        assert _classify_density(0.55) == "dense"
        assert _classify_density(0.50) == "dense"

    def test_moderate(self):
        assert _classify_density(0.45) == "moderate"
        assert _classify_density(0.40) == "moderate"

    def test_light(self):
        assert _classify_density(0.35) == "light"
        assert _classify_density(0.30) == "light"

    def test_very_light(self):
        assert _classify_density(0.25) == "very_light"
        assert _classify_density(0.0) == "very_light"


# =========================================================================
# _empty_result
# =========================================================================

class TestEmptyResult:
    def test_keys(self):
        r = _empty_result()
        expected = {
            "total_words", "content_words", "function_words",
            "lexical_density", "noun_ratio", "verb_ratio",
            "adjective_ratio", "adverb_ratio", "content_diversity",
            "density_label",
        }
        assert set(r.keys()) == expected

    def test_values(self):
        r = _empty_result()
        assert r["total_words"] == 0
        assert r["content_words"] == 0
        assert r["lexical_density"] == 0.0
        assert r["density_label"] == "very_light"


# =========================================================================
# compute_lexical_density — core
# =========================================================================

class TestComputeLexicalDensity:
    def test_empty_string(self):
        r = compute_lexical_density("")
        assert r["total_words"] == 0
        assert r["density_label"] == "very_light"

    def test_only_function_words(self):
        text = "the a an is are was were and or but in on at to for of"
        r = compute_lexical_density(text)
        assert r["content_words"] == 0
        assert r["lexical_density"] == 0.0

    def test_only_content_words(self):
        text = "architecture computation beautiful quickly"
        r = compute_lexical_density(text)
        assert r["function_words"] == 0
        assert r["lexical_density"] == 1.0
        assert r["density_label"] == "very_dense"

    def test_mixed(self):
        text = "the quick brown fox jumps over the lazy dog"
        r = compute_lexical_density(text)
        assert r["total_words"] > 0
        assert 0 < r["lexical_density"] < 1.0
        assert r["content_words"] + r["function_words"] == r["total_words"]

    def test_density_calculation(self):
        # 4 content + 2 function = 6 total → density = 4/6
        text = "architecture computation the the building design"
        r = compute_lexical_density(text)
        assert r["total_words"] == 6
        assert r["content_words"] == 4
        assert r["function_words"] == 2
        assert abs(r["lexical_density"] - 0.6667) < 0.01

    def test_ratios_sum_to_one(self):
        text = "the architecture is beautiful and runs quickly"
        r = compute_lexical_density(text)
        if r["content_words"] > 0:
            total_ratio = (r["noun_ratio"] + r["verb_ratio"] +
                           r["adjective_ratio"] + r["adverb_ratio"])
            assert abs(total_ratio - 1.0) < 0.01

    def test_content_diversity_nonzero(self):
        text = "architecture analyse beautiful quickly the system"
        r = compute_lexical_density(text)
        assert r["content_diversity"] > 0

    def test_field_completeness(self):
        r = compute_lexical_density("Hello world, this is a test.")
        expected_keys = {
            "total_words", "content_words", "function_words",
            "lexical_density", "noun_ratio", "verb_ratio",
            "adjective_ratio", "adverb_ratio", "content_diversity",
            "density_label",
        }
        assert set(r.keys()) == expected_keys

    def test_non_negative_values(self):
        r = compute_lexical_density("Some text with various words here.")
        for key in ("lexical_density", "noun_ratio", "verb_ratio",
                     "adjective_ratio", "adverb_ratio", "content_diversity"):
            assert r[key] >= 0.0

    def test_unicode_no_crash(self):
        r = compute_lexical_density("日本語 テスト café résumé naïve")
        assert isinstance(r, dict)
        assert r["total_words"] >= 0

    def test_single_word_content(self):
        r = compute_lexical_density("architecture")
        assert r["total_words"] == 1
        assert r["content_words"] == 1
        assert r["lexical_density"] == 1.0

    def test_single_word_function(self):
        r = compute_lexical_density("the")
        assert r["total_words"] == 1
        assert r["function_words"] == 1
        assert r["lexical_density"] == 0.0

    def test_repeated_content(self):
        r = compute_lexical_density("run run run run")
        assert r["content_words"] == 4
        assert r["lexical_density"] == 1.0
        # All verbs → verb_ratio = 1.0
        assert r["verb_ratio"] == 1.0

    def test_long_text(self):
        text = ("The complex architectural design requires careful "
                "analysis of structural requirements and building codes. "
                "Furthermore, the computational modelling provides "
                "important insights into material behaviour.")
        r = compute_lexical_density(text)
        assert r["total_words"] > 20
        assert 0 < r["lexical_density"] < 1.0
        assert r["density_label"] in ("very_dense", "dense", "moderate",
                                       "light", "very_light")

    def test_telegraphic_style(self):
        # Keyword-heavy → should be dense
        text = "server architecture database optimisation query performance"
        r = compute_lexical_density(text)
        assert r["density_label"] in ("very_dense", "dense")

    def test_conversational_style(self):
        # Lots of function words → should be light
        text = ("Well, I think that it is really important that we "
                "should all be able to have a good time and just "
                "enjoy the moment and not worry about anything")
        r = compute_lexical_density(text)
        assert r["density_label"] in ("light", "very_light", "moderate")


# =========================================================================
# lexical_density_report — on-disk integration
# =========================================================================

class TestLexicalDensityReport:
    def test_strokes_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl",
                                          delete=False) as f:
            f.write(json.dumps({"text": "the architecture is beautiful"}) + "\n")
            f.write(json.dumps({"text": "quickly running analyse"}) + "\n")
            f.name
        try:
            r = lexical_density_report(f.name)
            assert r["total_words"] > 0
            assert r["content_words"] > 0
        finally:
            os.unlink(f.name)

    def test_missing_file(self):
        r = lexical_density_report("/nonexistent/path/strokes.jsonl")
        assert r["total_words"] == 0
        assert r["density_label"] == "very_light"

    def test_malformed_jsonl(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl",
                                          delete=False) as f:
            f.write("this is not json\n")
            f.write(json.dumps({"text": "hello world"}) + "\n")
            fname = f.name
        try:
            r = lexical_density_report(fname)
            assert r["total_words"] >= 2  # at least "hello world"
        finally:
            os.unlink(fname)

    def test_empty_text_fields(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl",
                                          delete=False) as f:
            f.write(json.dumps({"text": ""}) + "\n")
            f.write(json.dumps({"text": "  "}) + "\n")
            fname = f.name
        try:
            r = lexical_density_report(fname)
            assert r["total_words"] == 0
        finally:
            os.unlink(fname)

    def test_body_fallback(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl",
                                          delete=False) as f:
            f.write(json.dumps({"body": "architecture computation"}) + "\n")
            fname = f.name
        try:
            r = lexical_density_report(fname)
            assert r["content_words"] == 2
        finally:
            os.unlink(fname)


# =========================================================================
# lexical_density_summary
# =========================================================================

class TestLexicalDensitySummary:
    def test_line_count(self):
        r = compute_lexical_density("The quick brown fox jumps.")
        s = lexical_density_summary(r)
        assert len(s.split("\n")) == 10

    def test_contains_key_fields(self):
        r = compute_lexical_density("The architecture is beautiful.")
        s = lexical_density_summary(r)
        assert "total words:" in s
        assert "lexical density:" in s
        assert "label:" in s

    def test_empty_summary(self):
        r = _empty_result()
        s = lexical_density_summary(r)
        assert "total words:     0" in s
        assert "very_light" in s


# =========================================================================
# CLI
# =========================================================================

class TestCLI:
    def test_exit_code(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl",
                                          delete=False) as f:
            f.write(json.dumps({"text": "hello world"}) + "\n")
            fname = f.name
        try:
            rc = main(["--strokes", fname])
            assert rc == 0
        finally:
            os.unlink(fname)

    def test_json_output(self, capsys):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl",
                                          delete=False) as f:
            f.write(json.dumps({"text": "architecture beautiful"}) + "\n")
            fname = f.name
        try:
            main(["--strokes", fname, "--json"])
            captured = capsys.readouterr()
            data = json.loads(captured.out)
            assert "lexical_density" in data
            assert data["total_words"] > 0
        finally:
            os.unlink(fname)

    def test_text_output(self, capsys):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl",
                                          delete=False) as f:
            f.write(json.dumps({"text": "the quick brown fox"}) + "\n")
            fname = f.name
        try:
            main(["--strokes", fname])
            captured = capsys.readouterr()
            assert "lexical density:" in captured.out
        finally:
            os.unlink(fname)


# =========================================================================
# Edge cases
# =========================================================================

class TestEdgeCases:
    def test_single_sentence(self):
        r = compute_lexical_density("Hello.")
        assert r["total_words"] == 1

    def test_numbers_only(self):
        r = compute_lexical_density("123 456 789")
        assert r["total_words"] == 0
        assert r["density_label"] == "very_light"

    def test_mixed_scripts(self):
        r = compute_lexical_density("hello 世界 world مرحبا")
        assert r["total_words"] >= 2  # at least hello, world

    def test_very_long_text(self):
        text = "the architecture is complex and beautiful " * 200
        r = compute_lexical_density(text)
        assert r["total_words"] > 1000
        assert 0 < r["lexical_density"] < 1.0

    def test_all_adverbs(self):
        text = "quickly slowly beautifully carefully easily"
        r = compute_lexical_density(text)
        assert r["adverb_ratio"] == 1.0
        assert r["lexical_density"] == 1.0

    def test_all_adjectives(self):
        text = "beautiful careful wonderful glorious"
        r = compute_lexical_density(text)
        assert r["adjective_ratio"] == 1.0

    def test_function_words_ratio(self):
        # Half function, half content
        text = "the architecture"
        r = compute_lexical_density(text)
        assert r["function_words"] == 1
        assert r["content_words"] == 1
        assert r["lexical_density"] == 0.5
