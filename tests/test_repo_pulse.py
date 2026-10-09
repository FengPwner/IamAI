"""Tests for iamai.repo_pulse — repo health scoring.

Covers:
  - Pulse.score weighted composite
  - Pulse.healthy threshold
  - Pulse.summary format
  - score_writer_gap edge cases (fresh, stale, very stale)
  - score_commit_gap edge cases
  - score_push failure mode
  - _clamp01 boundary values
  - pulse() with overridden now and repo path
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.repo_pulse import (
    COMMIT_INTERVAL_S,
    SICK_THRESHOLD,
    WRITER_CADENCE_S,
    Pulse,
    _clamp01,
    pulse,
    score_commit_gap,
    score_push,
    score_writer_gap,
)


# ---------------------------------------------------------------------------
# _clamp01
# ---------------------------------------------------------------------------


class TestClamp:
    def test_within_range(self):
        assert _clamp01(0.5) == 0.5

    def test_below_zero(self):
        assert _clamp01(-0.3) == 0.0

    def test_above_one(self):
        assert _clamp01(1.7) == 1.0

    def test_zero(self):
        assert _clamp01(0.0) == 0.0

    def test_one(self):
        assert _clamp01(1.0) == 1.0


# ---------------------------------------------------------------------------
# score_writer_gap
# ---------------------------------------------------------------------------


class TestScoreWriterGap:
    def test_fresh_stroke(self):
        """A stroke that just happened scores 1.0."""
        assert score_writer_gap(0.0) == 1.0

    def test_within_cadence(self):
        """A stroke within one cadence period scores 1.0."""
        assert score_writer_gap(WRITER_CADENCE_S) == 1.0

    def test_half_cadence(self):
        """Half a cadence period is still fresh → 1.0."""
        assert score_writer_gap(WRITER_CADENCE_S * 0.5) == 1.0

    def test_double_cadence(self):
        """At 2× cadence the score decays to ~0.67."""
        s = score_writer_gap(WRITER_CADENCE_S * 2)
        assert 0.6 < s < 0.7

    def test_triple_cadence(self):
        """At 3× cadence the score is ~0.33."""
        s = score_writer_gap(WRITER_CADENCE_S * 3)
        assert 0.3 < s < 0.4

    def test_quad_cadence(self):
        """At 4× cadence the score hits 0."""
        assert score_writer_gap(WRITER_CADENCE_S * 4) == 0.0

    def test_beyond_quad(self):
        """Way past 4× cadence stays at 0."""
        assert score_writer_gap(WRITER_CADENCE_S * 100) == 0.0

    def test_custom_cadence(self):
        """Custom cadence overrides the default."""
        assert score_writer_gap(60.0, cadence_s=60.0) == 1.0


# ---------------------------------------------------------------------------
# score_commit_gap
# ---------------------------------------------------------------------------


class TestScoreCommitGap:
    def test_fresh_commit(self):
        assert score_commit_gap(0.0) == 1.0

    def test_within_interval(self):
        assert score_commit_gap(COMMIT_INTERVAL_S) == 1.0

    def test_double_interval(self):
        s = score_commit_gap(COMMIT_INTERVAL_S * 2)
        assert s == 0.5

    def test_triple_interval(self):
        assert score_commit_gap(COMMIT_INTERVAL_S * 3) == 0.0

    def test_beyond_triple(self):
        assert score_commit_gap(COMMIT_INTERVAL_S * 10) == 0.0


# ---------------------------------------------------------------------------
# score_push
# ---------------------------------------------------------------------------


class TestScorePush:
    def test_failed_push_zeroes_score(self):
        """A failed push always scores 0 regardless of recency."""
        assert score_push(0.0, ok=False) == 0.0

    def test_failed_push_old(self):
        assert score_push(COMMIT_INTERVAL_S * 5, ok=False) == 0.0

    def test_successful_push_fresh(self):
        assert score_push(0.0, ok=True) == 1.0

    def test_successful_push_double_interval(self):
        s = score_push(COMMIT_INTERVAL_S * 2, ok=True)
        assert s == 0.5


# ---------------------------------------------------------------------------
# Pulse dataclass
# ---------------------------------------------------------------------------


class TestPulse:
    def test_score_healthy(self):
        p = Pulse(writer_score=1.0, commit_score=1.0, push_score=1.0)
        assert p.score == 1.0
        assert p.healthy is True

    def test_score_sick(self):
        p = Pulse(writer_score=0.0, commit_score=0.0, push_score=0.0)
        assert p.score == 0.0
        assert p.healthy is False

    def test_score_boundary(self):
        """Exactly at threshold counts as healthy."""
        p = Pulse(writer_score=SICK_THRESHOLD, commit_score=SICK_THRESHOLD, push_score=SICK_THRESHOLD)
        assert p.score == pytest.approx(SICK_THRESHOLD)
        assert p.healthy is True

    def test_score_just_below_threshold(self):
        v = SICK_THRESHOLD - 0.01
        p = Pulse(writer_score=v, commit_score=v, push_score=v)
        assert p.healthy is False

    def test_summary_healthy(self):
        p = Pulse(
            writer_score=0.9,
            commit_score=0.8,
            push_score=1.0,
            writer_gap_s=5.0,
            commit_gap_s=120.0,
            push_gap_s=120.0,
            push_ok=True,
        )
        s = p.summary()
        assert "healthy" in s
        assert "writer=0.9" in s
        assert "push_ok" not in s  # push_ok is internal, not in summary text directly
        assert "ok=True" in s

    def test_summary_sick(self):
        p = Pulse(
            writer_score=0.1,
            commit_score=0.0,
            push_score=0.0,
            writer_gap_s=999.0,
            commit_gap_s=9999.0,
            push_gap_s=9999.0,
            push_ok=False,
        )
        s = p.summary()
        assert "SICK" in s

    def test_summary_with_detail(self):
        p = Pulse(detail=["no writer state found", "no commits found"])
        s = p.summary()
        assert "no writer state found" in s
        assert "no commits found" in s

    def test_score_weighting(self):
        """Verify the 50/30/20 weighting."""
        p = Pulse(writer_score=1.0, commit_score=0.0, push_score=0.0)
        assert p.score == pytest.approx(0.5)

        p2 = Pulse(writer_score=0.0, commit_score=1.0, push_score=0.0)
        assert p2.score == pytest.approx(0.3)

        p3 = Pulse(writer_score=0.0, commit_score=0.0, push_score=1.0)
        assert p3.score == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# pulse() integration (mocked git / filesystem)
# ---------------------------------------------------------------------------


class TestPulseIntegration:
    def test_pulse_with_fresh_state(self, tmp_path: Path):
        """pulse() with a fresh writer state and recent commit scores high."""
        # Create a fake repo with a commit
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "README.md").write_text("# test\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)

        # Create a fake writer state
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        from datetime import datetime, timezone
        now_ts = datetime.now(timezone.utc).timestamp()
        state = {
            "history": [
                {"at": datetime.now(timezone.utc).isoformat(), "kind": "thought", "path": "notes/test.md", "seq": 1}
            ],
            "seq": 2,
            "tally": {"thought": 1},
        }
        (data_dir / "writer_state.qwen.json").write_text(json.dumps(state))

        with patch("iamai.repo_pulse.REPO", tmp_path):
            p = pulse(now=now_ts + 10, repo=tmp_path)

        assert p.writer_score > 0.5
        assert p.commit_score > 0.5
        # push_ok will be False since no remote tracking ref
        assert isinstance(p.score, float)
        assert 0.0 <= p.score <= 1.0

    def test_pulse_with_stale_writer(self, tmp_path: Path):
        """pulse() with a very old writer state scores low on writer."""
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "README.md").write_text("# test\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # Writer state from 10 minutes ago
        from datetime import datetime, timezone, timedelta
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        state = {
            "history": [
                {"at": old_time, "kind": "thought", "path": "notes/test.md", "seq": 1}
            ],
            "seq": 2,
            "tally": {"thought": 1},
        }
        (data_dir / "writer_state.qwen.json").write_text(json.dumps(state))

        now_ts = datetime.now(timezone.utc).timestamp()
        with patch("iamai.repo_pulse.REPO", tmp_path):
            p = pulse(now=now_ts, repo=tmp_path)

        assert p.writer_score == 0.0  # 10 min = 600s, way past 4×15s=60s
        assert p.writer_gap_s > 500.0
