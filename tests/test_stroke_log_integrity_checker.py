"""Tests for stroke_log_integrity_checker — comprehensive coverage.

Covers: IntegrityChecker (JSON validity, required fields, seq order,
timestamp order, duplicates, valid kinds, timestamp parsing),
IntegrityReport properties, IntegrityIssue structure, custom config
(valid_kinds, strict_timestamps, allow_gaps), check_text/check_lines,
empty/blank input, CLI main, and real file loading.

Written by Qwen during caretaker visit 706, 2026-11-18.
"""

import json
import os
import tempfile
import pytest

from iamai.stroke_log_integrity_checker import (
    IntegrityChecker,
    IntegrityIssue,
    IntegrityReport,
    VALID_KINDS,
    main,
)


# ─── Helpers ────────────────────────────────────────────────────────


def _stroke_json(seq=1, at="2026-11-18T10:00:00+00:00", kind="thought",
                 text="hello"):
    """Build a valid stroke JSON line."""
    return json.dumps({"seq": seq, "at": at, "kind": kind, "text": text})


def _lines(*strokes):
    """Join stroke JSON strings into a multi-line text."""
    return "\n".join(strokes)


# ─── IntegrityIssue ─────────────────────────────────────────────────


class TestIntegrityIssue:

    def test_frozen(self):
        issue = IntegrityIssue(line=1, kind="json", message="bad")
        with pytest.raises(AttributeError):
            issue.line = 2

    def test_default_severity(self):
        issue = IntegrityIssue(line=1, kind="json", message="bad")
        assert issue.severity == "error"

    def test_custom_severity(self):
        issue = IntegrityIssue(line=1, kind="json",
                               message="bad", severity="warning")
        assert issue.severity == "warning"


# ─── IntegrityReport ───────────────────────────────────────────────


class TestIntegrityReport:

    def test_is_valid_clean(self):
        r = IntegrityReport(path="x", total_lines=10, valid_strokes=10)
        assert r.is_valid
        assert r.issue_count == 0

    def test_is_valid_dirty(self):
        r = IntegrityReport(
            path="x", total_lines=10, valid_strokes=8,
            issues=[IntegrityIssue(line=3, kind="json", message="bad")]
        )
        assert not r.is_valid
        assert r.issue_count == 1

    def test_error_count(self):
        r = IntegrityReport(
            path="x", total_lines=5, valid_strokes=3,
            issues=[
                IntegrityIssue(line=1, kind="json", message="a",
                               severity="error"),
                IntegrityIssue(line=2, kind="seq_order", message="b",
                               severity="warning"),
                IntegrityIssue(line=3, kind="time_order", message="c",
                               severity="error"),
            ]
        )
        assert r.error_count == 2
        assert r.warning_count == 1

    def test_issues_of_kind(self):
        r = IntegrityReport(
            path="x", total_lines=5, valid_strokes=3,
            issues=[
                IntegrityIssue(line=1, kind="json", message="a"),
                IntegrityIssue(line=2, kind="seq_order", message="b"),
                IntegrityIssue(line=3, kind="json", message="c"),
            ]
        )
        json_issues = r.issues_of_kind("json")
        assert len(json_issues) == 2
        assert json_issues[0].line == 1
        assert json_issues[1].line == 3


# ─── JSON validity ──────────────────────────────────────────────────


class TestJsonValidity:

    def test_valid_json(self):
        text = _lines(_stroke_json(seq=1), _stroke_json(seq=2))
        checker = IntegrityChecker()
        report = checker.check_text(text)
        assert report.is_valid

    def test_invalid_json(self):
        text = _lines(_stroke_json(seq=1), "not json", _stroke_json(seq=3))
        checker = IntegrityChecker()
        report = checker.check_text(text)
        # Bad JSON on line 2, plus seq gap (1→3) on line 3
        json_issues = report.issues_of_kind("json")
        assert len(json_issues) == 1
        assert json_issues[0].line == 2

    def test_json_array_not_object(self):
        text = _lines(_stroke_json(seq=1), "[1, 2, 3]")
        checker = IntegrityChecker()
        report = checker.check_text(text)
        assert report.issue_count == 1
        assert "Expected JSON object" in report.issues[0].message


