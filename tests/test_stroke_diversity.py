"""Tests for iamai.stroke_diversity module."""

import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_diversity import (
    analyse,
    drift_score,
    mean_length,
    repetition_ratio,
    theme_entropy,
    vocabulary_richness,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _make_strokes(texts, kinds=None):
    strokes = []
    for i, text in enumerate(texts):
        s = {"text": text, "seq": i}
        if kinds:
            s["kind"] = kinds[i % len(kinds)]
        strokes.append(s)
    return strokes


DIVERSE_TEXTS = [
    "the quick brown fox jumps over the lazy dog",
    "quantum entanglement defies classical intuition",
    "baking sourdough requires patience and wild yeast",
    "neural networks learn hierarchical representations",
    "mountain streams carve valleys over millennia",
    "jazz improvisation follows hidden harmonic structures",
    "cryptographic hashes are one-way functions",
    "coral reefs support immense marine biodiversity",
    "lambda calculus underpins functional programming",
    "photosynthesis converts sunlight into chemical energy",
]

REPEATED_TEXTS = [
    "automation fails quietly so the log must speak",
    "automation fails quietly so the log must speak",
    "automation fails quietly so the log must speak loudly",
    "automation fails quietly so the log must speak",
    "automation fails quietly so the log must speak today",
    "automation fails quietly so the log must speak",
    "automation fails quietly so the log must speak now",
    "automation fails quietly so the log must speak",
    "automation fails quietly so the log must speak clearly",
    "automation fails quietly so the log must speak",
]

MIXED_KINDS = ["note", "thought", "snippet", "devlog", "garden", "metrics"]


# ---------------------------------------------------------------------------
# vocabulary_richness
# ---------------------------------------------------------------------------


class TestVocabularyRichness:
    def test_empty(self):
        assert vocabulary_richness([]) == 0.0

    def test_single_token(self):
        strokes = _make_strokes(["hello"])
        assert vocabulary_richness(strokes) == 1.0

    def test_all_unique(self):
        strokes = _make_strokes(["one two three four five"])
        assert vocabulary_richness(strokes) == 1.0

    def test_all_repeated(self):
        strokes = _make_strokes(["go go go go"])
        assert vocabulary_richness(strokes) == 0.25

    def test_diverse_corpus_higher_than_repetitive(self):
        diverse = _make_strokes(DIVERSE_TEXTS)
        repeated = _make_strokes(REPEATED_TEXTS)
        assert vocabulary_richness(diverse) > vocabulary_richness(repeated)


# ---------------------------------------------------------------------------
# mean_length
# ---------------------------------------------------------------------------


class TestMeanLength:
    def test_empty(self):
        assert mean_length([]) == 0.0

    def test_uniform(self):
        strokes = _make_strokes(["abcde", "fghij", "klmno"])
        assert mean_length(strokes) == 5.0

    def test_mixed(self):
        strokes = _make_strokes(["a", "abc", "abcde"])
        assert mean_length(strokes) == 3.0


# ---------------------------------------------------------------------------
# repetition_ratio
# ---------------------------------------------------------------------------


class TestRepetitionRatio:
    def test_empty(self):
        assert repetition_ratio([]) == 0.0

    def test_single(self):
        assert repetition_ratio([{"text": "hi"}]) == 0.0

    def test_all_identical(self):
        strokes = _make_strokes(["same text"] * 5)
        assert repetition_ratio(strokes, threshold=0.85, lookback=3) > 0.5

    def test_all_unique(self):
        strokes = _make_strokes(DIVERSE_TEXTS)
        assert repetition_ratio(strokes, threshold=0.85, lookback=3) == 0.0

    def test_repetitive_higher_than_diverse(self):
        rep = _make_strokes(REPEATED_TEXTS)
        div = _make_strokes(DIVERSE_TEXTS)
        assert repetition_ratio(rep) > repetition_ratio(div)


# ---------------------------------------------------------------------------
# theme_entropy
# ---------------------------------------------------------------------------


class TestThemeEntropy:
    def test_empty(self):
        assert theme_entropy([]) == 0.0

    def test_single_kind(self):
        strokes = _make_strokes(["a", "b", "c"], kinds=["note"] * 3)
        assert theme_entropy(strokes) == 0.0

    def test_uniform_distribution(self):
        strokes = _make_strokes(["a", "b", "c", "d"], kinds=["note", "thought"])
        ent = theme_entropy(strokes)
        assert abs(ent - 1.0) < 1e-6  # 2 categories, 50/50 → 1 bit

    def test_six_categories(self):
        texts = ["x"] * 60
        kinds = ["note", "thought", "snippet", "devlog", "garden", "metrics"]
        strokes = _make_strokes(texts, kinds=kinds)
        ent = theme_entropy(strokes)
        expected = math.log2(6)  # ~2.585 bits
        assert abs(ent - expected) < 0.01


# ---------------------------------------------------------------------------
# drift_score
# ---------------------------------------------------------------------------


class TestDriftScore:
    def test_insufficient_data(self):
        strokes = _make_strokes(["hello"] * 5)
        assert drift_score(strokes, window=10) == 0.0

    def test_no_drift(self):
        text = "the same vocabulary used throughout every single stroke"
        strokes = _make_strokes([text] * 100)
        assert drift_score(strokes, window=20) == 0.0

    def test_complete_drift(self):
        older = ["alpha beta gamma delta epsilon"] * 50
        newer = ["one two three four five six seven"] * 50
        strokes = _make_strokes(older + newer)
        ds = drift_score(strokes, window=50)
        assert ds > 0.8  # very different vocabularies

    def test_partial_drift(self):
        older = ["common word alpha beta"] * 50
        newer = ["common word gamma delta"] * 50
        strokes = _make_strokes(older + newer)
        ds = drift_score(strokes, window=50)
        assert 0.2 < ds < 0.8


# ---------------------------------------------------------------------------
# analyse (composite)
# ---------------------------------------------------------------------------


class TestAnalyse:
    def test_sparse_verdict(self):
        strokes = _make_strokes(["hello"] * 5)
        report = analyse(strokes)
        assert report["verdict"] == "sparse"

    def test_stale_verdict_high_repetition(self):
        strokes = _make_strokes(REPEATED_TEXTS * 5)
        report = analyse(strokes)
        assert report["verdict"] == "stale"

    def test_healthy_verdict(self):
        strokes = _make_strokes(DIVERSE_TEXTS * 5, kinds=MIXED_KINDS * 5)
        report = analyse(strokes)
        assert report["verdict"] in ("healthy", "sparse")

    def test_report_keys(self):
        strokes = _make_strokes(DIVERSE_TEXTS)
        report = analyse(strokes)
        expected_keys = {
            "vocabulary_richness",
            "mean_length",
            "repetition_ratio",
            "theme_entropy",
            "drift_score",
            "stroke_count",
            "verdict",
        }
        assert set(report.keys()) == expected_keys

    def test_stroke_count(self):
        strokes = _make_strokes(DIVERSE_TEXTS)
        report = analyse(strokes)
        assert report["stroke_count"] == len(DIVERSE_TEXTS)
