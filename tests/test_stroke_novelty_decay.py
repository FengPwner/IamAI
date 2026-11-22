"""tests for stroke_novelty_decay module — 40 tests."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import pytest
from stroke_novelty_decay import (
    NoveltyDecay,
    NoveltyPoint,
    novelty_report,
    _tokenize,
)


# ============================================================
# _tokenize
# ============================================================

class TestTokenize:
    def test_basic(self):
        assert _tokenize("Hello World") == ["hello", "world"]

    def test_punctuation_stripped(self):
        assert _tokenize("a, b; c.") == ["a", "b", "c"]

    def test_chinese_chars(self):
        tokens = _tokenize("测试 one two")
        assert "测试" in tokens
        assert "one" in tokens

    def test_empty(self):
        assert _tokenize("") == []

    def test_numbers(self):
        assert _tokenize("stroke 42") == ["stroke", "42"]


# ============================================================
# NoveltyPoint
# ============================================================

class TestNoveltyPoint:
    def test_fields(self):
        p = NoveltyPoint(index=10, ratio=0.35, novel_count=7, total_count=20)
        assert p.index == 10
        assert p.ratio == 0.35
        assert p.novel_count == 7
        assert p.total_count == 20

    def test_frozen(self):
        assert NoveltyPoint(1, 0.01, 1, 100).band() == "frozen"

    def test_decayed(self):
        assert NoveltyPoint(1, 0.05, 5, 100).band() == "decayed"

    def test_stale(self):
        assert NoveltyPoint(1, 0.15, 15, 100).band() == "stale"

    def test_stable(self):
        assert NoveltyPoint(1, 0.30, 30, 100).band() == "stable"

    def test_fresh(self):
        assert NoveltyPoint(1, 0.50, 50, 100).band() == "fresh"

    def test_boundary_040(self):
        assert NoveltyPoint(1, 0.40, 40, 100).band() == "fresh"

    def test_boundary_025(self):
        assert NoveltyPoint(1, 0.25, 25, 100).band() == "stable"

    def test_boundary_010(self):
        assert NoveltyPoint(1, 0.10, 10, 100).band() == "stale"

    def test_boundary_003(self):
        assert NoveltyPoint(1, 0.03, 3, 100).band() == "decayed"

    def test_frozen_immutability(self):
        p = NoveltyPoint(1, 0.5, 5, 10)
        with pytest.raises(AttributeError):
            p.ratio = 0.1  # type: ignore


# ============================================================
# NoveltyDecay — construction & points
# ============================================================

def _build_texts(n: int, vocab_pool: list[str], new_each: int = 0) -> list[str]:
    """build n strokes from vocab_pool, optionally adding `new_each` unique words per stroke."""
    texts = []
    for i in range(n):
        words = list(vocab_pool)
        for j in range(new_each):
            words.append(f"novel_{i}_{j}")
        texts.append(" ".join(words))
    return texts


class TestNoveltyDecayPoints:
    def test_empty(self):
        nd = NoveltyDecay([], window=5, step=2)
        assert nd.points() == []

    def test_single_stroke(self):
        nd = NoveltyDecay(["hello world"], window=5, step=2)
        assert nd.points() == []

    def test_basic_window(self):
        texts = _build_texts(10, ["alpha", "beta", "gamma"])
        nd = NoveltyDecay(texts, window=5, step=5)
        pts = nd.points()
        # idx starts at window(5), then 5+step(5)=10 → 2 points
        assert len(pts) == 2
        assert pts[0].index == 5
        assert pts[1].index == 10

    def test_two_windows(self):
        texts = _build_texts(20, ["alpha", "beta"])
        nd = NoveltyDecay(texts, window=5, step=5)
        pts = nd.points()
        assert len(pts) >= 2

    def test_novelty_zero_when_no_new_words(self):
        # all strokes identical → after first window, no novelty
        texts = ["hello world"] * 20
        nd = NoveltyDecay(texts, window=5, step=5)
        pts = nd.points()
        # second window onward: everything was seen in prior windows
        for p in pts[1:]:
            assert p.ratio == 0.0

    def test_novelty_positive_when_new_words(self):
        base = ["alpha", "beta"]
        texts = []
        for i in range(20):
            texts.append(" ".join(base + [f"unique_{i}"]))
        nd = NoveltyDecay(texts, window=5, step=5)
        pts = nd.points()
        # every window has some new tokens
        assert any(p.ratio > 0 for p in pts)

    def test_latest(self):
        texts = _build_texts(15, ["x", "y"], new_each=1)
        nd = NoveltyDecay(texts, window=5, step=5)
        lat = nd.latest()
        assert lat is not None
        assert lat == nd.points()[-1]

    def test_latest_none_when_empty(self):
        nd = NoveltyDecay([], window=5, step=2)
        assert nd.latest() is None

    def test_window_equals_length(self):
        texts = _build_texts(5, ["a", "b"])
        nd = NoveltyDecay(texts, window=5, step=1)
        pts = nd.points()
        assert len(pts) == 1
        assert pts[0].index == 5

    def test_step_one(self):
        texts = _build_texts(10, ["a", "b"])
        nd = NoveltyDecay(texts, window=5, step=1)
        pts = nd.points()
        assert len(pts) == 6  # indices 5..10


# ============================================================
# NoveltyDecay — trend
# ============================================================

class TestNoveltyDecayTrend:
    def test_insufficient_data(self):
        texts = _build_texts(5, ["a"])
        nd = NoveltyDecay(texts, window=5, step=5)
        assert nd.trend() == "insufficient_data"

    def test_steady(self):
        # each stroke adds one novel word to a repeated base → roughly constant novelty
        texts = []
        for i in range(60):
            texts.append(f"common base words here item_{i}")
        nd = NoveltyDecay(texts, window=10, step=5)
        # after the initial window, novelty stabilizes around a constant ratio
        assert nd.trend() == "steady"

    def test_declining(self):
        # first half has unique words, second half repeats
        texts = []
        for i in range(30):
            texts.append(" ".join([f"word_{i}_{j}" for j in range(10)]))
        for i in range(30):
            texts.append("common repeated text here always the same")
        nd = NoveltyDecay(texts, window=10, step=5)
        trend = nd.trend()
        assert trend in ("declining", "collapsed")

    def test_improving(self):
        # early: repetitive content (low novelty after initial window)
        # late: each stroke introduces many unique words (high novelty)
        texts = []
        # 30 strokes of highly repetitive content
        for i in range(30):
            texts.append("the same repeated words over and over again")
        # 30 strokes of richly unique content
        for i in range(30):
            unique_words = [f"novel_{i}_{j}" for j in range(20)]
            texts.append(" ".join(unique_words))
        nd = NoveltyDecay(texts, window=10, step=5)
        assert nd.trend() == "improving"


# ============================================================
# NoveltyDecay — summary
# ============================================================

class TestNoveltyDecaySummary:
    def test_keys(self):
        texts = _build_texts(20, ["a", "b"], new_each=1)
        nd = NoveltyDecay(texts, window=5, step=5)
        s = nd.summary()
        expected = {"total_strokes", "window", "step", "num_points",
                    "latest_ratio", "latest_band", "trend"}
        assert expected.issubset(s.keys())

    def test_empty_summary(self):
        nd = NoveltyDecay([], window=5, step=2)
        s = nd.summary()
        assert s["latest_ratio"] is None
        assert s["latest_band"] is None
        assert s["num_points"] == 0

    def test_values_consistent(self):
        texts = _build_texts(30, ["x"], new_each=2)
        nd = NoveltyDecay(texts, window=5, step=5)
        s = nd.summary()
        assert s["total_strokes"] == 30
        assert s["window"] == 5
        assert s["step"] == 5
        assert s["num_points"] == len(nd.points())


# ============================================================
# novelty_report
# ============================================================

class TestNoveltyReport:
    def test_basic_format(self):
        texts = _build_texts(30, ["a", "b"], new_each=1)
        r = novelty_report(texts, window=5, step=5)
        assert "novelty:" in r
        assert "trend=" in r

    def test_insufficient(self):
        r = novelty_report([], window=5, step=2)
        assert "insufficient" in r

    def test_single(self):
        r = novelty_report(["hello"], window=5, step=2)
        assert "insufficient" in r

    def test_percentage_format(self):
        texts = _build_texts(20, ["a"], new_each=3)
        r = novelty_report(texts, window=5, step=5)
        assert "%" in r


# ============================================================
# edge cases
# ============================================================

class TestEdgeCases:
    def test_identical_strokes(self):
        texts = ["repeat"] * 100
        nd = NoveltyDecay(texts, window=10, step=10)
        pts = nd.points()
        assert len(pts) >= 2
        # after first window all tokens known
        assert all(p.ratio == 0.0 for p in pts[1:])

    def test_completely_unique_strokes(self):
        # each stroke is a single unique word (no shared tokens)
        texts = [f"word{i:04d}" for i in range(50)]
        nd = NoveltyDecay(texts, window=5, step=5)
        pts = nd.points()
        # after first window, every token in the next window is novel
        for p in pts[1:]:
            assert p.ratio == 1.0

    def test_mixed_content(self):
        texts = []
        for i in range(40):
            base = "the quick brown fox jumps"
            if i % 3 == 0:
                base += f" special_event_{i}"
            texts.append(base)
        nd = NoveltyDecay(texts, window=10, step=5)
        pts = nd.points()
        assert len(pts) >= 2

    def test_window_larger_than_data(self):
        texts = _build_texts(3, ["a", "b"])
        nd = NoveltyDecay(texts, window=100, step=5)
        assert nd.points() == []

    def test_zero_total_tokens(self):
        # all empty strings
        texts = [""] * 20
        nd = NoveltyDecay(texts, window=5, step=5)
        pts = nd.points()
        for p in pts:
            assert p.ratio == 0.0
            assert p.novel_count == 0
