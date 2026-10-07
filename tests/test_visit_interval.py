"""Tests for iamai.visit_interval — caretaker visit interval analysis."""

import pytest
from datetime import datetime

from iamai.visit_interval import (
    VisitIntervalAnalyzer,
    VisitRecord,
    VisitStats,
    _VISIT_RE,
)


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------

class TestFilenameParsing:
    def test_valid_filename(self):
        m = _VISIT_RE.match("caretaker-visit-74-2026-10-08.md")
        assert m is not None
        assert m.group(1) == "74"
        assert m.group(2) == "2026-10-08"

    def test_single_digit_number(self):
        m = _VISIT_RE.match("caretaker-visit-1-2026-10-03.md")
        assert m is not None
        assert m.group(1) == "1"

    def test_triple_digit_number(self):
        m = _VISIT_RE.match("caretaker-visit-100-2026-10-10.md")
        assert m is not None
        assert m.group(1) == "100"

    def test_invalid_extension(self):
        m = _VISIT_RE.match("caretaker-visit-74-2026-10-08.txt")
        assert m is None

    def test_invalid_prefix(self):
        m = _VISIT_RE.match("caretaker-visits-74-2026-10-08.md")
        assert m is None

    def test_missing_date(self):
        m = _VISIT_RE.match("caretaker-visit-74.md")
        assert m is None

    def test_path_prefix_stripped(self):
        """The regex matches basename only; analyzer uses os.path.basename."""
        m = _VISIT_RE.match("notes/caretaker-visit-74-2026-10-08.md")
        assert m is None  # regex expects basename only


# ---------------------------------------------------------------------------
# VisitRecord
# ---------------------------------------------------------------------------

class TestVisitRecord:
    def test_timestamp_parsed(self):
        r = VisitRecord(number=74, date="2026-10-08")
        assert r.timestamp == datetime(2026, 10, 8)

    def test_date_preserved(self):
        r = VisitRecord(number=1, date="2026-10-03")
        assert r.date == "2026-10-03"
        assert r.number == 1


# ---------------------------------------------------------------------------
# Analyzer: add and dedup
# ---------------------------------------------------------------------------

class TestAnalyzerAdd:
    def test_add_single(self):
        a = VisitIntervalAnalyzer()
        a.add("caretaker-visit-1-2026-10-03.md")
        assert len(a.visits) == 1

    def test_add_with_path(self):
        a = VisitIntervalAnalyzer()
        a.add("notes/caretaker-visit-1-2026-10-03.md")
        assert len(a.visits) == 1

    def test_add_invalid_ignored(self):
        a = VisitIntervalAnalyzer()
        a.add("not-a-visit.md")
        assert len(a.visits) == 0

    def test_dedup_by_number_and_date(self):
        a = VisitIntervalAnalyzer()
        a.add("caretaker-visit-1-2026-10-03.md")
        a.add("caretaker-visit-1-2026-10-03.md")
        assert len(a.visits) == 1

    def test_same_number_different_date_not_dedup(self):
        a = VisitIntervalAnalyzer()
        a.add("caretaker-visit-1-2026-10-03.md")
        a.add("caretaker-visit-1-2026-10-04.md")
        assert len(a.visits) == 2

    def test_add_many(self):
        a = VisitIntervalAnalyzer()
        a.add_many([
            "caretaker-visit-1-2026-10-03.md",
            "caretaker-visit-2-2026-10-03.md",
            "invalid.md",
        ])
        assert len(a.visits) == 2

    def test_chaining(self):
        a = VisitIntervalAnalyzer()
        result = a.add("caretaker-visit-1-2026-10-03.md")
        assert result is a


# ---------------------------------------------------------------------------
# Analyzer: sorting
# ---------------------------------------------------------------------------

class TestAnalyzerSorting:
    def test_sorted_by_date_then_number(self):
        a = VisitIntervalAnalyzer()
        a.add("caretaker-visit-3-2026-10-04.md")
        a.add("caretaker-visit-1-2026-10-03.md")
        a.add("caretaker-visit-2-2026-10-03.md")
        visits = a.visits
        assert visits[0].number == 1
        assert visits[1].number == 2
        assert visits[2].number == 3


# ---------------------------------------------------------------------------
# Compute: interval statistics
# ---------------------------------------------------------------------------

