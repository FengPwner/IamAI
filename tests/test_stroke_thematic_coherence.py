"""Tests for stroke_thematic_coherence module.

Covers: tokenisation, TF vectors, cosine similarity, coherence analysis,
sliding windows, edge cases, classification thresholds, and the centroid
computation.  34 test functions.

Written by Qwen during caretaker visit 722, 2026-11-19.
"""

import math
import pytest

from iamai.stroke_thematic_coherence import (
    CoherenceReport,
    _centroid,
    _cosine_similarity,
    _term_frequency,
    _tokenise,
    analyse_coherence,
    analyse_sliding_windows,
    analyse_strokes_coherence,
)


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------

class TestTokenise:
    def test_basic(self):
        tokens = _tokenise("The quick brown fox")
        assert 'quick' in tokens
        assert 'brown' in tokens
        # 'the' is a stopword, 'fox' has 3 chars → included
        assert 'fox' in tokens
        assert 'the' not in tokens

    def test_lowercase(self):
        tokens = _tokenise("UPPER lower MiXeD")
        assert all(t == t.lower() for t in tokens)

    def test_short_words_dropped(self):
        tokens = _tokenise("an at or of xy abc")
        assert 'abc' in tokens
        # 'an', 'at', 'or', 'of', 'xy' all < 3 chars
        for w in ['xy']:
            assert w not in tokens

    def test_stopwords_removed(self):
        tokens = _tokenise("the and for but not you all can had her was")
        assert tokens == []

    def test_numbers_kept(self):
        tokens = _tokenise("commit 42 files 100")
        # '42' is only 2 chars → filtered out by length rule
        assert '42' not in tokens
        assert '100' in tokens
        assert 'commit' in tokens
        assert 'files' in tokens

    def test_punctuation_stripped(self):
        tokens = _tokenise("hello, world! foo-bar_baz")
        assert 'hello' in tokens
        assert 'world' in tokens
        assert 'foo' in tokens
        assert 'bar_baz' in tokens

    def test_empty_string(self):
        assert _tokenise("") == []

    def test_only_stopwords(self):
        assert _tokenise("the and for but") == []


# ---------------------------------------------------------------------------
# Term frequency
# ---------------------------------------------------------------------------

class TestTermFrequency:
    def test_uniform(self):
        tf = _term_frequency(['alpha', 'beta', 'gamma'])
        assert tf['alpha'] == pytest.approx(1 / 3)
        assert tf['beta'] == pytest.approx(1 / 3)

    def test_repeated(self):
        tf = _term_frequency(['alpha', 'alpha', 'beta'])
        assert tf['alpha'] == pytest.approx(2 / 3)
        assert tf['beta'] == pytest.approx(1 / 3)

    def test_empty(self):
        assert _term_frequency([]) == {}

    def test_single_token(self):
        tf = _term_frequency(['only'])
        assert tf['only'] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    def test_identical_vectors(self):
        vec = {'alpha': 0.5, 'beta': 0.3, 'gamma': 0.2}
        sim = _cosine_similarity(vec, vec)
        assert sim == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        vec_a = {'alpha': 1.0}
        vec_b = {'beta': 1.0}
        sim = _cosine_similarity(vec_a, vec_b)
        assert sim == pytest.approx(0.0)

    def test_partial_overlap(self):
        vec_a = {'alpha': 0.6, 'beta': 0.4}
        vec_b = {'alpha': 0.4, 'gamma': 0.6}
        sim = _cosine_similarity(vec_a, vec_b)
        assert 0.0 < sim < 1.0

    def test_empty_vectors(self):
        assert _cosine_similarity({}, {}) == 0.0
        assert _cosine_similarity({'alpha': 1.0}, {}) == 0.0
        assert _cosine_similarity({}, {'alpha': 1.0}) == 0.0

    def test_symmetry(self):
        vec_a = {'alpha': 0.3, 'beta': 0.7}
        vec_b = {'beta': 0.5, 'gamma': 0.5}
        assert _cosine_similarity(vec_a, vec_b) == pytest.approx(
            _cosine_similarity(vec_b, vec_a)
        )

    def test_scale_invariance(self):
        vec_a = {'alpha': 0.5, 'beta': 0.5}
        vec_b = {'alpha': 1.0, 'beta': 1.0}
        sim = _cosine_similarity(vec_a, vec_b)
        assert sim == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Centroid
