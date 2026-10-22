"""Tests for iamai.recovery_fidelity module."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.recovery_fidelity import (
    fidelity_report,
    fidelity_summary,
    _cadence_fidelity,
    _cv,
    _diversity_fidelity,
    _gap_stability,
    _grade,
    _inter_stroke_gaps,
    _length_fidelity,
    _mean,
    _median,
    _parse_ts,
    _stroke_lengths,
    _tokenize,
    _vocab_diversity,
)


# ── helpers ────────────────────────────────────────────────────


def _make_stroke(seq: int, text: str, ts: str) -> dict:
    return {"seq": seq, "text": text, "at": ts, "kind": "thought"}


def _make_uniform_strokes(n: int, text: str, gap_seconds: int,
                          base_ts: str = "2026-10-20T10:00:00+00:00") -> list:
    """Generate n strokes with uniform gap."""
    from datetime import datetime, timedelta, timezone
    base_epoch = _parse_ts(base_ts)
    base_dt = datetime.fromtimestamp(base_epoch, tz=timezone.utc)
    strokes = []
    for i in range(n):
        ts = (base_dt + timedelta(seconds=gap_seconds * i)).isoformat()
        strokes.append(_make_stroke(i + 1, text, ts))
    return strokes


# ── _tokenize ──────────────────────────────────────────────────


class TestTokenize:
    def test_basic(self):
        assert _tokenize("the garden grows") == ["the", "garden", "grows"]

    def test_punctuation(self):
        assert _tokenize("hello, world! test-case.") == ["hello", "world", "test", "case"]

    def test_case_insensitive(self):
        assert _tokenize("Garden GROWS") == ["garden", "grows"]

    def test_empty(self):
        assert _tokenize("") == []

    def test_numbers_stripped(self):
        tokens = _tokenize("commit 42 pushed")
        assert tokens == ["commit", "pushed"]


# ── _parse_ts ──────────────────────────────────────────────────


class TestParseTs:
    def test_epoch_float(self):
        assert _parse_ts(1697000000.0) == 1697000000.0

    def test_epoch_int(self):
        assert _parse_ts(1697000000) == 1697000000.0

    def test_epoch_string(self):
        assert _parse_ts("1697000000.0") == 1697000000.0

    def test_iso_with_tz(self):
        ts = _parse_ts("2026-10-20T10:00:00+00:00")
        assert ts > 0

    def test_iso_z_suffix(self):
        ts = _parse_ts("2026-10-20T10:00:00Z")
        assert ts > 0

    def test_iso_no_tz(self):
        ts = _parse_ts("2026-10-20T10:00:00")
        assert ts > 0

    def test_iso_fractional(self):
        ts = _parse_ts("2026-10-20T10:00:00.123456+00:00")
        assert ts > 0

    def test_space_separator(self):
        ts = _parse_ts("2026-10-20 10:00:00")
        assert ts > 0

    def test_garbage_returns_zero(self):
        assert _parse_ts("not-a-timestamp") == 0.0

    def test_none_returns_zero(self):
        assert _parse_ts(None) == 0.0


# ── _inter_stroke_gaps ─────────────────────────────────────────


class TestInterStrokeGaps:
    def test_uniform_gaps(self):
        strokes = _make_uniform_strokes(5, "hello world", 300)
        gaps = _inter_stroke_gaps(strokes)
        assert len(gaps) == 4
        for g in gaps:
            assert abs(g - 300) < 1.0

    def test_single_stroke(self):
        strokes = [_make_stroke(1, "hello", "2026-10-20T10:00:00+00:00")]
        assert _inter_stroke_gaps(strokes) == []

    def test_empty(self):
        assert _inter_stroke_gaps([]) == []

    def test_unsorted_input(self):
        """Gaps should still be computed correctly if strokes are out of order."""
        s1 = _make_stroke(1, "a b", "2026-10-20T10:00:00+00:00")
        s2 = _make_stroke(2, "c d", "2026-10-20T10:05:00+00:00")
        s3 = _make_stroke(3, "e f", "2026-10-20T10:10:00+00:00")
        gaps = _inter_stroke_gaps([s3, s1, s2])
        assert len(gaps) == 2
        for g in gaps:
            assert abs(g - 300) < 1.0


# ── _stroke_lengths ────────────────────────────────────────────


class TestStrokeLengths:
    def test_basic(self):
        strokes = [
            _make_stroke(1, "one two three", "2026-10-20T10:00:00+00:00"),
            _make_stroke(2, "four five", "2026-10-20T10:05:00+00:00"),
        ]
        assert _stroke_lengths(strokes) == [3, 2]

    def test_empty_text(self):
        strokes = [_make_stroke(1, "", "2026-10-20T10:00:00+00:00")]
        assert _stroke_lengths(strokes) == [0]


# ── _vocab_diversity ───────────────────────────────────────────


class TestVocabDiversity:
    def test_all_unique(self):
        strokes = [_make_stroke(1, "alpha beta gamma delta", "2026-10-20T10:00:00+00:00")]
        assert _vocab_diversity(strokes) == 1.0

    def test_all_same(self):
        strokes = [_make_stroke(1, "go go go go", "2026-10-20T10:00:00+00:00")]
        assert _vocab_diversity(strokes) == 0.25

    def test_empty(self):
        assert _vocab_diversity([]) == 0.0

    def test_mixed_strokes(self):
        strokes = [
            _make_stroke(1, "alpha beta", "2026-10-20T10:00:00+00:00"),
            _make_stroke(2, "beta gamma", "2026-10-20T10:05:00+00:00"),
        ]
        # tokens: alpha, beta, beta, gamma → 3/4 = 0.75
        assert abs(_vocab_diversity(strokes) - 0.75) < 0.01


# ── _mean / _median / _cv ──────────────────────────────────────


class TestStats:
    def test_mean_basic(self):
        assert _mean([10, 20, 30]) == 20.0

    def test_mean_empty(self):
        assert _mean([]) == 0.0

    def test_median_odd(self):
        assert _median([1, 3, 5]) == 3

    def test_median_even(self):
        assert _median([1, 2, 3, 4]) == 2.5

    def test_median_empty(self):
        assert _median([]) == 0.0

    def test_cv_uniform(self):
        assert _cv([10, 10, 10]) == 0.0

    def test_cv_variable(self):
        cv = _cv([10, 20, 30])
        assert cv > 0.4  # relatively variable

    def test_cv_empty(self):
        assert _cv([]) == 0.0

    def test_cv_zero_mean(self):
        assert _cv([0, 0, 0]) == 0.0


# ── _cadence_fidelity ──────────────────────────────────────────


class TestCadenceFidelity:
    def test_identical_gaps(self):
        pre = [300.0, 300.0, 300.0, 300.0]
        post = [300.0, 300.0, 300.0, 300.0]
        score = _cadence_fidelity(pre, post)
        assert score > 0.95

    def test_doubled_gaps(self):
        pre = [300.0, 300.0, 300.0, 300.0]
        post = [600.0, 600.0, 600.0, 600.0]
        score = _cadence_fidelity(pre, post)
        # median ratio = 0.5, but CV is 0 (uniform), so score = 0.5 * 1 = 0.5
        assert abs(score - 0.5) < 0.05

    def test_wildly_variable_post(self):
        pre = [300.0, 300.0, 300.0, 300.0]
        post = [100.0, 900.0, 50.0, 1200.0]
        score = _cadence_fidelity(pre, post)
        # high CV in post should penalise
        assert score < 0.5

    def test_zero_gaps(self):
        assert _cadence_fidelity([0, 0], [0, 0]) == 1.0


# ── _length_fidelity ───────────────────────────────────────────


class TestLengthFidelity:
    def test_identical_lengths(self):
        pre = [_make_stroke(i, "one two three", f"2026-10-20T10:{i:02d}:00+00:00")
               for i in range(10)]
        post = [_make_stroke(i, "four five six", f"2026-10-21T10:{i:02d}:00+00:00")
                for i in range(10)]
        score = _length_fidelity(pre, post)
        assert score == 1.0  # both have 3 words each

    def test_half_length(self):
        pre = [_make_stroke(i, "one two three four", f"2026-10-20T10:{i:02d}:00+00:00")
               for i in range(10)]
        post = [_make_stroke(i, "one two", f"2026-10-21T10:{i:02d}:00+00:00")
                for i in range(10)]
        score = _length_fidelity(pre, post)
        assert abs(score - 0.5) < 0.05

    def test_empty_both(self):
        pre = [_make_stroke(i, "", f"2026-10-20T10:{i:02d}:00+00:00") for i in range(10)]
        post = [_make_stroke(i, "", f"2026-10-21T10:{i:02d}:00+00:00") for i in range(10)]
        assert _length_fidelity(pre, post) == 1.0


# ── _diversity_fidelity ────────────────────────────────────────


class TestDiversityFidelity:
    def test_same_diversity(self):
        pre = [_make_stroke(i, "alpha beta gamma", f"2026-10-20T10:{i:02d}:00+00:00")
               for i in range(10)]
        post = [_make_stroke(i, "delta epsilon zeta", f"2026-10-21T10:{i:02d}:00+00:00")
                for i in range(10)]
        score = _diversity_fidelity(pre, post)
        assert score > 0.9

    def test_degraded_diversity(self):
        pre = [_make_stroke(i, f"word{i} alpha beta gamma", f"2026-10-20T10:{i:02d}:00+00:00")
               for i in range(10)]
        post = [_make_stroke(i, "same same same", f"2026-10-21T10:{i:02d}:00+00:00")
                for i in range(10)]
        score = _diversity_fidelity(pre, post)
        assert score < 0.5


# ── _gap_stability ─────────────────────────────────────────────


class TestGapStability:
    def test_perfectly_uniform(self):
        assert _gap_stability([300.0, 300.0, 300.0]) == 1.0

    def test_variable(self):
        score = _gap_stability([100.0, 500.0, 100.0, 500.0])
        assert 0.0 <= score < 0.5

    def test_empty(self):
        assert _gap_stability([]) == 1.0  # cv of empty is 0


# ── _grade ─────────────────────────────────────────────────────


class TestGrade:
    def test_full(self):
        assert _grade(0.95) == "full"
        assert _grade(0.90) == "full"

    def test_good(self):
        assert _grade(0.85) == "good"
        assert _grade(0.70) == "good"

    def test_partial(self):
        assert _grade(0.65) == "partial"
        assert _grade(0.50) == "partial"

    def test_poor(self):
        assert _grade(0.49) == "poor"
        assert _grade(0.0) == "poor"


# ── fidelity_report (integration) ─────────────────────────────


class TestFidelityReport:
    def test_perfect_recovery(self):
        """Identical pre and post strokes → score near 1.0."""
        text = "the garden grows steadily through autumn rain"
        pre = _make_uniform_strokes(10, text, 300)
        post = _make_uniform_strokes(10, text, 300, "2026-10-21T10:00:00+00:00")
        report = fidelity_report(pre, post)
        assert report["grade"] in ("full", "good")
        assert report["fidelity_score"] > 0.85
        assert report["pre_count"] == 10
        assert report["post_count"] == 10

    def test_degraded_recovery(self):
        """Shorter, less diverse post strokes → lower score."""
        pre_text = "the garden grows steadily through autumn rain and careful tending"
        post_text = "ok fine"
        pre = _make_uniform_strokes(10, pre_text, 300)
        post = _make_uniform_strokes(10, post_text, 600, "2026-10-21T10:00:00+00:00")
        report = fidelity_report(pre, post)
        assert report["fidelity_score"] < 0.7
        assert report["length_fidelity"] < 0.5

    def test_insufficient_pre(self):
        pre = _make_uniform_strokes(2, "hello", 300)
        post = _make_uniform_strokes(10, "world", 300)
        report = fidelity_report(pre, post)
        assert report["grade"] == "unknown"
        assert "insufficient" in report.get("note", "")

    def test_insufficient_post(self):
        pre = _make_uniform_strokes(10, "hello", 300)
        post = _make_uniform_strokes(3, "world", 300)
        report = fidelity_report(pre, post)
        assert report["grade"] == "unknown"

    def test_empty_both(self):
        report = fidelity_report([], [])
        assert report["grade"] == "unknown"

    def test_report_keys(self):
        pre = _make_uniform_strokes(10, "alpha beta gamma", 300)
        post = _make_uniform_strokes(10, "delta epsilon zeta", 300,
                                     "2026-10-21T10:00:00+00:00")
        report = fidelity_report(pre, post)
        expected_keys = {
            "fidelity_score", "grade", "cadence_fidelity", "length_fidelity",
            "diversity_fidelity", "gap_stability", "pre_count", "post_count",
            "detail",
        }
        assert expected_keys.issubset(set(report.keys()))

    def test_detail_keys(self):
        pre = _make_uniform_strokes(10, "alpha beta gamma", 300)
        post = _make_uniform_strokes(10, "delta epsilon zeta", 300,
                                     "2026-10-21T10:00:00+00:00")
        report = fidelity_report(pre, post)
        detail = report["detail"]
        for key in ("pre_mean_gap", "post_mean_gap", "pre_mean_length",
                     "post_mean_length", "pre_diversity", "post_diversity",
                     "post_gap_cv"):
            assert key in detail


# ── fidelity_summary ───────────────────────────────────────────


class TestFidelitySummary:
    def test_good_recovery(self):
        text = "the garden grows steadily through autumn rain"
        pre = _make_uniform_strokes(10, text, 300)
        post = _make_uniform_strokes(10, text, 300, "2026-10-21T10:00:00+00:00")
        summary = fidelity_summary(pre, post)
        assert "fidelity" in summary
        assert "(" in summary and ")" in summary

    def test_insufficient_data(self):
        summary = fidelity_summary([], [])
        assert "need at least" in summary or "insufficient" in summary

    def test_degraded_signals_mentioned(self):
        pre = _make_uniform_strokes(10, "alpha beta gamma delta epsilon", 300)
        post = _make_uniform_strokes(10, "ok", 900, "2026-10-21T10:00:00+00:00")
        summary = fidelity_summary(pre, post)
        # should mention at least one degradation signal
        assert any(s in summary for s in
                   ["cadence drift", "shorter strokes", "narrower vocab", "unsteady gaps"])
