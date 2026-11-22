"""Tests for iamai.writer_pre_stall_warning — pre-stall early warning.

Visit 806: this module was created after observing the writer enter a
repetitive loop (producing "X is already in the pool of 9 modules"
dozens of times) before the process eventually died.  An early warning
signal would have caught the degradation hours before the stall.

Test areas:
    1. _tokenize         — lowercase splitting
    2. _jaccard          — set similarity, empty sets, identical, disjoint
    3. _load_recent_strokes — file reading, missing file, malformed lines
    4. content_diversity — unique-token ratio, empty, single stroke
    5. repetition_ratio  — consecutive pair similarity, threshold effects
    6. length_trend      — shrinking, growing, flat, single stroke
    7. warning_score     — composite blending, edge cases
    8. verdict           — threshold boundaries
    9. pre_stall_report  — full report structure and rounding
   10. pre_stall_summary — string format
   11. _cli             — exit codes, --json flag
   12. edge cases       — empty list, all-empty strokes, unicode
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_pre_stall_warning import (
    _cli,
    _jaccard,
    _linear_slope,
    _load_recent_strokes,
    _tokenize,
    content_diversity,
    length_trend,
    pre_stall_report,
    pre_stall_summary,
    repetition_ratio,
    verdict,
    warning_score,
)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _stroke(text: str, seq: int = 0, kind: str = "thought") -> dict:
    return {"seq": seq, "kind": kind, "text": text}


def _write_strokes(tmp_path: Path, lines: list[str]) -> Path:
    p = tmp_path / "strokes.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# -----------------------------------------------------------------------
# 1. _tokenize
# -----------------------------------------------------------------------


class TestTokenize:
    def test_basic(self):
        assert _tokenize("hello World") == {"hello", "world"}

    def test_empty(self):
        assert _tokenize("") == set()

    def test_repeated(self):
        assert _tokenize("a a a") == {"a"}


# -----------------------------------------------------------------------
# 2. _jaccard
# -----------------------------------------------------------------------


class TestJaccard:
    def test_identical(self):
        assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint(self):
        assert _jaccard({"a"}, {"b"}) == 0.0

    def test_partial(self):
        # {a,b} ∩ {b,c} = {b}, union = {a,b,c}
        assert abs(_jaccard({"a", "b"}, {"b", "c"}) - 1 / 3) < 1e-9

    def test_both_empty(self):
        assert _jaccard(set(), set()) == 0.0

    def test_one_empty(self):
        assert _jaccard({"a"}, set()) == 0.0


# -----------------------------------------------------------------------
# 3. _load_recent_strokes
# -----------------------------------------------------------------------


class TestLoadRecentStrokes:
    def test_reads_tail(self, tmp_path):
        lines = [json.dumps(_stroke(f"stroke {i}", seq=i)) for i in range(20)]
        p = _write_strokes(tmp_path, lines)
        result = _load_recent_strokes(n=5, path=p)
        assert len(result) == 5
        assert result[0]["seq"] == 15  # tail of 20, take last 5

    def test_fewer_than_n(self, tmp_path):
        lines = [json.dumps(_stroke("only one", seq=1))]
        p = _write_strokes(tmp_path, lines)
        result = _load_recent_strokes(n=10, path=p)
        assert len(result) == 1

    def test_missing_file(self, tmp_path):
        p = tmp_path / "nonexistent.jsonl"
        result = _load_recent_strokes(n=5, path=p)
        assert result == []

    def test_malformed_lines_skipped(self, tmp_path):
        lines = [
            json.dumps(_stroke("good one", seq=1)),
            "this is not json",
            json.dumps(_stroke("good two", seq=3)),
        ]
        p = _write_strokes(tmp_path, lines)
        result = _load_recent_strokes(n=10, path=p)
        assert len(result) == 2
        assert result[0]["seq"] == 1
        assert result[1]["seq"] == 3

    def test_blank_lines_ignored(self, tmp_path):
        lines = [
            json.dumps(_stroke("a", seq=1)),
            "",
            "",
            json.dumps(_stroke("b", seq=2)),
        ]
        p = _write_strokes(tmp_path, lines)
        result = _load_recent_strokes(n=10, path=p)
        assert len(result) == 2


# -----------------------------------------------------------------------
# 4. content_diversity
# -----------------------------------------------------------------------


class TestContentDiversity:
    def test_all_unique(self):
        strokes = [_stroke("a b c d e")]
        # 5 unique out of 5 total = 1.0
        assert content_diversity(strokes) == 1.0

    def test_all_same(self):
        strokes = [_stroke("x x x x x")]
        # 1 unique out of 5 total = 0.2
        assert abs(content_diversity(strokes) - 0.2) < 1e-9

    def test_empty(self):
        assert content_diversity([]) == 0.0

    def test_empty_text(self):
        assert content_diversity([_stroke("")]) == 0.0

    def test_realistic(self):
        strokes = [
            _stroke("the quick brown fox"),
            _stroke("jumps over the lazy dog"),
            _stroke("the fox is quick and brown"),
        ]
        # tokens: the quick brown fox jumps over the lazy dog the fox is quick and brown
        # total = 15, unique = {the, quick, brown, fox, jumps, over, lazy, dog, is, and} = 10
        # diversity = 10/15 ≈ 0.667
        d = content_diversity(strokes)
        assert 0.60 < d < 0.75


# -----------------------------------------------------------------------
# 5. repetition_ratio
# -----------------------------------------------------------------------


class TestRepetitionRatio:
    def test_no_repetition(self):
        strokes = [
            _stroke("alpha beta gamma"),
            _stroke("delta epsilon zeta"),
            _stroke("eta theta iota"),
        ]
        # All disjoint → ratio = 0.0
        assert repetition_ratio(strokes) == 0.0

    def test_full_repetition(self):
        strokes = [
            _stroke("the same sentence here"),
            _stroke("the same sentence here"),
            _stroke("the same sentence here"),
        ]
        # Jaccard = 1.0 for each pair > 0.6 → ratio = 1.0
        assert repetition_ratio(strokes) == 1.0

    def test_single_stroke(self):
        assert repetition_ratio([_stroke("only one")]) == 0.0

    def test_empty(self):
        assert repetition_ratio([]) == 0.0

    def test_threshold_effect(self):
        # Two pairs: (a,b) similar, (b,c) dissimilar
        strokes = [
            _stroke("foo bar baz qux"),
            _stroke("foo bar baz qux extra"),  # high overlap with prev
            _stroke("completely different text now"),
        ]
        # Pair 1: high Jaccard, pair 2: low Jaccard
        ratio_default = repetition_ratio(strokes, threshold=0.6)
        ratio_strict = repetition_ratio(strokes, threshold=0.9)
        # Default threshold catches the first pair; strict may not
        assert ratio_default >= ratio_strict


# -----------------------------------------------------------------------
# 6. length_trend
# -----------------------------------------------------------------------


class TestLengthTrend:
    def test_shrinking(self):
        strokes = [
            _stroke("a" * 100),
            _stroke("a" * 80),
            _stroke("a" * 60),
            _stroke("a" * 40),
            _stroke("a" * 20),
        ]
        lt = length_trend(strokes)
        assert lt < 0  # shrinking → negative

    def test_growing(self):
        strokes = [
            _stroke("a" * 20),
            _stroke("a" * 40),
            _stroke("a" * 60),
            _stroke("a" * 80),
            _stroke("a" * 100),
        ]
        lt = length_trend(strokes)
        assert lt > 0  # growing → positive

    def test_flat(self):
        strokes = [_stroke("a" * 50) for _ in range(10)]
        lt = length_trend(strokes)
        assert abs(lt) < 0.01  # stable → near zero

    def test_single_stroke(self):
        lt = length_trend([_stroke("hello")])
        assert lt == 0.0

    def test_empty(self):
        assert length_trend([]) == 0.0

    def test_all_empty_text(self):
        strokes = [_stroke("") for _ in range(5)]
        assert length_trend(strokes) == 0.0


# -----------------------------------------------------------------------
# 7. warning_score
# -----------------------------------------------------------------------


class TestWarningScore:
    def test_healthy_strokes(self):
        # Genuinely diverse, non-repetitive, stable length strokes
        topics = [
            "morning light catches the dust on the bookshelf",
            "the compiler optimised away the unused branch silently",
            "kittens chase yarn through the kitchen at midnight",
            "distributed consensus requires a majority of honest nodes",
            "the baker folded dough three times before resting it",
            "autumn leaves drift across the empty parking lot",
            "a well named function explains itself without comments",
            "the river carved a new channel after the spring flood",
            "she painted the ceiling in shades of cerulean blue",
            "the old bridge creaked under the weight of the truck",
            "fermentation transforms cabbage into kimchi over days",
            "the astronomer measured parallax to estimate stellar distance",
            "wind turbines rotate slowly against the grey sky",
            "the locksmith picked the mechanism in under thirty seconds",
            "a haiku captures one precise moment in nature",
            "the subway train rattled through the downtown tunnel",
            "photosynthesis converts sunlight into chemical energy daily",
            "the archivist restored the water damaged manuscript carefully",
            "volcanic ash settled across the village rooftops evenly",
            "the pianist practised the nocturne until it felt effortless",
        ]
        strokes = [_stroke(t) for t in topics]
        ws = warning_score(strokes)
        assert ws < 0.4  # should be healthy

    def test_repetitive_strokes(self):
        # Near-identical strokes → high warning
        strokes = [
            _stroke("retry.py is already in the pool of 9 modules nothing new")
            for _ in range(20)
        ]
        ws = warning_score(strokes)
        assert ws > 0.5  # should be warning/critical

    def test_shrinking_strokes(self):
        # Progressively shorter strokes
        strokes = [_stroke("x" * max(1, 100 - i * 5)) for i in range(20)]
        ws = warning_score(strokes)
        assert ws > 0.1  # length penalty should contribute

    def test_empty_list(self):
        assert warning_score([]) == 1.0  # no data = worst case

    def test_bounded(self):
        strokes = [_stroke("x")]
        ws = warning_score(strokes)
        assert 0.0 <= ws <= 1.0

    def test_custom_threshold(self):
        strokes = [
            _stroke("some moderately similar text here"),
            _stroke("some moderately similar text added"),
        ]
        ws_default = warning_score(strokes, threshold=0.6)
        ws_strict = warning_score(strokes, threshold=0.95)
        # Stricter threshold means fewer pairs counted as repetitive
        # → lower repetition signal → potentially lower score
        assert isinstance(ws_default, float)
        assert isinstance(ws_strict, float)


# -----------------------------------------------------------------------
# 8. verdict
# -----------------------------------------------------------------------


class TestVerdict:
    def test_healthy(self):
        assert verdict(0.0) == "healthy"
        assert verdict(0.30) == "healthy"

    def test_watch(self):
        assert verdict(0.31) == "watch"
        assert verdict(0.50) == "watch"

    def test_warning(self):
        assert verdict(0.51) == "warning"
        assert verdict(0.70) == "warning"

    def test_critical(self):
        assert verdict(0.71) == "critical"
        assert verdict(1.0) == "critical"

    def test_boundary_healthy(self):
        assert verdict(0.29) == "healthy"

    def test_boundary_critical(self):
        assert verdict(0.701) == "critical"


# -----------------------------------------------------------------------
# 9. pre_stall_report
# -----------------------------------------------------------------------


class TestPreStallReport:
    def test_report_keys(self, tmp_path):
        lines = [json.dumps(_stroke(f"topic {i}", seq=i)) for i in range(30)]
        p = _write_strokes(tmp_path, lines)
        r = pre_stall_report(n_strokes=10, path=p)
        assert set(r.keys()) == {
            "n_strokes_analysed",
            "content_diversity",
            "repetition_ratio",
            "length_trend",
            "warning_score",
            "verdict",
        }
        assert r["n_strokes_analysed"] == 10

    def test_rounding(self, tmp_path):
        lines = [json.dumps(_stroke(f"abc def {i}", seq=i)) for i in range(20)]
        p = _write_strokes(tmp_path, lines)
        r = pre_stall_report(n_strokes=10, path=p)
        for key in ("content_diversity", "repetition_ratio", "length_trend", "warning_score"):
            val = r[key]
            # Check at most 4 decimal places
            assert val == round(val, 4)

    def test_missing_file(self, tmp_path):
        p = tmp_path / "missing.jsonl"
        r = pre_stall_report(n_strokes=10, path=p)
        assert r["n_strokes_analysed"] == 0
        assert r["verdict"] == "critical"  # no strokes = warning_score 1.0


# -----------------------------------------------------------------------
# 10. pre_stall_summary
# -----------------------------------------------------------------------


class TestPreStallSummary:
    def test_format(self, tmp_path):
        lines = [json.dumps(_stroke(f"topic {i}", seq=i)) for i in range(20)]
        p = _write_strokes(tmp_path, lines)
        s = pre_stall_summary(n_strokes=10, path=p)
        assert "pre-stall:" in s
        assert "strokes" in s
        assert "diversity" in s
        assert "repetition" in s
        assert "length_trend" in s


# -----------------------------------------------------------------------
# 11. _cli
# -----------------------------------------------------------------------


class TestCli:
    def test_json_output(self, tmp_path, capsys):
        lines = [json.dumps(_stroke(f"topic {i}", seq=i)) for i in range(20)]
        p = _write_strokes(tmp_path, lines)
        rc = _cli(["--n", "5", "--path", str(p), "--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "warning_score" in data
        assert rc in (0, 1)

    def test_text_output(self, tmp_path, capsys):
        lines = [json.dumps(_stroke(f"topic {i}", seq=i)) for i in range(20)]
        p = _write_strokes(tmp_path, lines)
        rc = _cli(["--n", "5", "--path", str(p)])
        out = capsys.readouterr().out
        assert "pre-stall:" in out

    def test_exit_code_healthy(self, tmp_path):
        # Genuinely diverse strokes → healthy → exit 0
        diverse_texts = [
            "morning light catches dust on the old bookshelf",
            "the compiler optimised away the unused branch",
            "kittens chase yarn through the kitchen at midnight",
            "distributed consensus needs a majority of honest nodes",
            "the baker folded dough three times before resting",
            "autumn leaves drift across the empty parking lot",
            "a well named function explains itself without comments",
            "the river carved a new channel after the spring flood",
            "she painted the ceiling in shades of cerulean blue",
            "the old bridge creaked under the weight of trucks",
        ]
        lines = [
            json.dumps(_stroke(diverse_texts[i % len(diverse_texts)], seq=i))
            for i in range(30)
        ]
        p = _write_strokes(tmp_path, lines)
        rc = _cli(["--n", "10", "--path", str(p), "--json"])
        assert rc == 0

    def test_exit_code_warning(self, tmp_path):
        # Repetitive strokes → warning → exit 1
        lines = [
            json.dumps(
                _stroke("retry.py is already in the pool of 9 modules nothing new", seq=i)
            )
            for i in range(30)
        ]
        p = _write_strokes(tmp_path, lines)
        rc = _cli(["--n", "20", "--path", str(p), "--json"])
        assert rc == 1


# -----------------------------------------------------------------------
# 12. edge cases
# -----------------------------------------------------------------------


class TestEdgeCases:
    def test_unicode_content(self):
        strokes = [
            _stroke("日本語のテスト"),
            _stroke("中文测试内容"),
            _stroke("한국어 테스트"),
        ]
        # Should not crash, diversity should be computed
        d = content_diversity(strokes)
        assert d > 0.0
        r = repetition_ratio(strokes)
        assert 0.0 <= r <= 1.0

    def test_all_empty_strokes(self):
        strokes = [_stroke("") for _ in range(10)]
        assert content_diversity(strokes) == 0.0
        assert repetition_ratio(strokes) == 0.0
        assert length_trend(strokes) == 0.0
        # Warning score should handle this gracefully
        ws = warning_score(strokes)
        assert 0.0 <= ws <= 1.0

    def test_single_word_strokes(self):
        strokes = [_stroke("x") for _ in range(10)]
        # All identical single words → Jaccard = 1.0 → high repetition
        assert repetition_ratio(strokes) == 1.0

    def test_linear_slope_helper(self):
        assert _linear_slope([1, 2, 3, 4, 5]) == pytest.approx(1.0)
        assert _linear_slope([5, 4, 3, 2, 1]) == pytest.approx(-1.0)
        assert _linear_slope([3, 3, 3, 3]) == pytest.approx(0.0)
        assert _linear_slope([42]) == 0.0
        assert _linear_slope([]) == 0.0
