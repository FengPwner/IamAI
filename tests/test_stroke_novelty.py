"""Tests for iamai.stroke_novelty — content repetition detector."""

import pytest

from iamai.stroke_novelty import (
    StrokeNovelty,
    StrokeNoveltyResult,
    _jaccard,
    _tokenise,
    classify_novelty,
    classify_stream,
)


# ---------------------------------------------------------------------------
# Tokenisation helpers
# ---------------------------------------------------------------------------


class TestTokenise:
    def test_basic(self):
        tokens = _tokenise("Hello World")
        assert tokens == {"hello", "world"}

    def test_strips_digits(self):
        tokens = _tokenise("commit 1700 files 1081")
        assert tokens == {"commit", "files"}

    def test_removes_stop_words(self):
        tokens = _tokenise("the quick brown fox is a very fast animal")
        # "the", "is", "a", "very" are stop words
        assert "the" not in tokens
        assert "is" not in tokens
        assert "quick" in tokens
        assert "brown" in tokens

    def test_removes_single_chars(self):
        tokens = _tokenise("I am a fox")
        # "i" and "a" removed (single char); "am" is a stop-word, also removed
        assert tokens == {"fox"}

    def test_punctuation_stripped(self):
        tokens = _tokenise("hello, world! foo-bar.baz")
        assert tokens == {"hello", "world", "foo", "bar", "baz"}

    def test_empty_string(self):
        assert _tokenise("") == set()

    def test_all_stopwords(self):
        assert _tokenise("the a an is are was") == set()


# ---------------------------------------------------------------------------
# Jaccard similarity
# ---------------------------------------------------------------------------


