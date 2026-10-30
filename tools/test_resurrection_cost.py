#!/usr/bin/env python3
"""Tests for resurrection_cost.py."""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from resurrection_cost import load_events, compute_cost


def make_graveyard(events):
    """Write events to a temp jsonl file, return path."""
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
    return path


def test_empty_graveyard():
    path = make_graveyard([])
    try:
        events = load_events(path, 24)
        metrics = compute_cost(events, 24)
        assert metrics["restart_count"] == 0
        assert metrics["death_count"] == 0
        assert metrics["overhead_pct"] == 0.0
        print("  PASS: empty graveyard")
    finally:
        os.unlink(path)


def test_single_restart_cycle():
    now = datetime.utcnow()
    events = [
        {"event": "death", "timestamp": (now - timedelta(hours=2)).isoformat()},
        {"event": "restart", "timestamp": (now - timedelta(hours=2) + timedelta(seconds=45)).isoformat()},
    ]
    path = make_graveyard(events)
    try:
        loaded = load_events(path, 24)
        metrics = compute_cost(loaded, 24)
        assert metrics["restart_count"] == 1
        assert metrics["death_count"] == 1
        assert metrics["mean_recovery_sec"] == 45.0
        assert metrics["overhead_pct"] > 0
        print("  PASS: single restart cycle")
    finally:
        os.unlink(path)


def test_multiple_restarts():
    now = datetime.utcnow()
    events = []
    for i in range(5):
        death_time = now - timedelta(hours=10 - i * 2)
        events.append({"event": "death", "timestamp": death_time.isoformat()})
        events.append({
            "event": "restart",
            "timestamp": (death_time + timedelta(seconds=30 + i * 10)).isoformat(),
        })
    path = make_graveyard(events)
    try:
        loaded = load_events(path, 24)
        metrics = compute_cost(loaded, 24)
        assert metrics["restart_count"] == 5
        assert metrics["death_count"] == 5
        assert metrics["mean_recovery_sec"] == 50.0  # (30+40+50+60+70)/5
        print("  PASS: multiple restarts")
    finally:
        os.unlink(path)


def test_old_events_excluded():
    old_time = datetime.utcnow() - timedelta(hours=48)
    events = [
        {"event": "death", "timestamp": old_time.isoformat()},
        {"event": "restart", "timestamp": (old_time + timedelta(seconds=60)).isoformat()},
    ]
    path = make_graveyard(events)
    try:
        loaded = load_events(path, 24)
        metrics = compute_cost(loaded, 24)
        assert metrics["restart_count"] == 0
        assert metrics["death_count"] == 0
        print("  PASS: old events excluded")
    finally:
        os.unlink(path)


def test_malformed_lines():
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        f.write("not json\n")
        f.write('{"event": "death", "timestamp": "bad-date"}\n')
        f.write(json.dumps({
            "event": "restart",
            "timestamp": datetime.utcnow().isoformat(),
        }) + "\n")
    try:
        loaded = load_events(path, 24)
        # only the valid restart event should be loaded
        assert len(loaded) == 1
        assert loaded[0]["event"] == "restart"
        print("  PASS: malformed lines handled")
    finally:
        os.unlink(path)


if __name__ == "__main__":
    print("Running resurrection_cost tests...")
    test_empty_graveyard()
    test_single_restart_cycle()
    test_multiple_restarts()
    test_old_events_excluded()
    test_malformed_lines()
    print("All 5 tests passed.")
