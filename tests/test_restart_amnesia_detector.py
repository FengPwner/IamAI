"""Tests for iamai.restart_amnesia_detector.

Covers:
  - tokeniser
  - vocabulary_overlap (edge cases, full overlap, no overlap, partial)
  - topic_drift (identical, orthogonal, empty input, single token)
  - cadence_similarity (identical CV, different CV, too few intervals)
  - AmnesiaDetector.check_from_tokens (amnesia / fresh / borderline)
  - AmnesiaDetector.check (raw strokes + timestamps)
  - AmnesiaVerdict.summary formatting
  - AmnesiaSignals.as_dict rounding
  - weight customisation and threshold customisation
  - edge cases (empty input, single token, zero weights)

Written by Qwen during caretaker visit 705, 2026-11-18.
"""

import math
import pytest

from iamai.restart_amnesia_detector import (
    AmnesiaDetector,
    AmnesiaSignals,
    AmnesiaVerdict,
    cadence_similarity,
    topic_drift,
    vocabulary_overlap,
    _tokenise,
)


# ─── Tokeniser ──────────────────────────────────────────────────────


class TestTokenise:
    def test_basic_english(self):
        assert _tokenise("Hello, world!") == ["hello", "world"]

    def test_chinese(self):
        tokens = _tokenise("你好世界 123")
        assert "你好世界" in tokens
        assert "123" in tokens

    def test_mixed(self):
        tokens = _tokenise("stroke-42 added to devlog.md")
        assert "stroke" in tokens
        assert "42" in tokens
        assert "added" in tokens
        assert "to" in tokens
        assert "devlog" in tokens
        assert "md" in tokens

    def test_empty(self):
        assert _tokenise("") == []

    def test_punctuation_only(self):
        assert _tokenise("!@#$%^&*()") == []


# ─── vocabulary_overlap ─────────────────────────────────────────────


class TestVocabularyOverlap:
    def test_full_overlap(self):
        tokens = ["alpha", "beta", "gamma"]
        assert vocabulary_overlap(tokens, tokens) == 1.0

    def test_no_overlap(self):
        pre = ["alpha", "beta"]
        post = ["gamma", "delta"]
        assert vocabulary_overlap(pre, post) == 0.0

    def test_partial_overlap(self):
        pre = ["a", "b", "c", "d"]
        post = ["c", "d", "e", "f"]
        # 2 of 4 post tokens in pre → 0.5
        assert vocabulary_overlap(pre, post) == 0.5

    def test_empty_post(self):
        assert vocabulary_overlap(["a", "b"], []) == 0.0

    def test_empty_pre(self):
        assert vocabulary_overlap([], ["a", "b"]) == 0.0

    def test_both_empty(self):
        assert vocabulary_overlap([], []) == 0.0

    def test_duplicate_post_tokens(self):
        pre = ["a", "b"]
        post = ["a", "a", "b", "b"]
        # unique post = {a, b}, both in pre → 1.0
        assert vocabulary_overlap(pre, post) == 1.0


# ─── topic_drift ────────────────────────────────────────────────────


class TestTopicDrift:
    def test_identical_distributions(self):
        tokens = ["alpha", "beta", "gamma", "alpha", "beta"]
        assert topic_drift(tokens, tokens) == pytest.approx(0.0, abs=1e-6)

    def test_orthogonal(self):
        pre = ["alpha"] * 10
        post = ["beta"] * 10
        assert topic_drift(pre, post) == pytest.approx(1.0, abs=1e-6)

    def test_partial_drift(self):
        pre = ["alpha"] * 5 + ["beta"] * 5
        post = ["alpha"] * 8 + ["gamma"] * 2
        drift = topic_drift(pre, post)
        assert 0.0 < drift < 1.0

    def test_empty_pre(self):
        assert topic_drift([], ["a", "b"]) == 0.0

    def test_empty_post(self):
        assert topic_drift(["a", "b"], []) == 0.0

    def test_both_empty(self):
        assert topic_drift([], []) == 0.0

    def test_single_token_each(self):
        # Same token → 0.0 drift
        assert topic_drift(["x"], ["x"]) == pytest.approx(0.0, abs=1e-6)
        # Different tokens → 1.0 drift
        assert topic_drift(["x"], ["y"]) == pytest.approx(1.0, abs=1e-6)


# ─── cadence_similarity ─────────────────────────────────────────────


