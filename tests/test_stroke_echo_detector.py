"""Tests for iamai.stroke_echo_detector — near-duplicate stroke detection."""

from __future__ import annotations

import pytest

from iamai.stroke_echo_detector import (
    ECHO_THRESHOLD,
    PREVIEW_LEN,
    WINDOW_SIZE,
    EchoEvent,
    EchoReport,
    _preview,
    detect_echoes,
    echo_report,
    text_similarity,
)


# ---------------------------------------------------------------------------
# text_similarity
# ---------------------------------------------------------------------------


class TestTextSimilarity:
    def test_identical_strings(self):
        assert text_similarity("hello world", "hello world") == 1.0

    def test_completely_different(self):
        ratio = text_similarity("aaaa", "zzzz")
        assert ratio < 0.1

    def test_one_char_difference(self):
        ratio = text_similarity("abcdefghij", "abcdefghik")
        assert ratio > 0.85

    def test_empty_strings(self):
        assert text_similarity("", "") == 1.0

    def test_one_empty(self):
        ratio = text_similarity("hello", "")
        assert ratio == 0.0

    def test_number_substitution(self):
        a = "tree is 839 files; 174049 lines is a lot for a toy"
        b = "tree is 839 files; 174084 lines is a lot for a toy"
        ratio = text_similarity(a, b)
        assert ratio > 0.90

    def test_reordered_words(self):
        a = "the quick brown fox"
        b = "the brown quick fox"
        ratio = text_similarity(a, b)
        assert 0.6 < ratio < 0.95


# ---------------------------------------------------------------------------
# _preview
# ---------------------------------------------------------------------------


class TestPreview:
    def test_short_text_unchanged(self):
        assert _preview("hello") == "hello"

    def test_long_text_truncated(self):
        text = "x" * 200
        result = _preview(text, max_len=50)
        assert len(result) == 50
        assert result.endswith("...")

    def test_whitespace_normalised(self):
        assert _preview("  hello   world  ") == "hello world"

    def test_exact_boundary(self):
        text = "a" * PREVIEW_LEN
        assert _preview(text) == text

    def test_one_over_boundary(self):
        text = "a" * (PREVIEW_LEN + 1)
        result = _preview(text)
        assert len(result) == PREVIEW_LEN
        assert result.endswith("...")


# ---------------------------------------------------------------------------
# detect_echoes
# ---------------------------------------------------------------------------


class TestDetectEchoes:
    def test_no_echoes_diverse_input(self):
        texts = [
            "the quick brown fox jumps over the lazy dog",
            "completely different sentence about nothing",
            "yet another unique observation today",
            "something entirely new to consider",
        ]
        assert detect_echoes(texts) == []

    def test_exact_duplicates(self):
        texts = ["hello world", "something else", "hello world"]
        events = detect_echoes(texts)
        assert len(events) >= 1
        assert events[0].ratio == 1.0
        assert events[0].index_a == 0
        assert events[0].index_b == 2

    def test_near_duplicates(self):
        texts = [
            "tree is 839 files; 174049 lines is a lot for a toy",
            "tree is 839 files; 174084 lines is a lot for a toy",
        ]
        events = detect_echoes(texts, threshold=0.85)
        assert len(events) == 1
        assert events[0].ratio > 0.90

    def test_empty_input(self):
        assert detect_echoes([]) == []

    def test_single_stroke(self):
        assert detect_echoes(["hello"]) == []

    def test_threshold_sensitivity(self):
        texts = [
            "tree is 839 files; 174049 lines is a lot for a toy",
            "tree is 839 files; 174084 lines is a lot for a toy",
        ]
        # High threshold should miss it if ratio < 0.99
        high_events = detect_echoes(texts, threshold=0.999)
        # Low threshold should catch it
        low_events = detect_echoes(texts, threshold=0.50)
        assert len(low_events) >= len(high_events)

    def test_window_respects_boundary(self):
        # Two identical strings separated by more than window_size
        filler = [f"unique sentence number {i}" for i in range(WINDOW_SIZE + 5)]
        texts = ["duplicate"] + filler + ["duplicate"]
        events = detect_echoes(texts, window=WINDOW_SIZE)
        # The two "duplicate" entries are too far apart for the window
        assert all(not (e.index_a == 0 and e.index_b == len(texts) - 1) for e in events)

    def test_window_catches_nearby(self):
        texts = ["duplicate", "something", "duplicate"]
        events = detect_echoes(texts, window=5)
        assert len(events) >= 1

    def test_multiple_echoes(self):
        texts = [
            "536 python files, 3302 logged thoughts",
            "536 python files, 3305 logged thoughts",
            "536 python files, 3308 logged thoughts",
        ]
        events = detect_echoes(texts, threshold=0.85)
        assert len(events) >= 2  # (0,1), (0,2), and possibly (1,2)

    def test_events_sorted_by_index_b(self):
        texts = [
            "alpha bravo charlie delta echo",
            "foxtrot golf hotel india juliet",
            "alpha bravo charlie delta echo",  # echo of 0
            "foxtrot golf hotel india juliet",  # echo of 1
        ]
        events = detect_echoes(texts, threshold=0.90)
        for i in range(1, len(events)):
            assert events[i].index_b >= events[i - 1].index_b


