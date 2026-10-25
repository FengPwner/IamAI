"""Tests for iamai.stroke_parity — disk-vs-git parity verification."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.stroke_parity import (
    ParityReport,
    _read_strokes,
    _committed_strokes,
    _seq_set,
    _kind_breakdown,
    stroke_parity,
    parity_summary,
    orphan_strokes,
    parity_grade,
    kind_parity,
    parity_trend,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path, strokes: list | None = None, committed: list | None = None) -> Path:
    """Create a minimal repo with a strokes JSONL and optionally a git HEAD.

    Parameters
    ----------
    tmp_path : Path
        pytest-provided temporary directory.
    strokes : list or None
        Stroke dicts to write to disk.  None → empty file.
    committed : list or None
        Stroke dicts to return as the "committed" (HEAD) version.
        None → same as *strokes* (perfect parity).
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)

    strokes_path = data_dir / "strokes.jsonl"
    if strokes is not None:
        with open(strokes_path, "w", encoding="utf-8") as fh:
            for s in strokes:
                fh.write(json.dumps(s) + "\n")

    # We will mock _committed_strokes to return the *committed* list
    # so that tests do not need a real git repo.
    return tmp_path


def _stroke(seq: int, kind: str = "thought", text: str = "test stroke") -> dict:
    return {"seq": seq, "at": "2026-10-17T04:00:00+00:00", "kind": kind, "text": text}


# ---------------------------------------------------------------------------
# _read_strokes
# ---------------------------------------------------------------------------


class TestReadStrokes:
    def test_basic(self, tmp_path: Path):
        strokes = [_stroke(1), _stroke(2), _stroke(3)]
        _make_repo(tmp_path, strokes=strokes)
        result = _read_strokes(tmp_path / "data" / "strokes.jsonl")
        assert len(result) == 3
        assert [s["seq"] for s in result] == [1, 2, 3]

    def test_empty_file(self, tmp_path: Path):
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        (tmp_path / "data" / "strokes.jsonl").write_text("")
        result = _read_strokes(tmp_path / "data" / "strokes.jsonl")
        assert result == []

    def test_missing_file(self, tmp_path: Path):
        result = _read_strokes(tmp_path / "data" / "nonexistent.jsonl")
        assert result == []

    def test_blank_lines_skipped(self, tmp_path: Path):
        path = tmp_path / "data" / "strokes.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_stroke(1)) + "\n\n\n" + json.dumps(_stroke(2)) + "\n")
        result = _read_strokes(path)
        assert len(result) == 2

    def test_malformed_json_skipped(self, tmp_path: Path):
        path = tmp_path / "data" / "strokes.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(_stroke(1)) + "\n"
            "this is not json\n"
            + json.dumps(_stroke(2)) + "\n"
        )
        result = _read_strokes(path)
        assert len(result) == 2

    def test_preserves_order(self, tmp_path: Path):
        strokes = [_stroke(i) for i in range(10)]
        _make_repo(tmp_path, strokes=strokes)
        result = _read_strokes(tmp_path / "data" / "strokes.jsonl")
        seqs = [s["seq"] for s in result]
        assert seqs == list(range(10))

    def test_large_file(self, tmp_path: Path):
        strokes = [_stroke(i) for i in range(1000)]
        _make_repo(tmp_path, strokes=strokes)
        result = _read_strokes(tmp_path / "data" / "strokes.jsonl")
        assert len(result) == 1000


# ---------------------------------------------------------------------------
# _seq_set
# ---------------------------------------------------------------------------


class TestSeqSet:
    def test_basic(self):
        strokes = [_stroke(1), _stroke(5), _stroke(3)]
        assert _seq_set(strokes) == {1, 5, 3}

    def test_empty(self):
        assert _seq_set([]) == set()

    def test_missing_seq_key(self):
        strokes = [_stroke(1), {"kind": "thought", "text": "no seq"}]
        assert _seq_set(strokes) == {1}


# ---------------------------------------------------------------------------
# _kind_breakdown
# ---------------------------------------------------------------------------


class TestKindBreakdown:
    def test_basic(self):
        strokes = [
            _stroke(1, "thought"),
            _stroke(2, "thought"),
            _stroke(3, "note"),
        ]
        committed_seqs = {1, 3}
        bd = _kind_breakdown(strokes, committed_seqs)
        assert bd["thought"] == {"total": 2, "committed": 1, "orphan": 1}
        assert bd["note"] == {"total": 1, "committed": 1, "orphan": 0}

    def test_empty(self):
        bd = _kind_breakdown([], set())
        assert bd == {}

    def test_all_orphans(self):
        strokes = [_stroke(1), _stroke(2)]
        bd = _kind_breakdown(strokes, set())
        assert bd["thought"]["orphan"] == 2

    def test_unknown_kind(self):
        strokes = [_stroke(1, kind="mystery")]
        bd = _kind_breakdown(strokes, set())
        assert "mystery" in bd


