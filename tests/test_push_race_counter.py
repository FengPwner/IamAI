#!/usr/bin/env python3
"""Tests for push_race_counter.py — push race detection and counting."""

import sys
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import push_race_counter as prc


# ---------------------------------------------------------------------------
# scan_commit_log
# ---------------------------------------------------------------------------

class TestScanCommitLog:
    def test_clean_log_no_races(self):
        """No race markers in commit messages → empty list."""
        fake_output = textwrap.dedent("""\
            2026-10-07T10:00:00+00:00||feat: add new feature
            2026-10-07T09:00:00+00:00||fix: correct typo in README
            2026-10-07T08:00:00+00:00||chore: update dependencies
        """).strip()
        with patch.object(prc, "run_git", return_value=(0, fake_output)):
            entries = prc.scan_commit_log("2026-10-01")
        assert entries == []

    def test_detects_rebase_fixup(self):
        """Commit with 'pull --rebase' marker is detected as a race."""
        fake_output = textwrap.dedent("""\
            2026-10-07T10:00:00+00:00||feat: normal commit
            2026-10-07T09:00:00+00:00||synced (rebase) — ready to push
            2026-10-07T08:00:00+00:00||another normal commit
        """).strip()
        with patch.object(prc, "run_git", return_value=(0, fake_output)):
            entries = prc.scan_commit_log("2026-10-01")
        assert len(entries) == 1
        assert entries[0].source == "commit"
        assert "rebase" in entries[0].description

    def test_detects_multiple_markers(self):
        """Multiple race markers across commits are all counted."""
        fake_output = textwrap.dedent("""\
            2026-10-07T12:00:00+00:00||synced (merge) — resolved divergence
            2026-10-07T10:00:00+00:00||feat: normal stuff
            2026-10-07T08:00:00+00:00||push race recovery
            2026-10-07T06:00:00+00:00||fetch first then push
        """).strip()
        with patch.object(prc, "run_git", return_value=(0, fake_output)):
            entries = prc.scan_commit_log("2026-10-01")
        assert len(entries) == 3

    def test_empty_log(self):
        """Empty git log output → empty list."""
        with patch.object(prc, "run_git", return_value=(0, "")):
            entries = prc.scan_commit_log("2026-10-01")
        assert entries == []

    def test_git_error(self):
        """Git failure → empty list (graceful degradation)."""
        with patch.object(prc, "run_git", return_value=(128, "fatal: not a repo")):
            entries = prc.scan_commit_log("2026-10-01")
        assert entries == []


# ---------------------------------------------------------------------------
# scan_devlog
# ---------------------------------------------------------------------------

class TestScanDevlog:
    def test_devlog_with_rejection(self, tmp_path):
        """Devlog lines mentioning 'rejected' are detected."""
        devlog = tmp_path / "docs" / "DEVLOG.md"
        devlog.parent.mkdir(parents=True)
        devlog.write_text(textwrap.dedent("""\
            # DEVLOG
            stroke 100: 1000 lines
            push rejected — remote had guoban's commit
            stroke 101: more content
        """), encoding="utf-8")
        with patch.object(prc, "REPO", tmp_path):
            entries = prc.scan_devlog(since_days=7)
        assert len(entries) == 1
        assert entries[0].source == "devlog"
        assert "rejected" in entries[0].description

    def test_devlog_missing(self, tmp_path):
        """No DEVLOG.md → empty list."""
        with patch.object(prc, "REPO", tmp_path):
            entries = prc.scan_devlog(since_days=7)
        assert entries == []

    def test_devlog_clean(self, tmp_path):
        """Devlog with no race markers → empty list."""
        devlog = tmp_path / "docs" / "DEVLOG.md"
        devlog.parent.mkdir(parents=True)
        devlog.write_text("stroke 100: all good\nstroke 101: still good\n",
                          encoding="utf-8")
        with patch.object(prc, "REPO", tmp_path):
            entries = prc.scan_devlog(since_days=7)
        assert entries == []


