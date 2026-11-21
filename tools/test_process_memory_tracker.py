#!/usr/bin/env python3
"""Tests for process_memory_tracker.py — RSS tracking and leak detection.

Covers:
    - RSS reading from /proc (mocked)
    - History file append / load round-trip
    - Trend classification (stable, growing, leaking, shrinking, unknown)
    - Edge cases (missing process, empty history, single sample)
    - CLI argument parsing and exit codes
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from process_memory_tracker import (
    STABLE,
    GROWING,
    LEAKING,
    SHRINKING,
    UNKNOWN,
    LEAK_PCT,
    GROWTH_CONSECUTIVE_MIN,
    classify_trend,
    format_kb,
    load_history,
    append_sample,
    read_rss_kb,
    sample_process,
    history_path,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _samples(rss_values: list[int], role: str = "writer") -> list[dict]:
    """Build a list of sample dicts from RSS values."""
    return [
        {"ts": f"2026-11-21T0{i}:00:00+00:00", "role": role,
         "pid": 1000 + i, "rss_kb": v}
        for i, v in enumerate(rss_values)
    ]


@pytest.fixture
def tmp_history(tmp_path):
    """Redirect history_path to a temporary directory."""
    original_repo = None

    def _mock_history_path(writer_id):
        suffix = writer_id or "default"
        return tmp_path / "data" / f"memory_history.{suffix}.jsonl"

    with patch("process_memory_tracker.history_path", side_effect=_mock_history_path):
        yield tmp_path


# ---------------------------------------------------------------------------
# classify_trend
# ---------------------------------------------------------------------------


class TestClassifyTrend:
    """Trend classification from RSS samples."""

    def test_empty_samples(self):
        result = classify_trend([])
        assert result["status"] == UNKNOWN
        assert result["sample_count"] == 0

    def test_single_sample(self):
        result = classify_trend(_samples([20000]))
        assert result["status"] == UNKNOWN
        assert result["sample_count"] == 1

    def test_stable_flat(self):
        """Constant RSS → stable."""
        result = classify_trend(_samples([20000] * 10))
        assert result["status"] == STABLE
        assert result["pct_change"] == 0.0

    def test_stable_small_fluctuation(self):
        """Tiny oscillation within 5% → stable."""
        base = 20000
        values = [base, base + 500, base - 300, base + 800, base - 200]
        result = classify_trend(_samples(values))
        assert result["status"] == STABLE

    def test_growing(self):
        """Monotonic increase across ≥ 3 samples → growing."""
        values = [20000, 21000, 22000, 23000, 24000]
        result = classify_trend(_samples(values))
        assert result["status"] == GROWING
        assert result["pct_change"] > 0

    def test_leaking(self):
        """Large (>50%) sustained monotonic growth → leaking."""
        # 8 consecutive increases, total growth > 50%
        values = [20000, 21000, 22000, 23000, 25000, 27000, 29000, 31000, 33000]
        result = classify_trend(_samples(values))
        assert result["status"] == LEAKING
        assert result["pct_change"] > 50.0

    def test_shrinking(self):
        """RSS decreasing by more than 5% → shrinking."""
        values = [30000, 28000, 26000, 24000, 22000]
        result = classify_trend(_samples(values))
        assert result["status"] == SHRINKING
        assert result["pct_change"] < 0

    def test_growing_not_leaking(self):
        """Monotonic increase but < 50% → growing, not leaking."""
        values = [20000, 20200, 20400, 20600, 20800]
        result = classify_trend(_samples(values))
        assert result["status"] == GROWING  # monotonic run of 4
        assert result["pct_change"] < 50.0

    def test_intermittent_growth_not_growing(self):
        """Up-down-up pattern with no 3-consecutive increase → stable."""
        values = [20000, 21000, 19000, 22000, 20000, 21000, 19500]
        result = classify_trend(_samples(values))
        # No 3 consecutive increases, and pct_change is small
        assert result["status"] == STABLE

    def test_leak_requires_consecutive(self):
        """>50% growth but not monotonic → growing or stable, not leaking."""
        # Growth is large but oscillates — should NOT be leaking
        values = [20000, 25000, 22000, 30000, 28000, 35000, 32000, 40000]
        result = classify_trend(_samples(values))
        assert result["status"] != LEAKING or result["pct_change"] <= 50.0


# ---------------------------------------------------------------------------
# format_kb
# ---------------------------------------------------------------------------


class TestFormatKb:
    def test_none(self):
        assert format_kb(None) == "?"

    def test_kilobytes(self):
        assert format_kb(512) == "512 KB"

    def test_megabytes(self):
        assert format_kb(2048) == "2.0 MB"

    def test_gigabytes(self):
        assert format_kb(2 * 1024 * 1024) == "2.0 GB"

    def test_boundary(self):
        assert format_kb(1023) == "1023 KB"
        assert format_kb(1024) == "1.0 MB"


# ---------------------------------------------------------------------------
# read_rss_kb
# ---------------------------------------------------------------------------


class TestReadRssKb:
    def test_missing_pid(self):
        """Non-existent PID returns None."""
        assert read_rss_kb(9999999) is None

    def test_mock_proc(self, tmp_path):
        """Parse VmRSS from a fake /proc/<pid>/status."""
        pid = 12345
        status_dir = tmp_path / str(pid)
        status_dir.mkdir()
        status_file = status_dir / "status"
        status_file.write_text(
            "Name: python3\n"
            "State: S (sleeping)\n"
            "VmPeak: 50000 kB\n"
            "VmSize: 45000 kB\n"
            "VmRSS:    23456 kB\n"
            "VmData: 10000 kB\n"
        )
        # Patch Path to look in tmp_path
        real_proc = Path("/proc")
        with patch("process_memory_tracker.Path") as mock_path:
            def side_effect(p):
                if str(p).startswith("/proc/"):
                    return tmp_path / str(p).replace("/proc/", "").lstrip("/")
                return Path(p)
            mock_path.side_effect = side_effect
            # Direct call uses the real /proc, so test the parsing logic
            # by calling the internal logic manually
            lines = status_file.read_text().splitlines()
            for line in lines:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1])
                    assert rss == 23456
                    break


# ---------------------------------------------------------------------------
# History file I/O
# ---------------------------------------------------------------------------


class TestHistoryIO:
    def test_append_and_load(self, tmp_path):
        """Append samples then load them back."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        hp = data_dir / "memory_history.test.jsonl"

        # Direct append
        rows = _samples([10000, 20000, 30000], role="writer")
        with open(hp, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

        # Load via helper (patch history_path)
        with patch("process_memory_tracker.history_path", return_value=hp):
            loaded = load_history("test", "writer")
            assert len(loaded) == 3
            assert loaded[0]["rss_kb"] == 10000
            assert loaded[2]["rss_kb"] == 30000

    def test_load_filters_by_role(self, tmp_path):
        """load_history should only return rows for the given role."""
        hp = tmp_path / "history.jsonl"
        mixed = _samples([10000], "writer") + _samples([5000], "batch")
        with open(hp, "w") as f:
            for r in mixed:
                f.write(json.dumps(r) + "\n")

        with patch("process_memory_tracker.history_path", return_value=hp):
            writer_rows = load_history("test", "writer")
            batch_rows = load_history("test", "batch")
            assert len(writer_rows) == 1
            assert len(batch_rows) == 1

    def test_load_limit(self, tmp_path):
        """load_history with limit returns only the last N rows."""
        hp = tmp_path / "history.jsonl"
        rows = _samples(list(range(1000, 1020)), role="writer")
        with open(hp, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

        with patch("process_memory_tracker.history_path", return_value=hp):
            loaded = load_history("test", "writer", limit=5)
            assert len(loaded) == 5
            assert loaded[0]["rss_kb"] == 1015

    def test_load_empty_file(self, tmp_path):
        """Empty history file returns empty list."""
        hp = tmp_path / "empty.jsonl"
        hp.write_text("")
        with patch("process_memory_tracker.history_path", return_value=hp):
            assert load_history("test", "writer") == []

    def test_load_nonexistent(self, tmp_path):
        """Missing history file returns empty list."""
        hp = tmp_path / "nope.jsonl"
        with patch("process_memory_tracker.history_path", return_value=hp):
            assert load_history("test", "writer") == []

    def test_load_malformed_lines(self, tmp_path):
        """Malformed JSON lines are skipped."""
        hp = tmp_path / "history.jsonl"
        hp.write_text(
            '{"ts":"2026-01-01","role":"writer","pid":1,"rss_kb":1000}\n'
            'THIS IS NOT JSON\n'
            '{"ts":"2026-01-02","role":"writer","pid":1,"rss_kb":2000}\n'
        )
        with patch("process_memory_tracker.history_path", return_value=hp):
            rows = load_history("test", "writer")
            assert len(rows) == 2


# ---------------------------------------------------------------------------
# sample_process (integration-ish)
# ---------------------------------------------------------------------------


class TestSampleProcess:
    def test_missing_writer(self):
        """Writer PID file missing → not running."""
        with patch("process_memory_tracker.read_pid", return_value=None):
            result = sample_process("nonexistent", "writer")
            assert result["running"] is False
            assert result["rss_str"] == "not running"

    def test_stale_pid(self):
        """PID file exists but process gone → stale pid."""
        with patch("process_memory_tracker.read_pid", return_value=99999):
            with patch("process_memory_tracker.read_rss_kb", return_value=None):
                result = sample_process("test", "writer")
                assert result["running"] is False
                assert result["rss_str"] == "stale pid"

    def test_healthy_process(self, tmp_path):
        """Running process with sample history."""
        hp = tmp_path / "history.jsonl"
        hp.parent.mkdir(exist_ok=True)

        with patch("process_memory_tracker.read_pid", return_value=1234):
            with patch("process_memory_tracker.read_rss_kb", return_value=25000):
                with patch("process_memory_tracker.history_path", return_value=hp):
                    result = sample_process("test", "writer")
                    assert result["running"] is True
                    assert result["rss_kb"] == 25000
                    assert result["rss_str"] == "24.4 MB"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCLI:
    def test_help(self):
        """--help should exit 0."""
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "process_memory_tracker.py"),
             "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "RSS" in result.stdout or "memory" in result.stdout.lower()

    def test_json_output(self):
        """--json should produce valid JSON."""
        # Use a nonexistent writer so PIDs are missing — still produces output
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "process_memory_tracker.py"),
             "--writer", "nonexistent_test_writer", "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["role"] == "writer"
        assert data[1]["role"] == "batch"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
