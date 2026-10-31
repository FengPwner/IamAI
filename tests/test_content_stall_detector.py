"""Tests for content_stall_detector.py — repetitive content detection.

Tests the three detection methods (exact_repeat, template_repeat,
unique_ratio) and edge cases like empty files and insufficient data.
"""

import json
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from content_stall_detector import (
    StallReport,
    detect_stall,
    extract_payload,
    format_report,
    normalize_for_template,
    read_tail,
)


class TestReadTail:
    def test_reads_last_n_lines(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("line1\nline2\nline3\nline4\nline5\n")
        assert read_tail(f, 3) == ["line3", "line4", "line5"]

    def test_skips_empty_lines(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("line1\n\nline2\n\nline3\n")
        assert read_tail(f, 5) == ["line1", "line2", "line3"]

    def test_returns_all_if_fewer_than_n(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("only\ntwo\n")
        assert read_tail(f, 10) == ["only", "two"]

    def test_missing_file(self, tmp_path):
        f = tmp_path / "nonexistent.md"
        assert read_tail(f) == []

    def test_large_file(self, tmp_path):
        f = tmp_path / "big.md"
        lines = [f"line-{i}" for i in range(1000)]
        f.write_text("\n".join(lines) + "\n")
        result = read_tail(f, 10)
        assert len(result) == 10
        assert result[-1] == "line-999"


class TestExtractPayload:
    def test_stroke_prefix(self):
        assert extract_payload("stroke 12345: some content") == "some content"

    def test_backtick_wrapped(self):
        assert extract_payload("`some content`") == "some content"

    def test_timestamp_prefix(self):
        line = "`2026-10-31T08:02:07+00:00` stroke 35629: tree is 1640 files"
        assert extract_payload(line) == "tree is 1640 files"

    def test_markdown_header_stroke(self):
        line = "## stroke 211 · 2026-10-31 09:56"
        result = extract_payload(line)
        # Should strip the stroke prefix
        assert "stroke" not in result or "211" not in result

    def test_plain_text_unchanged(self):
        assert extract_payload("just plain text") == "just plain text"


class TestNormalizeForTemplate:
    def test_replaces_backtick_content(self):
        text = "`retry.py` is already in the pool of 9 modules"
        result = normalize_for_template(text)
        assert "<MOD>" in result
        assert "retry.py" not in result

    def test_replaces_numbers(self):
        text = "tree is 1640 files; 367089 lines is a lot"
        result = normalize_for_template(text)
        assert "<N>" in result
        assert "1640" not in result

    def test_different_modules_same_template(self):
        t1 = normalize_for_template("`retry.py` is already in the pool of 9 modules")
        t2 = normalize_for_template("`chunk_text.py` is already in the pool of 9 modules")
        t3 = normalize_for_template("`parse_kv.py` is already in the pool of 9 modules")
        assert t1 == t2 == t3

    def test_replaces_timestamps(self):
        text = "stroke at 2026-10-31T08:02:07+00:00 happened"
        result = normalize_for_template(text)
        assert "2026" not in result


class TestDetectStall:
    def test_healthy_diverse_content(self, tmp_path):
        f = tmp_path / "history.md"
        lines = [
            f"stroke {i}: unique content number {i} about topic {i*7}"
            for i in range(20)
        ]
        f.write_text("\n".join(lines) + "\n")
        report = detect_stall(f, window=20, threshold=0.3)
        assert report.state == "healthy"
        assert report.unique_ratio > 0.3

    def test_stall_repetitive_content(self, tmp_path):
        f = tmp_path / "history.md"
        modules = ["retry.py", "chunk_text.py", "parse_kv.py"]
        lines = [
            f"stroke {35000+i*6}: `{modules[i%3]}` is already in the pool of 9 modules, nothing new to add there"
            for i in range(20)
        ]
        f.write_text("\n".join(lines) + "\n")
        report = detect_stall(f, window=20, threshold=0.3)
        assert report.state == "stall"
        assert report.unique_ratio < 0.3
        assert report.top_template_count == 20

    def test_insufficient_data(self, tmp_path):
        f = tmp_path / "history.md"
        f.write_text("only one line\n")
        report = detect_stall(f, window=20, threshold=0.3)
        assert report.state == "insufficient"

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.md"
        f.write_text("")
        report = detect_stall(f)
        assert report.state == "insufficient"

    def test_missing_file(self, tmp_path):
        f = tmp_path / "ghost.md"
        report = detect_stall(f)
        assert report.state == "insufficient"

    def test_exactly_at_threshold(self, tmp_path):
        f = tmp_path / "borderline.md"
        # 7 unique out of 20 = 0.35, above 0.3
        lines = [f"content {i}" for i in range(7)]
        lines += ["content 0"] * 13  # repeat first one
        f.write_text("\n".join(lines) + "\n")
        report = detect_stall(f, window=20, threshold=0.3)
        assert report.state == "healthy"

    def test_custom_threshold(self, tmp_path):
        f = tmp_path / "custom.md"
        # 5 unique out of 10 = 0.5
        lines = [f"topic {i}" for i in range(5)]
        lines += ["topic 0"] * 5
        f.write_text("\n".join(lines) + "\n")
        # With threshold=0.6, this should be a stall
        report = detect_stall(f, window=10, threshold=0.6)
        assert report.state == "stall"
        # With threshold=0.4, this should be healthy
        report2 = detect_stall(f, window=10, threshold=0.4)
        assert report2.state == "healthy"

    def test_window_smaller_than_file(self, tmp_path):
        f = tmp_path / "big.md"
        lines = [f"unique line {i}" for i in range(100)]
        f.write_text("\n".join(lines) + "\n")
        report = detect_stall(f, window=10, threshold=0.3)
        assert report.lines_read == 10
        assert report.state == "healthy"

    def test_report_fields(self, tmp_path):
        f = tmp_path / "fields.md"
        lines = [f"content {i}" for i in range(10)]
        f.write_text("\n".join(lines) + "\n")
        report = detect_stall(f, window=10, threshold=0.3)
        assert report.file == str(f)
        assert report.window == 10
        assert report.lines_read == 10
        assert report.unique_payloads == 10
        assert report.unique_ratio == 1.0
        assert report.state == "healthy"
        assert report.threshold == 0.3


class TestFormatReport:
    def test_healthy_format(self):
        report = StallReport(
            file="test.md", window=20, lines_read=20,
            unique_payloads=18, unique_ratio=0.9,
            top_template="content <N>", top_template_count=2,
            state="healthy", threshold=0.3,
        )
        text = format_report(report)
        assert "healthy" in text
        assert "90.00%" in text
        assert "test.md" in text

    def test_stall_format(self):
        report = StallReport(
            file="history.md", window=20, lines_read=20,
            unique_payloads=3, unique_ratio=0.15,
            top_template="<MOD> is already in the pool", top_template_count=18,
            state="stall", threshold=0.3,
        )
        text = format_report(report)
        assert "stall" in text
        assert "15.00%" in text

    def test_insufficient_format(self):
        report = StallReport(
            file="empty.md", window=20, lines_read=1,
            unique_payloads=0, unique_ratio=0.0,
            top_template="", top_template_count=0,
            state="insufficient", threshold=0.3,
        )
        text = format_report(report)
        assert "insufficient" in text

    def test_to_dict(self):
        report = StallReport(
            file="x.md", window=10, lines_read=5,
            unique_payloads=3, unique_ratio=0.6,
            top_template="t", top_template_count=2,
            state="healthy", threshold=0.3,
        )
        d = report.to_dict()
        assert d["file"] == "x.md"
        assert d["unique_ratio"] == 0.6
        # Should be JSON-serializable
        assert json.dumps(d)