# ---------------------------------------------------------------------------
# stroke_parity
# ---------------------------------------------------------------------------


class TestStrokeParity:
    def test_perfect_parity(self, tmp_path: Path):
        """All strokes on disk are also committed."""
        strokes = [_stroke(i) for i in range(1, 6)]
        _make_repo(tmp_path, strokes=strokes)
        with patch("iamai.stroke_parity._committed_strokes", return_value=strokes):
            p = stroke_parity(tmp_path)
        assert p.total == 5
        assert p.committed == 5
        assert p.orphan_count == 0
        assert p.ratio == 1.0
        assert p.is_synced is True
        assert p.critical is False

    def test_some_orphans(self, tmp_path: Path):
        """3 of 10 strokes not yet committed."""
        all_strokes = [_stroke(i) for i in range(1, 11)]
        committed = [_stroke(i) for i in range(1, 8)]
        _make_repo(tmp_path, strokes=all_strokes)
        with patch("iamai.stroke_parity._committed_strokes", return_value=committed):
            p = stroke_parity(tmp_path)
        assert p.total == 10
        assert p.committed == 7
        assert p.orphan_count == 3
        assert p.orphan_seqs == [8, 9, 10]
        assert 0.0 < p.ratio < 1.0
        assert p.is_synced is False

    def test_critical_threshold(self, tmp_path: Path):
        """More than 20 orphans triggers critical flag."""
        all_strokes = [_stroke(i) for i in range(1, 51)]  # 50 strokes
        committed = [_stroke(i) for i in range(1, 29)]    # 28 committed → 22 orphans
        _make_repo(tmp_path, strokes=all_strokes)
        with patch("iamai.stroke_parity._committed_strokes", return_value=committed):
            p = stroke_parity(tmp_path)
        assert p.orphan_count == 22
        assert p.critical is True

    def test_not_critical_at_20(self, tmp_path: Path):
        """Exactly 20 orphans is not critical (threshold is > 20)."""
        all_strokes = [_stroke(i) for i in range(1, 51)]  # 50 strokes
        committed = [_stroke(i) for i in range(1, 31)]    # 30 committed → 20 orphans
        _make_repo(tmp_path, strokes=all_strokes)
        with patch("iamai.stroke_parity._committed_strokes", return_value=committed):
            p = stroke_parity(tmp_path)
        assert p.orphan_count == 20
        assert p.critical is False

    def test_empty_repo(self, tmp_path: Path):
        """No strokes file at all → perfect parity (nothing to lose)."""
        _make_repo(tmp_path)
        with patch("iamai.stroke_parity._committed_strokes", return_value=[]):
            p = stroke_parity(tmp_path)
        assert p.total == 0
        assert p.ratio == 1.0
        assert p.is_synced is True

    def test_no_commits_yet(self, tmp_path: Path):
        """Strokes on disk but nothing committed yet → all are orphans."""
        strokes = [_stroke(i) for i in range(1, 6)]
        _make_repo(tmp_path, strokes=strokes)
        with patch("iamai.stroke_parity._committed_strokes", return_value=[]):
            p = stroke_parity(tmp_path)
        assert p.total == 5
        assert p.committed == 0
        assert p.orphan_count == 5
        assert p.ratio == 0.0

    def test_by_kind_breakdown(self, tmp_path: Path):
        strokes = [
            _stroke(1, "thought"), _stroke(2, "thought"), _stroke(3, "thought"),
            _stroke(4, "note"), _stroke(5, "note"),
            _stroke(6, "devlog"),
        ]
        committed = [_stroke(1, "thought"), _stroke(2, "thought"), _stroke(4, "note")]
        _make_repo(tmp_path, strokes=strokes)
        with patch("iamai.stroke_parity._committed_strokes", return_value=committed):
            p = stroke_parity(tmp_path)
        assert p.by_kind["thought"] == {"total": 3, "committed": 2, "orphan": 1}
        assert p.by_kind["note"] == {"total": 2, "committed": 1, "orphan": 1}
        assert p.by_kind["devlog"] == {"total": 1, "committed": 0, "orphan": 1}

    def test_ratio_precision(self, tmp_path: Path):
        """Ratio should be a float with reasonable precision."""
        all_strokes = [_stroke(i) for i in range(1, 101)]
        committed = [_stroke(i) for i in range(1, 100)]
        _make_repo(tmp_path, strokes=all_strokes)
        with patch("iamai.stroke_parity._committed_strokes", return_value=committed):
            p = stroke_parity(tmp_path)
        assert abs(p.ratio - 0.99) < 0.001

    def test_custom_strokes_file(self, tmp_path: Path):
        """Support non-default strokes file paths."""
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()
        strokes = [_stroke(1), _stroke(2)]
        path = custom_dir / "my_strokes.jsonl"
        with open(path, "w") as fh:
            for s in strokes:
                fh.write(json.dumps(s) + "\n")
        with patch("iamai.stroke_parity._committed_strokes", return_value=strokes):
            p = stroke_parity(tmp_path, strokes_file="custom/my_strokes.jsonl")
        assert p.total == 2
        assert p.is_synced


