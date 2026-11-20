"""tests for stroke_sequence_integrity module.

covers:
- clean log detection
- duplicate sequence detection
- missing sequence detection
- non-monotonic sequence detection
- temporal inversion detection
- negative gap detection
- large gap detection
- empty log handling
- missing file handling
- tail parameter
- JSON output format
- report formatting
- end-to-end with synthetic data
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stroke_sequence_integrity import (
    IntegrityReport,
    check_gaps,
    check_monotonic,
    check_temporal_order,
    format_report,
    load_strokes,
    parse_iso_timestamp,
    verify_integrity,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_stroke(seq, at="2026-01-01T00:00:00+00:00", kind="thought", text="test"):
    return {"seq": seq, "at": at, "kind": kind, "text": text}


def write_strokes_file(strokes, tmpdir=None):
    """Write a list of stroke dicts to a temp JSONL file, return Path."""
    if tmpdir is None:
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
    else:
        path = os.path.join(tmpdir, "strokes.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for s in strokes:
            f.write(json.dumps(s) + "\n")
    return Path(path)


def iso(minutes_offset):
    """Generate ISO timestamp at given minute offset from epoch."""
    return f"2026-01-01T00:{minutes_offset:02d}:00+00:00"


# ---------------------------------------------------------------------------
# parse_iso_timestamp
# ---------------------------------------------------------------------------

class TestParseIsoTimestamp:
    def test_valid_utc(self):
        dt = parse_iso_timestamp("2026-01-01T12:00:00+00:00")
        assert dt is not None
        assert dt.hour == 12

    def test_valid_z_suffix(self):
        dt = parse_iso_timestamp("2026-01-01T12:00:00Z")
        assert dt is not None

    def test_empty_string(self):
        assert parse_iso_timestamp("") is None

    def test_none_input(self):
        assert parse_iso_timestamp(None) is None

    def test_invalid_format(self):
        assert parse_iso_timestamp("not-a-date") is None

    def test_timezone_offset(self):
        dt = parse_iso_timestamp("2026-01-01T12:00:00+08:00")
        assert dt is not None


# ---------------------------------------------------------------------------
# load_strokes
# ---------------------------------------------------------------------------

class TestLoadStrokes:
    def test_load_basic(self, tmp_path):
        strokes = [make_stroke(1), make_stroke(2), make_stroke(3)]
        path = write_strokes_file(strokes, str(tmp_path))
        loaded = load_strokes(path)
        assert len(loaded) == 3
        assert loaded[0]["seq"] == 1

    def test_load_with_tail(self, tmp_path):
        strokes = [make_stroke(i) for i in range(1, 11)]
        path = write_strokes_file(strokes, str(tmp_path))
        loaded = load_strokes(path, tail=3)
        assert len(loaded) == 3
        assert loaded[0]["seq"] == 8

    def test_load_tail_zero(self, tmp_path):
        strokes = [make_stroke(1), make_stroke(2)]
        path = write_strokes_file(strokes, str(tmp_path))
        loaded = load_strokes(path, tail=0)
        # tail=0 is falsy, so all strokes loaded
        assert len(loaded) == 2

    def test_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_strokes(Path("/nonexistent/strokes.jsonl"))

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        loaded = load_strokes(path)
        assert len(loaded) == 0

    def test_malformed_lines_skipped(self, tmp_path):
        path = tmp_path / "bad.jsonl"
        path.write_text('{"seq": 1}\nnot json\n{"seq": 2}\n')
        loaded = load_strokes(path)
        assert len(loaded) == 2

    def test_blank_lines_skipped(self, tmp_path):
        path = tmp_path / "blanks.jsonl"
        path.write_text('{"seq": 1}\n\n{"seq": 2}\n\n')
        loaded = load_strokes(path)
        assert len(loaded) == 2


# ---------------------------------------------------------------------------
# check_monotonic
# ---------------------------------------------------------------------------

class TestCheckMonotonic:
    def test_clean_sequence(self):
        strokes = [make_stroke(i) for i in range(1, 6)]
        dupes, non_mono = check_monotonic(strokes)
        assert dupes == []
        assert non_mono == []

    def test_duplicate_seq(self):
        strokes = [make_stroke(1), make_stroke(2), make_stroke(2), make_stroke(3)]
        dupes, non_mono = check_monotonic(strokes)
        assert 2 in dupes

    def test_non_monotonic(self):
        strokes = [make_stroke(1), make_stroke(3), make_stroke(2), make_stroke(4)]
        dupes, non_mono = check_monotonic(strokes)
        assert len(non_mono) == 1
        assert non_mono[0] == (3, 2)

    def test_multiple_non_monotonic(self):
        strokes = [make_stroke(1), make_stroke(5), make_stroke(3), make_stroke(6), make_stroke(2)]
        dupes, non_mono = check_monotonic(strokes)
        assert len(non_mono) == 2

    def test_missing_seq_field(self):
        strokes = [{"at": "2026-01-01T00:00:00+00:00", "kind": "thought"}, make_stroke(1)]
        dupes, non_mono = check_monotonic(strokes)
        assert dupes == []
        assert non_mono == []

    def test_single_stroke(self):
        strokes = [make_stroke(42)]
        dupes, non_mono = check_monotonic(strokes)
        assert dupes == []
        assert non_mono == []


# ---------------------------------------------------------------------------
# check_gaps
# ---------------------------------------------------------------------------

class TestCheckGaps:
    def test_no_gaps(self):
        seen = {1, 2, 3, 4, 5}
        missing = check_gaps(1, 5, seen)
        assert missing == []

    def test_single_gap(self):
        seen = {1, 2, 4, 5}
        missing = check_gaps(1, 5, seen)
        assert missing == [3]

    def test_multiple_gaps(self):
        seen = {1, 3, 5, 7}
        missing = check_gaps(1, 7, seen)
        assert missing == [2, 4, 6]

    def test_first_equals_last(self):
        seen = {5}
        missing = check_gaps(5, 5, seen)
        assert missing == []

    def test_first_greater_than_last(self):
        missing = check_gaps(10, 5, set())
        assert missing == []

    def test_large_gap_capped(self):
        # only {1} present, range is 1..2000
        seen = {1}
        missing = check_gaps(1, 2000, seen)
        assert len(missing) == 1000  # capped


# ---------------------------------------------------------------------------
# check_temporal_order
# ---------------------------------------------------------------------------

class TestCheckTemporalOrder:
    def test_clean_ordering(self):
        strokes = [
            make_stroke(1, "2026-01-01T00:00:00+00:00"),
            make_stroke(2, "2026-01-01T00:01:00+00:00"),
            make_stroke(3, "2026-01-01T00:02:00+00:00"),
        ]
        inv, neg, large = check_temporal_order(strokes)
        assert inv == []
        assert neg == []
        assert large == []

    def test_temporal_inversion(self):
        strokes = [
            make_stroke(1, "2026-01-01T00:02:00+00:00"),
            make_stroke(2, "2026-01-01T00:01:00+00:00"),  # earlier than prev
        ]
        inv, neg, large = check_temporal_order(strokes)
        assert len(inv) == 1
        assert len(neg) == 1

    def test_large_gap_detected(self):
        strokes = [
            make_stroke(1, "2026-01-01T00:00:00+00:00"),
            make_stroke(2, "2026-01-03T00:00:00+00:00"),  # 48 hours later
        ]
        inv, neg, large = check_temporal_order(strokes)
        assert len(large) == 1
        assert large[0][0] == 2  # seq of the stroke after the gap

    def test_zero_gap_is_fine(self):
        strokes = [
            make_stroke(1, "2026-01-01T00:00:00+00:00"),
            make_stroke(2, "2026-01-01T00:00:00+00:00"),  # same time
        ]
        inv, neg, large = check_temporal_order(strokes)
        assert inv == []
        assert neg == []

    def test_missing_timestamp_skipped(self):
        strokes = [
            make_stroke(1, "2026-01-01T00:00:00+00:00"),
            {"seq": 2, "kind": "thought"},  # no "at"
            make_stroke(3, "2026-01-01T00:05:00+00:00"),
        ]
        inv, neg, large = check_temporal_order(strokes)
        assert inv == []

    def test_empty_strokes(self):
        inv, neg, large = check_temporal_order([])
        assert inv == []
        assert neg == []
        assert large == []


# ---------------------------------------------------------------------------
# verify_integrity (integration)
# ---------------------------------------------------------------------------

class TestVerifyIntegrity:
    def test_clean_log(self, tmp_path):
        strokes = [
            make_stroke(i, f"2026-01-01T00:{i:02d}:00+00:00")
            for i in range(1, 6)
        ]
        path = write_strokes_file(strokes, str(tmp_path))
        report = verify_integrity(strokes_path=path)
        assert report.is_clean
        assert report.total_strokes == 5
        assert report.anomaly_count() == 0

    def test_log_with_duplicates(self, tmp_path):
        strokes = [
            make_stroke(1, "2026-01-01T00:00:00+00:00"),
            make_stroke(2, "2026-01-01T00:01:00+00:00"),
            make_stroke(2, "2026-01-01T00:02:00+00:00"),
            make_stroke(3, "2026-01-01T00:03:00+00:00"),
        ]
        path = write_strokes_file(strokes, str(tmp_path))
        report = verify_integrity(strokes_path=path)
        assert not report.is_clean
        assert 2 in report.duplicate_seqs

    def test_log_with_missing_seqs(self, tmp_path):
        strokes = [
            make_stroke(1, "2026-01-01T00:00:00+00:00"),
            make_stroke(3, "2026-01-01T00:02:00+00:00"),
            make_stroke(5, "2026-01-01T00:04:00+00:00"),
        ]
        path = write_strokes_file(strokes, str(tmp_path))
        report = verify_integrity(strokes_path=path)
        assert not report.is_clean
        assert 2 in report.missing_seqs
        assert 4 in report.missing_seqs

    def test_log_with_temporal_inversion(self, tmp_path):
        strokes = [
            make_stroke(1, "2026-01-01T00:02:00+00:00"),
            make_stroke(2, "2026-01-01T00:01:00+00:00"),
        ]
        path = write_strokes_file(strokes, str(tmp_path))
        report = verify_integrity(strokes_path=path)
        assert not report.is_clean
        assert len(report.temporal_inversions) == 1

    def test_missing_file(self):
        report = verify_integrity(strokes_path=Path("/nonexistent/file.jsonl"))
        assert not report.is_clean

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        report = verify_integrity(strokes_path=path)
        assert report.is_clean
        assert report.total_strokes == 0

    def test_tail_parameter(self, tmp_path):
        strokes = [
            make_stroke(i, f"2026-01-01T00:{i:02d}:00+00:00")
            for i in range(1, 11)
        ]
        path = write_strokes_file(strokes, str(tmp_path))
        report = verify_integrity(strokes_path=path, tail=5)
        assert report.total_strokes == 5
        assert report.first_seq == 6

    def test_large_gap_detected(self, tmp_path):
        strokes = [
            make_stroke(1, "2026-01-01T00:00:00+00:00"),
            make_stroke(2, "2026-01-05T00:00:00+00:00"),  # 4 days later
        ]
        path = write_strokes_file(strokes, str(tmp_path))
        report = verify_integrity(strokes_path=path)
        assert len(report.large_gaps) == 1

    def test_no_seq_fields(self, tmp_path):
        strokes = [{"at": "2026-01-01T00:00:00+00:00", "kind": "thought"}]
        path = write_strokes_file(strokes, str(tmp_path))
        report = verify_integrity(strokes_path=path)
        # no seqs at all means not clean
        assert not report.is_clean


# ---------------------------------------------------------------------------
# IntegrityReport
# ---------------------------------------------------------------------------

class TestIntegrityReport:
    def test_clean_report(self):
        r = IntegrityReport(total_strokes=10, first_seq=1, last_seq=10)
        assert r.anomaly_count() == 0

    def test_anomaly_count(self):
        r = IntegrityReport(
            duplicate_seqs=[2, 5],
            missing_seqs=[3],
            non_monotonic=[(4, 3)],
        )
        assert r.anomaly_count() == 4

    def test_to_dict(self):
        r = IntegrityReport(
            total_strokes=5,
            first_seq=1,
            last_seq=5,
            duplicate_seqs=[3],
        )
        d = r.to_dict()
        assert d["total_strokes"] == 5
        assert d["duplicate_seqs"] == [3]
        assert d["missing_count"] == 0
        assert "is_clean" in d

    def test_to_dict_missing_capped(self):
        r = IntegrityReport(missing_seqs=list(range(1, 200)))
        d = r.to_dict()
        assert len(d["missing_seqs"]) == 50  # capped
        assert d["missing_count"] == 199


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_clean_output(self):
        r = IntegrityReport(total_strokes=100, first_seq=1, last_seq=100)
        text = format_report(r)
        assert "CLEAN" in text
        assert "no anomalies" in text

    def test_anomaly_output(self):
        r = IntegrityReport(
            total_strokes=10,
            first_seq=1,
            last_seq=10,
            duplicate_seqs=[3],
            missing_seqs=[5, 7],
        )
        r.is_clean = False
        text = format_report(r)
        assert "ANOMALIES" in text
        assert "duplicates" in text
        assert "missing seqs" in text

    def test_large_gaps_shown(self):
        r = IntegrityReport(
            total_strokes=2,
            first_seq=1,
            last_seq=2,
            large_gaps=[(2, 172800.0)],
        )
        text = format_report(r)
        assert "large gaps" in text
