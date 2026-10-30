"""tests for stall_cluster_detector.py — stall cluster analysis."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from stall_cluster_detector import (
    StallEvent,
    StallCluster,
    detect_stall_events,
    cluster_stalls,
    forecast_next_stall,
)


def _ts(minutes_ago: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)


# ---------------------------------------------------------------------------
# StallEvent basics
# ---------------------------------------------------------------------------

def test_stall_event_midpoint():
    e = StallEvent(
        before_ts=_ts(60),
        after_ts=_ts(30),
        gap_seconds=1800,
    )
    mid = e.midpoint
    # midpoint should be between before and after
    assert e.before_ts <= mid <= e.after_ts


def test_stall_event_large_gap():
    e = StallEvent(
        before_ts=_ts(720),   # 12 hours ago
        after_ts=_ts(600),    # 10 hours ago
        gap_seconds=7200,
    )
    assert e.gap_seconds == 7200


# ---------------------------------------------------------------------------
# detect_stall_events
# ---------------------------------------------------------------------------

def test_detect_no_stalls():
    # entries every 5 minutes — well under the 600s threshold
    timestamps = [_ts(i * 5) for i in range(20, -1, -1)]
    events = detect_stall_events(timestamps, gap_threshold=600)
    assert len(events) == 0


def test_detect_single_stall():
    # normal cadence, then a 20-minute gap, then normal again
    timestamps = []
    for i in range(10):
        timestamps.append(_ts(60 - i * 2))  # every 2 min
    # 20-minute gap
    timestamps.append(_ts(40 - 20))  # 60 min ago
    timestamps.append(_ts(30))
    timestamps = sorted(timestamps)

    events = detect_stall_events(timestamps, gap_threshold=600)
    assert len(events) >= 1
    assert events[0].gap_seconds > 600


def test_detect_multiple_stalls():
    timestamps = []
    base = datetime.now(timezone.utc)
    # cluster 1: entries every 2 min
    for i in range(5):
        timestamps.append(base - timedelta(hours=10, minutes=i * 2))
    # 30-min gap (stall)
    timestamps.append(base - timedelta(hours=9, minutes=30))
    # cluster 2: entries every 2 min
    for i in range(5):
        timestamps.append(base - timedelta(hours=9, minutes=30 + i * 2))
    # another 30-min gap
    timestamps.append(base - timedelta(hours=8, minutes=30))

    timestamps = sorted(timestamps)
    events = detect_stall_events(timestamps, gap_threshold=600)
    assert len(events) >= 2


# ---------------------------------------------------------------------------
# StallCluster
# ---------------------------------------------------------------------------

def test_cluster_single_event():
    c = StallCluster(events=[StallEvent(_ts(60), _ts(30), 1800)])
    assert c.count == 1
    assert c.intervals == []
    assert c.median_interval == 0.0
    assert c.is_accelerating is False


def test_cluster_two_events():
    events = [
        StallEvent(_ts(120), _ts(90), 1800),
        StallEvent(_ts(60), _ts(30), 1800),
    ]
    c = StallCluster(events=events)
    assert c.count == 2
    assert len(c.intervals) == 1
    assert c.is_accelerating is False  # only one interval, can't tell


def test_cluster_accelerating():
    # intervals getting shorter: 10h, 6h, 2h
    base = datetime.now(timezone.utc)
    events = [
        StallEvent(
            before_ts=base - timedelta(hours=24),
            after_ts=base - timedelta(hours=23),
            gap_seconds=3600,
        ),
        StallEvent(
            before_ts=base - timedelta(hours=14),
            after_ts=base - timedelta(hours=13),
            gap_seconds=3600,
        ),
        StallEvent(
            before_ts=base - timedelta(hours=8),
            after_ts=base - timedelta(hours=7),
            gap_seconds=3600,
        ),
        StallEvent(
            before_ts=base - timedelta(hours=6),
            after_ts=base - timedelta(hours=5),
            gap_seconds=3600,
        ),
    ]
    c = StallCluster(events=events)
    assert c.count == 4
    # first half intervals > second half intervals
    assert c.is_accelerating is True


def test_cluster_stable_cadence():
    # equal intervals: 6h, 6h, 6h, 6h
    base = datetime.now(timezone.utc)
    events = []
    for h in [24, 18, 12, 6]:
        events.append(StallEvent(
            before_ts=base - timedelta(hours=h + 1),
            after_ts=base - timedelta(hours=h),
            gap_seconds=3600,
        ))
    c = StallCluster(events=events)
    assert c.is_accelerating is False


def test_median_interval_odd():
    events = [
        StallEvent(_ts(100), _ts(90), 600),
        StallEvent(_ts(60), _ts(50), 600),
        StallEvent(_ts(30), _ts(20), 600),
    ]
    c = StallCluster(events=events)
    assert c.median_interval > 0


# ---------------------------------------------------------------------------
# cluster_stalls
# ---------------------------------------------------------------------------

def test_cluster_stalls_empty():
    assert cluster_stalls([]) == []


def test_cluster_stalls_single_group():
    base = datetime.now(timezone.utc)
    events = [
        StallEvent(base - timedelta(hours=2), base - timedelta(hours=1, minutes=50), 600),
        StallEvent(base - timedelta(hours=1, minutes=30), base - timedelta(hours=1, minutes=20), 600),
    ]
    clusters = cluster_stalls(events, max_cluster_gap=86400)
    assert len(clusters) == 1
    assert clusters[0].count == 2


def test_cluster_stalls_two_groups():
    base = datetime.now(timezone.utc)
    events = [
        StallEvent(base - timedelta(days=5), base - timedelta(days=4, hours=23), 3600),
        StallEvent(base - timedelta(days=3), base - timedelta(days=2, hours=23), 3600),
    ]
    # 2-day gap between events > 1-day cluster gap
    clusters = cluster_stalls(events, max_cluster_gap=86400)
    assert len(clusters) == 2


# ---------------------------------------------------------------------------
# forecast_next_stall
# ---------------------------------------------------------------------------

def test_forecast_no_clusters():
    result = forecast_next_stall([])
    assert result["forecast"] == "no data"
    assert result["confidence"] == "low"


def test_forecast_single_stall_cluster():
    c = StallCluster(events=[StallEvent(_ts(60), _ts(30), 1800)])
    result = forecast_next_stall([c])
    # single event in cluster -> insufficient data
    assert result["forecast"] == "insufficient data"


def test_forecast_accelerating():
    base = datetime.now(timezone.utc)
    events = [
        StallEvent(base - timedelta(hours=20), base - timedelta(hours=19), 3600),
        StallEvent(base - timedelta(hours=12), base - timedelta(hours=11), 3600),
        StallEvent(base - timedelta(hours=7), base - timedelta(hours=6), 3600),
        StallEvent(base - timedelta(hours=5), base - timedelta(hours=4), 3600),
    ]
    c = StallCluster(events=events)
    result = forecast_next_stall([c])
    assert result["confidence"] in ("medium", "low")
    assert "forecast" in result


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

def test_empty_timestamps():
    events = detect_stall_events([], gap_threshold=600)
    assert events == []


def test_single_timestamp():
    events = detect_stall_events([datetime.now(timezone.utc)], gap_threshold=600)
    assert events == []


def test_all_same_timestamp():
    ts = datetime.now(timezone.utc)
    events = detect_stall_events([ts, ts, ts], gap_threshold=600)
    assert events == []
