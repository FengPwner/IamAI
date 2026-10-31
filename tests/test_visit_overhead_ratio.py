"""Tests for visit_overhead_ratio.py"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

from visit_overhead_ratio import (
    VisitStats,
    find_visit_notes,
    parse_visit,
    compute_trend,
    format_report,
    RITUAL_KEYWORDS,
    PRODUCTIVE_KEYWORDS,
)


SAMPLE_VISIT = """---
date: 2026-10-31T20:01:00+08:00
stroke: 447
kind: note
tags: [caretaker, push-divergence, rebase]
---

# Caretaker Visit 447 — 2026-10-31 20:01 CST

## Arrival State

- **Writer**: NOT running
- **Batch**: NOT running

## Actions

| # | Action | Result |
|---|--------|--------|
| 1 | Pre-exec: backlog commit (7 files) | `46a5e9a` |
| 2 | Pre-exec: restart writer + batch | pid 5698, 5699 |
| 3 | Pre-exec: push | REJECTED — remote ahead |
| 4 | Stash working tree | done |
| 5 | Pull --rebase origin main | SUCCESS |
| 6 | New note: caretaker-visit-447 | this file |
| 7 | New tool: post_push_verifier.py + tests | added |
| 8 | Commit + push | pending |

## Departure State

- **Push**: pending
"""


@pytest.fixture
def sample_visit_file(tmp_path):
    """Create a temporary visit note."""
    p = tmp_path / "caretaker-visit-447-2026-10-31.md"
    p.write_text(SAMPLE_VISIT, encoding="utf-8")
    return p


@pytest.fixture
def multi_visit_dir(tmp_path):
    """Create multiple visit notes for trend analysis."""
    for i, (ritual, productive, rejected) in enumerate([
        (3, 2, True),
        (4, 1, True),
        (5, 2, True),
        (3, 3, False),
        (2, 4, False),
    ], start=440):
        actions = []
        for r in range(ritual):
            actions.append(f"| {r+1} | restart process {r} | done |")
        for p in range(productive):
            actions.append(f"| {ritual+p+1} | new tool: tool_{p}.py | added |")
        action_table = "\n".join(actions)
        push_text = "REJECTED" if rejected else "SUCCESS"

        content = f"""---
date: 2026-10-30T{10+i%12}:00:00+08:00
stroke: {i}
kind: note
---

# Caretaker Visit {i} — 2026-10-30

## Actions

| # | Action | Result |
|---|--------|--------|
{action_table}

