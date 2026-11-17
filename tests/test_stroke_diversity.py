"""Tests for iamai/stroke_diversity.py — category rotation balance."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.stroke_diversity import (
    ALL_KINDS,
    classify_diversity,
    diversity_report,
    diversity_summary,
    kind_share,
    missing_kind_count,
)


# ---------------------------------------------------------------------------
# classify_diversity
# ---------------------------------------------------------------------------

class TestClassifyDiversity:
    def test_balanced_high(self):
        assert classify_diversity(1.0) == "balanced"

    def test_balanced_boundary(self):
        assert classify_diversity(0.85) == "balanced"

    def test_skewed_low_boundary(self):
        assert classify_diversity(0.8499) == "skewed"

    def test_skewed_mid(self):
        assert classify_diversity(0.75) == "skewed"

    def test_skewed_high_boundary(self):
        assert classify_diversity(0.65) == "skewed"

    def test_fixated_below_boundary(self):
        assert classify_diversity(0.6499) == "fixated"

    def test_fixated_low(self):
        assert classify_diversity(0.30) == "fixated"

    def test_fixated_zero(self):
        assert classify_diversity(0.0) == "fixated"

    def test_negative_clamps_to_zero(self):
        assert classify_diversity(-0.5) == "fixated"


# ---------------------------------------------------------------------------
# diversity_report — balanced input
# ---------------------------------------------------------------------------

class TestDiversityReportBalanced:
    """Perfectly uniform distribution across all six kinds."""

    @pytest.fixture()
    def report(self):
        kinds = list(ALL_KINDS) * 10  # 60 strokes, 10 each
        return diversity_report(kinds)

    def test_label_balanced(self, report):
        assert report["label"] == "balanced"

    def test_diversity_index_one(self, report):
        assert report["diversity_index"] == 1.0

    def test_no_missing_kinds(self, report):
        assert report["missing_kinds"] == []

    def test_dominant_share_uniform(self, report):
        # All equal, so any one kind is 1/6 ≈ 0.1667
        assert abs(report["dominant_share"] - 1 / 6) < 0.001

    def test_count(self, report):
        assert report["count"] == 60

    def test_not_fixated(self, report):
        assert report["is_fixated"] is False

    def test_entropy_equals_max(self, report):
        assert abs(report["entropy"] - report["max_entropy"]) < 0.001

    def test_all_kinds_in_counts(self, report):
        for k in ALL_KINDS:
            assert k in report["kind_counts"]
            assert report["kind_counts"][k] == 10


# ---------------------------------------------------------------------------
# diversity_report — fixated input
# ---------------------------------------------------------------------------

class TestDiversityReportFixated:
    """One kind dominates heavily."""

    @pytest.fixture()
    def report(self):
        kinds = ["thought"] * 50 + ["devlog"] * 5 + ["garden"] * 5
        return diversity_report(kinds)

    def test_label_fixated(self, report):
        assert report["label"] == "fixated"

    def test_dominant_kind_thought(self, report):
        assert report["dominant_kind"] == "thought"

    def test_dominant_share_high(self, report):
        assert report["dominant_share"] == pytest.approx(50 / 60, abs=0.01)

    def test_missing_kinds(self, report):
        # snippet, metrics, note are missing
        assert set(report["missing_kinds"]) == {"snippet", "metrics", "note"}

    def test_is_fixated(self, report):
        assert report["is_fixated"] is True

    def test_diversity_index_low(self, report):
        assert report["diversity_index"] < 0.65


# ---------------------------------------------------------------------------
# diversity_report — skewed input
# ---------------------------------------------------------------------------

class TestDiversityReportSkewed:
    """Moderate imbalance — not fixated but not balanced either."""

    @pytest.fixture()
    def report(self):
        # thought gets 30, devlog 12, garden 8, snippet 5, metrics 3, note 2
        kinds = (
            ["thought"] * 30
            + ["devlog"] * 12
            + ["garden"] * 8
            + ["snippet"] * 5
            + ["metrics"] * 3
            + ["note"] * 2
        )
        return diversity_report(kinds)

    def test_label_skewed(self, report):
        assert report["label"] == "skewed"

    def test_dominant_kind_thought(self, report):
        assert report["dominant_kind"] == "thought"

    def test_is_fixated(self, report):
        # 30/60 = 0.5, above default 0.4 threshold
        assert report["is_fixated"] is True

    def test_no_missing(self, report):
        assert report["missing_kinds"] == []


# ---------------------------------------------------------------------------
# diversity_report — insufficient data
# ---------------------------------------------------------------------------

class TestDiversityReportInsufficient:
    def test_empty(self):
        r = diversity_report([])
        assert r["label"] == "insufficient_data"
        assert r["count"] == 0

    def test_one_stroke(self):
        r = diversity_report(["devlog"])
        assert r["label"] == "insufficient_data"

    def test_five_strokes(self):
        r = diversity_report(["devlog", "garden", "snippet", "thought", "metrics"])
        assert r["label"] == "insufficient_data"

    def test_six_strokes_sufficient(self):
        r = diversity_report(list(ALL_KINDS))
        assert r["label"] != "insufficient_data"


# ---------------------------------------------------------------------------
# diversity_report — edge cases
# ---------------------------------------------------------------------------

class TestDiversityReportEdgeCases:
    def test_two_kinds_only(self):
        kinds = ["devlog"] * 30 + ["garden"] * 30
        r = diversity_report(kinds)
        # Only 2 of 6 kinds used — entropy is low relative to max
        assert r["label"] in ("fixated", "skewed")
        assert len(r["missing_kinds"]) == 4

    def test_unknown_kind_included(self):
        kinds = list(ALL_KINDS) * 5 + ["experimental"] * 10
        r = diversity_report(kinds)
        assert "experimental" in r["kind_counts"]
        assert r["kind_counts"]["experimental"] == 10

    def test_single_kind_repeated(self):
        kinds = ["thought"] * 100
        r = diversity_report(kinds)
        assert r["label"] == "fixated"
        assert r["diversity_index"] == 0.0
        assert r["dominant_share"] == 1.0
        assert len(r["missing_kinds"]) == 5

    def test_fixation_threshold_custom(self):
        kinds = ["thought"] * 15 + ["devlog"] * 10 + ["garden"] * 10 + \
                ["snippet"] * 10 + ["metrics"] * 10 + ["note"] * 5
        # Default threshold 0.4 — thought at 25% should not trigger
        r_default = diversity_report(kinds)
        assert r_default["is_fixated"] is False
        # Lower threshold 0.2 — thought at 25% should trigger
        r_low = diversity_report(kinds, fixation_threshold=0.2)
        assert r_low["is_fixated"] is True


# ---------------------------------------------------------------------------
# diversity_summary
# ---------------------------------------------------------------------------

class TestDiversitySummary:
    def test_balanced_summary(self):
        kinds = list(ALL_KINDS) * 2
        s = diversity_summary(kinds)
        assert "balanced" in s
        assert "12 strokes" in s

    def test_insufficient_summary(self):
        s = diversity_summary(["devlog", "garden"])
        assert "insufficient data" in s

    def test_fixated_summary(self):
        kinds = ["thought"] * 30
        s = diversity_summary(kinds)
        assert "fixated" in s
        assert "thought" in s


# ---------------------------------------------------------------------------
# missing_kind_count
# ---------------------------------------------------------------------------

class TestMissingKindCount:
    def test_all_present(self):
        assert missing_kind_count(list(ALL_KINDS)) == 0

    def test_all_missing(self):
        assert missing_kind_count([]) == 6

    def test_one_kind_present(self):
        assert missing_kind_count(["thought"] * 10) == 5

    def test_three_kinds_present(self):
        assert missing_kind_count(["devlog", "garden", "snippet"] * 5) == 3


# ---------------------------------------------------------------------------
# kind_share
# ---------------------------------------------------------------------------

class TestKindShare:
    def test_half(self):
        kinds = ["devlog", "garden", "devlog", "thought"]
        assert kind_share(kinds, "devlog") == 0.5

    def test_zero(self):
        kinds = ["garden", "snippet", "thought"]
        assert kind_share(kinds, "devlog") == 0.0

    def test_empty(self):
        assert kind_share([], "devlog") == 0.0

    def test_all_same(self):
        kinds = ["thought"] * 20
        assert kind_share(kinds, "thought") == 1.0

    def test_all_kinds(self):
        kinds = list(ALL_KINDS)
        for k in ALL_KINDS:
            assert kind_share(kinds, k) == pytest.approx(1 / 6, abs=0.001)