# ─── Required fields ───────────────────────────────────────────────


class TestRequiredFields:

    def test_missing_seq(self):
        text = _lines(
            _stroke_json(seq=1),
            json.dumps({"at": "2026-11-18T10:00:00+00:00", "kind": "note"}),
        )
        checker = IntegrityChecker()
        report = checker.check_text(text)
        assert report.issue_count == 1
        assert report.issues[0].kind == "missing_field"
        assert "seq" in report.issues[0].message

    def test_missing_at(self):
        text = _lines(
            _stroke_json(seq=1),
            json.dumps({"seq": 2, "kind": "note"}),
        )
        checker = IntegrityChecker()
        report = checker.check_text(text)
        assert report.issue_count == 1
        assert report.issues[0].kind == "missing_field"
        assert "at" in report.issues[0].message

    def test_non_numeric_seq(self):
        text = _lines(
            json.dumps({"seq": "abc", "at": "2026-11-18T10:00:00+00:00"}),
        )
        checker = IntegrityChecker()
        report = checker.check_text(text)
        assert report.issue_count == 1
        assert report.issues[0].kind == "empty_seq"


# ─── Sequential seq ────────────────────────────────────────────────


class TestSeqOrder:

    def test_strictly_increasing(self):
        text = _lines(
            _stroke_json(seq=1), _stroke_json(seq=2), _stroke_json(seq=3)
        )
        checker = IntegrityChecker()
        report = checker.check_text(text)
        assert report.is_valid

    def test_seq_goes_backward(self):
        text = _lines(
            _stroke_json(seq=5), _stroke_json(seq=3)
        )
        checker = IntegrityChecker()
        report = checker.check_text(text)
        assert report.issue_count == 1
        assert report.issues[0].kind == "seq_order"
        assert "not increasing" in report.issues[0].message

    def test_seq_gap_warning(self):
        text = _lines(
            _stroke_json(seq=1), _stroke_json(seq=5)
        )
        checker = IntegrityChecker(allow_gaps=True)
        report = checker.check_text(text)
        assert report.issue_count == 1
        assert report.issues[0].severity == "warning"
        assert "gap" in report.issues[0].message
        assert "3" in report.issues[0].message  # missing 3

    def test_seq_gap_error_when_disallowed(self):
        text = _lines(
            _stroke_json(seq=1), _stroke_json(seq=5)
        )
        checker = IntegrityChecker(allow_gaps=False)
        report = checker.check_text(text)
        assert report.issue_count == 1
        assert report.issues[0].severity == "error"

    def test_seq_duplicate_value_not_increasing(self):
        text = _lines(
            _stroke_json(seq=3), _stroke_json(seq=3)
        )
        checker = IntegrityChecker()
        report = checker.check_text(text)
        # Should flag both duplicate and seq_order
        kinds = [i.kind for i in report.issues]
        assert "seq_order" in kinds


# ─── Duplicate detection ───────────────────────────────────────────


class TestDuplicates:

    def test_no_duplicates(self):
        text = _lines(
            _stroke_json(seq=1), _stroke_json(seq=2)
        )
        checker = IntegrityChecker()
        report = checker.check_text(text)
        dups = report.issues_of_kind("duplicate")
        assert len(dups) == 0

    def test_duplicate_seq(self):
        # Use timestamps that don't trigger time_order issue
        text = _lines(
            _stroke_json(seq=1, at="2026-11-18T10:00:00+00:00"),
            _stroke_json(seq=2, at="2026-11-18T10:01:00+00:00"),
            _stroke_json(seq=2, at="2026-11-18T10:02:00+00:00"),
        )
        checker = IntegrityChecker()
        report = checker.check_text(text)
        dups = report.issues_of_kind("duplicate")
        assert len(dups) == 1
        assert dups[0].line == 3
        assert "Duplicate seq: 2" in dups[0].message


# ─── Timestamp order ────────────────────────────────────────────────