# ---------------------------------------------------------------------------
# parity_summary
# ---------------------------------------------------------------------------


class TestParitySummary:
    def test_synced(self, tmp_path: Path):
        strokes = [_stroke(i) for i in range(1, 6)]
        _make_repo(tmp_path, strokes=strokes)
        with patch("iamai.stroke_parity._committed_strokes", return_value=strokes):
            s = parity_summary(tmp_path)
        assert "fully synced" in s
        assert "5/5" in s

    def test_orphans(self, tmp_path: Path):
        all_strokes = [_stroke(i) for i in range(1, 11)]
        committed = [_stroke(i) for i in range(1, 8)]
        _make_repo(tmp_path, strokes=all_strokes)
        with patch("iamai.stroke_parity._committed_strokes", return_value=committed):
            s = parity_summary(tmp_path)
        assert "orphans pending" in s
        assert "7/10" in s

    def test_single_orphan(self, tmp_path: Path):
        all_strokes = [_stroke(1), _stroke(2)]
        committed = [_stroke(1)]
        _make_repo(tmp_path, strokes=all_strokes)
        with patch("iamai.stroke_parity._committed_strokes", return_value=committed):
            s = parity_summary(tmp_path)
        assert "1 orphan pending" in s  # singular

    def test_percentage(self, tmp_path: Path):
        strokes = [_stroke(i) for i in range(1, 101)]
        committed = strokes[:99]
        _make_repo(tmp_path, strokes=strokes)
        with patch("iamai.stroke_parity._committed_strokes", return_value=committed):
            s = parity_summary(tmp_path)
        assert "99.00%" in s


# ---------------------------------------------------------------------------
# orphan_strokes
# ---------------------------------------------------------------------------


class TestOrphanStrokes:
    def test_basic(self, tmp_path: Path):
        all_strokes = [_stroke(i) for i in range(1, 11)]
        committed = [_stroke(i) for i in range(1, 8)]
        _make_repo(tmp_path, strokes=all_strokes)
        with patch("iamai.stroke_parity._committed_strokes", return_value=committed):
            orphans = orphan_strokes(tmp_path)
        assert orphans == [8, 9, 10]

    def test_none(self, tmp_path: Path):
        strokes = [_stroke(1), _stroke(2)]
        _make_repo(tmp_path, strokes=strokes)
        with patch("iamai.stroke_parity._committed_strokes", return_value=strokes):
            orphans = orphan_strokes(tmp_path)
        assert orphans == []

    def test_sorted(self, tmp_path: Path):
        """Orphans should be returned in ascending seq order even if written out of order."""
        all_strokes = [_stroke(5), _stroke(1), _stroke(3), _stroke(2), _stroke(4)]
        committed = [_stroke(1), _stroke(2)]
        _make_repo(tmp_path, strokes=all_strokes)
        with patch("iamai.stroke_parity._committed_strokes", return_value=committed):
            orphans = orphan_strokes(tmp_path)
        assert orphans == [3, 4, 5]


# ---------------------------------------------------------------------------
# parity_grade
# ---------------------------------------------------------------------------


class TestParityGrade:
    @pytest.mark.parametrize("committed_count,expected", [
        (100, "A"),  # 100/100 = 1.00
        (99, "A"),   # 99/100 = 0.99
        (96, "B"),   # 96/100 = 0.96
        (91, "C"),   # 91/100 = 0.91
        (82, "D"),   # 82/100 = 0.82
        (50, "F"),   # 50/100 = 0.50
    ])
    def test_grades(self, tmp_path: Path, committed_count: int, expected: str):
        all_strokes = [_stroke(i) for i in range(1, 101)]
        committed = all_strokes[:committed_count]
        _make_repo(tmp_path, strokes=all_strokes)
        with patch("iamai.stroke_parity._committed_strokes", return_value=committed):
            grade = parity_grade(tmp_path)
        assert grade == expected

    def test_empty_repo_is_a(self, tmp_path: Path):
        """No strokes → perfect grade."""
        _make_repo(tmp_path)
        with patch("iamai.stroke_parity._committed_strokes", return_value=[]):
            assert parity_grade(tmp_path) == "A"


