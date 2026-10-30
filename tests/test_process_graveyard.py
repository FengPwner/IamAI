"""Tests for iamai.process_graveyard module.

Comprehensive test suite covering:
- record_death: writing events to the graveyard file
- load_deaths: filtering by writer, time window
- mean_lifespan: computation with valid, empty, and malformed data
- death_rate: rate calculation
- clustering_score: Gini-based clustering measurement
- classify_verdict: band classification
- analyse: full integration report
- reset: cleanup for test isolation
"""

import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.process_graveyard import (
    DATA_DIR,
    GRAVEYARD_FILE,
    analyse,
    classify_verdict,
    clustering_score,
    death_rate,
    load_deaths,
    mean_lifespan,
    record_death,
    reset,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_graveyard(tmp_path, monkeypatch):
    """Redirect graveyard to a temp file for each test."""
    tmp_file = tmp_path / "process_graveyard.jsonl"
    monkeypatch.setattr("iamai.process_graveyard.GRAVEYARD_FILE", tmp_file)
    monkeypatch.setattr("iamai.process_graveyard.DATA_DIR", tmp_path)
    yield tmp_file
    # cleanup handled by tmp_path


def _write_events(events: list[dict], filepath: Path) -> None:
    """Helper to write pre-built events to a graveyard file."""
    with open(filepath, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def _make_death(
    ts_offset_minutes: float = 0,
    lifespan_seconds: float = 3600,
    writer: str = "qwen",
    pid: int = 12345,
    cause: str = "signal",
) -> dict:
    """Create a death event with a timestamp relative to now."""
    now = datetime.now(timezone.utc)
    ts = now - timedelta(minutes=ts_offset_minutes)
    return {
        "ts": ts.isoformat(),
        "writer": writer,
        "pid": pid,
        "lifespan_seconds": lifespan_seconds,
        "cause": cause,
        "restart_after_seconds": 30,
        "note": "",
    }


# ---------------------------------------------------------------------------
# record_death
# ---------------------------------------------------------------------------


class TestRecordDeath:
    def test_basic_record(self, clean_graveyard):
        event = record_death(writer="qwen", pid=100, lifespan_seconds=120)
        assert event["writer"] == "qwen"
        assert event["pid"] == 100
        assert event["lifespan_seconds"] == 120
        assert clean_graveyard.exists()

    def test_record_appends(self, clean_graveyard):
        record_death(writer="qwen", pid=1)
        record_death(writer="qwen", pid=2)
        record_death(writer="qwen", pid=3)
        lines = clean_graveyard.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_record_with_all_fields(self, clean_graveyard):
        event = record_death(
            writer="qwen",
            pid=999,
            lifespan_seconds=7200,
            cause="oom",
            restart_after_seconds=60,
            note="memory leak suspected",
        )
        assert event["cause"] == "oom"
        assert event["restart_after_seconds"] == 60
        assert event["note"] == "memory leak suspected"

    def test_record_none_values(self, clean_graveyard):
        event = record_death(writer="qwen", pid=None, lifespan_seconds=None)
        assert event["pid"] is None
        assert event["lifespan_seconds"] is None


# ---------------------------------------------------------------------------
# load_deaths
# ---------------------------------------------------------------------------


class TestLoadDeaths:
    def test_load_empty(self, clean_graveyard):
        # No file exists
        deaths = load_deaths()
        assert deaths == []

    def test_load_all(self, clean_graveyard):
        events = [_make_death(ts_offset_minutes=i * 60) for i in range(5)]
        _write_events(events, clean_graveyard)
        deaths = load_deaths()
        assert len(deaths) == 5

    def test_filter_by_writer(self, clean_graveyard):
        events = [
            _make_death(writer="qwen", ts_offset_minutes=30),
            _make_death(writer="doubao", ts_offset_minutes=60),
            _make_death(writer="qwen", ts_offset_minutes=90),
        ]
        _write_events(events, clean_graveyard)
        deaths = load_deaths(writer="qwen")
        assert len(deaths) == 2
        assert all(d["writer"] == "qwen" for d in deaths)

    def test_filter_by_window(self, clean_graveyard):
        events = [
            _make_death(ts_offset_minutes=30),   # within 2h
            _make_death(ts_offset_minutes=90),   # within 2h
            _make_death(ts_offset_minutes=180),  # outside 2h
        ]
        _write_events(events, clean_graveyard)
        deaths = load_deaths(window_hours=2.0)
        assert len(deaths) == 2

    def test_malformed_lines_skipped(self, clean_graveyard):
        with open(clean_graveyard, "w") as f:
            f.write(json.dumps(_make_death()) + "\n")
            f.write("not valid json\n")
            f.write("\n")  # empty line
            f.write(json.dumps(_make_death(ts_offset_minutes=60)) + "\n")
        deaths = load_deaths()
        assert len(deaths) == 2


# ---------------------------------------------------------------------------
# mean_lifespan
# ---------------------------------------------------------------------------


class TestMeanLifespan:
    def test_basic(self):
        deaths = [
            {"lifespan_seconds": 100},
            {"lifespan_seconds": 200},
            {"lifespan_seconds": 300},
        ]
        assert mean_lifespan(deaths) == 200.0

    def test_single(self):
        assert mean_lifespan([{"lifespan_seconds": 42}]) == 42.0

    def test_empty(self):
        assert mean_lifespan([]) is None

    def test_skips_missing(self):
        deaths = [
            {"lifespan_seconds": 100},
            {"lifespan_seconds": None},
            {"cause": "no lifespan field"},
            {"lifespan_seconds": 200},
        ]
        assert mean_lifespan(deaths) == 150.0

    def test_skips_zero_and_negative(self):
        deaths = [
            {"lifespan_seconds": 100},
            {"lifespan_seconds": 0},
            {"lifespan_seconds": -5},
            {"lifespan_seconds": 300},
        ]
        assert mean_lifespan(deaths) == 200.0


# ---------------------------------------------------------------------------
# death_rate
# ---------------------------------------------------------------------------


class TestDeathRate:
    def test_basic(self):
        deaths = [{}] * 10
        assert death_rate(deaths, 2.0) == 5.0

    def test_zero_window(self):
        assert death_rate([{}, {}, {}], 0.0) == 0.0

    def test_empty_deaths(self):
        assert death_rate([], 24.0) == 0.0

    def test_single_death(self):
        assert death_rate([{}], 1.0) == 1.0


# ---------------------------------------------------------------------------
# clustering_score
# ---------------------------------------------------------------------------


class TestClusteringScore:
    def test_empty(self):
        assert clustering_score([]) == 0.0

    def test_single_death(self):
        assert clustering_score([_make_death()]) == 0.0

    def test_evenly_spread(self):
        # Deaths every 60 minutes over 10 hours — should be low clustering
        events = [_make_death(ts_offset_minutes=i * 60) for i in range(10)]
        score = clustering_score(events, bucket_minutes=60)
        assert score < 0.3

    def test_clustered(self):
        # All deaths within 1 minute — should be high clustering
        events = [_make_death(ts_offset_minutes=i * 0.1) for i in range(20)]
        score = clustering_score(events, bucket_minutes=10)
        assert score > 0.5

    def test_two_clusters(self):
        # Deaths in two groups far apart
        events = (
            [_make_death(ts_offset_minutes=i, pid=100 + i) for i in range(5)]
            + [_make_death(ts_offset_minutes=300 + i, pid=200 + i) for i in range(5)]
        )
        score = clustering_score(events, bucket_minutes=10)
        # Two clusters should give moderate clustering
        assert 0.0 < score < 1.0

    def test_malformed_timestamps(self):
        events = [
            {"ts": "not-a-date", "writer": "qwen"},
            _make_death(ts_offset_minutes=30),
            _make_death(ts_offset_minutes=60),
        ]
        # Should not raise, just skip the bad one
        score = clustering_score(events)
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# classify_verdict
# ---------------------------------------------------------------------------


class TestClassifyVerdict:
    def test_stable(self):
        assert classify_verdict(0.0) == "stable"
        assert classify_verdict(0.05) == "stable"
        assert classify_verdict(0.09) == "stable"

    def test_mild(self):
        assert classify_verdict(0.1) == "mild"
        assert classify_verdict(0.3) == "mild"
        assert classify_verdict(0.49) == "mild"

    def test_churny(self):
        assert classify_verdict(0.5) == "churny"
        assert classify_verdict(1.0) == "churny"
        assert classify_verdict(1.99) == "churny"

    def test_turbulent(self):
        assert classify_verdict(2.0) == "turbulent"
        assert classify_verdict(10.0) == "turbulent"

    def test_boundary_exact(self):
        assert classify_verdict(0.1) == "mild"
        assert classify_verdict(0.5) == "churny"
        assert classify_verdict(2.0) == "turbulent"


# ---------------------------------------------------------------------------
# analyse (integration)
# ---------------------------------------------------------------------------


class TestAnalyse:
    def test_empty_graveyard(self, clean_graveyard):
        report = analyse(window_hours=24.0)
        assert report["death_count"] == 0
        assert report["verdict"] == "stable"
        assert report["death_rate_per_hour"] == 0.0
        assert report["clustering_score"] == 0.0
        assert report["mean_lifespan_minutes"] is None
        assert report["last_death_age_minutes"] is None

    def test_with_events(self, clean_graveyard):
        events = [
            _make_death(ts_offset_minutes=30, lifespan_seconds=1800, cause="signal"),
            _make_death(ts_offset_minutes=60, lifespan_seconds=3600, cause="oom"),
            _make_death(ts_offset_minutes=90, lifespan_seconds=900, cause="signal"),
        ]
        _write_events(events, clean_graveyard)

        report = analyse(window_hours=24.0)
        assert report["death_count"] == 3
        assert report["mean_lifespan_minutes"] == pytest.approx(35.0)  # (1800+3600+900)/3/60
        assert report["death_rate_per_hour"] > 0
        assert report["verdict"] in ("stable", "mild", "churny", "turbulent")
        assert "signal" in report["cause_distribution"]
        assert report["cause_distribution"]["signal"] == 2
        assert report["cause_distribution"]["oom"] == 1

    def test_window_filtering(self, clean_graveyard):
        events = [
            _make_death(ts_offset_minutes=30, lifespan_seconds=1800),
            _make_death(ts_offset_minutes=120, lifespan_seconds=7200),
            _make_death(ts_offset_minutes=300, lifespan_seconds=18000),
        ]
        _write_events(events, clean_graveyard)

        report = analyse(window_hours=2.0)  # only first event within 2h
        assert report["death_count"] == 1

    def test_last_death_age(self, clean_graveyard):
        events = [_make_death(ts_offset_minutes=30, lifespan_seconds=1800)]
        _write_events(events, clean_graveyard)

        report = analyse(window_hours=24.0)
        assert report["last_death_age_minutes"] is not None
        assert report["last_death_age_minutes"] >= 29  # approximately 30 min ago

    def test_custom_bucket(self, clean_graveyard):
        events = [_make_death(ts_offset_minutes=i * 5) for i in range(10)]
        _write_events(events, clean_graveyard)

        report_small = analyse(window_hours=24.0, bucket_minutes=5)
        report_large = analyse(window_hours=24.0, bucket_minutes=60)
        # Both should produce valid scores
        assert 0.0 <= report_small["clustering_score"] <= 1.0
        assert 0.0 <= report_large["clustering_score"] <= 1.0

    def test_report_structure(self, clean_graveyard):
        """Verify all expected keys are present."""
        report = analyse()
        expected_keys = {
            "death_count",
            "mean_lifespan_minutes",
            "death_rate_per_hour",
            "clustering_score",
            "last_death_age_minutes",
            "verdict",
            "cause_distribution",
        }
        assert set(report.keys()) == expected_keys


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_removes_file(self, clean_graveyard):
        record_death(writer="qwen", pid=1)
        assert clean_graveyard.exists()
        reset()
        assert not clean_graveyard.exists()

    def test_reset_no_file(self, clean_graveyard):
        # Should not raise when file doesn't exist
        reset()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_naive_timestamp(self, clean_graveyard):
        """Events without timezone info should still be loadable."""
        event = {
            "ts": "2026-10-28T01:00:00",  # naive, no tz
            "writer": "qwen",
            "pid": 100,
            "lifespan_seconds": 600,
            "cause": "unknown",
        }
        _write_events([event], clean_graveyard)
        deaths = load_deaths(window_hours=9999)
        assert len(deaths) == 1

    def test_all_same_cause(self, clean_graveyard):
        events = [_make_death(cause="oom", ts_offset_minutes=i * 30) for i in range(5)]
        _write_events(events, clean_graveyard)
        report = analyse(window_hours=24.0)
        assert report["cause_distribution"] == {"oom": 5}

    def test_zero_lifespan_events(self, clean_graveyard):
        events = [
            _make_death(lifespan_seconds=0, ts_offset_minutes=30),
            _make_death(lifespan_seconds=0, ts_offset_minutes=60),
        ]
        _write_events(events, clean_graveyard)
        report = analyse(window_hours=24.0)
        # Zero lifespans should be excluded from mean
        assert report["mean_lifespan_minutes"] is None