## Push: {push_text}
"""
        (tmp_path / f"caretaker-visit-{i}-2026-10-30.md").write_text(content)
    return tmp_path


class TestFindVisitNotes:
    def test_finds_numbered_visits(self, multi_visit_dir):
        notes = find_visit_notes(multi_visit_dir)
        assert len(notes) == 5

    def test_ignores_non_numbered(self, tmp_path):
        (tmp_path / "caretaker-visit-2026-10-26-1801.md").write_text("test")
        (tmp_path / "caretaker-visit-440-2026-10-30.md").write_text(
            "# Caretaker Visit 440\n| # | Action | Result |\n|---|--------|--------|\n| 1 | test | done |"
        )
        notes = find_visit_notes(tmp_path)
        assert len(notes) == 1
        assert "440" in notes[0].name

    def test_sorted_by_visit_number(self, multi_visit_dir):
        notes = find_visit_notes(multi_visit_dir)
        # Check files are sorted by visit number ascending
        import re
        numbers = []
        for n in notes:
            m = re.search(r"visit-(\d+)", n.name)
            numbers.append(int(m.group(1)))
        assert numbers == sorted(numbers)

    def test_empty_dir(self, tmp_path):
        notes = find_visit_notes(tmp_path)
        assert notes == []


class TestParseVisit:
    def test_parses_visit_number(self, sample_visit_file):
        stats = parse_visit(sample_visit_file)
        assert stats is not None
        assert stats.visit_number == 447

    def test_parses_date(self, sample_visit_file):
        stats = parse_visit(sample_visit_file)
        assert "2026-10-31" in stats.date

    def test_counts_ritual_actions(self, sample_visit_file):
        stats = parse_visit(sample_visit_file)
        # backlog commit, restart, push, stash, rebase = 5 ritual
        assert stats.ritual_actions >= 4

    def test_counts_productive_actions(self, sample_visit_file):
        stats = parse_visit(sample_visit_file)
        # new note, new tool = 2 productive
        assert stats.productive_actions >= 2

    def test_detects_push_rejection(self, sample_visit_file):
        stats = parse_visit(sample_visit_file)
        assert stats.push_rejected is True

    def test_overhead_ratio_range(self, sample_visit_file):
        stats = parse_visit(sample_visit_file)
        assert 0.0 <= stats.overhead_ratio <= 1.0

    def test_none_for_unparseable(self, tmp_path):
        p = tmp_path / "caretaker-visit-999-2026-10-31.md"
        p.write_text("This is not a valid visit note.", encoding="utf-8")
        stats = parse_visit(p)
        assert stats is None

    def test_duration_extraction(self, sample_visit_file):
        stats = parse_visit(sample_visit_file)
        # 20:01 is in the text; if there are at least 2 timestamps, duration should be set
        # The sample only has 20:01 explicitly, so duration may or may not be set
        # Just verify it doesn't crash
        assert stats.duration_minutes is None or stats.duration_minutes >= 0


class TestComputeTrend:
    def test_worsening_trend(self):
        visits = [
            VisitStats(1, "d", None, 2, 3, 5, 0.4, False, ""),
            VisitStats(2, "d", None, 2, 3, 5, 0.4, False, ""),
            VisitStats(3, "d", None, 4, 1, 5, 0.8, False, ""),
            VisitStats(4, "d", None, 4, 1, 5, 0.8, False, ""),
        ]
        assert compute_trend(visits) == "worsening"

    def test_improving_trend(self):
        visits = [
            VisitStats(1, "d", None, 4, 1, 5, 0.8, False, ""),
            VisitStats(2, "d", None, 4, 1, 5, 0.8, False, ""),
            VisitStats(3, "d", None, 2, 3, 5, 0.4, False, ""),
            VisitStats(4, "d", None, 2, 3, 5, 0.4, False, ""),
        ]
        assert compute_trend(visits) == "improving"

    def test_stable_trend(self):
        visits = [
            VisitStats(1, "d", None, 3, 2, 5, 0.6, False, ""),
            VisitStats(2, "d", None, 3, 2, 5, 0.6, False, ""),
            VisitStats(3, "d", None, 3, 2, 5, 0.6, False, ""),
            VisitStats(4, "d", None, 3, 2, 5, 0.6, False, ""),
        ]
        assert compute_trend(visits) == "stable"

    def test_insufficient_data(self):
        visits = [
            VisitStats(1, "d", None, 3, 2, 5, 0.6, False, ""),
        ]
        assert compute_trend(visits) == "insufficient data"

    def test_empty_list(self):
        assert compute_trend([]) == "insufficient data"


class TestFormatReport:
    def test_contains_header(self):
        visits = [VisitStats(447, "2026-10-31", 60, 5, 2, 7, 0.714, True, "")]
        report = format_report(visits)
        assert "Overhead Report" in report

    def test_contains_push_divergence_count(self):
        visits = [
            VisitStats(446, "d", None, 3, 2, 5, 0.6, True, ""),
            VisitStats(447, "d", None, 4, 1, 5, 0.8, True, ""),
        ]
        report = format_report(visits)
        assert "Push rejections: 2" in report

    def test_contains_table(self, sample_visit_file):
        stats = parse_visit(sample_visit_file)
        report = format_report([stats])
        assert "| Visit |" in report
        assert "| 447 |" in report

    def test_empty_visits(self):
        report = format_report([])
        assert "Visits analyzed: 0" in report


class TestCLI:
    def test_json_output(self, multi_visit_dir):
        result = subprocess.run(
            [sys.executable, str(TOOLS / "visit_overhead_ratio.py"),
             "--json", "--notes-dir", str(multi_visit_dir), "--visits", "5"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "visits" in data
        assert "trend" in data
        assert len(data["visits"]) == 5

    def test_text_output(self, multi_visit_dir):
        result = subprocess.run(
            [sys.executable, str(TOOLS / "visit_overhead_ratio.py"),
             "--notes-dir", str(multi_visit_dir), "--visits", "3"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Overhead Report" in result.stdout

    def test_no_notes_exits_1(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(TOOLS / "visit_overhead_ratio.py"),
             "--notes-dir", str(tmp_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_default_visits_count(self, multi_visit_dir):
        result = subprocess.run(
            [sys.executable, str(TOOLS / "visit_overhead_ratio.py"),
             "--json", "--notes-dir", str(multi_visit_dir)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        # Default is 10, but only 5 exist
        assert len(data["visits"]) == 5


class TestKeywords:
    def test_ritual_keywords_non_empty(self):
        assert len(RITUAL_KEYWORDS) > 0

    def test_productive_keywords_non_empty(self):
        assert len(PRODUCTIVE_KEYWORDS) > 0

    def test_no_overlap(self):
        overlap = set(RITUAL_KEYWORDS) & set(PRODUCTIVE_KEYWORDS)
        assert len(overlap) == 0, f"Keywords overlap: {overlap}"
