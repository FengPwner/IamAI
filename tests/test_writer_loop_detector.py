"""Tests for tools/writer_loop_detector.py — content repetition loop detection."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from writer_loop_detector import (  # noqa: E402
    tokenize,
    word_set,
    jaccard_similarity,
    character_trigrams,
    trigram_overlap,
    pair_jaccard,
    pair_trigram_overlaps,
    max_loop_run,
    classify,
    health_score,
    extract_text,
    analyze_window,
    analyze,
    load_strokes,
)


# ---------------------------------------------------------------------------
# tokenize
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_empty(self):
        assert tokenize("") == []

    def test_basic(self):
        result = tokenize("Hello World")
        assert result == ["hello", "world"]

    def test_with_punctuation(self):
        result = tokenize("it's a test-case, right?")
        assert "it" in result
        assert "s" in result
        assert "test" in result

    def test_numbers(self):
        result = tokenize("version 3 of tool42")
        assert "3" in result
        assert "tool42" in result

    def test_only_punctuation(self):
        assert tokenize("...!!!???") == []


# ---------------------------------------------------------------------------
# word_set
# ---------------------------------------------------------------------------


class TestWordSet:
    def test_basic(self):
        assert word_set(["a", "b", "a"]) == {"a", "b"}

    def test_empty(self):
        assert word_set([]) == set()


# ---------------------------------------------------------------------------
# jaccard_similarity
# ---------------------------------------------------------------------------


class TestJaccardSimilarity:
    def test_identical_sets(self):
        s = {"a", "b", "c"}
        assert jaccard_similarity(s, s) == 1.0

    def test_disjoint_sets(self):
        assert jaccard_similarity({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial_overlap(self):
        a = {"a", "b", "c"}
        b = {"b", "c", "d"}
        # intersection=2, union=4
        assert jaccard_similarity(a, b) == pytest.approx(0.5)

    def test_both_empty(self):
        assert jaccard_similarity(set(), set()) == 0.0

    def test_one_empty(self):
        assert jaccard_similarity({"a"}, set()) == 0.0


# ---------------------------------------------------------------------------
# character_trigrams
# ---------------------------------------------------------------------------


class TestCharacterTrigrams:
    def test_short_string(self):
        result = character_trigrams("ab")
        assert result == {"ab"}

    def test_empty(self):
        assert character_trigrams("") == set()

    def test_normal(self):
        result = character_trigrams("hello")
        assert "hel" in result
        assert "ell" in result
        assert "llo" in result
        assert len(result) == 3

    def test_case_insensitive(self):
        assert character_trigrams("Hello") == character_trigrams("hello")


# ---------------------------------------------------------------------------
# trigram_overlap
# ---------------------------------------------------------------------------


class TestTrigramOverlap:
    def test_identical(self):
        assert trigram_overlap("hello world", "hello world") == 1.0

    def test_completely_different(self):
        assert trigram_overlap("abc", "xyz") == 0.0

    def test_partial(self):
        overlap = trigram_overlap("the quick brown fox", "the quick red fox")
        assert 0.0 < overlap < 1.0

    def test_empty_strings(self):
        assert trigram_overlap("", "") == 0.0


# ---------------------------------------------------------------------------
# pair_jaccard
# ---------------------------------------------------------------------------


class TestPairJaccard:
    def test_empty(self):
        assert pair_jaccard([]) == []

    def test_single(self):
        assert pair_jaccard(["hello"]) == []

    def test_two_identical(self):
        result = pair_jaccard(["the cat sat", "the cat sat"])
        assert len(result) == 1
        assert result[0] == 1.0

    def test_two_different(self):
        result = pair_jaccard(["alpha beta", "gamma delta"])
        assert len(result) == 1
        assert result[0] == 0.0

    def test_three_texts(self):
        texts = ["hello world", "hello world foo", "completely different"]
        result = pair_jaccard(texts)
        assert len(result) == 2
        assert result[0] > 0  # some overlap
        assert result[1] == 0.0  # no overlap


# ---------------------------------------------------------------------------
# pair_trigram_overlaps
# ---------------------------------------------------------------------------


class TestPairTrigramOverlaps:
    def test_empty(self):
        assert pair_trigram_overlaps([]) == []

    def test_single(self):
        assert pair_trigram_overlaps(["hello"]) == []

    def test_identical_pair(self):
        result = pair_trigram_overlaps(["hello world", "hello world"])
        assert len(result) == 1
        assert result[0] == 1.0


# ---------------------------------------------------------------------------
# max_loop_run
# ---------------------------------------------------------------------------


class TestMaxLoopRun:
    def test_empty(self):
        assert max_loop_run([], 0.5) == 0

    def test_all_below(self):
        assert max_loop_run([0.1, 0.2, 0.3], 0.5) == 0

    def test_all_above(self):
        assert max_loop_run([0.6, 0.7, 0.8], 0.5) == 3

    def test_mixed(self):
        sims = [0.6, 0.7, 0.3, 0.8, 0.9, 0.6, 0.2]
        # run1: 2 (indices 0,1), run2: 3 (indices 3,4,5)
        assert max_loop_run(sims, 0.5) == 3

    def test_single_above(self):
        assert max_loop_run([0.6], 0.5) == 1

    def test_exact_threshold(self):
        assert max_loop_run([0.5, 0.5], 0.5) == 2


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


class TestClassify:
    def test_healthy(self):
        assert classify(0) == "healthy"
        assert classify(1) == "healthy"

    def test_mild(self):
        assert classify(2) == "mild"

    def test_moderate(self):
        assert classify(3) == "moderate"
        assert classify(4) == "moderate"

    def test_severe(self):
        assert classify(5) == "severe"
        assert classify(10) == "severe"


# ---------------------------------------------------------------------------
# health_score
# ---------------------------------------------------------------------------


class TestHealthScore:
    def test_perfect_health(self):
        # low similarity, no runs
        score = health_score("healthy", 0.1, 0)
        assert score == 90  # 100*(1-0.1) = 90, no penalty

    def test_severe_loop(self):
        score = health_score("severe", 0.8, 6)
        # base = max(0, int(100*0.2)) = 20
        # penalty = min(40, 6*8) = 40
        # score = max(0, 20-40) = 0
        assert score == 0

    def test_moderate_loop(self):
        score = health_score("moderate", 0.5, 3)
        # base = 50, penalty = 24
        assert score == 26

    def test_bounded_zero(self):
        assert health_score("severe", 1.0, 10) == 0


# ---------------------------------------------------------------------------
# extract_text
# ---------------------------------------------------------------------------


class TestExtractText:
    def test_content_field(self):
        assert extract_text({"content": "hello"}) == "hello"

    def test_text_field(self):
        assert extract_text({"text": "world"}) == "world"

    def test_body_field(self):
        assert extract_text({"body": "test body"}) == "test body"

    def test_summary_field(self):
        assert extract_text({"summary": "a summary"}) == "a summary"

    def test_fallback_json(self):
        stroke = {"kind": "thought", "seq": 42}
        result = extract_text(stroke)
        parsed = json.loads(result)
        assert parsed["kind"] == "thought"

    def test_empty_content_skipped(self):
        assert extract_text({"content": "", "text": "fallback"}) == "fallback"

    def test_whitespace_only_skipped(self):
        assert extract_text({"content": "   ", "text": "fallback"}) == "fallback"


# ---------------------------------------------------------------------------
# analyze_window
# ---------------------------------------------------------------------------


class TestAnalyzeWindow:
    def test_empty(self):
        result = analyze_window([])
        assert result["verdict"] == "healthy"
        assert result["health"] == 100
        assert result["pair_count"] == 0

    def test_single(self):
        result = analyze_window(["only one stroke"])
        assert result["verdict"] == "healthy"
        assert result["pair_count"] == 0

    def test_healthy_window(self):
        texts = [
            "the cat sat on the mat",
            "quantum computing uses qubits for processing",
            "mediterranean cuisine features olive oil extensively",
            "mountain climbing requires proper equipment and training",
            "jazz improvisation builds on chord progressions",
        ]
        result = analyze_window(texts)
        assert result["verdict"] == "healthy"
        assert result["health"] > 50
        assert result["pair_count"] == 4

    def test_looping_window(self):
        base = "the automated writer produces thoughtful content about various topics"
        texts = [base] * 8  # all identical
        result = analyze_window(texts)
        assert result["verdict"] == "severe"
        assert result["pair_jaccard_mean"] == 1.0
        assert result["max_run_length"] == 7  # 8 texts = 7 pairs

    def test_mild_repetition(self):
        texts = [
            "the quick brown fox jumps over the lazy dog",
            "the quick brown fox leaps over the lazy dog",  # similar
            "the quick brown fox jumps over the lazy dog",  # similar
            "completely different content about other matters",
            "another unique sentence entirely",
        ]
        result = analyze_window(texts)
        # First two pairs are similar, third breaks
        assert result["pair_count"] == 4

    def test_high_similarity_count(self):
        texts = ["hello world foo bar baz"] * 4
        result = analyze_window(texts)
        assert result["high_similarity_pairs"] == 3  # all pairs are identical


# ---------------------------------------------------------------------------
# analyze (integration with temp file)
# ---------------------------------------------------------------------------


class TestAnalyze:
    def test_with_temp_file(self, tmp_path: Path):
        strokes_file = tmp_path / "strokes.jsonl"
        strokes = [
            {"content": "first thought about cats", "kind": "thought"},
            {"content": "second thought about dogs", "kind": "thought"},
            {"content": "third thought about fish", "kind": "thought"},
        ]
        with open(strokes_file, "w") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")

        result = analyze(window=10, strokes_path=strokes_file)
        assert result["window"] == 3
        assert result["total_strokes"] == 3
        assert result["pair_count"] == 2
        assert result["verdict"] in ("healthy", "mild", "moderate", "severe")

    def test_missing_file(self, tmp_path: Path):
        result = analyze(strokes_path=tmp_path / "nonexistent.jsonl")
        assert result["verdict"] == "healthy"
        assert result["total_strokes"] == 0

    def test_malformed_lines_skipped(self, tmp_path: Path):
        strokes_file = tmp_path / "strokes.jsonl"
        with open(strokes_file, "w") as f:
            f.write('{"content": "valid stroke"}\n')
            f.write("this is not json\n")
            f.write('{"content": "another valid one"}\n')
            f.write("\n")  # empty line

        result = analyze(window=10, strokes_path=strokes_file)
        assert result["total_strokes"] == 2

    def test_window_truncation(self, tmp_path: Path):
        strokes_file = tmp_path / "strokes.jsonl"
        with open(strokes_file, "w") as f:
            for i in range(20):
                f.write(json.dumps({"content": f"stroke number {i}"}) + "\n")

        result = analyze(window=5, strokes_path=strokes_file)
        assert result["window"] == 5
        assert result["total_strokes"] == 20


# ---------------------------------------------------------------------------
# load_strokes
# ---------------------------------------------------------------------------


class TestLoadStrokes:
    def test_normal(self, tmp_path: Path):
        f = tmp_path / "s.jsonl"
        f.write_text('{"a":1}\n{"b":2}\n')
        result = load_strokes(f)
        assert len(result) == 2

    def test_skips_bad(self, tmp_path: Path):
        f = tmp_path / "s.jsonl"
        f.write_text('{"a":1}\nbroken\n{"b":2}\n')
        result = load_strokes(f)
        assert len(result) == 2

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "s.jsonl"
        f.write_text("")
        assert load_strokes(f) == []

    def test_missing(self, tmp_path: Path):
        assert load_strokes(tmp_path / "nope.jsonl") == []


# ---------------------------------------------------------------------------
# CLI (smoke test)
# ---------------------------------------------------------------------------


class TestCLI:
    def test_text_output(self, tmp_path: Path, capsys):
        strokes_file = tmp_path / "strokes.jsonl"
        with open(strokes_file, "w") as f:
            for i in range(5):
                f.write(json.dumps({"content": f"unique stroke content {i}"}) + "\n")

        from writer_loop_detector import main
        sys.argv = ["writer_loop_detector.py", "--strokes", str(strokes_file)]
        main()
        captured = capsys.readouterr()
        assert "Writer Loop Detector" in captured.out
        assert "verdict:" in captured.out

    def test_json_output(self, tmp_path: Path, capsys):
        strokes_file = tmp_path / "strokes.jsonl"
        with open(strokes_file, "w") as f:
            for i in range(5):
                f.write(json.dumps({"content": f"unique stroke content {i}"}) + "\n")

        from writer_loop_detector import main
        sys.argv = ["writer_loop_detector.py", "--json", "--strokes", str(strokes_file)]
        main()
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "verdict" in parsed
        assert "health" in parsed
