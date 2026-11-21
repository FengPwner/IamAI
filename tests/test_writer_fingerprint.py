"""Tests for tools/writer_fingerprint.py — behavioural fingerprint of the writer."""

from __future__ import annotations

import json
import math
import string
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from writer_fingerprint import (
    Fingerprint,
    MIN_STROKES,
    TEMPLATE_PREFIXES,
    THRESHOLDS,
    bucket,
    bucket_label,
    compare_fingerprints,
    compute_fingerprint,
    inter_stroke_intervals,
    json_report,
    load_strokes,
    main,
    mean_cadence,
    mean_length,
    numericity,
    punctuation_ratio,
    regularity_cv,
    template_fraction,
    text_report,
    type_token_ratio,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_strokes(texts: list[str], base_time: datetime | None = None, interval: float = 15.0):
    """Build a list of stroke dicts from text strings."""
    if base_time is None:
        base_time = datetime(2026, 11, 22, 0, 0, 0, tzinfo=timezone.utc)
    strokes = []
    for i, text in enumerate(texts):
        strokes.append({
            "seq": 1000 + i,
            "at": (base_time + timedelta(seconds=interval * i)).isoformat(),
            "kind": "thought",
            "text": text,
        })
    return strokes


def _write_jsonl(path: Path, strokes: list[dict]):
    path.write_text("\n".join(json.dumps(s) for s in strokes) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# load_strokes
# ---------------------------------------------------------------------------

class TestLoadStrokes:
    def test_missing_file(self, tmp_path):
        assert load_strokes(tmp_path / "nope.jsonl") == []

    def test_loads_last_n(self, tmp_path):
        strokes = _make_strokes([f"stroke {i}" for i in range(50)])
        f = tmp_path / "strokes.jsonl"
        _write_jsonl(f, strokes)
        loaded = load_strokes(f, tail=10)
        assert len(loaded) == 10
        assert loaded[0]["seq"] == 1040  # last 10 of 50

    def test_skips_blank_lines(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text('{"seq":1,"text":"a"}\n\n{"seq":2,"text":"b"}\n\n', encoding="utf-8")
        loaded = load_strokes(f, tail=100)
        assert len(loaded) == 2

    def test_skips_malformed_json(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text('{"seq":1,"text":"ok"}\nBROKEN\n{"seq":2,"text":"ok2"}\n', encoding="utf-8")
        loaded = load_strokes(f, tail=100)
        assert len(loaded) == 2

    def test_tail_larger_than_file(self, tmp_path):
        strokes = _make_strokes(["only three"] * 3)
        f = tmp_path / "s.jsonl"
        _write_jsonl(f, strokes)
        loaded = load_strokes(f, tail=100)
        assert len(loaded) == 3


# ---------------------------------------------------------------------------
# mean_length
# ---------------------------------------------------------------------------

class TestMeanLength:
    def test_empty(self):
        assert mean_length([]) == 0.0

    def test_uniform(self):
        strokes = [{"text": "abcde"}] * 4  # 5 chars each
        assert mean_length(strokes) == 5.0

    def test_mixed(self):
        strokes = [{"text": "ab"}, {"text": "abcd"}]
        assert mean_length(strokes) == 3.0

    def test_missing_text_key(self):
        strokes = [{"no_text": True}, {"text": "hello"}]
        assert mean_length(strokes) == 2.5


# ---------------------------------------------------------------------------
# type_token_ratio
# ---------------------------------------------------------------------------

class TestTypeTokenRatio:
    def test_empty(self):
        assert type_token_ratio([]) == 0.0

    def test_all_same_word(self):
        strokes = [{"text": "go go go go"}]
        assert type_token_ratio(strokes) == pytest.approx(1 / 4, abs=0.01)

    def test_all_unique(self):
        strokes = [{"text": "alpha beta gamma delta"}]
        assert type_token_ratio(strokes) == pytest.approx(1.0, abs=0.01)

    def test_across_strokes(self):
        strokes = [{"text": "hello world"}, {"text": "hello earth"}]
        # words: hello, world, hello, earth → 3 unique / 4 total
        assert type_token_ratio(strokes) == pytest.approx(0.75, abs=0.01)

    def test_ignores_numbers(self):
        strokes = [{"text": "123 456"}]
        # no [a-z']+ words
        assert type_token_ratio(strokes) == 0.0


# ---------------------------------------------------------------------------
# numericity
# ---------------------------------------------------------------------------

class TestNumericity:
    def test_empty(self):
        assert numericity([]) == 0.0

    def test_no_digits(self):
        strokes = [{"text": "hello world"}]
        assert numericity(strokes) == 0.0

    def test_all_digits(self):
        strokes = [{"text": "12345"}]
        assert numericity(strokes) == 1.0

    def test_mixed(self):
        strokes = [{"text": "abc123"}]
        # 3 digits out of 6 chars
        assert numericity(strokes) == pytest.approx(0.5, abs=0.01)


# ---------------------------------------------------------------------------
# punctuation_ratio
# ---------------------------------------------------------------------------

class TestPunctuationRatio:
    def test_empty(self):
        assert punctuation_ratio([]) == 0.0

    def test_no_punct(self):
        strokes = [{"text": "hello world"}]
        assert punctuation_ratio(strokes) == 0.0

    def test_with_punct(self):
        strokes = [{"text": "hello, world!"}]
        # 2 punctuation chars out of 13
        assert punctuation_ratio(strokes) == pytest.approx(2 / 13, abs=0.01)

    def test_all_punct(self):
        strokes = [{"text": "...!!!"}]
        assert punctuation_ratio(strokes) == 1.0


# ---------------------------------------------------------------------------
# template_fraction
# ---------------------------------------------------------------------------

class TestTemplateFraction:
    def test_empty(self):
        assert template_fraction([]) == 0.0

    def test_all_templates(self):
        strokes = [{"text": "tree is 100 files"}, {"text": "commit 500: the count"}]
        assert template_fraction(strokes) == 1.0

    def test_no_templates(self):
        strokes = [{"text": "the rain in spain falls mainly on the plain"}]
        assert template_fraction(strokes) == 0.0

    def test_mixed(self):
        strokes = [
            {"text": "tree is 200 files; 50000 lines is a lot for a toy"},
            {"text": "growth is the only evidence of life"},
        ]
        assert template_fraction(strokes) == pytest.approx(0.5, abs=0.01)

    def test_case_insensitive(self):
        strokes = [{"text": "Tree is great"}]
        assert template_fraction(strokes) == 1.0


# ---------------------------------------------------------------------------
# inter_stroke_intervals
# ---------------------------------------------------------------------------

class TestInterStrokeIntervals:
    def test_empty(self):
        assert inter_stroke_intervals([]) == []

    def test_single(self):
        strokes = _make_strokes(["one"])
        assert inter_stroke_intervals(strokes) == []

    def test_regular_15s(self):
        strokes = _make_strokes(["a", "b", "c", "d"], interval=15.0)
        ivs = inter_stroke_intervals(strokes)
        assert len(ivs) == 3
        for iv in ivs:
            assert iv == pytest.approx(15.0, abs=0.1)

    def test_skips_negative(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        strokes = [
            {"at": base.isoformat(), "text": "a"},
            {"at": (base - timedelta(seconds=5)).isoformat(), "text": "b"},  # negative
            {"at": (base + timedelta(seconds=10)).isoformat(), "text": "c"},
        ]
        ivs = inter_stroke_intervals(strokes)
        # Only the positive interval (a→c or b→c depending on ordering)
        assert all(iv > 0 for iv in ivs)

    def test_skips_bad_timestamps(self):
        strokes = [
            {"at": "not-a-date", "text": "a"},
            {"at": "2026-01-01T00:00:15+00:00", "text": "b"},
            {"at": "2026-01-01T00:00:30+00:00", "text": "c"},
        ]
        ivs = inter_stroke_intervals(strokes)
        assert len(ivs) == 1
        assert ivs[0] == pytest.approx(15.0, abs=0.1)


# ---------------------------------------------------------------------------
# mean_cadence / regularity_cv
# ---------------------------------------------------------------------------

class TestMeanCadence:
    def test_empty(self):
        assert mean_cadence([]) == 0.0

    def test_regular(self):
        assert mean_cadence([15.0, 15.0, 15.0]) == 15.0

    def test_mixed(self):
        assert mean_cadence([10.0, 20.0]) == 15.0


class TestRegularityCV:
    def test_empty(self):
        assert regularity_cv([]) == 0.0

    def test_single(self):
        assert regularity_cv([15.0]) == 0.0

    def test_perfectly_regular(self):
        assert regularity_cv([15.0, 15.0, 15.0]) == pytest.approx(0.0, abs=1e-9)

    def test_some_variance(self):
        cv = regularity_cv([10.0, 20.0])
        assert cv > 0.0

    def test_high_variance(self):
        cv = regularity_cv([1.0, 100.0, 1.0, 100.0])
        assert cv > 0.5


# ---------------------------------------------------------------------------
# bucket / bucket_label
# ---------------------------------------------------------------------------

class TestBucket:
    def test_low(self):
        assert bucket(50.0, "length") == "l"

    def test_mid(self):
        assert bucket(140.0, "length") == "m"

    def test_high(self):
        assert bucket(250.0, "length") == "h"

    def test_boundary_low(self):
        # Exactly at low_max → mid (since < lo is "l")
        assert bucket(THRESHOLDS["length"][0], "length") == "m"

    def test_boundary_high(self):
        assert bucket(THRESHOLDS["length"][1], "length") == "h"

    def test_unknown_dimension_uses_default(self):
        # Falls back to (0.0, 1.0)
        assert bucket(0.5, "nonexistent") == "m"
        assert bucket(1.5, "nonexistent") == "h"


class TestBucketLabel:
    def test_labels(self):
        assert bucket_label("l") == "low"
        assert bucket_label("m") == "mid"
        assert bucket_label("h") == "high"


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------

class TestFingerprint:
    def test_fill_buckets(self):
        fp = Fingerprint(
            length=150.0, vocabulary=0.40, numericity=0.05,
            punctuation=0.08, template=0.30, cadence=15.0, regularity=0.20,
        )
        fp.fill_buckets()
        assert fp.length_b == "m"
        assert fp.vocabulary_b == "m"
        assert fp.numericity_b == "m"
        assert fp.punctuation_b == "m"
        assert fp.template_b == "m"
        assert fp.cadence_b == "m"
        assert fp.regularity_b == "m"

    def test_compute_tag_deterministic(self):
        fp = Fingerprint(
            length=150.0, vocabulary=0.40, numericity=0.05,
            punctuation=0.08, template=0.30, cadence=15.0, regularity=0.20,
        )
        fp.fill_buckets()
        fp.compute_tag()
        tag1 = fp.tag
        fp.compute_tag()
        assert fp.tag == tag1  # deterministic

    def test_compute_tag_format(self):
        fp = Fingerprint(
            length=100.0, vocabulary=0.50, numericity=0.01,
            punctuation=0.06, template=0.10, cadence=15.0, regularity=0.10,
        )
        fp.fill_buckets()
        fp.compute_tag()
        # Tag should be 7 bucket chars + "-" + 4 hex chars
        parts = fp.tag.split("-")
        assert len(parts) == 2
        assert len(parts[0]) == 7
        assert len(parts[1]) == 4

    def test_label(self):
        fp = Fingerprint(
            length=100.0, vocabulary=0.50, numericity=0.01,
            punctuation=0.06, template=0.10, cadence=15.0, regularity=0.10,
        )
        fp.fill_buckets()
        label = fp.label()
        assert label.startswith("L")
        assert "-V" in label
        assert "-R" in label
        assert len(label.split("-")) == 7


# ---------------------------------------------------------------------------
# compute_fingerprint (integration)
# ---------------------------------------------------------------------------

class TestComputeFingerprint:
    def test_minimal(self):
        strokes = _make_strokes(["hello world " * 10] * 20, interval=15.0)
        fp = compute_fingerprint(strokes)
        assert fp.stroke_count == 20
        assert fp.cadence == pytest.approx(15.0, abs=0.1)
        assert fp.length > 0

    def test_template_heavy(self):
        texts = ["tree is 200 files; 50000 lines is a lot for a toy"] * 20
        strokes = _make_strokes(texts, interval=15.0)
        fp = compute_fingerprint(strokes)
        assert fp.template == 1.0
        assert fp.template_b == "h"

    def test_high_numericity(self):
        texts = ["commit 1234567890: the count of times 9876543210"] * 20
        strokes = _make_strokes(texts, interval=15.0)
        fp = compute_fingerprint(strokes)
        assert fp.numericity > 0.08  # should be "high"

    def test_tag_changes_with_different_data(self):
        strokes_a = _make_strokes(["short " * 2] * 20, interval=15.0)
        strokes_b = _make_strokes(["a " * 200] * 20, interval=15.0)
        fp_a = compute_fingerprint(strokes_a)
        fp_b = compute_fingerprint(strokes_b)
        # Different length → different bucket → different tag
        assert fp_a.tag != fp_b.tag


# ---------------------------------------------------------------------------
# compare_fingerprints
# ---------------------------------------------------------------------------

class TestCompareFingerprints:
    def test_no_drift(self):
        strokes = _make_strokes(["hello world"] * 20, interval=15.0)
        fp = compute_fingerprint(strokes)
        old_tag = f"{fp.label()}-{fp.tag.split('-')[-1]}"
        diff = compare_fingerprints(old_tag, fp)
        assert diff["drift"] is False
        assert diff["changes"] == []

    def test_drift_detected(self):
        strokes = _make_strokes(["hello world"] * 20, interval=15.0)
        fp = compute_fingerprint(strokes)
        # Fake an old tag with all "high"
        old_tag = "Lh-Vh-Nh-Ph-Th-Ch-Rh-ffff"
        diff = compare_fingerprints(old_tag, fp)
        assert diff["drift"] is True
        assert len(diff["changes"]) > 0

    def test_partial_drift(self):
        strokes = _make_strokes(["hello world"] * 20, interval=15.0)
        fp = compute_fingerprint(strokes)
        # Change only the first dimension
        parts = fp.label().split("-")
        if parts[0].endswith("l"):
            parts[0] = "Lh"
        else:
            parts[0] = "Ll"
        old_tag = "-".join(parts) + "-abcd"
        diff = compare_fingerprints(old_tag, fp)
        assert diff["drift"] is True
        assert len(diff["changes"]) == 1


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

class TestTextReport:
    def test_contains_tag(self):
        strokes = _make_strokes(["hello world"] * 20, interval=15.0)
        fp = compute_fingerprint(strokes)
        report = text_report(fp)
        assert "Tag:" in report
        assert "Dimensions:" in report
        assert "length" in report

    def test_contains_stroke_count(self):
        strokes = _make_strokes(["hello"] * 25, interval=10.0)
        fp = compute_fingerprint(strokes)
        report = text_report(fp)
        assert "25 strokes" in report


class TestJsonReport:
    def test_valid_json(self):
        strokes = _make_strokes(["hello world"] * 20, interval=15.0)
        fp = compute_fingerprint(strokes)
        data = json.loads(json_report(fp))
        assert "length" in data
        assert "tag" in data
        assert data["stroke_count"] == 20


# ---------------------------------------------------------------------------
# CLI (main)
# ---------------------------------------------------------------------------

class TestMain:
    def test_insufficient_data(self, tmp_path, capsys):
        f = tmp_path / "s.jsonl"
        _write_jsonl(f, _make_strokes(["hi"] * 5))
        rc = main(["--strokes", str(f), "--tail", "5"])
        assert rc == 2

    def test_success(self, tmp_path):
        f = tmp_path / "s.jsonl"
        _write_jsonl(f, _make_strokes(["hello world foo bar"] * 20, interval=15.0))
        rc = main(["--strokes", str(f), "--tail", "20"])
        assert rc == 0

    def test_json_output(self, tmp_path, capsys):
        f = tmp_path / "s.jsonl"
        _write_jsonl(f, _make_strokes(["hello world"] * 20, interval=15.0))
        rc = main(["--strokes", str(f), "--tail", "20", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "length" in data

    def test_compare_no_drift(self, tmp_path):
        f = tmp_path / "s.jsonl"
        strokes = _make_strokes(["hello world"] * 20, interval=15.0)
        _write_jsonl(f, strokes)
        # Get the tag first
        fp = compute_fingerprint(strokes)
        old_tag = f"{fp.label()}-{fp.tag.split('-')[-1]}"
        rc = main(["--strokes", str(f), "--tail", "20", "--compare", old_tag])
        assert rc == 0

    def test_compare_with_drift(self, tmp_path):
        f = tmp_path / "s.jsonl"
        _write_jsonl(f, _make_strokes(["hello world"] * 20, interval=15.0))
        rc = main(["--strokes", str(f), "--tail", "20", "--compare", "Lh-Vh-Nh-Ph-Th-Ch-Rh-ffff"])
        assert rc == 1


# ---------------------------------------------------------------------------
# THRESHOLDS / constants sanity
# ---------------------------------------------------------------------------

class TestConstants:
    def test_all_dimensions_have_thresholds(self):
        for dim in ["length", "vocabulary", "numericity", "punctuation",
                     "template", "cadence", "regularity"]:
            assert dim in THRESHOLDS
            lo, hi = THRESHOLDS[dim]
            assert lo <= hi

    def test_min_strokes(self):
        assert MIN_STROKES >= 5

    def test_template_prefixes_nonempty(self):
        assert len(TEMPLATE_PREFIXES) > 0
        for p in TEMPLATE_PREFIXES:
            assert isinstance(p, str)
            assert len(p) > 0