class TestTimestampOrder:

    def test_monotonic(self):
        text = _lines(
            _stroke_json(seq=1, at="2026-11-18T10:00:00+00:00"),
            _stroke_json(seq=2, at="2026-11-18T10:01:00+00:00"),
            _stroke_json(seq=3, at="2026-11-18T10:02:00+00:00"),
        )
        checker = IntegrityChecker()
        report = checker.check_text(text)
        time_issues = report.issues_of_kind("time_order")
        assert len(time_issues) == 0

    def test_backward_timestamp(self):
        text = _lines(
            _stroke_json(seq=1, at="2026-11-18T10:00:00+00:00"),
            _stroke_json(seq=2, at="2026-11-18T09:00:00+00:00"),
        )
        checker = IntegrityChecker()
        report = checker.check_text(text)
        time_issues = report.issues_of_kind("time_order")
        assert len(time_issues) == 1
        assert "backward" in time_issues[0].message

    def test_equal_timestamps_ok(self):
        text = _lines(
            _stroke_json(seq=1, at="2026-11-18T10:00:00+00:00"),
            _stroke_json(seq=2, at="2026-11-18T10:00:00+00:00"),
        )
        checker = IntegrityChecker()
        report = checker.check_text(text)
        time_issues = report.issues_of_kind("time_order")
        assert len(time_issues) == 0

    def test_invalid_timestamp(self):
        text = _lines(
            json.dumps({"seq": 1, "at": "not-a-date"}),
        )
        checker = IntegrityChecker()
        report = checker.check_text(text)
        ts_issues = report.issues_of_kind("invalid_timestamp")
        assert len(ts_issues) == 1

    def test_naive_timestamp_warning(self):
        text = _lines(
            json.dumps({"seq": 1, "at": "2026-11-18T10:00:00"}),
        )
        checker = IntegrityChecker(strict_timestamps=True)
        report = checker.check_text(text)
        ts_issues = report.issues_of_kind("invalid_timestamp")
        assert len(ts_issues) == 1
        assert ts_issues[0].severity == "warning"
        assert "timezone" in ts_issues[0].message

    def test_naive_timestamp_accepted(self):
        text = _lines(
            json.dumps({"seq": 1, "at": "2026-11-18T10:00:00"}),
        )
        checker = IntegrityChecker(strict_timestamps=False)
        report = checker.check_text(text)
        ts_issues = report.issues_of_kind("invalid_timestamp")
        assert len(ts_issues) == 0


# ─── Valid kind ─────────────────────────────────────────────────────


class TestValidKind:

    def test_valid_kinds(self):
        strokes = [
            _stroke_json(seq=i + 1, kind=k,
                         at=f"2026-11-18T10:{i:02d}:00+00:00")
            for i, k in enumerate(sorted(VALID_KINDS))
        ]
        checker = IntegrityChecker()
        report = checker.check_text(_lines(*strokes))
        kind_issues = report.issues_of_kind("invalid_kind")
        assert len(kind_issues) == 0

    def test_invalid_kind_warning(self):
        text = _lines(
            _stroke_json(seq=1, kind="unknown_type"),
        )
        checker = IntegrityChecker()
        report = checker.check_text(text)
        kind_issues = report.issues_of_kind("invalid_kind")
        assert len(kind_issues) == 1
        assert kind_issues[0].severity == "warning"

    def test_custom_valid_kinds(self):
        text = _lines(
            _stroke_json(seq=1, kind="custom_kind"),
        )
        checker = IntegrityChecker(valid_kinds={"custom_kind", "thought"})
        report = checker.check_text(text)
        kind_issues = report.issues_of_kind("invalid_kind")
        assert len(kind_issues) == 0

    def test_empty_kind_accepted(self):
        text = _lines(
            json.dumps({"seq": 1, "at": "2026-11-18T10:00:00+00:00"}),
        )
        checker = IntegrityChecker()
        report = checker.check_text(text)
        kind_issues = report.issues_of_kind("invalid_kind")
        assert len(kind_issues) == 0


# ─── Blank lines and empty input ───────────────────────────────────


class TestEdgeCases:

    def test_empty_input(self):
        checker = IntegrityChecker()
        report = checker.check_text("")
        assert report.is_valid
        assert report.total_lines == 0
        assert report.valid_strokes == 0

    def test_blank_lines_only(self):
        checker = IntegrityChecker()
        report = checker.check_text("\n\n  \n\n")
        assert report.is_valid
        assert report.total_lines == 0

    def test_blank_lines_between_strokes(self):
        text = _stroke_json(seq=1) + "\n\n" + _stroke_json(seq=2) + "\n"
        checker = IntegrityChecker()
        report = checker.check_text(text)
        assert report.is_valid
        assert report.valid_strokes == 2

    def test_single_stroke(self):
        checker = IntegrityChecker()
        report = checker.check_text(_stroke_json(seq=42))
        assert report.is_valid
        assert report.valid_strokes == 1
        assert report.total_lines == 1