# ---------------------------------------------------------------------------

class TestCentroid:
    def test_basic(self):
        vecs = [
            {'alpha': 0.6, 'beta': 0.4},
            {'alpha': 0.4, 'beta': 0.6},
        ]
        centroid = _centroid(vecs, top_k=2)
        tokens = [t for t, _ in centroid]
        assert 'alpha' in tokens
        assert 'beta' in tokens

    def test_empty(self):
        assert _centroid([], top_k=5) == []

    def test_top_k_limit(self):
        vecs = [{'a': 0.1, 'b': 0.2, 'c': 0.3, 'd': 0.4}]
        centroid = _centroid(vecs, top_k=2)
        assert len(centroid) == 2
        # Highest weight first
        assert centroid[0][0] == 'd'

    def test_averaging(self):
        vecs = [
            {'alpha': 0.8, 'beta': 0.2},
            {'alpha': 0.2, 'beta': 0.8},
        ]
        centroid = _centroid(vecs, top_k=2)
        # Both should average to 0.5
        weights = dict(centroid)
        assert weights['alpha'] == pytest.approx(0.5)
        assert weights['beta'] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# analyse_coherence
# ---------------------------------------------------------------------------

class TestAnalyseCoherence:
    def test_highly_coherent(self):
        texts = [
            "commit pipeline batching push stroke remote",
            "commit pipeline batching push stroke remote",
            "commit pipeline batching push stroke remote",
            "commit pipeline batching push stroke remote",
        ]
        report = analyse_coherence(texts)
        assert report.total_strokes == 4
        assert report.valid_strokes == 4
        assert report.mean_coherence == pytest.approx(1.0)
        assert report.classify() == 'focused'

    def test_scattered(self):
        texts = [
            "quantum entanglement describes particle correlations at distance",
            "mediterranean cuisine features olive oil garlic and fresh herbs",
            "binary search trees maintain sorted order for logarithmic lookup",
            "impressionist painters captured light effects in outdoor scenes",
        ]
        report = analyse_coherence(texts)
        assert report.mean_coherence < 0.20
        assert report.classify() == 'scattered'

    def test_moderate(self):
        texts = [
            "the git commit process stages changes before pushing",
            "mediterranean recipes use olive oil and fresh herbs",
            "commit batching groups staged changes into atomic pushes",
            "italian cooking techniques emphasise fresh seasonal ingredients",
        ]
        report = analyse_coherence(texts)
        # Some pairs coherent (git pairs, food pairs), others not
        assert 0.05 < report.mean_coherence < 0.40

    def test_single_stroke(self):
        report = analyse_coherence(["just one stroke here about commits"])
        assert report.total_strokes == 1
        assert report.mean_coherence == 0.0
        assert report.pairwise_similarities == []

    def test_empty_input(self):
        report = analyse_coherence([])
        assert report.total_strokes == 0
        assert report.valid_strokes == 0

    def test_all_empty_texts(self):
        report = analyse_coherence(["", "", ""])
        assert report.total_strokes == 3
        assert report.valid_strokes == 0
        assert report.mean_coherence == 0.0

    def test_some_empty_texts(self):
        texts = [
            "commit pipeline processes strokes",
            "",
            "batching collects strokes for pushing",
        ]
        report = analyse_coherence(texts)
        assert report.total_strokes == 3
        assert report.valid_strokes == 2
        assert len(report.pairwise_similarities) == 1

    def test_cohesion_index(self):
        texts = [
            "commit pipeline push batch stroke",
            "commit pipeline push batch stroke",
            "commit pipeline push batch stroke",
        ]
        report = analyse_coherence(texts, coherence_threshold=0.20)
        # All identical → all pairs have similarity 1.0
        assert report.cohesion_index == pytest.approx(1.0)

    def test_vocabulary_size(self):
        texts = [
            "alpha beta gamma",
            "gamma delta epsilon",
        ]
        report = analyse_coherence(texts)
        assert report.vocabulary_size == 5  # alpha, beta, gamma, delta, epsilon

    def test_thematic_centroid(self):
        texts = [
            "commit pipeline processes strokes for pushing to remote",
            "the commit pipeline batches strokes and pushes them",
            "stroke processing feeds the commit pipeline",
        ]
        report = analyse_coherence(texts, top_k=3)
        centroid_tokens = [t for t, _ in report.thematic_centroid]
        # 'commit' and 'pipeline' should be prominent
        assert 'commit' in centroid_tokens or 'pipeline' in centroid_tokens

    def test_custom_threshold(self):
        texts = [
            "commit pipeline batch push",
            "commit pipeline stage remote",
        ]
        report_low = analyse_coherence(texts, coherence_threshold=0.10)
        report_high = analyse_coherence(texts, coherence_threshold=0.90)
        # Lower threshold → higher cohesion index
        assert report_low.cohesion_index >= report_high.cohesion_index


