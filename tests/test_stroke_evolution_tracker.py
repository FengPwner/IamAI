"""Tests for iamai/stroke_evolution_tracker.py — stream evolution analysis.

Run:  python3 -m pytest tests/test_stroke_evolution_tracker.py -v

Written by Qwen during caretaker visit 729, 2026-11-19.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.stroke_evolution_tracker import (  # noqa: E402
    EvolutionReport,
    WindowMetrics,
    _classify_regime,
    _linear_slope,
    analyse_evolution,
    analyse_evolution_windows,
    compute_callback_density,
    compute_topic_similarity,
    compute_window_depth,
    count_sentences,
    extract_content_words,
    has_cross_reference,
)


# ---------------------------------------------------------------------------
# extract_content_words
# ---------------------------------------------------------------------------


class TestExtractContentWords:
    def test_basic_extraction(self):
        words = extract_content_words("the algorithm processes data efficiently")
        assert "algorithm" in words
        assert "processes" in words
        assert "efficiently" in words

    def test_filters_short_words(self):
        words = extract_content_words("a an to of in on at by or is")
        assert words == []

    def test_filters_stopwords(self):
        words = extract_content_words("this that these those about above")
        assert words == []

    def test_case_insensitive(self):
        words = extract_content_words("ALGORITHM Data Processing")
        assert "algorithm" in words
        assert "data" in words
        assert "processing" in words

    def test_empty_string(self):
        assert extract_content_words("") == []

    def test_numbers_ignored(self):
        words = extract_content_words("test 12345 hello world")
        assert "test" in words
        assert "hello" in words
        assert "world" in words

    def test_punctuation_handling(self):
        words = extract_content_words("algorithm, data; processing. analysis!")
        assert "algorithm" in words
        assert "data" in words
        assert "processing" in words
        assert "analysis" in words


# ---------------------------------------------------------------------------
# count_sentences
# ---------------------------------------------------------------------------


class TestCountSentences:
    def test_basic_sentences(self):
        assert count_sentences("Hello world. How are you? I am fine!") == 3

    def test_single_sentence(self):
        assert count_sentences("Just one sentence here.") == 1

    def test_no_punctuation(self):
        assert count_sentences("no punctuation at all") == 1

    def test_empty_string(self):
        assert count_sentences("") == 0

    def test_multiple_dots(self):
        assert count_sentences("Wait... Really?! Yes.") == 3

    def test_question_and_exclamation(self):
        assert count_sentences("What? Really! Yes.") == 3


# ---------------------------------------------------------------------------
# has_cross_reference
# ---------------------------------------------------------------------------


class TestHasCrossReference:
    def test_detects_see(self):
        assert has_cross_reference("see the previous analysis for details")

    def test_detects_previously(self):
        assert has_cross_reference("previously we established that")

    def test_detects_extends(self):
        assert has_cross_reference("this module extends the work")

    def test_detects_builds(self):
        assert has_cross_reference("this builds on earlier research")

    def test_no_cross_reference(self):
        assert not has_cross_reference("just a simple statement of fact")

    def test_case_insensitive(self):
        assert has_cross_reference("Previously we discussed this topic")

    def test_empty_string(self):
        assert not has_cross_reference("")


# ---------------------------------------------------------------------------
# _linear_slope
# ---------------------------------------------------------------------------


class TestLinearSlope:
    def test_positive_slope(self):
        slope = _linear_slope([1.0, 2.0, 3.0, 4.0, 5.0])
        assert slope > 0

    def test_negative_slope(self):
        slope = _linear_slope([5.0, 4.0, 3.0, 2.0, 1.0])
        assert slope < 0

    def test_flat_slope(self):
        slope = _linear_slope([3.0, 3.0, 3.0, 3.0])
        assert abs(slope) < 1e-10

    def test_single_value(self):
        assert _linear_slope([5.0]) == 0.0

    def test_empty(self):
        assert _linear_slope([]) == 0.0

    def test_two_values(self):
        slope = _linear_slope([2.0, 4.0])
        assert abs(slope - 2.0) < 1e-10

    def test_known_slope(self):
        # y = 2x + 1 for x = 0..4 → [1, 3, 5, 7, 9]
        slope = _linear_slope([1.0, 3.0, 5.0, 7.0, 9.0])
        assert abs(slope - 2.0) < 1e-10


# ---------------------------------------------------------------------------
# compute_window_depth
# ---------------------------------------------------------------------------


class TestComputeWindowDepth:
    def test_empty_window(self):
        depth, unique, sent, cref = compute_window_depth([])
        assert depth == 0.0
        assert unique == 0
        assert sent == 0.0
        assert cref == 0.0

    def test_rich_strokes(self):
        strokes = [
            "The algorithm efficiently processes large datasets using parallel computation techniques.",
            "Previously established methods require significantly more computational resources.",
            "This approach extends traditional boundaries of distributed computing architecture.",
        ]
        depth, unique, sent, cref = compute_window_depth(strokes)
        assert depth > 0
        assert unique > 10
        assert sent >= 1.0  # mean sentences per stroke ≥ 1
        assert cref > 0  # "previously" and "extends" are cross-refs

    def test_sparse_strokes(self):
        strokes = ["ok", "yes", "no"]
        depth, unique, sent, cref = compute_window_depth(strokes)
        assert depth < 0.1  # very low — no content words
        assert unique == 0
        assert cref == 0.0

    def test_depth_increases_with_richness(self):
        simple = ["the cat sat on the mat. it was a good cat."]
        rich = [
            "The sophisticated algorithm implements advanced parallel processing "
            "techniques previously established in distributed computing research. "
            "This extends conventional boundaries significantly."
        ]
        d_simple, _, _, _ = compute_window_depth(simple)
        d_rich, _, _, _ = compute_window_depth(rich)
        assert d_rich > d_simple


# ---------------------------------------------------------------------------
# compute_topic_similarity
# ---------------------------------------------------------------------------


class TestComputeTopicSimilarity:
    def test_identical_sets(self):
        words = ["algorithm", "data", "processing"]
        assert compute_topic_similarity(words, words) == 1.0

    def test_disjoint_sets(self):
        assert compute_topic_similarity(
            ["algorithm", "data"], ["music", "dance"]
        ) == 0.0

    def test_partial_overlap(self):
        sim = compute_topic_similarity(
            ["algorithm", "data", "processing"],
            ["algorithm", "data", "analysis"],
        )
        # intersection = {algorithm, data}, union = {algorithm, data, processing, analysis}
        assert abs(sim - 2.0 / 4.0) < 1e-10

    def test_empty_input(self):
        assert compute_topic_similarity([], []) == 0.0
        assert compute_topic_similarity(["word"], []) == 0.0
        assert compute_topic_similarity([], ["word"]) == 0.0


# ---------------------------------------------------------------------------
# compute_callback_density
# ---------------------------------------------------------------------------


class TestComputeCallbackDensity:
    def test_no_prior_vocab(self):
        assert compute_callback_density(["algorithm processing data"], set()) == 0.0

    def test_all_callbacks(self):
        prior = {"algorithm", "processing", "data"}
        strokes = [
            "the algorithm runs fast",
            "processing data efficiently",
        ]
        density = compute_callback_density(strokes, prior)
        assert density == 1.0

    def test_no_callbacks(self):
        prior = {"music", "dance", "rhythm"}
        strokes = [
            "the algorithm runs fast",
            "processing data efficiently",
        ]
        density = compute_callback_density(strokes, prior)
        assert density == 0.0

    def test_partial_callbacks(self):
        prior = {"algorithm"}
        strokes = [
            "the algorithm runs fast",
            "nothing related here today",
        ]
        density = compute_callback_density(strokes, prior)
        assert abs(density - 0.5) < 1e-10

    def test_empty_strokes(self):
        assert compute_callback_density([], {"word"}) == 0.0


# ---------------------------------------------------------------------------
# _classify_regime
# ---------------------------------------------------------------------------


class TestClassifyRegime:
    def test_deepening(self):
        regime = _classify_regime(
            depth_slope=0.02, mean_drift=0.3, mean_callback=0.2
        )
        assert regime == "deepening"

    def test_spiraling_with_callbacks(self):
        regime = _classify_regime(
            depth_slope=0.02, mean_drift=0.8, mean_callback=0.5
        )
        assert regime == "spiraling"

    def test_spiraling_without_callbacks(self):
        regime = _classify_regime(
            depth_slope=0.02, mean_drift=0.8, mean_callback=0.1
        )
        assert regime == "spiraling"

    def test_wandering(self):
        regime = _classify_regime(
            depth_slope=-0.01, mean_drift=0.8, mean_callback=0.2
        )
        assert regime == "wandering"

    def test_stagnating(self):
        regime = _classify_regime(
            depth_slope=-0.01, mean_drift=0.3, mean_callback=0.1
        )
        assert regime == "stagnating"

    def test_boundary_deepening(self):
        regime = _classify_regime(
            depth_slope=0.006, mean_drift=0.5, mean_callback=0.2
        )
        assert regime == "deepening"

    def test_boundary_stagnating(self):
        regime = _classify_regime(
            depth_slope=0.004, mean_drift=0.5, mean_callback=0.2
        )
        assert regime == "stagnating"


# ---------------------------------------------------------------------------
# analyse_evolution — integration
# ---------------------------------------------------------------------------


class TestAnalyseEvolution:
    def test_empty_input(self):
        report = analyse_evolution([])
        assert report.total_strokes == 0
        assert report.regime == "stagnating"
        assert report.window_count == 0
        assert "no strokes" in report.summary()

    def test_single_stroke(self):
        report = analyse_evolution(["just one stroke about algorithms"])
        assert report.total_strokes == 1
        assert report.window_count == 1
        assert report.depth_slope == 0.0  # can't compute slope with 1 point

    def test_small_batch(self):
        strokes = [
            f"stroke number {i} discusses algorithm processing data"
            for i in range(5)
        ]
        report = analyse_evolution(strokes, window_size=3)
        assert report.total_strokes == 5
        assert report.window_count == 2

    def test_deepening_stream(self):
        """Build a stream that gets progressively deeper."""
        base = "simple text about cats"
        rich_template = (
            "The sophisticated analysis extends previously established "
            "frameworks with increasingly complex computational methodologies "
            "that build upon earlier discoveries in distributed systems."
        )
        # start simple, end rich
        strokes = []
        for i in range(30):
            if i < 10:
                strokes.append(f"basic observation number {i} about simple things")
            elif i < 20:
                strokes.append(
                    f"deeper analysis {i} regarding algorithmic processing "
                    f"techniques with detailed examination"
                )
            else:
                strokes.append(f"{rich_template} iteration {i}")
        report = analyse_evolution(strokes, window_size=10)
        assert report.total_strokes == 30
        assert report.window_count == 3
        assert report.depth_slope > 0

    def test_wandering_stream(self):
        """Topics shift constantly without deepening."""
        # Each window of 5 gets a completely different single-topic vocabulary
        # so consecutive windows have near-zero Jaccard similarity.
        topic_blocks = [
            ["music rhythm melody harmony tempo beat song chord"] * 5,
            ["cooking recipe ingredient flavor spice kitchen oven"] * 5,
            ["ocean marine coral reef tide current nautical"] * 5,
            ["mountain summit alpine granite elevation climbing"] * 5,
            ["painting canvas brush palette pigment watercolor"] * 5,
            ["garden blossom harvest compost perennial botany"] * 5,
        ]
        strokes = []
        for block in topic_blocks:
            strokes.extend(block)
        report = analyse_evolution(strokes, window_size=5)
        assert report.total_strokes == 30
        # consecutive windows have completely different topics
        assert report.mean_drift > 0.5

    def test_stagnating_stream(self):
        """Same content repeated."""
        strokes = [
            "the algorithm processes data using standard methods"
        ] * 30
        report = analyse_evolution(strokes, window_size=10)
        assert report.regime == "stagnating"
        assert report.mean_drift == 0.0  # identical windows

    def test_custom_window_size(self):
        strokes = [f"stroke {i} about algorithms" for i in range(25)]
        report = analyse_evolution(strokes, window_size=5)
        assert report.window_count == 5
        assert report.window_size == 5

    def test_summary_format(self):
        strokes = [f"stroke {i} about algorithms and data" for i in range(20)]
        report = analyse_evolution(strokes, window_size=10)
        s = report.summary()
        assert "windows" in s
        assert "strokes" in s
        assert "depth_slope" in s
        assert "drift" in s

    def test_window_metrics_populated(self):
        strokes = [f"stroke {i} about algorithms" for i in range(20)]
        report = analyse_evolution(strokes, window_size=10)
        assert len(report.windows) == 2
        assert report.windows[0].window_index == 0
        assert report.windows[1].window_index == 1
        assert report.windows[0].stroke_range == (0, 10)
        assert report.windows[1].stroke_range == (10, 20)

    def test_callback_density_builds_over_time(self):
        """Later windows should have callback potential from earlier vocab."""
        strokes = []
        shared_words = "algorithm processing distributed computation framework"
        for i in range(40):
            if i < 10:
                strokes.append(
                    f"introducing the {shared_words} concepts in iteration {i}"
                )
            elif i < 20:
                strokes.append(f"completely different topic about gardening {i}")
            else:
                strokes.append(
                    f"revisiting the {shared_words} with deeper analysis {i}"
                )
        report = analyse_evolution(strokes, window_size=10)
        # The third window should have higher callback density
        assert len(report.callback_densities) == 4
        assert report.callback_densities[2] > report.callback_densities[1]

    def test_drift_velocities_count(self):
        strokes = [f"stroke {i}" for i in range(30)]
        report = analyse_evolution(strokes, window_size=10)
        # drift computed between consecutive windows: n-1 values
        assert len(report.drift_velocities) == report.window_count - 1

    def test_partial_last_window(self):
        strokes = [f"stroke {i} about data" for i in range(15)]
        report = analyse_evolution(strokes, window_size=10)
        assert report.window_count == 2
        assert report.windows[1].stroke_range == (10, 15)


# ---------------------------------------------------------------------------
# analyse_evolution_windows — convenience
# ---------------------------------------------------------------------------


class TestAnalyseEvolutionWindows:
    def test_returns_list(self):
        strokes = [f"stroke {i} about algorithms" for i in range(20)]
        windows = analyse_evolution_windows(strokes, window_size=10)
        assert len(windows) == 2
        assert all(isinstance(w, WindowMetrics) for w in windows)

    def test_empty(self):
        assert analyse_evolution_windows([]) == []


# ---------------------------------------------------------------------------
# dataclass sanity checks
# ---------------------------------------------------------------------------


class TestDataClasses:
    def test_evolution_report_defaults(self):
        r = EvolutionReport()
        assert r.total_strokes == 0
        assert r.regime == "stagnating"
        assert r.depth_scores == []

    def test_window_metrics_defaults(self):
        wm = WindowMetrics(window_index=0, stroke_range=(0, 10))
        assert wm.depth_score == 0.0
        assert wm.unique_words == 0
        assert wm.callback_density == 0.0