# ---------------------------------------------------------------------------
# EchoEvent
# ---------------------------------------------------------------------------


class TestEchoEvent:
    def test_severity_near_identical(self):
        ev = EchoEvent(0, 1, 0.96, "a", "b")
        assert ev.severity == "near-identical"

    def test_severity_very_similar(self):
        ev = EchoEvent(0, 1, 0.92, "a", "b")
        assert ev.severity == "very-similar"

    def test_severity_similar(self):
        ev = EchoEvent(0, 1, 0.87, "a", "b")
        assert ev.severity == "similar"

    def test_frozen(self):
        ev = EchoEvent(0, 1, 0.90, "a", "b")
        with pytest.raises(AttributeError):
            ev.ratio = 0.5


# ---------------------------------------------------------------------------
# EchoReport
# ---------------------------------------------------------------------------


class TestEchoReport:
    def test_clean_report(self):
        r = EchoReport(total_strokes=100, echo_count=0)
        assert r.echo_density == 0.0
        assert r.worst_ratio == 0.0
        assert r.verdict == "clean"

    def test_mild_report(self):
        r = EchoReport(
            total_strokes=100,
            echo_count=5,
            events=[EchoEvent(0, 1, 0.90, "a", "b")],
        )
        assert r.echo_density == 0.05
        assert r.verdict == "mild"

    def test_echoing_report(self):
        events = [EchoEvent(i, i + 1, 0.95, "a", "b") for i in range(20)]
        r = EchoReport(total_strokes=50, echo_count=20, events=events)
        assert r.echo_density == 0.40
        assert r.verdict == "echoing"
        assert r.worst_ratio == 0.95

    def test_summary_clean(self):
        r = EchoReport(total_strokes=100, echo_count=0)
        s = r.summary()
        assert "no echoes" in s
        assert "100" in s

    def test_summary_with_echoes(self):
        r = EchoReport(
            total_strokes=100,
            echo_count=3,
            events=[EchoEvent(0, 1, 0.95, "a", "b")],
        )
        s = r.summary()
        assert "3 echoes" in s
        assert "0.95" in s

    def test_summary_single_echo(self):
        r = EchoReport(
            total_strokes=10,
            echo_count=1,
            events=[EchoEvent(0, 1, 0.88, "a", "b")],
        )
        s = r.summary()
        assert "1 echo" in s
        # Should NOT say "1 echoe"
        assert "1 echoe" not in s


# ---------------------------------------------------------------------------
# echo_report (integration)
# ---------------------------------------------------------------------------


class TestEchoReportIntegration:
    def test_full_pipeline(self):
        texts = [
            "tree is 839 files; 174049 lines is a lot for a toy",
            "tree is 839 files; 174084 lines is a lot for a toy",
            "something completely different here",
            "another unique observation about the weather",
        ]
        report = echo_report(texts)
        assert report.total_strokes == 4
        assert report.echo_count >= 1
        assert report.verdict in ("mild", "echoing")

    def test_empty_pipeline(self):
        report = echo_report([])
        assert report.total_strokes == 0
        assert report.echo_count == 0
        assert report.verdict == "clean"

    def test_custom_threshold(self):
        texts = ["hello world", "hello earth"]
        # Default threshold might not catch it
        strict = echo_report(texts, threshold=0.95)
        # Relaxed threshold should catch it
        relaxed = echo_report(texts, threshold=0.50)
        assert relaxed.echo_count >= strict.echo_count
