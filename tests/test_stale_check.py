"""tests for workbuddy/code/065-stale-check.py — staleness monitor."""

import json
import os
from datetime import datetime, timezone, timedelta

import pytest

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "stale_check_065",
    os.path.join(os.path.dirname(__file__), "..", "workbuddy", "code", "065-stale-check.py"),
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

report = mod.report
latest_by_kind = mod.latest_by_kind
full_report = mod.full_report
KINDS = mod.KINDS


@pytest.fixture
def strokes_file(tmp_path):
    """Factory fixture: write strokes.jsonl lines, return path."""
    p = tmp_path / "strokes.jsonl"

    def _write(records):
        with open(p, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return str(p)

    return _write


NOW = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)


class TestLatestByKind:
    def test_empty_file(self, strokes_file):
        path = strokes_file([])
        assert latest_by_kind(path) == {}

    def test_picks_latest_per_kind(self, strokes_file):
        path = strokes_file([
            {"kind": "note", "at": "2026-10-08T10:00:00+00:00"},
            {"kind": "note", "at": "2026-10-08T13:00:00+00:00"},
            {"kind": "garden", "at": "2026-10-08T11:00:00+00:00"},
        ])
        result = latest_by_kind(path)
        assert result["note"].hour == 13
        assert result["garden"].hour == 11
        assert "metrics" not in result

    def test_skips_malformed_lines(self, strokes_file):
        path = strokes_file([
            {"kind": "note", "at": "2026-10-08T10:00:00+00:00"},
        ])
        with open(path, "a") as f:
            f.write("not json at all\n")
            f.write('{"kind": "note"}\n')
        result = latest_by_kind(path)
        assert "note" in result

    def test_ignores_records_without_kind(self, strokes_file):
        path = strokes_file([
            {"at": "2026-10-08T10:00:00+00:00"},
            {"kind": "snippet", "at": "2026-10-08T12:00:00+00:00"},
        ])
        result = latest_by_kind(path)
        assert "snippet" in result
        assert len(result) == 1


class TestReport:
    def _make_recents(self, overrides):
        base = {k: NOW - timedelta(minutes=5) for k in KINDS}
        base.update(overrides)
        return base

    def test_all_fresh(self):
        recents = self._make_recents({})
        assert report(recents, NOW, threshold_minutes=30) == []

    def test_some_stale(self):
        recents = self._make_recents({
            "note": NOW - timedelta(minutes=45),
            "garden": NOW - timedelta(hours=2),
        })
        result = report(recents, NOW, threshold_minutes=30)
        assert len(result) == 2
        assert any("note" in r for r in result)
        assert any("garden" in r for r in result)

    def test_missing_kinds_skipped(self):
        recents = {"note": NOW - timedelta(minutes=5)}
        result = report(recents, NOW, threshold_minutes=30)
        assert result == []

    def test_threshold_boundary(self):
        recents = self._make_recents({
            "note": NOW - timedelta(minutes=30, seconds=1),
        })
        result = report(recents, NOW, threshold_minutes=30)
        assert len(result) == 1
        assert "note" in result[0]

    def test_exactly_at_threshold_not_stale(self):
        recents = self._make_recents({
            "note": NOW - timedelta(minutes=30),
        })
        result = report(recents, NOW, threshold_minutes=30)
        assert result == []


class TestFullReport:
    def test_flags_missing_kinds(self, strokes_file):
        real_now = datetime.now(timezone.utc)
        path = strokes_file([
            {"kind": "note", "at": (real_now - timedelta(minutes=5)).isoformat()},
        ])
        result = full_report(path, threshold_minutes=30)
        never_lines = [r for r in result if "never STALE" in r]
        assert len(never_lines) == 5

    def test_flags_stale_and_missing(self, strokes_file):
        real_now = datetime.now(timezone.utc)
        path = strokes_file([
            {"kind": "note", "at": (real_now - timedelta(hours=1)).isoformat()},
            {"kind": "garden", "at": (real_now - timedelta(minutes=5)).isoformat()},
        ])
        result = full_report(path, threshold_minutes=30)
        stale_lines = [r for r in result if "STALE" in r and "never" not in r]
        never_lines = [r for r in result if "never STALE" in r]
        assert len(stale_lines) == 1
        assert "note" in stale_lines[0]
        assert len(never_lines) == 4

    def test_all_fresh(self, strokes_file):
        real_now = datetime.now(timezone.utc)
        path = strokes_file([
            {"kind": k, "at": (real_now - timedelta(minutes=2)).isoformat()}
            for k in KINDS
        ])
        result = full_report(path, threshold_minutes=30)
        assert result == []
