"""Tests for iamai.repo_nervous_system."""

import pytest
from unittest.mock import patch

from iamai.repo_nervous_system import (
    NerveReport,
    ReflexPair,
    REFLEX_PAIRS,
    nerve_report,
    nerve_summary,
    _find_paired,
    _extract_reflex_events,
    _classify_health,
    _tools_present,
    _git_log,
)


# ---------------------------------------------------------------------------
# ReflexPair dataclass
# ---------------------------------------------------------------------------

class TestReflexPair:
    def test_frozen(self):
        pair = ReflexPair(detector="a", responder="b")
        with pytest.raises(AttributeError):
            pair.detector = "c"

    def test_defaults(self):
        pair = ReflexPair(detector="a", responder="b")
        assert pair.expected_latency_s == 600.0
        assert pair.severity == "medium"


# ---------------------------------------------------------------------------
# _find_paired
# ---------------------------------------------------------------------------

class TestFindPaired:
    def test_both_present(self):
        pairs = (ReflexPair("det_a", "resp_a"),)
        matched, orphan_d, orphan_r = _find_paired(["det_a", "resp_a"], pairs)
        assert len(matched) == 1
        assert orphan_d == []
        assert orphan_r == []

    def test_detector_only(self):
        pairs = (ReflexPair("det_a", "resp_a"),)
        matched, orphan_d, orphan_r = _find_paired(["det_a"], pairs)
        assert matched == []
        assert orphan_d == ["det_a"]
        assert orphan_r == []

    def test_responder_only(self):
        pairs = (ReflexPair("det_a", "resp_a"),)
        matched, orphan_d, orphan_r = _find_paired(["resp_a"], pairs)
        assert matched == []
        assert orphan_d == []
        assert orphan_r == ["resp_a"]

    def test_neither_present(self):
        pairs = (ReflexPair("det_a", "resp_a"),)
        matched, orphan_d, orphan_r = _find_paired([], pairs)
        assert matched == []
        assert orphan_d == []
        assert orphan_r == []

    def test_multiple_pairs_mixed(self):
        pairs = (
            ReflexPair("d1", "r1"),
            ReflexPair("d2", "r2"),
            ReflexPair("d3", "r3"),
        )
        tools = ["d1", "r1", "d2", "r3"]
        matched, orphan_d, orphan_r = _find_paired(tools, pairs)
        assert len(matched) == 1
        assert matched[0].detector == "d1"
        assert orphan_d == ["d2"]
        assert orphan_r == ["r3"]

    def test_empty_pairs(self):
        matched, orphan_d, orphan_r = _find_paired(["any"], ())
        assert matched == []
        assert orphan_d == []
        assert orphan_r == []


# ---------------------------------------------------------------------------
# _extract_reflex_events
# ---------------------------------------------------------------------------

