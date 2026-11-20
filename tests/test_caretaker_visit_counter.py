"""Tests for tools/caretaker_visit_counter.py — visit counting and stats."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from caretaker_visit_counter import (  # noqa: E402
    Visit,
    VisitStats,
    compute_stats,
    format_report,
    main,
    parse_visits,
)


# ---------------------------------------------------------------------------
# parse_visits
# ---------------------------------------------------------------------------


class TestParseVisits:
    def test_empty_directory(self, tmp_path: Path) -> None:
        visits = parse_visits(tmp_path)
        assert visits == []

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        visits = parse_visits(tmp_path / "nope")
        assert visits == []

    def test_finds_visit_files(self, tmp_path: Path) -> None:
        (tmp_path / "caretaker-visit-1-2026-01-01.md").write_text("# visit 1")
        (tmp_path / "caretaker-visit-2-2026-01-02.md").write_text("# visit 2")
        (tmp_path / "unrelated.md").write_text("noise")
        visits = parse_visits(tmp_path)
        assert len(visits) == 2
        assert visits[0].number == 1
        assert visits[1].number == 2

    def test_ignores_malformed_names(self, tmp_path: Path) -> None:
        (tmp_path / "caretaker-visit-abc-2026-01-01.md").write_text("bad")
        (tmp_path / "caretaker-visit-1-baddate.md").write_text("bad")
        (tmp_path / "caretaker-visit-1-2026-01-01.md").write_text("good")
        visits = parse_visits(tmp_path)
        assert len(visits) == 1

    def test_sorted_by_date_then_number(self, tmp_path: Path) -> None:
        (tmp_path / "caretaker-visit-5-2026-01-01.md").write_text("# 5")
        (tmp_path / "caretaker-visit-3-2026-01-02.md").write_text("# 3")
        (tmp_path / "caretaker-visit-7-2026-01-01.md").write_text("# 7")
        visits = parse_visits(tmp_path)
        assert [v.number for v in visits] == [5, 7, 3]


# ---------------------------------------------------------------------------
# compute_stats
# ---------------------------------------------------------------------------


def _make_visits(numbers_and_dates: list) -> list:
    return [
        Visit(
            number=n,
            date=datetime.strptime(d, "%Y-%m-%d"),
            filename=f"caretaker-visit-{n}-{d}.md",
        )
        for n, d in numbers_and_dates
    ]


class TestComputeStats:
    def test_returns_none_for_single_visit(self) -> None:
        visits = _make_visits([(1, "2026-01-01")])
        assert compute_stats(visits) is None

    def test_basic_two_visits(self) -> None:
        visits = _make_visits([(1, "2026-01-01"), (2, "2026-01-02")])
        stats = compute_stats(visits)
        assert stats is not None
        assert stats.total_visits == 2
        assert stats.longest_gap_hours == 24.0
        assert stats.median_gap_hours == 24.0

    def test_detects_long_gap(self) -> None:
        visits = _make_visits([
            (1, "2026-01-01"),
            (2, "2026-01-02"),
            (3, "2026-01-10"),  # 8-day gap from visit 2
        ])
        stats = compute_stats(visits)
        assert stats is not None
        assert stats.longest_gap_hours == pytest.approx(8 * 24, abs=1)
        assert stats.longest_gap_between == (2, 3)
        assert stats.verdict == "degraded"

    def test_healthy_verdict(self) -> None:
        # daily visits over 30 days — no gaps > 48h, stable trend
        pairs = [(i, f"2026-01-{i:02d}") for i in range(1, 29)]
        visits = _make_visits(pairs)
        stats = compute_stats(visits)
        assert stats is not None
        assert stats.verdict == "healthy"

    def test_declining_trend(self) -> None:
        # dense early, very sparse late
        pairs = []
        for i in range(1, 21):
            pairs.append((i, f"2026-01-{i:02d}"))
        # then big gaps
        pairs.append((21, "2026-03-01"))
        pairs.append((22, "2026-03-15"))
        visits = _make_visits(pairs)
        stats = compute_stats(visits, recent_window_days=30)
        assert stats is not None
        assert stats.recent_trend == "declining"

    def test_improving_trend(self) -> None:
        # sparse early, dense late
        pairs = [(1, "2026-01-01"), (2, "2026-02-01"), (3, "2026-03-01")]
        for i in range(4, 25):
            pairs.append((i, f"2026-03-{i - 3:02d}"))
        visits = _make_visits(pairs)
        stats = compute_stats(visits, recent_window_days=30)
        assert stats is not None
        assert stats.recent_trend == "improving"

    def test_coverage_ratio(self) -> None:
        # 10 visits over 9 days (Jan 1 to Jan 10)
        # theoretical max = 9 * 144 = 1296
        # coverage = 10 / 1296 ≈ 0.0077
        pairs = [(i, f"2026-01-{i:02d}") for i in range(1, 11)]
        visits = _make_visits(pairs)
        stats = compute_stats(visits)
        assert stats is not None
        expected = 10 / (9.0 * 144)
        assert stats.coverage_ratio_10min == pytest.approx(expected, rel=0.01)

    def test_observation_days_clamped_to_one(self) -> None:
        # two visits on the same day → obs_days clamped to 1.0
        visits = _make_visits([(1, "2026-01-01"), (2, "2026-01-01")])
        stats = compute_stats(visits)
        assert stats is not None
        assert stats.observation_days == 1.0

    def test_trend_stable_when_window_equals_obs(self) -> None:
        # 10 daily visits: obs_days=9, recent_window defaults to 14
        # but clamped to 9, so recent_rate == overall_rate → stable
        pairs = [(i, f"2026-01-{i:02d}") for i in range(1, 11)]
        visits = _make_visits(pairs)
        stats = compute_stats(visits, recent_window_days=14)
        assert stats is not None
        assert stats.recent_trend == "stable"


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


class TestFormatReport:
    def test_contains_key_fields(self) -> None:
        stats = VisitStats(
            total_visits=100,
            first_visit_date="2026-01-01",
            last_visit_date="2026-03-01",
            observation_days=60.0,
            visits_per_day=1.67,
            longest_gap_hours=72.0,
            longest_gap_between=(50, 51),
            median_gap_hours=24.0,
            recent_trend="stable",
            coverage_ratio_10min=0.0116,
            verdict="degraded",
        )
        report = format_report(stats)
        assert "total visits:       100" in report
        assert "degraded" in report
        assert "stable" in report
        assert "72.0h" in report


# ---------------------------------------------------------------------------
# main (integration)
# ---------------------------------------------------------------------------


class TestMain:
    def test_no_notes_dir(self, tmp_path: Path) -> None:
        rc = main(["--notes-dir", str(tmp_path / "nope")])
        assert rc == 2

    def test_too_few_visits(self, tmp_path: Path) -> None:
        (tmp_path / "caretaker-visit-1-2026-01-01.md").write_text("# 1")
        rc = main(["--notes-dir", str(tmp_path)])
        assert rc == 2

    def test_healthy_run(self, tmp_path: Path) -> None:
        for i in range(1, 11):
            (tmp_path / f"caretaker-visit-{i}-2026-01-{i:02d}.md").write_text(
                f"# {i}"
            )
        # 10 daily visits over 9 days → stable trend, max gap 24h → healthy
        rc = main(["--notes-dir", str(tmp_path)])
        assert rc == 0

    def test_json_output(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        for i in range(1, 11):
            (tmp_path / f"caretaker-visit-{i}-2026-01-{i:02d}.md").write_text(
                f"# {i}"
            )
        rc = main(["--notes-dir", str(tmp_path), "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["total_visits"] == 10
        assert "verdict" in data

    def test_degraded_exits_1(self, tmp_path: Path) -> None:
        # big gap triggers degraded verdict
        (tmp_path / "caretaker-visit-1-2026-01-01.md").write_text("# 1")
        (tmp_path / "caretaker-visit-2-2026-01-02.md").write_text("# 2")
        (tmp_path / "caretaker-visit-3-2026-03-01.md").write_text("# 3")
        rc = main(["--notes-dir", str(tmp_path)])
        assert rc == 1

    def test_custom_recent_window(self, tmp_path: Path) -> None:
        # with a very large recent window, sparse tail looks declining
        for i in range(1, 6):
            (tmp_path / f"caretaker-visit-{i}-2026-01-{i:02d}.md").write_text(
                f"# {i}"
            )
        (tmp_path / "caretaker-visit-6-2026-02-15.md").write_text("# 6")
        rc = main(["--notes-dir", str(tmp_path), "--recent-window", "7"])
        # recent 7 days only has visit 6 → declining relative to overall
        assert rc == 1