# ─── File loading ───────────────────────────────────────────────────


class TestFileLoading:

    def test_check_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            _stroke_json(seq=1) + "\n" + _stroke_json(seq=2) + "\n",
            encoding="utf-8"
        )
        checker = IntegrityChecker()
        report = checker.check(str(p))
        assert report.is_valid
        assert report.valid_strokes == 2
        assert report.path == str(p)

    def test_nonexistent_file(self, tmp_path):
        checker = IntegrityChecker()
        report = checker.check(str(tmp_path / "nope.jsonl"))
        assert report.is_valid
        assert report.total_lines == 0

    def test_check_lines_directly(self):
        lines = [_stroke_json(seq=1), _stroke_json(seq=2)]
        checker = IntegrityChecker()
        report = checker.check_lines(lines, path="<test>")
        assert report.is_valid
        assert report.path == "<test>"


# ─── CLI main ───────────────────────────────────────────────────────


class TestCLI:

    def test_main_clean(self, tmp_path, monkeypatch, capsys):
        p = tmp_path / "strokes.jsonl"
        p.write_text(_stroke_json(seq=1) + "\n", encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["prog", str(p)])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "integrity OK" in captured.out

    def test_main_dirty(self, tmp_path, monkeypatch, capsys):
        p = tmp_path / "strokes.jsonl"
        p.write_text("not json\n", encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["prog", str(p)])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Issues found" in captured.out

    def test_main_default_path(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["prog"])
        # Will try to read data/strokes.jsonl — just ensure no crash
        with pytest.raises(SystemExit):
            main()


# ─── Integration ────────────────────────────────────────────────────


class TestIntegration:

    def test_realistic_log_with_issues(self):
        """Simulate a realistic log with multiple issue types."""
        lines = [
            _stroke_json(seq=1, at="2026-11-18T10:00:00+00:00"),
            _stroke_json(seq=2, at="2026-11-18T10:00:15+00:00"),
            "bad json line",                                          # json
            _stroke_json(seq=4, at="2026-11-18T10:00:45+00:00"),     # gap 2→4
            _stroke_json(seq=4, at="2026-11-18T10:01:00+00:00"),     # dup + seq not increasing
            _stroke_json(seq=6, at="not-a-date"),                    # invalid timestamp
            _stroke_json(seq=7, at="2026-11-18T10:02:00+00:00",
                         kind="bogus"),                               # bad kind
        ]
        checker = IntegrityChecker()
        report = checker.check_text("\n".join(lines))

        assert not report.is_valid
        assert report.total_lines == 7
        # Lines 1,2,4,5 parse fully; line 7 parses but has bad kind;
        # line 3 is bad JSON; line 6 has invalid timestamp (continues before valid_count)
        assert report.valid_strokes == 5

        kinds = {i.kind for i in report.issues}
        assert "json" in kinds
        assert "seq_order" in kinds
        assert "duplicate" in kinds
        assert "invalid_timestamp" in kinds
        assert "invalid_kind" in kinds

    def test_perfect_log(self):
        """A perfectly valid log with no issues."""
        lines = [
            _stroke_json(
                seq=i,
                at=f"2026-11-18T10:{i:02d}:00+00:00",
                kind="thought",
            )
            for i in range(1, 11)
        ]
        checker = IntegrityChecker()
        report = checker.check_text("\n".join(lines))
        assert report.is_valid
        assert report.valid_strokes == 10
        assert report.total_lines == 10

    def test_z_suffix_timestamp(self):
        """Timestamps with Z suffix should parse correctly."""
        text = _lines(
            _stroke_json(seq=1, at="2026-11-18T10:00:00Z"),
            _stroke_json(seq=2, at="2026-11-18T10:01:00Z"),
        )
        checker = IntegrityChecker()
        report = checker.check_text(text)
        assert report.is_valid
