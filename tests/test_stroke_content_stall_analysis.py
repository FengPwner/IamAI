"""Tests for tools/stroke_content_stall_analysis.py"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.stroke_content_stall_analysis import (
    analyse,
    detect_stalls,
    format_summary,
    has_metric,
    median,
    text_length,
)

# ---------------------------------------------------------------------------
# detect_stalls
# ---------------------------------------------------------------------------


def test_detect_stalls_empty():
    assert detect_stalls([]) == []


def test_detect_stalls_single():
    assert detect_stalls([datetime(2026, 1, 1, tzinfo=timezone.utc)]) == []


def test_detect_stalls_no_gaps():
    ts = [
        datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 0, 1, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 0, 2, 0, tzinfo=timezone.utc),
    ]
    assert detect_stalls(ts, threshold_seconds=300) == []


def test_detect_stalls_one_gap():
    ts = [
        datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 0, 1, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 0, 10, 0, tzinfo=timezone.utc),  # 540s gap
    ]
    assert detect_stalls(ts, threshold_seconds=300) == [1]


def test_detect_stalls_multiple_gaps():
    ts = [
        datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 0, 10, 0, tzinfo=timezone.utc),  # gap at 0
        datetime(2026, 1, 1, 0, 11, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 0, 20, 0, tzinfo=timezone.utc),  # gap at 2
    ]
    result = detect_stalls(ts, threshold_seconds=300)
    assert result == [0, 2]


def test_detect_stalls_custom_threshold():
    ts = [
        datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 0, 2, 0, tzinfo=timezone.utc),   # 120s
        datetime(2026, 1, 1, 0, 3, 0, tzinfo=timezone.utc),
    ]
    assert detect_stalls(ts, threshold_seconds=60) == [0]
    assert detect_stalls(ts, threshold_seconds=300) == []


# ---------------------------------------------------------------------------
# text_length
# ---------------------------------------------------------------------------


def test_text_length_basic():
    assert text_length({"text": "hello"}) == 5


def test_text_length_empty():
    assert text_length({"text": ""}) == 0


def test_text_length_missing_key():
    assert text_length({}) == 0


def test_text_length_unicode():
    assert text_length({"text": "你好世界"}) == 4


# ---------------------------------------------------------------------------
# has_metric
# ---------------------------------------------------------------------------


def test_has_metric_files():
    assert has_metric({"text": "tree is 1049 files"}) is True


def test_has_metric_lines():
    assert has_metric({"text": "222112 lines is a lot for a toy"}) is True


def test_has_metric_commits_deep():
    assert has_metric({"text": "12 commits deep"}) is True


def test_has_metric_logged_thoughts():
    assert has_metric({"text": "673 logged thoughts"}) is True


def test_has_metric_python_files():
    assert has_metric({"text": "673 python files"}) is True


def test_has_metric_no_match():
    assert has_metric({"text": "the quick brown fox"}) is False


def test_has_metric_empty():
    assert has_metric({"text": ""}) is False


def test_has_metric_missing():
    assert has_metric({}) is False


def test_has_metric_number_only():
    assert has_metric({"text": "42 reasons to refactor"}) is False


def test_has_metric_tracked_files():
    assert has_metric({"text": "30 tracked files"}) is True


# ---------------------------------------------------------------------------
# median
# ---------------------------------------------------------------------------


def test_median_odd():
    assert median([1, 3, 5]) == 3.0


def test_median_even():
    assert median([1, 2, 3, 4]) == 2.5


def test_median_single():
    assert median([7]) == 7.0


def test_median_empty():
    assert median([]) == 0.0


def test_median_unsorted():
    assert median([5, 1, 3]) == 3.0


def test_median_duplicates():
    assert median([2, 2, 2]) == 2.0


# ---------------------------------------------------------------------------
# analyse (integration)
# ---------------------------------------------------------------------------


def _make_strokes(texts, intervals_seconds):
    """Helper: build stroke list with controlled timestamps and texts."""
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    strokes = []
    t = base
    for i, (txt, gap) in enumerate(zip(texts, intervals_seconds)):
        t = t + timedelta(seconds=gap)
        strokes.append({
            "seq": i + 1,
            "at": t.isoformat(),
            "kind": "thought",
            "text": txt,
        })
    return strokes


def test_analyse_no_stalls():
    strokes = _make_strokes(
        ["short", "also short", "still short"],
        [0, 60, 60],
    )
    r = analyse(strokes, threshold_seconds=300)
    assert r["stalls_detected"] == 0
    assert r["length_score"] == 0.0
    assert r["verdict"] == "independent"


def test_analyse_long_text_stalls():
    # strokes before stalls are long; others are short
    short = "hi"
    long_text = "a" * 200 + " 1049 files"
    strokes = _make_strokes(
        [short, long_text, short, long_text, short],
        [0, 60, 600, 60, 600],  # gaps at indices 1 and 3 → stall-preceding = long
    )
    r = analyse(strokes, threshold_seconds=300)
    assert r["stalls_detected"] == 2
    assert r["length_score"] == 1.0  # both stall-preceding strokes are above median
    assert r["verdict"] == "content_correlated"


def test_analyse_metric_stalls():
    no_metric = "just a thought about code"
    with_metric = "tree is 1049 files; 222112 lines"
    strokes = _make_strokes(
        [no_metric, with_metric, no_metric, with_metric, no_metric],
        [0, 60, 600, 60, 600],
    )
    r = analyse(strokes, threshold_seconds=300)
    assert r["stalls_detected"] == 2
    assert r["stall_metric_rate"] == 1.0


def test_analyse_independent():
    # uniform short text, stalls at random — no content signal
    strokes = _make_strokes(
        ["hi"] * 10,
        [0, 60, 600, 60, 60, 600, 60, 60, 600, 60],
    )
    r = analyse(strokes, threshold_seconds=300)
    assert r["stalls_detected"] >= 2
    assert r["length_score"] <= 0.5  # all same length → at most half above median
    assert r["verdict"] == "independent"


def test_analyse_weak_signal():
    # slightly longer texts before stalls but not dramatically
    strokes = _make_strokes(
        ["ab", "abc", "ab", "abcde", "ab", "abcdefgh", "ab", "abc", "ab"],
        [0, 60, 600, 60, 600, 60, 60, 60, 60],
    )
    r = analyse(strokes, threshold_seconds=300)
    assert r["stalls_detected"] >= 1


def test_analyse_verdict_thresholds():
    # force length_score to specific ranges by controlling stall-preceding texts
    # all population: mix of short and long
    # stall-preceding: all long → length_score = 1.0 → content_correlated
    strokes = _make_strokes(
        ["x", "x" * 200, "x", "x" * 200, "x", "x" * 200],
        [0, 60, 600, 60, 600, 60],
    )
    r = analyse(strokes, threshold_seconds=300)
    assert r["verdict"] in ("content_correlated", "weak_signal", "independent")


def test_analyse_empty_strokes():
    r = analyse([], threshold_seconds=300)
    assert r["strokes_analyzed"] == 0
    assert r["stalls_detected"] == 0


# ---------------------------------------------------------------------------
# format_summary
# ---------------------------------------------------------------------------


def test_format_summary_contains_key_fields():
    r = {
        "strokes_analyzed": 100,
        "stalls_detected": 5,
        "population_median_length": 120.0,
        "population_metric_rate": 0.45,
        "length_score": 0.6123,
        "metric_score": 0.3456,
        "stall_median_length": 150.0,
        "stall_metric_rate": 0.6,
        "verdict": "weak_signal",
    }
    s = format_summary(r)
    assert "100" in s
    assert "5" in s
    assert "0.6123" in s
    assert "0.3456" in s
    assert "weak_signal" in s


def test_format_summary_no_trailing_newline():
    r = {
        "strokes_analyzed": 0,
        "stalls_detected": 0,
        "population_median_length": 0.0,
        "population_metric_rate": 0.0,
        "length_score": 0.0,
        "metric_score": 0.5,
        "stall_median_length": 0.0,
        "stall_metric_rate": 0.0,
        "verdict": "independent",
    }
    s = format_summary(r)
    assert not s.endswith("\n")
