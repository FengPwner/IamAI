#!/usr/bin/env python3
"""Tests for tools/commit_age.py — uncommitted change age measurement."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from commit_age import (
    AgeReport,
    classify,
    format_text,
    get_oldest_mtime,
    get_uncommitted_files,
    parse_porcelain,
    verdict_to_exit,
)


# ── parse_porcelain ──────────────────────────────────────────────


class TestParsePorcelain:
    def test_modified_file(self):
        assert parse_porcelain(" M notes/history.md") == "notes/history.md"

    def test_staged_file(self):
        assert parse_porcelain("A  data/new.jsonl") == "data/new.jsonl"

    def test_deleted_file(self):
        assert parse_porcelain(" D old_file.py") == "old_file.py"

    def test_untracked_file(self):
        assert parse_porcelain("?? new_file.py") == "new_file.py"

    def test_rename_returns_raw(self):
        """parse_porcelain returns the raw path; rename splitting
        happens in get_uncommitted_files."""
        assert parse_porcelain("R  old.py -> new.py") == "old.py -> new.py"

    def test_short_line_returns_none(self):
        assert parse_porcelain("XY") is None

    def test_empty_line_returns_none(self):
        assert parse_porcelain("") is None


# ── classify ─────────────────────────────────────────────────────


class TestClassify:
    def test_fresh(self):
        assert classify(30, 600, 3600) == "fresh"

    def test_fresh_at_boundary(self):
        assert classify(599, 600, 3600) == "fresh"

    def test_aging(self):
        assert classify(600, 600, 3600) == "aging"

    def test_aging_mid(self):
        assert classify(1800, 600, 3600) == "aging"

    def test_stale(self):
        assert classify(3600, 600, 3600) == "stale"

    def test_very_stale(self):
        assert classify(86400, 600, 3600) == "stale"

    def test_custom_thresholds(self):
        assert classify(100, 50, 200) == "aging"
        assert classify(250, 50, 200) == "stale"
        assert classify(10, 50, 200) == "fresh"


# ── verdict_to_exit ─────────────────────────────────────────────


class TestVerdictToExit:
    def test_fresh_is_zero(self):
        assert verdict_to_exit("fresh") == 0

    def test_aging_is_one(self):
        assert verdict_to_exit("aging") == 1

    def test_stale_is_two(self):
        assert verdict_to_exit("stale") == 2

    def test_clean_is_three(self):
        assert verdict_to_exit("clean") == 3


# ── format_text ──────────────────────────────────────────────────


class TestFormatText:
    def test_clean(self):
        report = AgeReport(0.0, "", 0, "clean")
        assert "clean" in format_text(report)

    def test_fresh_minutes(self):
        report = AgeReport(180, "notes/a.md", 3, "fresh")
        text = format_text(report)
        assert "fresh" in text
        assert "3m" in text
        assert "notes/a.md" in text

    def test_stale_hours(self):
        report = AgeReport(7200, "data/strokes.jsonl", 12, "stale")
        text = format_text(report)
        assert "stale" in text
        assert "2.0h" in text

    def test_file_count_included(self):
        report = AgeReport(900, "docs/x.md", 5, "aging")
        text = format_text(report)
        assert "5 file(s)" in text


# ── get_oldest_mtime ───────────────────────────────────────────


class TestGetOldestMtime:
    def test_single_file(self, tmp_path: Path):
        f = tmp_path / "a.txt"
        f.write_text("hello")
        # Set mtime to 100 seconds ago
        old_time = time.time() - 100
        os.utime(f, (old_time, old_time))
        result = get_oldest_mtime(tmp_path, ["a.txt"])
        assert result is not None
        age, name = result
        assert name == "a.txt"
        assert 90 < age < 120  # allow some slack

    def test_picks_oldest(self, tmp_path: Path):
        f1 = tmp_path / "new.txt"
        f2 = tmp_path / "old.txt"
        f1.write_text("new")
        f2.write_text("old")
        now = time.time()
        os.utime(f1, (now - 10, now - 10))
        os.utime(f2, (now - 500, now - 500))
        result = get_oldest_mtime(tmp_path, ["new.txt", "old.txt"])
        assert result is not None
        age, name = result
        assert name == "old.txt"
        assert age > 400

    def test_missing_file_skipped(self, tmp_path: Path):
        result = get_oldest_mtime(tmp_path, ["nonexistent.txt"])
        assert result is None

    def test_empty_list_returns_none(self, tmp_path: Path):
        assert get_oldest_mtime(tmp_path, []) is None


# ── get_uncommitted_files (integration, needs git) ──────────────


class TestGetUncommittedFiles:
    def test_clean_repo(self, tmp_path: Path):
        """A freshly init+committed repo should have zero uncommitted files."""
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test"],
            cwd=tmp_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, capture_output=True,
        )
        (tmp_path / "a.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path, capture_output=True,
        )
        files = get_uncommitted_files(tmp_path)
        assert files == []

    def test_modified_file_detected(self, tmp_path: Path):
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test"],
            cwd=tmp_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, capture_output=True,
        )
        (tmp_path / "a.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path, capture_output=True,
        )
        (tmp_path / "a.txt").write_text("modified")
        files = get_uncommitted_files(tmp_path)
        assert "a.txt" in files

    def test_untracked_file_detected(self, tmp_path: Path):
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test"],
            cwd=tmp_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, capture_output=True,
        )
        (tmp_path / "a.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path, capture_output=True,
        )
        (tmp_path / "new.txt").write_text("untracked")
        files = get_uncommitted_files(tmp_path)
        assert "new.txt" in files


# ── end-to-end via subprocess ────────────────────────────────────


class TestCLI:
    def test_clean_repo_exit_3(self, tmp_path: Path):
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test"],
            cwd=tmp_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, capture_output=True,
        )
        (tmp_path / "a.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path, capture_output=True,
        )
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "commit_age.py"),
             "--repo", str(tmp_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 3
        assert "clean" in result.stdout

    def test_json_output(self, tmp_path: Path):
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test"],
            cwd=tmp_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, capture_output=True,
        )
        (tmp_path / "a.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path, capture_output=True,
        )
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "commit_age.py"),
             "--repo", str(tmp_path), "--json"],
            capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        assert "verdict" in data
        assert data["verdict"] == "clean"
        assert "age_seconds" in data

    def test_modified_file_exit_0(self, tmp_path: Path):
        """Freshly modified file should be 'fresh' (exit 0)."""
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test"],
            cwd=tmp_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, capture_output=True,
        )
        (tmp_path / "a.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path, capture_output=True,
        )
        (tmp_path / "a.txt").write_text("modified just now")
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "commit_age.py"),
             "--repo", str(tmp_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "fresh" in result.stdout
