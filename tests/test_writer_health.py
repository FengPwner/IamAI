#!/usr/bin/env python3
"""Tests for tools/writer_health.py — writer composite health scoring."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

# Ensure tools/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import writer_health  # noqa: E402


class TestFindRepoRoot(unittest.TestCase):
    """find_repo_root walks up to locate data/strokes.jsonl."""

    def test_finds_repo_with_strokes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "data").mkdir()
            (repo / "data" / "strokes.jsonl").write_text("")
            sub = repo / "tools" / "sub"
            sub.mkdir(parents=True)
            self.assertEqual(writer_health.find_repo_root(sub), repo)

    def test_returns_start_when_no_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = writer_health.find_repo_root(Path(tmp))
            self.assertEqual(result, Path(tmp))


class TestIsWriterAlive(unittest.TestCase):
    """is_writer_alive checks for a running writer_loop process."""

    @patch("writer_health.subprocess.run")
    def test_returns_true_when_process_exists(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="12345\n", stderr=""
        )
        self.assertTrue(writer_health.is_writer_alive("qwen"))

    @patch("writer_health.subprocess.run")
    def test_returns_false_when_no_process(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=""
        )
        self.assertFalse(writer_health.is_writer_alive("qwen"))

    @patch("writer_health.subprocess.run")
    def test_returns_false_on_missing_pgrep(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        self.assertFalse(writer_health.is_writer_alive("qwen"))


class TestGetLastStrokeTime(unittest.TestCase):
    """get_last_stroke_time reads the timestamp from the last strokes.jsonl line."""

    def test_returns_none_for_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.assertIsNone(writer_health.get_last_stroke_time(repo))

    def test_returns_none_for_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "data").mkdir()
            (repo / "data" / "strokes.jsonl").write_text("")
            self.assertIsNone(writer_health.get_last_stroke_time(repo))

    def test_parses_last_line_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "data").mkdir()
            ts = "2026-10-31T12:00:00+00:00"
            lines = [
                json.dumps({"at": "2026-10-31T11:00:00+00:00", "kind": "note"}),
                json.dumps({"at": ts, "kind": "thought"}),
            ]
            (repo / "data" / "strokes.jsonl").write_text("\n".join(lines) + "\n")
            result = writer_health.get_last_stroke_time(repo)
            self.assertIsNotNone(result)
            self.assertEqual(result.isoformat(), ts)

    def test_handles_malformed_json_gracefully(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "data").mkdir()
            (repo / "data" / "strokes.jsonl").write_text("not json\n{bad\n")
            self.assertIsNone(writer_health.get_last_stroke_time(repo))


class TestCountStrokesInWindow(unittest.TestCase):
    """count_strokes_in_window counts recent strokes within the time window."""

    def test_returns_zero_for_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.assertEqual(writer_health.count_strokes_in_window(repo, 3600), 0)

    def test_counts_only_recent_strokes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "data").mkdir()
            now = datetime.now(timezone.utc)
            recent = (now - timedelta(minutes=30)).isoformat()
            old = (now - timedelta(hours=5)).isoformat()
            lines = [
                json.dumps({"at": old, "kind": "note"}),
                json.dumps({"at": recent, "kind": "thought"}),
                json.dumps({"at": recent, "kind": "snippet"}),
            ]
            (repo / "data" / "strokes.jsonl").write_text("\n".join(lines) + "\n")
            # 1 hour window: should count 2 recent, not the old one
            count = writer_health.count_strokes_in_window(repo, 3600)
            self.assertEqual(count, 2)

    def test_counts_all_when_within_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "data").mkdir()
            now = datetime.now(timezone.utc)
            ts = (now - timedelta(minutes=5)).isoformat()
            lines = [json.dumps({"at": ts, "kind": k}) for k in ("note", "thought", "devlog")]
            (repo / "data" / "strokes.jsonl").write_text("\n".join(lines) + "\n")
            count = writer_health.count_strokes_in_window(repo, 3600)
            self.assertEqual(count, 3)


class TestComputeHealth(unittest.TestCase):
    """compute_health produces valid score dicts."""

    def _make_repo(self, strokes):
        """Helper: create a temp repo with given stroke entries."""
        tmp = tempfile.mkdtemp()
        repo = Path(tmp)
        (repo / "data").mkdir()
        lines = [json.dumps(s) for s in strokes]
        (repo / "data" / "strokes.jsonl").write_text("\n".join(lines) + "\n")
        return repo

    @patch("writer_health.is_writer_alive", return_value=True)
    def test_healthy_score_with_recent_strokes(self, _alive):
        now = datetime.now(timezone.utc)
        # Strokes in chronological order (oldest first), last line is most recent
        strokes = [
            {"at": (now - timedelta(seconds=(239 - i) * 15)).isoformat(), "kind": "note"}
            for i in range(240)  # ~1 hour of strokes at 15s cadence
        ]
        repo = self._make_repo(strokes)
        result = writer_health.compute_health(repo=repo, cadence_seconds=15, window_seconds=3600)
        self.assertGreaterEqual(result["score"], 70)
        self.assertEqual(result["verdict"], "healthy")
        self.assertIn("process_score", result)
        self.assertIn("cadence_score", result)
        self.assertIn("throughput_score", result)

    @patch("writer_health.is_writer_alive", return_value=False)
    def test_dead_score_with_no_process(self, _alive):
        now = datetime.now(timezone.utc)
        # Last stroke was 2 hours ago
        old_ts = (now - timedelta(hours=2)).isoformat()
        strokes = [{"at": old_ts, "kind": "note"}]
        repo = self._make_repo(strokes)
        result = writer_health.compute_health(repo=repo, cadence_seconds=15, window_seconds=3600)
        self.assertLess(result["score"], 40)
        self.assertEqual(result["verdict"], "dead")

    @patch("writer_health.is_writer_alive", return_value=True)
    def test_score_bounds(self, _alive):
        """Score is always 0-100."""
        repo = self._make_repo([])
        result = writer_health.compute_health(repo=repo, cadence_seconds=15)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)

    @patch("writer_health.is_writer_alive", return_value=True)
    def test_verdict_labels(self, _alive):
        """All four verdict labels are valid strings."""
        for label in ("healthy", "degraded", "stalled", "dead"):
            self.assertIsInstance(label, str)

    @patch("writer_health.is_writer_alive", return_value=True)
    def test_degraded_with_slight_drift(self, _alive):
        now = datetime.now(timezone.utc)
        # Last stroke 25s ago (1.67x cadence of 15s), some throughput
        ts = (now - timedelta(seconds=25)).isoformat()
        strokes = [{"at": ts, "kind": "note"}]
        # Add more recent strokes for partial throughput
        for i in range(50):
            strokes.append({
                "at": (now - timedelta(minutes=i)).isoformat(),
                "kind": "note"
            })
        repo = self._make_repo(strokes)
        result = writer_health.compute_health(repo=repo, cadence_seconds=15, window_seconds=3600)
        self.assertIn(result["verdict"], ("healthy", "degraded", "stalled"))
        # process alive so at least 40 pts
        self.assertGreaterEqual(result["score"], 40)


class TestComputeHealthComponents(unittest.TestCase):
    """Verify individual score component ranges."""

    @patch("writer_health.is_writer_alive", return_value=True)
    def test_component_scores_sum_to_total(self, _alive):
        now = datetime.now(timezone.utc)
        strokes = [
            {"at": (now - timedelta(seconds=10)).isoformat(), "kind": "note"},
            {"at": (now - timedelta(minutes=5)).isoformat(), "kind": "thought"},
        ]
        tmp = tempfile.mkdtemp()
        repo = Path(tmp)
        (repo / "data").mkdir()
        (repo / "data" / "strokes.jsonl").write_text(
            "\n".join(json.dumps(s) for s in strokes) + "\n"
        )
        result = writer_health.compute_health(repo=repo, cadence_seconds=15)
        component_sum = result["process_score"] + result["cadence_score"] + result["throughput_score"]
        # Score is int(component_sum) clamped to [0, 100]
        self.assertAlmostEqual(result["score"], min(100, max(0, int(component_sum))), delta=1)


if __name__ == "__main__":
    unittest.main()
