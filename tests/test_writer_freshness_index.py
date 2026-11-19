"""Tests for iamai.writer_freshness_index — lexical novelty measurement."""

import json
import tempfile
from pathlib import Path

import pytest

from iamai.writer_freshness_index import (
    FreshnessAnalyser,
    FreshnessReport,
    _tokenise,
)


# ── helpers ────────────────────────────────────────────────────────────

def _make_strokes(texts, base_seq=1):
    """Build stroke dicts from a list of text strings."""
    return [
        {"seq": base_seq + i, "at": "2026-01-01T00:00:00+00:00",
         "kind": "thought", "text": t}
        for i, t in enumerate(texts)
    ]


def _write_jsonl(strokes, path):
    with open(path, "w", encoding="utf-8") as fh:
        for s in strokes:
            fh.write(json.dumps(s) + "\n")


# ── _tokenise ──────────────────────────────────────────────────────────

class TestTokenise:

    def test_basic_tokenisation(self):
        assert _tokenise("Hello World", include_stopwords=True) == ["hello", "world"]

    def test_strips_punctuation(self):
        assert _tokenise("don't worry, be happy!", include_stopwords=True) == [
            "don't", "worry", "be", "happy",
        ]

    def test_excludes_stopwords_by_default(self):
        result = _tokenise("the quick brown fox is a lazy dog")
        assert "the" not in result
        assert "is" not in result
        assert "a" not in result
        assert "quick" in result
        assert "brown" in result

    def test_empty_string(self):
        assert _tokenise("") == []
        assert _tokenise("", include_stopwords=True) == []

    def test_numbers_preserved(self):
        assert _tokenise("version 42 release", include_stopwords=True) == [
            "version", "42", "release",
        ]


# ── FreshnessAnalyser (in-memory) ──────────────────────────────────────

class TestFreshnessAnalyser:

    def test_all_novel_when_no_history(self):
        strokes = _make_strokes(["alpha beta gamma"])
        fa = FreshnessAnalyser(strokes, include_stopwords=True)
        r = fa.report(window_size=10)
        assert r.freshness_index == 1.0
        assert r.novel_tokens == r.recent_tokens

    def test_all_repeated_when_history_covers_recent(self):
        strokes = _make_strokes([
            "hello world",
            "foo bar",
            "hello world foo bar",  # recent: all tokens in history
        ])
        fa = FreshnessAnalyser(strokes, include_stopwords=True)
        r = fa.report(window_size=1)
        assert r.freshness_index == 0.0
        assert r.novel_tokens == 0

    def test_mixed_freshness(self):
        strokes = _make_strokes([
            "the cat sat on the mat",          # history
            "the cat ran across the bridge",    # recent: 'ran', 'across', 'bridge' are novel
        ])
        fa = FreshnessAnalyser(strokes, include_stopwords=True)
        r = fa.report(window_size=1)
        assert r.novel_tokens > 0
        assert 0.0 < r.freshness_index < 1.0

    def test_window_size_larger_than_corpus(self):
        strokes = _make_strokes(["alpha", "beta"])
        fa = FreshnessAnalyser(strokes, include_stopwords=True)
        r = fa.report(window_size=100)
        assert r.window_size == 2  # clamped
        assert r.freshness_index == 1.0  # no history, all novel

    def test_window_size_must_be_positive(self):
        fa = FreshnessAnalyser(_make_strokes(["x"]))
        with pytest.raises(ValueError, match="window_size must be positive"):
            fa.report(window_size=0)

    def test_empty_strokes_list(self):
        fa = FreshnessAnalyser([], include_stopwords=True)
        r = fa.report(window_size=5)
        assert r.window_size == 0
        assert r.recent_tokens == 0

    def test_novel_token_occurrences_counted(self):
        strokes = _make_strokes([
            "old stuff here",
            "brand new word brand new word",
        ])
        fa = FreshnessAnalyser(strokes, include_stopwords=True)
        r = fa.report(window_size=1)
        # 'brand', 'new', 'word' are all novel
        assert r.novel_tokens == 3
        # "brand new word brand new word" -> brand:2, new:2, word:2 = 6
        assert r.novel_token_occurrences == 6

    def test_top_novel_and_repeated(self):
        history = _make_strokes(["alpha beta gamma"] * 3, base_seq=1)
        recent = _make_strokes(
            ["alpha delta epsilon delta epsilon delta"],
            base_seq=10,
        )
        fa = FreshnessAnalyser(history + recent, include_stopwords=True)
        r = fa.report(window_size=1, top_n=5)
        # delta(3) and epsilon(2) are novel; alpha(1) is repeated
        assert r.top_novel[0] == ("delta", 3)
        assert r.top_novel[1] == ("epsilon", 2)
        assert r.top_repeated[0] == ("alpha", 1)

    def test_repetition_index_complement(self):
        strokes = _make_strokes(["hello world", "hello world"])
        fa = FreshnessAnalyser(strokes, include_stopwords=True)
        r = fa.report(window_size=1)
        assert abs(r.freshness_index + r.repetition_index - 1.0) < 1e-9

    def test_stopword_exclusion_affects_novelty(self):
        strokes = _make_strokes([
            "the cat sat",
            "the cat ran",
        ])
        # Without stopwords: 'the' is excluded, so only 'cat','sat'/'ran' matter
        fa_no_sw = FreshnessAnalyser(strokes, include_stopwords=False)
        r_no_sw = fa_no_sw.report(window_size=1)
        # 'ran' is the only novel token in recent (after excluding stopwords)
        assert "ran" in [t for t, _ in r_no_sw.top_novel]