# ---------------------------------------------------------------------------
# scan_visit_notes
# ---------------------------------------------------------------------------

class TestScanVisitNotes:
    def test_visit_with_push_race(self, tmp_path):
        """Visit note mentioning push race is detected."""
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir(parents=True)
        (notes_dir / "caretaker-visit-68-2026-10-07.md").write_text(
            "# visit 68\n\npush race resolved via rebase.\n",
            encoding="utf-8",
        )
        (notes_dir / "caretaker-visit-67-2026-10-07.md").write_text(
            "# visit 67\n\nadded rebase strategy, no race this time.\n",
            encoding="utf-8",
        )
        with patch.object(prc, "REPO", tmp_path):
            entries = prc.scan_visit_notes(since_days=7)
        assert len(entries) == 1
        assert entries[0].source == "visit"
        assert "visit-68" in entries[0].description

    def test_no_notes_dir(self, tmp_path):
        """Missing notes/ directory → empty list."""
        with patch.object(prc, "REPO", tmp_path):
            entries = prc.scan_visit_notes(since_days=7)
        assert entries == []


# ---------------------------------------------------------------------------
# count_races (integration-level)
# ---------------------------------------------------------------------------

class TestCountRaces:
    def test_zero_races_all_sources(self):
        """When all scanners return empty, total is zero."""
        with patch.object(prc, "scan_commit_log", return_value=[]), \
             patch.object(prc, "scan_devlog", return_value=[]), \
             patch.object(prc, "scan_visit_notes", return_value=[]):
            result = prc.count_races(days=7, source="all")
        assert result["total"] == 0
        assert result["rate_per_day"] == 0.0
        assert result["by_source"] == {}

    def test_counts_across_sources(self):
        """Races from different sources are summed correctly."""
        commit_entries = [prc.RaceEntry("2026-10-07T10:00:00", "commit", "rebase fixup")]
        devlog_entries = [prc.RaceEntry("", "devlog", "push rejected")]
        visit_entries = [prc.RaceEntry("2026-10-07", "visit", "visit-68: race")]
        with patch.object(prc, "scan_commit_log", return_value=commit_entries), \
             patch.object(prc, "scan_devlog", return_value=devlog_entries), \
             patch.object(prc, "scan_visit_notes", return_value=visit_entries):
            result = prc.count_races(days=7, source="all")
        assert result["total"] == 3
        assert result["by_source"] == {"commit": 1, "devlog": 1, "visit": 1}
        assert result["rate_per_day"] == round(3 / 7, 2)

    def test_log_only_source(self):
        """source='log' only scans commit log."""
        commit_entries = [prc.RaceEntry("2026-10-07T10:00:00", "commit", "rebase")]
        with patch.object(prc, "scan_commit_log", return_value=commit_entries) as mock_log:
            result = prc.count_races(days=3, source="log")
        assert result["total"] == 1
        mock_log.assert_called_once()

    def test_rate_calculation(self):
        """Rate per day is total / days, rounded to 2 decimals."""
        entries = [prc.RaceEntry("", "commit", f"race {i}") for i in range(10)]
        with patch.object(prc, "scan_commit_log", return_value=entries), \
             patch.object(prc, "scan_devlog", return_value=[]), \
             patch.object(prc, "scan_visit_notes", return_value=[]):
            result = prc.count_races(days=5, source="all")
        assert result["rate_per_day"] == 2.0
        assert result["total"] == 10

    def test_zero_day_window(self):
        """Zero-day window doesn't crash (clamped to 1 for division)."""
        with patch.object(prc, "scan_commit_log", return_value=[]), \
             patch.object(prc, "scan_devlog", return_value=[]), \
             patch.object(prc, "scan_visit_notes", return_value=[]):
            result = prc.count_races(days=0, source="all")
        assert result["total"] == 0
        assert result["rate_per_day"] == 0.0
