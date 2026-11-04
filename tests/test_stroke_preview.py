#!/usr/bin/env python3
"""Tests for tools/stroke_preview.py — stroke log preview and health signals."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from stroke_preview import (
    StrokeEntry,
    find_repo_root,
    format_stroke,
    format_summary,
    parse_strokes,
    read_strokes,
    to_json,
    truncate,
)


# ── truncate ─────────────────────────────────────────────────────


class TestTruncate:
    def test_short_text_unchanged(self):
        assert truncate("hello", 80) == "hello"

    def test_exact_length_unchanged(self):
        text = "a" * 80
        assert truncate(text, 80) == text

    def test_long_text_clipped(self):
        text = "x" * 100
        result = truncate(text, 80)
        assert len(result) == 80
        assert result.endswith("\u2026")

    def test_trailing_space_stripped_before_ellipsis(self):
        text = "hello " + "x" * 100
        result = truncate(text, 10)
        assert result.endswith("\u2026")
        # The character before ellipsis should not be a trailing space
        assert result[-2] != " "

    def test_zero_max_len(self):
        # max_len=0 is a degenerate edge: text[:-1] + '…' is acceptable
        result = truncate("hello", 0)
        assert result.endswith("\u2026")

    def test_one_char_max_len(self):
        result = truncate("hello", 1)
        assert result == "\u2026"


# ── read_strokes ─────────────────────────────────────────────────


class TestReadStrokes:
    def test_reads_last_n_lines(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        lines = [json.dumps({"seq": i, "kind": "note", "at": f"2026-01-0{i}", "text": f"t{i}"})
                 for i in range(1, 11)]
        f.write_text("\n".join(lines) + "\n")
        result = read_strokes(f, 3)
        assert len(result) == 3
        assert result[0]["seq"] == 8
        assert result[-1]["seq"] == 10

    def test_returns_all_if_fewer_than_count(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text(json.dumps({"seq": 1, "kind": "note", "at": "t", "text": "a"}) + "\n")
        result = read_strokes(f, 100)
        assert len(result) == 1

    def test_skips_blank_lines(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        content = json.dumps({"seq": 1, "kind": "note", "at": "t", "text": "a"})
        f.write_text(f"\n\n{content}\n\n{content}\n\n")
        result = read_strokes(f, 10)
        assert len(result) == 2

    def test_skips_malformed_json(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        good = json.dumps({"seq": 1, "kind": "note", "at": "t", "text": "ok"})
        f.write_text(f"not json\n{good}\n{{bad\n")
        result = read_strokes(f, 10)
        assert len(result) == 1
        assert result[0]["text"] == "ok"

    def test_missing_file_returns_empty(self, tmp_path):
        result = read_strokes(tmp_path / "nope.jsonl", 10)
        assert result == []

    def test_empty_file_returns_empty(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text("")
        result = read_strokes(f, 10)
        assert result == []


# ── parse_strokes ────────────────────────────────────────────────


class TestParseStrokes:
    def test_basic_parsing(self):
        raw = [{"seq": 42, "at": "2026-11-04T01:00:00+00:00", "kind": "thought", "text": "hello"}]
        entries = parse_strokes(raw)
        assert len(entries) == 1
        assert entries[0].seq == 42
        assert entries[0].kind == "thought"
        assert entries[0].text == "hello"
        assert entries[0].is_duplicate is False

    def test_consecutive_duplicate_flagged(self):
        raw = [
            {"seq": 1, "at": "t1", "kind": "note", "text": "same"},
            {"seq": 2, "at": "t2", "kind": "note", "text": "same"},
        ]
        entries = parse_strokes(raw)
        assert entries[0].is_duplicate is False
        assert entries[1].is_duplicate is True

    def test_non_consecutive_same_text_not_flagged(self):
        raw = [
            {"seq": 1, "at": "t1", "kind": "note", "text": "hello"},
            {"seq": 2, "at": "t2", "kind": "note", "text": "world"},
            {"seq": 3, "at": "t3", "kind": "note", "text": "hello"},
        ]
        entries = parse_strokes(raw)
        assert all(not e.is_duplicate for e in entries)

    def test_empty_text_not_flagged_as_duplicate(self):
        raw = [
            {"seq": 1, "at": "t1", "kind": "note", "text": ""},
            {"seq": 2, "at": "t2", "kind": "note", "text": ""},
        ]
        entries = parse_strokes(raw)
        assert all(not e.is_duplicate for e in entries)

    def test_missing_fields_get_defaults(self):
        raw = [{}]
        entries = parse_strokes(raw)
        assert entries[0].seq == 0
        assert entries[0].at == ""
        assert entries[0].kind == "unknown"
        assert entries[0].text == ""

    def test_triple_duplicate_all_marked(self):
        raw = [
            {"seq": 1, "at": "t1", "kind": "note", "text": "loop"},
            {"seq": 2, "at": "t2", "kind": "note", "text": "loop"},
            {"seq": 3, "at": "t3", "kind": "note", "text": "loop"},
        ]
        entries = parse_strokes(raw)
        assert entries[0].is_duplicate is False
        assert entries[1].is_duplicate is True
        assert entries[2].is_duplicate is True


# ── format_stroke ────────────────────────────────────────────────


class TestFormatStroke:
    def test_normal_stroke(self):
        entry = StrokeEntry(seq=100, at="2026-11-04T01:00:00+00:00", kind="thought", text="hello world")
        result = format_stroke(entry)
        assert result.startswith("#100")
        assert "(thought)" in result
        assert "hello world" in result
        assert "[DUP]" not in result

    def test_duplicate_stroke_has_flag(self):
        entry = StrokeEntry(seq=101, at="t", kind="note", text="echo", is_duplicate=True)
        result = format_stroke(entry)
        assert "[DUP]" in result

    def test_long_text_truncated(self):
        entry = StrokeEntry(seq=1, at="t", kind="note", text="x" * 200)
        result = format_stroke(entry, max_len=50)
        assert "\u2026" in result

    def test_short_text_not_truncated(self):
        entry = StrokeEntry(seq=1, at="t", kind="note", text="short")
        result = format_stroke(entry, max_len=50)
        assert "short" in result
        assert "\u2026" not in result


# ── format_summary ───────────────────────────────────────────────


class TestFormatSummary:
    def test_empty_entries(self):
        assert format_summary([]) == "no strokes in window"

    def test_kind_distribution(self):
        entries = [
            StrokeEntry(seq=1, at="t", kind="note", text="a"),
            StrokeEntry(seq=2, at="t", kind="note", text="b"),
            StrokeEntry(seq=3, at="t", kind="thought", text="c"),
        ]
        result = format_summary(entries)
        assert "3 strokes" in result
        assert "note x2" in result
        assert "thought x1" in result

    def test_duplicate_count(self):
        entries = [
            StrokeEntry(seq=1, at="t", kind="note", text="x"),
            StrokeEntry(seq=2, at="t", kind="note", text="x", is_duplicate=True),
            StrokeEntry(seq=3, at="t", kind="note", text="y"),
        ]
        result = format_summary(entries)
        assert "duplicates: 1" in result

    def test_no_duplicates_shows_zero(self):
        entries = [StrokeEntry(seq=1, at="t", kind="note", text="unique")]
        result = format_summary(entries)
        assert "duplicates: 0" in result


# ── to_json ──────────────────────────────────────────────────────


class TestToJson:
    def test_round_trip(self):
        entries = [StrokeEntry(seq=1, at="t", kind="note", text="hello", is_duplicate=False)]
        result = json.loads(to_json(entries))
        assert len(result) == 1
        assert result[0]["seq"] == 1
        assert result[0]["kind"] == "note"
        assert result[0]["is_duplicate"] is False

    def test_empty_list(self):
        result = json.loads(to_json([]))
        assert result == []

    def test_duplicate_flag_preserved(self):
        entries = [StrokeEntry(seq=1, at="t", kind="note", text="dup", is_duplicate=True)]
        result = json.loads(to_json(entries))
        assert result[0]["is_duplicate"] is True


# ── find_repo_root ───────────────────────────────────────────────


class TestFindRepoRoot:
    def test_finds_repo_from_inside(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        assert find_repo_root(sub) == tmp_path

    def test_finds_repo_at_root(self, tmp_path):
        (tmp_path / ".git").mkdir()
        assert find_repo_root(tmp_path) == tmp_path

    def test_returns_start_when_no_git(self, tmp_path):
        sub = tmp_path / "no_git"
        sub.mkdir()
        assert find_repo_root(sub) == sub


# ── integration: CLI ─────────────────────────────────────────────


class TestCLI:
    def test_runs_on_real_repo(self):
        """End-to-end: run the tool against the actual repo strokes file."""
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "stroke_preview.py"), "--count", "5"],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0
        assert "#6" in result.stdout or "window:" in result.stdout

    def test_summary_mode(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": i, "at": f"t{i}", "kind": "note", "text": f"text{i}"})
            for i in range(5)
        ]
        f.write_text("\n".join(lines) + "\n")
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "stroke_preview.py"),
             "--strokes", str(f), "--count", "5", "--summary"],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0
        assert "5 strokes" in result.stdout

    def test_json_mode(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text(json.dumps({"seq": 1, "at": "t", "kind": "note", "text": "hi"}) + "\n")
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "stroke_preview.py"),
             "--strokes", str(f), "--count", "3", "--json"],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) == 1
