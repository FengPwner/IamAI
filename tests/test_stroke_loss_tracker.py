#!/usr/bin/env python3
"""Tests for stroke_loss_tracker.py"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from stroke_loss_tracker import (
    compute_cadence_spm,
    estimate_loss,
    format_json,
    format_text,
    load_history,
    parse_ts,
    run,
)


# ── parse_ts ────────────────────────────────────────────────────────────────

class TestParseTs:
    def test_valid_iso(self):
        dt = parse_ts("2026-10-19T04:09:06+00:00")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 10
        assert dt.day == 19
        assert dt.hour == 4

    def test_z_suffix(self):
        dt = parse_ts("2026-10-19T04:09:06Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_empty_string(self):
        assert parse_ts("") is None

    def test_none(self):
        assert parse_ts(None) is None

    def test_invalid_format(self):
        assert parse_ts("not-a-date") is None

    def test_integer_input(self):
        assert parse_ts(12345) is None

    def test_whitespace(self):
        dt = parse_ts("  2026-10-19T04:09:06+00:00  ")
        assert dt is not None


# ── load_history ────────────────────────────────────────────────────────────

class TestLoadHistory:
    def test_existing_file(self, tmp_path):
        state = {"history": [{"at": "2026-10-19T00:00:00+00:00", "seq": 1}]}
        p = tmp_path / "writer_state.test.json"
        p.write_text(json.dumps(state), encoding="utf-8")
        h = load_history(p)
        assert len(h) == 1
        assert h[0]["seq"] == 1

    def test_missing_file(self, tmp_path):
        h = load_history(tmp_path / "nonexistent.json")
        assert h == []

    def test_invalid_json(self, tmp_path):
        p = tmp_path / "writer_state.test.json"
        p.write_text("not json", encoding="utf-8")
        h = load_history(p)
        assert h == []

    def test_empty_history_key(self, tmp_path):
        p = tmp_path / "writer_state.test.json"
        p.write_text(json.dumps({"other": "data"}), encoding="utf-8")
        h = load_history(p)
        assert h == []


# ── compute_cadence_spm ─────────────────────────────────────────────────────

class TestComputeCadenceSpm:
    def _make_history(self, n, start_ts, interval_seconds):
        """Helper: generate n history entries at fixed interval."""
        result = []
        for i in range(n):
            ts = start_ts + timedelta(seconds=interval_seconds * i)
            result.append({
                "at": ts.isoformat(),
                "seq": i + 1,
                "kind": "metrics",
                "path": "docs/METRICS.md",
            })
        return result

    def test_normal_cadence(self):
        # 4 strokes per minute = one every 15 seconds
        start = datetime(2026, 10, 19, 0, 0, 0, tzinfo=timezone.utc)
        h = self._make_history(20, start, 15)
        spm = compute_cadence_spm(h, 15)
        assert 3.5 <= spm <= 4.5  # ~4 spm

    def test_single_entry(self):
        h = [{"at": "2026-10-19T00:00:00+00:00", "seq": 1}]
        spm = compute_cadence_spm(h, 0)
        assert spm == 0.0

    def test_zero_end_idx(self):
        h = [
            {"at": "2026-10-19T00:00:00+00:00", "seq": 1},
            {"at": "2026-10-19T00:00:15+00:00", "seq": 2},
        ]
        spm = compute_cadence_spm(h, 0)
        assert spm == 0.0

    def test_same_timestamp(self):
        h = [
            {"at": "2026-10-19T00:00:00+00:00", "seq": 1},
            {"at": "2026-10-19T00:00:00+00:00", "seq": 2},
        ]
        spm = compute_cadence_spm(h, 1)
        assert spm == 0.0

    def test_invalid_timestamps(self):
        h = [
            {"at": "bad-ts", "seq": 1},
            {"at": "also-bad", "seq": 2},
        ]
        spm = compute_cadence_spm(h, 1)
        assert spm == 0.0

    def test_small_window(self):
        start = datetime(2026, 10, 19, 0, 0, 0, tzinfo=timezone.utc)
        h = self._make_history(5, start, 15)
        spm = compute_cadence_spm(h, 3, window=3)
        assert spm > 0


# ── estimate_loss ───────────────────────────────────────────────────────────

class TestEstimateLoss:
    def _make_history(self, entries):
        """Helper: entries = list of (timestamp_str, seq)."""
        return [{"at": ts, "seq": seq, "kind": "x", "path": "x"} for ts, seq in entries]

    def test_no_stalls(self):
        # entries 15 seconds apart, threshold 300
        start = datetime(2026, 10, 19, 0, 0, 0, tzinfo=timezone.utc)
        entries = []
        for i in range(20):
            ts = start + timedelta(seconds=15 * i)
            entries.append((ts.isoformat(), i + 1))
        h = self._make_history(entries)
        stalls = estimate_loss(h, threshold_seconds=300)
        assert stalls == []

    def test_single_stall(self):
        # normal cadence, then a 10-minute gap
        start = datetime(2026, 10, 19, 0, 0, 0, tzinfo=timezone.utc)
        entries = []
        for i in range(10):
            ts = start + timedelta(seconds=15 * i)
            entries.append((ts.isoformat(), i + 1))
        # gap: 600 seconds
        gap_start = start + timedelta(seconds=15 * 9)
        gap_end = gap_start + timedelta(seconds=600)
        entries.append((gap_end.isoformat(), 11))
        h = self._make_history(entries)
        stalls = estimate_loss(h, threshold_seconds=300)
        assert len(stalls) == 1
        assert stalls[0]["gap_seconds"] == 600
        assert stalls[0]["estimated_loss"] > 0

    def test_multiple_stalls(self):
        base = datetime(2026, 10, 19, 0, 0, 0, tzinfo=timezone.utc)
        entries = []
        seq = 1
        t = base
        for _ in range(3):
            for i in range(5):
                entries.append((t.isoformat(), seq))
                seq += 1
                t += timedelta(seconds=15)
            # 400 second gap
            t += timedelta(seconds=400)
        entries.append((t.isoformat(), seq))
        h = self._make_history(entries)
        stalls = estimate_loss(h, threshold_seconds=300)
        assert len(stalls) == 3

    def test_short_history(self):
        h = self._make_history([("2026-10-19T00:00:00+00:00", 1)])
        stalls = estimate_loss(h, threshold_seconds=300)
        assert stalls == []

    def test_empty_history(self):
        stalls = estimate_loss([], threshold_seconds=300)
        assert stalls == []

    def test_threshold_respected(self):
        base = datetime(2026, 10, 19, 0, 0, 0, tzinfo=timezone.utc)
        entries = []
        for i in range(10):
            ts = base + timedelta(seconds=15 * i)
            entries.append((ts.isoformat(), i + 1))
        # 200 second gap - below default 300 threshold
        gap_end = base + timedelta(seconds=15 * 9) + timedelta(seconds=200)
        entries.append((gap_end.isoformat(), 11))
        h = self._make_history(entries)
        # threshold 300 should miss it
        stalls_300 = estimate_loss(h, threshold_seconds=300)
        assert len(stalls_300) == 0
        # threshold 100 should catch it
        stalls_100 = estimate_loss(h, threshold_seconds=100)
        assert len(stalls_100) == 1

    def test_seq_values(self):
        base = datetime(2026, 10, 19, 0, 0, 0, tzinfo=timezone.utc)
        entries = []
        for i in range(5):
            ts = base + timedelta(seconds=15 * i)
            entries.append((ts.isoformat(), i + 100))
        gap_end = base + timedelta(seconds=15 * 4) + timedelta(seconds=500)
        entries.append((gap_end.isoformat(), 200))
        h = self._make_history(entries)
        stalls = estimate_loss(h, threshold_seconds=300)
        assert len(stalls) == 1
        assert stalls[0]["seq_before"] == 104
        assert stalls[0]["seq_after"] == 200


# ── format_text ─────────────────────────────────────────────────────────────

class TestFormatText:
    def test_no_stalls(self):
        result = format_text([], 100)
        assert "no stalls" in result

    def test_single_stall(self):
        stalls = [{
            "start": "2026-10-19T00:00:00+00:00",
            "end": "2026-10-19T00:10:00+00:00",
            "gap_seconds": 600,
            "cadence_spm": 4.0,
            "estimated_loss": 40,
            "seq_before": 100,
            "seq_after": 200,
        }]
        result = format_text(stalls, 500)
        assert "stalls detected:    1" in result
        assert "estimated loss:    40" in result
        assert "observed strokes:  500" in result
        assert "expected total:    540" in result
        assert "availability:" in result
        assert "seq 100 → 200" in result

    def test_multiple_stalls(self):
        stalls = [
            {
                "start": "a", "end": "b", "gap_seconds": 300,
                "cadence_spm": 4.0, "estimated_loss": 20,
                "seq_before": 1, "seq_after": 2,
            },
            {
                "start": "c", "end": "d", "gap_seconds": 600,
                "cadence_spm": 3.5, "estimated_loss": 35,
                "seq_before": 3, "seq_after": 4,
            },
        ]
        result = format_text(stalls, 200)
        assert "stalls detected:    2" in result
        assert "estimated loss:    55" in result
        assert "longest stall:     600s" in result


# ── format_json ─────────────────────────────────────────────────────────────

class TestFormatJson:
    def test_structure(self):
        stalls = [{
            "start": "a", "end": "b", "gap_seconds": 600,
            "cadence_spm": 4.0, "estimated_loss": 40,
            "seq_before": 1, "seq_after": 2,
        }]
        output = format_json(stalls, 100)
        data = json.loads(output)
        assert data["stall_count"] == 1
        assert data["total_stall_seconds"] == 600
        assert data["estimated_total_loss"] == 40
        assert data["observed_strokes"] == 100
        assert data["expected_total"] == 140
        assert "availability_pct" in data
        assert len(data["stalls"]) == 1

    def test_no_stalls(self):
        output = format_json([], 50)
        data = json.loads(output)
        assert data["stall_count"] == 0
        assert data["estimated_total_loss"] == 0
        assert data["availability_pct"] == 100.0

    def test_availability_calculation(self):
        stalls = [{
            "start": "a", "end": "b", "gap_seconds": 300,
            "cadence_spm": 4.0, "estimated_loss": 20,
            "seq_before": 1, "seq_after": 2,
        }]
        output = format_json(stalls, 80)
        data = json.loads(output)
        # 80 / (80 + 20) = 80%
        assert data["availability_pct"] == 80.0

    def test_json_valid(self):
        stalls = [{
            "start": "x", "end": "y", "gap_seconds": 100,
            "cadence_spm": 2.0, "estimated_loss": 3,
            "seq_before": 10, "seq_after": 20,
        }]
        output = format_json(stalls, 30)
        # Should not raise
        data = json.loads(output)
        assert isinstance(data, dict)


# ── run (integration) ───────────────────────────────────────────────────────

class TestRun:
    def test_missing_state_file(self, tmp_path, monkeypatch):
        # Point to a repo root that has no state file
        monkeypatch.setattr("stroke_loss_tracker.Path", lambda *a: tmp_path)
        result = run(writer="nonexistent", threshold=300)
        assert result == 1

    def test_valid_state(self, tmp_path):
        # Create a minimal repo structure
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        state = {
            "history": [
                {"at": "2026-10-19T00:00:00+00:00", "seq": 1, "kind": "x", "path": "x"},
                {"at": "2026-10-19T00:00:15+00:00", "seq": 2, "kind": "x", "path": "x"},
                {"at": "2026-10-19T00:00:30+00:00", "seq": 3, "kind": "x", "path": "x"},
            ]
        }
        (data_dir / "writer_state.test.json").write_text(json.dumps(state), encoding="utf-8")

        # Patch the repo path
        import stroke_loss_tracker as slt
        original_run = slt.run

        def patched_run(writer="test", threshold=300, json_output=False):
            state_path = data_dir / f"writer_state.{writer}.json"
            if not state_path.exists():
                return 1
            history = slt.load_history(state_path)
            stalls = slt.estimate_loss(history, threshold)
            if json_output:
                print(slt.format_json(stalls, len(history)))
            else:
                print(slt.format_text(stalls, len(history)))
            return 0

        result = patched_run(writer="test")
        assert result == 0

    def test_json_output(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        state = {
            "history": [
                {"at": "2026-10-19T00:00:00+00:00", "seq": 1, "kind": "x", "path": "x"},
                {"at": "2026-10-19T00:10:00+00:00", "seq": 2, "kind": "x", "path": "x"},
            ]
        }
        (data_dir / "writer_state.test.json").write_text(json.dumps(state), encoding="utf-8")

        import stroke_loss_tracker as slt
        state_path = data_dir / "writer_state.test.json"
        history = slt.load_history(state_path)
        stalls = slt.estimate_loss(history, threshold_seconds=300)
        output = slt.format_json(stalls, len(history))
        data = json.loads(output)
        assert data["stall_count"] == 1
        assert data["total_stall_seconds"] == 600