# ---------------------------------------------------------------------------
# kind_parity
# ---------------------------------------------------------------------------


class TestKindParity:
    def test_existing_kind(self, tmp_path: Path):
        strokes = [
            _stroke(1, "thought"), _stroke(2, "thought"), _stroke(3, "note"),
        ]
        committed = [_stroke(1, "thought")]
        _make_repo(tmp_path, strokes=strokes)
        with patch("iamai.stroke_parity._committed_strokes", return_value=committed):
            kp = kind_parity(tmp_path, kind="thought")
        assert kp == {"total": 2, "committed": 1, "orphan": 1}

    def test_missing_kind(self, tmp_path: Path):
        strokes = [_stroke(1, "thought")]
        _make_repo(tmp_path, strokes=strokes)
        with patch("iamai.stroke_parity._committed_strokes", return_value=strokes):
            kp = kind_parity(tmp_path, kind="snippet")
        assert kp == {"total": 0, "committed": 0, "orphan": 0}


# ---------------------------------------------------------------------------
# parity_trend
# ---------------------------------------------------------------------------


class TestParityTrend:
    def test_improving(self):
        reports = [
            ParityReport(total=100, committed=90, orphan_count=10, ratio=0.90),
            ParityReport(total=100, committed=95, orphan_count=5, ratio=0.95),
            ParityReport(total=100, committed=99, orphan_count=1, ratio=0.99),
        ]
        trend = parity_trend(reports)
        assert trend["improving"] is True
        assert abs(trend["mean_ratio"] - 0.9467) < 0.01
        assert trend["min_ratio"] == 0.90
        assert trend["max_orphans"] == 10

    def test_degrading(self):
        reports = [
            ParityReport(total=100, committed=99, orphan_count=1, ratio=0.99),
            ParityReport(total=100, committed=90, orphan_count=10, ratio=0.90),
        ]
        trend = parity_trend(reports)
        assert trend["improving"] is False
        assert trend["min_ratio"] == 0.90
        assert trend["max_orphans"] == 10

    def test_empty(self):
        trend = parity_trend([])
        assert trend["mean_ratio"] == 0.0
        assert trend["improving"] is False

    def test_single_report(self):
        reports = [ParityReport(total=100, committed=95, orphan_count=5, ratio=0.95)]
        trend = parity_trend(reports)
        assert trend["improving"] is True  # last >= first when only one
        assert trend["mean_ratio"] == 0.95


# ---------------------------------------------------------------------------
# integration: full lifecycle
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_lifecycle(self, tmp_path: Path):
        """Simulate write → commit → verify cycle."""
        # Phase 1: nothing on disk, nothing committed
        _make_repo(tmp_path)
        with patch("iamai.stroke_parity._committed_strokes", return_value=[]):
            p = stroke_parity(tmp_path)
        assert p.is_synced

        # Phase 2: 5 strokes written, none committed
        strokes = [_stroke(i) for i in range(1, 6)]
        _make_repo(tmp_path, strokes=strokes)
        with patch("iamai.stroke_parity._committed_strokes", return_value=[]):
            p = stroke_parity(tmp_path)
        assert p.orphan_count == 5
        assert p.ratio == 0.0

        # Phase 3: batch commit catches up (all committed)
        with patch("iamai.stroke_parity._committed_strokes", return_value=strokes):
            p = stroke_parity(tmp_path)
            assert p.is_synced
            assert parity_grade(tmp_path) == "A"

        # Phase 4: more strokes written (partial catch-up)
        more_strokes = strokes + [_stroke(i) for i in range(6, 11)]
        _make_repo(tmp_path, strokes=more_strokes)
        with patch("iamai.stroke_parity._committed_strokes", return_value=strokes):
            p = stroke_parity(tmp_path)
        assert p.orphan_count == 5
        assert p.orphan_seqs == [6, 7, 8, 9, 10]

        # Phase 5: full catch-up
        with patch("iamai.stroke_parity._committed_strokes", return_value=more_strokes):
            p = stroke_parity(tmp_path)
        assert p.is_synced
        assert p.total == 10
