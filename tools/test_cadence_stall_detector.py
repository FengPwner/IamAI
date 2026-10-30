#!/usr/bin/env python3
"""Tests for cadence_stall_detector.py"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Ensure tools/ is importable
sys.path.insert(0, str(Path(__file__).parent))
from cadence_stall_detector import (
    get_last_stroke_time,
    get_configured_cadence,
    detect_stall,
)


def make_repo(strokes: list[dict] | None = None, state: dict | None = None) -> Path:
    """Create a temporary repo structure with given strokes and state."""
    tmpdir = Path(tempfile.mkdtemp())
    data_dir = tmpdir / "data"
    data_dir.mkdir()

    if strokes is not None:
        with open(data_dir / "strokes.jsonl", "w") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")

    if state is not None:
        with open(data_dir / "writer_state.qwen.json", "w") as f:
            json.dump(state, f)

    return tmpdir


class TestGetLastStrokeTime(unittest.TestCase):
    def test_empty_repo(self):
        repo = make_repo()
        self.assertIsNone(get_last_stroke_time(repo))

    def test_single_stroke(self):
        ts = "2026-10-30T12:00:00+00:00"
        repo = make_repo(strokes=[{"seq": 1, "at": ts, "kind": "thought", "text": "hello"}])
        result = get_last_stroke_time(repo)
        self.assertIsNotNone(result)
        self.assertEqual(result.isoformat(), ts)

    def test_multiple_strokes_returns_last(self):
        strokes = [
            {"seq": 1, "at": "2026-10-30T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"seq": 2, "at": "2026-10-30T11:00:00+00:00", "kind": "thought", "text": "b"},
            {"seq": 3, "at": "2026-10-30T12:00:00+00:00", "kind": "thought", "text": "c"},
        ]
        repo = make_repo(strokes=strokes)
        result = get_last_stroke_time(repo)
        self.assertEqual(result.isoformat(), "2026-10-30T12:00:00+00:00")

    def test_no_strokes_file(self):
        repo = make_repo()
        self.assertIsNone(get_last_stroke_time(repo))

    def test_trailing_newline(self):
        repo = make_repo(strokes=[{"seq": 1, "at": "2026-10-30T12:00:00+00:00", "kind": "thought", "text": "x"}])
        # Append trailing newline
        with open(repo / "data" / "strokes.jsonl", "a") as f:
            f.write("\n")
        result = get_last_stroke_time(repo)
        self.assertIsNotNone(result)

    def test_empty_file(self):
        repo = make_repo()
        (repo / "data" / "strokes.jsonl").write_text("")
        self.assertIsNone(get_last_stroke_time(repo))

    def test_malformed_last_line(self):
        repo = make_repo()
        with open(repo / "data" / "strokes.jsonl", "w") as f:
            f.write("not json\n")
        self.assertIsNone(get_last_stroke_time(repo))


class TestGetConfiguredCadence(unittest.TestCase):
    def test_no_state_file(self):
        repo = make_repo()
        self.assertIsNone(get_configured_cadence(repo))

    def test_cadence_in_root(self):
        repo = make_repo(state={"cadence": 15})
        self.assertEqual(get_configured_cadence(repo), 15)

    def test_cadence_in_config(self):
        repo = make_repo(state={"config": {"cadence": 30}})
        self.assertEqual(get_configured_cadence(repo), 30)

    def test_cadence_inferred_from_history(self):
        state = {
            "history": [
                {"at": "2026-10-30T12:00:00+00:00", "kind": "thought"},
                {"at": "2026-10-30T12:00:20+00:00", "kind": "thought"},
            ]
        }
        repo = make_repo(state=state)
        self.assertEqual(get_configured_cadence(repo), 20)

    def test_cadence_empty_history(self):
        repo = make_repo(state={"history": []})
        self.assertIsNone(get_configured_cadence(repo))

    def test_malformed_state(self):
        repo = make_repo()
        (repo / "data" / "writer_state.qwen.json").write_text("not json")
        self.assertIsNone(get_configured_cadence(repo))


class TestDetectStall(unittest.TestCase):
    def _now(self, base: str, seconds_later: float) -> datetime:
        return datetime.fromisoformat(base) + timedelta(seconds=seconds_later)

    def test_no_stall(self):
        ts = "2026-10-30T12:00:00+00:00"
        repo = make_repo(
            strokes=[{"seq": 1, "at": ts, "kind": "thought", "text": "x"}],
            state={"cadence": 15},
        )
        now = self._now(ts, 10)  # 10s later, within 2x cadence
        result = detect_stall(repo=repo, now=now)
        self.assertEqual(result["status"], "none")
        self.assertEqual(result["exit_code"], 0)

    def test_mild_stall(self):
        ts = "2026-10-30T12:00:00+00:00"
        repo = make_repo(
            strokes=[{"seq": 1, "at": ts, "kind": "thought", "text": "x"}],
            state={"cadence": 15},
        )
        now = self._now(ts, 45)  # 45s = 3x cadence → mild
        result = detect_stall(repo=repo, now=now)
        self.assertEqual(result["status"], "mild")
        self.assertEqual(result["exit_code"], 1)
        self.assertAlmostEqual(result["gap_ratio"], 3.0, places=1)

    def test_severe_stall(self):
        ts = "2026-10-30T12:00:00+00:00"
        repo = make_repo(
            strokes=[{"seq": 1, "at": ts, "kind": "thought", "text": "x"}],
            state={"cadence": 15},
        )
        now = self._now(ts, 120)  # 120s = 8x cadence → severe
        result = detect_stall(repo=repo, now=now)
        self.assertEqual(result["status"], "severe")
        self.assertEqual(result["exit_code"], 2)

    def test_boundary_exactly_2x(self):
        ts = "2026-10-30T12:00:00+00:00"
        repo = make_repo(
            strokes=[{"seq": 1, "at": ts, "kind": "thought", "text": "x"}],
            state={"cadence": 15},
        )
        now = self._now(ts, 30)  # exactly 2x → mild
        result = detect_stall(repo=repo, now=now)
        self.assertEqual(result["status"], "mild")

    def test_boundary_exactly_5x(self):
        ts = "2026-10-30T12:00:00+00:00"
        repo = make_repo(
            strokes=[{"seq": 1, "at": ts, "kind": "thought", "text": "x"}],
            state={"cadence": 15},
        )
        now = self._now(ts, 75)  # exactly 5x → severe
        result = detect_stall(repo=repo, now=now)
        self.assertEqual(result["status"], "severe")

    def test_cadence_override(self):
        ts = "2026-10-30T12:00:00+00:00"
        repo = make_repo(
            strokes=[{"seq": 1, "at": ts, "kind": "thought", "text": "x"}],
            state={"cadence": 15},
        )
        now = self._now(ts, 90)  # 90s / 60s override = 1.5x → no stall
        result = detect_stall(repo=repo, cadence_override=60, now=now)
        self.assertEqual(result["status"], "none")
        self.assertEqual(result["cadence_seconds"], 60)

    def test_unknown_no_data(self):
        repo = make_repo()
        result = detect_stall(repo=repo)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["exit_code"], 3)

    def test_json_output_fields(self):
        ts = "2026-10-30T12:00:00+00:00"
        repo = make_repo(
            strokes=[{"seq": 1, "at": ts, "kind": "thought", "text": "x"}],
            state={"cadence": 15},
        )
        now = self._now(ts, 10)
        result = detect_stall(repo=repo, now=now)
        for key in ["status", "exit_code", "last_stroke", "gap_seconds",
                     "cadence_seconds", "gap_ratio", "checked_at"]:
            self.assertIn(key, result)

    def test_large_strokes_file(self):
        """Performance: 10000 strokes should still work."""
        strokes = [
            {"seq": i, "at": f"2026-10-30T{12 + i // 3600:02d}:{(i % 3600) // 60:02d}:{i % 60:02d}+00:00",
             "kind": "thought", "text": f"stroke {i}"}
            for i in range(10000)
        ]
        repo = make_repo(strokes=strokes, state={"cadence": 15})
        result = detect_stall(repo=repo)
        self.assertIn(result["status"], ["none", "mild", "severe", "unknown"])

    def test_default_cadence_fallback(self):
        ts = "2026-10-30T12:00:00+00:00"
        repo = make_repo(
            strokes=[{"seq": 1, "at": ts, "kind": "thought", "text": "x"}],
            # No cadence configured
        )
        now = self._now(ts, 25)  # 25s / 15s default = 1.67x → no stall
        result = detect_stall(repo=repo, now=now)
        self.assertEqual(result["cadence_seconds"], 15)
        self.assertEqual(result["status"], "none")


if __name__ == "__main__":
    unittest.main()
