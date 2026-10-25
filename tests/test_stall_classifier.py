"""Tests for iamai.stall_classifier."""

from __future__ import annotations

import pytest
from iamai.stall_classifier import (
    classify_stall,
    classify_stalls_batch,
    summarise,
    _is_off_peak,
    _is_long_gap,
    _collect_signals,
    _score_category,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class TestIsOffPeak:
    def test_early_morning(self):
        assert _is_off_peak(1) is True
        assert _is_off_peak(3) is True
        assert _is_off_peak(5) is True

    def test_boundary(self):
        assert _is_off_peak(0) is False  # midnight not in window
        assert _is_off_peak(6) is False  # 06:00 is end (exclusive)

    def test_daytime(self):
        assert _is_off_peak(12) is False
        assert _is_off_peak(18) is False
        assert _is_off_peak(23) is False


class TestIsLongGap:
    def test_short_gap(self):
        assert _is_long_gap(300, 400) is False

    def test_exactly_double(self):
        assert _is_long_gap(800, 400) is False  # not > 2x, just ==

    def test_over_double(self):
        assert _is_long_gap(801, 400) is True

    def test_zero_modal(self):
        assert _is_long_gap(10, 0) is True

    def test_negative_modal(self):
        assert _is_long_gap(10, -1) is True


# ---------------------------------------------------------------------------
# signal collection
# ---------------------------------------------------------------------------

class TestCollectSignals:
    def test_process_death_signals(self):
        evidence = {
            "gap_seconds": 2000,
            "modal_interval": 400,
            "process_alive": False,
            "batch_alive": False,
            "lock_present": False,
            "hour_gmt8": 3,
            "disk_usage_pct": 50,
            "dmesg_oom": False,
            "abrupt_last_stroke": True,
        }
        signals = _collect_signals(evidence)
        pd = signals["process_death"]
        assert pd["process_dead"] is True
        assert pd["batch_dead"] is True
        assert pd["off_peak"] is True
        assert pd["abrupt_last_stroke"] is True
        assert pd["no_lock"] is True
        assert pd["long_gap"] is True

    def test_natural_gap_signals(self):
        evidence = {
            "gap_seconds": 300,
            "modal_interval": 400,
            "process_alive": True,
            "batch_alive": True,
            "lock_present": False,
            "hour_gmt8": 14,
            "disk_usage_pct": 30,
            "dmesg_oom": False,
        }
        signals = _collect_signals(evidence)
        ng = signals["natural_gap"]
        assert ng["process_alive"] is True
        assert ng["short_gap"] is True
        assert ng["peak_hour"] is True


# ---------------------------------------------------------------------------
# category scoring
# ---------------------------------------------------------------------------

class TestScoreCategory:
    def test_perfect_process_death(self):
        signals = {
            "process_dead": True,
            "batch_dead": True,
            "off_peak": True,
            "abrupt_last_stroke": True,
            "no_lock": True,
            "long_gap": True,
        }
        score, reasons = _score_category("process_death", signals)
        assert score == 1.0
        assert len(reasons) == 6

    def test_no_signals(self):
        signals = {k: False for k in [
            "process_dead", "batch_dead", "off_peak",
            "abrupt_last_stroke", "no_lock", "long_gap",
        ]}
        score, reasons = _score_category("process_death", signals)
        assert score == 0.0
        assert len(reasons) == 0


# ---------------------------------------------------------------------------
# full classification
# ---------------------------------------------------------------------------

class TestClassifyStall:
    def test_classic_process_death(self):
        """Off-peak, both processes dead, no lock → process_death."""
        evidence = {
            "gap_seconds": 1600,
            "modal_interval": 400,
            "process_alive": False,
            "batch_alive": False,
            "lock_present": False,
            "hour_gmt8": 3,
            "disk_usage_pct": 45,
            "dmesg_oom": False,
            "io_errors": False,
            "abrupt_last_stroke": True,
        }
        result = classify_stall(evidence)
        assert result["label"] == "process_death"
        assert result["confidence"] >= 0.80
        assert "off_peak" in result["reasons"]
        assert "process_dead" in result["reasons"]

    def test_lock_contention(self):
        """Lock file present, process alive, no OOM → lock_contention."""
        evidence = {
            "gap_seconds": 900,
            "modal_interval": 400,
            "process_alive": True,
            "batch_alive": True,
            "lock_present": True,
            "hour_gmt8": 15,
            "disk_usage_pct": 50,
            "dmesg_oom": False,
            "io_errors": False,
            "abrupt_last_stroke": False,
            "commit_gap_exceeds_stroke_gap": True,
        }
        result = classify_stall(evidence)
        assert result["label"] == "lock_contention"
        assert result["confidence"] >= 0.60
        assert "lock_present" in result["reasons"]

    def test_resource_exhaustion(self):
        """High disk + OOM → resource_exhaustion."""
        evidence = {
            "gap_seconds": 1200,
            "modal_interval": 400,
            "process_alive": False,
            "batch_alive": True,
            "lock_present": False,
            "hour_gmt8": 10,
            "disk_usage_pct": 95,
            "dmesg_oom": True,
            "io_errors": True,
            "abrupt_last_stroke": False,
        }
        result = classify_stall(evidence)
        assert result["label"] == "resource_exhaustion"
        assert result["confidence"] >= 0.60
        assert "high_disk" in result["reasons"]
        assert "dmesg_oom" in result["reasons"]

    def test_natural_gap(self):
        """Short gap, process alive, peak hours → natural_gap."""
        evidence = {
            "gap_seconds": 300,
            "modal_interval": 400,
            "process_alive": True,
            "batch_alive": True,
            "lock_present": False,
            "hour_gmt8": 14,
            "disk_usage_pct": 30,
            "dmesg_oom": False,
            "io_errors": False,
            "abrupt_last_stroke": False,
        }
        result = classify_stall(evidence)
        assert result["label"] == "natural_gap"
        assert result["confidence"] >= 0.70
        assert "process_alive" in result["reasons"]

    def test_unknown_when_ambiguous(self):
        """Minimal evidence should still produce a label (highest score wins)."""
        evidence = {
            "gap_seconds": 500,
            "modal_interval": 400,
            "process_alive": True,
            "batch_alive": True,
            "lock_present": False,
            "hour_gmt8": 12,
            "disk_usage_pct": 50,
            "dmesg_oom": False,
            "io_errors": False,
            "abrupt_last_stroke": False,
        }
        result = classify_stall(evidence)
        assert result["label"] in {
            "process_death", "lock_contention",
            "resource_exhaustion", "natural_gap",
        }
        assert 0 <= result["confidence"] <= 1.0

    def test_confidence_bounded(self):
        """Confidence is always in [0, 1]."""
        for hour in range(24):
            evidence = {
                "gap_seconds": 400,
                "modal_interval": 400,
                "process_alive": True,
                "batch_alive": False,
                "lock_present": True,
                "hour_gmt8": hour,
                "disk_usage_pct": 85,
                "dmesg_oom": False,
                "io_errors": False,
                "abrupt_last_stroke": False,
            }
            result = classify_stall(evidence)
            assert 0.0 <= result["confidence"] <= 1.0

    def test_all_scores_present(self):
        """Result always contains scores for all categories."""
        evidence = {
            "gap_seconds": 100,
            "modal_interval": 400,
            "process_alive": True,
            "batch_alive": True,
            "lock_present": False,
            "hour_gmt8": 12,
            "disk_usage_pct": 20,
            "dmesg_oom": False,
            "io_errors": False,
            "abrupt_last_stroke": False,
        }
        result = classify_stall(evidence)
        expected_keys = {
            "process_death", "lock_contention",
            "resource_exhaustion", "natural_gap",
        }
        assert set(result["scores"].keys()) == expected_keys


# ---------------------------------------------------------------------------
# batch and summary
# ---------------------------------------------------------------------------

class TestBatchAndSummarise:
    def test_classify_stalls_batch(self):
        events = [
            {
                "gap_seconds": 1600, "modal_interval": 400,
                "process_alive": False, "batch_alive": False,
                "lock_present": False, "hour_gmt8": 3,
                "disk_usage_pct": 45, "dmesg_oom": False,
                "io_errors": False, "abrupt_last_stroke": True,
            },
            {
                "gap_seconds": 300, "modal_interval": 400,
                "process_alive": True, "batch_alive": True,
                "lock_present": False, "hour_gmt8": 14,
                "disk_usage_pct": 30, "dmesg_oom": False,
                "io_errors": False, "abrupt_last_stroke": False,
            },
        ]
        results = classify_stalls_batch(events)
        assert len(results) == 2
        assert results[0]["label"] == "process_death"
        assert results[1]["label"] == "natural_gap"

    def test_summarise(self):
        classifications = [
            {"label": "process_death"},
            {"label": "process_death"},
            {"label": "natural_gap"},
            {"label": "lock_contention"},
            {"label": "process_death"},
        ]
        counts = summarise(classifications)
        assert counts["process_death"] == 3
        assert counts["natural_gap"] == 1
        assert counts["lock_contention"] == 1
        assert counts["resource_exhaustion"] == 0

    def test_summarise_empty(self):
        counts = summarise([])
        assert all(v == 0 for v in counts.values())


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_missing_fields_use_defaults(self):
        """Classifier should not crash on minimal evidence."""
        result = classify_stall({})
        assert "label" in result
        assert "confidence" in result
        assert "reasons" in result
        assert "scores" in result

    def test_extra_fields_ignored(self):
        """Extra evidence fields should not cause errors."""
        evidence = {
            "gap_seconds": 500,
            "modal_interval": 400,
            "process_alive": True,
            "batch_alive": True,
            "lock_present": False,
            "hour_gmt8": 12,
            "disk_usage_pct": 30,
            "dmesg_oom": False,
            "io_errors": False,
            "abrupt_last_stroke": False,
            "extra_field_1": "ignored",
            "extra_field_2": 42,
        }
        result = classify_stall(evidence)
        assert result["label"] in {
            "process_death", "lock_contention",
            "resource_exhaustion", "natural_gap",
        }

    def test_extreme_gap(self):
        """Very long gap should push toward process_death or resource."""
        evidence = {
            "gap_seconds": 86400,  # 24 hours
            "modal_interval": 400,
            "process_alive": False,
            "batch_alive": False,
            "lock_present": False,
            "hour_gmt8": 4,
            "disk_usage_pct": 40,
            "dmesg_oom": False,
            "io_errors": False,
            "abrupt_last_stroke": True,
        }
        result = classify_stall(evidence)
        assert result["label"] == "process_death"

    def test_off_peak_boundary_hour_0(self):
        """Hour 0 (midnight) is NOT in the off-peak window [1,6)."""
        evidence = {
            "gap_seconds": 1600, "modal_interval": 400,
            "process_alive": False, "batch_alive": False,
            "lock_present": False, "hour_gmt8": 0,
            "disk_usage_pct": 45, "dmesg_oom": False,
            "io_errors": False, "abrupt_last_stroke": True,
        }
        result = classify_stall(evidence)
        # hour 0 → not off_peak, so confidence should be lower
        # than the same evidence at hour 3
        evidence["hour_gmt8"] = 3
        result_peak = classify_stall(evidence)
        assert result_peak["confidence"] >= result["confidence"]

    def test_only_disk_high(self):
        """High disk alone should not dominate — process_death needs more."""
        evidence = {
            "gap_seconds": 400,
            "modal_interval": 400,
            "process_alive": True,
            "batch_alive": True,
            "lock_present": False,
            "hour_gmt8": 12,
            "disk_usage_pct": 95,
            "dmesg_oom": False,
            "io_errors": False,
            "abrupt_last_stroke": False,
        }
        result = classify_stall(evidence)
        # process alive + short gap → natural_gap should win over
        # resource_exhaustion despite high disk
        assert result["label"] != "resource_exhaustion"