class TestExtractReflexEvents:
    def test_basic_pair(self):
        log = [
            ("aaa", "stall detected in writer loop"),
            ("bbb", "restart writer after stall"),
        ]
        latencies = _extract_reflex_events(log)
        assert len(latencies) == 1
        assert latencies[0] == 600.0  # 1 gap * 600s

    def test_two_gap_pair(self):
        log = [
            ("aaa", "stall detected at 03:00"),
            ("bbb", "unrelated commit"),
            ("ccc", "recovery and restart"),
        ]
        latencies = _extract_reflex_events(log)
        assert len(latencies) == 1
        assert latencies[0] == 1200.0  # 2 gaps * 600s

    def test_no_detection(self):
        log = [
            ("aaa", "add new feature"),
            ("bbb", "improve tests"),
        ]
        latencies = _extract_reflex_events(log)
        assert latencies == []

    def test_detection_without_response(self):
        log = [
            ("aaa", "stall detected"),
            ("bbb", "add new feature"),
            ("ccc", "update docs"),
        ]
        latencies = _extract_reflex_events(log)
        assert latencies == []

    def test_multiple_pairs(self):
        log = [
            ("a1", "stall detected"),
            ("a2", "restart done"),
            ("a3", "deadman triggered"),
            ("a4", "catch-up commit flushed"),
        ]
        latencies = _extract_reflex_events(log)
        assert len(latencies) == 2

    def test_empty_log(self):
        assert _extract_reflex_events([]) == []

    def test_backlog_detection(self):
        log = [
            ("aaa", "backlog pressure exceeding threshold"),
            ("bbb", "flush pending strokes"),
        ]
        latencies = _extract_reflex_events(log)
        assert len(latencies) == 1

    def test_push_race(self):
        log = [
            ("aaa", "push race detected at remote"),
            ("bbb", "something else"),
            ("ccc", "push gate activated"),
        ]
        latencies = _extract_reflex_events(log)
        assert len(latencies) == 1
        assert latencies[0] == 1200.0

    def test_stale_lock(self):
        log = [
            ("aaa", "stale lock found in index"),
            ("bbb", "lock clean completed"),
        ]
        latencies = _extract_reflex_events(log)
        assert len(latencies) == 1

    def test_dedup_pending_detection(self):
        """Two detections in a row: only the first is tracked."""
        log = [
            ("aaa", "stall detected first"),
            ("bbb", "deadman also triggered"),
            ("ccc", "restart writer"),
        ]
        latencies = _extract_reflex_events(log)
        # Only one reflex pair, from idx 0 to idx 2
        assert len(latencies) == 1
        assert latencies[0] == 1200.0


# ---------------------------------------------------------------------------
# _classify_health
# ---------------------------------------------------------------------------

class TestClassifyHealth:
    def test_sharp(self):
        assert _classify_health(90.0, 0) == "sharp"

    def test_sharp_boundary(self):
        assert _classify_health(80.0, 0) == "sharp"

    def test_responsive(self):
        assert _classify_health(70.0, 1) == "responsive"

    def test_responsive_boundary(self):
        assert _classify_health(60.0, 2) == "responsive"

    def test_dulled(self):
        assert _classify_health(50.0, 5) == "dulled"

    def test_dulled_boundary(self):
        assert _classify_health(40.0, 10) == "dulled"

    def test_neuropathic(self):
        assert _classify_health(30.0, 3) == "neuropathic"

    def test_neuropathic_zero(self):
        assert _classify_health(0.0, 0) == "neuropathic"

    def test_high_integrity_with_orphans(self):
        """High integrity but many orphans → dulled (orphans > 2)."""
        assert _classify_health(85.0, 5) == "dulled"

    def test_boundary_59(self):
        assert _classify_health(59.0, 1) == "dulled"


# ---------------------------------------------------------------------------
# nerve_summary
# ---------------------------------------------------------------------------

class TestNerveSummary:
    def test_dormant(self):
        report = NerveReport(nerve_health="dormant")
        s = nerve_summary(report)
        assert "dormant" in s

    def test_sharp_with_latency(self):
        report = NerveReport(
            nerve_health="sharp",
            reflex_integrity=95.0,
            paired_reflexes=14,
            mean_reflex_latency_s=450.0,
        )
        s = nerve_summary(report)
        assert "sharp" in s
        assert "95%" in s
        assert "450s" in s

    def test_orphan_detectors_listed(self):
        report = NerveReport(
            nerve_health="dulled",
            reflex_integrity=50.0,
            paired_reflexes=5,
            orphan_detectors=["stall_probe", "push_lag"],
        )
        s = nerve_summary(report)
        assert "stall_probe" in s
        assert "push_lag" in s

    def test_no_orphans_no_orphan_text(self):
        report = NerveReport(
            nerve_health="sharp",
            reflex_integrity=100.0,
            paired_reflexes=10,
        )
        s = nerve_summary(report)
        assert "orphan" not in s.lower()

    def test_zero_latency_omitted(self):
        report = NerveReport(
            nerve_health="responsive",
            reflex_integrity=70.0,
            paired_reflexes=8,
            mean_reflex_latency_s=0.0,
        )
        s = nerve_summary(report)
        assert "mean reflex" not in s


