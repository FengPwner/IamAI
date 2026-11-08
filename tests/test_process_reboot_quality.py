"""Tests for iamai.process_reboot_quality module."""

import pytest

from iamai.process_reboot_quality import RebootQuality, reboot_quality_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strokes(start, interval, count, jitter=0.0):
    """Generate ascending timestamps with optional jitter."""
    import random
    if jitter:
        random.seed(42)
    times = []
    t = start
    for _ in range(count):
        times.append(t)
        delta = interval
        if jitter:
            delta += random.uniform(-jitter, jitter)
        t += max(0.1, delta)
    return times


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_reboot():
    """Old process writes 20 strokes, then 60s gap, new process writes 30 clean strokes."""
    pre = _strokes(1000.0, 15.0, 20)
    post = _strokes(pre[-1] + 60.0, 15.0, 30)
    return pre, post


@pytest.fixture
def lossy_reboot():
    """Old process writes 20 strokes, then 600s gap, new process writes only 5."""
    pre = _strokes(1000.0, 15.0, 20)
    post = _strokes(pre[-1] + 600.0, 15.0, 5)
    return pre, post


@pytest.fixture
def overlapping_reboot():
    """Old process keeps writing after new one starts — overlap."""
    pre = _strokes(1000.0, 15.0, 20)
    # new process starts before old one stops
    post = _strokes(pre[-1] - 30.0, 15.0, 25)
    return pre, post


@pytest.fixture
def jittery_reboot():
    """Clean handoff but post-reboot cadence is very uneven."""
    pre = _strokes(1000.0, 15.0, 20)
    post = _strokes(pre[-1] + 20.0, 15.0, 20, jitter=12.0)
    return pre, post


# ---------------------------------------------------------------------------
# Loss ratio
# ---------------------------------------------------------------------------


class TestLossRatio:
    def test_no_loss(self, clean_reboot):
        pre, post = clean_reboot
        rq = RebootQuality(pre, post, expected_interval=15.0)
        assert rq.loss_ratio == 0.0

    def test_significant_loss(self, lossy_reboot):
        pre, post = lossy_reboot
        rq = RebootQuality(pre, post, expected_interval=15.0)
        # 600s gap / 15s = 40 expected strokes, only 5 produced
        assert rq.loss_ratio > 0.5

    def test_empty_pre_is_zero_loss(self):
        post = _strokes(1000.0, 15.0, 10)
        rq = RebootQuality([], post, expected_interval=15.0)
        assert rq.loss_ratio == 0.0

    def test_empty_post_is_zero_loss(self):
        pre = _strokes(1000.0, 15.0, 10)
        rq = RebootQuality(pre, [], expected_interval=15.0)
        assert rq.loss_ratio == 0.0


# ---------------------------------------------------------------------------
# Overlap
# ---------------------------------------------------------------------------


class TestOverlap:
    def test_no_overlap(self, clean_reboot):
        pre, post = clean_reboot
        rq = RebootQuality(pre, post, expected_interval=15.0)
        assert rq.overlap_s == 0.0

    def test_overlap_detected(self, overlapping_reboot):
        pre, post = overlapping_reboot
        rq = RebootQuality(pre, post, expected_interval=15.0)
        assert rq.overlap_s > 0.0
        # last pre-stroke is after first post-stroke
        assert pre[-1] > post[0]

    def test_overlap_duration(self):
        pre = [100.0, 115.0, 130.0, 145.0]
        post = [120.0, 135.0, 150.0, 165.0]
        rq = RebootQuality(pre, post, expected_interval=15.0)
        # last pre = 145, first post = 120, overlap = 25s
        assert rq.overlap_s == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# Cadence drift
# ---------------------------------------------------------------------------


class TestCadenceDrift:
    def test_perfect_cadence(self, clean_reboot):
        pre, post = clean_reboot
        rq = RebootQuality(pre, post, expected_interval=15.0)
        assert rq.cadence_drift < 0.01

    def test_drift_detected(self, jittery_reboot):
        pre, post = jittery_reboot
        rq = RebootQuality(pre, post, expected_interval=15.0)
        # jittery post-strokes should show more drift
        assert rq.cadence_drift > 0.0

    def test_single_post_stroke_no_drift(self):
        pre = _strokes(1000.0, 15.0, 10)
        post = [pre[-1] + 15.0]
        rq = RebootQuality(pre, post, expected_interval=15.0)
        assert rq.cadence_drift == 0.0

    def test_empty_post_no_drift(self):
        pre = _strokes(1000.0, 15.0, 10)
        rq = RebootQuality(pre, [], expected_interval=15.0)
        assert rq.cadence_drift == 0.0


# ---------------------------------------------------------------------------
# Sequence gap
# ---------------------------------------------------------------------------


class TestSequenceGap:
    def test_no_gap(self):
        pre = [100.0, 115.0, 130.0]
        post = [145.0, 160.0, 175.0]
        rq = RebootQuality(pre, post, expected_interval=15.0)
        assert rq.sequence_gap == 0

    def test_gap_detected(self):
        pre = [100.0, 115.0, 130.0]
        # 4 missing strokes worth of time
        post = [130.0 + 15.0 * 5, 130.0 + 15.0 * 6, 130.0 + 15.0 * 7]
        rq = RebootQuality(pre, post, expected_interval=15.0)
        assert rq.sequence_gap >= 3

    def test_empty_sequences(self):
        rq = RebootQuality([], [], expected_interval=15.0)
        assert rq.sequence_gap == 0