class TestJaccard:
    def test_identical_sets(self):
        assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self):
        assert _jaccard({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial_overlap(self):
        # {a, b} & {b, c} = {b}, union = {a, b, c}
        assert abs(_jaccard({"a", "b"}, {"b", "c"}) - 1 / 3) < 1e-9

    def test_both_empty(self):
        assert _jaccard(set(), set()) == 0.0

    def test_one_empty(self):
        assert _jaccard({"a"}, set()) == 0.0


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


class TestClassifyNovelty:
    def test_fresh(self):
        assert classify_novelty(0.80) == "fresh"
        assert classify_novelty(0.70) == "fresh"

    def test_familiar(self):
        assert classify_novelty(0.55) == "familiar"
        assert classify_novelty(0.40) == "familiar"

    def test_repetitive(self):
        assert classify_novelty(0.25) == "repetitive"
        assert classify_novelty(0.15) == "repetitive"

    def test_clone(self):
        assert classify_novelty(0.10) == "clone"
        assert classify_novelty(0.0) == "clone"


class TestClassifyStream:
    def test_healthy(self):
        assert classify_stream(clone_frac=0.05, repetitive_or_clone_frac=0.20) == "healthy"

    def test_stagnating(self):
        assert classify_stream(clone_frac=0.20, repetitive_or_clone_frac=0.45) == "stagnating"

    def test_loop(self):
        assert classify_stream(clone_frac=0.65, repetitive_or_clone_frac=0.80) == "loop"

    def test_boundary_healthy(self):
        assert classify_stream(0.0, 0.39) == "healthy"

    def test_boundary_stagnating(self):
        assert classify_stream(0.0, 0.40) == "stagnating"

    def test_boundary_loop(self):
        assert classify_stream(0.60, 0.80) == "loop"


# ---------------------------------------------------------------------------
# StrokeNovelty — construction
# ---------------------------------------------------------------------------


class TestStrokeNoveltyInit:
    def test_defaults(self):
        sn = StrokeNovelty()
        assert sn.lookback == 10
        assert sn.count == 0

    def test_custom_lookback(self):
        sn = StrokeNovelty(lookback=5)
        assert sn.lookback == 5

    def test_lookback_minimum(self):
        sn = StrokeNovelty(lookback=0)
        assert sn.lookback == 1


# ---------------------------------------------------------------------------
# score_stroke
# ---------------------------------------------------------------------------


class TestScoreStroke:
    def test_first_stroke_is_fresh(self):
        sn = StrokeNovelty()
        r = sn.score_stroke("the quick brown fox jumps over the lazy dog")
        assert r.verdict == "fresh"
        assert r.novelty == 1.0
        assert r.nearest_neighbour == -1
        assert sn.count == 1

    def test_identical_stroke_is_clone(self):
        sn = StrokeNovelty()
        sn.score_stroke("the quick brown fox jumps over the lazy dog", seq=1)
        r = sn.score_stroke("the quick brown fox jumps over the lazy dog", seq=2)
        assert r.verdict == "clone"
        assert r.nearest_neighbour == 1

    def test_similar_stroke_is_repetitive(self):
        sn = StrokeNovelty()
        sn.score_stroke("tests are the part of a repository that argues back", seq=1)
        r = sn.score_stroke("tests are the part of a codebase that argues back", seq=2)
        # Most words overlap; should be repetitive or clone depending on ratio.
        assert r.verdict in ("clone", "repetitive")
        assert r.nearest_neighbour == 1

    def test_different_stroke_is_fresh(self):
        sn = StrokeNovelty()
        sn.score_stroke("the quick brown fox jumps over the lazy dog", seq=1)
        r = sn.score_stroke("quantum computing enables polynomial factoring", seq=2)
        assert r.verdict == "fresh"
        assert r.novelty > 0.5

    def test_auto_seq(self):
        sn = StrokeNovelty()
        r1 = sn.score_stroke("alpha beta gamma")
        r2 = sn.score_stroke("delta epsilon zeta")
        assert r1.seq == 0
        assert r2.seq == 1

    def test_empty_text_is_fresh(self):
        sn = StrokeNovelty()
        r = sn.score_stroke("", seq=0)
        assert r.verdict == "fresh"
        assert r.novelty == 1.0


# ---------------------------------------------------------------------------
# score_many
# ---------------------------------------------------------------------------


class TestScoreMany:
    def test_batch(self):
        sn = StrokeNovelty()
        strokes = [
            {"text": "the build server caught fire at dawn", "seq": 10},
            {"text": "refactoring legacy code is archaeological work", "seq": 11},
            {"text": "the build server caught fire at dusk", "seq": 12},
        ]
        results = sn.score_many(strokes)
        assert len(results) == 3
        assert results[0].verdict == "fresh"
        # Third stroke is very similar to the first.
        assert results[2].verdict in ("clone", "repetitive")

    def test_seq_from_dict(self):
        sn = StrokeNovelty()
        strokes = [
            {"text": "alpha beta", "seq": 5},
            {"text": "gamma delta", "seq": 6},
        ]
        results = sn.score_many(strokes)
        assert results[0].seq == 5
        assert results[1].seq == 6


# ---------------------------------------------------------------------------
# stream_verdict
# ---------------------------------------------------------------------------


class TestStreamVerdict:
    def test_empty(self):
        sn = StrokeNovelty()
        v = sn.stream_verdict()
        assert v["verdict"] == "healthy"
        assert v["total"] == 0

    def test_healthy_stream(self):
        sn = StrokeNovelty()
        unique_texts = [
            "quantum entanglement defies classical intuition",
            "refactoring legacy code reveals forgotten assumptions",
            "the build pipeline failed because of a missing semicolon",
            "distributed consensus requires more messages than you think",
            "garbage collection pauses are the tax on managed memory",
        ]
        for i, t in enumerate(unique_texts):
            sn.score_stroke(t, seq=i)
        v = sn.stream_verdict()
        assert v["verdict"] == "healthy"
        assert v["fresh"] == len(unique_texts)

    def test_loop_stream(self):
        sn = StrokeNovelty()
        # Repeat the same text many times.
        for i in range(10):
            sn.score_stroke("tests are the part of a repository that argues back", seq=i)
        v = sn.stream_verdict()
        assert v["verdict"] == "loop"
        assert v["clone"] >= 6  # at least 60% should be clones

    def test_stagnating_stream(self):
        sn = StrokeNovelty()
        # Alternate between two similar phrases.
        texts = [
            "ten minutes is long enough to be honest and short enough to be boring",
            "ten minutes is long enough to be truthful and short enough to be tedious",
        ] * 10
        for i, t in enumerate(texts):
            sn.score_stroke(t, seq=i)
        v = sn.stream_verdict()
        assert v["verdict"] in ("stagnating", "loop")

    def test_window_limits_scope(self):
        sn = StrokeNovelty()
        # 5 fresh, then 10 clones.
        for i in range(5):
            sn.score_stroke(f"completely unique topic number {i} about widgets", seq=i)
        for i in range(5, 15):
            sn.score_stroke("the same old refrain about testing code", seq=i)
        # window=10 should only see the last 10 (all similar).
        v = sn.stream_verdict(window=10)
        assert v["total"] == 10

    def test_avg_novelty_range(self):
        sn = StrokeNovelty()
        for i in range(5):
            sn.score_stroke(f"unique thought about topic number {i}", seq=i)
        v = sn.stream_verdict()
        assert 0.0 <= v["avg_novelty"] <= 1.0


# ---------------------------------------------------------------------------
# StrokeNoveltyResult
# ---------------------------------------------------------------------------


class TestStrokeNoveltyResult:
    def test_to_dict(self):
        r = StrokeNoveltyResult(
            seq=42, novelty=0.8123, repetition=0.1877,
            nearest_neighbour=10, verdict="fresh",
        )
        d = r.to_dict()
        assert d["seq"] == 42
        assert d["novelty"] == 0.8123
        assert d["repetition"] == 0.1877
        assert d["nearest_neighbour"] == 10
        assert d["verdict"] == "fresh"

    def test_frozen(self):
        r = StrokeNoveltyResult(seq=1, novelty=0.5, repetition=0.5,
                                nearest_neighbour=0, verdict="familiar")
        with pytest.raises(AttributeError):
            r.novelty = 0.9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_clears_state(self):
        sn = StrokeNovelty()
        sn.score_stroke("hello world", seq=0)
        sn.score_stroke("foo bar", seq=1)
        assert sn.count == 2
        sn.reset()
        assert sn.count == 0
        # After reset, first stroke should be fresh again.
        r = sn.score_stroke("hello world", seq=0)
        assert r.verdict == "fresh"


# ---------------------------------------------------------------------------
# Lookback window
# ---------------------------------------------------------------------------


class TestLookback:
    def test_lookback_limits_comparison(self):
        sn = StrokeNovelty(lookback=2)
        sn.score_stroke("alpha beta gamma delta", seq=1)
        sn.score_stroke("epsilon zeta eta theta", seq=2)
        sn.score_stroke("iota kappa lambda mu", seq=3)
        # seq 4 is identical to seq 1, but lookback=2 only sees seq 2, 3.
        r = sn.score_stroke("alpha beta gamma delta", seq=4)
        # Should not match seq 1 (out of lookback window).
        assert r.nearest_neighbour != 1

    def test_lookback_one(self):
        sn = StrokeNovelty(lookback=1)
        sn.score_stroke("hello world foo bar baz", seq=1)
        # seq 2 is identical to seq 1 — clone.
        r2 = sn.score_stroke("hello world foo bar baz", seq=2)
        assert r2.verdict == "clone"
        assert r2.nearest_neighbour == 1
        # seq 3 is different; lookback=1 only sees seq 2.
        r3 = sn.score_stroke("quantum physics explains everything", seq=3)
        # seq 2 has no overlap with seq 3 → novelty high.
        assert r3.verdict == "fresh"
        assert r3.nearest_neighbour == -1  # zero similarity → no neighbour