# ---------------------------------------------------------------------------
# nerve_report (integration with mocks)
# ---------------------------------------------------------------------------

class TestNerveReport:
    def test_empty_log_returns_dormant(self):
        with patch("iamai.repo_nervous_system._git_log", return_value=[]):
            report = nerve_report(repo_path="/fake", last=50)
        assert report.nerve_health == "dormant"
        assert report.commit_count == 0

    def test_basic_report(self):
        log = [
            ("aaa", "caretaker visit 351: add repo_circulation.py"),
            ("bbb", "stall detected and classified"),
            ("ccc", "restart writer after stall"),
        ]
        tools = [
            "stall_classifier", "run_both", "auto_lock_clean",
            "stale_lock_detector", "commit_batch", "push_gate",
            "push_race_counter", "deadman_switch",
        ]
        with patch("iamai.repo_nervous_system._git_log", return_value=log), \
             patch("iamai.repo_nervous_system._tools_present", return_value=tools):
            report = nerve_report(repo_path="/fake", last=50)

        assert report.commit_count == 3
        assert report.detector_count > 0
        assert report.nerve_health != "dormant"

    def test_report_has_reflex_count(self):
        log = [("aaa", "add feature")]
        tools = ["stall_classifier", "run_both", "deadman_switch"]
        with patch("iamai.repo_nervous_system._git_log", return_value=log), \
             patch("iamai.repo_nervous_system._tools_present", return_value=tools):
            report = nerve_report(repo_path="/fake", last=10)
        assert report.paired_reflexes >= 1

    def test_report_orphan_detectors(self):
        log = [("aaa", "add feature")]
        # writer_silence_detector present but run_both missing
        tools = ["writer_silence_detector", "stale_lock_detector", "auto_lock_clean"]
        with patch("iamai.repo_nervous_system._git_log", return_value=log), \
             patch("iamai.repo_nervous_system._tools_present", return_value=tools):
            report = nerve_report(repo_path="/fake", last=10)
        # writer_silence_detector should be orphan (run_both missing)
        assert "writer_silence_detector" in report.orphan_detectors

    def test_report_lesions(self):
        log = [("aaa", "add feature")]
        tools = ["run_both"]  # Only responder, no detectors at all
        with patch("iamai.repo_nervous_system._git_log", return_value=log), \
             patch("iamai.repo_nervous_system._tools_present", return_value=tools):
            report = nerve_report(repo_path="/fake", last=10)
        # All detectors are missing → lesions
        assert len(report.lesions) > 0


# ---------------------------------------------------------------------------
# REFLEX_PAIRS integrity
# ---------------------------------------------------------------------------

class TestReflexPairsIntegrity:
    """Ensure the curated pair registry is self-consistent."""

    def test_all_pairs_have_detector(self):
        for pair in REFLEX_PAIRS:
            assert pair.detector, f"pair missing detector: {pair}"

    def test_all_pairs_have_responder(self):
        for pair in REFLEX_PAIRS:
            assert pair.responder, f"pair missing responder: {pair}"

    def test_positive_latency(self):
        for pair in REFLEX_PAIRS:
            assert pair.expected_latency_s > 0

    def test_valid_severity(self):
        valid = {"low", "medium", "high"}
        for pair in REFLEX_PAIRS:
            assert pair.severity in valid, f"bad severity: {pair.severity}"

    def test_no_duplicate_detectors(self):
        detectors = [p.detector for p in REFLEX_PAIRS]
        assert len(detectors) == len(set(detectors))

    def test_has_critical_pairs(self):
        """At least the stall→restart pair must exist."""
        stall_pairs = [p for p in REFLEX_PAIRS if "stall" in p.detector]
        assert len(stall_pairs) >= 1