class TestCadenceSimilarity:
    def test_identical_intervals(self):
        intervals = [15.0, 15.0, 15.0, 15.0]
        assert cadence_similarity(intervals, intervals) == pytest.approx(1.0)

    def test_different_cadence(self):
        # pre: very regular (CV near 0), post: very irregular (high CV)
        pre = [15.0] * 10
        post = [1.0, 100.0, 2.0, 80.0, 3.0, 90.0]
        sim = cadence_similarity(pre, post)
        assert sim < 0.3

    def test_similar_cadence_different_mean(self):
        # Same CV but different means
        pre = [10.0, 20.0, 10.0, 20.0]  # CV = 0.333...
        post = [20.0, 40.0, 20.0, 40.0]  # CV = 0.333...
        sim = cadence_similarity(pre, post)
        assert sim == pytest.approx(1.0, abs=1e-6)

    def test_too_few_pre(self):
        assert cadence_similarity([15.0], [15.0, 16.0]) == 0.0

    def test_too_few_post(self):
        assert cadence_similarity([15.0, 16.0], [15.0]) == 0.0

    def test_both_too_few(self):
        assert cadence_similarity([], []) == 0.0

    def test_constant_intervals(self):
        # Both perfectly constant but different values
        pre = [10.0, 10.0, 10.0]
        post = [20.0, 20.0, 20.0]
        # CV_pre = 0, CV_post = 0 → similarity = 1.0
        assert cadence_similarity(pre, post) == 1.0


# ─── AmnesiaDetector ────────────────────────────────────────────────


class TestAmnesiaDetector:
    def test_amnesia_detected(self):
        """High overlap + low drift + similar cadence → amnesia."""
        det = AmnesiaDetector()
        pre = ["the", "writer", "continues", "writing", "strokes"] * 10
        post = ["the", "writer", "continues", "writing", "strokes"] * 10
        intervals = [15.0] * 9

        verdict = det.check_from_tokens(pre, post, intervals, intervals)
        assert verdict.has_amnesia is True
        assert verdict.score >= 0.70

    def test_fresh_after_restart(self):
        """Low overlap + high drift → clearly fresh."""
        det = AmnesiaDetector()
        pre = ["alpha", "beta", "gamma"] * 5
        post = ["delta", "epsilon", "zeta", "eta", "theta"] * 5
        verdict = det.check_from_tokens(pre, post)
        assert verdict.has_amnesia is False
        assert verdict.score < 0.70

    def test_borderline_below_threshold(self):
        """Partial overlap, some drift → below threshold."""
        det = AmnesiaDetector()
        pre = ["alpha", "beta", "gamma", "delta"] * 5
        post = ["gamma", "delta", "epsilon", "zeta"] * 5
        verdict = det.check_from_tokens(pre, post)
        # overlap is 0.5, drift is moderate → should be below 0.70
        assert verdict.has_amnesia is False

    def test_check_with_raw_strokes(self):
        det = AmnesiaDetector()
        pre_strokes = [
            "the writer produces another stroke about cadence monitoring",
            "cadence drift is a subtle signal that accumulates over time",
            "monitoring the rhythm of commits reveals process health",
        ]
        post_strokes = [
            "exploring the topology of ideas requires fresh perspective",
            "new directions emerge when we step away from old patterns",
            "the restart provides an opportunity for creative renewal",
        ]
        pre_ts = [1000.0, 1015.0, 1030.0]
        post_ts = [2000.0, 2015.0, 2030.0]
        verdict = det.check(pre_strokes, post_strokes, pre_ts, post_ts)
        assert isinstance(verdict, AmnesiaVerdict)
        assert 0.0 <= verdict.score <= 1.0

    def test_check_without_timestamps(self):
        det = AmnesiaDetector()
        pre = ["hello world alpha beta"]
        post = ["gamma delta epsilon zeta"]
        verdict = det.check(pre, post)
        assert isinstance(verdict, AmnesiaVerdict)

    def test_empty_strokes(self):
        det = AmnesiaDetector()
        verdict = det.check([], [])
        assert verdict.score == 0.0
        assert verdict.has_amnesia is False

    def test_custom_threshold(self):
        det = AmnesiaDetector(threshold=0.30)
        pre = ["a", "b", "c"] * 5
        post = ["a", "b", "c"] * 5
        verdict = det.check_from_tokens(pre, post)
        # With low threshold, even moderate overlap triggers amnesia
        assert verdict.has_amnesia is True

    def test_custom_weights(self):
        det = AmnesiaDetector(
            overlap_weight=1.0,
            drift_weight=0.0,
            cadence_weight=0.0,
        )
        pre = ["x", "y"]
        post = ["x", "y"]
        verdict = det.check_from_tokens(pre, post)
        # Only overlap matters → score = 1.0
        assert verdict.score == pytest.approx(1.0)

    def test_zero_weights(self):
        det = AmnesiaDetector(
            overlap_weight=0.0,
            drift_weight=0.0,
            cadence_weight=0.0,
        )
        verdict = det.check_from_tokens(["a"], ["a"])
        assert verdict.score == 0.0

    def test_score_clamped_to_unit(self):
        det = AmnesiaDetector()
        # Feed inputs designed to maximise all three signals
        tokens = ["z"] * 20
        intervals = [15.0] * 19
        verdict = det.check_from_tokens(tokens, tokens, intervals, intervals)
        assert 0.0 <= verdict.score <= 1.0