# ── FreshnessAnalyser.from_jsonl ───────────────────────────────────────

class TestFreshnessFromJsonl:

    def test_loads_from_jsonl(self, tmp_path):
        strokes = _make_strokes([
            "first stroke about old things",
            "second stroke about new discoveries",
        ])
        p = tmp_path / "strokes.jsonl"
        _write_jsonl(strokes, p)
        fa = FreshnessAnalyser.from_jsonl(p, include_stopwords=True)
        r = fa.report(window_size=1)
        assert r.corpus_size == 2
        assert r.freshness_index > 0.0

    def test_empty_jsonl(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        fa = FreshnessAnalyser.from_jsonl(p)
        r = fa.report(window_size=5)
        assert r.corpus_size == 0


# ── FreshnessReport.summary ────────────────────────────────────────────

class TestFreshnessReportSummary:

    def test_high_freshness_summary(self):
        r = FreshnessReport(
            window_size=10, total_history_tokens=100,
            recent_tokens=50, novel_tokens=30,
            freshness_index=0.60, novel_token_occurrences=45,
            repetition_index=0.40,
            top_novel=[("newword", 5), ("another", 3)],
            top_repeated=[("old", 10)],
            corpus_size=20,
        )
        s = r.summary()
        assert "high" in s.lower()
        assert "30/50" in s

    def test_low_freshness_summary(self):
        r = FreshnessReport(
            window_size=10, total_history_tokens=100,
            recent_tokens=50, novel_tokens=5,
            freshness_index=0.10, novel_token_occurrences=8,
            repetition_index=0.90,
            top_novel=[("rare", 2)],
            top_repeated=[("common", 20)],
            corpus_size=20,
        )
        s = r.summary()
        assert "low" in s.lower()

    def test_moderate_freshness_summary(self):
        r = FreshnessReport(
            window_size=10, total_history_tokens=100,
            recent_tokens=50, novel_tokens=15,
            freshness_index=0.30, novel_token_occurrences=20,
            repetition_index=0.70,
            top_novel=[("mid", 3)],
            top_repeated=[("base", 15)],
            corpus_size=20,
        )
        s = r.summary()
        assert "moderate" in s.lower()

    def test_no_tokens_summary(self):
        r = FreshnessReport(
            window_size=10, total_history_tokens=0,
            recent_tokens=0, novel_tokens=0,
            freshness_index=1.0, novel_token_occurrences=0,
            repetition_index=0.0,
            top_novel=[], top_repeated=[],
            corpus_size=0,
        )
        s = r.summary()
        assert "no tokens" in s.lower()
