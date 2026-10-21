"""tests for iamai.stroke_novelty"""

import pytest

from iamai.stroke_novelty import (
    DEFAULT_WINDOW,
    NoveltyReport,
    NoveltyScorer,
    _tokenise,
)


# ---------------------------------------------------------------------------
# _tokenise()
# ---------------------------------------------------------------------------
class TestTokenise:
    def test_basic(self):
        assert _tokenise("Hello World") == {"hello", "world"}

    def test_punctuation_stripped(self):
        assert _tokenise("a repo, that's fine!") == {"a", "repo", "that", "s", "fine"}

    def test_numbers_kept(self):
        assert _tokenise("stroke 400") == {"stroke", "400"}

    def test_empty(self):
        assert _tokenise("") == set()
        assert _tokenise("   ") == set()

    def test_case_insensitive(self):
        assert _tokenise("ABC abc") == {"abc"}


# ---------------------------------------------------------------------------
# NoveltyScorer.score()
# ---------------------------------------------------------------------------
class TestScoreBatch:
    def test_single_stroke_is_fully_novel(self):
        scorer = NoveltyScorer()
        report = scorer.score(["hello world"])
        assert report.scores == [1.0]
        assert report.average == 1.0

    def test_identical_strokes_low_novelty(self):
        scorer = NoveltyScorer()
        report = scorer.score([
            "a repo that only accumulates is a landfill",
            "a repo that only accumulates is a landfill",
        ])
        assert report.scores[0] == 1.0
        assert report.scores[1] == 0.0

    def test_partial_overlap(self):
        scorer = NoveltyScorer()
        report = scorer.score([
            "commit history is documentation",
            "commit history is the only honest thing",
        ])
        # second stroke: tokens = {commit, history, is, the, only, honest, thing}
        # overlap = {commit, history, is} → 3/7 ≈ 0.571
        assert 0.4 < report.scores[1] < 0.7

    def test_empty_batch(self):
        scorer = NoveltyScorer()
        report = scorer.score([])
        assert report.scores == []
        assert report.average == 0.0
        assert report.count == 0

    def test_empty_stroke_gets_zero(self):
        scorer = NoveltyScorer()
        report = scorer.score(["hello world", ""])
        assert report.scores[1] == 0.0

    def test_window_respected(self):
        scorer = NoveltyScorer(window=1)
        report = scorer.score([
            "alpha beta gamma",
            "alpha beta gamma",
            "delta epsilon zeta",
        ])
        # stroke 0: novel (1.0)
        # stroke 1 vs stroke 0: all overlap → 0.0
        # stroke 2 vs stroke 1 only (window=1): no overlap → 1.0
        assert report.scores[0] == 1.0
        assert report.scores[1] == 0.0
        assert report.scores[2] == 1.0

    def test_window_two_looks_back_further(self):
        scorer = NoveltyScorer(window=2)
        report = scorer.score([
            "alpha beta",
            "gamma delta",
            "alpha gamma",
        ])
        # stroke 2 vs {0,1}: tokens {alpha, gamma}, overlap = {alpha, gamma} → 0.0
        assert report.scores[2] == 0.0


# ---------------------------------------------------------------------------
# NoveltyScorer.score_one()
# ---------------------------------------------------------------------------
class TestScoreOne:
    def test_no_history_is_novel(self):
        scorer = NoveltyScorer()
        assert scorer.score_one("hello world", []) == 1.0

    def test_full_overlap(self):
        scorer = NoveltyScorer()
        score = scorer.score_one(
            "hello world",
            ["hello world", "goodbye world"],
        )
        assert score == 0.0

    def test_window_limits_reference(self):
        scorer = NoveltyScorer(window=1)
        # only the last history entry counts
        score = scorer.score_one(
            "alpha beta",
            ["gamma delta", "alpha beta"],
        )
        # reference = {alpha, beta} from last entry → full overlap
        assert score == 0.0

    def test_empty_stroke(self):
        scorer = NoveltyScorer()
        assert scorer.score_one("", ["hello"]) == 0.0


# ---------------------------------------------------------------------------
# NoveltyReport properties
# ---------------------------------------------------------------------------
class TestReport:
    def test_min_max(self):
        report = NoveltyReport(scores=[0.2, 0.8, 0.5])
        assert report.min_score == 0.2
        assert report.max_score == 0.8

    def test_empty_min_max(self):
        report = NoveltyReport()
        assert report.min_score == 0.0
        assert report.max_score == 0.0

    def test_above_threshold(self):
        report = NoveltyReport(scores=[0.1, 0.5, 0.9, 0.3])
        assert report.above_threshold(0.5) == 2

    def test_below_threshold(self):
        report = NoveltyReport(scores=[0.1, 0.5, 0.9, 0.2])
        assert report.below_threshold(0.3) == 2

    def test_count(self):
        report = NoveltyReport(scores=[0.5, 0.5])
        assert report.count == 2


# ---------------------------------------------------------------------------
# trend detection
# ---------------------------------------------------------------------------
class TestTrend:
    def test_falling(self):
        scorer = NoveltyScorer()
        report = scorer.score([
            "alpha beta gamma delta",
            "alpha beta gamma epsilon",
            "alpha beta gamma zeta",
            "alpha beta gamma eta",
        ])
        assert report.trend == "falling"

    def test_steady_with_two_items(self):
        scorer = NoveltyScorer()
        report = scorer.score(["hello world", "goodbye moon"])
        assert report.trend == "steady"

    def test_steady_single(self):
        scorer = NoveltyScorer()
        report = scorer.score(["hello world"])
        assert report.trend == "steady"


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_invalid_window(self):
        with pytest.raises(ValueError):
            NoveltyScorer(window=0)
        with pytest.raises(ValueError):
            NoveltyScorer(window=-1)

    def test_default_window(self):
        scorer = NoveltyScorer()
        assert scorer.window == DEFAULT_WINDOW

    def test_long_batch(self):
        scorer = NoveltyScorer(window=3)
        strokes = [f"unique word token number {i}" for i in range(20)]
        report = scorer.score(strokes)
        assert report.count == 20
        assert all(0.0 <= s <= 1.0 for s in report.scores)
