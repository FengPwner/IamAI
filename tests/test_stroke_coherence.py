"""Tests for iamai.stroke_coherence module."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_coherence import (
    analyse,
    coherence_grade,
    jaccard,
    mean_run_length,
    pairwise_similarities,
    topic_stability,
    _tokenise,
    DEFAULT_STABILITY_THRESHOLD,
)


# ── _tokenise ─────────────────────────────────────────────────


class TestTokenise:
    def test_basic(self):
        tokens = _tokenise("the garden grows slowly")
        assert tokens == {"garden", "grows", "slowly"}

    def test_strips_stopwords(self):
        tokens = _tokenise("it is a very beautiful day")
        assert "it" not in tokens
        assert "is" not in tokens
        assert "a" not in tokens
        assert "very" not in tokens
        assert "beautiful" in tokens
        assert "day" in tokens

    def test_strips_short_tokens(self):
        tokens = _tokenise("i am ok")
        # "i" and "am" are stopwords; "ok" is len 2 but not a stopword
        assert "ok" in tokens

    def test_empty_string(self):
        assert _tokenise("") == set()

    def test_case_insensitive(self):
        assert _tokenise("Garden GROWS") == _tokenise("garden grows")

    def test_punctuation_handling(self):
        tokens = _tokenise("hello, world! test-case.")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens
        assert "case" in tokens


# ── jaccard ───────────────────────────────────────────────────


class TestJaccard:
    def test_identical_sets(self):
        s = {"a", "b", "c"}
        assert jaccard(s, s) == 1.0

    def test_disjoint_sets(self):
        assert jaccard({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial_overlap(self):
        # {a,b} ∩ {b,c} = {b}, {a,b} ∪ {b,c} = {a,b,c}
        assert abs(jaccard({"a", "b"}, {"b", "c"}) - 1 / 3) < 1e-9

    def test_empty_sets(self):
        assert jaccard(set(), set()) == 0.0

    def test_one_empty(self):
        assert jaccard({"a"}, set()) == 0.0

    def test_subset(self):
        # {a} ⊂ {a,b,c}  → 1/3
        assert abs(jaccard({"a"}, {"a", "b", "c"}) - 1 / 3) < 1e-9


# ── pairwise_similarities ─────────────────────────────────────


class TestPairwiseSimilarities:
    def test_empty(self):
        assert pairwise_similarities([]) == []

    def test_single_stroke(self):
        assert pairwise_similarities([{"text": "hello world"}]) == []

    def test_two_identical_strokes(self):
        strokes = [{"text": "garden grows"}, {"text": "garden grows"}]
        sims = pairwise_similarities(strokes)
        assert len(sims) == 1
        assert sims[0] == 1.0

    def test_two_disjoint_strokes(self):
        strokes = [{"text": "garden grows"}, {"text": "python async"}]
        sims = pairwise_similarities(strokes)
        assert len(sims) == 1
        assert sims[0] == 0.0

    def test_three_strokes_two_pairs(self):
        strokes = [
            {"text": "the garden grows slowly"},
            {"text": "slow growth in the garden"},
            {"text": "python async event loop"},
        ]
        sims = pairwise_similarities(strokes)
        assert len(sims) == 2
        # First pair shares "garden", "grows"/"growth", "slowly"/"slow"
        assert sims[0] > 0.1
        # Second pair shares very little
        assert sims[1] < 0.1

    def test_custom_text_key(self):
        strokes = [{"content": "hello world"}, {"content": "hello world"}]
        sims = pairwise_similarities(strokes, text_key="content")
        assert sims[0] == 1.0

    def test_missing_text_key(self):
        strokes = [{"other": "data"}, {"other": "data"}]
        sims = pairwise_similarities(strokes)
        assert sims == [0.0]


# ── topic_stability ───────────────────────────────────────────


class TestTopicStability:
    def test_empty(self):
        assert topic_stability([]) == 0.0

    def test_all_above(self):
        assert topic_stability([0.2, 0.3, 0.4]) == 1.0

    def test_all_below(self):
        assert topic_stability([0.01, 0.02, 0.03]) == 0.0

    def test_mixed(self):
        # 2 of 4 above 0.15
        result = topic_stability([0.2, 0.05, 0.3, 0.01])
        assert abs(result - 0.5) < 1e-9

    def test_custom_threshold(self):
        sims = [0.10, 0.20, 0.30]
        assert topic_stability(sims, threshold=0.25) == 1 / 3
        assert abs(topic_stability(sims, threshold=0.25) - 1 / 3) < 1e-9

    def test_exact_threshold(self):
        assert topic_stability([0.15], threshold=0.15) == 1.0


# ── mean_run_length ───────────────────────────────────────────


class TestMeanRunLength:
    def test_empty(self):
        assert mean_run_length([]) == 0.0

    def test_no_runs(self):
        assert mean_run_length([0.01, 0.02, 0.03]) == 0.0

    def test_single_run(self):
        # Three consecutive above threshold = run of 3
        assert mean_run_length([0.2, 0.3, 0.4]) == 3.0

    def test_two_runs(self):
        # Run of 2, then break, then run of 1 → mean = 1.5
        sims = [0.2, 0.3, 0.01, 0.2]
        assert mean_run_length(sims) == 1.5

    def test_all_one_run(self):
        assert mean_run_length([0.5, 0.5, 0.5, 0.5]) == 4.0

    def test_alternating(self):
        # Above, below, above, below → two runs of 1 each → mean 1.0
        sims = [0.2, 0.01, 0.2, 0.01]
        assert mean_run_length(sims) == 1.0


# ── coherence_grade ───────────────────────────────────────────


class TestCoherenceGrade:
    def test_threaded(self):
        assert coherence_grade(0.35) == "threaded"
        assert coherence_grade(0.30) == "threaded"

    def test_loose(self):
        assert coherence_grade(0.25) == "loose"
        assert coherence_grade(0.18) == "loose"

    def test_scattered(self):
        assert coherence_grade(0.15) == "scattered"
        assert coherence_grade(0.10) == "scattered"

    def test_disjointed(self):
        assert coherence_grade(0.05) == "disjointed"
        assert coherence_grade(0.0) == "disjointed"


# ── analyse (integration) ─────────────────────────────────────


class TestAnalyse:
    def test_empty_strokes(self):
        report = analyse([])
        assert report["pairwise_similarity"] == 0.0
        assert report["topic_stability"] == 0.0
        assert report["run_length"] == 0.0
        assert report["n_pairs"] == 0
        assert report["coherence_grade"] == "disjointed"

    def test_single_stroke(self):
        report = analyse([{"text": "hello world"}])
        assert report["n_pairs"] == 0

    def test_coherent_sequence(self):
        strokes = [
            {"text": "the garden grows with careful attention"},
            {"text": "careful garden attention yields deep roots"},
            {"text": "deep roots anchor the growing garden"},
            {"text": "growing garden needs strong roots"},
        ]
        report = analyse(strokes)
        assert report["n_pairs"] == 3
        assert report["pairwise_similarity"] > 0.1
        assert report["topic_stability"] > 0.3
        assert report["coherence_grade"] in ("threaded", "loose")

    def test_incoherent_sequence(self):
        strokes = [
            {"text": "python async programming patterns"},
            {"text": "ancient roman aqueducts carried water"},
            {"text": "banana bread recipe requires ripe bananas"},
            {"text": "quantum entanglement defies classical physics"},
        ]
        report = analyse(strokes)
        assert report["n_pairs"] == 3
        assert report["pairwise_similarity"] < 0.1
        assert report["coherence_grade"] == "disjointed"

    def test_mixed_sequence(self):
        strokes = [
            {"text": "the writer produces diverse content"},
            {"text": "diverse content includes thoughts and notes"},
            {"text": "python async event loops are efficient"},
            {"text": "quantum computing uses qubits"},
        ]
        report = analyse(strokes)
        assert report["n_pairs"] == 3
        assert 0.0 < report["pairwise_similarity"] < 0.5

    def test_returns_all_keys(self):
        strokes = [{"text": "a"}, {"text": "b"}]
        report = analyse(strokes)
        expected_keys = {
            "pairwise_similarity",
            "topic_stability",
            "run_length",
            "coherence_grade",
            "n_pairs",
        }
        assert set(report.keys()) == expected_keys

    def test_custom_threshold(self):
        strokes = [
            {"text": "garden grows"},
            {"text": "garden blooms"},
        ]
        # With very high threshold, this pair should be unstable
        report = analyse(strokes, stability_threshold=0.9)
        assert report["topic_stability"] == 0.0

        # With very low threshold, should be stable
        report = analyse(strokes, stability_threshold=0.01)
        assert report["topic_stability"] == 1.0