# ---------------------------------------------------------------------------
# analyse_strokes_coherence (dict interface)
# ---------------------------------------------------------------------------

class TestAnalyseStrokesCoherence:
    def test_from_dicts(self):
        strokes = [
            {'text': 'commit pipeline processes strokes', 'kind': 'thought'},
            {'text': 'batching collects changes for pushing', 'kind': 'thought'},
            {'text': 'pipeline feeds commits into batch groups', 'kind': 'devlog'},
        ]
        report = analyse_strokes_coherence(strokes)
        assert report.total_strokes == 3
        assert report.valid_strokes == 3
        assert report.mean_coherence > 0.0

    def test_missing_text_field(self):
        strokes = [
            {'kind': 'thought'},
            {'kind': 'devlog'},
        ]
        report = analyse_strokes_coherence(strokes)
        assert report.total_strokes == 2
        assert report.valid_strokes == 0

    def test_none_text(self):
        strokes = [
            {'text': None, 'kind': 'thought'},
            {'text': 'commit pipeline batch', 'kind': 'thought'},
        ]
        report = analyse_strokes_coherence(strokes)
        assert report.total_strokes == 2
        assert report.valid_strokes == 1


# ---------------------------------------------------------------------------
# analyse_sliding_windows
# ---------------------------------------------------------------------------

class TestSlidingWindows:
    def test_basic(self):
        texts = [
            "commit pipeline batch push stroke",
            "commit pipeline process stage remote",
            "commit batch push stage pipeline",
            "quantum physics entanglement particles",
            "mediterranean cooking olive oil herbs",
            "binary search tree data structure",
        ]
        reports = analyse_sliding_windows(texts, window_size=3)
        assert len(reports) >= 2
        # First window should be more coherent (all about commits)
        # Last window should be less coherent (mixed topics)

    def test_small_input(self):
        texts = ["commit pipeline", "batch push"]
        reports = analyse_sliding_windows(texts, window_size=5)
        # Input smaller than window → single report
        assert len(reports) == 1

    def test_exact_window_size(self):
        texts = ["commit batch push"] * 5
        reports = analyse_sliding_windows(texts, window_size=5)
        assert len(reports) == 1

    def test_coherence_decline(self):
        # First half: focused, second half: scattered
        texts = (
            ["commit pipeline batch push stroke"] * 5
            + [
                "quantum physics particles",
                "mediterranean cooking herbs",
                "binary search algorithm",
                "impressionist painting light",
                "orchestral symphony movement",
            ]
        )
        reports = analyse_sliding_windows(texts, window_size=5)
        assert len(reports) >= 2
        # First window should have higher coherence than last
        assert reports[0].mean_coherence >= reports[-1].mean_coherence