class TestCompute:
    def test_two_visits_same_day(self):
        """Two visits on the same date → interval is 0 hours."""
        a = VisitIntervalAnalyzer()
        a.add("caretaker-visit-1-2026-10-03.md")
        a.add("caretaker-visit-2-2026-10-03.md")
        stats = a.compute()
        assert stats.count == 2
        assert stats.mean_hours == 0.0
        assert stats.median_hours == 0.0
        assert stats.longest_gap_hours == 0.0

    def test_two_visits_one_day_apart(self):
        a = VisitIntervalAnalyzer()
        a.add("caretaker-visit-1-2026-10-03.md")
        a.add("caretaker-visit-2-2026-10-04.md")
        stats = a.compute()
        assert stats.count == 2
        assert stats.mean_hours == 24.0
        assert stats.median_hours == 24.0
        assert stats.min_hours == 24.0
        assert stats.max_hours == 24.0
        assert stats.longest_gap_hours == 24.0
        assert stats.longest_gap_indices == (0, 1)

    def test_three_visits_mixed_intervals(self):
        a = VisitIntervalAnalyzer()
        a.add("caretaker-visit-1-2026-10-03.md")
        a.add("caretaker-visit-2-2026-10-04.md")  # +24h
        a.add("caretaker-visit-3-2026-10-06.md")  # +48h
        stats = a.compute()
        assert stats.count == 3
        assert stats.mean_hours == pytest.approx(36.0)  # (24+48)/2
        assert stats.median_hours == 36.0  # median of [24, 48]
        assert stats.min_hours == 24.0
        assert stats.max_hours == 48.0
        assert stats.longest_gap_hours == 48.0
        assert stats.longest_gap_indices == (1, 2)

    def test_four_visits_odd_median(self):
        a = VisitIntervalAnalyzer()
        a.add("caretaker-visit-1-2026-10-03.md")
        a.add("caretaker-visit-2-2026-10-04.md")  # +24h
        a.add("caretaker-visit-3-2026-10-05.md")  # +24h
        a.add("caretaker-visit-4-2026-10-07.md")  # +48h
        stats = a.compute()
        # intervals: [24, 24, 48], sorted: [24, 24, 48], median = 24
        assert stats.median_hours == 24.0

    def test_four_visits_even_median(self):
        a = VisitIntervalAnalyzer()
        a.add("caretaker-visit-1-2026-10-03.md")
        a.add("caretaker-visit-2-2026-10-05.md")  # +48h
        a.add("caretaker-visit-3-2026-10-06.md")  # +24h
        a.add("caretaker-visit-4-2026-10-08.md")  # +48h
        stats = a.compute()
        # intervals: [48, 24, 48], sorted: [24, 48, 48], median = 48
        assert stats.median_hours == 48.0

    def test_too_few_visits_raises(self):
        a = VisitIntervalAnalyzer()
        a.add("caretaker-visit-1-2026-10-03.md")
        with pytest.raises(ValueError, match="at least 2"):
            a.compute()

    def test_empty_analyzer_raises(self):
        a = VisitIntervalAnalyzer()
        with pytest.raises(ValueError, match="at least 2"):
            a.compute()

    def test_longest_gap_identifies_correct_pair(self):
        a = VisitIntervalAnalyzer()
        a.add("caretaker-visit-1-2026-10-03.md")
        a.add("caretaker-visit-2-2026-10-04.md")  # +24h
        a.add("caretaker-visit-3-2026-10-04.md")  # +0h
        a.add("caretaker-visit-4-2026-10-10.md")  # +144h (6 days)
        stats = a.compute()
        assert stats.longest_gap_hours == 144.0
        assert stats.longest_gap_indices == (2, 3)


# ---------------------------------------------------------------------------
# VisitStats.summary
# ---------------------------------------------------------------------------

class TestStatsSummary:
    def test_summary_format(self):
        a = VisitIntervalAnalyzer()
        a.add("caretaker-visit-1-2026-10-03.md")
        a.add("caretaker-visit-2-2026-10-04.md")
        a.add("caretaker-visit-3-2026-10-06.md")
        stats = a.compute()
        s = stats.summary()
        assert "3 visits" in s
        assert "mean interval" in s
        assert "longest gap" in s


# ---------------------------------------------------------------------------
# from_directory
# ---------------------------------------------------------------------------

class TestFromDirectory:
    def test_nonexistent_directory(self, tmp_path):
        a = VisitIntervalAnalyzer.from_directory(str(tmp_path / "nonexistent"))
        assert len(a.visits) == 0

    def test_scans_directory(self, tmp_path):
        (tmp_path / "caretaker-visit-1-2026-10-03.md").write_text("# visit 1")
        (tmp_path / "caretaker-visit-2-2026-10-04.md").write_text("# visit 2")
        (tmp_path / "other-file.md").write_text("# not a visit")
        a = VisitIntervalAnalyzer.from_directory(str(tmp_path))
        assert len(a.visits) == 2

    def test_ignores_non_matching_files(self, tmp_path):
        (tmp_path / "caretaker-visit-1-2026-10-03.md").write_text("# visit 1")
        (tmp_path / "caretaker-visits-summary.md").write_text("# summary")
        (tmp_path / "README.md").write_text("# readme")
        a = VisitIntervalAnalyzer.from_directory(str(tmp_path))
        assert len(a.visits) == 1
