"""Tests for iamai.visit_interval — caretaker visit interval analysis."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from iamai.visit_interval import parse_visit_files, visit_intervals, visit_stats


@pytest.fixture
def notes_dir(tmp_path: Path) -> Path:
    """Create a temporary notes directory with sample visit files."""
    visits = [
        ("caretaker-visit-1-2026-10-03.md", "# Visit 1\nFirst visit.\n"),
        ("caretaker-visit-2-2026-10-03.md", "# Visit 2\nSame day.\n"),
        ("caretaker-visit-3-2026-10-04.md", "# Visit 3\nNext day.\n"),
        ("caretaker-visit-4-2026-10-04.md", "# Visit 4\nStill same day.\n"),
        ("caretaker-visit-5-2026-10-06.md", "# Visit 5\nTwo days later.\n"),
    ]
    for name, content in visits:
        (tmp_path / name).write_text(content, encoding="utf-8")
    # A decoy file that should be skipped
    (tmp_path / "some-other-note.md").write_text("not a visit", encoding="utf-8")
    return tmp_path


def test_parse_visit_files_finds_all(notes_dir: Path) -> None:
    visits = parse_visit_files(notes_dir)
    assert len(visits) == 5
    assert visits[0]["visit_number"] == 1
    assert visits[-1]["visit_number"] == 5


def test_parse_visit_files_skips_non_matching(notes_dir: Path) -> None:
    visits = parse_visit_files(notes_dir)
    filenames = [v["filename"] for v in visits]
    assert "some-other-note.md" not in filenames


def test_parse_visit_files_empty_dir(tmp_path: Path) -> None:
    assert parse_visit_files(tmp_path) == []


def test_parse_visit_files_nonexistent_dir(tmp_path: Path) -> None:
    assert parse_visit_files(tmp_path / "does-not-exist") == []


def test_visit_intervals_computes_gaps(notes_dir: Path) -> None:
    intervals = visit_intervals(notes_dir)
    assert len(intervals) == 4
    # visit 1 → 2: same day = 0h
    assert intervals[0] == 0.0
    # visit 2 → 3: 1 day = 24h
    assert intervals[1] == 24.0
    # visit 3 → 4: same day = 0h
    assert intervals[2] == 0.0
    # visit 4 → 5: 2 days = 48h
    assert intervals[3] == 48.0


def test_visit_intervals_single_visit(tmp_path: Path) -> None:
    (tmp_path / "caretaker-visit-1-2026-10-03.md").write_text("only one")
    assert visit_intervals(tmp_path) == []


def test_visit_stats_summary(notes_dir: Path) -> None:
    stats = visit_stats(notes_dir)
    assert stats["count"] == 5
    assert stats["first_visit"] == 1
    assert stats["last_visit"] == 5
    assert stats["date_span_days"] == 3  # Oct 3 → Oct 6
    assert stats["same_day_visits"] == 2  # visits 1→2 and 3→4
    assert stats["mean_interval_hours"] == pytest.approx(18.0)  # (0+24+0+48)/4
    assert stats["min_interval_hours"] == 0.0
    assert stats["max_interval_hours"] == 48.0


def test_visit_stats_single_visit(tmp_path: Path) -> None:
    (tmp_path / "caretaker-visit-1-2026-10-03.md").write_text("only one")
    stats = visit_stats(tmp_path)
    assert stats["count"] == 1
    assert stats["mean_interval_hours"] == 0.0


def test_visit_stats_empty_dir(tmp_path: Path) -> None:
    stats = visit_stats(tmp_path)
    assert stats["count"] == 0
    assert stats["first_visit"] == 0
    assert stats["last_visit"] == 0