# ─── AmnesiaVerdict ─────────────────────────────────────────────────


class TestAmnesiaVerdict:
    def test_summary_amnesia(self):
        v = AmnesiaVerdict(score=0.85, has_amnesia=True)
        assert v.summary() == "AMNESIA (score=0.850)"

    def test_summary_fresh(self):
        v = AmnesiaVerdict(score=0.23, has_amnesia=False)
        assert v.summary() == "fresh (score=0.230)"

    def test_default_values(self):
        v = AmnesiaVerdict()
        assert v.score == 0.0
        assert v.has_amnesia is False


# ─── AmnesiaSignals ─────────────────────────────────────────────────


class TestAmnesiaSignals:
    def test_as_dict(self):
        s = AmnesiaSignals(
            vocabulary_overlap=0.81234,
            topic_drift=0.15678,
            cadence_similarity=0.99123,
        )
        d = s.as_dict()
        assert d["vocabulary_overlap"] == 0.8123
        assert d["topic_drift"] == 0.1568
        assert d["cadence_similarity"] == 0.9912

    def test_as_dict_defaults(self):
        s = AmnesiaSignals()
        d = s.as_dict()
        assert d == {
            "vocabulary_overlap": 0.0,
            "topic_drift": 0.0,
            "cadence_similarity": 0.0,
        }


# ─── Integration ────────────────────────────────────────────────────


class TestIntegration:
    def test_realistic_amnesia_scenario(self):
        """Simulate pre/post restart strokes that look amnesiac."""
        det = AmnesiaDetector()

        # Pre-restart: writer was discussing process monitoring
        pre_strokes = [
            "the cadence monitor tracks inter-stroke intervals and flags drift",
            "when the writer stalls the gap exceeds twice the expected cadence",
            "commit batch collects strokes and writes them every ten minutes",
            "process liveness is checked by reading the pid file and sending signal zero",
            "the push coordinator handles divergence with rebase and retry logic",
        ]

        # Post-restart: writer continues same topic (suspicious!)
        post_strokes = [
            "the cadence monitor tracks inter-stroke intervals and flags anomalies",
            "when the writer stalls the gap exceeds twice the normal cadence",
            "commit batch collects strokes and persists them every ten minutes",
            "process liveness is checked by reading the pid and sending zero signal",
            "the push coordinator handles divergence with rebase and retry patterns",
        ]

        pre_ts = [1000.0 + 15 * i for i in range(5)]
        post_ts = [2000.0 + 15 * i for i in range(5)]

        verdict = det.check(pre_strokes, post_strokes, pre_ts, post_ts)
        # Should detect amnesia: high overlap, low drift, similar cadence
        assert verdict.has_amnesia is True
        assert verdict.signals.vocabulary_overlap > 0.7
        assert verdict.signals.topic_drift < 0.15

    def test_realistic_fresh_scenario(self):
        """Simulate pre/post restart strokes that are clearly different."""
        det = AmnesiaDetector()

        pre_strokes = [
            "monitoring the commit rhythm reveals process health over time",
            "the batch committer aggregates strokes into periodic snapshots",
            "git push divergence occurs when remote advances before local push",
        ]

        post_strokes = [
            "exploring neural architectures for sequence prediction tasks",
            "transformer attention mechanisms capture long-range dependencies efficiently",
            "gradient descent optimisation converges faster with adaptive learning rates",
        ]

        pre_ts = [1000.0, 1015.0, 1030.0]
        post_ts = [2000.0, 2015.0, 2030.0]

        verdict = det.check(pre_strokes, post_strokes, pre_ts, post_ts)
        assert verdict.has_amnesia is False
        assert verdict.signals.vocabulary_overlap < 0.4
