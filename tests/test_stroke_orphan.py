"""Tests for iamai.stroke_orphan — orphan stroke detection."""

import pytest
import time
from datetime import datetime, timezone, timedelta

from iamai.stroke_orphan import (
    OrphanReport,
    detect_orphans,
    _classify_severity,
    _load_jsonl,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stroke(seq: int, at_epoch: float) -> dict:
    """Create a stroke dict from a seq and Unix epoch."""
    dt = datetime.fromtimestamp(at_epoch, tz=timezone.utc)
    return {
        "seq": seq,
        "at": dt.isoformat(),
        "kind": "thought",
        "text": f"stroke {seq}",
    }


NOW = time.time()


def _stroke_ago(seq: int, seconds_ago: float) -> dict:
    """Create a stroke whose timestamp is ``seconds_ago`` before NOW."""
    return _make_stroke(seq, NOW - seconds_ago)


# ---------------------------------------------------------------------------
# _classify_severity
# ---------------------------------------------------------------------------

class TestClassifySeverity:
    def test_clean_when_zero_orphans(self):
        assert _classify_severity(0, 0.0) == "CLEAN"

    def test_clean_even_with_large_age(self):
        # count=0 always CLEAN regardless of age
        assert _classify_severity(0, 9999.0) == "CLEAN"

    def test_fresh_when_young(self):
        assert _classify_severity(5, 60.0) == "FRESH"

    def test_fresh_boundary(self):
        assert _classify_severity(1, 119.0) == "FRESH"

    def test_warm_at_120s(self):
        assert _classify_severity(3, 120.0) == "WARM"

    def test_warm_under_600(self):
        assert _classify_severity(10, 599.0) == "WARM"

    def test_stale_at_600(self):
        assert _classify_severity(5, 600.0) == "STALE"

    def test_stale_under_1800(self):
        assert _classify_severity(20, 1799.0) == "STALE"

    def test_at_risk_at_1800(self):
        assert _classify_severity(1, 1800.0) == "AT_RISK"

    def test_at_risk_large(self):
        assert _classify_severity(100, 3600.0) == "AT_RISK"


# ---------------------------------------------------------------------------
# detect_orphans — CLEAN cases
# ---------------------------------------------------------------------------

class TestDetectOrphansClean:
    def test_both_empty(self):
        result = detect_orphans([], [], now=NOW)
        assert result.severity == "CLEAN"
        assert result.orphan_count == 0
        assert result.oldest_age_s == 0.0

    def test_all_committed(self):
        strokes = [_stroke_ago(i, 300) for i in range(1, 6)]
        result = detect_orphans(strokes, strokes, now=NOW)
        assert result.severity == "CLEAN"
        assert result.orphan_count == 0

    def test_committed_superset(self):
        """Committed has MORE strokes than working (unusual but valid)."""
        working = [_stroke_ago(i, 300) for i in range(1, 4)]
        committed = [_stroke_ago(i, 300) for i in range(1, 8)]
        result = detect_orphans(working, committed, now=NOW)
        assert result.severity == "CLEAN"


# ---------------------------------------------------------------------------
# detect_orphans — orphans exist
# ---------------------------------------------------------------------------

class TestDetectOrphansFound:
    def test_single_orphan(self):
        working = [_stroke_ago(1, 60), _stroke_ago(2, 30)]
        committed = [_stroke_ago(1, 60)]
        result = detect_orphans(working, committed, now=NOW)
        assert result.orphan_count == 1
        assert result.orphan_seqs == [2]
        assert 29 <= result.oldest_age_s <= 31

    def test_multiple_orphans(self):
        working = [_stroke_ago(i, 300 - i * 10) for i in range(1, 6)]
        committed = [_stroke_ago(1, 290)]
        result = detect_orphans(working, committed, now=NOW)
        assert result.orphan_count == 4
        assert sorted(result.orphan_seqs) == [2, 3, 4, 5]

    def test_oldest_age(self):
        working = [_stroke_ago(1, 500), _stroke_ago(2, 100)]
        committed = []
        result = detect_orphans(working, committed, now=NOW)
        assert result.orphan_count == 2
        assert 499 <= result.oldest_age_s <= 501
        assert 99 <= result.newest_age_s <= 101

    def test_fresh_severity(self):
        working = [_stroke_ago(1, 30)]
        committed = []
        result = detect_orphans(working, committed, now=NOW)
        assert result.severity == "FRESH"

    def test_warm_severity(self):
        working = [_stroke_ago(1, 200)]
        committed = []
        result = detect_orphans(working, committed, now=NOW)
        assert result.severity == "WARM"

    def test_stale_severity(self):
        working = [_stroke_ago(1, 900)]
        committed = []
        result = detect_orphans(working, committed, now=NOW)
        assert result.severity == "STALE"

    def test_at_risk_severity(self):
        working = [_stroke_ago(1, 2000)]
        committed = []
        result = detect_orphans(working, committed, now=NOW)
        assert result.severity == "AT_RISK"


# ---------------------------------------------------------------------------
# OrphanReport
# ---------------------------------------------------------------------------

class TestOrphanReport:
    def test_frozen(self):
        report = OrphanReport(
            orphan_count=1,
            orphan_seqs=[5],
            oldest_age_s=100.0,
            newest_age_s=100.0,
            severity="FRESH",
        )
        with pytest.raises(Exception):
            report.severity = "STALE"  # type: ignore[misc]

    def test_to_dict(self):
        report = OrphanReport(
            orphan_count=2,
            orphan_seqs=[3, 4],
            oldest_age_s=456.789,
            newest_age_s=12.345,
            severity="WARM",
        )
        d = report.to_dict()
        assert d["orphan_count"] == 2
        assert d["orphan_seqs"] == [3, 4]
        assert d["oldest_age_s"] == 456.8
        assert d["newest_age_s"] == 12.3
        assert d["severity"] == "WARM"

    def test_to_dict_clean(self):
        report = OrphanReport(
            orphan_count=0,
            orphan_seqs=[],
            oldest_age_s=0.0,
            newest_age_s=0.0,
            severity="CLEAN",
        )
        d = report.to_dict()
        assert d["orphan_count"] == 0
        assert d["orphan_seqs"] == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_z_suffix_timestamp(self):
        """ISO timestamps ending in Z should parse correctly."""
        working = [{"seq": 1, "at": "2026-11-09T00:00:00Z", "kind": "thought", "text": "x"}]
        committed = []
        # Use a known now to get predictable age
        fixed_now = datetime(2026, 11, 9, 0, 5, 0, tzinfo=timezone.utc).timestamp()
        result = detect_orphans(working, committed, now=fixed_now)
        assert result.orphan_count == 1
        assert 299 <= result.oldest_age_s <= 301

    def test_empty_committed(self):
        working = [_stroke_ago(i, 60) for i in range(1, 4)]
        result = detect_orphans(working, [], now=NOW)
        assert result.orphan_count == 3

    def test_large_batch(self):
        """Stress test with 1000 strokes."""
        working = [_stroke_ago(i, 10 * i) for i in range(1, 1001)]
        committed = [_stroke_ago(i, 10 * i) for i in range(1, 901)]
        result = detect_orphans(working, committed, now=NOW)
        assert result.orphan_count == 100
        assert len(result.orphan_seqs) == 100

    def test_duplicate_seqs_in_working(self):
        """If working has duplicate seqs, each orphan counted once per entry."""
        s = _stroke_ago(1, 60)
        working = [s, s]
        committed = []
        result = detect_orphans(working, committed, now=NOW)
        # Both entries are orphans (same seq but both are uncommitted)
        assert result.orphan_count == 2

    def test_seq_type_mismatch(self):
        """Committed seqs as ints, working seqs as ints — should match."""
        working = [{"seq": 1, "at": _stroke_ago(1, 60)["at"], "kind": "t", "text": "x"}]
        committed = [{"seq": 1, "at": _stroke_ago(1, 60)["at"], "kind": "t", "text": "x"}]
        result = detect_orphans(working, committed, now=NOW)
        assert result.severity == "CLEAN"


# ---------------------------------------------------------------------------
# _load_jsonl
# ---------------------------------------------------------------------------

class TestLoadJsonl:
    def test_nonexistent_file(self, tmp_path):
        result = _load_jsonl(tmp_path / "nope.jsonl")
        assert result == []

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        assert _load_jsonl(p) == []

    def test_valid_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            '{"seq": 1, "at": "2026-01-01T00:00:00+00:00", "kind": "thought", "text": "a"}',
            '{"seq": 2, "at": "2026-01-01T00:01:00+00:00", "kind": "thought", "text": "b"}',
        ]
        p.write_text("\n".join(lines))
        result = _load_jsonl(p)
        assert len(result) == 2
        assert result[0]["seq"] == 1
        assert result[1]["text"] == "b"

    def test_blank_lines_skipped(self, tmp_path):
        p = tmp_path / "messy.jsonl"
        p.write_text('\n{"seq": 1, "at": "2026-01-01T00:00:00+00:00", "kind": "t", "text": "x"}\n\n')
        result = _load_jsonl(p)
        assert len(result) == 1
