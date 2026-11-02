"""Tests for iamai.stroke_vitality — composite health score.

Covers:
    - Individual dimension scorers (rate, novelty, kind_balance, coherence)
    - Composite VitalityReport assembly
    - Edge cases (empty input, single stroke, malformed data)
    - CLI tool (tools/stroke_vitality.py) integration
    - Formatting and serialization
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_vitality import (
    ALL_KINDS,
    DEFAULT_NOVELTY_WINDOW,
    DEFAULT_TARGET_RATE,
    VERDICT_THRESHOLDS,
    WEIGHTS,
    VitalityReport,
    VitalityScorer,
    _infer_rate,
    _score_coherence,
    _score_kind_balance,
    _score_novelty,
    _score_rate,
    _tokenise,
    format_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_strokes(
    texts: list[str],
    kinds: list[str] | None = None,
    base_hour: int = 10,
) -> list[dict]:
    """Build minimal stroke dicts with text, kind, and sequential timestamps."""
    if kinds is None:
        kinds = ["thought"] * len(texts)
    return [
        {
            "seq": i + 1,
            "at": f"2026-11-02T{base_hour + i // 10:02d}:{(i % 10) * 6:02d}:00+00:00",
            "kind": kinds[i % len(kinds)],
            "text": texts[i],
        }
        for i in range(len(texts))
    ]


# ===========================================================================
# _tokenise
# ===========================================================================


class TestTokenise:
    def test_basic(self):
        assert _tokenise("Hello World") == {"hello", "world"}

    def test_punctuation_stripped(self):
        assert _tokenise("a repo, that only accumulates!") == {
            "a",
            "repo",
            "that",
            "only",
            "accumulates",
        }

    def test_numbers_included(self):
        assert _tokenise("commit 42") == {"commit", "42"}

    def test_empty_string(self):
        assert _tokenise("") == set()

    def test_stopwords_stripped(self):
        tokens = _tokenise("the quick brown fox", strip_stopwords=True)
        assert "the" not in tokens
        assert "quick" in tokens
        assert "brown" in tokens

    def test_stopwords_kept_by_default(self):
        tokens = _tokenise("the quick brown fox")
        assert "the" in tokens


# ===========================================================================
# _score_rate
# ===========================================================================


class TestScoreRate:
    def test_at_target(self):
        assert _score_rate(300.0, 300.0) == 1.0

    def test_above_target(self):
        assert _score_rate(600.0, 300.0) == 1.0

    def test_half_target(self):
        score = _score_rate(150.0, 300.0)
        assert 0.45 <= score <= 0.55

    def test_zero_rate(self):
        assert _score_rate(0.0, 300.0) == 0.0

    def test_zero_target(self):
        assert _score_rate(100.0, 0.0) == 1.0

    def test_both_zero(self):
        assert _score_rate(0.0, 0.0) == 0.5

    def test_small_rate(self):
        score = _score_rate(30.0, 300.0)
        assert score == pytest.approx(0.1)

    def test_negative_rate(self):
        assert _score_rate(-10.0, 300.0) == 0.0


# ===========================================================================
# _score_novelty
# ===========================================================================


class TestScoreNovelty:
    def test_all_identical(self):
        strokes = _make_strokes(["hello world"] * 5)
        score = _score_novelty(strokes, window=3)
        assert score < 0.1  # almost pure repetition

    def test_all_unique(self):
        strokes = _make_strokes(
            [
                "alpha beta gamma",
                "delta epsilon zeta",
                "eta theta iota",
                "kappa lambda mu",
                "nu xi omicron",
            ]
        )
        score = _score_novelty(strokes, window=2)
        assert score > 0.8

    def test_single_stroke(self):
        strokes = _make_strokes(["hello world"])
        score = _score_novelty(strokes, window=3)
        assert score == 0.5  # insufficient data

    def test_empty_strokes(self):
        score = _score_novelty([], window=3)
        assert score == 0.5

    def test_empty_text(self):
        strokes = _make_strokes(["", "", "hello world", ""])
        # Empty texts get 0.0 novelty, non-empty may have some overlap
        score = _score_novelty(strokes, window=2)
        assert isinstance(score, float)

    def test_window_size_effect(self):
        strokes = _make_strokes(
            [
                "alpha beta",
                "gamma delta",
                "epsilon zeta",
                "alpha beta",  # repeats first
                "gamma delta",  # repeats second
            ]
        )
        score_small = _score_novelty(strokes, window=1)
        score_large = _score_novelty(strokes, window=4)
        # Larger window captures more history, so repetitions are caught
        assert score_small >= score_large or abs(score_small - score_large) < 0.3

    def test_partial_overlap(self):
        strokes = _make_strokes(
            [
                "the garden grows slowly",
                "slow growth means deep roots",
                "roots anchor the plant",
            ]
        )
        score = _score_novelty(strokes, window=2)
        assert 0.0 < score < 1.0


# ===========================================================================
# _score_kind_balance
# ===========================================================================


class TestScoreKindBalance:
    def test_uniform_distribution(self):
        kinds = ["devlog", "garden", "snippet", "note"] * 10
        strokes = _make_strokes(["x"] * 40, kinds=kinds)
        score = _score_kind_balance(strokes)
        assert score > 0.95

    def test_single_kind(self):
        strokes = _make_strokes(["x"] * 20, kinds=["thought"])
        score = _score_kind_balance(strokes)
        assert score == 0.0

    def test_two_kinds_balanced(self):
        kinds = ["note", "devlog"] * 10
        strokes = _make_strokes(["x"] * 20, kinds=kinds)
        score = _score_kind_balance(strokes)
        assert score > 0.9  # log2(2)=1, so max entropy = 1 bit

    def test_skewed_distribution(self):
        kinds = ["thought"] * 95 + ["note"] * 5
        strokes = _make_strokes(["x"] * 100, kinds=kinds)
        score = _score_kind_balance(strokes)
        assert score < 0.5

    def test_empty_strokes(self):
        score = _score_kind_balance([])
        assert score == 0.5

    def test_many_kinds_uniform(self):
        kinds = ALL_KINDS * 5  # all 8 kinds, 5 each
        strokes = _make_strokes(["x"] * 40, kinds=kinds)
        score = _score_kind_balance(strokes)
        assert score > 0.95

    def test_missing_kind_defaults_to_thought(self):
        strokes = [{"text": "hello"}, {"text": "world"}, {"text": "foo"}]
        score = _score_kind_balance(strokes)
        assert score == 0.0  # all default to "thought"


# ===========================================================================
# _score_coherence
# ===========================================================================


class TestScoreCoherence:
    def test_high_coherence(self):
        strokes = _make_strokes(
            [
                "the garden grows slowly in spring",
                "spring brings rain to the garden",
                "rain helps the garden grow",
            ]
        )
        score = _score_coherence(strokes)
        assert score > 0.3

    def test_low_coherence(self):
        strokes = _make_strokes(
            [
                "quantum entanglement spooky action",
                "medieval castle architecture gothic",
                "photosynthesis chlorophyll sunlight",
            ]
        )
        score = _score_coherence(strokes)
        assert score < 0.3

    def test_single_stroke(self):
        strokes = _make_strokes(["hello world"])
        score = _score_coherence(strokes)
        assert score == 0.5  # insufficient data

    def test_empty_strokes(self):
        score = _score_coherence([])
        assert score == 0.5

    def test_identical_strokes(self):
        strokes = _make_strokes(["same exact text"] * 5)
        score = _score_coherence(strokes)
        assert score > 0.9

    def test_capped_at_one(self):
        # Even with extremely high overlap, score shouldn't exceed 1.0
        strokes = _make_strokes(["a b c d e f g"] * 10)
        score = _score_coherence(strokes)
        assert score <= 1.0


# ===========================================================================
# _infer_rate
# ===========================================================================


class TestInferRate:
    def test_basic_rate(self):
        strokes = [
            {"at": "2026-11-02T10:00:00+00:00"},
            {"at": "2026-11-02T11:00:00+00:00"},
        ]
        rate = _infer_rate(strokes)
        assert rate is not None
        assert rate == pytest.approx(2.0)  # 2 strokes in 1 hour

    def test_no_timestamps(self):
        strokes = [{"text": "hello"}, {"text": "world"}]
        rate = _infer_rate(strokes)
        assert rate is None

    def test_single_stroke(self):
        strokes = [{"at": "2026-11-02T10:00:00+00:00"}]
        rate = _infer_rate(strokes)
        assert rate is None

    def test_empty(self):
        rate = _infer_rate([])
        assert rate is None

    def test_malformed_timestamps(self):
        strokes = [
            {"at": "not-a-date"},
            {"at": "2026-11-02T10:00:00+00:00"},
            {"at": "2026-11-02T11:00:00+00:00"},
        ]
        rate = _infer_rate(strokes)
        assert rate is not None
        assert rate == pytest.approx(2.0)

    def test_same_timestamp(self):
        strokes = [
            {"at": "2026-11-02T10:00:00+00:00"},
            {"at": "2026-11-02T10:00:00+00:00"},
        ]
        rate = _infer_rate(strokes)
        assert rate is None  # span is zero


# ===========================================================================
# VitalityReport
# ===========================================================================


class TestVitalityReport:
    def test_is_healthy_true(self):
        r = VitalityReport(score=75.0, verdict="healthy", breakdown={})
        assert r.is_healthy is True

    def test_is_healthy_false(self):
        r = VitalityReport(score=35.0, verdict="stagnant", breakdown={})
        assert r.is_healthy is False

    def test_weakest_dimension(self):
        r = VitalityReport(
            score=60.0,
            verdict="healthy",
            breakdown={"rate": 0.9, "novelty": 0.3, "kind_balance": 0.7, "coherence": 0.8},
        )
        assert r.weakest_dimension == "novelty"

    def test_weakest_dimension_empty(self):
        r = VitalityReport(score=50.0, verdict="struggling", breakdown={})
        assert r.weakest_dimension == "unknown"

    def test_to_dict(self):
        r = VitalityReport(
            score=72.0,
            verdict="healthy",
            breakdown={"rate": 0.8},
            details={"stroke_count": 100},
        )
        d = r.to_dict()
        assert d["score"] == 72.0
        assert d["verdict"] == "healthy"
        assert d["stroke_count"] == 100
        assert "weakest" in d

    def test_frozen(self):
        r = VitalityReport(score=50.0, verdict="struggling", breakdown={})
        with pytest.raises(AttributeError):
            r.score = 60.0


# ===========================================================================
# VitalityScorer
# ===========================================================================


class TestVitalityScorer:
    def test_default_construction(self):
        scorer = VitalityScorer()
        assert scorer.novelty_window == DEFAULT_NOVELTY_WINDOW
        assert scorer.target_rate == DEFAULT_TARGET_RATE

    def test_custom_params(self):
        scorer = VitalityScorer(novelty_window=20, target_rate=500.0)
        assert scorer.novelty_window == 20
        assert scorer.target_rate == 500.0

    def test_invalid_window(self):
        with pytest.raises(ValueError, match="novelty_window"):
            VitalityScorer(novelty_window=0)

    def test_invalid_target(self):
        with pytest.raises(ValueError, match="target_rate"):
            VitalityScorer(target_rate=-1.0)

    def test_assess_healthy_input(self):
        scorer = VitalityScorer()
        kinds = ["devlog", "garden", "snippet", "note", "thought"] * 4
        texts = [
            f"unique topic number {i} about different subject matter"
            for i in range(20)
        ]
        strokes = _make_strokes(texts, kinds=kinds)
        report = scorer.assess(strokes, rate_per_hour=280.0)
        assert 0 <= report.score <= 100
        assert report.verdict in {"thriving", "healthy", "struggling", "stagnant"}
        assert len(report.breakdown) == 4

    def test_assess_no_rate(self):
        scorer = VitalityScorer()
        strokes = _make_strokes(["hello world", "foo bar baz"])
        report = scorer.assess(strokes)
        assert report.breakdown["rate"] == 0.5  # neutral default

    def test_assess_override_target(self):
        scorer = VitalityScorer(target_rate=300.0)
        strokes = _make_strokes(["x"] * 5)
        r1 = scorer.assess(strokes, rate_per_hour=150.0)
        r2 = scorer.assess(strokes, rate_per_hour=150.0, target_rate=150.0)
        # Lower target → higher rate score
        assert r2.breakdown["rate"] > r1.breakdown["rate"]

    def test_assess_zero_rate(self):
        scorer = VitalityScorer()
        strokes = _make_strokes(["x"] * 5)
        report = scorer.assess(strokes, rate_per_hour=0.0)
        assert report.breakdown["rate"] == 0.0

    def test_assess_from_strokes(self):
        scorer = VitalityScorer()
        strokes = _make_strokes(
            [f"text about topic {i}" for i in range(20)],
            kinds=["note", "devlog"] * 10,
        )
        report = scorer.assess_from_strokes(strokes)
        assert isinstance(report, VitalityReport)
        assert report.details["stroke_count"] == 20

    def test_verdict_thresholds(self):
        scorer = VitalityScorer()
        # Stagnant: all dimensions low
        strokes = _make_strokes(["same text"] * 10, kinds=["thought"])
        report = scorer.assess(strokes, rate_per_hour=10.0)
        assert report.verdict == "stagnant"

    def test_breakdown_keys(self):
        scorer = VitalityScorer()
        strokes = _make_strokes(["hello"] * 5)
        report = scorer.assess(strokes, rate_per_hour=100.0)
        assert set(report.breakdown.keys()) == {
            "rate",
            "novelty",
            "kind_balance",
            "coherence",
        }

    def test_weights_sum_to_one(self):
        assert sum(WEIGHTS.values()) == pytest.approx(1.0)

    def test_score_range(self):
        scorer = VitalityScorer()
        # Random diverse input
        texts = [f"topic {i} with words about {i * 7}" for i in range(50)]
        kinds = [ALL_KINDS[i % 8] for i in range(50)]
        strokes = _make_strokes(texts, kinds=kinds)
        report = scorer.assess(strokes, rate_per_hour=300.0)
        assert 0.0 <= report.score <= 100.0


# ===========================================================================
# format_report
# ===========================================================================


class TestFormatReport:
    def test_basic_format(self):
        report = VitalityReport(
            score=72.5,
            verdict="healthy",
            breakdown={"rate": 0.8, "novelty": 0.65, "kind_balance": 0.7, "coherence": 0.75},
            details={"stroke_count": 200, "observed_rate": 280.0},
        )
        text = format_report(report)
        assert "healthy" in text
        assert "72.5" in text
        assert "200 strokes" in text
        assert "280/hr" in text

    def test_minimal_report(self):
        report = VitalityReport(
            score=45.0, verdict="struggling", breakdown={"rate": 0.4}
        )
        text = format_report(report)
        assert "struggling" in text
        assert "45.0" in text


# ===========================================================================
# Integration: end-to-end with realistic data
# ===========================================================================


class TestIntegration:
    def test_healthy_writer(self):
        """Simulate a healthy writer producing diverse content."""
        scorer = VitalityScorer(target_rate=240.0)
        texts = [
            "the garden grows new branches every week",
            "commit pipelines need careful error handling",
            "naming conventions reveal hidden assumptions",
            "test coverage only matters if tests assert something",
            "a deterministic log is a reproducible log",
            "process restarts should be auditable events",
            "rate without quality is just faster landfill",
            "the caretaker watches but does not interfere",
            "coherence means threads not repetition",
            "novelty decays when the writer runs out of topics",
        ]
        kinds = [
            "garden", "devlog", "note", "thought", "snippet",
            "devlog", "note", "caretaker", "thought", "metrics",
        ]
        strokes = _make_strokes(texts, kinds=kinds)
        report = scorer.assess(strokes, rate_per_hour=240.0)

        assert report.score >= 40  # at least struggling+
        assert report.breakdown["rate"] == 1.0  # at target
        assert report.breakdown["kind_balance"] > 0.5  # 7 kinds used
        assert report.breakdown["novelty"] > 0.3  # diverse texts

    def test_stagnant_writer(self):
        """Simulate a stuck writer producing identical content."""
        scorer = VitalityScorer(target_rate=300.0)
        strokes = _make_strokes(
            ["the same thought repeated"] * 20,
            kinds=["thought"],
        )
        report = scorer.assess(strokes, rate_per_hour=30.0)

        assert report.score < 60
        assert report.breakdown["rate"] < 0.2  # way below target
        assert report.breakdown["kind_balance"] == 0.0  # single kind
        assert report.breakdown["novelty"] < 0.1  # pure repetition

    def test_jsonl_roundtrip(self, tmp_path):
        """Write strokes to JSONL, load them, score them."""
        strokes_path = tmp_path / "strokes.jsonl"
        strokes = _make_strokes(
            [f"topic {i} is interesting" for i in range(30)],
            kinds=["note", "devlog", "garden"] * 10,
        )
        with open(strokes_path, "w") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")

        # Load and score
        loaded = []
        with open(strokes_path) as f:
            for line in f:
                loaded.append(json.loads(line.strip()))

        scorer = VitalityScorer()
        report = scorer.assess_from_strokes(loaded)
        assert report.score > 0
        assert report.details["stroke_count"] == 30