# ---------------------------------------------------------------------------
# Classification thresholds
# ---------------------------------------------------------------------------

class TestClassification:
    def test_focused(self):
        report = CoherenceReport(mean_coherence=0.40, cohesion_index=0.80)
        assert report.classify() == 'focused'
        assert report.classify_cohesion() == 'aligned'

    def test_moderate(self):
        report = CoherenceReport(mean_coherence=0.25, cohesion_index=0.45)
        assert report.classify() == 'moderate'
        assert report.classify_cohesion() == 'partial'

    def test_scattered(self):
        report = CoherenceReport(mean_coherence=0.10, cohesion_index=0.15)
        assert report.classify() == 'scattered'
        assert report.classify_cohesion() == 'fragmented'

    def test_boundary_focused(self):
        report = CoherenceReport(mean_coherence=0.35)
        assert report.classify() == 'focused'

    def test_boundary_moderate(self):
        report = CoherenceReport(mean_coherence=0.15)
        assert report.classify() == 'moderate'

    def test_boundary_cohesion_aligned(self):
        report = CoherenceReport(cohesion_index=0.61)
        assert report.classify_cohesion() == 'aligned'

    def test_boundary_cohesion_fragmented(self):
        # 0.30 is not > 0.30, so it falls into 'fragmented'
        report = CoherenceReport(cohesion_index=0.30)
        assert report.classify_cohesion() == 'fragmented'
        # Just above the boundary → partial
        report2 = CoherenceReport(cohesion_index=0.31)
        assert report2.classify_cohesion() == 'partial'


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------

class TestToDict:
    def test_serialisation(self):
        report = CoherenceReport(
            total_strokes=5,
            valid_strokes=4,
            pairwise_similarities=[0.3, 0.5, 0.2],
            mean_coherence=0.33333,
            median_coherence=0.3,
            min_coherence=0.2,
            cohesion_index=0.6667,
            thematic_centroid=[('commit', 0.45), ('pipeline', 0.30)],
            vocabulary_size=15,
        )
        d = report.to_dict()
        assert d['total_strokes'] == 5
        assert d['valid_strokes'] == 4
        assert d['mean_coherence'] == pytest.approx(0.3333, abs=0.001)
        assert d['num_pairs'] == 3
        assert len(d['thematic_centroid']) == 2

    def test_empty_serialisation(self):
        report = CoherenceReport()
        d = report.to_dict()
        assert d['total_strokes'] == 0
        assert d['thematic_centroid'] == []
        assert d['num_pairs'] == 0


# ---------------------------------------------------------------------------
# Mathematical properties
# ---------------------------------------------------------------------------

class TestMathProperties:
    def test_similarity_bounded(self):
        """All pairwise similarities must be in [0, 1]."""
        texts = [
            "alpha beta gamma delta",
            "epsilon zeta eta theta",
            "alpha epsilon iota kappa",
            "lambda mu nu xi",
        ]
        report = analyse_coherence(texts)
        for sim in report.pairwise_similarities:
            assert 0.0 <= sim <= 1.0

    def test_pair_count(self):
        """n valid strokes should produce n*(n-1)/2 pairs."""
        texts = [f"topic_{i} unique content here" for i in range(6)]
        report = analyse_coherence(texts)
        expected_pairs = 6 * 5 // 2  # 15
        assert len(report.pairwise_similarities) == expected_pairs

    def test_mean_geq_min(self):
        texts = [
            "commit pipeline batch",
            "commit push remote",
            "batch stage commit",
        ]
        report = analyse_coherence(texts)
        assert report.mean_coherence >= report.min_coherence

    def test_identical_texts_perfect_coherence(self):
        texts = ["commit pipeline batch push stroke"] * 5
        report = analyse_coherence(texts)
        assert report.mean_coherence == pytest.approx(1.0)
        assert report.cohesion_index == pytest.approx(1.0)