# ---------------------------------------------------------------------------
# Downtime
# ---------------------------------------------------------------------------


class TestDowntime:
    def test_downtime_measured(self, clean_reboot):
        pre, post = clean_reboot
        rq = RebootQuality(pre, post, expected_interval=15.0)
        assert rq.downtime_s == pytest.approx(60.0, abs=0.5)

    def test_zero_downtime(self):
        pre = [100.0, 115.0, 130.0]
        post = [130.1, 145.1, 160.1]
        rq = RebootQuality(pre, post, expected_interval=15.0)
        assert rq.downtime_s < 1.0


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


class TestVerdict:
    def test_clean_reboot_is_clean(self, clean_reboot):
        pre, post = clean_reboot
        rq = RebootQuality(pre, post, expected_interval=15.0)
        assert rq.verdict == "clean"

    def test_lossy_reboot_is_not_clean(self, lossy_reboot):
        pre, post = lossy_reboot
        rq = RebootQuality(pre, post, expected_interval=15.0)
        assert rq.verdict != "clean"

    def test_overlapping_reboot_penalized(self, overlapping_reboot):
        pre, post = overlapping_reboot
        rq = RebootQuality(pre, post, expected_interval=15.0)
        assert rq.overlap_s > 0.0

    def test_verdict_is_valid_string(self, clean_reboot):
        pre, post = clean_reboot
        rq = RebootQuality(pre, post, expected_interval=15.0)
        assert rq.verdict in {"clean", "acceptable", "rough", "degraded", "broken"}

    def test_explicit_reboot_time(self):
        pre = _strokes(1000.0, 15.0, 10)
        reboot_at = pre[-1] + 30.0
        post = _strokes(reboot_at + 15.0, 15.0, 20)
        rq = RebootQuality(pre, post, expected_interval=15.0, reboot_time=reboot_at)
        assert rq.verdict in {"clean", "acceptable"}


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class TestSummary:
    def test_summary_keys(self, clean_reboot):
        pre, post = clean_reboot
        rq = RebootQuality(pre, post, expected_interval=15.0)
        s = rq.summary()
        expected_keys = {
            "loss_ratio", "overlap_s", "cadence_drift", "sequence_gap",
            "downtime_s", "pre_stroke_count", "post_stroke_count", "verdict",
        }
        assert set(s.keys()) == expected_keys

    def test_summary_types(self, clean_reboot):
        pre, post = clean_reboot
        rq = RebootQuality(pre, post, expected_interval=15.0)
        s = rq.summary()
        assert isinstance(s["loss_ratio"], float)
        assert isinstance(s["overlap_s"], float)
        assert isinstance(s["cadence_drift"], float)
        assert isinstance(s["sequence_gap"], int)
        assert isinstance(s["downtime_s"], float)
        assert isinstance(s["pre_stroke_count"], int)
        assert isinstance(s["post_stroke_count"], int)
        assert isinstance(s["verdict"], str)

    def test_summary_counts(self, clean_reboot):
        pre, post = clean_reboot
        rq = RebootQuality(pre, post, expected_interval=15.0)
        s = rq.summary()
        assert s["pre_stroke_count"] == 20
        assert s["post_stroke_count"] == 30


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class TestReport:
    def test_report_format(self, clean_reboot):
        pre, post = clean_reboot
        report = reboot_quality_report(pre, post, expected_interval=15.0)
        assert "reboot:" in report
        assert "lost strokes" in report
        assert "overlap" in report
        assert "cadence drift" in report
        assert "clean" in report

    def test_report_with_explicit_reboot_time(self):
        pre = _strokes(1000.0, 15.0, 10)
        reboot_at = pre[-1] + 45.0
        post = _strokes(reboot_at + 15.0, 15.0, 20)
        report = reboot_quality_report(pre, post, expected_interval=15.0,
                                       reboot_time=reboot_at)
        assert isinstance(report, str)
        assert "reboot:" in report

    def test_report_empty_post(self):
        pre = _strokes(1000.0, 15.0, 10)
        report = reboot_quality_report(pre, [], expected_interval=15.0)
        assert "reboot:" in report

    def test_report_empty_pre(self):
        post = _strokes(1000.0, 15.0, 10)
        report = reboot_quality_report([], post, expected_interval=15.0)
        assert "reboot:" in report


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_single_stroke_each(self):
        pre = [1000.0]
        post = [1020.0]
        rq = RebootQuality(pre, post, expected_interval=15.0)
        assert rq.pre_stroke_count == 1
        assert rq.post_stroke_count == 1
        assert rq.downtime_s == pytest.approx(20.0)

    def test_both_empty(self):
        rq = RebootQuality([], [], expected_interval=15.0)
        assert rq.loss_ratio == 0.0
        assert rq.overlap_s == 0.0
        assert rq.cadence_drift == 0.0
        assert rq.sequence_gap == 0
        assert rq.downtime_s == 0.0

    def test_unsorted_input_is_sorted(self):
        pre = [130.0, 100.0, 115.0]
        post = [160.0, 145.0, 175.0]
        rq = RebootQuality(pre, post, expected_interval=15.0)
        assert rq.pre_stroke_count == 3
        assert rq.post_stroke_count == 3

    def test_identical_timestamps(self):
        pre = [100.0, 100.0, 100.0]
        post = [100.0, 100.0, 100.0]
        rq = RebootQuality(pre, post, expected_interval=15.0)
        # overlap: last pre = 100, first post = 100, overlap = 0
        assert rq.overlap_s == 0.0
